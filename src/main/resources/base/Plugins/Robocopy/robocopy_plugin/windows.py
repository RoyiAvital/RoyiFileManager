"""Lazy Windows process ownership; no Qt or third-party imports."""

import ctypes
from ctypes import wintypes
from functools import cache
import os
import re
import subprocess
from threading import Event, Lock, Thread
from time import monotonic


class Canceled(Exception):
	pass


class SecurityAttributes(ctypes.Structure):
	_fields_ = [('length', wintypes.DWORD), ('descriptor', ctypes.c_void_p), ('inherit', wintypes.BOOL)]


class StartupInfo(ctypes.Structure):
	_fields_ = [('cb', wintypes.DWORD), ('reserved', wintypes.LPWSTR), ('desktop', wintypes.LPWSTR),
		('title', wintypes.LPWSTR), ('x', wintypes.DWORD), ('y', wintypes.DWORD),
		('xsize', wintypes.DWORD), ('ysize', wintypes.DWORD), ('xchars', wintypes.DWORD),
		('ychars', wintypes.DWORD), ('fill', wintypes.DWORD), ('flags', wintypes.DWORD),
		('show', wintypes.WORD), ('reserved_size', wintypes.WORD), ('reserved_bytes', ctypes.c_void_p),
		('stdin', wintypes.HANDLE), ('stdout', wintypes.HANDLE), ('stderr', wintypes.HANDLE)]


class StartupInfoEx(ctypes.Structure):
	_fields_ = [('startup', StartupInfo), ('attributes', ctypes.c_void_p)]


class ProcessInfo(ctypes.Structure):
	_fields_ = [('process', wintypes.HANDLE), ('thread', wintypes.HANDLE),
		('pid', wintypes.DWORD), ('tid', wintypes.DWORD)]


class BasicLimits(ctypes.Structure):
	_fields_ = [('process_time', ctypes.c_longlong), ('job_time', ctypes.c_longlong),
		('flags', wintypes.DWORD), ('minimum', ctypes.c_size_t), ('maximum', ctypes.c_size_t),
		('active', wintypes.DWORD), ('affinity', ctypes.c_size_t),
		('priority', wintypes.DWORD), ('scheduling', wintypes.DWORD)]


class IoCounters(ctypes.Structure):
	_fields_ = [(name, ctypes.c_ulonglong) for name in
		('read_ops', 'write_ops', 'other_ops', 'read_bytes', 'write_bytes', 'other_bytes')]


class ExtendedLimits(ctypes.Structure):
	_fields_ = [('basic', BasicLimits), ('io', IoCounters), ('process_memory', ctypes.c_size_t),
		('job_memory', ctypes.c_size_t), ('peak_process', ctypes.c_size_t), ('peak_job', ctypes.c_size_t)]


class FindData(ctypes.Structure):
	_fields_ = [('attributes', wintypes.DWORD), ('created', wintypes.FILETIME),
		('accessed', wintypes.FILETIME), ('modified', wintypes.FILETIME),
		('size_high', wintypes.DWORD), ('size_low', wintypes.DWORD),
		('reserved0', wintypes.DWORD), ('reserved1', wintypes.DWORD),
		('name', wintypes.WCHAR * 260), ('alternate', wintypes.WCHAR * 14)]


@cache
def api():
	if os.name != 'nt':
		raise OSError('Robocopy requires Windows.')
	library = ctypes.WinDLL('kernel32', use_last_error=True)
	handle, pointer, dword = wintypes.HANDLE, ctypes.c_void_p, wintypes.DWORD
	for name, arguments, result in (
		('GetSystemDirectoryW', [wintypes.LPWSTR, wintypes.UINT], wintypes.UINT),
		('CreateJobObjectW', [pointer, wintypes.LPCWSTR], handle),
		('SetInformationJobObject', [handle, ctypes.c_int, pointer, dword], wintypes.BOOL),
		('AssignProcessToJobObject', [handle, handle], wintypes.BOOL),
		('TerminateJobObject', [handle, wintypes.UINT], wintypes.BOOL),
		('CreatePipe', [ctypes.POINTER(handle), ctypes.POINTER(handle), pointer, dword], wintypes.BOOL),
		('SetHandleInformation', [handle, dword, dword], wintypes.BOOL),
		('CreateFileW', [wintypes.LPCWSTR, dword, dword, pointer, dword, dword, handle], handle),
		('InitializeProcThreadAttributeList', [pointer, dword, dword, ctypes.POINTER(ctypes.c_size_t)], wintypes.BOOL),
		('UpdateProcThreadAttribute', [pointer, dword, ctypes.c_size_t, pointer, ctypes.c_size_t, pointer, pointer], wintypes.BOOL),
		('DeleteProcThreadAttributeList', [pointer], None),
		('CreateProcessW', [wintypes.LPCWSTR, wintypes.LPWSTR, pointer, pointer, wintypes.BOOL,
			dword, pointer, wintypes.LPCWSTR, pointer, ctypes.POINTER(ProcessInfo)], wintypes.BOOL),
		('ResumeThread', [handle], dword),
		('TerminateProcess', [handle, wintypes.UINT], wintypes.BOOL),
		('WaitForSingleObject', [handle, dword], dword),
		('GetExitCodeProcess', [handle, ctypes.POINTER(dword)], wintypes.BOOL),
		('ReadFile', [handle, pointer, dword, ctypes.POINTER(dword), pointer], wintypes.BOOL),
		('PeekNamedPipe', [handle, pointer, dword, pointer, ctypes.POINTER(dword), pointer], wintypes.BOOL),
		('CloseHandle', [handle], wintypes.BOOL),
		('GetFileInformationByHandleEx', [handle, ctypes.c_int, pointer, dword], wintypes.BOOL),
		('FindFirstFileW', [wintypes.LPCWSTR, ctypes.POINTER(FindData)], handle),
		('FindNextFileW', [handle, ctypes.POINTER(FindData)], wintypes.BOOL),
		('FindClose', [handle], wintypes.BOOL),
	):
		function = getattr(library, name)
		function.argtypes, function.restype = arguments, result
	return library


def checked(success):
	if not success:
		raise ctypes.WinError(ctypes.get_last_error())
	return success


def executable():
	library = api()
	buffer = ctypes.create_unicode_buffer(32768)
	length = library.GetSystemDirectoryW(buffer, len(buffer))
	checked(length)
	if length >= len(buffer):
		raise OSError('Windows system directory is too long.')
	path = os.path.join(buffer.value, 'robocopy.exe')
	if not os.path.isfile(path):
		raise FileNotFoundError('Windows robocopy.exe was not found.')
	return path


def case_sensitive(path):
	library = api()
	handle = library.CreateFileW(path, 0x80, 7, None, 3, 0x02000000, None)
	if handle == ctypes.c_void_p(-1).value:
		raise ctypes.WinError(ctypes.get_last_error())
	try:
		flags = wintypes.DWORD()
		if not library.GetFileInformationByHandleEx(handle, 23, ctypes.byref(flags), ctypes.sizeof(flags)):
			code = ctypes.get_last_error()
			if code in (1, 50, 87):
				return None
			raise ctypes.WinError(code)
		return bool(flags.value & 1)
	finally:
		library.CloseHandle(handle)


def filenames(path, check=lambda: None):
	library = api()
	data = FindData()
	check()
	handle = library.FindFirstFileW(os.path.join(path, '*'), ctypes.byref(data))
	if handle == ctypes.c_void_p(-1).value:
		raise ctypes.WinError(ctypes.get_last_error())
	try:
		while True:
			check()
			if data.name not in ('.', '..'):
				yield data.name, data.alternate
			if not library.FindNextFileW(handle, ctypes.byref(data)):
				code = ctypes.get_last_error()
				if code != 18:
					raise ctypes.WinError(code)
				return
	finally:
		library.FindClose(handle)


def output_text(raw):
	lines = []
	for line in re.split(br'\n\x00?', raw):
		line = line.removeprefix(b'\xff\xfe').strip(b'\r\x00')
		if not line:
			continue
		if line.count(b'\x00') > len(line) // 4:
			if len(line) % 2:
				line += b'\x00'
			text = line.decode('utf-16-le', errors='replace')
		else:
			text = line.decode('mbcs', errors='replace')
		lines.append(''.join(char if char.isprintable() or char == '\t' else ' ' for char in text))
	return '\n'.join(lines)


class OutputTail:
	def __init__(self):
		self._lock = Lock()
		self._data = bytearray()
		self.error = None

	def add(self, data):
		with self._lock:
			self._data.extend(data)
			del self._data[:-65536]

	def text(self):
		with self._lock:
			return output_text(bytes(self._data))


class OwnedProcess:
	def __init__(self, arguments, cwd=None):
		self.library = api()
		self.job = self.process = self.read_pipe = None
		self.pid = None
		self.output = OutputTail()
		self.reader = None
		self._drain = Event()
		self._closed = False
		self._start(arguments, cwd)

	def _start(self, arguments, cwd):
		library = self.library
		writer = input_handle = thread = attributes = None
		try:
			self.job = checked(library.CreateJobObjectW(None, None))
			limits = ExtendedLimits()
			limits.basic.flags = 0x2000
			checked(library.SetInformationJobObject(self.job, 9, ctypes.byref(limits), ctypes.sizeof(limits)))
			security = SecurityAttributes(ctypes.sizeof(SecurityAttributes), None, True)
			read_handle, write_handle = wintypes.HANDLE(), wintypes.HANDLE()
			checked(library.CreatePipe(ctypes.byref(read_handle), ctypes.byref(write_handle), ctypes.byref(security), 0))
			self.read_pipe, writer = read_handle.value, write_handle.value
			checked(library.SetHandleInformation(self.read_pipe, 1, 0))
			input_handle = library.CreateFileW('NUL', 0x80000000, 3, ctypes.byref(security), 3, 0, None)
			if input_handle == ctypes.c_void_p(-1).value:
				input_handle = None
				raise ctypes.WinError(ctypes.get_last_error())
			size = ctypes.c_size_t()
			library.InitializeProcThreadAttributeList(None, 1, 0, ctypes.byref(size))
			storage = ctypes.create_string_buffer(size.value)
			checked(library.InitializeProcThreadAttributeList(storage, 1, 0, ctypes.byref(size)))
			attributes = storage
			handles = (wintypes.HANDLE * 2)(input_handle, writer)
			checked(library.UpdateProcThreadAttribute(attributes, 0, 0x20002, handles, ctypes.sizeof(handles), None, None))
			startup = StartupInfoEx()
			startup.startup.cb = ctypes.sizeof(startup)
			startup.startup.flags = 0x100
			startup.startup.stdin = input_handle
			startup.startup.stdout = startup.startup.stderr = writer
			startup.attributes = ctypes.cast(attributes, ctypes.c_void_p)
			info = ProcessInfo()
			command = ctypes.create_unicode_buffer(subprocess.list2cmdline(arguments))
			checked(library.CreateProcessW(arguments[0], command, None, None, True,
				0x00000004 | 0x00080000 | 0x08000000, None, cwd, ctypes.byref(startup), ctypes.byref(info)))
			self.process, thread, self.pid = info.process, info.thread, info.pid
			checked(library.AssignProcessToJobObject(self.job, self.process))
			self.reader = Thread(target=self._read, name='robocopy-output', daemon=True)
			self.reader.start()
			if library.ResumeThread(thread) == 0xffffffff:
				raise ctypes.WinError(ctypes.get_last_error())
		except BaseException:
			if self.process:
				library.TerminateProcess(self.process, 1)
				library.WaitForSingleObject(self.process, 0xffffffff)
			if writer:
				library.CloseHandle(writer)
				writer = None
			self.close()
			raise
		finally:
			if attributes is not None:
				library.DeleteProcThreadAttributeList(attributes)
			for handle in (writer, input_handle, thread):
				if handle:
					library.CloseHandle(handle)

	def _read(self):
		buffer = ctypes.create_string_buffer(8192)
		amount = wintypes.DWORD()
		available = wintypes.DWORD()
		remaining = None
		try:
			while self.library.PeekNamedPipe(self.read_pipe, None, 0, None, ctypes.byref(available), None):
				if remaining is None and self._drain.is_set():
					remaining = available.value
				requested = min(len(buffer), available.value, remaining if remaining is not None else len(buffer))
				if requested:
					if not self.library.ReadFile(self.read_pipe, buffer, requested, ctypes.byref(amount), None):
						break
					if not amount.value:
						return
					self.output.add(buffer.raw[:amount.value])
					if remaining is not None:
						remaining -= amount.value
				elif remaining is not None:
					return
				else:
					self._drain.wait(.05)
			code = ctypes.get_last_error()
			if code not in (109, 6, 995):
				raise ctypes.WinError(code)
		except BaseException as error:
			self.output.error = error

	def poll(self):
		waited = self.library.WaitForSingleObject(self.process, 0)
		if waited == 258:
			return None
		if waited != 0:
			raise ctypes.WinError(ctypes.get_last_error())
		code = wintypes.DWORD()
		checked(self.library.GetExitCodeProcess(self.process, ctypes.byref(code)))
		return code.value

	def close(self):
		if self._closed:
			return
		self._closed = True
		if self.job:
			self.library.TerminateJobObject(self.job, 1)
		if self.process:
			self.library.WaitForSingleObject(self.process, 0xffffffff)
		self._drain.set()
		if self.reader is not None and self.reader.ident is not None:
			self.reader.join()
		for handle in (self.read_pipe, self.process, self.job):
			if handle:
				self.library.CloseHandle(handle)
		self.read_pipe = self.process = self.job = None


def run(arguments, check=lambda: None, activity=lambda text: None, timeout=None, cwd=None):
	check()
	process = OwnedProcess(arguments, cwd)
	started = monotonic()
	waiter = Event()
	try:
		while True:
			code = process.poll()
			if code is not None:
				break
			check()
			if process.output.error is not None:
				raise OSError('Could not read Robocopy output: ' + str(process.output.error))
			if timeout is not None and monotonic() - started >= timeout:
				raise TimeoutError('Robocopy option check timed out.')
			text = process.output.text()
			activity(text.splitlines()[-1][-512:] if text else '')
			waiter.wait(.1)
	finally:
		process.close()
	if process.output.error is not None:
		raise OSError('Could not read Robocopy output: ' + str(process.output.error))
	return code, process.output.text()