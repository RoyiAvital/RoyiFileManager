from fman import PLATFORM, ApplicationCommand, DirectoryPaneCommand, \
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

import json
import sys

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

class ExternalPluginTest(TestCase):
	def test_load(self):
		if not self._plugin.load():
			self.fail(self._error_handler.error_messages)
		with open(join(self._plugin_dir, 'Key Bindings.json'), 'r') as f:
			bindings = json.load(f)
		self.assertEqual(bindings, self._config.load_json('Key Bindings.json'))
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
		self.assertIsNone(self._config.load_json('Key Bindings.json'))
	def setUp(self):
		super().setUp()
		self._sys_path_before = list(sys.path)
		self._plugin_dir = get_resource('Simple Plugin')
		self._config = Config(PLATFORM)
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
				        def rows(value):
				            if entered is not None:
				                entered.set()
				                release.wait(5)
				            return (QuickTableRow((label, value)),)
				        return show_quick_board(
				            columns=(QuickTableColumn('Context'), QuickTableColumn('Preview')),
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
						self.run_in_app(window.request_accept)
						self.assertTrue(finished.wait(5))
						self.assertEqual([(text, True)], result)
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
				self.assertEqual([('draft', False)], result)
				self.assertNotIn('quick_board_consumer', sys.modules)
				release.set()
				from fman.impl.ui.quick_board import _slots
				self.wait_for(lambda: _slots._value == 2)
			finally:
				plugin.unload()