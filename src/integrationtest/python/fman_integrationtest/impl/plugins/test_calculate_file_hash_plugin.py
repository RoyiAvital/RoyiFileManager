from fman import PLATFORM, Window
from fman.impl.plugins.command_registry import ApplicationCommandRegistry, PaneCommandRegistry
from fman.impl.plugins.config import Config
from fman.impl.plugins.context_menu import ContextMenuProvider
from fman.impl.plugins.key_bindings import KeyBindings
from fman.impl.plugins.mother_fs import MotherFileSystem
from fman.impl.plugins.plugin import ExternalPlugin
from fman_integrationtest.impl.plugins import StubCommandCallback, StubFontDatabase, StubTheme
from fman_unittest.impl.plugins import StubErrorHandler
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase

import sys


class CalculateFileHashPluginTest(TestCase):
	def test_load_defaults_binding_and_unload(self):
		modules = {name: module for name, module in sys.modules.items()
			if name == 'calculate_file_hash' or name.startswith('calculate_file_hash.')}
		def restore():
			for name in tuple(sys.modules):
				if name == 'calculate_file_hash' or name.startswith('calculate_file_hash.'):
					del sys.modules[name]
			sys.modules.update(modules)
		self.addCleanup(restore)
		for name in modules:
			del sys.modules[name]
		path = Path(__file__).resolve().parents[5] / 'main' / 'resources' / 'base' / 'Plugins' / 'CalculateFileHash'
		config = Config(PLATFORM)
		errors = StubErrorHandler()
		callback = StubCommandCallback()
		pane_registry = PaneCommandRegistry(errors, callback)
		window = Window(None, pane_registry)
		application_registry = ApplicationCommandRegistry(window, errors, callback)
		bindings = KeyBindings()
		context = ContextMenuProvider(pane_registry, application_registry, bindings)
		plugin = ExternalPlugin(str(path), config, StubTheme(), StubFontDatabase(), context,
			errors, application_registry, pane_registry, bindings, MotherFileSystem(None), window)
		self.assertTrue(plugin.load())
		try:
			self.assertEqual({'calculate_file_hash', 'calculate_file_hash_by'}, set(pane_registry.get_commands()))
			self.assertIn({'keys': ['Ctrl+H'], 'command': 'calculate_file_hash'}, bindings.get_sanitized_bindings())
			self.assertEqual([], errors.error_messages)
			from calculate_file_hash.ui import HashController
			self.assertTrue(HashController.owner.active)
			with TemporaryDirectory() as settings_path:
				config.add_dir(settings_path)
				Path(settings_path, 'CalculateFileHash.json').write_text('{}', encoding='utf-8')
				self.assertEqual('sha256', config.load_json('CalculateFileHash.json')['default_algorithm'])
		finally:
			plugin.unload()
		self.assertFalse(HashController.owner.active)
		self.assertEqual([], list(pane_registry.get_commands()))
		from fman.ui import OutputTextBox
		self.assertTrue(callable(OutputTextBox))