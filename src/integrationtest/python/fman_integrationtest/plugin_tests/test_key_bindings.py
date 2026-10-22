from fman_integrationtest.plugin_tests import PluginTest
from threading import Event
from unittest.mock import patch

class KeyBindingsTest(PluginTest):
	def test_key_bindings(self, timeout_secs=5):
		key_bindings = self._plugin_support.get_sanitized_key_bindings()
		self.assertEqual(2, len(key_bindings))
		first, second = key_bindings
		self.assertEqual({
			'keys': ['Enter'],
			'command': 'test_command',
			'args': {
				'success': True
			}
		}, first)
		# Can do this because sys.path has been extended by `Plugin#load()`:
		from simple_plugin import TestCommand
		self.assertFalse(TestCommand.RAN, 'Sanity check')
		completed = Event()
		with patch.object(self._command_callback, 'after_command',
			side_effect=lambda name: completed.set()):
			try:
				self._plugin_support.run_application_command(
					'test_command', {'ran': True}
				)
				self.assertTrue(completed.wait(timeout_secs), "TestCommand didn't finish.")
				self.assertTrue(TestCommand.RAN)
			finally:
				TestCommand.RAN = False
			self.assertEqual({
				'keys': ['Space'],
				'command': 'command_raising_error'
			}, second)
			completed.clear()
			with patch.object(self._left_pane._widget, 'cancel_pattern_selection') as cancel_preview:
				self._left_pane.run_command('command_raising_error')
				self.assertTrue(completed.wait(timeout_secs), 'Pane command did not finish.')
				cancel_preview.assert_called_once_with()
			self.assertEqual(
				["Command 'CommandRaisingError' raised error."],
				self._error_handler.error_messages
			)