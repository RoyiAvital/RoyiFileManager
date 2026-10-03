from core import Name, Size, Modified
from fman.listing import Listing
from unittest import TestCase

class ColumnTest:
	def setUp(self):
		self._entries = {
			'a': {
				'is_dir': False, 'size': 1, 'mtime': 1473339042.0
			},
			'b': {
				'is_dir': False, 'size': 0, 'mtime': 1473339043.0
			},
			'B': {
				'is_dir': False, 'size': 2, 'mtime': 1473339042.0
			},
			'a_dir': {
				'is_dir': True, 'size': 3, 'mtime': 1473339045.0
			},
			'b_dir': {
				'is_dir': True, 'size': 4, 'mtime': 1473339046.0
			}

		}
		self._column = self.column_class()
	def assert_is_less(self, left, right, is_ascending=True):
		left_val = self._key(left, is_ascending)
		right_val = self._key(right, is_ascending)
		self.assertLess(left_val, right_val)
	def assert_is_greater(self, left, right, is_ascending=True):
		self.assertGreater(
			self._key(left, is_ascending),
			self._key(right, is_ascending),
			"%s is not > %s" % (left, right)
		)
	def check_less_than_chain(self, *chain, is_ascending=True):
		for i, left in enumerate(chain[:-1]):
			right = chain[i + 1]
			self.assert_is_less(left, right, is_ascending)
	def _key(self, path, is_ascending):
		entry = self._entries.get(path, {})
		mtime = entry.get('mtime')
		listing = Listing.create('test://', (path,),
			is_dir=(entry.get('is_dir', False),), sizes=(entry.get('size'),),
			mtimes_ns=(None if mtime is None else int(mtime * 1_000_000_000),))
		return self._column.keys(listing, is_ascending)[0]

class NameTest(ColumnTest, TestCase):

	column_class = Name

	def test_numeric_boundaries_unicode_and_arbitrary_lengths(self):
		from fman.impl.util.natural import natural_key
		names = ['file' + digits for digits in ('0', '2', '10', '999999', '1000000', '9' * 99, '1' + '0' * 99, '9' * 5000)]
		self.assertEqual(names, sorted(reversed(names), key=natural_key))
		self.assertEqual(natural_key('file2'), natural_key('file\u0660\u0662'))
		self.assertEqual(natural_key('FILE000'), natural_key('file\u0660'))
		listing = Listing.create('test://', names)
		for ascending in (False, True):
			keys = self._column.keys(listing, ascending)
			self.assertEqual(names, sorted(names, key=dict(zip(names, keys)).__getitem__))
			self.assertEqual((ascending,) * len(names), tuple(key[0] for key in keys))
	def test_mixed_text_punctuation_and_numeric_ties(self):
		from fman.impl.util.natural import natural_key
		names = ['a', 'a!', 'a-2', 'a.2', 'a0', 'a2', 'a02', 'a2!', 'a2a', 'a10', 'a_', 'ab']
		self.assertEqual(names, sorted(names, key=natural_key))
		self.assertEqual(list(reversed(names)), sorted(reversed(names), key=natural_key, reverse=True))
	def test_less(self):
		self.assert_is_less('a', 'b')
	def test_less_numbers(self):
		self.assert_is_less('foo 2.txt', 'foo 10.txt')
		self.assert_is_less('2 foo.txt', '10 foo.txt')
		self.assert_is_less('2', '10')
		self.assert_is_less('2', 'a1.txt')
		self.assert_is_less('file.txt', 'file1.txt')
		self.assert_is_less('02 Google Apps.pdf', '15 Tarsnap.pdf')
	def test_greater(self):
		self.assert_is_greater('b', 'a')
	def test_upper_case(self):
		self.assert_is_less('a', 'B')
	def test_directories_before_files(self):
		self.check_less_than_chain('a_dir', 'b_dir', 'a')
	def test_descending(self):
		self.check_less_than_chain(
			'a', 'b', 'a_dir', 'b_dir',
			is_ascending=False
		)

class SizeTest(ColumnTest, TestCase):

	column_class = Size

	def test_less(self):
		self.assert_is_less('b', 'a')
	def test_greater(self):
		self.assert_is_greater('a', 'b')
	def test_descending(self):
		# Qt expects the implementation of less_than to generally be independent
		# of the sort order:
		self.assert_is_less('b', 'a', False)
	def test_directories_by_name_before_files(self):
		self.check_less_than_chain('a_dir', 'b_dir', 'b')
	def test_directories_by_name_before_files_descending(self):
		self.check_less_than_chain(
			'b', 'a', 'b_dir', 'a_dir', is_ascending=False
		)

class ModifiedTest(ColumnTest, TestCase):

	column_class = Modified

	def test_less(self):
		self.assert_is_less('a', 'b')
	def test_greater(self):
		self.assert_is_greater('b', 'a')
	def test_descending(self):
		# Qt expects the implementation of less_than to generally be independent
		# of the sort order:
		self.assert_is_less('a', 'b', False)
	def test_directories_before_files(self):
		self.check_less_than_chain('a_dir', 'b_dir', 'a')