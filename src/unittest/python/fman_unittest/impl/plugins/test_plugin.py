from fman.fs import FileSystem
from fman.impl.plugins.plugin import _get_command_name, \
	get_command_class_name, FileSystemWrapper
from fman_unittest.impl.plugins import StubErrorHandler
from unittest import TestCase
from unittest.mock import Mock, patch
from types import ModuleType


class PluginServiceTest(TestCase):
	def make_plugin(self):
		from fman.impl.plugins.plugin import ExternalPlugin
		return ExternalPlugin('service-test', *[Mock() for index in range(10)])

	def test_service_starts_after_registration_and_disposes_before_unregister(self):
		from fman.impl.plugins.plugin import PluginService
		from fman.fs import Column
		events = []
		class Service(PluginService):
			def start(self):
				events.append('start')
			def on_pane_added(self, pane):
				events.append(pane)
			def dispose(self):
				self.assert_inactive = not self.owner.active
				events.append('dispose')
		class Size(Column):
			pass
		package = ModuleType('service_test')
		package.Service = Service
		package.Size = Size
		plugin = self.make_plugin()
		with patch.object(plugin, '_load_packages', return_value=[package]), \
			patch.object(plugin, '_register_column', side_effect=lambda cls: events.append('column')), \
			patch.object(plugin, '_unregister_column', side_effect=lambda cls: events.append('unregister')):
			plugin._load_classes()
			plugin._start_services()
			service = plugin._services[0]
			plugin.on_pane_added('pane')
			plugin.unload()
			plugin.unload()
		self.assertEqual(['column', 'start', 'pane', 'dispose', 'unregister'], events)
		self.assertTrue(service.assert_inactive)

	def test_failed_service_start_is_disposed(self):
		from fman.impl.plugins.plugin import PluginService
		disposed = Mock()
		class Broken(PluginService):
			def start(self):
				raise ValueError('start failed')
			def dispose(self):
				disposed()
		plugin = self.make_plugin()
		plugin._service_classes.append(Broken)
		with patch.object(plugin, '_load', side_effect=plugin._start_services):
			self.assertFalse(plugin.load())
		disposed.assert_called_once_with()
		self.assertEqual([], plugin._services)

class GetCommandNameTest(TestCase):
	def test_single_letter(self):
		self.assertEqual('c', _get_command_name('C'))
	def test_single_word(self):
		self.assertEqual('copy', _get_command_name('Copy'))
	def test_two_words(self):
		self.assertEqual(
			'open_terminal', _get_command_name('OpenTerminal')
		)
	def test_three_words(self):
		self.assertEqual(
			'move_cursor_up', _get_command_name('MoveCursorUp')
		)
	def test_two_consecutive_upper_case_chars(self):
		self.assertEqual('get_url', _get_command_name('GetURL'))

class GetCommandClassNameTest(TestCase):
	def test_is_inverse_of_get_command_name(self):
		for test_string in ('C', 'Copy', 'OpenTerminal', 'MoveCursorUp'):
			result = get_command_class_name(_get_command_name(test_string))
			self.assertEqual(test_string, result)

class FileSystemWrapperTest(TestCase):
	def test_tracked_plugin_defects_are_attributed_and_propagated(self):
		from fman.impl.navigation import NavigationRequest, tracking
		class Broken(FileSystem):
			scheme = 'broken://'
			def iterdir(self, path):
				yield 42
		wrapper = self._wrap(Broken)
		with tracking(NavigationRequest(lambda *args: None)):
			with self.assertRaises(TypeError):
				list(wrapper.iterdir(''))
		self._expect_error("FileSystem 'Broken' raised error.")
	def test_tracked_iteration_error_propagates_without_duplicate_alert(self):
		from fman.impl.navigation import NavigationRequest, tracking
		class Denied(FileSystem):
			scheme = 'denied://'
			def iterdir(self, path):
				yield 'first'
				raise PermissionError('denied')
		wrapper = self._wrap(Denied)
		with tracking(NavigationRequest(lambda *args: None)):
			with self.assertRaises(PermissionError):
				list(wrapper.iterdir(''))
		self.assertEqual([], self._error_handler.error_messages)
	def test_iterdir_not_implemented(self):

		class IterdirNotImplemented(FileSystem):
			scheme = 'noiterdir://'

		wrapper = self._wrap(IterdirNotImplemented)
		self.assertEqual([], list(wrapper.iterdir('')))
		self._expect_error(
			"Error: FileSystem 'IterdirNotImplemented' does not implement "
			"iterdir(...)."
		)
	def test_iterdir_none(self):
		self._test_iterdir_error(
			lambda _: None,
			"Error: FS.iterdir(...) returned None instead of an iterable such "
			"as ['a.txt', 'b.jpg']."
		)
	def test_iterdir_number(self):
		self._test_iterdir_error(
			lambda _: 2,
			"Error: FS.iterdir(...) returned 2 instead of an iterable such "
			"as ['a.txt', 'b.jpg']."
		)
	def test_iterdir_non_string(self):
		def iterdir(_):
			yield from range(5)
		self._test_iterdir_error(
			iterdir,
			"Error: FS.iterdir(...) yielded 0 instead of a string such as "
			"'file.txt'."
		)
	def test_iterdir_raising_error(self):
		def iterdir(_):
			raise ValueError()
		self._test_iterdir_error(iterdir, "FileSystem 'FS' raised error.")
	def test_get_default_columns_nonexistent(self):
		self._test_get_default_columns_error(
			lambda _: ('Name',),
			"Error: FS.get_default_columns(...) returned a column that does "
			"not exist: 'Name'. Should have been one of: 'core.Name', "
			"'core.Size', 'core.Modified'."
		)
	def _test_iterdir_error(self, iterdir, expected_error):
		class FS(FileSystem):
			scheme = 'scheme://'
			def iterdir(self, path):
				return iterdir(path)
		wrapper = self._wrap(FS)
		self.assertEqual([], list(wrapper.iterdir('')))
		self._expect_error(expected_error)
	def _test_get_default_columns_error(self, get_default_cols, expected_error):
		class FS(FileSystem):
			scheme = 'scheme://'
			def get_default_columns(self, path):
				return get_default_cols(path)
		wrapper = self._wrap(FS)
		self.assertEqual(('core.Name',), wrapper.get_default_columns(''))
		self._expect_error(expected_error)
	def _wrap(self, fs_class):
		fs = StubMotherFileSystem(['core.Name', 'core.Size', 'core.Modified'])
		return FileSystemWrapper(fs_class(), fs, self._error_handler)
	def _expect_error(self, error_message):
		self.assertEqual([error_message], self._error_handler.error_messages)
	def setUp(self):
		super().setUp()
		self._error_handler = StubErrorHandler()

class StubMotherFileSystem:
	def __init__(self, columns):
		self._columns = columns
	def get_registered_column_names(self):
		return self._columns