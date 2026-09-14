from pathlib import Path
from unittest import TestCase
from unittest.mock import patch

import fman


class PortableStorageTest(TestCase):
	def test_environment_override(self):
		override = str(Path('custom-settings').resolve())
		with patch.dict(
			'os.environ', {'ROYIFILEMANAGER_USER_SETTINGS': override}
		):
			self.assertEqual(override, fman._get_data_directory())

	def test_default_directory_is_portable(self):
		with patch.dict('os.environ', {}, clear=True):
			data_directory = Path(fman._get_data_directory())
		self.assertEqual('UserSettings', data_directory.name)
		self.assertNotIn('AppData', data_directory.parts)


class PluginApiCompatibilityTest(TestCase):
	def test_general_api_does_not_expose_qt_host_bridges(self):
		self.assertFalse(hasattr(fman.DirectoryPane, 'closed'))
		self.assertTrue(callable(getattr(fman.DirectoryPane, 'on_closed', None)))
		for name in ('tool_parent', 'set_panel', 'set_bottom_panel',
				'remove_bottom_panel', 'get_quicklist_item_css'):
			self.assertFalse(hasattr(fman.Window, name), name)

	def test_public_ui_exports(self):
		import fman.ui
		expected = {
			'ListItem', 'QuickList', 'Panel', 'IconButton', 'TextButton',
			'DropDown', 'JsonSettings', 'UiController', 'UiOwner', 'Resource',
			'settings_resource', 'matchers', 'ToolWindow', 'PaneToolWindow',
			'NavigationHandle', 'navigate', 'OutputTextBox', 'TableRow', 'TableAction',
			'TextField', 'Toggle', 'Choice', 'Label', 'Action', 'TableHandle', 'PanelHandle',
			'show_table', 'show_panel'
		}
		self.assertEqual(expected, set(fman.ui.__all__))
		self.assertFalse(hasattr(fman.ui, 'BottomPanel'))
		self.assertFalse(hasattr(fman.ui.PaneToolWindow, 'set_bottom_panel'))
		for name in expected:
			self.assertTrue(hasattr(fman.ui, name), name)

	def test_favorites_uses_only_exported_host_api(self):
		root = Path(fman.__file__).parents[2] / 'resources/base/Plugins/Favorites'
		files = list(root.rglob('*.py'))
		self.assertTrue(files)
		for source_file in files:
			text = source_file.read_text(encoding='utf-8')
			for forbidden in ('fman.impl', 'from core', 'import core', '._widget', '._theme'):
				self.assertNotIn(forbidden, text, str(source_file))

	def test_public_plugin_api_is_preserved(self):
		expected = {
			'ApplicationCommand', 'DirectoryPaneCommand',
			'DirectoryPaneListener', 'Task', 'load_json', 'save_json',
			'show_alert', 'show_prompt', 'show_quicksearch'
		}
		self.assertTrue(expected.issubset(set(fman.__all__)))


class RegistryPolicyTest(TestCase):
	def test_source_does_not_call_registry_apis(self):
		source_root = Path(fman.__file__).parent
		forbidden = (
			'import win' + 'reg', 'from win' + 'reg', 'Q' + 'Settings',
			'Reg' + 'CreateKey', 'Reg' + 'SetValue', 'Reg' + 'DeleteKey',
			'HKEY' + '_'
		)
		for source_file in source_root.rglob('*.py'):
			text = source_file.read_text(encoding='utf-8')
			for token in forbidden:
				self.assertNotIn(token, text, str(source_file))