from fman.impl.plugins import SETTINGS_PLUGIN_NAME
from fman.impl.plugins.discover import find_plugin_dirs
from os import mkdir
from os.path import join, basename
from shutil import rmtree
from tempfile import mkdtemp
from unittest import TestCase

class FindPluginDirsTest(TestCase):
	def test_manual_thirdparty_discovery_reload_list_and_remove(self):
		from core import commands
		from fman.url import as_human_readable, as_url
		from pathlib import Path
		from tempfile import TemporaryDirectory
		from unittest.mock import Mock, call, patch
		with TemporaryDirectory() as root:
			shipped = Path(root, 'Shipped')
			thirdparty = Path(root, 'Plugins', 'Third-party')
			user = Path(root, 'Plugins', 'User')
			manual = thirdparty / 'ManualProbe'
			settings = user / 'Settings'
			wrong_location = Path(root, 'Plugins', 'NotDiscovered')
			for directory in (shipped, manual, settings, wrong_location):
				directory.mkdir(parents=True)
			self.assertEqual([str(manual), str(settings)], find_plugin_dirs(str(shipped), str(thirdparty), str(user)))
			pane = Mock()
			pane.get_path.return_value = 'file://C:/fixture'
			window = Mock()
			window.get_panes.return_value = [pane]
			with patch.object(commands, 'DATA_DIRECTORY', root), \
				patch.object(commands, '_THIRDPARTY_PLUGINS_DIR', str(thirdparty)), \
				patch.object(commands, 'load_plugin') as load, \
				patch.object(commands, 'unload_plugin') as unload, \
				patch.object(commands, 'show_status_message'), \
				patch.object(commands, 'show_alert'), \
				patch.object(commands, 'show_quicksearch', return_value=('', str(manual))), \
				patch.object(commands, 'delete', side_effect=lambda url: rmtree(as_human_readable(url))):
				commands.ReloadPlugins(window)()
				self.assertEqual([call(str(manual)), call(str(settings))], load.call_args_list)
				self.assertEqual([call(str(settings)), call(str(manual))], unload.call_args_list)
				pane.set_path.assert_called_once_with('file://C:/fixture')
				listing = commands.ListPlugins(pane)
				with patch('builtins.open', side_effect=AssertionError('Listing must not read metadata')):
					items = listing._get_matching_plugins('')
				self.assertEqual(['ManualProbe', 'Settings'], [item.title for item in items])
				self.assertTrue(all(not item.hint for item in items))
				listing()
				pane.set_path.assert_called_with(as_url(str(manual)), onerror=None)
				self.assertFalse((manual / 'Plugin.json').exists())
				commands.RemovePlugin(window)()
				unload.assert_called_with(str(manual))
				self.assertFalse(manual.exists())
				self.assertTrue(settings.is_dir())
				self.assertTrue(wrong_location.is_dir())

	def test_find_plugins(self):
		plugin_dirs = \
			[self.shipped_plugin, self.thirdparty_plugin, self.settings_plugin]
		for plugin_dir in plugin_dirs:
			mkdir(plugin_dir)
		self.assertEqual(
			plugin_dirs,
			find_plugin_dirs(
				self.shipped_plugins, self.thirdparty_plugins, self.user_plugins
			)
		)
	def test_find_plugins_no_settings_plugin(self):
		mkdir(self.shipped_plugin)
		mkdir(self.thirdparty_plugin)
		self.assertEqual(
			[self.shipped_plugin, self.thirdparty_plugin, self.settings_plugin],
			find_plugin_dirs(
				self.shipped_plugins, self.thirdparty_plugins, self.user_plugins
			)
		)
	def setUp(self):
		self.shipped_plugins = mkdtemp()
		self.thirdparty_plugins = mkdtemp()
		self.user_plugins = mkdtemp()
		self.shipped_plugin = join(self.shipped_plugins, 'Shipped')
		thirdparty_plugin = 'Very Simple Plugin'
		assert basename(thirdparty_plugin)[0] > SETTINGS_PLUGIN_NAME[0], \
			"Please ensure that the name of the third-party plugin appears in" \
			"listdir(...) _after_ the Settings plugin. This lets us test that" \
			"find_plugins(...) does not simply return plugins in the same " \
			"order as listdir(...) but ensures that the Settings plugin " \
			"appears last."
		self.thirdparty_plugin = \
			join(self.thirdparty_plugins, thirdparty_plugin)
		self.settings_plugin = join(self.user_plugins, SETTINGS_PLUGIN_NAME)
	def tearDown(self):
		rmtree(self.shipped_plugins)
		rmtree(self.thirdparty_plugins)
		rmtree(self.user_plugins)