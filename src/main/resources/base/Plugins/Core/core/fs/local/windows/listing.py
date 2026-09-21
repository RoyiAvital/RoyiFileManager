import ctypes
from ctypes import wintypes
import os
from stat import S_ISDIR, FILE_ATTRIBUTE_DIRECTORY, FILE_ATTRIBUTE_REPARSE_POINT
from struct import Struct

from fman.listing import Listing


_RECORD = Struct('<IIqqqqqqIIII16s')
_EPOCH = 116444736000000000
_UNSUPPORTED = (1, 50, 87, 120, 124)
_LINK_TAGS = (0xA0000003, 0xA000000C)


def records(data):
	offset = 0
	while True:
		if offset + _RECORD.size > len(data):
			raise ValueError('Truncated directory record')
		values = _RECORD.unpack_from(data, offset)
		next_offset, _, created, _, modified, _, size, _, attributes, length, _, tag, identity = values
		end = offset + _RECORD.size + length
		if not length or length % 2 or end > len(data) or size < 0:
			raise ValueError('Invalid directory record')
		if next_offset and (next_offset % 8 or next_offset < _RECORD.size + length
			or offset + next_offset + _RECORD.size > len(data)):
			raise ValueError('Invalid directory record offset')
		name = data[offset + _RECORD.size:end].decode('utf-16-le', errors='surrogatepass')
		if name not in ('.', '..'):
			yield name, size, (modified - _EPOCH) * 100, attributes, tag, identity, (created - _EPOCH) * 100
		if not next_offset:
			return
		offset += next_offset


class NativeDirectory:
	def __init__(self, path):
		self.path = path if path.startswith('\\\\?\\') else '\\\\?\\' + os.path.abspath(path)
		self.api = ctypes.WinDLL('kernel32', use_last_error=True)
		for name, arguments, result in (
			('CreateFileW', [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD,
				ctypes.c_void_p, wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE], wintypes.HANDLE),
			('CloseHandle', [wintypes.HANDLE], wintypes.BOOL),
			('GetFileInformationByHandleEx', [wintypes.HANDLE, ctypes.c_int,
				ctypes.c_void_p, wintypes.DWORD], wintypes.BOOL),
			('GetFinalPathNameByHandleW', [wintypes.HANDLE, wintypes.LPWSTR,
				wintypes.DWORD, wintypes.DWORD], wintypes.DWORD),
			('GetVolumeInformationByHandleW', [wintypes.HANDLE, wintypes.LPWSTR,
				wintypes.DWORD, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p,
				wintypes.LPWSTR, wintypes.DWORD], wintypes.BOOL)):
			function = getattr(self.api, name)
			function.argtypes, function.restype = arguments, result

	def __enter__(self):
		self.handle = self.api.CreateFileW(self.path, 0x81, 7, None, 3, 0x02000000, None)
		if self.handle == ctypes.c_void_p(-1).value:
			raise ctypes.WinError(ctypes.get_last_error())
		return self

	def __exit__(self, *args):
		self.api.CloseHandle(self.handle)

	def scope(self):
		path = ctypes.create_unicode_buffer(32768)
		length = self.api.GetFinalPathNameByHandleW(self.handle, path, len(path), 0)
		if not length:
			raise ctypes.WinError(ctypes.get_last_error())
		if length >= len(path) or path.value.upper().startswith('\\\\?\\UNC\\'):
			return None
		flags = wintypes.DWORD()
		filesystem = ctypes.create_unicode_buffer(32)
		if not self.api.GetVolumeInformationByHandleW(self.handle, None, 0, None, None,
			ctypes.byref(flags), filesystem, len(filesystem)):
			raise ctypes.WinError(ctypes.get_last_error())
		if filesystem.value not in ('NTFS', 'ReFS') or not flags.value & 0x01000000:
			return None
		data = ctypes.create_string_buffer(24)
		if not self.api.GetFileInformationByHandleEx(self.handle, 18, data, len(data)):
			raise ctypes.WinError(ctypes.get_last_error())
		return int.from_bytes(data.raw[:8], 'little'), data.raw[8:24]

	def batches(self, check_canceled):
		buffer = ctypes.create_string_buffer(65536)
		information_class = 20
		while True:
			check_canceled()
			ctypes.memset(buffer, 0, len(buffer))
			if not self.api.GetFileInformationByHandleEx(
				self.handle, information_class, buffer, len(buffer)):
				error = ctypes.get_last_error()
				if error == 18:
					return
				raise ctypes.WinError(error)
			yield buffer.raw
			information_class = 19


def scan(location, path, check_canceled):
	check_canceled()
	if path.startswith('\\\\') or not os.path.isabs(path):
		return None
	names, directories, sizes, mtimes, attributes, created = ([] for _ in range(6))
	identities = bytearray()
	try:
		with NativeDirectory(path) as directory:
			scope = directory.scope()
			if scope is None:
				return None
			for batch in directory.batches(check_canceled):
				for name, size, modified, own_attributes, tag, identity, birth in records(batch):
					is_dir = bool(own_attributes & FILE_ATTRIBUTE_DIRECTORY)
					if own_attributes & FILE_ATTRIBUTE_REPARSE_POINT and tag in _LINK_TAGS:
						check_canceled()
						try:
							metadata = os.stat(os.path.join(path, name))
						except OSError:
							pass
						else:
							is_dir, size, modified = S_ISDIR(metadata.st_mode), metadata.st_size, metadata.st_mtime_ns
					names.append(name)
					directories.append(is_dir)
					sizes.append(size)
					mtimes.append(modified)
					attributes.append(own_attributes)
					created.append(birth)
					identities.extend(identity)
	except OSError as error:
		if getattr(error, 'winerror', None) in _UNSUPPORTED:
			return None
		raise
	check_canceled()
	return Listing(location, names, directories, sizes, mtimes, attributes,
		created, bytes(identities), scope)