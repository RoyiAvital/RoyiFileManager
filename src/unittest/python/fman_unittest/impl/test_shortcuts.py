from json import dump
from os import makedirs
from os.path import join
from tempfile import TemporaryDirectory
from unittest import TestCase

from fman.impl.shortcuts import collect_shortcuts


class CollectShortcutsTest(TestCase):
	def test_separates_sources_and_applies_override_order(self):
		with TemporaryDirectory() as root:
			core = self._write(root, 'Core', [
				{'keys': ['F1'], 'command': 'help'},
				{'keys': ['Ctrl+K'], 'command': 'core_command'}
			])
			plugin = self._write(root, 'Git Integration', [
				{'keys': ['Ctrl+K'], 'command': 'plugin_command'},
				{'keys': ['Ctrl+G'], 'command': 'git_status'}
			])

			result = collect_shortcuts(
				[core, plugin],
				{'help', 'core_command', 'plugin_command', 'git_status'}
			)

		self.assertEqual([
			('Git Integration', 'plugin_command', 'Ctrl+K'),
			('Git Integration', 'git_status', 'Ctrl+G'),
			('Core', 'help', 'F1')
		], result)

	def test_ignores_missing_and_malformed_files(self):
		with TemporaryDirectory() as root:
			valid = self._write(root, 'Core', [
				{'keys': [], 'command': 'missing_key'},
				{'keys': ['F1']},
				{'keys': ['F2'], 'command': 'valid'}
			])
			result = collect_shortcuts([join(root, 'missing.json'), valid])

		self.assertEqual([('Core', 'valid', 'F2')], result)

	def test_ignores_commands_that_are_not_registered(self):
		with TemporaryDirectory() as root:
			bindings = self._write(root, 'Old Plugin', [
				{'keys': ['Ctrl+O'], 'command': 'removed_command'},
				{'keys': ['Ctrl+A'], 'command': 'active_command'}
			])

			result = collect_shortcuts([bindings], {'active_command'})

		self.assertEqual([
			('Old Plugin', 'active_command', 'Ctrl+A')
		], result)

	@staticmethod
	def _write(root, plugin_name, bindings):
		plugin_dir = join(root, plugin_name)
		makedirs(plugin_dir)
		path = join(plugin_dir, 'Key Bindings.json')
		with open(path, 'w') as file:
			dump(bindings, file)
		return path