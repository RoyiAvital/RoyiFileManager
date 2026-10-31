from fman.fs import FileSystem, cached
from fman.impl.plugins.mother_fs import MotherFileSystem
from fman_unittest.impl.model import StubFileSystem
from threading import Thread, Lock
from time import sleep
from unittest import TestCase

class MotherFileSystemTest(TestCase):
	def test_optional_columns_skip_unknown_and_duplicates(self):
		mother = MotherFileSystem()
		column = object()
		mother.register_column('size.Column', column)
		with self.assertLogs('fman.impl.plugins.mother_fs', level='WARNING'):
			self.assertEqual((column,), mother.get_optional_columns(['missing.Column', 'size.Column', 'size.Column']))
	def test_exists(self):
		fs = StubFileSystem({
			'a': {}
		})
		mother_fs = self._create_mother_fs(fs)
		self.assertTrue(mother_fs.exists('stub://a'))
		self.assertFalse(mother_fs.exists('stub://b'))
		mother_fs.touch('stub://b')
		self.assertTrue(mother_fs.exists('stub://b'))
	def test_delete_removes_from_parent_listing(self):
		fs = StubFileSystem({
			'a': {
				'is_dir': True, 'files': ['b']
			},
			'a/b': {}
		})
		mother_fs = self._create_mother_fs(fs)
		self.assertEqual(['b'], list(mother_fs.iterdir('stub://a')))
		mother_fs.delete('stub://a/b')
		self.assertEqual([], list(mother_fs.iterdir('stub://a')))
		self.assertFalse(mother_fs.exists('stub://a/b'))
	def test_delete_removes_children(self):
		fs = StubFileSystem({
			'': {'is_dir': True, 'files': ['a']},
			'a': {
				'is_dir': True, 'files': ['b']
			},
			'a/b': {}
		})
		mother_fs = self._create_mother_fs(fs)
		# Put in cache:
		mother_fs.is_dir('stub://a/b')
		mother_fs.delete('stub://a')
		self.assertFalse(mother_fs.exists('stub://a/b'))
	def test_default_prepare_trash_moves_to_trash(self):
		fs = TrashOnlyFileSystem()
		mother_fs = self._create_mother_fs(fs)
		tasks = mother_fs.prepare_trash('trash://a/b')
		self.assertEqual(1, len(tasks))
		self.assertEqual('Deleting b', tasks[0].get_title())
		tasks[0]()
		self.assertEqual(['a/b'], fs.trashed)
		self.assertEqual([], fs.deleted)
	def test_default_prepare_trash_requires_move_to_trash(self):
		fs = StubFileSystem({'a': {}})
		mother_fs = self._create_mother_fs(fs)
		with self.assertRaises(NotImplementedError):
			mother_fs.prepare_trash('stub://a')
	def test_iterdir_is_lazy_and_uncached(self):
		fs = LazyFileSystem({'a': ['b', 'c']})
		mother_fs = self._create_mother_fs(fs)
		names = mother_fs.iterdir('lazy://a')
		mother_fs.notify_file_added('lazy://a/b')
		self.assertEqual(0, fs.num_yielded)
		self.assertEqual(['b', 'c'], list(names))
		fs._dirs['a'].append('d')
		self.assertEqual(['b', 'c', 'd'], list(mother_fs.iterdir('lazy://a')))
	def test_no_concurrent_is_dir_queries(self):
		fs = FileSystemCountingIsdirCalls()
		mother_fs = self._create_mother_fs(fs)
		def _new_thread():
			return Thread(target=mother_fs.is_dir, args=('fscic://test',))
		t1, t2 = _new_thread(), _new_thread()
		t1.start()
		t2.start()
		t1.join()
		t2.join()
		self.assertEqual(1, fs.num_is_dir_calls)
	def test_permission_error(self):
		fs = FileSystemRaisingError()
		mother_fs = self._create_mother_fs(fs)
		# Put 'foo' in cache:
		mother_fs.is_dir('fsre://foo')
		with self.assertRaises(PermissionError):
			mother_fs.iterdir('fsre://foo')
	def test_is_dir_file(self):
		fs = StubFileSystem({
			'a': {}
		})
		mother_fs = self._create_mother_fs(fs)
		self.assertFalse(mother_fs.is_dir('stub://a'))
	def test_is_dir_nonexistent(self):
		fs = StubFileSystem({})
		mother_fs = self._create_mother_fs(fs)
		url = 'stub://non-existent'
		with self.assertRaises(FileNotFoundError):
			mother_fs.is_dir(url)
		self.assertFalse(mother_fs.exists(url))
		mother_fs.mkdir(url)
		self.assertTrue(mother_fs.is_dir(url))
	def test_remove_child(self):
		fs = StubFileSystem({
			'a': {'is_dir': True}
		})
		mother_fs = self._create_mother_fs(fs)
		self.assertTrue(mother_fs.is_dir('stub://a'))
		mother_fs.remove_child(fs.scheme)
		mother_fs.add_child(fs.scheme, StubFileSystem({}))
		with self.assertRaises(FileNotFoundError):
			mother_fs.is_dir('stub://a')
	def test_mkdir_triggers_file_added(self):
		mother_fs = self._create_mother_fs(StubFileSystem({}))
		url = 'stub://test'
		with self.assertRaises(FileNotFoundError):
			# This should not put `url` in cache:
			mother_fs.is_dir(url)
		files_added = []
		def on_file_added(url_):
			files_added.append(url_)
		mother_fs.file_added.add_callback(on_file_added)
		mother_fs.mkdir(url)
		self.assertEqual([url], files_added)
	def test_relative_paths(self):
		mother_fs = self._create_mother_fs(StubFileSystem({
			'a': {'is_dir': True},
			'a/b': {'is_dir': True}
		}))
		self.assertTrue(mother_fs.is_dir('stub://a/b/..'))
		mother_fs.move('stub://a', 'stub://b')
		with self.assertRaises(FileNotFoundError):
			mother_fs.is_dir('stub://a/b/..')
		mother_fs.touch('stub://a/../c')
		self.assertTrue(mother_fs.exists('stub://c'))
		mother_fs.mkdir('stub://a/../dir')
		self.assertTrue(mother_fs.is_dir('stub://a/../dir'))
		self.assertTrue(mother_fs.is_dir('stub://dir'))
		mother_fs.move('stub://a/b', 'stub://a/../b')
		self.assertTrue(mother_fs.exists('stub://b'))
	def test_notify_file_changed_clears_cached_children_before_callbacks(self):
		fs = ValuesFileSystem({'folder/file': 'old'})
		mother_fs = self._create_mother_fs(fs)
		url = 'values://folder/file'
		self.assertEqual('old', mother_fs.query(url, 'stat'))
		fs.values['folder/file'] = 'new'
		self.assertEqual('old', mother_fs.query(url, 'stat'))
		seen = []
		mother_fs.add_file_changed_callback('values://folder', lambda _: seen.append(mother_fs.query(url, 'stat')))
		mother_fs.notify_file_changed('values://folder')
		self.assertEqual(['new'], seen)
	def _create_mother_fs(self, fs):
		result = MotherFileSystem()
		result.add_child(fs.scheme, fs)
		return result

class ValuesFileSystem(FileSystem):

	scheme = 'values://'

	def __init__(self, values):
		super().__init__()
		self.values = values
	@cached
	def stat(self, path):
		return self.values[path]

class FileSystemCountingIsdirCalls(FileSystem):

	scheme = 'fscic://'

	def __init__(self):
		super().__init__()
		self.num_is_dir_calls = 0
		self._num_is_dir_calls_lock = Lock()
	@cached # prevents execution by multiple threads at the same time
	def is_dir(self, _):
		with self._num_is_dir_calls_lock:
			self.num_is_dir_calls += 1
		# Give other threads a chance to run:
		sleep(.1)
		return True

class FileSystemRaisingError(FileSystem):

	scheme = 'fsre://'

	def is_dir(self, path):
		return True
	def iterdir(self, path):
		raise PermissionError(path)

class LazyFileSystem(FileSystem):

	scheme = 'lazy://'

	def __init__(self, dirs):
		super().__init__()
		self._dirs = dirs
		self.num_yielded = 0
	def iterdir(self, path):
		for name in self._dirs[path]:
			self.num_yielded += 1
			yield name

class TrashOnlyFileSystem(FileSystem):

	scheme = 'trash://'

	def __init__(self):
		super().__init__()
		self.trashed = []
		self.deleted = []
	def move_to_trash(self, path):
		self.trashed.append(path)
	def delete(self, path):
		self.deleted.append(path)
