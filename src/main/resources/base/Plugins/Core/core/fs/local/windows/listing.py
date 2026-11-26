import importlib.machinery
import importlib.util
import os
from pathlib import Path
from struct import Struct

from fman.listing import Listing


_RECORD = Struct('<IIqqqqqqIIII16s')
_EPOCH = 116444736000000000
# The longest Windows path as UTF-16: no name is longer (NTFS and ReFS allow 255 units).
_MAX_NAME_BYTES = 2 * 32767
_LINK_TAGS = (0xA0000003, 0xA000000C)


_LFS_POINTER_PREFIX = b'version https://git-lfs.github.com/spec/v1'


def _native_enumerator_candidates():
	"""Package-local binary (frozen application), then src/main/rust/fsenum (repository checkout)."""
	here = Path(__file__).resolve().parent
	yield here / '_fsenum.pyd'
	if len(here.parents) > 8:  # a drive-root portable install is shallower than a checkout
		yield here.parents[8] / 'main' / 'rust' / 'fsenum' / '_fsenum.pyd'


def _load_native_enumerator():
	"""The `_fsenum` extension (Plan/DirectoryEnumerator001.md); the scanner has no Python fallback.

	Source: src/main/rust/fsenum. The frozen application ships the module next to
	this file; a repository checkout keeps it at src/main/rust/fsenum/_fsenum.pyd
	(Git LFS), paired with its sources by fsenum.sha256 and checked by build.py.
	"""
	candidates = list(_native_enumerator_candidates())
	for path in candidates:
		if not path.is_file():
			continue
		with open(path, 'rb') as handle:
			if handle.read(len(_LFS_POINTER_PREFIX)) == _LFS_POINTER_PREFIX:
				raise ImportError('%s is a Git LFS pointer, not the module: run `git lfs pull`.' % path)
		loader = importlib.machinery.ExtensionFileLoader('_fsenum', str(path))
		spec = importlib.util.spec_from_file_location('_fsenum', str(path), loader=loader)
		module = importlib.util.module_from_spec(spec)
		loader.exec_module(module)
		return module
	raise ImportError(
		'Native directory enumerator _fsenum.pyd not found (looked in %s). '
		'Run `git lfs pull`; see src/main/rust/fsenum/README.md.' % ', '.join(map(str, candidates)))


_fsenum = _load_native_enumerator()


def records(data):
	"""Reference parser: what `_fsenum` computes per record, in Python.

	Not used by scan(); kept as the readable specification that the tests and
	src/misc/benchmark_fsenum.py compare the native module against.
	"""
	offset = 0
	while True:
		if offset + _RECORD.size > len(data):
			raise ValueError('Truncated directory record')
		values = _RECORD.unpack_from(data, offset)
		next_offset, _, created, _, modified, _, size, _, attributes, length, _, tag, identity = values
		end = offset + _RECORD.size + length
		if not length or length % 2 or length > _MAX_NAME_BYTES or end > len(data) or size < 0:
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


def scan(location, path, check_canceled, previous=None):
	"""Safe path (Plan/DirectoryEnumerator001.md): native enumeration, then a
	Listing without re-validation.

	`_fsenum.scan` reads the folder's FILE_ID_EXTD_DIR_INFO batches (see
	records()) on its own threads and returns the columns, or None for a volume
	without stable identities (UNC, FAT, ...). Per entry, in Python:
	  names.append(name); is_dir.append(bool(attributes & FILE_ATTRIBUTE_DIRECTORY))
	  sizes.append(size); mtimes.append(modified); attributes.append(attributes)
	  created.append(birth); identities.extend(identity)
	and for a reparse point with a tag in _LINK_TAGS, when it succeeds:
	  metadata = os.stat(os.path.join(path, name))
	  is_dir, size, modified = S_ISDIR(metadata.st_mode), metadata.st_size, metadata.st_mtime_ns
	It also returns the Name order as a native table, attached as Listing._native.
	With `previous`, the last native Listing of this location, unchanged entries
	reuse its objects and an unchanged folder returns `previous` itself.
	"""
	check_canceled()
	if path.startswith('\\\\') or not os.path.isabs(path):
		return None
	if previous is not None and previous.location != location:
		previous = None
	result = _fsenum.scan('\\\\?\\' + os.path.abspath(path), os.path.join(path, ''), _LINK_TAGS, check_canceled,
		previous)
	if result is None or result is previous:
		return result
	names, directories, sizes, mtimes, attributes, created, identities, scope, table = result
	return Listing._trusted(location, names, directories, sizes, mtimes, attributes, created, identities, scope,
		native=table)