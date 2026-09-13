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
	def setUp(self):
		import sys
		from fman.ui import UiOwner
		from unittest.mock import patch
		modules = {name: module for name, module in sys.modules.items()
			if name == 'favorites' or name.startswith('favorites.')}
		def restore_modules():
			for name in tuple(sys.modules):
				if name == 'favorites' or name.startswith('favorites.'):
					del sys.modules[name]
			sys.modules.update(modules)
		self.addCleanup(restore_modules)
		if 'favorites' in modules:
			owner = patch.object(modules['favorites'].FavoritesController, 'owner', UiOwner())
			owner.start()
			self.addCleanup(owner.stop)

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
			import sys
			old_module = sys.modules['favorites']
			old_controller = old_module.FavoritesController
			old_lock = old_module._LOCK
			from unittest.mock import Mock, patch
			pane = Mock()
			pane.get_path.return_value = 'file:///C:/Current'
			self.assertEqual({
				'add_current_folder_to_favorites', 'show_favorites'
			}, {name for name in pane_registry.get_commands() if pane_registry.is_command_visible(name, pane)})
			from fman.impl.ui import UiController, UiOwner
			class TestController(UiController):
				pass
			TestController.owner = UiOwner()
			owner = TestController.owner
			plugin._ui_owners.append(owner)

			config.add_dir(settings_path)
			settings = config.load_json('Favorites.json')
			settings['favorites'].append({
				'name': 'Projects', 'url': 'file:///D:/Projects'
			})
			config.save_json('Favorites.json', settings)

			destination = Path(settings_path) / 'Favorites (Windows).json'
			self.assertTrue(destination.is_file())
			plugin.unload()
			self.assertFalse(owner.active)
			self.assertNotIn('favorites.store', sys.modules)
			self.assertFalse(old_controller.owner.active)
			self.assertTrue(plugin.load())
			new_module = sys.modules['favorites']
			self.assertIs(old_lock, new_module._LOCK)
			self.assertIsNot(old_controller, new_module.FavoritesController)
			self.assertTrue(new_module.FavoritesController.owner.active)
			with patch.object(old_module, 'save_json') as old_save:
				old_module.AddCurrentFolderToFavorites(pane)()
				old_save.assert_not_called()
			plugin.unload()