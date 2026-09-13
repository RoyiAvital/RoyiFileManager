from core.commands import CreateAndEditFile, History, Move, NewEmptyFile, \
	ResetWindowGeometry, \
	SyncPaneLocation, \
	_from_human_readable, \
	get_dest_suggestion, _find_extension_start, _get_shortcuts_for_command
from core.tests import StubUI
from core.util import filenotfounderror
from fman import OK, YES, NO, PLATFORM
from fman.impl.plugins.plugin import _get_command_name
from fman.url import join, as_human_readable, as_url, dirname
from unittest import TestCase
from unittest.mock import call, Mock, patch

import json
import os
import os.path

class NewEmptyFileTest(TestCase):
	def test_has_command_center_identifier_and_aliases(self):
		self.assertEqual('new_empty_file', _get_command_name(NewEmptyFile))
		self.assertEqual(
			('New empty file', 'Create empty file', 'Touch'),
			NewEmptyFile.aliases
		)
	@patch('core.commands.touch')
	@patch('core.commands.exists', return_value=False)
	@patch('core.commands.show_prompt', return_value=('report.txt', True))
	@patch('core.commands.OpenWithEditor.__call__')
	def test_creates_file_and_places_cursor_without_editor(
		self, open_mock, show_prompt_mock, exists_mock, touch_mock
	):
		pane = self._create_pane()

		NewEmptyFile(pane)()

		show_prompt_mock.assert_called_once_with(
			'Enter file name to create:', '', selection_end=None
		)
		exists_mock.assert_called_once_with('file:///folder/report.txt')
		touch_mock.assert_called_once_with('file:///folder/report.txt')
		pane.place_cursor_at.assert_called_once_with(
			'file:///folder/report.txt'
		)
		open_mock.assert_not_called()
	@patch('core.commands.exists', return_value=True)
	@patch('core.commands.is_dir', return_value=False)
	@patch('core.commands.show_prompt', return_value=('', False))
	def test_suggests_file_under_cursor_and_selects_stem(
		self, show_prompt_mock, is_dir_mock, exists_mock
	):
		pane = self._create_pane()
		pane.get_file_under_cursor.return_value = \
			'file:///folder/source.tar.gz'

		NewEmptyFile(pane)()

		show_prompt_mock.assert_called_once_with(
			'Enter file name to create:', 'source.tar.gz', selection_end=6
		)
	@patch('core.commands.is_dir', return_value=True)
	@patch('core.commands.show_prompt', return_value=('', False))
	def test_directory_under_cursor_is_not_suggested(
		self, show_prompt_mock, is_dir_mock
	):
		pane = self._create_pane()
		pane.get_file_under_cursor.return_value = 'file:///folder/subfolder'

		NewEmptyFile(pane)()

		show_prompt_mock.assert_called_once_with(
			'Enter file name to create:', '', selection_end=None
		)
	@patch('core.commands.touch')
	@patch('core.commands.exists', return_value=True)
	@patch('core.commands.show_prompt', return_value=('existing.txt', True))
	def test_existing_path_is_no_op(
		self, show_prompt_mock, exists_mock, touch_mock
	):
		pane = self._create_pane()

		NewEmptyFile(pane)()

		exists_mock.assert_called_once_with('file:///folder/existing.txt')
		touch_mock.assert_not_called()
		pane.place_cursor_at.assert_not_called()
	@patch('core.commands.exists')
	@patch('core.commands.show_prompt', return_value=('', False))
	def test_cancel_is_no_op(self, show_prompt_mock, exists_mock):
		pane = self._create_pane()

		NewEmptyFile(pane)()

		exists_mock.assert_not_called()
		pane.place_cursor_at.assert_not_called()
	@patch('core.commands.exists')
	@patch('core.commands.show_prompt', return_value=('', True))
	def test_empty_name_is_no_op(self, show_prompt_mock, exists_mock):
		pane = self._create_pane()

		NewEmptyFile(pane)()

		exists_mock.assert_not_called()
		pane.place_cursor_at.assert_not_called()
	@patch('core.commands.show_alert')
	@patch('core.commands.touch', side_effect=PermissionError)
	@patch('core.commands.exists', return_value=False)
	@patch('core.commands.show_prompt', return_value=('blocked.txt', True))
	def test_permission_error_is_reported(
		self, show_prompt_mock, exists_mock, touch_mock, show_alert_mock
	):
		pane = self._create_pane()

		NewEmptyFile(pane)()

		self.assertIn(
			'blocked.txt', show_alert_mock.call_args.args[0]
		)
		pane.place_cursor_at.assert_not_called()
	@patch('core.commands.show_alert')
	@patch('core.commands.touch', side_effect=NotImplementedError)
	@patch('core.commands.exists', return_value=False)
	@patch('core.commands.show_prompt', return_value=('unsupported.txt', True))
	def test_unsupported_filesystem_is_reported(
		self, show_prompt_mock, exists_mock, touch_mock, show_alert_mock
	):
		pane = self._create_pane()

		NewEmptyFile(pane)()

		show_alert_mock.assert_called_once_with(
			'Sorry, creating a file is not supported here.'
		)
		pane.place_cursor_at.assert_not_called()
	@patch('core.commands.show_alert')
	@patch(
		'core.commands.touch', side_effect=OSError(123, 'Invalid file name')
	)
	@patch('core.commands.exists', return_value=False)
	@patch('core.commands.show_prompt', return_value=('a?b', True))
	def test_other_os_error_is_reported(
		self, show_prompt_mock, exists_mock, touch_mock, show_alert_mock
	):
		pane = self._create_pane()

		NewEmptyFile(pane)()

		message = show_alert_mock.call_args.args[0]
		self.assertIn('a?b', message)
		self.assertIn('Invalid file name', message)
		pane.place_cursor_at.assert_not_called()
	@patch('core.commands.touch')
	@patch('core.commands.exists', return_value=False)
	@patch('core.commands.show_prompt', return_value=('hidden.txt', True))
	def test_hidden_file_cursor_failure_is_ignored(
		self, show_prompt_mock, exists_mock, touch_mock
	):
		pane = self._create_pane()
		pane.place_cursor_at.side_effect = ValueError

		NewEmptyFile(pane)()

		touch_mock.assert_called_once_with('file:///folder/hidden.txt')
	def test_ctrl_n_binding(self):
		bindings_path = os.path.abspath(os.path.join(
			os.path.dirname(__file__), '..', '..', '..', 'Key Bindings.json'
		))
		with open(bindings_path, encoding='utf-8') as bindings_file:
			bindings = json.load(bindings_file)
		self.assertIn(
			{'keys': ['Ctrl+N'], 'command': 'new_empty_file'}, bindings
		)
	@patch('core.commands._fs_implements')
	def test_visibility_requires_touch_support(self, fs_implements_mock):
		pane = self._create_pane()
		fs_implements_mock.side_effect = [True, False]
		command = NewEmptyFile(pane)

		self.assertTrue(command.is_visible())
		self.assertFalse(command.is_visible())
		self.assertEqual(
			[call('file://', 'touch'), call('file://', 'touch')],
			fs_implements_mock.call_args_list
		)

	@staticmethod
	def _create_pane():
		pane = Mock()
		pane.get_file_under_cursor.return_value = None
		pane.get_path.return_value = 'file:///folder'
		return pane

class CreateAndEditFileTest(TestCase):
	@patch('core.commands.OpenWithEditor.__call__')
	@patch('core.commands.show_alert')
	@patch('core.commands.touch', side_effect=OSError(2, 'Folder vanished'))
	@patch('core.commands.exists', return_value=False)
	@patch('core.commands.show_prompt', return_value=('new.txt', True))
	def test_os_error_is_reported_without_opening_editor(
		self, show_prompt_mock, exists_mock, touch_mock, show_alert_mock,
		open_mock
	):
		pane = Mock()
		pane.get_file_under_cursor.return_value = None
		pane.get_path.return_value = 'file:///folder'

		CreateAndEditFile(pane)()

		self.assertIn('Folder vanished', show_alert_mock.call_args.args[0])
		pane.place_cursor_at.assert_not_called()
		open_mock.assert_not_called()
	@patch('core.commands.OpenWithEditor.__call__')
	@patch('core.commands.touch')
	@patch('core.commands.exists', return_value=False)
	@patch('core.commands.show_prompt', return_value=('new.txt', True))
	def test_new_file_is_created_selected_and_opened(
		self, show_prompt_mock, exists_mock, touch_mock, open_mock
	):
		pane = Mock()
		pane.get_file_under_cursor.return_value = None
		pane.get_path.return_value = 'file:///folder'

		CreateAndEditFile(pane)()

		touch_mock.assert_called_once_with('file:///folder/new.txt')
		pane.place_cursor_at.assert_called_once_with('file:///folder/new.txt')
		open_mock.assert_called_once_with('file:///folder/new.txt')
	@patch('core.commands.OpenWithEditor.__call__')
	@patch('core.commands.touch')
	@patch('core.commands.exists', return_value=True)
	@patch('core.commands.show_prompt', return_value=('existing.txt', True))
	def test_existing_file_is_selected_and_opened_without_touch(
		self, show_prompt_mock, exists_mock, touch_mock, open_mock
	):
		pane = Mock()
		pane.get_file_under_cursor.return_value = None
		pane.get_path.return_value = 'file:///folder'

		CreateAndEditFile(pane)()

		touch_mock.assert_not_called()
		pane.place_cursor_at.assert_called_once_with(
			'file:///folder/existing.txt'
		)
		open_mock.assert_called_once_with('file:///folder/existing.txt')

class ResetWindowGeometryTest(TestCase):
	def test_resets_active_session_window(self):
		window = object()
		session_manager = Mock()
		application_context = Mock(session_manager=session_manager)

		with patch(
			'fman.impl.application_context.get_application_context',
			return_value=application_context
		):
			ResetWindowGeometry(window)()

		session_manager.reset_window_geometry.assert_called_once_with(window)

class SyncPaneLocationTest(TestCase):
	def test_has_command_center_identifier_and_alias(self):
		self.assertEqual(
			'sync_pane_location', _get_command_name(SyncPaneLocation)
		)
		self.assertEqual(('Sync Pane Location',), SyncPaneLocation.aliases)
	def test_syncs_opposite_pane_to_active_path(self):
		left_pane = Mock()
		right_pane = Mock()
		left_pane.window.get_panes.return_value = [left_pane, right_pane]
		left_pane.get_path.return_value = 'file:///C:/source'
		right_pane.get_path.return_value = 'file:///D:/target'

		SyncPaneLocation(left_pane)()

		right_pane.set_path.assert_called_once_with('file:///C:/source')
		left_pane.set_path.assert_not_called()
		left_pane.focus.assert_not_called()
		right_pane.focus.assert_not_called()
	def test_syncs_left_pane_when_right_is_active(self):
		left_pane = Mock()
		right_pane = Mock()
		right_pane.window.get_panes.return_value = [left_pane, right_pane]
		right_pane.get_path.return_value = 'file:///C:/source'
		left_pane.get_path.return_value = 'file:///D:/target'

		SyncPaneLocation(right_pane)()

		left_pane.set_path.assert_called_once_with('file:///C:/source')
		right_pane.set_path.assert_not_called()
		left_pane.focus.assert_not_called()
		right_pane.focus.assert_not_called()
	def test_visibility_requires_an_opposite_pane(self):
		pane = Mock()
		pane.window.get_panes.return_value = [pane]
		self.assertFalse(SyncPaneLocation(pane).is_visible())

		other_pane = Mock()
		pane.window.get_panes.return_value = [pane, other_pane]
		self.assertTrue(SyncPaneLocation(pane).is_visible())
	@patch('core.commands.show_status_message')
	def test_single_pane_invocation_reports_without_navigation(
		self, show_status_message_mock
	):
		pane = Mock()
		pane.window.get_panes.return_value = [pane]

		SyncPaneLocation(pane)()

		pane.set_path.assert_not_called()
		show_status_message_mock.assert_called_once_with(
			'No other pane to sync.', timeout_secs=3
		)
	@patch('core.commands.show_status_message')
	def test_null_location_is_not_synchronized(self, show_status_message_mock):
		pane = Mock()
		other_pane = Mock()
		pane.window.get_panes.return_value = [pane, other_pane]
		pane.get_path.return_value = 'null://'

		SyncPaneLocation(pane)()

		other_pane.set_path.assert_not_called()
		show_status_message_mock.assert_called_once_with(
			'No location to sync.', timeout_secs=3
		)
	def test_same_location_does_not_reload_opposite_pane(self):
		pane = Mock()
		other_pane = Mock()
		pane.window.get_panes.return_value = [pane, other_pane]
		pane.get_path.return_value = 'file:///C:/same'
		other_pane.get_path.return_value = 'file:///C:/same'

		SyncPaneLocation(pane)()

		other_pane.set_path.assert_not_called()

class FindExtensionStartTest(TestCase):
	def test_no_extension(self):
		self.assertIsNone(_find_extension_start('File'))
	def test_normal_extension(self):
		self.assertEqual(4, _find_extension_start('test.zip'))
	def test_tar_xz(self):
		self.assertEqual(7, _find_extension_start('archive.tar.xz'))
	def test_tar_gz(self):
		self.assertEqual(7, _find_extension_start('archive.tar.gz'))

class ConfirmTreeOperationTest(TestCase):

	class FileSystem:
		def __init__(self, files, case_sensitive=PLATFORM == 'Linux'):
			self._files = files
			self._case_sensitive = case_sensitive

		def exists(self, url):
			try:
				self._get(url)
			except KeyError:
				return False
			return True

		def is_dir(self, url):
			try:
				file_info = self._get(url)
			except KeyError:
				raise filenotfounderror(url) from None
			return file_info['is_dir']

		def samefile(self, url1, url2):
			if not self._case_sensitive:
				url1 = url1.lower()
				url2 = url2.lower()
			return url1 == url2

		def _get(self, url):
			dict_ = self._files
			if not self._case_sensitive:
				dict_ = {k.lower(): v for k, v in self._files.items()}
				url = url.lower()
			return dict_[url]

	def test_no_files(self):
		self._expect_alert(('No file is selected!',), answer=OK)
		self._check([], None)
	def test_one_file(self):
		dest_path = as_human_readable(join(self._dest, 'a.txt'))
		sel_start = dest_path.rindex(os.sep) + 1
		self._expect_prompt(
			('Move "a.txt" to', dest_path, sel_start, sel_start + 1),
			(dest_path, True)
		)
		self._check([self._a_txt], (self._dest, 'a.txt'))
	def test_one_dir(self):
		dest_path = as_human_readable(self._dest)
		self._expect_prompt(
			('Move "a" to', dest_path, 0, None), (dest_path, True)
		)
		self._check([self._a], (self._dest, None))
	def test_rename_dir_to_uppercase(self):
		dest_path = as_human_readable(self._src)
		self._expect_prompt(
			('Move "a" to', dest_path, 0, None), ('A', True)
		)
		self._check([self._a], (self._src, 'A'), dest_dir=self._src)
	def test_two_files(self):
		dest_path = as_human_readable(self._dest)
		self._expect_prompt(
			('Move 2 files to', dest_path, 0, None), (dest_path, True)
		)
		self._check([self._a_txt, self._b_txt], (self._dest, None))
	def test_into_subfolder(self):
		dest_path = as_human_readable(join(self._dest, 'a.txt'))
		sel_start = dest_path.rindex(os.sep) + 1
		self._expect_prompt(
			('Move "a.txt" to', dest_path, sel_start, sel_start + 1),
			('a', True)
		)
		self._check([self._a_txt], (self._a, None))
	def test_overwrite_single_file(self):
		dest_url = join(self._dest, 'a.txt')
		self._fs._files[dest_url] = {'is_dir': False}
		dest_path = as_human_readable(dest_url)
		sel_start = dest_path.rindex(os.sep) + 1
		self._expect_prompt(
			('Move "a.txt" to', dest_path, sel_start, sel_start + 1),
			(dest_path, True)
		)
		self._check([self._a_txt], (self._dest, 'a.txt'))
	def test_multiple_files_over_one(self):
		dest_url = join(self._dest, 'a.txt')
		self._fs._files[dest_url] = {'is_dir': False}
		dest_path = as_human_readable(dest_url)
		self._expect_prompt(
			('Move 2 files to', as_human_readable(self._dest), 0, None),
			(dest_path, True)
		)
		self._expect_alert(
			('You cannot move multiple files to a single file!',), answer=OK
		)
		self._check([self._a_txt, self._b_txt], None)
	def test_multiple_into_self(self):
		dest_path = as_human_readable(self._a)
		self._expect_prompt(
			('Move 2 files to', dest_path, 0, None), (dest_path, True)
		)
		self._expect_alert(('You cannot move a file to itself!',), answer=OK)
		self._check([self._a_txt, self._a], None, dest_dir=self._a)
	def test_renamed_destination(self):
		dest_path = as_human_readable(join(self._dest, 'a.txt'))
		sel_start = dest_path.rindex(os.sep) + 1
		self._expect_prompt(
			('Move "a.txt" to', dest_path, sel_start, sel_start + 1),
			(as_human_readable(join(self._dest, 'z.txt')), True)
		)
		self._check([self._a_txt], (self._dest, 'z.txt'))
	def test_multiple_files_nonexistent_dest(self):
		dest_url = join(self._dest, 'dir')
		dest_path = as_human_readable(dest_url)
		self._expect_prompt(
			('Move 2 files to', as_human_readable(self._dest), 0, None),
			(dest_path, True)
		)
		self._expect_alert(
			('%s does not exist. Do you want to create it as a directory and '
			 'move the files there?' % dest_path, YES | NO, YES),
			answer=YES
		)
		self._check([self._a_txt, self._b_txt], (dest_url, None))
	def test_file_system_root(self):
		dest_path = as_human_readable(join(self._root, 'a.txt'))
		sel_start = dest_path.rindex(os.sep) + 1
		self._expect_prompt(
			('Move "a.txt" to', dest_path, sel_start, sel_start + 1),
			(dest_path, True)
		)
		self._check([self._a_txt], (self._root, 'a.txt'), dest_dir=self._root)
	def test_different_scheme(self):
		dest_path = as_human_readable(join(self._dest, 'a.txt'))
		sel_start = dest_path.rindex(os.sep) + 1
		self._expect_prompt(
			('Move "a.txt" to', dest_path, sel_start, sel_start + 1),
			(dest_path, True)
		)
		src_url = 'zip:///dest.zip/a.txt'
		src_dir = dirname(src_url)
		self._check([src_url], (self._dest, 'a.txt'), src_dir=src_dir)
	def _expect_alert(self, args, answer):
		self._ui.expect_alert(args, answer)
	def _expect_prompt(self, args, answer):
		self._ui.expect_prompt(args, answer)
	def _check(self, files, expected_result, src_dir=None, dest_dir=None):
		if src_dir is None:
			src_dir = self._src
		if dest_dir is None:
			dest_dir = self._dest
		actual_result = Move._confirm_tree_operation(
			files, dest_dir, src_dir, self._ui, self._fs
		)
		self._ui.verify_expected_dialogs_were_shown()
		self.assertEqual(expected_result, actual_result)
	def setUp(self):
		super().setUp()
		self._ui = StubUI(self)
		self._root = as_url('C:\\' if PLATFORM == 'Windows' else '/')
		self._src = join(self._root, 'src')
		self._dest = join(self._root, 'dest')
		self._a = join(self._root, 'src/a')
		self._a_txt = join(self._root, 'src/a.txt')
		self._b_txt = join(self._root, 'src/b.txt')
		self._fs = self.FileSystem({
			self._src: {'is_dir': True},
			self._dest: {'is_dir': True},
			self._a: {'is_dir': True},
			self._a_txt: {'is_dir': False},
			self._b_txt: {'is_dir': False},
		})

class GetDestSuggestionTest(TestCase):
	def test_file(self):
		file_path = os.path.join(self._root, 'file.txt')
		selection_start = file_path.rindex(os.sep) + 1
		selection_end = selection_start + len('file')
		self.assertEqual(
			(file_path, selection_start, selection_end),
			get_dest_suggestion(as_url(file_path))
		)
	def test_dir(self):
		dir_path = os.path.join(self._root, 'dir')
		selection_start = dir_path.rindex(os.sep) + 1
		selection_end = None
		self.assertEqual(
			(dir_path, selection_start, selection_end),
			get_dest_suggestion(as_url(dir_path))
		)
	def setUp(self):
		super().setUp()
		self._root = 'C:\\' if PLATFORM == 'Windows' else '/'

class FromHumanReadableTest(TestCase):
	def test_no_src_dir(self):
		path = __file__
		dir_url = as_url(os.path.dirname(path))
		self.assertEqual(
			as_url(path),
			_from_human_readable(path, dir_url, None)
		)

class GetShortcutsForCommandTest(TestCase):
	def test_no_shortcut(self):
		self._check([{'keys': ['Enter'], 'command': 'open'}], 'copy', [])
	def test_simple(self):
		self._check([{'keys': ['Enter'], 'command': 'open'}], 'open', ['Enter'])
	def test_two_shortcuts(self):
		self._check(
			[{'keys': ['Enter'], 'command': 'open'},
			 {'keys': ['Down'], 'command': 'open'}],
			'open', ['Enter', 'Down']
		)
	def test_shortcut_only_displayed_for_one_command(self):
		bindings = [
			{'keys': ['Enter'], 'command': 'open'},
			{'keys': ['Enter'], 'command': 'alternative'}
		]
		self._check(bindings, 'open', ['Enter'])
		self._check(bindings, 'alternative', [])
	def _check(self, key_bindings, command, expected_shortcuts):
		actual = list(_get_shortcuts_for_command(key_bindings, command))
		self.assertEqual(expected_shortcuts, actual)

class HistoryTest(TestCase):
	def test_empty_back(self):
		with self.assertRaises(ValueError):
			self._go_back()
	def test_empty_forward(self):
		with self.assertRaises(ValueError):
			self._go_forward()
	def test_single_back(self):
		self._go_to('single item')
		with self.assertRaises(ValueError):
			self._go_back()
	def test_single_forward(self):
		self._go_to('single item')
		with self.assertRaises(ValueError):
			self._go_forward()
	def test_go_back_forward(self):
		self._go_to('a', 'b', 'c')
		self.assertEqual('b', self._go_back())
		self.assertEqual('a', self._go_back())
		self.assertEqual('b', self._go_forward())
		self.assertEqual('c', self._go_forward())
	def test_go_to_after_back(self):
		self._go_to('a', 'b')
		self.assertEqual('a', self._go_back())
		self._go_to('c')
		self.assertEqual(['a', 'c'], self._history._paths)
	def setUp(self):
		super().setUp()
		self._history = History()
	def _go_back(self):
		path = self._history.go_back()
		self._history.path_changed(path)
		return path
	def _go_forward(self):
		path = self._history.go_forward()
		self._history.path_changed(path)
		return path
	def _go_to(self, *paths):
		for path in paths:
			self._history.path_changed(path)