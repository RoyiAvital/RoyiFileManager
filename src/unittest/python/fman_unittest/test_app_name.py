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
		checksum_helper = root / 'src/main/resources/base/Plugins/ChecksumFiles/package.py'
		checksum_helper.parent.mkdir(parents=True)
		shutil.copy2(self.ROOT / checksum_helper.relative_to(root), checksum_helper)
		shutil.copy2(self.ROOT / 'build.py', root / 'build.py')
		return settings_path

	def test_build_paths_freeze_and_help_use_settings(self):
		for name in ('RfmRenameProbe', 'build'):
			with self.subTest(name=name), TemporaryDirectory() as temporary:
				root = Path(temporary).resolve(strict=True)
				self._fixture(root, name)
				build = runpy.run_path(str(root / 'build.py'))
				self.assertEqual(name, build['APP_NAME'])
				self.assertEqual(root / 'target' / name, build['DIST_DIR'])
				self.assertEqual(root / 'target/.pyinstaller', build['WORK_DIR'])
				build['DIST_DIR'].mkdir(parents=True)
				with patch.dict(build['freeze'].__globals__, {
					'_require_windows': Mock(), '_ensure_7za': Mock(),
					'_ensure_everything': Mock(), '_verify_native_parser': Mock(),
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
			root = Path(temporary).resolve(strict=True)
			settings_path = self._fixture(root, 'RfmRenameProbe')
			build = runpy.run_path(str(root / 'build.py'))
			settings_path.unlink()
			distribution = build['DIST_DIR']
			distribution.mkdir(parents=True)
			(distribution / 'RfmRenameProbe.exe').write_bytes(b'fixture')
			with patch.dict(build['package'].__globals__, {
				'_require_windows': Mock(), '_copy_dependency_manifests': Mock(),
				'_verify_everything': Mock(), '_verify_native_parser_packaged': Mock(),
				'_verify_pdf_helper_packaged': Mock()
			}), patch('builtins.print') as output:
				build['package']()
			archive = root / 'target/RfmRenameProbe-9.8.7-windows-x86_64.zip'
			output.assert_called_once_with(archive)
			with ZipFile(archive) as package:
				self.assertEqual(['RfmRenameProbe/RfmRenameProbe.exe'], package.namelist())

	def test_spec_derives_both_names_and_preserves_bundled_settings(self):
		with TemporaryDirectory() as temporary:
			root = Path(temporary).resolve(strict=True)
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


class NativeParserPackagingTest(TestCase):
	def test_packaged_copy_must_exist_and_match_the_verified_binary(self):
		import build
		with TemporaryDirectory() as temporary:
			root = Path(temporary)
			official = root / 'official.pyd'
			packaged = root / 'frozen/_internal/resources/Plugins/Core/core/fs/local/windows/_fsparser.pyd'
			with patch.object(build, '_verify_native_parser') as verify, \
					patch.object(build, 'NATIVE_PARSER_BINARY', official), \
					patch.object(build, 'DIST_DIR', root / 'frozen'):
				for official_bytes, packaged_bytes in ((None, None), (b'module', None), (b'module', b'other')):
					with self.subTest(official=official_bytes, packaged=packaged_bytes):
						for path, content in ((official, official_bytes), (packaged, packaged_bytes)):
							path.unlink(missing_ok=True)
							if content is not None:
								path.parent.mkdir(parents=True, exist_ok=True)
								path.write_bytes(content)
						with self.assertRaises(SystemExit):
							build._verify_native_parser_packaged()
				packaged.write_bytes(b'module')
				build._verify_native_parser_packaged()
				self.assertEqual(4, verify.call_count)

	def test_source_check_failure_stops_the_packaged_check(self):
		import build
		with patch.object(build, '_verify_native_parser', side_effect=SystemExit('mismatch')), \
				patch.object(build, '_sha256') as digest, self.assertRaises(SystemExit):
			build._verify_native_parser_packaged()
		digest.assert_not_called()


class PdfHelperPackagingTest(TestCase):
	def _replies(self):
		identity = dict(epoch=1, generation=1, revision=0, fingerprint=[1, 2, 3, 4])
		frames = [({'type': 'ready'}, b''),
			(dict(identity, type='document', operation=1, sizes=[[200, 200], [300, 150]]), b'')]
		for page, (width, height, color) in enumerate(((200, 200, b'\x00\x00\xff\xff'),
			(300, 150, b'\x00\xff\x00\xff'))):
			frames.append((dict(identity, type='page', operation=page + 2, page=page,
				width=width, height=height, stride=width * 4), color * width * height))
		return frames

	def test_packaged_command_environment_and_protocol(self):
		import build
		from _quick_view_pdf_worker import FrameDecoder, encode_frame
		with TemporaryDirectory() as temporary:
			distribution = Path(temporary)
			executable = distribution / 'PdfRenameProbe.exe'
			executable.touch()
			frames = self._replies()
			response = b''.join(encode_frame(header, pixels) for header, pixels in frames)
			seen = []
			def run(command, **options):
				self.assertEqual([str(executable), '--quick-view-pdf-worker'], command)
				self.assertEqual(distribution, options['cwd'])
				self.assertEqual(30, options['timeout'])
				self.assertTrue(options['capture_output'])
				self.assertTrue(options['check'])
				decoder = FrameDecoder()
				requests = decoder.feed(options['input'])
				decoder.finish()
				self.assertEqual(['open', 'render', 'render', 'close'], [header['type'] for header, data in requests])
				self.assertTrue(all(not data for header, data in requests))
				for operation, (header, data) in enumerate(requests, 1):
					self.assertEqual((1, 1, operation, 0), tuple(header[name]
						for name in ('epoch', 'generation', 'operation', 'revision')))
				path = Path(requests[0][0]['path'])
				self.assertTrue(path.is_absolute())
				self.assertEqual(build._pdf_smoke_fixture(), path.read_bytes())
				seen.append(path)
				environment = options['env']
				self.assertFalse(any(name.upper().startswith(('PYTHON', 'CONDA', '_PYI', 'PYINSTALLER'))
					for name in environment))
				windows = Path(build.os.environ['SYSTEMROOT'])
				self.assertEqual([str(windows / 'System32'), str(windows)], environment['PATH'].split(build.os.pathsep))
				return build.subprocess.CompletedProcess(command, 0, response, b'')
			with patch.object(build, 'DIST_DIR', distribution), patch.object(build, 'APP_NAME', 'PdfRenameProbe'), \
					patch.dict(build.os.environ, {'PYTHONPATH': 'source', 'PYTHONHOME': 'development',
						'CONDA_PREFIX': 'environment', '_PYI_APPLICATION_HOME_DIR': 'old-bundle'}), \
					patch.object(build.subprocess, 'run', side_effect=run), patch('builtins.print') as output:
				build._verify_pdf_helper_packaged()
			output.assert_called_once()
			self.assertEqual(1, len(seen))
			self.assertFalse(seen[0].exists())

	def test_bad_replies_block_packaging(self):
		import build
		from _quick_view_pdf_worker import encode_frame
		cases = []
		for index, field, value in ((0, 'type', 'other'), (1, 'sizes', [[200, 200]]),
			(1, 'fingerprint', [1]), (1, 'operation', 2), (2, 'generation', 2),
			(2, 'revision', 1), (2, 'page', 1), (2, 'width', 201), (2, 'stride', 4),
			(2, 'fingerprint', [4, 3, 2, 1]), (3, 'height', 149)):
			frames = self._replies()
			frames[index][0][field] = value
			cases.append(b''.join(encode_frame(header, pixels) for header, pixels in frames))
		for index, pixels in ((0, b'extra'), (1, b'extra'), (2, b'short'),
			(2, b'\x00\xff\x00\xff' * 200 * 200), (3, b'\x00\x00\xff\xff' * 300 * 150)):
			frames = self._replies()
			frames[index] = (frames[index][0], pixels)
			cases.append(b''.join(encode_frame(header, payload) for header, payload in frames))
		valid = b''.join(encode_frame(header, pixels) for header, pixels in self._replies())
		cases.extend((b'', b'not a frame', valid[:-1], valid + encode_frame({'type': 'ready'}),
			encode_frame({'type': 'ready'}) + encode_frame({'type': 'error', 'message': 'Backend unavailable'})))
		with TemporaryDirectory() as temporary, patch.object(build, 'DIST_DIR', Path(temporary)):
			(build.DIST_DIR / (build.APP_NAME + '.exe')).touch()
			for index, response in enumerate(cases):
				with self.subTest(case=index), patch.object(build.subprocess, 'run',
						return_value=build.subprocess.CompletedProcess([], 0, response, b'')), \
						self.assertRaisesRegex(SystemExit, 'Packaged PDF helper smoke failed'):
					build._verify_pdf_helper_packaged()

	def test_missing_executable_launch_crash_and_timeout(self):
		import build
		with TemporaryDirectory() as temporary, patch.object(build, 'DIST_DIR', Path(temporary)):
			with patch.object(build.subprocess, 'run') as execute, self.assertRaisesRegex(SystemExit, 'missing'):
				build._verify_pdf_helper_packaged()
			execute.assert_not_called()
			(build.DIST_DIR / (build.APP_NAME + '.exe')).touch()
			for error in (OSError('launch failed'), build.subprocess.CalledProcessError(1, ['helper']),
				build.subprocess.TimeoutExpired(['helper'], 30)):
				seen = []
				def run(command, **options):
					from _quick_view_pdf_worker import FrameDecoder
					seen.append(Path(FrameDecoder().feed(options['input'])[0][0]['path']))
					raise error
				with self.subTest(error=type(error).__name__), patch.object(build.subprocess, 'run', side_effect=run), \
						self.assertRaisesRegex(SystemExit, 'Packaged PDF helper smoke failed'):
					build._verify_pdf_helper_packaged()
				self.assertFalse(seen[0].exists())

	def test_timeout_kills_child_and_cleans_fixture(self):
		import build
		from _quick_view_pdf_worker import FrameDecoder
		run, popen = build.subprocess.run, build.subprocess.Popen
		children, paths = [], []
		def start(*args, **options):
			child = popen(*args, **options)
			children.append(child)
			return child
		def hang(command, **options):
			paths.append(Path(FrameDecoder().feed(options['input'])[0][0]['path']))
			options['timeout'] = .2
			return run([sys.executable, '-B', '-c', 'from threading import Event; Event().wait()'], **options)
		with TemporaryDirectory() as temporary, patch.object(build, 'DIST_DIR', Path(temporary)):
			(build.DIST_DIR / (build.APP_NAME + '.exe')).touch()
			with patch.object(build.subprocess, 'Popen', side_effect=start), \
					patch.object(build.subprocess, 'run', side_effect=hang), \
					self.assertRaisesRegex(SystemExit, 'timed out'):
				build._verify_pdf_helper_packaged()
			self.assertEqual(1, len(children))
			self.assertIsNotNone(children[0].poll())
			self.assertFalse(paths[0].exists())

	def test_smoke_exchange_with_real_windowed_worker(self):
		import build
		executable = Path(sys.executable).with_name('pythonw.exe')
		self.assertTrue(executable.is_file())
		worker = build.ROOT / 'src/main/python/_quick_view_pdf_worker.py'
		code = 'import runpy, sys; sys.exit(runpy.run_path(sys.argv[1])["main"]())'
		run = build.subprocess.run
		def launch(command, **options):
			return run([str(executable), '-B', '-c', code, str(worker)], **options)
		with TemporaryDirectory() as temporary, patch.object(build, 'DIST_DIR', Path(temporary)):
			(build.DIST_DIR / (build.APP_NAME + '.exe')).touch()
			with patch.object(build.subprocess, 'run', side_effect=launch), patch('builtins.print'):
				build._verify_pdf_helper_packaged()

	def test_package_stops_before_archive_on_pdf_smoke_failure(self):
		import build
		with TemporaryDirectory() as temporary, \
				patch.object(build, 'DIST_DIR', Path(temporary)), \
				patch.object(build, '_require_windows'), \
				patch.object(build, '_verify_everything'), \
				patch.object(build, '_verify_native_parser_packaged'), \
				patch.object(build, '_verify_pdf_helper_packaged',
					side_effect=SystemExit('Packaged PDF helper failed')) as verify, \
				patch.object(build, '_copy_dependency_manifests') as manifests, \
				patch.object(build, 'ZipFile') as archive, patch('builtins.print'):
			with self.assertRaisesRegex(SystemExit, 'Packaged PDF helper failed'):
				build.package()
			verify.assert_called_once_with()
			manifests.assert_not_called()
			archive.assert_not_called()


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
			usage_helper.UsageHelper(True)._on_mouse_action(pane, ('aborted', 1))
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