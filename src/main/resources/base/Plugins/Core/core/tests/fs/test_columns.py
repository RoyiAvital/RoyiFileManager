from core import Name, Size, Modified
from core.tests import StubFS
from core.tests.fs import StubFileSystem
from fman.url import as_url
from unittest import TestCase

class ColumnTest:
	def setUp(self):
		self._fs = StubFileSystem({
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

		})
		self._column = self.column_class(StubFS(self._fs))
	def assert_is_less(self, left, right, is_ascending=True):
		left_val = self._get_sort_value(left, is_ascending)
		right_val = self._get_sort_value(right, is_ascending)
		self.assertLess(left_val, right_val)
	def assert_is_greater(self, left, right, is_ascending=True):
		self.assertGreater(
			self._get_sort_value(left, is_ascending),
			self._get_sort_value(right, is_ascending),
			"%s is not > %s" % (left, right)
		)
	def check_less_than_chain(self, *chain, is_ascending=True):
		for i, left in enumerate(chain[:-1]):
			right = chain[i + 1]
			self.assert_is_less(left, right, is_ascending)
	def _get_sort_value(self, path, is_ascending):
		url = as_url(path, StubFileSystem.scheme)
		return self._column.get_sort_value(url, is_ascending)

class NameTest(ColumnTest, TestCase):

	column_class = Name

	def test_numeric_boundaries_unicode_and_arbitrary_lengths(self):
		from core import _natural_name_key
		from types import SimpleNamespace
		names = ['file' + digits for digits in ('0', '2', '10', '999999', '1000000', '9' * 99, '1' + '0' * 99, '9' * 5000)]
		self.assertEqual(names, sorted(reversed(names), key=_natural_name_key))
		self.assertEqual(_natural_name_key('file2'), _natural_name_key('file\u0660\u0662'))
		self.assertEqual(_natural_name_key('FILE000'), _natural_name_key('file\u0660'))
		listing = SimpleNamespace(display_names=tuple(names), is_dir=(False,) * len(names))
		for ascending in (False, True):
			keys = self._column.keys(listing, ascending)
			self.assertEqual(names, sorted(names, key=dict(zip(names, keys)).__getitem__))
			for name, key in zip(names[:-1], keys):
				self._fs.touch(name)
				self.assertEqual(key, self._get_sort_value(name, ascending))
	def test_mixed_text_punctuation_and_numeric_ties(self):
		from core import _natural_name_key
		names = ['a', 'a!', 'a-2', 'a.2', 'a0', 'a2', 'a02', 'a2!', 'a2a', 'a10', 'a_', 'ab']
		self.assertEqual(names, sorted(names, key=_natural_name_key))
		self.assertEqual(list(reversed(names)), sorted(reversed(names), key=_natural_name_key, reverse=True))
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
	def assert_is_less(self, left, right, is_ascending=True):
		if not self._fs.exists(left):
			self._fs.touch(left)
		if not self._fs.exists(right):
			self._fs.touch(right)
		super().assert_is_less(left, right, is_ascending)

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