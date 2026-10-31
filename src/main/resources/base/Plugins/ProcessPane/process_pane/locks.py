"""Processes that use a file or folder, found with regular user rights.

Windows keeps, per file object, the IDs of the processes that have it open,
including running executables and loaded DLLs. Reading that list needs only an
attribute-only handle to the item; no process is opened to find its users.
"""

from dataclasses import dataclass, field
from functools import lru_cache
from ctypes import wintypes

import ctypes
import ntpath
import os


MAX_ITEMS = 100_000
MAX_RESULT_ROWS = 10_000
MAX_RESULT_BYTES = 4 * 1024 * 1024
_FILE_READ_ATTRIBUTES = 0x80
_SHARE_ALL = 0x7
_OPEN_EXISTING = 3
# Backup semantics opens folders; open-reparse-point queries links themselves, not their targets.
_OPEN_FLAGS = 0x02000000 | 0x00200000
_INVALID_HANDLE = ctypes.c_void_p(-1).value
_PROCESS_IDS_USING_FILE = 47
_BUFFER_TOO_SMALL = (0xC0000004, 0x80000005)
_MAX_BUFFER = 1 << 20
_QUERY_LIMITED_INFORMATION = 0x1000


class _IoStatus(ctypes.Structure):
	_fields_ = [('status', ctypes.c_void_p), ('information', ctypes.c_size_t)]


@lru_cache(maxsize=1)
def _native():
	kernel = ctypes.WinDLL('kernel32', use_last_error=True)
	kernel.CreateFileW.argtypes = (wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, ctypes.c_void_p,
		wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE)
	kernel.CreateFileW.restype = wintypes.HANDLE
	kernel.CloseHandle.argtypes = (wintypes.HANDLE,)
	kernel.CloseHandle.restype = wintypes.BOOL
	ntdll = ctypes.WinDLL('ntdll')
	ntdll.NtQueryInformationFile.argtypes = (wintypes.HANDLE, ctypes.POINTER(_IoStatus), ctypes.c_void_p,
		wintypes.ULONG, ctypes.c_int)
	ntdll.NtQueryInformationFile.restype = wintypes.ULONG
	ntdll.RtlNtStatusToDosError.argtypes = (wintypes.ULONG,)
	ntdll.RtlNtStatusToDosError.restype = wintypes.ULONG
	return kernel, ntdll


def _extended(path):
	path = os.path.abspath(path)
	if path.startswith('\\\\?\\'):
		return path
	if path.startswith('\\\\'):
		return '\\\\?\\UNC\\' + path[2:]
	return '\\\\?\\' + path


def process_ids(path):
	"""IDs of the processes that have the file or folder at `path` open."""
	kernel, ntdll = _native()
	handle = kernel.CreateFileW(_extended(path), _FILE_READ_ATTRIBUTES, _SHARE_ALL, None, _OPEN_EXISTING,
		_OPEN_FLAGS, None)
	if handle in (None, _INVALID_HANDLE):
		raise ctypes.WinError(ctypes.get_last_error())
	try:
		size = 4096
		while True:
			buffer = ctypes.create_string_buffer(size)
			status = ntdll.NtQueryInformationFile(handle, ctypes.byref(_IoStatus()), buffer, size,
				_PROCESS_IDS_USING_FILE)
			if status == 0:
				break
			if status in _BUFFER_TOO_SMALL and size < _MAX_BUFFER:
				size *= 4
				continue
			raise ctypes.WinError(ntdll.RtlNtStatusToDosError(status))
	finally:
		kernel.CloseHandle(handle)
	word = ctypes.sizeof(ctypes.c_size_t)
	count = min(ctypes.c_ulong.from_buffer(buffer).value, size // word - 1)
	return tuple((ctypes.c_size_t * count).from_buffer(buffer, word))


@dataclass
class Usage:
	# (path, process IDs) for each item in use.
	items: list = field(default_factory=list)
	checked: int = 0
	failed: int = 0
	complete: bool = True
	limited: bool = False


def find(root, check=lambda: None, progress=lambda path: None, query=process_ids):
	"""Items in use at `root` and, for a folder, below it; links and junctions are not followed.

	An error for `root` itself propagates. Later errors are counted in `failed`.
	"""
	usage = Usage()
	retained_rows = retained_bytes = 0
	def visit(path):
		nonlocal retained_rows, retained_bytes
		usage.checked += 1
		if usage.checked % 256 == 0:
			progress(path)
		ids = query(path)
		if ids:
			path_bytes = len(path.encode('utf-8', 'surrogatepass'))
			remaining = max(0, MAX_RESULT_BYTES - retained_bytes - path_bytes)
			kept = min(len(ids), MAX_RESULT_ROWS - retained_rows, remaining // 8)
			if kept:
				usage.items.append((path, tuple(ids[:kept])))
				retained_rows += kept
				retained_bytes += path_bytes + 8 * kept
			usage.limited |= kept < len(ids)
	check()
	visit(root)
	check()
	if not os.path.isdir(root) or os.path.islink(root) or os.path.isjunction(root):
		return usage
	folders = [root]
	while folders:
		folder = folders.pop()
		try:
			with os.scandir(folder) as entries:
				for entry in entries:
					check()
					if usage.checked >= MAX_ITEMS:
						usage.complete = False
						return usage
					try:
						visit(entry.path)
						if entry.is_dir(follow_symlinks=False) and not entry.is_junction():
							folders.append(entry.path)
					except OSError:
						usage.failed += 1
		except OSError:
			usage.failed += 1
	check()
	return usage


def describe(ids, api, check=lambda: None):
	"""{process ID: (name, executable path)}; the path is '' when Windows denies the query."""
	result = {}
	for pid in ids:
		check()
		try:
			with api.open(pid, _QUERY_LIMITED_INFORMATION) as handle:
				path = api.image_name(handle)
			result[pid] = (ntpath.basename(path), path)
		except OSError:
			result[pid] = ('System' if pid == 4 else 'Unavailable', '')
	check()
	return result
