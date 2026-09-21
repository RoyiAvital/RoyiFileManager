from core.commands import About, CreateAndEditFile, History, Move, NewEmptyFile, \
	OpenWithEditor, ViewFile, SetTextEditor, SetTextViewer, \
	ResetWindowGeometry, \
	SyncPaneLocation, \
	_from_human_readable, \
	get_dest_suggestion, _find_extension_start, _get_shortcuts_for_command, \
	_recent_commands, _COMMAND_PALETTE_HISTORY, CommandPalette, CommandPaletteItem
from core.tests import StubUI
from core.commands import _hidden_file_filter
from core.util import filenotfounderror
from fman import OK, YES, NO, PLATFORM
from fman.impl.plugins.plugin import _get_command_name
from fman.url import join, as_human_readable, as_url, dirname
from unittest import TestCase
from unittest.mock import call, Mock, patch

import json
import os
import os.path

class HiddenFileFilterTest(TestCase):
	def setUp(self):
		self.platform = patch('core.commands.PLATFORM', 'Windows')
		self.platform.start()
		self.addCleanup(self.platform.stop)
	def test_cached_flags_skip_qt_on_repeated_passes(self):
		for hidden in (True, False):
			with patch('core.commands.query', return_value=hidden) as query, \
				patch('core.commands.is_hidden', side_effect=AssertionError):
				for _ in range(3):
					self.assertIs(not hidden, _hidden_file_filter('file://C:/entry'))
				self.assertEqual(3, query.call_count)
	def test_unknown_and_oserror_use_qt(self):
		for result in (None, OSError('unavailable')):
			for hidden in (True, False):
				with patch('core.commands.query', return_value=None,
					side_effect=result) as query, \
					patch('core.commands.is_hidden', return_value=hidden) as fallback:
					self.assertIs(not hidden, _hidden_file_filter('file://C:/entry'))
					fallback.assert_called_once_with('C:/entry')
	def test_provider_without_private_method_falls_back(self):
		provider = object()
		with patch('core.commands.query', side_effect=lambda *args:
			getattr(provider, '_pane_hidden_state')('C:/entry')), \
			patch('core.commands.is_hidden', return_value=True) as fallback:
			self.assertFalse(_hidden_file_filter('file://C:/entry'))
			fallback.assert_called_once()
	def test_errors_inside_existing_method_propagate(self):
		class Provider:
			def _pane_hidden_state(self, path):
				return self.bug
		for error in (AttributeError('bug'), ValueError('bug'), RuntimeError('bug')):
			with patch('core.commands.query', side_effect=error), \
				patch('core.commands.is_hidden', side_effect=AssertionError):
				with self.assertRaises(type(error)):
					_hidden_file_filter('file://C:/entry')
		with patch('core.commands.query', side_effect=lambda *args:
			Provider()._pane_hidden_state('entry')):
			with self.assertRaises(AttributeError):
				_hidden_file_filter('file://C:/entry')
	def test_nonlocal_and_mac_volumes_bypass_local_checks(self):
		for platform, url in (('Windows', 'zip://archive/entry'),
			('Mac', 'file:///Volumes')):
			with patch('core.commands.PLATFORM', platform), \
				patch('core.commands.query', side_effect=AssertionError), \
				patch('core.commands.is_hidden', side_effect=AssertionError):
				self.assertTrue(_hidden_file_filter(url))
	def test_nonwindows_keeps_qt(self):
		with patch('core.commands.PLATFORM', 'Linux'), \
			patch('core.commands.query', side_effect=AssertionError), \
			patch('core.commands.is_hidden', return_value=True):
			self.assertFalse(_hidden_file_filter('file:///tmp/entry'))

class AboutTest(TestCase):
	@patch('core.commands.show_alert')
	def test_shows_product_version_from_build_settings(self, show_alert):
		from fman import FMAN_VERSION
		from pathlib import Path
		settings_path = Path(__file__).resolve().parents[9] / 'src/build/settings/base.json'
		version = json.loads(settings_path.read_text(encoding='utf-8'))['version']
		context = Mock(build_settings={'version': version})
		with patch('fman.impl.application_context.get_application_context', return_value=context):
			About(Mock())()
		show_alert.assert_called_once_with(
			'RoyiFileManager version: %s\nfman plug-in API: %s' % (version, FMAN_VERSION)
		)
		self.assertNotEqual(FMAN_VERSION, version)

class CommandPaletteHistoryTest(TestCase):
	def setUp(self):
		from fman.impl.plugins.config import Config
		from fman.ui import Resource
		from pathlib import Path
		from tempfile import TemporaryDirectory
		self.temporary = TemporaryDirectory()
		self.addCleanup(self.temporary.cleanup)
		self.root = Path(self.temporary.name)
		self.config = Config('Windows')
		self.config.add_dir(str(self.root))
		self.history_path = self.root / 'Command Palette History (Windows).json'
		self.resource = Resource()
		self.load_patch = patch('core.commands.load_json', side_effect=self.config.load_json)
		self.load_patch.start()
		self.addCleanup(self.load_patch.stop)
		resource_patch = patch('fman.ui.settings_resource', return_value=self.resource)
		resource_patch.start()
		self.addCleanup(resource_patch.stop)
	def test_record_eviction_and_dict_identity(self):
		document = self.config.load_json(_COMMAND_PALETTE_HISTORY, default={'other': True})
		for name in ('first', 'second', 'third', 'fourth', 'second'):
			_recent_commands(executed=('pane', name))
		self.assertEqual((('pane', 'second'), ('pane', 'fourth'), ('pane', 'third')), _recent_commands())
		self.assertIs(document, self.config.load_json(_COMMAND_PALETTE_HISTORY))
		self.assertTrue(document['other'])
		self.assertFalse(self.history_path.exists())
	def test_quit_restart_round_trip_without_session_writes(self):
		from fman.impl.plugins.config import Config
		_recent_commands(executed=('application', 'quit'))
		self.assertEqual([], list(self.root.iterdir()))
		self.config.on_quit()
		restarted = Config('Windows')
		restarted.add_dir(str(self.root))
		with patch('core.commands.load_json', side_effect=restarted.load_json):
			self.assertEqual((('application', 'quit'),), _recent_commands())
	def test_invalid_files_use_shared_fallback_without_overwriting(self):
		from fman.impl.plugins.config import Config
		for contents in ('{', 'null', '[]', '42', '"history"'):
			with self.subTest(contents=contents):
				self.history_path.write_text(contents, encoding='utf-8')
				config = Config('Windows')
				config.add_dir(str(self.root))
				with patch('core.commands.load_json', side_effect=config.load_json):
					_recent_commands(executed=('pane', 'copy'))
					self.assertEqual((('pane', 'copy'),), _recent_commands())
				self.assertNotIn(_COMMAND_PALETTE_HISTORY, config._save_on_quit)
				config.on_quit()
				self.assertEqual(contents, self.history_path.read_text(encoding='utf-8'))
	def test_read_errors_use_fallback(self):
		with patch('core.commands.load_json', side_effect=PermissionError):
			self.assertEqual((('pane', 'copy'),), _recent_commands(executed=('pane', 'copy')))
			self.assertEqual((('pane', 'copy'),), _recent_commands())
	def test_fallback_survives_command_module_reload(self):
		from subprocess import run
		from textwrap import dedent
		import sys
		script = dedent('''\
			import core.commands as commands
			from fman.ui import settings_resource
			from importlib import reload
			from unittest.mock import patch
			resource = settings_resource(commands._COMMAND_PALETTE_HISTORY)
			with patch('core.commands.load_json', side_effect=PermissionError):
				commands._recent_commands(executed=('pane', 'copy'))
			reload(commands)
			assert settings_resource(commands._COMMAND_PALETTE_HISTORY) is resource
			with patch('core.commands.load_json', side_effect=PermissionError):
				assert commands._recent_commands() == (('pane', 'copy'),)
		''')
		result = run([sys.executable, '-c', script], capture_output=True, text=True)
		self.assertEqual(0, result.returncode, result.stdout + result.stderr)
	def test_valid_history_retains_dict_on_config_reload(self):
		_recent_commands(executed=('pane', 'copy'))
		self.config.on_quit()
		document = self.config.load_json(_COMMAND_PALETTE_HISTORY)
		self.config.add_dir(str(self.root / 'another_plugin'))
		self.assertIs(document, self.config.load_json(_COMMAND_PALETTE_HISTORY))
		self.assertEqual((('pane', 'copy'),), _recent_commands())
	def test_unsaved_history_survives_plugin_reload_and_quit(self):
		from core.commands import ReloadPlugins
		_recent_commands(executed=('pane', 'copy'))
		self.config.on_quit()
		before = self.history_path.read_bytes()
		_recent_commands(executed=('pane', 'paste'))
		plugin = str(self.root)
		with patch('core.commands._get_plugins', return_value=[plugin]), \
			patch('core.commands.PreservePanePaths'), \
			patch('core.commands.unload_plugin', side_effect=self.config.remove_dir), \
			patch('core.commands.load_plugin', side_effect=self.config.add_dir), \
			patch('core.commands.show_status_message'):
			ReloadPlugins(Mock())()
		self.assertEqual(before, self.history_path.read_bytes())
		self.config.on_quit()
		self.assertEqual([
			{'kind': 'pane', 'name': 'paste'}, {'kind': 'pane', 'name': 'copy'}
		], json.loads(self.history_path.read_text(encoding='utf-8'))['recent'])
	def test_normalize_before_display_and_preserve_scopes(self):
		entries = [None, 'legacy', {}, {'kind': 'pane', 'name': ''},
			{'kind': 'pane', 'name': ' '}, {'kind': [], 'name': 'bad'},
			{'kind': 'pane', 'name': 'x' * 257}]
		entries += [{'kind': 'pane', 'name': 'same'}] * 10
		entries += [{'kind': 'application', 'name': 'same'},
			{'kind': 'pane', 'name': 'third'}, {'kind': 'pane', 'name': 'fourth'}]
		self.history_path.write_text(json.dumps({'recent': entries}), encoding='utf-8')
		self.assertEqual((('pane', 'same'), ('application', 'same'), ('pane', 'third')), _recent_commands())
	def test_bounds_input_scan(self):
		self.history_path.write_text(json.dumps({'recent': [None] * 256 + [
			{'kind': 'pane', 'name': 'beyond_bound'}]}), encoding='utf-8')
		self.assertEqual((), _recent_commands())
	def test_wrong_recent_value_resets_in_valid_dict(self):
		for value in (None, 'text', {}, 3):
			with self.subTest(value=value):
				document = self.config.load_json(_COMMAND_PALETTE_HISTORY, default={})
				document['recent'] = value
				self.assertEqual((), _recent_commands())
				self.assertEqual([], document['recent'])
	def test_prune_missing_registry_entries(self):
		_recent_commands(executed=('pane', 'missing'))
		_recent_commands(executed=('pane', 'hidden_but_registered'))
		self.assertEqual((('pane', 'hidden_but_registered'),),
			_recent_commands(registered={('pane', 'hidden_but_registered')}))
	def test_concurrent_record_and_prune(self):
		from concurrent.futures import ThreadPoolExecutor
		identities = tuple(('pane', name) for name in ('first', 'second', 'third'))
		with ThreadPoolExecutor(max_workers=4) as workers:
			futures = [workers.submit(_recent_commands, registered=set(identities), executed=identity)
				for identity in identities for repeat in range(20)]
			for future in futures:
				self.assertLessEqual(len(future.result()), 3)
		self.assertEqual(set(identities), set(_recent_commands()))

class CommandPaletteRecentTest(TestCase):
	def setUp(self):
		from fman.ui import Resource
		self.document = {'recent': []}
		self.bindings = [{'keys': ['Ctrl+A'], 'command': 'alpha'}]
		self.pane = Mock()
		self.aliases = {'alpha': ['Alpha'], 'beta': ['Beta'], 'files': ['Find files', 'Search files']}
		self.app_aliases = {'exit': ['Exit']}
		self.pane.get_commands.side_effect = lambda: list(self.aliases)
		self.pane.is_command_visible.return_value = True
		self.pane.get_command_aliases.side_effect = self.aliases.__getitem__
		patches = [
			patch('core.commands.load_json', side_effect=lambda name, **kwargs:
				self.bindings if name == 'Key Bindings.json' else self.document),
			patch('core.commands.get_application_commands', side_effect=lambda: list(self.app_aliases)),
			patch('core.commands.get_application_command_aliases', side_effect=self.app_aliases.__getitem__),
			patch('fman.ui.settings_resource', return_value=Resource())
		]
		for patcher in patches:
			patcher.start()
			self.addCleanup(patcher.stop)
		self.palette = CommandPalette(self.pane)
	def seed(self, *identities):
		self.document['recent'] = [{'kind': kind, 'name': name} for kind, name in identities]
	def open(self, query='', result=None):
		items = []
		def show(provider, **kwargs):
			items.extend(provider(query))
			return result
		with patch('core.commands.show_quicksearch', side_effect=show):
			self.palette()
		return items
	def test_empty_history_preserves_titles_order_hints_and_highlights(self):
		items = self.open()
		self.assertEqual(['Beta', 'Exit', 'Alpha', 'Find files'], [item.title for item in items])
		self.assertEqual(['', '', 'Ctrl+A', ''], [item.hint for item in items])
		self.assertTrue(all(not item.highlight for item in items))
	def test_pinned_items_have_hints_and_no_duplicates(self):
		self.seed(('pane', 'alpha'), ('pane', 'files'))
		items = self.open()
		self.assertEqual(['Alpha', 'Find files', 'Beta', 'Exit'], [item.title for item in items])
		self.assertEqual(['Ctrl+A \u00b7 Recent', 'Recent', '', ''], [item.hint for item in items])
	def test_multiple_shortcuts_retain_original_order(self):
		self.bindings.append({'keys': ['Alt+A'], 'command': 'alpha'})
		self.seed(('pane', 'alpha'))
		self.assertEqual('Ctrl+A, Alt+A \u00b7 Recent', self.open()[0].hint)
	def test_nonmatching_recent_omitted_and_matching_alias_highlight_preserved(self):
		baseline = list(self.palette._suggest_commands('search'))
		self.seed(('pane', 'alpha'), ('pane', 'files'))
		items = self.open('search')
		self.assertEqual(['Search files'], [item.title for item in items])
		self.assertEqual(baseline[0].highlight, items[0].highlight)
		self.assertEqual('Recent', items[0].hint)
	def test_tier_and_alias_precedence_unchanged(self):
		self.aliases.update({'contiguous': ['Amazing Bee'], 'fuzzy': ['Aardvark']})
		baseline = list(self.palette._suggest_commands('ab'))
		self.seed(('pane', 'alpha'))
		items = self.open('ab')
		self.assertEqual([(item.title, item.highlight) for item in baseline],
			[(item.title, item.highlight) for item in items])
	def test_records_before_execution_and_retains_query(self):
		command = CommandPaletteItem(self.pane.run_command, 'files')
		self.pane.run_command.side_effect = lambda name: self.assertEqual((('pane', 'files'),), _recent_commands())
		self.open(result=('file', command))
		self.pane.run_command.assert_called_once_with('files')
		self.assertEqual('file', self.palette._last_query)
	def test_cancelling_or_accepting_no_match_does_not_record(self):
		self.seed(('pane', 'alpha'))
		for result in (None, ('not found', None)):
			self.open(result=result)
			self.assertEqual((('pane', 'alpha'),), _recent_commands())
		self.pane.run_command.assert_not_called()
	def test_hidden_history_survives_pane_context_change(self):
		self.seed(('pane', 'alpha'))
		self.pane.is_command_visible.side_effect = lambda name: name != 'alpha'
		self.assertNotIn('Alpha', [item.title for item in self.open()])
		self.assertEqual((('pane', 'alpha'),), _recent_commands())
		self.pane.is_command_visible.side_effect = None
		self.palette = CommandPalette(self.pane)
		self.assertEqual('Alpha', self.open()[0].title)
	def test_missing_commands_are_pruned(self):
		self.seed(('pane', 'missing'), ('pane', 'alpha'))
		self.open()
		self.assertEqual((('pane', 'alpha'),), _recent_commands())
	def test_duplicate_names_keep_both_rows_and_correct_dispatch(self):
		self.app_aliases['alpha'] = ['Application Alpha']
		self.seed(('application', 'alpha'))
		with patch('core.commands.run_application_command') as run:
			items = self.open()
			self.assertEqual('Application Alpha', items[0].title)
			self.assertIn('Alpha', [item.title for item in items])
			self.open(result=('', items[0].value))
			run.assert_called_once_with('alpha')
		self.pane.run_command.assert_not_called()
		self.assertEqual((('application', 'alpha'),), _recent_commands())
	def test_empty_history_keeps_duplicate_names(self):
		self.app_aliases['alpha'] = ['Application Alpha']
		items = self.open()
		self.assertEqual(2, sum(item.value.name == 'alpha' for item in items))
	def test_cursor_restoration_uses_scoped_identity(self):
		self.app_aliases['alpha'] = ['Application Alpha']
		self.seed(('pane', 'alpha'), ('application', 'alpha'))
		self.palette._last_cmd_name = 'alpha'
		self.palette._last_cmd_kind = 'application'
		self.palette._last_query = 'alpha'
		with patch('core.commands.show_quicksearch', return_value=None) as show:
			self.palette()
		self.assertEqual(1, show.call_args.kwargs['item'])
		self.assertEqual('alpha', show.call_args.kwargs['query'])
		self.assertEqual('', self.palette._last_query)
		self.assertEqual('', self.palette._last_cmd_name)
		self.assertEqual('pane', self.palette._last_cmd_kind)
	def test_empty_query_restores_most_recent_at_zero(self):
		self.seed(('pane', 'files'))
		self.palette._last_cmd_name = 'files'
		with patch('core.commands.show_quicksearch', return_value=None) as show:
			self.palette()
		self.assertEqual(0, show.call_args.kwargs['item'])
	def test_provider_does_not_load_history(self):
		self.seed(('pane', 'alpha'))
		def show(provider, **kwargs):
			with patch('core.commands._recent_commands', side_effect=AssertionError('History on Qt')):
				self.assertTrue(list(provider('')))
				self.assertTrue(list(provider('a')))
		with patch('core.commands.show_quicksearch', side_effect=show):
			self.palette()
	def test_snapshot_stable_during_other_pane_recording(self):
		self.seed(('pane', 'alpha'))
		def show(provider, **kwargs):
			_recent_commands(executed=('pane', 'beta'))
			self.assertEqual('Alpha', list(provider(''))[0].title)
		with patch('core.commands.show_quicksearch', side_effect=show):
			self.palette()
		self.assertEqual('Beta', self.open()[0].title)

class NewEmptyFileTest(TestCase):
	def test_has_command_center_identifier_and_aliases(self):
		self.assertEqual('new_empty_file', _get_command_name(NewEmptyFile))
		self.assertEqual(
			('New file', 'Create file', 'New empty file', 'Create empty file', 'Touch'),
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

class TextEditorCommandsTest(TestCase):
	def test_command_center_identifiers_and_aliases(self):
		for command, name, alias in (
			(OpenWithEditor, 'open_with_editor', 'Edit'),
			(ViewFile, 'view_file', 'View'),
			(SetTextEditor, 'set_text_editor', 'Set text editor'),
			(SetTextViewer, 'set_text_viewer', 'Set text viewer')):
			with self.subTest(command=name):
				self.assertEqual(name, _get_command_name(command))
				self.assertEqual((alias,), command.aliases)

	@patch('core.text_editor.open_file')
	def test_launch_commands_route_cursor_and_explicit_target(self, open_file):
		pane = Mock()
		pane.get_file_under_cursor.return_value = 'file:///cursor.txt'
		for command, role in ((OpenWithEditor, 'editor'), (ViewFile, 'viewer')):
			command(pane)()
			open_file.assert_called_with('file:///cursor.txt', role)
			command(pane)('file:///explicit.txt')
			open_file.assert_called_with('file:///explicit.txt', role)
		self.assertEqual(4, open_file.call_count)

	@patch('core.text_editor.configure')
	def test_setup_commands_route_independently_without_target(self, configure):
		pane = Mock()
		SetTextEditor(pane)()
		SetTextViewer(pane)()
		self.assertEqual([call('editor'), call('viewer')], configure.call_args_list)
		pane.get_file_under_cursor.assert_not_called()

class CreateAndEditFileTest(TestCase):
	def test_has_command_center_identifier_and_aliases(self):
		self.assertEqual('create_and_edit_file', _get_command_name(CreateAndEditFile))
		self.assertEqual(('Edit new file', 'Create and edit file'), CreateAndEditFile.aliases)
		self.assertFalse(set(CreateAndEditFile.aliases) & set(NewEmptyFile.aliases))

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
	def test_has_command_center_identifier_and_alias(self):
		self.assertEqual('reset_window_geometry', _get_command_name(ResetWindowGeometry))
		self.assertEqual(('Reset window geometry',), ResetWindowGeometry.aliases)

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
		self.assertEqual(('Sync pane location',), SyncPaneLocation.aliases)
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