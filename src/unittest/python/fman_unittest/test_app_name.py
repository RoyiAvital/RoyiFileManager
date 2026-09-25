from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import Mock, patch
import json
import runpy
import shutil
import sys
from zipfile import ZipFile

from fbs_runtime.build_settings import get_build_settings, load_build_settings, settings_path


class BuildSettingsTest(TestCase):
	def tearDown(self):
		get_build_settings.cache_clear()

	def test_valid_names_and_other_settings_are_preserved(self):
		for name in ('RfmRenameProbe', 'build', 'App_2-x', 'A' * 64):
			with self.subTest(name=name), TemporaryDirectory() as temporary:
				path = Path(temporary) / 'base.json'
				settings = {'app_name': name, 'version': '9.8.7'}
				path.write_text(json.dumps(settings), encoding='utf-8')
				self.assertEqual(settings, load_build_settings(path))

	def test_invalid_names_report_settings_path_and_field(self):
		invalid = (None, 1, True, [], {}, '', ' ', 'App Name', '../App',
			'App/name', 'App\\name', 'App:', 'App*', 'App?', 'App"', 'App<',
			'App>', 'App|', 'App\nName', 'App\x00', 'App.', 'App ', 'A' * 65,
			'CON', 'con', 'PRN', 'AUX', 'NUL', 'NUL.txt', 'COM1', 'COM9',
			'LPT1', 'LPT9', '1App', '\u00e9App')
		with TemporaryDirectory() as temporary:
			path = Path(temporary) / 'base.json'
			for name in invalid:
				with self.subTest(name=name):
					path.write_text(json.dumps({'app_name': name}), encoding='utf-8')
					with self.assertRaises(ValueError) as caught:
						load_build_settings(path)
					self.assertIn(str(path), str(caught.exception))
					self.assertIn('app_name', str(caught.exception))

	def test_missing_name_and_non_object_document_are_rejected(self):
		with TemporaryDirectory() as temporary:
			path = Path(temporary) / 'base.json'
			for settings in ({'version': '9.8.7'}, [], None):
				with self.subTest(settings=settings):
					path.write_text(json.dumps(settings), encoding='utf-8')
					with self.assertRaisesRegex(ValueError, 'app_name'):
						load_build_settings(path)

	def test_unreadable_or_malformed_settings_report_path(self):
		with TemporaryDirectory() as temporary:
			path = Path(temporary) / 'base.json'
			for contents in (None, '{'):
				if contents is not None:
					path.write_text(contents, encoding='utf-8')
				with self.assertRaises(ValueError) as caught:
					load_build_settings(path)
				self.assertIn(str(path), str(caught.exception))

	def test_development_path_is_canonical(self):
		with patch.object(sys, 'frozen', False, create=True):
			self.assertEqual(Path(__file__).resolve().parents[4] /
				'src/build/settings/base.json', settings_path())

	def test_frozen_settings_are_one_cached_snapshot(self):
		from fbs_runtime.application_context.PyQt5 import ApplicationContext
		get_build_settings.cache_clear()
		with TemporaryDirectory() as temporary:
			path = Path(temporary) / 'resources/build-settings/base.json'
			path.parent.mkdir(parents=True)
			path.write_text(json.dumps({'app_name': 'RfmRenameProbe'}), encoding='utf-8')
			with patch.object(sys, 'frozen', True, create=True), \
					patch.object(sys, '_MEIPASS', temporary, create=True):
				self.assertEqual(path, settings_path())
				settings = get_build_settings()
				path.unlink()
				self.assertIs(settings, get_build_settings())
				self.assertIs(settings, ApplicationContext().build_settings)
				self.assertEqual('RfmRenameProbe', settings['app_name'])


class BuildNamingTest(TestCase):
	ROOT = Path(__file__).resolve().parents[4]

	def _fixture(self, root, name):
		settings_path = root / 'src/build/settings/base.json'
		settings_path.parent.mkdir(parents=True)
		settings_path.write_text(json.dumps({
			'app_name': name, 'version': '9.8.7'
		}), encoding='utf-8')
		helper = root / 'src/main/python/fbs_runtime/build_settings.py'
		helper.parent.mkdir(parents=True)
		shutil.copy2(self.ROOT / helper.relative_to(root), helper)
		shutil.copy2(self.ROOT / 'build.py', root / 'build.py')
		return settings_path

	def test_build_paths_freeze_and_help_use_settings(self):
		for name in ('RfmRenameProbe', 'build'):
			with self.subTest(name=name), TemporaryDirectory() as temporary:
				root = Path(temporary)
				self._fixture(root, name)
				build = runpy.run_path(str(root / 'build.py'))
				self.assertEqual(name, build['APP_NAME'])
				self.assertEqual(root / 'target' / name, build['DIST_DIR'])
				self.assertEqual(root / 'target/.pyinstaller', build['WORK_DIR'])
				build['DIST_DIR'].mkdir(parents=True)
				with patch.dict(build['freeze'].__globals__, {
					'_require_windows': Mock(), '_ensure_7za': Mock(),
					'_ensure_conda_lock': Mock(), '_remove_previous_freeze': Mock(),
					'_copy_dependency_manifests': Mock()
				}), patch('subprocess.run') as execute:
					build['freeze']()
				arguments = execute.call_args.args[0]
				self.assertEqual(str(root / 'application.spec'), arguments[-1])
				self.assertEqual(str(build['WORK_DIR']), arguments[arguments.index('--workpath') + 1])
				with patch('argparse.ArgumentParser') as parser:
					parser.return_value.parse_args.return_value.command = 'not-a-command'
					with self.assertRaises(KeyError):
						build['main']([])
					self.assertEqual('Build %s.' % name, parser.call_args.kwargs['description'])

	def test_archive_name_root_and_version_use_cached_settings(self):
		with TemporaryDirectory() as temporary:
			root = Path(temporary)
			settings_path = self._fixture(root, 'RfmRenameProbe')
			build = runpy.run_path(str(root / 'build.py'))
			settings_path.unlink()
			distribution = build['DIST_DIR']
			distribution.mkdir(parents=True)
			(distribution / 'RfmRenameProbe.exe').write_bytes(b'fixture')
			with patch.dict(build['package'].__globals__, {
				'_require_windows': Mock(), '_copy_dependency_manifests': Mock()
			}), patch('builtins.print') as output:
				build['package']()
			archive = root / 'target/RfmRenameProbe-9.8.7-windows-x86_64.zip'
			output.assert_called_once_with(archive)
			with ZipFile(archive) as package:
				self.assertEqual(['RfmRenameProbe/RfmRenameProbe.exe'], package.namelist())

	def test_spec_derives_both_names_and_preserves_bundled_settings(self):
		with TemporaryDirectory() as temporary:
			root = Path(temporary)
			self._fixture(root, 'RfmRenameProbe')
			executable, collection = Mock(), Mock()
			with patch('PyInstaller.utils.hooks.collect_all', return_value=([], [], [])), \
					patch.dict('os.environ', {'ROYIFILEMANAGER_BUILD_CONSOLE': '1'}):
				spec = runpy.run_path(str(self.ROOT / 'application.spec'), init_globals={
					'SPECPATH': str(root), 'Analysis': Mock(), 'PYZ': Mock(),
					'EXE': executable, 'COLLECT': collection
				})
			self.assertEqual('RfmRenameProbe', executable.call_args.kwargs['name'])
			self.assertTrue(executable.call_args.kwargs['console'])
			self.assertEqual('RfmRenameProbe', collection.call_args.kwargs['name'])
			self.assertIn(('src/build/settings/base.json', 'resources/build-settings'), spec['datas'])


class RuntimeNamingTest(TestCase):
	def test_message_box_has_explicit_product_title(self):
		import os
		import subprocess
		script = '''
from unittest.mock import patch
from PyQt5.QtWidgets import QApplication
from fman.impl import widgets
application = QApplication([])
with patch.object(widgets, 'APP_NAME', 'RfmRenameProbe'):
    dialog = widgets.MessageBox(None)
    assert dialog.windowTitle() == 'RfmRenameProbe'
'''
		result = subprocess.run([sys.executable, '-c', script],
			env=dict(os.environ, QT_QPA_PLATFORM='offscreen'),
			capture_output=True, text=True, timeout=30)
		self.assertEqual(0, result.returncode, result.stdout + result.stderr)

	def test_guidance_uses_product_name(self):
		from fman.impl.onboarding import tutorial, cleanup_guide
		from fman.impl import usage_helper, nonexistent_shortcut_handler
		pane = Mock()
		pane.window.get_panes.return_value = [pane]
		with patch.object(tutorial, 'APP_NAME', 'RfmRenameProbe'), \
				patch.object(cleanup_guide, 'APP_NAME', 'RfmRenameProbe'):
			tour = tutorial.Tutorial(False, Mock(), pane, Mock(), Mock(), Mock())
			guide = cleanup_guide.CleanupGuide(Mock(), pane, Mock(), Mock(), Mock())
			self.assertEqual('Welcome to RfmRenameProbe!', tour._steps[0]._title)
			self.assertIn('RfmRenameProbe will jump', ' '.join(guide._steps[3]._paragraphs))
		with patch.object(usage_helper, 'APP_NAME', 'RfmRenameProbe'), \
				patch.object(usage_helper, 'show_alert') as alert:
			usage_helper.UsageHelper(True)._on_mouse_action(pane, ['AbortedTour'])
			self.assertIn('RfmRenameProbe is optimized', alert.call_args.args[0])
		with patch.object(nonexistent_shortcut_handler, 'APP_NAME', 'RfmRenameProbe'), \
				patch.object(nonexistent_shortcut_handler, 'show_alert') as alert:
			nonexistent_shortcut_handler.NonexistentShortcutHandler(Mock(), {}, Mock())._handle_ctrl_cmd_t()
			self.assertIn('RfmRenameProbe does not yet support tabs', alert.call_args.args[0])

	def test_runtime_product_comes_from_settings(self):
		from fman.impl.product import APP_NAME
		self.assertEqual(get_build_settings()['app_name'], APP_NAME)

	def test_qt_identity_and_window_title_use_product_name(self):
		from fman.impl import application_context as runtime
		context = runtime.DevelopmentApplicationContext()
		context.style = Mock()
		context.palette = Mock()
		context.mac_clipboard_fix = None
		context.get_resource = Mock(return_value='icon')
		with patch.object(runtime, 'APP_NAME', 'RfmRenameProbe'), \
				patch.object(runtime, 'Application') as factory, \
				patch.object(runtime, 'QIcon'), \
				patch.object(runtime, '_set_windows_app_id'):
			application = context.app
			self.assertIs(factory.return_value, application)
			application.setOrganizationName.assert_called_once_with('RfmRenameProbe')
			application.setOrganizationDomain.assert_called_once_with('RfmRenameProbe')
			application.setApplicationName.assert_called_once_with('RfmRenameProbe')
			self.assertEqual('RfmRenameProbe', context._get_main_window_title())

	def test_windows_taskbar_identity_uses_product_name(self):
		from fman.impl import application_context as runtime
		with patch.object(runtime, 'APP_NAME', 'RfmRenameProbe'), \
				patch.object(runtime, 'PLATFORM', 'Windows'), \
				patch('ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID') as set_id:
			runtime._set_windows_app_id()
			set_id.assert_called_once_with('RfmRenameProbe')

	def test_profile_and_platform_error_use_product_name(self):
		from fman import main
		with patch.object(main, 'APP_NAME', 'RfmRenameProbe'), \
				patch('fbs_runtime.application_context.is_frozen', return_value=True), \
				patch('cProfile.run') as profile:
			main.profile_main()
			self.assertEqual('RfmRenameProbe.profile', profile.call_args.kwargs['filename'])
			with patch.object(sys, 'platform', 'unsupported'):
				with self.assertRaisesRegex(RuntimeError, 'RfmRenameProbe'):
					main.main()


class DocumentationNamingTest(TestCase):
	def test_hook_updates_metadata_and_explicit_tokens_only(self):
		from types import SimpleNamespace
		root = Path(__file__).resolve().parents[4]
		hook = runpy.run_path(str(root / 'src/misc/docs_hooks.py'))
		with TemporaryDirectory() as temporary:
			fixture = Path(temporary)
			path = fixture / 'src/build/settings/base.json'
			path.parent.mkdir(parents=True)
			path.write_text(json.dumps({'app_name': 'RfmRenameProbe'}), encoding='utf-8')
			config = SimpleNamespace(config_file_path=str(fixture / 'mkdocs.yml'), extra={})
			self.assertIs(config, hook['on_config'](config))
			self.assertEqual('RfmRenameProbe', config.site_name)
			self.assertIsInstance(config.copyright, str)
			self.assertIn('RfmRenameProbe', config.copyright)
			markdown = '# {{ app_name }}\n```powershell\n.\\{{ app_name }}.exe\n```\n'
			unchanged = '[repo](https://example.test/repository) ![image](assets/stable.png)\n`literal` {{ other }}'
			path.unlink()
			self.assertEqual('# RfmRenameProbe\n```powershell\n.\\RfmRenameProbe.exe\n```\n' + unchanged,
				hook['on_page_markdown'](markdown + unchanged, config=config))
			with self.assertRaisesRegex(ValueError, 'base.json'):
				hook['on_config'](config)
			path.write_text(json.dumps({'app_name': 'CON'}), encoding='utf-8')
			with self.assertRaisesRegex(ValueError, 'app_name'):
				hook['on_config'](config)