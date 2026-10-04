"""Tests for the native directory-record parser `_fsparser` (Done/FSParser.md).

The module under test is the one the scanner loaded (`listing._fsparser`), or
the file named by `FSPARSER_PYD`; every parser test skips when neither exists.
"""

import importlib.machinery
import importlib.util
import os
import sys
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase, skipUnless

from core.fs.local.windows import listing

REPOSITORY = Path(__file__).resolve().parents[9]
NATIVE_SOURCES = REPOSITORY / 'src' / 'main' / 'c'
INT64_MIN, INT64_MAX = -2**63, 2**63 - 1
EPOCH = listing._EPOCH
FAST_MIN = -(2**63 // 100) + EPOCH  # C integer division truncates toward zero
FAST_MAX = INT64_MAX // 100 + EPOCH
FILE_ATTRIBUTE_DIRECTORY = 0x10
FILE_ATTRIBUTE_REPARSE_POINT = 0x400
LINK_TAGS = listing._LINK_TAGS
CLOUD_TAG = 0x9000601A
APP_EXEC_LINK_TAG = 0x8000001B
IDENTITY = bytes(range(16))


def _load():
	override = os.environ.get('FSPARSER_PYD')
	if not override:
		return listing._fsparser
	loader = importlib.machinery.ExtensionFileLoader('_fsparser', override)
	spec = importlib.util.spec_from_file_location('_fsparser', override, loader=loader)
	module = importlib.util.module_from_spec(spec)
	loader.exec_module(module)
	return module


_fsparser = _load() if os.name == 'nt' else None


@skipUnless((NATIVE_SOURCES / 'fsparser.sha256').is_file(), 'repository checkout required')
class SourceBinaryPairingTest(TestCase):
	"""src/main/c/_fsparser.pyd is the build of src/main/c/fsparser.c recorded in fsparser.sha256."""

	def test_hashes_match_and_scanner_loaded_that_binary(self):
		sys.path.insert(0, str(NATIVE_SOURCES))
		try:
			from check_hashes import check
			from fsparser_hashes import BINARY, is_lfs_pointer
		finally:
			sys.path.remove(str(NATIVE_SOURCES))
		self.assertEqual([], check())
		self.assertFalse(is_lfs_pointer(BINARY))
		if os.name == 'nt':
			self.assertIsNotNone(listing._fsparser, 'scanner did not load the committed binary')
			self.assertEqual(str(BINARY).lower(), listing._fsparser.__file__.lower())


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
	names, directories, sizes, mtimes, attributes, created, tags = ([] for _ in range(7))
	identities = bytearray()
	for data in batches:
		for name, size, modified, own_attributes, tag, identity, birth in listing.records(data):
			names.append(name)
			directories.append(bool(own_attributes & FILE_ATTRIBUTE_DIRECTORY))
			sizes.append(size)
			mtimes.append(modified)
			attributes.append(own_attributes)
			created.append(birth)
			identities.extend(identity)
			tags.append(tag)
	return names, directories, sizes, mtimes, attributes, created, bytes(identities), tags


def empty_columns():
	return [[] for _ in range(6)] + [bytearray(), []]


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
}

MIXED = batch(
	record('.', attributes=FILE_ATTRIBUTE_DIRECTORY),
	record('..', attributes=FILE_ATTRIBUTE_DIRECTORY),
	record('file.txt', size=1234, modified=EPOCH + 10**9, created=EPOCH - 5),
	record('folder', attributes=FILE_ATTRIBUTE_DIRECTORY | 0x2),
	record('link', attributes=FILE_ATTRIBUTE_REPARSE_POINT, tag=0xA000000C),
	record('\U0001F600 emoji'),
	record('lone', name_bytes='a\ud800b'.encode('utf-16-le', 'surrogatepass')),
	record('bom', name_bytes='\ufeffname'.encode('utf-16-le')),
	record('big', size=INT64_MAX, identity=b'\xff' * 16),
	record('trailing.', size=1),
	record('trailing ', size=2),
	record('Case.txt'),
	record('case.txt'),
	record('cloud.docx', attributes=FILE_ATTRIBUTE_REPARSE_POINT | 0x20, tag=CLOUD_TAG),
	record('app.exe', attributes=FILE_ATTRIBUTE_REPARSE_POINT | 0x20, tag=APP_EXEC_LINK_TAG),
)
MIXED_LINK_INDEX = 2
MIXED_COUNT = 13

FILETIMES = (INT64_MIN, INT64_MIN + 1, FAST_MIN - 1, FAST_MIN, FAST_MIN + 1,
	-1, 0, EPOCH - 1, EPOCH, EPOCH + 1,
	FAST_MAX - 1, FAST_MAX, FAST_MAX + 1, INT64_MAX - 1, INT64_MAX)


@skipUnless(_fsparser is not None, '_fsparser extension not available')
class ParserCases:
	"""Shared contract; subclasses implement parse(*batches) -> 8 columns."""

	def parse(self, *batches):
		raise NotImplementedError

	def assertParity(self, *batches):
		expected = python_parse(*batches)
		actual = self.parse(*batches)
		self.assertEqual(expected[6], actual[6], 'identities')
		for label, left, right in zip(
			('names', 'is_dir', 'sizes', 'mtimes', 'attributes', 'created', 'tags'),
			expected[:6] + expected[7:], actual[:6] + actual[7:]):
			self.assertEqual(list(left), list(right), label)
			self.assertEqual([type(v) for v in left], [type(v) for v in right], label)

	def test_header_size(self):
		self.assertEqual(_fsparser.HEADER_SIZE, listing._RECORD.size)

	def test_parity_mixed_records(self):
		self.assertParity(MIXED)

	def test_parity_across_batches(self):
		self.assertParity(*(batch(*(record('n%05d' % (b * 600 + i)) for i in range(600))) for b in range(5)))

	def test_single_record_and_dot_only(self):
		self.assertParity(batch(record('only')))
		self.assertParity(batch(record('.'), record('..')))

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
					self.parse(batch(record('first')), data)
				self.assertEqual(str(actual.exception), str(expected.exception))

	def test_rejects_non_bytes(self):
		data = batch(record('a'))
		for bad in (bytearray(data), memoryview(data), data.decode('latin-1')):
			with self.assertRaises(TypeError):
				self.parse(bad)

	def test_live_directory_parity(self):
		with TemporaryDirectory() as root:
			for index in range(300):
				Path(root, 'file-%03d-\u00e9.txt' % index).write_bytes(b'x' * index)
			Path(root, 'sub').mkdir()
			with listing.NativeDirectory(root) as directory:
				if directory.scope() is None:
					self.skipTest('Temporary directory is not on NTFS/ReFS')
				batches = list(directory.batches(lambda: None))
			self.assertGreater(len(batches), 0)
			self.assertParity(*batches)


class ParseRecordsTest(ParserCases, TestCase):

	def parse(self, *batches):
		return _fsparser.parse_records(list(batches))

	def test_accepts_any_sequence_and_empty(self):
		self.assertEqual(_fsparser.parse_records(()), ([], [], [], [], [], [], b'', []))
		self.assertEqual(_fsparser.parse_records(iter([batch(record('a'))]))[0], ['a'])
		with self.assertRaises(TypeError):
			_fsparser.parse_records(batch(record('a')))


class ParseBatchTest(ParserCases, TestCase):

	def parse(self, *batches):
		columns = empty_columns()
		for data in batches:
			_fsparser.parse_batch(data, *columns)
		return tuple(columns[:6]) + (bytes(columns[6]),) + (columns[7],)

	def test_returns_count_and_appends_after_existing_entries(self):
		columns = empty_columns()
		columns[0].append('existing')
		columns[6].extend(b'\1' * 16)
		count = _fsparser.parse_batch(batch(record('a'), record('b')), *columns)
		self.assertEqual(count, 2)
		self.assertEqual(columns[0], ['existing', 'a', 'b'])
		self.assertEqual(bytes(columns[6]), b'\1' * 16 + IDENTITY * 2)
		self.assertEqual(len(columns[1]), 2)

	def test_malformed_leaves_columns_unchanged(self):
		for label, data in MALFORMED.items():
			with self.subTest(label):
				columns = empty_columns()
				columns[0].append('kept')
				with self.assertRaises(ValueError):
					_fsparser.parse_batch(data, *columns)
				self.assertEqual(columns[0], ['kept'])
				self.assertEqual([len(column) for column in columns[1:]], [0] * 7)

	def test_rejects_wrong_column_types(self):
		data = batch(record('a'))
		for position, bad in ((6, b''), (2, ()), (0, None)):
			columns = empty_columns()
			columns[position] = bad
			with self.assertRaises(TypeError):
				_fsparser.parse_batch(data, *columns)


class ColumnsTest(ParserCases, TestCase):

	def parse(self, *batches):
		columns = _fsparser.Columns(LINK_TAGS)
		for data in batches:
			columns.add(data)
		return columns.finish()

	def test_frozen_finish_returns_tuples(self):
		columns = _fsparser.Columns(LINK_TAGS)
		columns.add(MIXED)
		result = columns.finish(frozen=True)
		self.assertEqual([type(column) for column in result], [tuple] * 6 + [bytes, tuple])
		self.assertEqual(result, tuple(
			tuple(column) if index != 6 else column for index, column in enumerate(python_parse(MIXED))))

	def test_add_reports_only_link_tags(self):
		columns = _fsparser.Columns(LINK_TAGS)
		self.assertEqual(len(columns), 0)
		self.assertEqual(columns.add(MIXED), [MIXED_LINK_INDEX])
		self.assertEqual(len(columns), MIXED_COUNT)
		junction = batch(record('plain'), record('junction', attributes=0x410, tag=0xA0000003))
		self.assertEqual(columns.add(junction), [MIXED_COUNT + 1])
		self.assertEqual(columns.entry(MIXED_LINK_INDEX), ('link', FILE_ATTRIBUTE_REPARSE_POINT, 0xA000000C))
		self.assertEqual(columns.entry(MIXED_COUNT + 1), ('junction', 0x410, 0xA0000003))
		with self.assertRaises(IndexError):
			columns.entry(MIXED_COUNT + 2)
		# Cloud and AppExecLink reparse points keep their own metadata untouched.
		names, is_dir, sizes, _, attributes, _, _, tags = columns.finish()
		cloud = names.index('cloud.docx')
		self.assertEqual((is_dir[cloud], sizes[cloud], tags[cloud]), (False, 0, CLOUD_TAG))

	def test_link_tags_argument(self):
		self.assertEqual(_fsparser.Columns(()).add(MIXED), [])
		self.assertEqual(_fsparser.Columns([CLOUD_TAG]).add(MIXED), [MIXED_COUNT - 2])
		self.assertEqual(_fsparser.Columns(link_tags=(APP_EXEC_LINK_TAG, 0xA000000C)).add(MIXED),
			[MIXED_LINK_INDEX, MIXED_COUNT - 1])
		with self.assertRaises(TypeError):
			_fsparser.Columns()
		for bad in (1, ('x',), (None,)):
			with self.assertRaises(TypeError):
				_fsparser.Columns(bad)
		for bad in ((-1,), (2**32,)):
			with self.assertRaises(OverflowError):
				_fsparser.Columns(bad)

	def test_patch_replaces_link_metadata(self):
		columns = _fsparser.Columns(LINK_TAGS)
		columns.add(MIXED)
		columns.patch(MIXED_LINK_INDEX, True, 77, 123456789)
		with self.assertRaises(IndexError):
			columns.patch(MIXED_COUNT, True, 0, 0)
		names, is_dir, sizes, mtimes, attributes, created, identities, tags = columns.finish()
		self.assertEqual(
			(names[MIXED_LINK_INDEX], is_dir[MIXED_LINK_INDEX], sizes[MIXED_LINK_INDEX],
				mtimes[MIXED_LINK_INDEX], attributes[MIXED_LINK_INDEX], tags[MIXED_LINK_INDEX]),
			('link', True, 77, 123456789, FILE_ATTRIBUTE_REPARSE_POINT, 0xA000000C))
		self.assertEqual(python_parse(MIXED)[5], created)

	def test_patch_enforces_trusted_invariants(self):
		class Int(int):
			pass
		columns = _fsparser.Columns(LINK_TAGS)
		columns.add(MIXED)
		for arguments in ((1, 0, 0), (True, True, 0), (True, 0, True), (True, Int(1), 0),
			(True, 0, Int(1)), (True, 1.0, 0), (True, None, 0)):
			with self.subTest(arguments):
				with self.assertRaises(TypeError):
					columns.patch(MIXED_LINK_INDEX, *arguments)
		with self.assertRaises(ValueError):
			columns.patch(MIXED_LINK_INDEX, True, -1, 0)
		columns.patch(MIXED_LINK_INDEX, False, 0, -5)
		columns.patch(MIXED_LINK_INDEX, False, 2**70, 2**70)
		_, is_dir, sizes, mtimes, *_ = columns.finish()
		self.assertEqual((is_dir[MIXED_LINK_INDEX], sizes[MIXED_LINK_INDEX], mtimes[MIXED_LINK_INDEX]),
			(False, 2**70, 2**70))

	def test_malformed_keeps_previous_entries(self):
		for label, data in MALFORMED.items():
			with self.subTest(label):
				columns = _fsparser.Columns(LINK_TAGS)
				columns.add(batch(record('kept')))
				with self.assertRaises(ValueError):
					columns.add(data)
				self.assertEqual(len(columns), 1)
				self.assertEqual(columns.finish()[0], ['kept'])

	def test_rejects_reuse(self):
		data = batch(record('a'))
		columns = _fsparser.Columns(LINK_TAGS)
		columns.add(data)
		columns.finish()
		self.assertEqual(len(columns), 0)
		for call in (lambda: columns.add(data), lambda: columns.finish(), lambda: columns.patch(0, True, 0, 0)):
			with self.assertRaises(ValueError):
				call()
		with self.assertRaises(IndexError):
			columns.entry(0)

	def test_discard_without_finish_releases(self):
		columns = _fsparser.Columns(LINK_TAGS)
		for _ in range(3):
			columns.add(batch(*(record('x%04d' % i) for i in range(500))))
		del columns


@skipUnless(_fsparser is not None, '_fsparser extension not available')
class NaturalKeysTest(TestCase):

	EDGE_NAMES = ('File2.txt', 'file02.txt', 'file10.txt', 'a' + '9' * 80, '0', '000', 'x0000001y',
		'Stra\u00dfe_caf\u00e9_CAF\u00c9_12', 'v\u0662\u0663', 'v\uff12', '\u0130stanbul 5', 'K 7',
		'lone\udc80 3', '\U0001F600 42', '\U0001D7CE\U0001D7D7', '', '\u0660\u0660\u0661\u0662\u0663',
		'1234567', '12345678901234567890' * 3, 'ab\u0665\u0666cd', '\xff\xfe 1', '\u0100 2')

	@staticmethod
	def reference(names, is_dir, ascending):
		from fman.impl.util.natural import natural_key
		return tuple(('1' if d ^ ascending else '0') + natural_key(name) for name, d in zip(names, is_dir))

	def test_matches_python_reference_on_edge_names(self):
		is_dir = [index % 3 == 0 for index in range(len(self.EDGE_NAMES))]
		for ascending in (True, False):
			keys = _fsparser.natural_keys(self.EDGE_NAMES, is_dir, ascending)
			self.assertIsInstance(keys, tuple)
			self.assertEqual(self.reference(self.EDGE_NAMES, is_dir, ascending), keys)

	def test_matches_python_reference_on_every_code_point(self):
		import unicodedata
		self.assertEqual(unicodedata.unidata_version, _fsparser.UNICODE_VERSION)
		for start in range(0, 0x110000, 0x10000):
			names = [chr(code) for code in range(start, start + 0x10000)]
			flags = [False] * len(names)
			self.assertEqual(self.reference(names, flags, True), _fsparser.natural_keys(names, flags, True))

	def test_accepts_sequences_and_truthy_flags(self):
		keys = _fsparser.natural_keys(iter(['b', 'a']), (1, 0), True)
		self.assertEqual(('0b', '1a'), keys)  # directories sort first when ascending
		self.assertEqual((), _fsparser.natural_keys([], [], False))

	def test_empty_names_in_any_position(self):
		self.assertEqual(('1',), _fsparser.natural_keys(('',), (False,), True))
		self.assertEqual(('1', '1a', '1'), _fsparser.natural_keys(('', 'a', ''), (False,) * 3, True))
		self.assertEqual(('0', '1\xe9'), _fsparser.natural_keys(('', '\xc9'), (False, True), False))

	def test_rejects_bad_arguments(self):
		with self.assertRaises(ValueError):
			_fsparser.natural_keys(['a', 'b'], [False], True)
		for names in (['a', 1], ['a', b'b'], [None]):
			with self.assertRaises(TypeError):
				_fsparser.natural_keys(names, [False] * len(names), True)
		with self.assertRaises(TypeError):
			_fsparser.natural_keys(['a'], [False])

