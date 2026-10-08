from importlib import import_module
import os
from pathlib import Path
import subprocess
from tempfile import TemporaryDirectory
from unittest import TestCase

from fman.url import as_url
from fman_unittest.robocopy_fixture import plugin_module


class RobocopyEngineIT(TestCase):
	def test_loopback_unc_loose_files_copy_and_move(self):
		local_source = self.source
		unc = Path('\\\\localhost\\' + local_source.drive[0] + '$' + str(local_source)[2:])
		try:
			if not unc.is_dir():
				self.skipTest('Loopback administrative share unavailable')
		except OSError as error:
			self.skipTest('Loopback administrative share unavailable: %s' % error)
		self.source = unc
		for move in (False, True):
			with self.subTest(move=move):
				name = 'move.txt' if move else '\u00e9tude.txt'
				(local_source / name).write_bytes(b'UNC fixture')
				(local_source / 'unselected.txt').write_bytes(b'keep')
				self.run_plan(self.plan((name,), move=move))
				self.assertEqual(b'UNC fixture', (self.destination / name).read_bytes())
				self.assertEqual(not move, (local_source / name).exists())
				self.assertFalse((self.destination / 'unselected.txt').exists())

	def test_hyphen_directory_copy_and_move(self):
		for move in (False, True):
			with self.subTest(move=move):
				name = '-move' if move else '-copy'
				(self.source / name).mkdir()
				(self.source / name / 'inside.txt').write_bytes(b'folder')
				self.run_plan(self.plan((name,), move=move))
				self.assertEqual(b'folder', (self.destination / name / 'inside.txt').read_bytes())
				self.assertEqual(not move, (self.source / name).exists())

	def setUp(self):
		self.plugin = self.enterContext(plugin_module())
		self.engine = import_module('robocopy_plugin.engine')
		self.windows = import_module('robocopy_plugin.windows')
		self.root = Path(self.enterContext(TemporaryDirectory())).resolve()
		self.source, self.destination = self.root / 'source', self.root / 'destination'
		self.source.mkdir()
		self.executable = self.windows.executable()

	def plan(self, names, move=False, settings=None, log=None):
		return self.engine.prepare(as_url(self.source), tuple(as_url(self.source / name) for name in names),
			str(self.destination), self.executable, settings or self.engine.Settings(retries=0), move, log)

	def run_plan(self, plan, log=None):
		codes = []
		for job in plan.jobs:
			self.engine.recheck(plan, job)
			code, output = self.windows.run(job.arguments(self.executable, plan.settings, plan.move, log), timeout=15)
			self.assertLess(code, 8, output)
			codes.append(code)
		return codes

	def test_exact_mixed_selection_and_two_unicode_log_appends(self):
		names = ('file with space.txt', 'note', '[brackets].txt', '@leading.txt', '\u00e9tude.txt')
		for name in (*names, 'note.txt', 'unselected.txt'):
			(self.source / name).write_bytes(name.encode())
		(self.source / 'Photos' / 'empty').mkdir(parents=True)
		(self.source / 'Photos' / 'picture.bin').write_bytes(b'picture')
		logs = import_module('robocopy_plugin.logs')
		settings = self.engine.Settings(log_enabled=True, retries=0)
		self.engine.probe(self.executable, settings)
		path = logs.choose_path(str(self.root / 'settings'))
		plan = self.plan((*names, 'Photos'), settings=settings, log=path)
		log = logs.TransferLog(path, 'Copy fixture')
		for index, job in enumerate(plan.jobs):
			log.append('Job %d' % (index + 1))
			self.engine.recheck(plan, job)
			code, output = self.windows.run(job.arguments(self.executable, settings, log=path), timeout=15)
			self.assertLess(code, 8, output)
			log.validate()
		log.finish('Completed fixture')
		self.assertEqual(set((*names, 'Photos')), {path.name for path in self.destination.iterdir()})
		for name in names:
			self.assertEqual((self.source / name).read_bytes(), (self.destination / name).read_bytes())
		self.assertTrue((self.destination / 'Photos' / 'empty').is_dir())
		text = log.path.read_text(encoding='utf-16')
		for marker in ('Job 1', 'Job 2', '\u00e9tude.txt', 'Completed fixture'):
			self.assertIn(marker, text)
		self.assertNotIn('\ufeff', text)

	def test_native_equal_metadata_move_keeps_source(self):
		self.destination.mkdir()
		source, destination = self.source / 'same.txt', self.destination / 'same.txt'
		source.write_bytes(b'aaaa')
		destination.write_bytes(b'bbbb')
		stamp = source.stat().st_mtime_ns
		os.utime(destination, ns=(stamp, stamp))
		plan = self.plan(('same.txt',), move=True)
		self.assertEqual([0], self.run_plan(plan))
		self.assertEqual(b'aaaa', source.read_bytes())
		self.assertEqual(b'bbbb', destination.read_bytes())
		self.assertEqual((1, 0, (str(source),)), self.engine.remaining(plan.jobs[0].entries))

	def test_forced_small_native_batches_never_include_unselected_files(self):
		names = tuple('selected %d.txt' % index for index in range(12))
		for name in (*names, 'unselected.txt'):
			(self.source / name).write_bytes(name.encode())
		plan = self.plan(names)
		entries = plan.jobs[0].entries
		limit = self.engine.command_units(self.engine.Job(plan.source, plan.destination, (), (names[0],)).arguments(
			self.executable, plan.settings)) + 40
		jobs = self.engine.build_jobs(plan.source, plan.destination, entries, self.executable, plan.settings, limit=limit)
		self.assertGreater(len(jobs), 1)
		for job in jobs:
			arguments = job.arguments(self.executable, plan.settings)
			self.assertLessEqual(self.engine.command_units(arguments), limit)
			code, output = self.windows.run(arguments, timeout=15)
			self.assertLess(code, 8, output)
		self.assertEqual(set(names), {path.name for path in self.destination.iterdir()})
		for name in names:
			self.assertEqual(name.encode(), (self.destination / name).read_bytes())

	def test_move_files_and_empty_selected_directory_not_pane_root(self):
		(self.source / 'move.txt').write_bytes(b'move')
		(self.source / 'keep.txt').write_bytes(b'keep')
		(self.source / 'Empty').mkdir()
		plan = self.plan(('move.txt', 'Empty'), move=True)
		self.run_plan(plan)
		self.assertEqual({'keep.txt'}, {path.name for path in self.source.iterdir()})
		self.assertEqual({'move.txt', 'Empty'}, {path.name for path in self.destination.iterdir()})
		for job in plan.jobs:
			self.assertEqual((0, 0, ()), self.engine.remaining(job.entries))

	def test_native_overwrite_newer_and_destination_hardlink_effect(self):
		self.destination.mkdir()
		source, destination = self.source / 'report.txt', self.destination / 'report.txt'
		source.write_bytes(b'new source content')
		destination.write_bytes(b'old')
		os.utime(source, (1600000000, 1600000000))
		os.utime(destination, (1700000000, 1700000000))
		alias = self.root / 'outside.txt'
		os.link(destination, alias)
		self.run_plan(self.plan(('report.txt',)))
		self.assertEqual(source.read_bytes(), destination.read_bytes())
		self.assertEqual(source.read_bytes(), alias.read_bytes())

	def test_self_descendant_source_replacement_and_log_overlap_refused(self):
		(self.source / 'Folder').mkdir()
		for target in (self.source, self.source / 'Folder' / 'child'):
			self.destination = target
			with self.assertRaises(ValueError):
				self.plan(('Folder',))
		self.destination = self.root / 'target'
		with self.assertRaisesRegex(ValueError, 'log'):
			self.plan(('Folder',), log=str(self.destination / 'log.txt'))
		plan = self.plan(('Folder',))
		(self.source / 'Folder').rename(self.source / 'old')
		(self.source / 'Folder').mkdir()
		with self.assertRaisesRegex(ValueError, 'replaced'):
			self.engine.recheck(plan, plan.jobs[0])
		self.assertFalse(self.destination.exists())

	def junction(self, link, target):
		result = subprocess.run([os.path.join(os.environ['WINDIR'], 'System32', 'cmd.exe'),
			'/d', '/c', 'mklink', '/J', str(link), str(target)], capture_output=True, timeout=10)
		self.assertEqual(0, result.returncode, repr(result.stdout + result.stderr))

	def test_nested_source_junction_exclusion_and_selected_junction_refusal(self):
		folder = self.source / 'Folder'
		folder.mkdir()
		outside = self.root / 'outside'
		outside.mkdir()
		(outside / 'keep.txt').write_bytes(b'outside')
		self.junction(folder / 'excluded', outside)
		self.junction(self.source / 'selected', outside)
		with self.assertRaisesRegex(ValueError, 'junctions'):
			self.plan(('selected',))
		plan = self.plan(('Folder',), move=True)
		self.run_plan(plan)
		self.assertFalse((self.destination / 'Folder' / 'excluded').exists())
		self.assertEqual(b'outside', (outside / 'keep.txt').read_bytes())
		self.assertEqual(1, self.engine.remaining(plan.jobs[0].entries)[0])

	def test_documented_destination_junction_effect_and_ads(self):
		folder = self.source / 'Folder' / 'redirect'
		folder.mkdir(parents=True)
		(folder / 'file.txt').write_bytes(b'native data')
		with open(str(folder / 'file.txt') + ':extra', 'wb') as stream:
			stream.write(b'alternate stream')
		(self.destination / 'Folder').mkdir(parents=True)
		outside = self.root / 'outside'
		outside.mkdir()
		self.junction(self.destination / 'Folder' / 'redirect', outside)
		self.run_plan(self.plan(('Folder',)))
		self.assertEqual(b'native data', (outside / 'file.txt').read_bytes())
		with open(str(outside / 'file.txt') + ':extra', 'rb') as stream:
			self.assertEqual(b'alternate stream', stream.read())

	def test_selected_symlink_refused_and_nested_source_symlinks_excluded(self):
		(self.source / 'Folder').mkdir()
		outside = self.root / 'outside'
		outside.mkdir()
		(outside / 'file.txt').write_bytes(b'outside')
		try:
			os.symlink(outside, self.source / 'Folder' / 'directory-link', target_is_directory=True)
			os.symlink(outside / 'file.txt', self.source / 'Folder' / 'file-link.txt')
			os.symlink(outside, self.source / 'selected-link', target_is_directory=True)
		except OSError as error:
			if getattr(error, 'winerror', None) == 1314:
				self.skipTest('Windows symlink privilege unavailable')
			raise
		with self.assertRaisesRegex(ValueError, 'links'):
			self.plan(('selected-link',))
		self.run_plan(self.plan(('Folder',), move=True))
		self.assertEqual([], list((self.destination / 'Folder').iterdir()))
		self.assertEqual(b'outside', (outside / 'file.txt').read_bytes())
		self.assertTrue((self.source / 'Folder').exists())

	def test_failed_native_move_overwrite_preserves_source(self):
		import ctypes
		self.destination.mkdir()
		(self.source / 'locked.txt').write_bytes(b'source data')
		(self.destination / 'locked.txt').write_bytes(b'keep')
		plan = self.plan(('locked.txt',), move=True)
		library = self.windows.api()
		handle = library.CreateFileW(str(self.destination / 'locked.txt'), 0x80000000, 0, None, 3, 0, None)
		self.assertNotEqual(ctypes.c_void_p(-1).value, handle)
		try:
			code, output = self.windows.run(plan.jobs[0].arguments(self.executable, plan.settings, True), timeout=15)
			self.assertGreaterEqual(code, 8, output)
		finally:
			library.CloseHandle(handle)
		self.assertEqual(b'source data', (self.source / 'locked.txt').read_bytes())
		self.assertEqual(b'keep', (self.destination / 'locked.txt').read_bytes())
		self.assertEqual(1, self.engine.remaining(plan.jobs[0].entries)[0])

	def test_native_short_alias_refused(self):
		import ctypes
		from ctypes import wintypes
		path = self.source / 'long selected filename.txt'
		path.write_bytes(b'keep')
		library = self.windows.api()
		library.GetShortPathNameW.argtypes = [wintypes.LPCWSTR, wintypes.LPWSTR, wintypes.DWORD]
		library.GetShortPathNameW.restype = wintypes.DWORD
		buffer = ctypes.create_unicode_buffer(32768)
		self.windows.checked(library.GetShortPathNameW(str(path), buffer, len(buffer)))
		alias = Path(buffer.value).name
		if alias == path.name:
			self.skipTest('8.3 aliases are disabled for this temporary volume')
		with self.assertRaisesRegex(ValueError, '8.3 alias'):
			self.plan((alias,))
		self.assertFalse(self.destination.exists())

	def test_native_case_sensitive_directory_refused(self):
		import ctypes
		from ctypes import wintypes
		library = self.windows.api()
		library.SetFileInformationByHandle.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD]
		library.SetFileInformationByHandle.restype = wintypes.BOOL
		handle = library.CreateFileW(str(self.source), 0xc0000000, 7, None, 3, 0x02000000, None)
		self.assertNotEqual(ctypes.c_void_p(-1).value, handle)
		try:
			flags = wintypes.DWORD(1)
			if not library.SetFileInformationByHandle(handle, 23, ctypes.byref(flags), ctypes.sizeof(flags)):
				code = ctypes.get_last_error()
				if code in (1, 5, 50, 87, 1314):
					self.skipTest('Native case-sensitive directory setup unavailable (Windows error %d)' % code)
				raise ctypes.WinError(code)
		finally:
			library.CloseHandle(handle)
		(self.source / 'File.txt').write_bytes(b'upper')
		(self.source / 'file.txt').write_bytes(b'lower')
		self.assertEqual(2, len(list(self.source.iterdir())))
		with self.assertRaisesRegex(ValueError, 'case-sensitive'):
			self.plan(('File.txt', 'file.txt'))
		self.assertFalse(self.destination.exists())