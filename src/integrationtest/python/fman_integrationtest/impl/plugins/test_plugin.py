from fman import ApplicationCommand, DirectoryPaneCommand, \
	DirectoryPane, DirectoryPaneListener, Window
from fman.impl.plugins import ExternalPlugin
from fman.impl.plugins.command_registry import PaneCommandRegistry, \
	ApplicationCommandRegistry
from fman.impl.plugins.config import Config
from fman.impl.plugins.context_menu import ContextMenuProvider
from fman.impl.plugins.key_bindings import KeyBindings
from fman.impl.plugins.mother_fs import MotherFileSystem
from fman.impl.plugins.plugin import Plugin
from fman_integrationtest import get_resource
from fman_integrationtest import test_qt as qt_tests
from fman_integrationtest.impl.plugins import StubCommandCallback, StubTheme, \
	StubFontDatabase
from fman_unittest.impl.plugins import StubErrorHandler
from os.path import join
from unittest import TestCase

import sys
import yaml

setUpModule = qt_tests.setUpModule
tearDownModule = qt_tests.tearDownModule

class PluginTest(TestCase):
	def test_error_instantiating_application_command(self):
		self._plugin._register_application_command(FailToInstantiateAC)
		self.assertEqual(
			["Could not instantiate command 'FailToInstantiateAC'."],
			self._error_handler.error_messages
		)
	def test_error_instantiating_directory_pane_command(self):
		self._plugin._register_directory_pane_command(FailToInstantiateDPC)
		self._plugin.on_pane_added(self._pane)
		self._pane.run_command('fail_to_instantiate_dpc')
		self.assertEqual(
			["Could not instantiate command 'FailToInstantiateDPC'."],
			self._error_handler.error_messages
		)
	def test_error_instantiating_directory_pane_listener(self):
		self._plugin._register_directory_pane_listener(FailToInstantiateDPL)
		self._plugin.on_pane_added(self._pane)
		self.assertEqual(
			["Could not instantiate listener 'FailToInstantiateDPL'."],
			self._error_handler.error_messages
		)
	def setUp(self):
		super().setUp()
		self._error_handler = StubErrorHandler()
		self._command_callback = StubCommandCallback()
		self._panecmd_registry = \
			PaneCommandRegistry(self._error_handler, self._command_callback)
		self._window = Window(None, self._panecmd_registry)
		self._appcmd_registry = ApplicationCommandRegistry(
			self._window, self._error_handler, self._command_callback
		)
		self._key_bindings = KeyBindings()
		self._plugin = Plugin(
			self._error_handler, self._appcmd_registry, self._panecmd_registry,
			self._key_bindings, None, None
		)
		self._pane = DirectoryPane(None, None, self._panecmd_registry)

class FailToInstantiateAC(ApplicationCommand):
	def __init__(self, *args, **kwargs):
		raise ValueError()

class FailToInstantiateDPC(DirectoryPaneCommand):
	def __init__(self, *args, **kwargs):
		raise ValueError()

class FailToInstantiateDPL(DirectoryPaneListener):
	def __init__(self, *args, **kwargs):
		raise ValueError()

class BundledCommandCategoryTest(TestCase):

	CATEGORIES = {'Application', 'Settings', 'File', 'Clipboard', 'Selection',
		'Navigation', 'View', 'Search', 'Favorites', 'Tools'}

	def test_every_bundled_command_has_a_known_category(self):
		from fman.impl.plugins.builtin import ToggleFullscreen, TourCommand
		from fman.impl.plugins.command_registry import _get_category
		from importlib import import_module
		from inspect import isclass
		from pathlib import Path
		root = Path(__file__).resolve().parents[6]
		plugin_dirs = sorted((root / 'src/main/resources/base/Plugins').iterdir())
		plugin_dirs.append(root / 'plugins/BatchFileRenamer')
		commands = {'TourCommand': TourCommand, 'ToggleFullscreen': ToggleFullscreen}
		path_before = list(sys.path)
		self.addCleanup(setattr, sys, 'path', path_before)
		for plugin_dir in plugin_dirs:
			if str(plugin_dir) not in sys.path:
				sys.path.append(str(plugin_dir))
			for init in sorted(plugin_dir.glob('*/__init__.py')):
				module = import_module(init.parent.name)
				for value in vars(module).values():
					if isclass(value) and value not in (ApplicationCommand, DirectoryPaneCommand) \
							and issubclass(value, (ApplicationCommand, DirectoryPaneCommand)):
						commands[value.__name__] = value
		self.assertGreater(len(commands), 100)
		wrong = {name: _get_category(cls) for name, cls in commands.items()
			if _get_category(cls) not in self.CATEGORIES and name != 'none'}
		self.assertEqual({}, wrong)
		self.assertEqual('', _get_category(commands['none']))

class ExternalPluginTest(TestCase):
	def test_load(self):
		if not self._plugin.load():
			self.fail(self._error_handler.error_messages)
		with open(join(self._plugin_dir, 'Key Bindings.yaml'), 'r', encoding='utf-8') as f:
			bindings = yaml.safe_load(f)
		self.assertEqual(bindings, self._config.load_json('Key Bindings.yaml'))
		plugin_font = join(self._plugin_dir, 'Open Sans.ttf')
		self.assertEqual([plugin_font], self._font_database.loaded_fonts)
		theme_css = join(self._plugin_dir, 'Theme.css')
		self.assertEqual([theme_css], self._theme.loaded_css_files)
		self.assertIn(self._plugin_dir, sys.path)
		self.assertIn('test_command', self._appcmd_registry.get_commands())
		self.assertIn(
			'command_raising_error', self._panecmd_registry.get_commands()
		)

		from simple_plugin import ListenerRaisingError
		self.assertIn(
			ListenerRaisingError, self._plugin._directory_pane_listeners
		)
		self.assertEqual(bindings, self._key_bindings.get_sanitized_bindings())

		from simple_plugin import TestFileSystem
		fs_wrapper = self._mother_fs._children[TestFileSystem.scheme]
		fs_instance = fs_wrapper.unwrap()
		self.assertIsInstance(fs_instance, TestFileSystem)

		from simple_plugin import TestColumn
		loaded_columns = self._mother_fs._columns
		self.assertEqual(1, len(loaded_columns))
		col_name, col_instance = next(iter(loaded_columns.items()))
		self.assertEqual('simple_plugin.TestColumn', col_name)
		self.assertIsInstance(col_instance.unwrap(), TestColumn)
	def test_unload(self):
		self.test_load()
		self._plugin.unload()
		self.assertEqual({}, self._mother_fs._columns)
		self.assertEqual({}, self._mother_fs._children)
		self.assertEqual([], self._key_bindings.get_sanitized_bindings())
		self.assertEqual([], self._plugin._directory_pane_listeners)
		self.assertEqual(set(), self._panecmd_registry.get_commands())
		self.assertEqual(set(), self._appcmd_registry.get_commands())
		self.assertNotIn(self._plugin_dir, sys.path)
		self.assertEqual([], self._theme.loaded_css_files)
		self.assertEqual([], self._font_database.loaded_fonts)
		self.assertIsNone(self._config.load_json('Key Bindings.yaml'))
	def setUp(self):
		super().setUp()
		self._sys_path_before = list(sys.path)
		self._plugin_dir = get_resource('Simple Plugin')
		self._config = Config()
		self._theme = StubTheme()
		self._font_database = StubFontDatabase()
		self._error_handler = StubErrorHandler()
		self._command_callback = StubCommandCallback()
		self._panecmd_registry = \
			PaneCommandRegistry(self._error_handler, self._command_callback)
		self._window = Window(None, self._panecmd_registry)
		self._appcmd_registry = ApplicationCommandRegistry(
			self._window, self._error_handler, self._command_callback
		)
		self._key_bindings = KeyBindings()
		cm_provider = ContextMenuProvider(
			self._panecmd_registry, self._appcmd_registry, self._key_bindings
		)
		self._mother_fs = MotherFileSystem(None)
		window = Window(None, self._panecmd_registry)
		self._plugin = ExternalPlugin(
			self._plugin_dir, self._config, self._theme, self._font_database,
			cm_provider, self._error_handler, self._appcmd_registry,
			self._panecmd_registry, self._key_bindings, self._mother_fs, window
		)
	def tearDown(self):
		sys.path = self._sys_path_before
		super().tearDown()


class BatchFileRenamerPluginIT(qt_tests.QuickBoardFixture):
	def test_installed_public_only_command_renames_only_visible_files(self):
		self._exercise_renamer(bundled=False)

	def test_spec_bundled_command_renames_only_visible_files(self):
		self._exercise_renamer(bundled=True)

	def test_random_preview_matches_bundled_command_execution(self):
		self._exercise_renamer(bundled=True, random_fields=True)

	def _exercise_renamer(self, bundled, random_fields=False):
		from pathlib import Path
		from tempfile import TemporaryDirectory
		from shutil import copy2, copytree
		from unittest.mock import Mock, patch
		from fman_unittest.batch_file_renamer_fixture import PLUGIN_ROOT
		from fman.impl.ui.table_filters import compile_filter
		from fman.url import as_url
		from core import LocalFileSystem
		fixture = ExternalPluginTest()
		fixture.setUp()
		self.addCleanup(fixture.tearDown)
		with TemporaryDirectory() as directory:
			root = Path(directory).resolve()
			if bundled:
				import build
				from runpy import run_path
				from PyInstaller.building.utils import format_binaries_and_datas
				from fman.impl.plugins.discover import find_plugin_dirs
				with patch('PyInstaller.utils.hooks.collect_all', return_value=([], [], [])):
					specification = run_path(str(build.ROOT / 'application.spec'), init_globals={
						'SPECPATH': str(build.ROOT), 'Analysis': Mock(), 'PYZ': Mock(), 'EXE': Mock(), 'COLLECT': Mock()})
				self.assertIn('string', specification['hidden_imports'])
				self.assertIn('random', specification['hidden_imports'])
				data = [entry for entry in specification['datas'] if entry[1] == 'resources/Plugins/BatchFileRenamer']
				self.assertTrue(data, 'Batch File Renamer must be included in the frozen resources')
				for destination, source in format_binaries_and_datas(data, workingdir=str(build.ROOT)):
					target = root / '_internal' / destination
					target.parent.mkdir(parents=True, exist_ok=True)
					copy2(source, target)
				installed = root / '_internal/resources/Plugins/BatchFileRenamer'
				self.assertTrue((installed / 'batch_file_renamer/engine.py').is_file())
				discovered = find_plugin_dirs(str(root / '_internal/resources/Plugins'),
					str(root / 'Third-party'), str(root / 'User'))
				self.assertIn(str(installed), discovered)
				self.assertFalse((root / 'Third-party').exists())
			else:
				installed = root / 'Third-party/BatchFileRenamer'
				copytree(PLUGIN_ROOT, installed)
			files = root / 'files'
			files.mkdir()
			for name in ('IMG_2.txt', 'IMG_10.txt', 'occupied.txt'):
				(files / name).write_text(name, encoding='utf-8')
			fixture._plugin._path = str(installed)
			self.assertTrue(fixture._plugin.load(), fixture._error_handler.error_messages)
			try:
				self.assertIn('batch_file_renamer', fixture._panecmd_registry.get_commands())
				from batch_file_renamer import BatchFileRenamer
				pane = Mock()
				pane.get_path.return_value = as_url(files)
				pane.get_selected_files.return_value = [as_url(files / 'IMG_2.txt'), as_url(files / 'IMG_10.txt')]
				callbacks = []
				def subscribe(callback):
					callbacks.append(callback)
					return lambda: callbacks.remove(callback) if callback in callbacks else None
				pane.on_path_changed.side_effect = subscribe
				pane.on_closed.return_value = lambda: None
				pane.reload.side_effect = lambda on_done=None: on_done() if on_done is not None else None
				mother = MotherFileSystem(None)
				mother.add_child('file://', LocalFileSystem())
				with patch('fman.fs._get_mother_fs', return_value=mother), patch('fman.APP_VERSION', '0.14.0'), \
						patch('fman.submit_task', side_effect=lambda task: task()):
					finished, result = self.start_call(BatchFileRenamer(pane))
					board = self.window_for()
					self.settled(board)
					self.assertIn('{c} random letter', self.run_in_app(lambda: board.summary.content))
					self.assertIn('{d} random digit', self.run_in_app(lambda: board.summary.content))
					self.assertEqual((900, 600), self.run_in_app(lambda: (board.width(), board.height())))
					widths = self.run_in_app(lambda: tuple(board.table.view.columnWidth(index) for index in range(6)))
					for index in (0, 1, 5):
						self.assertLess(widths[index], min(widths[2], widths[4]))
					template = 'renamed_{index}_{c}{c}{d}{d}{ext}' if random_fields else 'renamed_{index}{ext}'
					self.run_in_app(board.input.setText, template)
					self.settled(board)
					if random_fields:
						initial = self.run_in_app(lambda: tuple(row.cells[4] for row in board.table.rows))
						self.run_in_app(board.input.setText, 'edited_' + template)
						self.settled(board)
						self.assertEqual(tuple('edited_' + name for name in initial),
							self.run_in_app(lambda: tuple(row.cells[4] for row in board.table.rows)))
					self.run_in_app(board.table.set_column_filter, 2, compile_filter(board.schema.columns[2], 2, 'substring', 'IMG_10'))
					self.settled(board)
					self.assertEqual((None, 0), board.mapping)
					expected_name = self.run_in_app(lambda: board.table.rows[1].cells[4])
					if random_fields:
						self.assertRegex(expected_name, r'^edited_renamed_0_[a-zA-Z]{2}[0-9]{2}\.txt$')
						self.assertEqual(initial[1].removeprefix('renamed_1_'),
							expected_name.removeprefix('edited_renamed_0_'))
					else:
						self.assertEqual('renamed_0.txt', expected_name)
					self.run_in_app(board.request_accept)
					report = self.wait_table()
					self.assertTrue((files / 'IMG_2.txt').exists())
					self.assertFalse((files / 'IMG_10.txt').exists())
					self.assertEqual('IMG_10.txt', (files / expected_name).read_text())
					self.assertIn('1 renamed; 1 excluded', self.run_in_app(lambda: report.summary.content))
					self.run_in_app(report.close)
					self.assertTrue(finished.wait(5))
					pane.select.assert_called_once_with((as_url(files / expected_name),))
					self.assertFalse(callbacks)
			finally:
				fixture._plugin.unload()


class QuickBoardPluginIT(qt_tests.QuickBoardFixture):
	def test_public_only_consumers_and_host_lifetime_after_unload(self):
		from pathlib import Path
		from tempfile import TemporaryDirectory
		from textwrap import dedent
		from threading import Event
		fixture = ExternalPluginTest()
		fixture.setUp()
		self.addCleanup(fixture.tearDown)
		with TemporaryDirectory() as directory:
			package = Path(directory, 'quick_board_consumer')
			package.mkdir()
			package.joinpath('__init__.py').write_text(dedent('''
				from fman.ui import QuickTableColumn, QuickTableRow, show_quick_board
				CASES = (
				    ('Batch rename', '{name}_{index:03d}.{ext}'),
				    ('Destination', '{modified:%Y-%m}/{ext}/{name}.{ext}'),
				    ('Export', '{name} | {size} | {modified:%Y-%m-%d}'),
				    ('Query', 'ext:pdf size:>10mb'),
				    ('Exclusion', '*.tmp;*.bak;cache*'),
				    ('Arguments', '--output "{name}.txt" "{path}"'),
				)
				class Board:
				    @classmethod
				    def compose(cls, label, text, entered=None, release=None):
				        def rows(value, mapping):
				            if entered is not None:
				                entered.set()
				                release.wait(5)
				            return (QuickTableRow((label, value)),), None
				        return show_quick_board(
				            columns=(QuickTableColumn('Context'), QuickTableColumn('Preview', sortable=False, filterable=False)),
				            get_rows=rows, text=text, title=label, summary='Captured sample')
			'''.expandtabs(4)), encoding='utf-8')
			plugin = fixture._plugin
			plugin._path = directory
			self.assertTrue(plugin.load(), fixture._error_handler.error_messages)
			try:
				from quick_board_consumer import Board, CASES
				for label, text in CASES:
					with self.subTest(label=label):
						finished, result = self.start_call(Board.compose, label, text)
						window = self.window_for()
						self.settled(window)
						self.assertEqual((label, text), self.run_in_app(lambda: window.table.model.rows[0].cells))
						edited = text + ' updated'
						self.run_in_app(window.input.setText, edited)
						self.settled(window)
						self.assertIsNone(window.preview_error)
						self.assertEqual((label, edited), self.run_in_app(lambda: window.table.model.rows[0].cells))
						self.run_in_app(window.request_accept)
						self.assertTrue(finished.wait(5))
						self.assertEqual([(edited, True, (0,))], result)
				entered, release = Event(), Event()
				self.releases.append(release)
				finished, result = self.start_call(Board.compose, 'Unload', 'draft', entered, release)
				window = self.window_for()
				self.assertTrue(entered.wait(5))
				plugin.unload()
				self.assertFalse(finished.is_set())
				self.assertTrue(self.run_in_app(window.isVisible))
				self.run_in_app(window.close)
				self.assertTrue(finished.wait(5))
				self.assertEqual([('draft', False, None)], result)
				self.assertNotIn('quick_board_consumer', sys.modules)
				release.set()
				from fman.impl.ui.quick_board import _slots
				self.wait_for(lambda: _slots._value == 2)
			finally:
				plugin.unload()