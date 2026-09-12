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