import ctypes
from ctypes import wintypes
import importlib.machinery
import importlib.util
import os
from pathlib import Path
from stat import S_ISDIR
from struct import Struct

from fman.listing import Listing


_RECORD = Struct('<IIqqqqqqIIII16s')
_EPOCH = 116444736000000000
_UNSUPPORTED = (1, 50, 87, 120, 124)
_LINK_TAGS = (0xA0000003, 0xA000000C)


_LFS_POINTER_PREFIX = b'version https://git-lfs.github.com/spec/v1'


def _native_parser_candidates():
	"""Package-local binary (frozen application), then src/main/c (repository checkout)."""
	here = Path(__file__).resolve().parent
	yield here / '_fsparser.pyd'
	if len(here.parents) > 8:  # a drive-root portable install is shallower than a checkout
		yield here.parents[8] / 'main' / 'c' / '_fsparser.pyd'


def _load_native_parser():
	"""The `_fsparser` extension (Done/FSParser.md); the scanner has no Python fallback.

	Source: src/main/c/fsparser.c. The frozen application ships the module next to
	this file; a repository checkout keeps it at src/main/c/_fsparser.pyd (Git LFS),
	paired with its source by src/main/c/fsparser.sha256 and checked by build.py.
	"""
	candidates = list(_native_parser_candidates())
	for path in candidates:
		if not path.is_file():
			continue
		with open(path, 'rb') as handle:
			if handle.read(len(_LFS_POINTER_PREFIX)) == _LFS_POINTER_PREFIX:
				raise ImportError('%s is a Git LFS pointer, not the module: run `git lfs pull`.' % path)
		loader = importlib.machinery.ExtensionFileLoader('_fsparser', str(path))
		spec = importlib.util.spec_from_file_location('_fsparser', str(path), loader=loader)
		module = importlib.util.module_from_spec(spec)
		loader.exec_module(module)
		return module
	raise ImportError(
		'Native directory parser _fsparser.pyd not found (looked in %s). '
		'Run `git lfs pull`; see src/main/c/README.md.' % ', '.join(map(str, candidates)))


_fsparser = _load_native_parser() if os.name == 'nt' else None


def records(data):
	"""Reference parser: what `_fsparser` computes per record, in Python.

	Not used by scan(); kept as the readable specification that the tests, the
	gauge and src/misc/validate_fsparser.py compare the C module against.
	"""
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
			# Other NTFS drivers can store these; Listing rejects them, so the parser must too.
			if '/' in name or '\\' in name or '\x00' in name:
				raise ValueError('Invalid directory entry name')
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
	"""Safe path (Done/FSParser.md): C parsing, then a Listing without re-validation.

	The per-record work runs in _fsparser; the Listing is built with
	Listing._trusted because every column is guaranteed by the kernel and the C
	code (see that method). Every other producer is the regular, validated path.
	src/misc/benchmark_fsparser.py and src/misc/validate_fsparser.py compare this
	against records() on real folders and crafted buffers.
	"""
	check_canceled()
	if path.startswith('\\\\') or not os.path.isabs(path):
		return None
	try:
		with NativeDirectory(path) as directory:
			scope = directory.scope()
			if scope is None:
				return None
			columns = _fsparser.Columns(_LINK_TAGS)
			for batch in directory.batches(check_canceled):
				# Equivalent Python, per record of the batch (see records()):
				#   names.append(name); directories.append(bool(own_attributes & FILE_ATTRIBUTE_DIRECTORY))
				#   sizes.append(size); mtimes.append(modified); attributes.append(own_attributes)
				#   created.append(birth); identities.extend(identity)
				# add() does those appends in C and returns the indices of the entries that
				# are reparse points with a tag in _LINK_TAGS, for the link follow-up below.
				for index in columns.add(batch):
					name, _, _ = columns.entry(index)
					check_canceled()
					try:
						metadata = os.stat(os.path.join(path, name))
					except OSError:
						continue
					# Equivalent Python: is_dir, size, modified = S_ISDIR(st_mode), st_size, st_mtime_ns for that entry.
					columns.patch(index, S_ISDIR(metadata.st_mode), metadata.st_size, metadata.st_mtime_ns)
	except OSError as error:
		if getattr(error, 'winerror', None) in _UNSUPPORTED:
			return None
		raise
	check_canceled()
	# Equivalent Python: tuple(names), tuple(directories), ..., bytes(identities).
	names, directories, sizes, mtimes, attributes, created, identities, _ = columns.finish(frozen=True)
	return Listing._trusted(location, names, directories, sizes, mtimes, attributes, created, identities, scope)