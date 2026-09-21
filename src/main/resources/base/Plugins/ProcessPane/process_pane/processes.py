from dataclasses import dataclass
from contextlib import contextmanager
from functools import lru_cache
from threading import Lock

import ntpath
import os
import re
import sys


@dataclass(frozen=True)
class ProcessRecord:

	pid: int
	name: str
	created: int | None

	def path(self, generation):
		name = re.sub(r'[/\\~\x00-\x1f\x7f]', '_', self.name).strip('.') or 'Process'
		identity = format(self.created, 'x') if self.created is not None else 'unknown-%d' % generation
		return '%s~%d~%s' % (name, self.pid, identity)


class Snapshot:

	def __init__(self):
		self._records = {}
		self._generation = 0
		self._lock = Lock()
		self._refresh_lock = Lock()

	def refresh(self, enumerate_processes):
		return tuple(path for path, record in self.capture(enumerate_processes))

	def capture(self, enumerate_processes):
		with self._refresh_lock:
			records = tuple(enumerate_processes())
			with self._lock:
				self._generation += 1
				self._records = {record.path(self._generation): record for record in records}
				return tuple(self._records.items())

	def get(self, path):
		with self._lock:
			try:
				return self._records[path]
			except KeyError:
				raise FileNotFoundError('Process list changed. Refresh and select the process again.') from None


class ProcessError(Exception):
	pass


@lru_cache(maxsize=1)
def get_provider():
	if sys.platform != 'win32':
		raise ProcessError('Process Pane is available on Windows only.')
	try:
		from win32process import EnumProcesses
	except ImportError as error:
		raise ProcessError('Process Pane requires pywin32 compatible with this Python runtime. Use an application package that includes pywin32.') from error
	return ProcessProvider(EnumProcesses, WindowsApi())


class ProcessProvider:

	def __init__(self, enumerate_pids, api):
		self.enumerate_pids = enumerate_pids
		self.api = api

	def snapshot(self):
		for pid in self.enumerate_pids():
			if pid == 0:
				yield ProcessRecord(pid, 'System Idle Process', None)
				continue
			try:
				with self.api.open(pid, 0x1000) as handle:
					created = self.api.creation_time(handle)
					name = ntpath.basename(self.api.image_name(handle))
			except OSError as error:
				if getattr(error, 'winerror', None) == 87:
					continue
				created = None
				name = 'System' if pid == 4 else 'Unavailable'
			yield ProcessRecord(pid, name, created)

	def end(self, record, check_canceled):
		if record.pid in (0, 4, os.getpid()) or record.created is None:
			raise ProcessError('This process cannot be ended safely (system, self, or unverified identity).')
		try:
			with self.api.open(record.pid, 0x1001) as handle:
				if self.api.creation_time(handle) != record.created:
					raise ProcessError('The process has changed or exited. Refresh and select it again.')
				try:
					critical = self.api.is_critical(handle)
				except OSError as error:
					raise ProcessError('Could not verify process safety; termination was refused.') from error
				if critical:
					raise ProcessError('Critical system processes cannot be ended.')
				check_canceled()
				self.api.terminate(handle)
		except OSError as error:
			code = getattr(error, 'winerror', None)
			if code == 5:
				message = 'Access denied; Windows permissions may not allow this operation, or the process may already be exiting. Refresh the list.'
			elif code == 87:
				message = 'The process has already exited. Refresh the list.'
			else:
				message = 'Could not end the process: %s' % error
			raise ProcessError(message) from error


class WindowsApi:

	def __init__(self):
		import ctypes
		from ctypes import wintypes
		self.ctypes = ctypes
		self.types = wintypes
		self.kernel = ctypes.WinDLL('kernel32', use_last_error=True)
		pointer = ctypes.POINTER
		for name, args, result in (
			('OpenProcess', [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD], wintypes.HANDLE),
			('CloseHandle', [wintypes.HANDLE], wintypes.BOOL),
			('GetProcessTimes', [wintypes.HANDLE] + [pointer(wintypes.FILETIME)] * 4, wintypes.BOOL),
			('QueryFullProcessImageNameW', [wintypes.HANDLE, wintypes.DWORD, wintypes.LPWSTR, pointer(wintypes.DWORD)], wintypes.BOOL),
			('IsProcessCritical', [wintypes.HANDLE, pointer(wintypes.BOOL)], wintypes.BOOL),
			('TerminateProcess', [wintypes.HANDLE, wintypes.UINT], wintypes.BOOL),
		):
			try:
				function = getattr(self.kernel, name)
			except AttributeError as error:
				raise ProcessError('Process Pane requires Windows 8.1 or newer with %s support.' % name) from error
			function.argtypes = args
			function.restype = result

	def _require(self, result):
		if not result:
			raise self.ctypes.WinError(self.ctypes.get_last_error())
		return result

	@contextmanager
	def open(self, pid, access):
		handle = self._require(self.kernel.OpenProcess(access, False, pid))
		try:
			yield handle
		finally:
			self.kernel.CloseHandle(handle)

	def creation_time(self, handle):
		times = [self.types.FILETIME() for index in range(4)]
		self._require(self.kernel.GetProcessTimes(handle, *(self.ctypes.byref(value) for value in times)))
		return (times[0].dwHighDateTime << 32) | times[0].dwLowDateTime

	def image_name(self, handle):
		length = self.types.DWORD(32768)
		buffer = self.ctypes.create_unicode_buffer(length.value)
		self._require(self.kernel.QueryFullProcessImageNameW(handle, 0, buffer, self.ctypes.byref(length)))
		return buffer.value

	def is_critical(self, handle):
		critical = self.types.BOOL()
		self._require(self.kernel.IsProcessCritical(handle, self.ctypes.byref(critical)))
		return bool(critical.value)

	def terminate(self, handle):
		self._require(self.kernel.TerminateProcess(handle, 1))