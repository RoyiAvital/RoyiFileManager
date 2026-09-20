"""Acceptance tests for the Improve Pane Scan "lazy identity stat" design.

Design under test (Plan/ImprovePaneScan.md, reviewed alternative):
LocalFileSystem.iterdir enumerates with os.scandir and seeds the existing
'stat' cache for each ordinary entry with a LazyStat proxy built from
DirEntry.stat(). Display fields come from the enumeration; st_dev, st_ino and
st_nlink trigger one real os.stat on first access. Reparse points are not
seeded and keep the existing full-stat path. Every test skips until
core.fs.local exposes LazyStat, so the module is safe in the current suite.
"""

from core import LocalFileSystem
from core.fs.local import MoveByCopying
from core.tests import SYMLINKS_SUPPORTED
from fman import PLATFORM
from fman.url import as_url, join, splitscheme
from pathlib import Path
from stat import S_ISDIR
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest import TestCase, skipUnless
from unittest.mock import patch

import os

try:
	from core.fs.local import LazyStat
except ImportError:
	LazyStat = None

IDENTITY_FIELDS = ('st_dev', 'st_ino', 'st_nlink')
DISPLAY_FIELDS = (
	'st_mode', 'st_size', 'st_mtime', 'st_mtime_ns', 'st_atime', 'st_ctime'
)


def _urlpath(file_path):
	return splitscheme(as_url(str(file_path)))[1]


class _CountingStat:
	"""Wrap os.stat, counting calls that resolve to paths below `root`."""

	def __init__(self, root):
		self._root = os.path.normcase(str(root))
		self._real = os.stat
		self.calls = []

	def __call__(self, path, *args, **kwargs):
		if os.path.normcase(str(path)).startswith(self._root):
			self.calls.append(str(path))
		return self._real(path, *args, **kwargs)


@skipUnless(LazyStat is not None, 'Improve Pane Scan is not implemented yet')
class ScanMetadataTest(TestCase):
	def setUp(self):
		self._fs = LocalFileSystem()
		self._tmp = TemporaryDirectory()
		self.root = Path(self._tmp.name)
		self.addCleanup(self._tmp.cleanup)
		(self.root / 'report.txt').write_bytes(b'x' * 1234)
		(self.root / 'empty.bin').write_bytes(b'')
		(self.root / 'sub').mkdir()
		(self.root / 'sub' / 'nested.txt').write_bytes(b'y' * 10)
		(self.root / 'Ünïcode ✓.txt').write_bytes(b'z' * 7)
		self.dir_path = _urlpath(self.root)

	def _child(self, name):
		return self.dir_path + '/' + name

	def _scan(self):
		return list(self._fs.iterdir(self.dir_path))

	# --- Enumeration ------------------------------------------------------

	def test_iterdir_lists_the_same_names_as_listdir(self):
		self.assertEqual(sorted(os.listdir(self.root)), sorted(self._scan()))

	def test_iterdir_returns_a_list_compatible_with_host_listing_cache(self):
		# MotherFileSystem mutates cached listings with .remove()/.append().
		names = self._fs.iterdir(self.dir_path)
		names.append('added.txt')
		names.remove('added.txt')

	# --- Display metadata without per-entry os.stat -----------------------

	def test_display_queries_after_scan_perform_no_path_stat(self):
		counter = _CountingStat(self.root)
		with patch('os.stat', counter):
			self._scan()
			self.assertEqual(1234, self._fs.size_bytes(self._child('report.txt')))
			self.assertEqual(0, self._fs.size_bytes(self._child('empty.bin')))
			self.assertTrue(self._fs.is_dir(self._child('sub')))
			self.assertFalse(self._fs.is_dir(self._child('report.txt')))
			self.assertEqual(7, self._fs.size_bytes(self._child('Ünïcode ✓.txt')))
			self._fs.modified_datetime(self._child('report.txt'))
		self.assertEqual([], counter.calls)

	def test_display_fields_equal_a_full_stat_for_stable_entries(self):
		self._scan()
		for name in ('report.txt', 'empty.bin', 'sub', 'Ünïcode ✓.txt'):
			seeded = self._fs.stat(self._child(name))
			full = os.stat(self.root / name)
			for field in DISPLAY_FIELDS:
				self.assertEqual(
					getattr(full, field), getattr(seeded, field), (name, field)
				)
			self.assertEqual(S_ISDIR(full.st_mode), S_ISDIR(seeded.st_mode))

	def test_seeded_stat_exposes_windows_attributes(self):
		self._scan()
		seeded = self._fs.stat(self._child('report.txt'))
		if PLATFORM == 'Windows':
			self.assertEqual(
				os.stat(self.root / 'report.txt').st_file_attributes,
				seeded.st_file_attributes
			)
		for field in ('st_ctime', 'st_atime', 'st_mtime_ns'):
			self.assertTrue(hasattr(seeded, field), field)

	# --- Identity fields upgrade lazily -----------------------------------

	def test_identity_fields_trigger_exactly_one_full_stat_and_memoize(self):
		self._scan()
		counter = _CountingStat(self.root)
		with patch('os.stat', counter):
			seeded = self._fs.stat(self._child('report.txt'))
			self.assertEqual([], counter.calls)
			identity = tuple(getattr(seeded, field) for field in IDENTITY_FIELDS)
			self.assertEqual(1, len(counter.calls))
			again = tuple(getattr(seeded, field) for field in IDENTITY_FIELDS)
			self.assertEqual(1, len(counter.calls), 'identity must be memoized')
		full = os.stat(self.root / 'report.txt')
		self.assertEqual(identity, again)
		self.assertEqual(
			(full.st_dev, full.st_ino, full.st_nlink), identity
		)
		self.assertTrue(full.st_dev and full.st_ino, 'fixture lacks identity')

	def test_cached_proxy_is_reused_between_queries(self):
		self._scan()
		first = self._fs.stat(self._child('report.txt'))
		second = self._fs.stat(self._child('report.txt'))
		self.assertIs(first, second)

	# --- Operations that depend on identity -------------------------------

	def test_samefile_recognizes_hard_links_after_scan(self):
		try:
			os.link(self.root / 'report.txt', self.root / 'alias.txt')
		except OSError as error:
			self.skipTest('hard links unavailable: %s' % error)
		self._scan()
		self.assertTrue(self._fs.samefile(
			self._child('report.txt'), self._child('alias.txt')
		))
		self.assertFalse(self._fs.samefile(
			self._child('report.txt'), self._child('empty.bin')
		))

	def test_samefile_does_not_fall_back_to_path_comparison(self):
		# LocalFileSystem.samefile compares resolved paths only when identity is
		# zero; a seeded proxy must never present zero identity.
		self._scan()
		with patch.object(self._fs, 'resolve', side_effect=AssertionError):
			self.assertTrue(self._fs.samefile(
				self._child('report.txt'), self._child('report.txt')
			))

	def test_prepare_move_on_same_device_uses_rename_after_scan(self):
		(self.root / 'dest').mkdir()
		self._scan()
		self._fs.iterdir(self._child('dest'))
		tasks = list(self._fs.prepare_move(
			join(as_url(str(self.root)), 'report.txt'),
			join(as_url(str(self.root)), 'dest', 'report.txt')
		))
		self.assertEqual(1, len(tasks))
		self.assertNotIsInstance(tasks[0], MoveByCopying)
		tasks[0]()
		self.assertTrue((self.root / 'dest' / 'report.txt').is_file())
		self.assertFalse((self.root / 'report.txt').exists())

	def test_prepare_move_across_devices_copies_when_identity_differs(self):
		(self.root / 'dest').mkdir()
		self._scan()
		dest_parent = self._child('dest')
		real = self._fs.stat(dest_parent)
		other_device = SimpleNamespace(
			st_dev=real.st_dev + 1, st_ino=real.st_ino, st_nlink=1,
			st_mode=real.st_mode, st_size=real.st_size, st_mtime=real.st_mtime
		)
		self._fs.cache.put(dest_parent, 'stat', other_device)
		tasks = list(self._fs.prepare_move(
			join(as_url(str(self.root)), 'report.txt'),
			join(as_url(str(self.root)), 'dest', 'report.txt')
		))
		self.assertEqual(1, len(tasks))
		self.assertIsInstance(tasks[0], MoveByCopying)

	# --- Reparse points keep the full-stat path ---------------------------

	@skipUnless(SYMLINKS_SUPPORTED, 'Symbolic links require Windows privilege')
	def test_symlinks_are_not_seeded_and_follow_the_target(self):
		(self.root / 'link.txt').symlink_to(self.root / 'report.txt')
		(self.root / 'broken.txt').symlink_to(self.root / 'missing.txt')
		self._scan()
		with self.assertRaises(KeyError):
			self._fs.cache.get(self._child('link.txt'), 'stat')
		self.assertEqual(1234, self._fs.size_bytes(self._child('link.txt')))
		self.assertEqual(
			os.lstat(self.root / 'broken.txt').st_size,
			self._fs.stat(self._child('broken.txt')).st_size
		)
		self.assertFalse(self._fs.is_dir(self._child('broken.txt')))

	@skipUnless(SYMLINKS_SUPPORTED, 'Symbolic links require Windows privilege')
	def test_directory_symlink_reports_directory_of_target(self):
		(self.root / 'sublink').symlink_to(self.root / 'sub', target_is_directory=True)
		self._scan()
		self.assertTrue(self._fs.is_dir(self._child('sublink')))

	# --- Invalidation -----------------------------------------------------

	def test_cache_clear_of_directory_discards_seeded_children(self):
		self._scan()
		(self.root / 'report.txt').write_bytes(b'x' * 5000)
		self.assertEqual(1234, self._fs.size_bytes(self._child('report.txt')))
		self._fs.cache.clear(self.dir_path)
		self._scan()
		self.assertEqual(5000, self._fs.size_bytes(self._child('report.txt')))

	def test_single_entry_invalidation_uses_a_fresh_full_stat(self):
		self._scan()
		(self.root / 'report.txt').write_bytes(b'x' * 99)
		self._fs.cache.clear(self._child('report.txt'))
		counter = _CountingStat(self.root)
		with patch('os.stat', counter):
			self.assertEqual(99, self._fs.size_bytes(self._child('report.txt')))
		self.assertEqual(1, len(counter.calls))

	# --- Failure handling -------------------------------------------------

	def test_entry_disappearing_during_scan_is_listed_but_not_seeded(self):
		real_scandir = os.scandir

		class Vanishing:
			name = 'ghost.txt'
			path = str(self.root / 'ghost.txt')
			def is_symlink(self):
				return False
			def stat(self, follow_symlinks=True):
				raise FileNotFoundError(self.path)

		class Entries:
			def __init__(self, inner):
				self._inner = inner
			def __enter__(self):
				return self
			def __exit__(self, *_):
				self._inner.close()
			def __iter__(self):
				yield Vanishing()
				yield from self._inner

		with patch('os.scandir', lambda p: Entries(real_scandir(p))):
			names = self._scan()
		self.assertIn('ghost.txt', names)
		with self.assertRaises(KeyError):
			self._fs.cache.get(self._child('ghost.txt'), 'stat')
		with self.assertRaises(FileNotFoundError):
			self._fs.stat(self._child('ghost.txt'))

	def test_scandir_handle_is_closed_after_enumeration(self):
		real_scandir = os.scandir
		closed = []

		def tracking(path):
			iterator = real_scandir(path)
			original_close = iterator.close
			def close():
				closed.append(path)
				original_close()
			iterator.close = close
			return iterator

		with patch('os.scandir', tracking):
			self._scan()
		self.assertEqual(1, len(closed))

	def test_nonexistent_and_relative_directories_keep_existing_errors(self):
		with self.assertRaises(FileNotFoundError):
			self._fs.iterdir(self.dir_path + '/nonexistent')
		with self.assertRaises(FileNotFoundError):
			self._fs.iterdir('relative')

	# --- Cost --------------------------------------------------------------

	def test_thousand_entry_scan_performs_no_path_stat(self):
		for index in range(1000):
			(self.root / ('bulk_%04d.txt' % index)).write_bytes(b'b')
		counter = _CountingStat(self.root)
		with patch('os.stat', counter):
			names = self._scan()
			for name in names:
				self._fs.is_dir(self._child(name))
				if not name == 'sub':
					self._fs.size_bytes(self._child(name))
		self.assertEqual(1004, len(names))
		self.assertEqual([], counter.calls)
