"""Tests for the native directory enumerator `_fsenum` (Plan/DirectoryEnumerator001.md).

The module under test is the one the scanner loaded (`listing._fsenum`).
"""

import _winapi
import os
import random
import unicodedata
from array import array
from pathlib import Path
from stat import S_ISDIR
from tempfile import TemporaryDirectory
from unittest import TestCase, skipUnless

from core.fs.local.windows import listing
from fman.impl.util.natural import natural_key
from fman.listing import Listing

_fsenum = listing._fsenum
CRATE = Path(__file__).resolve().parents[9] / 'src' / 'main' / 'rust' / 'fsenum'
INT64_MIN, INT64_MAX = -2**63, 2**63 - 1
EPOCH = listing._EPOCH
FILE_ATTRIBUTE_HIDDEN = 0x2
FILE_ATTRIBUTE_DIRECTORY = 0x10
FILE_ATTRIBUTE_REPARSE_POINT = 0x400
LINK_TAGS = listing._LINK_TAGS
CLOUD_TAG = 0x9000601A
IDENTITY = bytes(range(16))


@skipUnless((CRATE / 'fsenum.sha256').is_file(), 'repository checkout required')
class SourceBinaryPairingTest(TestCase):
	"""src/main/rust/fsenum/_fsenum.pyd is the build of its sources recorded in fsenum.sha256."""

	def test_hashes_match_and_scanner_loaded_that_binary(self):
		import sys
		sys.path.insert(0, str(CRATE))
		try:
			from fsenum_hashes import BINARY, check, is_lfs_pointer
		finally:
			sys.path.remove(str(CRATE))
		self.assertEqual([], check())
		self.assertFalse(is_lfs_pointer(BINARY))
		self.assertEqual(str(BINARY).lower(), _fsenum.__file__.lower())


def record(name, size=0, modified=EPOCH, created=EPOCH, attributes=0x20, tag=0,
	identity=IDENTITY, name_bytes=None, next_offset=None):
	if name_bytes is None:
		name_bytes = name.encode('utf-16-le', 'surrogatepass')
	length = listing._RECORD.size + len(name_bytes)
	padded = (length + 7) // 8 * 8
	if next_offset is None:
		next_offset = padded
	header = listing._RECORD.pack(next_offset, 0, created, 0, modified, 0, size, 0,
		attributes, len(name_bytes), 0, tag, identity)
	return header + name_bytes + b'\0' * (padded - length)


def batch(*records):
	"""Chain records; the last one gets next_offset 0."""
	last = records[-1]
	last = (0).to_bytes(4, 'little') + last[4:]
	return b''.join(records[:-1]) + last


def python_parse(*batches):
	"""records() as the scan's columns, plus the indices of link-tagged reparse points."""
	names, directories, sizes, mtimes, attributes, created, links = ([] for _ in range(7))
	identities = bytearray()
	for data in batches:
		for name, size, modified, own_attributes, tag, identity, birth in listing.records(data):
			if own_attributes & FILE_ATTRIBUTE_REPARSE_POINT and tag in LINK_TAGS:
				links.append(len(names))
			names.append(name)
			directories.append(bool(own_attributes & FILE_ATTRIBUTE_DIRECTORY))
			sizes.append(size)
			mtimes.append(modified)
			attributes.append(own_attributes)
			created.append(birth)
			identities.extend(identity)
	return tuple(names), tuple(directories), tuple(sizes), tuple(mtimes), tuple(attributes), tuple(created), \
		bytes(identities), tuple(links)


MALFORMED = {
	'empty': b'',
	'truncated header': b'\0' * 40,
	'zero name length': record('', name_bytes=b''),
	'odd name length': record('x', name_bytes=b'x'),
	'name past end': batch(record('abc'))[:90],
	'negative size': record('a', size=-1),
	'unaligned offset': batch(record('a', next_offset=92), record('b')),
	'offset too small': batch(record('abcdefghij', next_offset=88), record('b')),
	'offset past end': batch(record('a', next_offset=96), record('b')[:40]),
	'slash in name': batch(record('ok'), record('a/b')),
	'backslash in name': batch(record('ok'), record('a\\b')),
	'NUL in name': batch(record('ok'), record('a\x00b')),
	'backslash after dot entries': batch(record('.', attributes=FILE_ATTRIBUTE_DIRECTORY), record('\\')),
	'name longer than a path': record('a' * (listing._MAX_NAME_BYTES // 2 + 1)),
}

MIXED = batch(
	record('.', attributes=FILE_ATTRIBUTE_DIRECTORY),
	record('..', attributes=FILE_ATTRIBUTE_DIRECTORY),
	record('file.txt', size=1234, modified=EPOCH + 10**9, created=EPOCH - 5),
	record('folder', attributes=FILE_ATTRIBUTE_DIRECTORY | FILE_ATTRIBUTE_HIDDEN),
	record('link', attributes=FILE_ATTRIBUTE_REPARSE_POINT, tag=0xA000000C),
	record('junction', attributes=FILE_ATTRIBUTE_REPARSE_POINT | FILE_ATTRIBUTE_DIRECTORY, tag=0xA0000003),
	record('\U0001F600 emoji'),
	record('lone', name_bytes='a\ud800b'.encode('utf-16-le', 'surrogatepass')),
	record('bom', name_bytes='\ufeffname'.encode('utf-16-le')),
	record('latin1 \xe9\xff'),
	record('big', size=INT64_MAX, identity=b'\xff' * 16),
	record('trailing.', size=1),
	record('Case.txt'),
	record('case.txt'),
	record('cloud.docx', attributes=FILE_ATTRIBUTE_REPARSE_POINT | 0x20, tag=CLOUD_TAG),
)

FILETIMES = (INT64_MIN, INT64_MIN + 1, -1, 0, EPOCH - 1, EPOCH, EPOCH + 1,
	INT64_MAX // 100 + EPOCH, INT64_MAX // 100 + EPOCH + 1, INT64_MAX - 1, INT64_MAX)


class ParseBatchesTest(TestCase):
	"""parse_batches: the scan's decoding and object creation on given buffers, against records()."""

	def assertParity(self, *batches):
		expected = python_parse(*batches)
		actual = _fsenum.parse_batches(batches, LINK_TAGS)
		self.assertEqual(expected[6], actual[6], 'identities')
		for label, left, right in zip(('names', 'is_dir', 'sizes', 'mtimes', 'attributes', 'created', 'links'),
			expected[:6] + expected[7:], actual[:6] + actual[7:]):
			self.assertIs(tuple, type(right), label)
			self.assertEqual(left, right, label)
			self.assertEqual([type(value) for value in left], [type(value) for value in right], label)

	def test_header_size(self):
		self.assertEqual(listing._RECORD.size, _fsenum.HEADER_SIZE)

	def test_mixed_records_and_link_indices(self):
		self.assertParity(MIXED)
		self.assertEqual((2, 3), _fsenum.parse_batches((MIXED,), LINK_TAGS)[7])

	def test_batches_crossing_segments(self):
		count = _fsenum.SEGMENT_SIZE + 700
		names = ['n%05d \xe9' % index if index % 3 else 'n%05d \u0100' % index for index in range(count)]
		self.assertParity(*(batch(*(record(name, size=index) for index, name in enumerate(names[start:start + 700])))
			for start in range(0, count, 700)))

	def test_single_record_and_dot_only(self):
		self.assertParity(batch(record('only')))
		self.assertParity(batch(record('.'), record('..')))

	def test_longest_names(self):
		units = listing._MAX_NAME_BYTES // 2
		self.assertParity(batch(record('a' * units), record('\u0100' * units)))

	def test_filetime_boundaries(self):
		for value in FILETIMES:
			with self.subTest(value=value):
				self.assertParity(batch(record('t', modified=value, created=value)))

	def test_malformed_matches_python(self):
		for label, data in MALFORMED.items():
			with self.subTest(label):
				with self.assertRaises(ValueError) as expected:
					list(listing.records(data))
				with self.assertRaises(ValueError) as actual:
					_fsenum.parse_batches((batch(record('first')), data), LINK_TAGS)
				self.assertEqual(str(expected.exception), str(actual.exception))

	def test_rejects_non_bytes(self):
		data = batch(record('a'))
		for bad in (bytearray(data), memoryview(data), data.decode('latin-1')):
			with self.assertRaises(TypeError):
				_fsenum.parse_batches((bad,), LINK_TAGS)


class NaturalKeysTest(TestCase):

	EDGE_NAMES = ('File2.txt', 'file02.txt', 'file10.txt', 'a' + '9' * 80, '0', '000', 'x0000001y',
		'Stra\u00dfe_caf\u00e9_CAF\u00c9_12', 'v\u0662\u0663', 'v\uff12', '\u0130stanbul 5', 'K 7',
		'lone\udc80 3', '\U0001F600 42', '\U0001D7CE\U0001D7D7', '', '\u0660\u0660\u0661\u0662\u0663',
		'1234567', '12345678901234567890' * 3, 'ab\u0665\u0666cd', '\xff\xfe 1', '\u0100 2',
		'\u03a3', 'A\u03a3', 'A\u03a3b', 'A\u03a3.', 'A\u0345\u03a3', '\u03a3\u03a3 \u03a3')

	@staticmethod
	def reference(names, is_dir, ascending):
		return tuple(('1' if d ^ ascending else '0') + natural_key(name) for name, d in zip(names, is_dir))

	def test_matches_python_reference_on_edge_names(self):
		is_dir = [index % 3 == 0 for index in range(len(self.EDGE_NAMES))]
		for ascending in (True, False):
			keys = _fsenum.natural_keys(self.EDGE_NAMES, is_dir, ascending)
			self.assertIsInstance(keys, tuple)
			self.assertEqual(self.reference(self.EDGE_NAMES, is_dir, ascending), keys)

	def test_matches_python_reference_on_every_code_point(self):
		self.assertEqual(unicodedata.unidata_version, _fsenum.UNICODE_VERSION)
		for start in range(0, 0x110000, 0x10000):
			names = [chr(code) + 'x\u03a3 9' + chr(code) for code in range(start, start + 0x10000)]
			flags = [False] * len(names)
			self.assertEqual(self.reference(names, flags, True), _fsenum.natural_keys(names, flags, True))

	def test_accepts_sequences_and_truthy_flags(self):
		self.assertEqual(('0b', '1a'), _fsenum.natural_keys(iter(['b', 'a']), (1, 0), True))
		self.assertEqual((), _fsenum.natural_keys([], [], False))

	def test_rejects_bad_arguments(self):
		with self.assertRaises(ValueError):
			_fsenum.natural_keys(['a', 'b'], [False], True)
		for names in (['a', 1], ['a', b'b'], [None]):
			with self.assertRaises(TypeError):
				_fsenum.natural_keys(names, [False] * len(names), True)
		with self.assertRaises(TypeError):
			_fsenum.natural_keys(['a'], [False])


def reference_order(names, is_dir, ascending):
	keys = NaturalKeysTest.reference(names, is_dir, ascending)
	return list(sorted(range(len(names)), key=keys.__getitem__, reverse=not ascending))


class NameOrderTest(TestCase):
	"""The native sort equals Python's stable sorted() over the Name keys, ties included."""

	def assertOrder(self, names, is_dir):
		for ascending in (True, False):
			with self.subTest(ascending=ascending):
				order = array('I', _fsenum.name_order(names, is_dir, ascending))
				self.assertEqual(reference_order(names, is_dir, ascending), list(order))

	def test_shared_stems_duplicate_keys_and_segments(self):
		generator = random.Random(7)
		stems = ('IMG_2024', 'common_' + 'a' * 40, 'File', 'file', '\u03a3\u03c3', '\U0001F600', 'x\udc80', '')
		names = [generator.choice(stems) + generator.choice(('', '0', '007', '7', '1' * 9, '.txt', ' \xe9'))
			+ str(generator.randrange(50)) for _ in range(2 * _fsenum.SEGMENT_SIZE + 300)]
		self.assertOrder(names, [generator.random() < 0.2 for _ in names])

	def test_code_points_across_planes(self):
		codes = list(range(1, 0x3400, 3)) + list(range(0xD7F0, 0xE010)) + list(range(0x1F600, 0x1F650)) + [0x10FFFF]
		names = [chr(code) for code in codes] + ['a' + chr(code) + '1' for code in codes[::7]]
		random.Random(3).shuffle(names)
		self.assertOrder(names, [False] * len(names))

	def test_digit_led_names_and_shared_stems(self):
		# Keys that share their first bytes: zero padding, a short stem, a whole first chunk.
		generator = random.Random(11)
		for stem in ('', 'IMG_', 'a stem longer than one chunk '):
			names = [stem + str(generator.randrange(10 ** generator.randrange(1, 9))) + '.jpg'
				for _ in range(_fsenum.SEGMENT_SIZE + 500)]
			self.assertOrder(names, [False] * len(names))

	def test_rejects_nul(self):
		# The sort pads keys with NUL, so 'a\0' would order before 'a'; folder names never hold one.
		with self.assertRaises(ValueError):
			_fsenum.name_order(['a\x00', 'a'], [False, False], True)


def junction(link, target):
	_winapi.CreateJunction(str(target), str(link))


def device_junction(link, device):
	"""A mount point to a device path such as \\??\\C:, the volume itself rather than its root."""
	import struct
	from win32file import CreateFile, DeviceIoControl
	from winioctlcon import FSCTL_SET_REPARSE_POINT
	os.mkdir(link)
	substitute, printed = device.encode('utf-16-le'), device[4:].encode('utf-16-le')
	data = struct.pack('<HHHH', 0, len(substitute), len(substitute) + 2, len(printed)) \
		+ substitute + b'\0\0' + printed + b'\0\0'
	# GENERIC_WRITE, OPEN_EXISTING, FILE_FLAG_BACKUP_SEMANTICS | FILE_FLAG_OPEN_REPARSE_POINT
	handle = CreateFile(str(link), 0x40000000, 0, None, 3, 0x02000000 | 0x00200000, None)
	try:
		DeviceIoControl(handle, FSCTL_SET_REPARSE_POINT, struct.pack('<IHH', 0xA0000003, len(data), 0) + data, None)
	finally:
		handle.Close()


def hide(path):
	from win32file import GetFileAttributes, SetFileAttributes
	SetFileAttributes(str(path), GetFileAttributes(str(path)) | FILE_ATTRIBUTE_HIDDEN)


class ScanTest(TestCase):
	"""Live folders: columns against os.stat, the native order, links, refresh reuse, errors."""

	def setUp(self):
		self._temporary = TemporaryDirectory()
		self.folder = Path(self._temporary.name).resolve()
		self.location = 'file://' + str(self.folder).replace('\\', '/')

	def tearDown(self):
		self._temporary.cleanup()

	def scan(self, previous=None, check=lambda: None):
		return listing.scan(self.location, str(self.folder), check, previous)

	def populate(self, count):
		for index in range(count):
			(self.folder / ('file%05d.txt' % index)).write_bytes(b'x' * (index % 7))

	def test_columns_match_os_stat(self):
		self.populate(20)
		for name in ('Stra\u00dfe 2', '\u0130stanbul', '\U0001F600 emoji', '.dot'):
			(self.folder / name).write_bytes(b'payload')
		(self.folder / 'hidden').write_bytes(b'')
		hide(self.folder / 'hidden')
		(self.folder / 'directory').mkdir()
		(self.folder / 'target').mkdir()
		(self.folder / 'target' / 'inside').write_bytes(b'')
		junction(self.folder / 'link', self.folder / 'target')
		(self.folder / 'missing').mkdir()
		junction(self.folder / 'dangling', self.folder / 'missing')
		(self.folder / 'missing').rmdir()
		result = self.scan()
		if result is None:
			self.skipTest('Temporary directory is not on NTFS/ReFS')
		self.assertEqual(sorted(os.listdir(self.folder)), sorted(result.names))
		self.assertIsNotNone(result._native)
		for index, name in enumerate(result.names):
			with self.subTest(name=name):
				own = os.lstat(self.folder / name)
				self.assertEqual(own.st_file_attributes, result.attributes[index])
				self.assertEqual(own.st_ino, int.from_bytes(result.identity(index)[0], 'little'))
				self.assertEqual(own.st_birthtime_ns, result.created_ns[index])
				metadata = own
				if name in ('link', 'dangling'):
					self.assertTrue(own.st_file_attributes & FILE_ATTRIBUTE_REPARSE_POINT)
					try:
						metadata = os.stat(self.folder / name)
					except OSError:
						self.assertEqual('dangling', name)
				self.assertEqual(bool(metadata.st_file_attributes & FILE_ATTRIBUTE_DIRECTORY), result.is_dir[index])
				self.assertEqual(metadata.st_mtime_ns, result.mtimes_ns[index])
				if not result.is_dir[index]:
					self.assertEqual(metadata.st_size, result.sizes[index])
		self.assertEqual(self.folder.stat().st_ino, int.from_bytes(result.scope[1], 'little'))

	def test_link_to_a_device_reports_what_os_stat_reports(self):
		# os.stat follows it to the volume and reports a zeroed block device, not the link's own values.
		link = self.folder / 'volume'
		device_junction(link, '\\??\\' + self.folder.drive)
		try:
			result = self.scan()
			metadata, own = os.stat(link), os.lstat(link)
		finally:
			os.rmdir(link)
		if result is None:
			self.skipTest('Temporary directory is not on NTFS/ReFS')
		self.assertEqual((False, 0, 0), (S_ISDIR(metadata.st_mode), metadata.st_size, metadata.st_mtime_ns))
		self.assertEqual((False, 0, 0), (result.is_dir[0], result.sizes[0], result.mtimes_ns[0]))
		self.assertTrue(own.st_file_attributes & FILE_ATTRIBUTE_DIRECTORY)

	def test_native_order_and_hidden_filter(self):
		from core import Name
		from core.commands import _hidden_file_filter
		names = ['File%d' % index for index in range(30)] + ['file02', 'file2', 'Zeta', 'alpha']
		for name in names:
			(self.folder / name).write_bytes(b'')
		for name in ('dir10', 'Dir9', 'dir010'):
			(self.folder / name).mkdir()
		for name in ('File3', 'dir10'):
			hide(self.folder / name)
		result = self.scan()
		if result is None:
			self.skipTest('Temporary directory is not on NTFS/ReFS')
		hidden = _hidden_file_filter.snapshot_filter()
		for ascending in (True, False):
			with self.subTest(ascending=ascending):
				order = Name().order(result, ascending)
				self.assertEqual('I', order.typecode)
				self.assertEqual(reference_order(result.names, result.is_dir, ascending), list(order))
				visible = hidden.filter_indices(result, order, lambda: None)
				self.assertIsInstance(visible, array)
				self.assertEqual([index for index in order if hidden(result, index)], list(visible))

	def test_projection_keeps_the_native_order_array(self):
		from types import SimpleNamespace
		from core import Name
		from core.commands import _hidden_file_filter
		from fman.impl.model.listing import project
		from fman.impl.widgets import FilterBar
		for name in ('b10', 'B9', 'a', '.hidden'):
			(self.folder / name).write_bytes(b'')
		hide(self.folder / '.hidden')
		result = self.scan()
		if result is None:
			self.skipTest('Temporary directory is not on NTFS/ReFS')
		inactive = FilterBar.snapshot_filter(SimpleNamespace(_matcher=None, _active=False))
		projection = project(result, None, Name(), 0, True,
			(_hidden_file_filter.snapshot_filter(), inactive), lambda: None)
		self.assertIsInstance(projection.visible, array)
		self.assertEqual(['a', 'B9', 'b10'], [result.names[index] for index in projection.visible])
		self.assertEqual({index: row for row, index in enumerate(projection.visible)}, projection.rows)

	def test_empty_folder_and_listings_without_a_table(self):
		from dataclasses import replace
		from core import Name
		from core.commands import _hidden_file_filter
		result = self.scan()
		if result is None:
			self.skipTest('Temporary directory is not on NTFS/ReFS')
		self.assertEqual((), result.names)
		self.assertEqual(b'', result.identities)
		for ascending in (True, False):
			order = Name().order(result, ascending)
			self.assertEqual(array('I'), order)
			self.assertEqual(array('I'), _hidden_file_filter.snapshot_filter().filter_indices(result, order, lambda: None))
		# Only the scan attaches a table; every other listing sorts by keys().
		(self.folder / 'b').write_bytes(b'')
		result = self.scan()
		self.assertEqual(array('I', [0]), Name().order(result, True))
		self.assertIsNone(Name().order(replace(result, labels=('a',)), True))
		self.assertIsNone(Name().order(Listing.create(self.location, ['b']), True))

	def test_unchanged_rescan_returns_previous_and_changes_equal_a_fresh_scan(self):
		from core import Name
		self.populate(_fsenum.SEGMENT_SIZE + 200)
		first = self.scan()
		if first is None:
			self.skipTest('Temporary directory is not on NTFS/ReFS')
		self.assertIs(first, self.scan(first))
		changes = (
			lambda: (self.folder / 'file02100.txt').write_bytes(b'longer content'),
			lambda: (self.folder / 'aaa-first.txt').write_bytes(b''),
			lambda: (self.folder / 'file04200.txt').rename(self.folder / 'zzz-last.txt'),
			lambda: (self.folder / 'file00003.txt').unlink(),
			lambda: hide(self.folder / 'file04000.txt'),
		)
		previous = first
		for step, change in enumerate(changes):
			with self.subTest(step=step):
				change()
				reused, fresh = self.scan(previous), self.scan()
				self.assertIsNot(previous, reused)
				self.assertEqual(fresh, reused)
				self.assertEqual(fresh.identities, reused.identities)
				for ascending in (True, False):
					self.assertEqual(Name().order(fresh, ascending), Name().order(reused, ascending))
				previous = reused
		other = listing.scan(self.location + '/other', str(self.folder), lambda: None, previous)
		self.assertIsNot(previous, other)
		self.assertEqual(self.location + '/other', other.location)

	def test_local_file_system_reuses_its_last_listing(self):
		from core.fs.local import LocalFileSystem
		self.populate(3)
		provider = LocalFileSystem()
		path = self.location[len('file://'):]
		first = provider.scan(path, lambda: None)
		if first._native is None:
			self.skipTest('Temporary directory is not on NTFS/ReFS')
		self.assertIs(first, provider.scan(path, lambda: None))
		(self.folder / 'new.txt').write_bytes(b'')
		second = provider.scan(path, lambda: None)
		self.assertIsNot(first, second)
		self.assertIn('new.txt', second.names)
		del first, second
		self.assertEqual(0, len(provider._native_listings))

	def test_paths_outside_native_scope_return_none(self):
		(self.folder / 'file').write_bytes(b'')
		for path in ('\\\\server\\share\\folder', '\\\\?\\C:\\', 'relative\\folder', str(self.folder / 'file')):
			with self.subTest(path=path):
				self.assertIsNone(listing.scan('file://x', path, lambda: None))

	def test_missing_folder_raises_file_not_found(self):
		with self.assertRaises(FileNotFoundError) as caught:
			listing.scan('file://x', str(self.folder / 'missing'), lambda: None)
		self.assertIn(caught.exception.winerror, (2, 3))

	def test_cancellation_propagates_the_check_exception(self):
		class Stop(Exception):
			pass
		self.populate(_fsenum.SEGMENT_SIZE + 10)
		# Call 1 is Python's check before the native scan; the native calls follow.
		# Every one of them stops the scan, until a scan needs no further call.
		for allowed in range(1000):
			calls = []
			def check():
				calls.append(None)
				if len(calls) > allowed:
					raise Stop()
			try:
				result = self.scan(check=check)
			except Stop:
				continue
			break
		self.assertGreater(allowed, 1)
		self.assertEqual(self.scan(), result)
