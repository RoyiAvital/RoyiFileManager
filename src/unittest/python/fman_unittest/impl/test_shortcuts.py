from json import dump
from os import makedirs
from os.path import join
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase

from fman.impl.shortcuts import collect_shortcuts


class CollectShortcutsTest(TestCase):
	def test_bundled_text_commands_are_available_in_shortcut_list(self):
		from json import load
		path = Path(__file__).resolve().parents[4] / 'main/resources/base/Plugins/Core/Key Bindings.json'
		commands = {'view_file', 'open_with_editor', 'create_and_edit_file'}
		self.assertEqual([
			('Core', 'view_file', 'F3'),
			('Core', 'open_with_editor', 'F4'),
			('Core', 'create_and_edit_file', 'Shift+F4')
		], collect_shortcuts([str(path)], commands))
		with path.open() as file:
			bindings = load(file)
		for shortcut in ('F3', 'F4', 'Shift+F4'):
			self.assertEqual(1, sum(shortcut in binding['keys'] for binding in bindings))

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


class ShortcutSuggestionsTest(TestCase):
	def test_arrow_suggestions_offer_and_dispatch_home_and_end(self):
		from fman.impl.nonexistent_shortcut_handler import NonexistentShortcutHandler
		from unittest.mock import Mock
		for shortcut, choice, command in (
			('Left', 'Move home', 'move_cursor_home'),
			('Right', 'Move end', 'move_cursor_end')
		):
			with self.subTest(shortcut=shortcut):
				pane = Mock()
				pane.get_path.return_value = 'file:///c:/folder'
				pane.get_file_under_cursor.return_value = 'file:///c:/folder/child'
				pane.window.get_panes.return_value = [pane]
				handler = NonexistentShortcutHandler(Mock(), {}, Mock())
				handler._get_previous_folder_in_history = Mock(return_value=None)
				handler._get_next_folder_in_history = Mock(return_value=None)
				handler._is_existing_dir = Mock(return_value=True)
				handler._show_suggestions = Mock(return_value=choice)
				handler._offer_to_customize_keybindings = Mock()
				event = Mock()
				event.is_modifier_only.return_value = False
				event.matches.side_effect = lambda pattern: pattern == shortcut
				self.assertTrue(handler(event, pane))
				options = handler._show_suggestions.call_args.args[2]
				self.assertIn(choice, [name for name, description in options])
				self.assertEqual((shortcut, command),
					handler._offer_to_customize_keybindings.call_args.args[1:])