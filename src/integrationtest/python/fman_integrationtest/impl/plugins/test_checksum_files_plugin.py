from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
import os
import subprocess
import sys


class ChecksumFilesPluginTest(TestCase):
    def test_packaged_loader_native_reload_and_inflight_cancellation(self):
        from src.main.resources.base.Plugins.ChecksumFiles.package import package
        with TemporaryDirectory() as directory:
            path = package(Path(directory) / 'Third-party' / 'ChecksumFiles')
            script = 'from fman_integrationtest.impl.plugins.test_checksum_files_plugin import native_smoke; import sys; native_smoke(sys.argv[1])'
            completed = subprocess.run([sys.executable, '-c', script, str(path)], capture_output=True, text=True, timeout=30)
            self.assertEqual(0, completed.returncode, completed.stdout + completed.stderr)
            self.assertIn('native checksum lifecycle passed', completed.stdout)

    def test_supplied_portable_commands_and_private_backend(self):
        executable = os.environ.get('CHECKSUM_FILES_PORTABLE_EXE')
        if not executable:
            self.skipTest('Set CHECKSUM_FILES_PORTABLE_EXE to an existing portable host.')
        self._run_application_probe(Path(executable))

    def test_source_commands_are_bundled_without_installation(self):
        self._run_application_probe()

    def _run_application_probe(self, executable=None):
        import build
        import json
        import shutil
        from runpy import run_path
        from unittest.mock import Mock, patch
        from PyInstaller.building.utils import format_binaries_and_datas
        from src.misc.generate_checksum_fixtures import generate
        with TemporaryDirectory() as directory:
            root = Path(directory)
            settings = root / 'UserSettings'
            third_party = settings / 'Plugins' / 'Third-party'
            if executable is not None:
                host = root / 'Host'
                shutil.copytree(executable.parent, host, ignore=shutil.ignore_patterns('UserSettings'))
                bundled = host / '_internal/resources/Plugins/ChecksumFiles'
                if bundled.exists():
                    shutil.rmtree(bundled)
                with patch('PyInstaller.utils.hooks.collect_all', return_value=([], [], [])):
                    specification = run_path(str(build.ROOT / 'application.spec'), init_globals={
                        'SPECPATH': str(build.ROOT), 'Analysis': Mock(), 'PYZ': Mock(), 'EXE': Mock(), 'COLLECT': Mock()})
                for kind in ('datas', 'binaries'):
                    for destination, source in format_binaries_and_datas(specification[kind], workingdir=str(build.ROOT)):
                        relative = Path(destination)
                        if relative.parts[:3] == ('resources', 'Plugins', 'ChecksumFiles'):
                            target = host / '_internal' / relative
                            target.parent.mkdir(parents=True, exist_ok=True)
                            shutil.copy2(source, target)
                command = [str(host / executable.name)]
            else:
                command = [sys.executable, str(build.ROOT / 'src/main/python/fman/main.py')]
            probe = third_party / 'ChecksumProbe' / 'checksum_probe'
            probe.mkdir(parents=True)
            (probe / '__init__.py').write_text(PORTABLE_PROBE, encoding='utf-8')
            corpus = root / 'corpus'
            generate(corpus)
            report = root / 'report.json'
            environment = build._environment()
            if executable is not None:
                for name in ('PYTHONPATH', 'PYTHONHOME', 'QT_PLUGIN_PATH', 'QT_QPA_PLATFORM_PLUGIN_PATH'):
                    environment.pop(name, None)
                environment['PATH'] = os.pathsep.join((str(host), os.path.join(os.environ['WINDIR'], 'System32'), os.environ['WINDIR']))
            environment.update({
                'ROYIFILEMANAGER_USER_SETTINGS': str(settings),
                'CHECKSUM_PROBE_CORPUS': str(corpus),
                'CHECKSUM_PROBE_REPORT': str(report),
                'QT_QPA_PLATFORM': 'windows',
                'PYTHONFAULTHANDLER': '1',
            })
            completed = subprocess.run(command, env=environment, cwd=directory, capture_output=True, text=True, timeout=45)
            self.assertTrue(report.exists(), completed.stdout + completed.stderr)
            result = json.loads(report.read_text(encoding='utf-8'))
            self.assertEqual(0, completed.returncode, {'report': result, 'stderr': completed.stderr, 'stdout': completed.stdout})
            self.assertNotIn('error', result)
            self.assertEqual(executable is not None, result['frozen'])
            self.assertTrue(result['bundled_plugin'])
            self.assertEqual(83, result['matched'])
            self.assertEqual(12, result['algorithms'])
            self.assertEqual(executable is not None, result['private_native'])
            self.assertTrue(result['native_after_reload'])
            self.assertEqual(['a-first.sha256', 'B-highlighted.sha256'], result['manifest_selection'])
            self.assertEqual(['', 'checksum'], result['palette_queries'])
            print('Bundled checksum smoke:', json.dumps(result, sort_keys=True))


def native_smoke(path):
    from fman import PLATFORM, Window
    from fman.impl.plugins.command_registry import ApplicationCommandRegistry, PaneCommandRegistry
    from fman.impl.plugins.config import Config
    from fman.impl.plugins.context_menu import ContextMenuProvider
    from fman.impl.plugins.key_bindings import KeyBindings
    from fman.impl.plugins.mother_fs import MotherFileSystem
    from fman.impl.plugins.plugin import ExternalPlugin
    from fman_integrationtest.impl.plugins import StubCommandCallback, StubFontDatabase, StubTheme
    from fman_unittest.impl.plugins import StubErrorHandler
    from threading import Event, Thread
    from unittest.mock import Mock

    config = Config(PLATFORM)
    errors = StubErrorHandler()
    callback = StubCommandCallback()
    pane_registry = PaneCommandRegistry(errors, callback)
    window = Window(None, pane_registry)
    application_registry = ApplicationCommandRegistry(window, errors, callback)
    bindings = KeyBindings()
    context = ContextMenuProvider(pane_registry, application_registry, bindings)
    plugin = ExternalPlugin(path, config, StubTheme(), StubFontDatabase(), context,
        errors, application_registry, pane_registry, bindings, MotherFileSystem(None), window)
    assert plugin.load(), errors.error_messages
    try:
        assert set(pane_registry.get_commands()) == {'generate_checksum_file', 'verify_checksum'}
        import checksum_files
        from checksum_files import commands, engine
        assert commands.ChecksumController.owner.active
        assert not any(name.startswith('checksum_files._vendor.blake3') for name in sys.modules)
        with TemporaryDirectory() as directory:
            config.add_dir(directory)
            Path(directory, 'ChecksumFiles.json').write_text('{}', encoding='utf-8')
            assert config.load_json('ChecksumFiles.json')['default_algorithm'] == 'sha256'
            source = Path(directory) / 'data'
            source.write_bytes(b'abc')
            algorithm = engine.BY_ID['blake3']
            digest, count = engine.hash_file(str(source), algorithm, engine.Settings())
            assert digest == '6437b3ac38465133ffb63b75273a8db548c558465d79db03fd359c6cd5bd9d85'
            assert count == 3
            import blake3
            assert blake3.blake3(b'abc').hexdigest() == digest
            assert sys.modules['checksum_files._vendor.blake3.blake3'].__file__.startswith(path)
            plugin.unload()
            assert not commands.ChecksumController.owner.active
            assert plugin.load(), errors.error_messages
            from checksum_files import commands, engine
            assert engine.hash_file(str(source), engine.BY_ID['blake3'], engine.Settings())[0] == digest
            source.write_bytes(b'checksum' * (3 * 1024 * 1024))
            started, resume = Event(), Event()
            pane = Mock()
            failures = []
            def operation(check, progress):
                def pause(amount):
                    started.set()
                    if not resume.wait(5):
                        raise TimeoutError('Reload test did not resume.')
                return engine.hash_file(str(source), engine.BY_ID['blake3'], engine.Settings(), check, pause)
            with commands._running(pane) as run:
                task = commands._ChecksumTask('BLAKE3 reload test', run, operation)
                def execute():
                    try:
                        task()
                    except BaseException as error:
                        failures.append(error)
                worker = Thread(target=execute)
                worker.start()
                try:
                    assert started.wait(5), 'Native work did not start.'
                    plugin.unload()
                    assert plugin.load(), errors.error_messages
                finally:
                    resume.set()
                    worker.join(5)
                assert not worker.is_alive()
                assert not failures, failures
                assert not task.completed
                assert task.result is None
        assert not errors.error_messages, errors.error_messages
    finally:
        plugin.unload()
    assert not list(pane_registry.get_commands())
    print('native checksum lifecycle passed')


PORTABLE_PROBE = r'''
from fman import DirectoryPaneListener
from threading import Lock, Thread
import os

_lock = Lock()
_started = False

class ChecksumProbe(DirectoryPaneListener):
    def on_path_changed(self):
        global _started
        with _lock:
            if _started or os.environ.get('CHECKSUM_PROBE_ACTIVE') == '1':
                return
            _started = True
            os.environ['CHECKSUM_PROBE_ACTIVE'] = '1'
        Thread(target=self.check, daemon=True).start()

    def check(self):
        import json
        from pathlib import Path
        import sys
        from threading import Event
        from PyQt5.QtCore import QMetaObject, Qt, PYQT_VERSION_STR, QT_VERSION_STR
        from PyQt5.QtWidgets import QApplication
        from fman import APP_VERSION, YES
        from fman.url import as_url
        from fman.impl.util.qt.thread import run_in_main_thread
        report = {'host': APP_VERSION, 'python': sys.version, 'qt': QT_VERSION_STR,
                  'pyqt': PYQT_VERSION_STR, 'frozen': bool(getattr(sys, 'frozen', False))}
        try:
            import checksum_files
            from checksum_files import commands, engine
            report['bundled_plugin'] = 'resources' in Path(checksum_files.__file__).parts and 'Third-party' not in Path(checksum_files.__file__).parts
            corpus = Path(os.environ['CHECKSUM_PROBE_CORPUS'])
            loaded = Event()
            self.pane.set_path(as_url(corpus), callback=lambda *args: loaded.set())
            if not loaded.wait(10):
                raise RuntimeError('Portable pane did not load the corpus.')
            registered = self.pane.get_commands()
            assert 'generate_checksum_file' in registered and 'verify_checksum' in registered
            from core import commands as core_commands
            original_quicksearch = core_commands.show_quicksearch
            palette_queries = []
            def inspect_palette(suggest, **kwargs):
                for query in ('', 'checksum'):
                    titles = {item.title for item in suggest(query)}
                    assert {'Generate checksum file', 'Verify checksum file'} <= titles
                    palette_queries.append(query)
                return None
            core_commands.show_quicksearch = inspect_palette
            try:
                self.pane.run_command('command_palette')
            finally:
                core_commands.show_quicksearch = original_quicksearch
            report['palette_queries'] = palette_queries
            original_choose, original_prompt, original_alert = commands._choose, commands.show_prompt, commands.show_alert
            alerts = []
            replacements = []
            def alert(message, *args, **kwargs):
                if message.startswith('Replace checksum file?'):
                    replacements.append(message)
                    return YES
                alerts.append(message)
            try:
                commands._choose = lambda items, default=0: 'sha256'
                commands.show_prompt = lambda *args, **kwargs: ('CheckSum.sha256', True)
                commands.show_alert = alert
                commands.GenerateChecksumFile(self.pane)()
                assert not alerts, alerts
                assert (corpus / 'CheckSum.sha256').is_file()
                commands.show_prompt = lambda *args, **kwargs: ('CHECKSUM.sha256', True)
                commands.GenerateChecksumFile(self.pane)()
                assert not alerts, alerts
                assert len(replacements) == 1
                commands.VerifyChecksum(self.pane)()
                assert not alerts, alerts
            finally:
                commands._choose, commands.show_prompt, commands.show_alert = original_choose, original_prompt, original_alert
            table = commands._tables[self.pane]
            assert '83 matched, 0 problems' in table.summary, table.summary
            assert len(table.rows) == 0
            @run_in_main_thread
            def inspect_table():
                table.switch(True)
                assert len(table.rows) == 83
                assert self.pane.window._widget._panel_dock is None
                table.handle.close()
                assert table.closed
            inspect_table()
            first = corpus / 'a-first.sha256'
            highlighted = corpus / 'B-highlighted.sha256'
            first.write_bytes((corpus / 'CHECKSUM.sha256').read_bytes())
            highlighted.write_bytes(b'invalid record\n')
            from fman.fs import notify_file_added
            notify_file_added(as_url(first))
            notify_file_added(as_url(highlighted))
            ordinary = corpus / 'ascii-lf.txt'
            loaded.clear()
            self.pane.set_path(as_url(corpus), callback=lambda *args: loaded.set())
            if not loaded.wait(10):
                raise RuntimeError('Portable pane did not refresh the manifests.')
            def unexpected_picker(*args, **kwargs):
                raise AssertionError('Verification opened a manifest picker.')
            choices = []
            commands._choose, commands.show_alert = unexpected_picker, alert
            try:
                for cursor, expected_manifest, expected_summary in (
                        (ordinary, first, '83 matched, 0 problems'),
                        (highlighted, highlighted, '0 matched, 1 problems')):
                    self.pane.place_cursor_at(as_url(cursor))
                    assert self.pane.get_file_under_cursor() == as_url(cursor), (self.pane.get_file_under_cursor(), as_url(cursor))
                    commands.VerifyChecksum(self.pane)()
                    assert not alerts, alerts
                    chosen_table = commands._tables[self.pane]
                    assert Path(chosen_table.manifest).name == expected_manifest.name
                    assert expected_summary in chosen_table.summary, chosen_table.summary
                    @run_in_main_thread
                    def close_chosen_table():
                        from fman.impl.ui.facade import _hosts
                        host = next(host for host in _hosts.values() if host.owner is chosen_table.owner)
                        assert expected_manifest.name in host.windowTitle()
                        chosen_table.handle.close()
                    close_chosen_table()
                    choices.append(expected_manifest.name)
            finally:
                commands._choose, commands.show_alert = original_choose, original_alert
            report['manifest_selection'] = choices
            sample = corpus / 'empty.bin'
            if not sample.exists():
                sample = next(path for path in corpus.iterdir() if path.is_file() and path.stat().st_size == 0)
            for algorithm in engine.ALGORITHMS:
                digest, count = engine.hash_file(str(sample), algorithm, engine.Settings())
                assert count == 0 and len(digest) == algorithm.hex_length
            expected = 'af1349b9f5f9a1a6a0404dea36dcc9499bcb25c9adc112b7cc9a93cae41f3262'
            assert engine.hash_file(str(sample), engine.BY_ID['blake3'], engine.Settings())[0] == expected
            module = sys.modules.get('checksum_files._vendor.blake3.blake3')
            report.update(matched=83, algorithms=12, private_native=module is not None and '_vendor' in module.__file__)
            from fman import run_application_command
            previous_owner = commands.ChecksumController.owner
            run_application_command('reload_plugins')
            assert previous_owner.active
            from checksum_files import commands, engine
            assert commands.ChecksumController.owner is previous_owner
            assert engine.hash_file(str(sample), engine.BY_ID['blake3'], engine.Settings())[0] == expected
            report['native_after_reload'] = True
        except BaseException as error:
            import traceback
            report['error'] = repr(error)
            report['traceback'] = traceback.format_exc()
        finally:
            Path(os.environ['CHECKSUM_PROBE_REPORT']).write_text(json.dumps(report), encoding='utf-8')
            QMetaObject.invokeMethod(QApplication.instance(), 'quit', Qt.QueuedConnection)
'''