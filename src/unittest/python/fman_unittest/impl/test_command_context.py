from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from unittest import TestCase
from unittest.mock import Mock

from fman import DirectoryPane
from fman.impl.plugins.command_registry import PaneCommandRegistry


class CommandContextTest(TestCase):
	def test_nested_exception_restores_context(self):
		pane = DirectoryPane(None, Mock(), None)
		pane._widget.get_file_under_cursor.return_value = 'original'
		registry = PaneCommandRegistry(Mock(), Mock())
		with registry._set_context(pane, 'outer'):
			with self.assertRaises(ValueError):
				with registry._set_context(pane, None):
					self.assertIsNone(pane.get_file_under_cursor())
					raise ValueError()
			self.assertEqual('outer', pane.get_file_under_cursor())
		self.assertEqual('original', pane.get_file_under_cursor())
	def test_concurrent_commands_do_not_share_overrides(self):
		pane = DirectoryPane(None, Mock(), None)
		pane._widget.get_file_under_cursor.return_value = 'original'
		barrier = Barrier(2, timeout=5)
		def invoke(value):
			with pane._override_file_under_cursor(value):
				barrier.wait()
				result = pane.get_file_under_cursor()
				barrier.wait()
			return result
		with ThreadPoolExecutor(max_workers=2) as workers:
			self.assertEqual(['first', 'second'], list(workers.map(invoke, ['first', 'second'])))
		self.assertEqual('original', pane.get_file_under_cursor())