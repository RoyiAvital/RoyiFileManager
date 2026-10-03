import importlib.util
from contextlib import redirect_stdout
from io import StringIO
import json
import os
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory
from textwrap import dedent
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
	def test_restricted_child_with_admin_only_default_dacl(self):
		script = '''
import os, sys
from pathlib import Path
import build, win32api, win32con, win32security

token = win32security.OpenProcessToken(win32api.GetCurrentProcess(), win32con.TOKEN_ALL_ACCESS)
original = win32security.GetTokenInformation(token, win32security.TokenDefaultDacl)
restricted_acl = win32security.ACL()
for identity in (win32security.WinBuiltinAdministratorsSid, win32security.WinLocalSystemSid):
    restricted_acl.AddAccessAllowedAce(win32security.ACL_REVISION, win32con.GENERIC_ALL,
        win32security.CreateWellKnownSid(identity))
child_script = """
print('Started restricted Python', flush=True)
import ctypes, win32api, win32con
assert not ctypes.windll.shell32.IsUserAnAdmin(), 'Child still has admin privileges'
process = win32api.OpenProcess(win32con.PROCESS_ALL_ACCESS, False, win32api.GetCurrentProcessId())
process.Close()
from PyQt5.QtWidgets import QApplication, QWidget
app = QApplication([])
widget = QWidget()
widget.resize(320, 240)
widget.show()
app.processEvents()
assert not widget.grab().isNull()
widget.close()
print('PASS: restricted Qt capture', flush=True)
"""
try:
    win32security.SetTokenInformation(token, win32security.TokenDefaultDacl, restricted_acl)
    build._run_restricted([sys.executable, '-u', '-c', child_script],
        {**os.environ, 'QT_QPA_PLATFORM': 'windows'}, Path(sys.argv[1]) / 'child.log', 10)
	remaining = win32security.GetTokenInformation(token, win32security.TokenDefaultDacl)
	assert [remaining.GetAce(index) for index in range(remaining.GetAceCount())] == [
		restricted_acl.GetAce(index) for index in range(restricted_acl.GetAceCount())
	], 'Launcher changed the parent token default ACL'
finally:
    win32security.SetTokenInformation(token, win32security.TokenDefaultDacl, original)
    token.Close()
'''
		with TemporaryDirectory() as temporary_directory:
			result = subprocess.run([sys.executable, '-X', 'faulthandler', '-c',
				dedent(script.expandtabs(4)), temporary_directory], cwd=ROOT,
				capture_output=True, text=True, timeout=25)
			self.assertEqual(0, result.returncode, result.stdout + result.stderr)
			self.assertIn('PASS: restricted Qt capture', result.stdout)

	def test_source_child_watchdog_is_canceled_on_success_and_error(self):
		for error in (None, RuntimeError('Capture failed')):
			with self.subTest(error=error), \
					patch.object(screenshots.faulthandler, 'dump_traceback_later') as start, \
					patch.object(screenshots.faulthandler, 'cancel_dump_traceback_later') as cancel, \
					patch.object(screenshots, '_capture_source_child', return_value=0, side_effect=error), \
					redirect_stdout(StringIO()) as output:
				if error is None:
					self.assertEqual(0, screenshots.main(['--_source-child', '--timeout', '5']))
				else:
					with self.assertRaisesRegex(RuntimeError, 'Capture failed'):
						screenshots.main(['--_source-child', '--timeout', '5'])
				start.assert_called_once_with(5)
				cancel.assert_called_once_with()
				self.assertIn('Starting source child: overview', output.getvalue())

	def test_restricted_child_keeps_callers_desktop(self):
		script = '''
import os, sys
from pathlib import Path
from uuid import uuid4
import build, win32api, win32con, win32service

original = win32service.GetThreadDesktop(win32api.GetCurrentThreadId())
name = 'RFM_Capture_' + uuid4().hex
desktop = win32service.CreateDesktop(name, 0, win32con.GENERIC_ALL, None)
child_script = """
import sys, win32api, win32service
from PyQt5.QtWidgets import QApplication, QWidget
desktop = win32service.GetThreadDesktop(win32api.GetCurrentThreadId())
name = win32service.GetUserObjectInformation(desktop, 2)
assert name == sys.argv[1], 'Child moved to desktop: ' + name
app = QApplication([])
widget = QWidget()
widget.resize(320, 240)
widget.show()
app.processEvents()
assert not widget.grab().isNull()
widget.close()
print('PASS: private desktop Qt capture', flush=True)
"""
try:
    desktop.SetThreadDesktop()
    environment = {**os.environ, 'QT_QPA_PLATFORM': 'windows'}
    build._run_restricted([sys.executable, '-c', child_script, name], environment,
        Path(sys.argv[1]) / 'child.log', 15)
finally:
    original.SetThreadDesktop()
    desktop.CloseDesktop()
'''
		with TemporaryDirectory() as temporary_directory:
			result = subprocess.run([sys.executable, '-X', 'faulthandler', '-c',
				dedent(script), temporary_directory], cwd=ROOT,
				capture_output=True, text=True, timeout=30)
			self.assertEqual(0, result.returncode, result.stdout + result.stderr)
			self.assertIn('PASS: private desktop Qt capture', result.stdout)

	def test_restricted_child_token_output_and_exit_code(self):
		script = '''
import ctypes, os, sys, win32api, win32con, win32security
assert not ctypes.windll.shell32.IsUserAnAdmin(), 'Child still has admin privileges'
token = win32security.OpenProcessToken(win32api.GetCurrentProcess(), win32con.TOKEN_QUERY)
assert not win32security.GetTokenInformation(token, win32security.TokenElevation)
try:
    integrity, attributes = win32security.GetTokenInformation(token, win32security.TokenIntegrityLevel)
    assert integrity.GetSubAuthority(integrity.GetSubAuthorityCount() - 1) == 8192
finally:
    token.Close()
print(os.environ['CAPTURE_TEST_VALUE'])
print(sys.argv[2], file=sys.stderr)
raise SystemExit(int(sys.argv[1]))
'''
		with TemporaryDirectory() as temporary_directory:
			log = Path(temporary_directory) / 'capture.log'
			value = 'value with spaces and "quotes"'
			environment = {**os.environ, 'CAPTURE_TEST_VALUE': value}
			for return_code in (0, 7):
				with self.subTest(return_code=return_code), redirect_stdout(StringIO()) as output:
					command = [sys.executable, '-c', dedent(script), str(return_code), value]
					if return_code:
						with self.assertRaises(subprocess.CalledProcessError) as raised:
							screenshots._run_restricted(command, environment, log, 15)
						self.assertEqual(return_code, raised.exception.returncode)
					else:
						screenshots._run_restricted(command, environment, log, 15)
					self.assertEqual([value, value], output.getvalue().splitlines())
					self.assertEqual(output.getvalue(), log.read_text(encoding='utf-8'))

	def test_restricted_child_timeout_preserves_log_and_stops_descendants(self):
		import pywintypes
		import win32api
		import win32con
		import win32event
		script = '''
import subprocess, sys
from threading import Event
child = subprocess.Popen([sys.executable, '-c', 'from threading import Event; Event().wait()'])
print(child.pid, flush=True)
Event().wait()
'''
		with TemporaryDirectory() as temporary_directory, redirect_stdout(StringIO()) as output:
			log = Path(temporary_directory) / 'capture.log'
			command = [sys.executable, '-u', '-c', dedent(script)]
			with self.assertRaises(subprocess.TimeoutExpired):
				screenshots._run_restricted(command, os.environ.copy(), log, 2)
			self.assertEqual(log.read_text(encoding='utf-8'), output.getvalue())
			child_pid = int(output.getvalue().strip())
			try:
				child = win32api.OpenProcess(win32con.SYNCHRONIZE | win32con.PROCESS_TERMINATE,
					False, child_pid)
			except pywintypes.error as error:
				self.assertEqual(87, error.winerror)
			else:
				try:
					if win32event.WaitForSingleObject(child, 5000) != win32event.WAIT_OBJECT_0:
						win32api.TerminateProcess(child, 1)
						self.fail('Restricted child left a descendant running')
				finally:
					child.Close()

	def test_elevated_capture_uses_restricted_child_without_fallback(self):
		args = screenshots._parse_args(['--mode', 'source'])
		settings = Path('isolated/UserSettings')
		for error in (None, OSError('Restricted launch failed')):
			with self.subTest(error=error), \
					patch.object(screenshots, 'SOURCE_CAPTURES', ('fuzzy-find',)), \
					patch.object(screenshots, '_prepare_settings', return_value=settings), \
					patch.object(screenshots, '_seed_settings'), \
					patch.object(screenshots, '_source_environment', return_value={'test': 'value'}), \
					patch.object(screenshots.ctypes.windll.shell32, 'IsUserAnAdmin', return_value=1), \
					patch.object(screenshots, '_run_restricted', side_effect=error) as restricted, \
					patch.object(screenshots.subprocess, 'run') as run:
				if error is None:
					self.assertEqual(screenshots._source_outputs(args.output_dir, 'fuzzy-find'),
						screenshots._run_source(args))
				else:
					with self.assertRaisesRegex(OSError, 'Restricted launch failed'):
						screenshots._run_source(args)
				run.assert_not_called()
				restricted.assert_called_once()
				command, environment, log, timeout = restricted.call_args.args
				self.assertIn('fuzzy-find', command)
				self.assertEqual({'test': 'value'}, environment)
				self.assertEqual(settings / 'Local/capture.log', log)
				self.assertEqual(args.timeout + 30, timeout)

	def test_source_environment_enables_child_crash_diagnostics(self):
		with patch.dict(os.environ, {'PYTHONPATH': 'existing', 'PYTHONFAULTHANDLER': '0'}, clear=True):
			environment = screenshots._source_environment(Path('isolated'))
			self.assertEqual('0', os.environ['PYTHONFAULTHANDLER'])
		self.assertEqual('1', environment['PYTHONFAULTHANDLER'])
		self.assertEqual('1', environment['PYTHONUNBUFFERED'])
		self.assertEqual('isolated', environment['ROYIFILEMANAGER_USER_SETTINGS'])
		self.assertEqual([str(path) for path in screenshots.SOURCE_PATHS] + ['existing'],
			environment['PYTHONPATH'].split(os.pathsep))

	def test_source_child_closes_main_window_on_success_and_failure(self):
		script = '''
import sys
from pathlib import Path
sys.path.insert(0, sys.argv[1])
import generate_docs_screenshots as screenshots
from fman.impl.application_context import get_application_context
from search_file_fuzzy.matcher import Matcher

sample, output = Path(sys.argv[2]), Path(sys.argv[3])
empty = sys.argv[4] == 'empty'
screenshots._source_capture_paths = lambda capture: (sample, sample)
if empty:
    Matcher.matches = lambda self, query: iter(())
context = get_application_context()
closed = []
context.main_window.closed.connect(lambda: closed.append(True))
args = screenshots._parse_args([
    '--_source-child', '--_capture', 'fuzzy-find', '--output-dir', str(output)
])
try:
    result = screenshots._capture_source_child(args)
except RuntimeError as error:
    assert empty and 'no image results' in str(error), str(error)
else:
    assert not empty and result == 0, result
    screenshots._validate_image(screenshots._source_outputs(output, 'fuzzy-find')[0])
assert closed == [True], 'Capture bypassed main-window cleanup'
assert not context.main_window.isVisible(), 'Capture left its main window open'
'''
		with TemporaryDirectory() as temporary_directory, \
				patch.object(screenshots, 'WORK_DIR', Path(temporary_directory)):
			sample = Path(temporary_directory) / 'sample'
			(sample / 'nested').mkdir(parents=True)
			(sample / 'nested' / 'img_sample.txt').write_text('sample', encoding='utf-8')
			for case in ('success', 'empty'):
				with self.subTest(case=case):
					settings = screenshots._prepare_settings(case)
					environment = screenshots._source_environment(settings)
					environment['QT_QPA_PLATFORM'] = 'windows'
					result = subprocess.run([
						sys.executable, '-c', dedent(script), str(SCRIPT.parent),
						str(sample), str(settings.parent / 'output'), case,
					], cwd=ROOT, env=environment, capture_output=True, text=True, timeout=45)
					self.assertEqual(0, result.returncode, result.stdout + result.stderr)

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
				patch.object(screenshots.ctypes.windll.shell32, 'IsUserAnAdmin', return_value=0), \
				patch.object(screenshots, '_run_restricted') as restricted, \
				patch.object(screenshots.subprocess, 'run') as run:
			outputs = screenshots._run_source(args)
			restricted.assert_not_called()
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
