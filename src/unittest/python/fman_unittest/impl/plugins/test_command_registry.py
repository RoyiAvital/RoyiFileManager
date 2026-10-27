from fman import ApplicationCommand, DirectoryPane, DirectoryPaneCommand
from fman.impl.plugins.command_registry import ApplicationCommandRegistry, \
	PaneCommandRegistry
from unittest import TestCase
from unittest.mock import Mock, patch

class FileCommand(DirectoryPaneCommand):
	category = ' File '

class InheritedFileCommand(FileCommand):
	pass

class PlainCommand(DirectoryPaneCommand):
	pass

class BadCategoryCommand(DirectoryPaneCommand):
	category = ('File',)

class SettingsCommand(ApplicationCommand):
	category = 'Settings'

class PlainApplicationCommand(ApplicationCommand):
	pass

class CommandCategoryTest(TestCase):
	def test_pane_registry(self):
		registry = PaneCommandRegistry(Mock(), Mock())
		for name, cls in (('file', FileCommand), ('inherited', InheritedFileCommand),
				('plain', PlainCommand), ('bad', BadCategoryCommand)):
			registry.register_command(name, cls)
		self.assertEqual('File', registry.get_command_category('file'))
		self.assertEqual('File', registry.get_command_category('inherited'))
		self.assertEqual('', registry.get_command_category('plain'))
		self.assertEqual('', registry.get_command_category('bad'))
		pane = DirectoryPane(Mock(), None, registry)
		self.assertEqual('File', pane.get_command_category('file'))
	def test_application_registry(self):
		registry = ApplicationCommandRegistry(Mock(), Mock(), Mock())
		registry.register_command('settings', SettingsCommand)
		registry.register_command('plain', PlainApplicationCommand)
		self.assertEqual('Settings', registry.get_command_category('settings'))
		self.assertEqual('', registry.get_command_category('plain'))
	def test_public_application_accessor(self):
		import fman
		support = Mock()
		support.get_application_command_category.return_value = 'Settings'
		with patch('fman._get_plugin_support', return_value=support):
			self.assertEqual('Settings', fman.get_application_command_category('settings'))
		support.get_application_command_category.assert_called_once_with('settings')
