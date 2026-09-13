from fman import PLATFORM, Window
from fman.impl.plugins.command_registry import ApplicationCommandRegistry, \
	PaneCommandRegistry
from fman.impl.plugins.config import Config
from fman.impl.plugins.context_menu import ContextMenuProvider
from fman.impl.plugins.key_bindings import KeyBindings
from fman.impl.plugins.mother_fs import MotherFileSystem
from fman.impl.plugins.plugin import ExternalPlugin
from fman_integrationtest.impl.plugins import StubCommandCallback, \
	StubFontDatabase, StubTheme
from fman_unittest.impl.plugins import StubErrorHandler
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase


class FavoritesPluginTest(TestCase):
	def test_loads_commands_binding_and_saves_to_user_settings(self):
		plugin_path = Path(__file__).resolve().parents[5] / 'main' / \
			'resources' / 'base' / 'Plugins' / 'Favorites'
		with TemporaryDirectory() as settings_path:
			config = Config(PLATFORM)
			error_handler = StubErrorHandler()
			callback = StubCommandCallback()
			pane_registry = PaneCommandRegistry(error_handler, callback)
			window = Window(None, pane_registry)
			application_registry = ApplicationCommandRegistry(
				window, error_handler, callback
			)
			key_bindings = KeyBindings()
			mother_fs = MotherFileSystem(None)
			context_menu = ContextMenuProvider(
				pane_registry, application_registry, key_bindings
			)
			plugin = ExternalPlugin(
				str(plugin_path), config, StubTheme(), StubFontDatabase(),
				context_menu, error_handler, application_registry, pane_registry,
				key_bindings, mother_fs, window
			)

			self.assertTrue(plugin.load())
			self.assertTrue({
				'add_current_folder_to_favorites', 'show_favorites',
				'remove_from_favorites', 'rename_favorite'
			}.issubset(pane_registry.get_commands()))
			self.assertIn({
				'keys': ['Ctrl+B'], 'command': 'show_favorites'
			}, key_bindings.get_sanitized_bindings())
			self.assertEqual([], error_handler.error_messages)

			config.add_dir(settings_path)
			settings = config.load_json('Favorites.json')
			settings['favorites'].append({
				'name': 'Projects', 'url': 'file:///D:/Projects'
			})
			config.save_json('Favorites.json', settings)

			destination = Path(settings_path) / 'Favorites (Windows).json'
			self.assertTrue(destination.is_file())
			plugin.unload()