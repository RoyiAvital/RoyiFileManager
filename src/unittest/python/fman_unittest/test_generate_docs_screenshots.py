import importlib.util
import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import patch

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
			'royifilemanager-fuzzy-find-recursive.png',
			'royifilemanager-search-files.png',
			'royifilemanager-search-files-panel.png',
			'royifilemanager-find-files-fd.png',
			'royifilemanager-find-files-fd-panel.png',
			'royifilemanager-favorites.png',
			'royifilemanager-directory-size.png',
			'royifilemanager-file-hash.png',
			'royifilemanager-process-pane.png',
			'royifilemanager-pack-archive.png',
		), outputs)

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
