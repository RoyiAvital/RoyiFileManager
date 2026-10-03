import importlib.util
import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import Mock, patch

import win32gui
import win32process


ROOT = Path(__file__).resolve().parents[4]
SCRIPT = ROOT / 'src' / 'misc' / 'generate_docs_screenshots.py'
SPEC = importlib.util.spec_from_file_location('generate_docs_screenshots', SCRIPT)
screenshots = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(screenshots)


class GenerateDocsScreenshotsTest(TestCase):
	def test_defaults_use_public_windows_paths(self):
		with patch.dict(os.environ, {'WINDIR': 'C:\\Windows'}):
			left, right = screenshots._public_paths()
		self.assertEqual(Path('C:\\'), left)
		self.assertEqual(Path('C:\\Windows'), right)

	def test_rejects_nonstandard_windows_directory(self):
		with patch.dict(os.environ, {'WINDIR': 'C:\\Users\\Private'}):
			with self.assertRaises(RuntimeError):
				screenshots._public_paths()

	def test_selects_public_windows_image(self):
		with TemporaryDirectory() as temporary_directory, \
				patch.object(screenshots, '_public_paths') as public_paths:
			windows = Path(temporary_directory) / 'Windows'
			image = windows / 'Web' / 'Wallpaper' / 'image.jpg'
			image.parent.mkdir(parents=True)
			image.write_bytes(b'image')
			public_paths.return_value = Path('C:\\'), windows
			self.assertEqual(image, screenshots._public_image())

	def test_source_outputs_include_documented_features(self):
		output_directory = Path('docs/assets')
		outputs = tuple(
			path.name
			for capture in screenshots.SOURCE_CAPTURES
			for path in screenshots._source_outputs(output_directory, capture)
		)
		self.assertEqual((
			'royifilemanager-dual-pane.png',
			'royifilemanager-command-center.png',
			'royifilemanager-find-location.png',
			'royifilemanager-file-context-menu.png',
			'royifilemanager-filter-pane.png',
			'royifilemanager-quickview.png',
			'royifilemanager-quickview-python.png',
			'royifilemanager-fuzzy-find-recursive.png',
			'royifilemanager-everything-images.png',
			'royifilemanager-everything-fonts.png',
			'royifilemanager-everything-folders.png',
			'royifilemanager-search-files.png',
			'royifilemanager-search-files-panel.png',
			'royifilemanager-find-files-fd.png',
			'royifilemanager-find-files-fd-panel.png',
			'royifilemanager-favorites.png',
			'royifilemanager-directory-size.png',
			'royifilemanager-file-hash.png',
			'royifilemanager-checksum-empty-menu.png',
			'royifilemanager-checksum-all-menu.png',
			'royifilemanager-process-pane.png',
			'royifilemanager-pack-archive.png',
		), outputs)

	def test_text_capture_generates_its_own_python_sample(self):
		with TemporaryDirectory() as temporary_directory, \
				patch.object(screenshots, 'WORK_DIR', Path(temporary_directory)), \
				patch.object(screenshots, '_public_paths', return_value=(
					Path('C:\\'), Path('C:\\Windows')
				)):
			left, right = screenshots._source_capture_paths('quick-view-text')
			self.assertEqual(Path(temporary_directory) / 'source-quick-view-text/sample', left)
			self.assertEqual(Path('C:\\Windows'), right)
			source = (left / 'file_summary.py').read_text(encoding='utf-8')
			self.assertEqual(screenshots.PYTHON_SAMPLE, source)
			self.assertNotIn('\t', source)
			compile(source, 'file_summary.py', 'exec')

	def test_checksum_capture_generates_a_verifiable_sample(self):
		from checksum_files import engine
		with TemporaryDirectory() as temporary_directory, \
				patch.object(screenshots, 'WORK_DIR', Path(temporary_directory)), \
				patch.object(screenshots, '_public_paths', return_value=(
					Path('C:\\'), Path('C:\\Windows')
				)):
			left, right = screenshots._source_capture_paths('checksum-files')
			self.assertEqual(Path(temporary_directory) / 'source-checksum-files/sample', left)
			self.assertEqual(Path('C:\\Windows'), right)
			results = engine.verify(str(left / 'Samples.sha256'), engine.Settings())
			self.assertTrue(results.complete)
			self.assertEqual(3, results.total)
			self.assertEqual(3, results.matched)
			self.assertEqual({'README.txt', 'Data/readings.csv', 'Documents/notes.txt'},
				{row.path.replace('\\', '/') for row in results.all_rows})

	def test_python_capture_grabs_window_and_restores_location_label(self):
		for fail in (False, True):
			with self.subTest(fail=fail):
				window, location_bar = Mock(), Mock()
				location_bar.text.return_value = 'Private working path'
				def grab():
					location_bar.setText.assert_called_once_with('Python sample')
					if fail:
						raise RuntimeError('Capture failed')
					return 'full window pixmap'
				window.grab.side_effect = grab
				if fail:
					with self.assertRaises(RuntimeError):
						screenshots._grab_window_with_sample_location(window, location_bar)
				else:
					self.assertEqual('full window pixmap',
						screenshots._grab_window_with_sample_location(window, location_bar))
				window.grab.assert_called_once_with()
				self.assertEqual(2, location_bar.setText.call_count)
				location_bar.setText.assert_called_with('Private working path')

	def test_seeds_public_favorites(self):
		with TemporaryDirectory() as temporary_directory, \
				patch.dict(os.environ, {'WINDIR': 'C:\\Windows'}):
			settings = Path(temporary_directory)
			screenshots._seed_settings(settings, 'favorites')
			document = json.loads((
				settings / 'Plugins' / 'User' / 'Settings' / 'Favorites (Windows).json'
			).read_text(encoding='utf-8'))
		urls = [favorite['url'] for favorite in document['favorites']]
		self.assertIn('file://C:', urls)
		self.assertTrue(all(
			url == 'file://C:' or url.casefold().startswith('file://c:/windows') for url in urls
		))

	def test_seeds_enabled_directory_sizes(self):
		with TemporaryDirectory() as temporary_directory, \
				patch.dict(os.environ, {'WINDIR': 'C:\\Windows'}):
			settings = Path(temporary_directory)
			screenshots._seed_settings(settings, 'directory-size')
			document = json.loads((
				settings / 'Plugins' / 'User' / 'Settings' / 'DirectorySize (Windows).json'
			).read_text(encoding='utf-8'))
		self.assertEqual({'enabled': True}, document)

	def test_everything_capture_uses_only_public_roots_and_a_private_instance(self):
		with TemporaryDirectory() as temporary_directory, \
				patch.object(screenshots, '_public_paths', return_value=(
					Path('C:\\'), Path('C:\\Windows')
				)), patch.object(screenshots.os, 'getpid', return_value=12345):
			settings = Path(temporary_directory)
			screenshots._seed_settings(settings, 'everything-search')
			document = json.loads((settings / 'Plugins/User/Settings/Everything (Windows).json')
				.read_text(encoding='utf-8'))
			self.assertEqual({'folders': ['C:\\Windows\\Web', 'C:\\Windows\\Fonts'],
				'instance': 'RoyiFileManagerDocs_12345'}, document)
			self.assertEqual((Path('C:\\Windows\\Web'), Path('C:\\Windows\\Fonts')),
				screenshots._source_capture_paths('everything-search'))
			screenshots._seed_settings(settings, 'everything-folders')
			self.assertEqual(document, json.loads((settings / 'Plugins/User/Settings/Everything (Windows).json')
				.read_text(encoding='utf-8')))
			self.assertEqual((Path('C:\\Windows\\Web'), Path('C:\\Windows\\Fonts')),
				screenshots._source_capture_paths('everything-folders'))
		self.assertIn(ROOT / 'src/main/resources/base/Plugins/Everything', screenshots.SOURCE_PATHS)

	def test_everything_capture_checks_dependency_before_launch(self):
		args = screenshots._parse_args(['--mode', 'source'])
		with patch.object(screenshots, 'SOURCE_CAPTURES', ('everything-search',)), \
				patch.object(screenshots, '_prepare_settings', return_value=Path('isolated')), \
				patch.object(screenshots, '_seed_settings') as seed, \
				patch.object(screenshots, '_source_environment', return_value={}), \
				patch.object(screenshots.subprocess, 'run') as run:
			outputs = screenshots._run_source(args)
			self.assertEqual(2, len(outputs))
			self.assertEqual(2, run.call_count)
			self.assertEqual([screenshots.sys.executable, '-c', 'import build; build._ensure_everything()'],
				run.call_args_list[0].args[0])
			seed.assert_called_once_with(Path('isolated'), 'everything-search')
			self.assertIn('everything-search', run.call_args_list[1].args[0])

	def test_everything_example_validation_rejects_empty_and_wrong_results(self):
		from fman import QuicksearchItem
		from fman.url import as_url
		with TemporaryDirectory() as temporary_directory, \
				patch.object(screenshots, '_public_paths', return_value=(Path('C:\\'), Path(temporary_directory))):
			windows = Path(temporary_directory)
			image = windows / 'Web' / 'img19.jpg'
			image.parent.mkdir()
			image.write_bytes(b'X' * (100 * 1024 + 1))
			item = QuicksearchItem(as_url(image), title=str(image), description='2026-10-03, 101 KB')
			screenshots._validate_everything_items([item], 0)
			with self.assertRaises(RuntimeError):
				screenshots._validate_everything_items([], 0)
			with self.assertRaises(RuntimeError):
				screenshots._validate_everything_items([item], 1)
			font = windows / 'Fonts' / 'segoeui.ttf'
			item = QuicksearchItem(as_url(font), title=str(font), description='2026-10-03, 1 MB', highlight=[(0, 5)])
			screenshots._validate_everything_items([item], 1)
			bold = font.with_name('segoeuib.ttf')
			with self.assertRaises(RuntimeError):
				screenshots._validate_everything_items([
					QuicksearchItem(as_url(bold), title=str(bold), description='1 MB', highlight=[(0, 5)])], 1)

	def test_other_captures_use_default_settings(self):
		with TemporaryDirectory() as temporary_directory, \
				patch.dict(os.environ, {'WINDIR': 'C:\\Windows'}):
			settings = Path(temporary_directory)
			screenshots._seed_settings(settings, 'file-hash')
			self.assertEqual([], list(settings.iterdir()))

	def test_directory_size_uses_small_public_folders(self):
		with patch.dict(os.environ, {'WINDIR': 'C:\\Windows'}):
			left, right = screenshots._source_capture_paths('directory-size')
		self.assertEqual(Path('C:\\Windows\\Web'), left)
		self.assertIn(right, (left, left / 'Wallpaper'))

	def test_prepares_non_first_run_session(self):
		with TemporaryDirectory() as temporary_directory, \
				patch.object(screenshots, 'WORK_DIR', Path(temporary_directory)), \
				patch.object(screenshots, '_application_version', return_value='1.2.3'):
			settings = screenshots._prepare_settings('source')
			document = json.loads(
				(settings / 'Local' / 'Session.json').read_text(encoding='utf-8')
			)
		self.assertEqual('1.2.3', document['app_version'])
		self.assertTrue(document['is_licensed'])

	def test_rejects_invalid_dimensions(self):
		with self.assertRaises(SystemExit):
			screenshots._parse_args(['--width', '0'])

	def test_finds_visible_main_window_for_process(self):
		def enumerate_windows(callback, argument):
			callback(123, argument)
		with patch.object(screenshots, 'APP_NAME', 'RfmRenameProbe'), \
				patch.object(win32gui, 'EnumWindows', side_effect=enumerate_windows), \
				patch.object(win32gui, 'IsWindowVisible', return_value=True), \
				patch.object(win32gui, 'GetWindowText', return_value='RfmRenameProbe'), \
				patch.object(
					win32process, 'GetWindowThreadProcessId', return_value=(1, 456)
				):
			handle = screenshots._find_window(456, 1)
		self.assertEqual(123, handle)

	def test_default_executable_uses_settings_name(self):
		import runpy
		with patch('fbs_runtime.build_settings.get_build_settings', return_value={
			'app_name': 'RfmRenameProbe', 'version': '9.8.7'
		}):
			loaded = runpy.run_path(str(SCRIPT))
		self.assertEqual(ROOT / 'target/RfmRenameProbe/RfmRenameProbe.exe', loaded['DEFAULT_EXE'])
		self.assertEqual('9.8.7', loaded['_application_version']())

	def test_resizes_packaged_client(self):
		with patch.object(win32gui, 'GetWindowLong', return_value=0), \
				patch.object(
					screenshots.ctypes.windll.user32,
					'AdjustWindowRectEx', return_value=True
				), patch.object(win32gui, 'MoveWindow') as move_window, \
				patch.object(win32gui, 'ShowWindow'), \
				patch.object(win32gui, 'SetForegroundWindow'):
			screenshots._resize_client(123, 1280, 800)
		move_window.assert_called_once_with(123, 80, 80, 1280, 800, True)
