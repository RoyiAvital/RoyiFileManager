from copy import deepcopy
from core.comparator import MANUAL, SETTINGS, PaneSnapshot, PRESETS, configuration_args, configure, native_paths, prepare_launch, select_operands, validate_operands
from core.external_program import MAX_COMMAND_UNITS, parse_arguments
from fman.impl.plugins.config import Config
from fman.url import as_url
from pathlib import Path
from subprocess import check_output, list2cmdline
from tempfile import TemporaryDirectory
from threading import Lock
from unittest import TestCase
from unittest.mock import Mock, patch

import json
import os
import sys


class ComparatorOperandsTest(TestCase):
	def test_cross_pane_marks_and_cursors_keep_physical_order(self):
		for active in (0, 1):
			for left_marked in (False, True):
				for right_marked in (False, True):
					with self.subTest(active=active, left=left_marked, right=right_marked):
						panes = (
							PaneSnapshot('file://C:/left', ('left-mark',) if left_marked else (), 'left-cursor'),
							PaneSnapshot('file://C:/right', ('right-mark',) if right_marked else (), 'right-cursor'))
						self.assertEqual((('left-mark' if left_marked else 'left-cursor',
							'right-mark' if right_marked else 'right-cursor'), (0, 1)), select_operands('file', panes, active))

	def test_active_pair_ignores_opposite_and_has_stable_order(self):
		for selected in (('file://C:/z', 'file://C:/A'), ('file://C:/A', 'file://C:/z')):
			active = PaneSnapshot('file://C:', selected, None)
			other = PaneSnapshot('zip://invalid', ('one', 'two', 'three'), None)
			for panes, index in (((active,), 0), ((active, other), 0), ((other, active), 1)):
				with self.subTest(panes=panes, active=index):
					self.assertEqual((('file://C:/A', 'file://C:/z'), (index,)), select_operands('file', panes, index))
		pair = ('file://C:/a', 'file://C:/A')
		self.assertEqual(tuple(reversed(pair)), select_operands('file', (PaneSnapshot('file://C:', pair),), 0)[0])

	def test_ambiguity_and_missing_candidates_are_errors(self):
		valid = PaneSnapshot('file://C:', (), 'file://C:/one')
		for panes in ((valid,), (valid, valid, valid), (valid, PaneSnapshot('file://D:')),
			(PaneSnapshot('file://C:', ('a', 'b', 'c')), valid),
			(valid, PaneSnapshot('file://D:', ('a', 'b')))):
			with self.subTest(panes=panes), self.assertRaises(ValueError):
				select_operands('file', panes, 0)

	def test_folders_ignore_all_selection_and_cursor_state(self):
		panes = (PaneSnapshot('file://C:', ('a', 'b', 'c'), 'child'), PaneSnapshot('file://D:', (), None))
		for active in (0, 1):
			self.assertEqual((('file://C:', 'file://D:'), (0, 1)), select_operands('folder', panes, active))
		for panes in ((panes[0],), (*panes, panes[0])):
			with self.assertRaises(ValueError):
				select_operands('folder', panes, 0)

	def test_resolution_root_separators_and_unsupported_schemes(self):
		with patch('core.comparator.resolve', side_effect=lambda url: 'file://C:' if url == 'alias://root' else url):
			self.assertEqual(('C:\\', '\\\\server\\share'), native_paths(('alias://root', 'file:////server/share')))
			for url in ('zip://archive/file', 'process://1', 'null://', 'file://relative', None):
				with self.subTest(url=url), self.assertRaises(ValueError):
					native_paths((url,))


class ComparatorLaunchTest(TestCase):
	def setUp(self):
		self.directory = TemporaryDirectory()
		self.addCleanup(self.directory.cleanup)
		self.root = Path(self.directory.name)
		self.paths = tuple(str(self.root / name) for name in ('left {file} \u754c.txt', 'right %PATH%.txt'))
		for path in self.paths:
			Path(path).write_bytes(b'same\0binary')
		self.configuration = {'executable': sys.executable, 'arguments': []}

	def test_literal_arguments_reach_real_child_in_order(self):
		arguments = ['--flag', '', 'a"b', 'C:\\folder with spaces\\', '{literal}', '%PATH%', '\u754c']
		self.configuration['arguments'] = ['-c', 'import json,sys;print(json.dumps(sys.argv[1:]))',
			*parse_arguments(list2cmdline(arguments))]
		before = deepcopy(self.configuration)
		kwargs = prepare_launch(self.configuration, self.paths)
		self.assertFalse(kwargs['shell'])
		self.assertEqual([*arguments, *self.paths], json.loads(check_output(**kwargs, text=True)))
		self.assertEqual(before, self.configuration)

	def test_all_eight_preset_arrays(self):
		self.assertEqual(('Meld', 'Beyond Compare', 'WinMerge', 'SmartSynchronize'), tuple(preset[0] for preset in PRESETS))
		self.assertEqual(('Meld.exe', 'BCompare.exe', 'WinMergeU.exe', 'smartsynchronize.exe'), tuple(preset[1] for preset in PRESETS))
		self.assertEqual((((), ()), (('/solo',), ('/solo',)), (('/s-', '/u'), ('/s-', '/u', '/r')), ((), ())),
			tuple((preset[2], preset[3]) for preset in PRESETS))
		for preset in PRESETS:
			for arguments in preset[2:]:
				self.configuration['arguments'] = list(arguments)
				self.assertEqual([sys.executable, *arguments, *self.paths], prepare_launch(self.configuration, self.paths)['args'])

	def test_invalid_configuration_and_command_limits(self):
		for configuration in (None, {}, [], {'args': [sys.executable]},
			{'executable': 'relative.exe', 'arguments': []},
			{'executable': str(self.root / 'tool.cmd'), 'arguments': []},
			{'executable': sys.executable, 'arguments': 'not argv'},
			{'executable': sys.executable, 'arguments': [None]},
			dict(self.configuration, shell=True), dict(self.configuration, cwd='C:\\'),
			dict(self.configuration, arguments=['\0']), dict(self.configuration, arguments=['x' * MAX_COMMAND_UNITS]),
			dict(self.configuration, executable=str(self.root / 'missing.exe'))):
			with self.subTest(configuration=configuration), self.assertRaises(ValueError):
				prepare_launch(configuration, self.paths)
		for paths in ((), (self.paths[0],), ('relative.txt', self.paths[0]), ('C:\\bad\0', self.paths[0])):
			with self.subTest(paths=paths), self.assertRaises(ValueError):
				prepare_launch(self.configuration, paths)
		with patch('core.comparator.os.stat') as metadata:
			configuration_args(self.configuration)
			metadata.assert_not_called()

	def test_types_identity_and_metadata_only_checks(self):
		check = Mock()
		validate_operands(self.paths, 'file', check)
		self.assertEqual(4, check.call_count)
		child = self.root / 'child'
		child.mkdir()
		validate_operands((str(self.root), str(child)), 'folder', Mock())
		link = self.root / 'hardlink.txt'
		os.link(self.paths[0], link)
		for paths, role in (((self.paths[0], self.paths[0]), 'file'), ((self.paths[0], str(link)), 'file'),
			((self.paths[0], str(self.root)), 'file'), (self.paths, 'folder'),
			((self.paths[0], str(self.root / 'missing')), 'file')):
			with self.subTest(paths=paths, role=role), self.assertRaises(ValueError):
				validate_operands(paths, role, Mock())
		with patch('core.comparator.os.stat', side_effect=PermissionError('denied')), self.assertRaisesRegex(ValueError, 'inaccessible'):
			validate_operands(self.paths, 'file', Mock())
		with patch('core.comparator.os.stat', return_value=Mock(st_mode=0o100644, st_ino=0)), self.assertRaisesRegex(ValueError, 'identity'):
			validate_operands(self.paths, 'file', Mock())

	def test_symlink_alias_and_dangling_link(self):
		link = self.root / 'link.txt'
		try:
			link.symlink_to(self.paths[0])
		except OSError as error:
			self.skipTest('Symlink creation unavailable: %s' % error)
		with self.assertRaisesRegex(ValueError, 'different filesystem objects'):
			validate_operands((self.paths[0], str(link)), 'file', Mock())
		Path(self.paths[0]).unlink()
		with self.assertRaisesRegex(ValueError, 'inaccessible'):
			validate_operands((str(link), self.paths[1]), 'file', Mock())


class ComparatorWizardTest(TestCase):
	def setUp(self):
		self.directory = TemporaryDirectory()
		self.addCleanup(self.directory.cleanup)
		self.config = Config('Windows')
		self.config.add_dir(self.directory.name)
		self.original = {'file_comparator': {'executable': sys.executable, 'arguments': ['--files']},
			'folder_comparator': {'executable': sys.executable, 'arguments': ['--folders']},
			'editor': {'args': [sys.executable, '{file}']}, 'unrelated': {'keep': True}}
		self.config.save_json(SETTINGS, deepcopy(self.original))
		self.mocks = {}
		for name in ('show_quicksearch', 'show_file_open_dialog', 'show_prompt',
			'show_status_message', 'show_alert', 'load_json', 'save_json', 'Popen'):
			patcher = patch('core.comparator.' + name)
			self.mocks[name] = patcher.start()
			self.addCleanup(patcher.stop)
		self.mocks['load_json'].side_effect = self.config.load_json
		self.mocks['save_json'].side_effect = self.config.save_json
		self.mocks['show_quicksearch'].return_value = ('', MANUAL)
		self.mocks['show_file_open_dialog'].return_value = sys.executable
		self.mocks['show_prompt'].return_value = ('', True)

	def assert_persisted(self, expected):
		reloaded = Config('Windows')
		reloaded.add_dir(self.directory.name)
		self.assertEqual(expected, reloaded.load_json(SETTINGS))

	def test_all_presets_and_roles_persist_independently(self):
		for role in ('file', 'folder'):
			for name, executable, file_args, folder_args in PRESETS:
				with self.subTest(role=role, preset=name):
					self.config.save_json(SETTINGS, deepcopy(self.original))
					self.mocks['show_quicksearch'].return_value = ('', name)
					result = configure(role)
					self.assertEqual({'executable': sys.executable, 'arguments': list(file_args if role == 'file' else folder_args)}, result)
					self.assert_persisted(dict(self.original, **{role + '_comparator': result}))
					self.mocks['show_file_open_dialog'].assert_called_with('Set %s comparator' % role,
						sys.executable, '%s (%s);;Applications (*.exe)' % (name, executable))
					items = self.mocks['show_quicksearch'].call_args.args[0]
					self.assertEqual([preset[0] for preset in PRESETS] + [MANUAL, 'Clear %s comparator' % role],
						[item.value for item in items('')])
					self.assertEqual(['WinMerge'], [item.value for item in items('winmerge')])
		self.mocks['Popen'].assert_not_called()
		self.mocks['show_prompt'].assert_not_called()

	def test_manual_prefill_and_literal_arguments(self):
		arguments = ['', 'a"b', '{left}', '%PATH%', 'C:\\folder with spaces\\']
		self.mocks['show_prompt'].return_value = (list2cmdline(arguments), True)
		result = configure('file')
		self.assertEqual(arguments, result['arguments'])
		self.mocks['show_prompt'].assert_called_once_with('Arguments:', '--files')
		self.assert_persisted(dict(self.original, file_comparator=result))

	def test_cancellation_at_each_step_never_saves_or_launches(self):
		for role in ('file', 'folder'):
			for name, value in (('show_quicksearch', None), ('show_quicksearch', ('', None)),
				('show_file_open_dialog', ''), ('show_prompt', ('ignored', False))):
				with self.subTest(role=role, step=name):
					previous = self.mocks[name].return_value
					self.mocks[name].return_value = value
					self.assertIsNone(configure(role))
					self.mocks[name].return_value = previous
					self.assert_persisted(self.original)
		self.mocks['save_json'].assert_not_called()
		self.mocks['Popen'].assert_not_called()

	def test_clear_masks_inheritance_and_leaves_other_role(self):
		self.config.add_dir(str(Path(self.directory.name, 'user')))
		for role in ('file', 'folder'):
			self.config.save_json(SETTINGS, deepcopy(self.original))
			self.mocks['show_quicksearch'].return_value = ('', 'Clear %s comparator' % role)
			configure(role)
			reloaded = Config('Windows')
			reloaded.add_dir(self.directory.name)
			self.assertEqual(self.original, reloaded.load_json(SETTINGS))
			reloaded.add_dir(str(Path(self.directory.name, 'user')))
			self.assertEqual(dict(self.original, **{role + '_comparator': None}), reloaded.load_json(SETTINGS))
		self.mocks['show_file_open_dialog'].assert_not_called()
		self.mocks['Popen'].assert_not_called()

	def test_clear_unset_does_not_write(self):
		for settings in ({}, {'file_comparator': None}):
			self.config.save_json(SETTINGS, settings)
			self.mocks['show_quicksearch'].return_value = ('', 'Clear file comparator')
			configure('file')
		self.mocks['save_json'].assert_not_called()

	def test_unrelated_edits_preserved_and_same_role_conflicts(self):
		for changed_key in ('unrelated', 'file_comparator'):
			with self.subTest(key=changed_key):
				self.config.save_json(SETTINGS, deepcopy(self.original))
				def change_settings(*args):
					self.config.save_json(SETTINGS, dict(self.original, **{changed_key: {'new': True}}))
					return '', True
				self.mocks['show_prompt'].side_effect = change_settings
				result = configure('file')
				if changed_key == 'file_comparator':
					self.assertIsNone(result)
					self.assert_persisted(dict(self.original, file_comparator={'new': True}))
					self.assertIn('changed while setup', self.mocks['show_alert'].call_args.args[0])
				else:
					self.assert_persisted(dict(self.original, unrelated={'new': True}, file_comparator=result))

	def test_invalid_settings_and_failed_save_preserve_cache(self):
		cached = self.config.load_json(SETTINGS)
		for error in (OSError('Read only'), ValueError('Invalid save')):
			self.mocks['save_json'].side_effect = error
			self.assertIsNone(configure('file'))
			self.assertEqual(self.original, cached)
			self.assert_persisted(self.original)
		self.mocks['show_status_message'].assert_not_called()
		self.mocks['Popen'].assert_not_called()
		self.mocks['load_json'].side_effect = lambda *args, **kwargs: []
		self.assertIsNone(configure('folder'))
		self.assertIn('must contain an object', self.mocks['show_alert'].call_args.args[0])


class ComparatorCommandTest(TestCase):
	def test_commands_delegate_lazily_with_exact_labels(self):
		from core.commands import CompareFiles, CompareFolders, SetFileComparator, SetFolderComparator
		from fman.impl.plugins.plugin import _get_command_name
		pane = Mock()
		for command, role, identifier, label in (
			(CompareFiles, 'file', 'compare_files', 'Compare files'),
			(CompareFolders, 'folder', 'compare_folders', 'Compare folders'),
			(SetFileComparator, 'file', 'set_file_comparator', 'Set file comparator'),
			(SetFolderComparator, 'folder', 'set_folder_comparator', 'Set folder comparator')):
			with self.subTest(command=identifier), patch('core.comparator.compare') as launch, patch('core.comparator.configure') as setup:
				self.assertEqual(identifier, _get_command_name(command))
				self.assertEqual((label,), command.aliases)
				command(pane)()
				if identifier.startswith('set_'):
					setup.assert_called_once_with(role)
					launch.assert_not_called()
				else:
					launch.assert_called_once_with(pane, role)
					setup.assert_not_called()

	def test_existing_name_comparison_is_unchanged(self):
		from core.commands import CompareDirectories
		left, right = Mock(), Mock()
		left.window.get_panes.return_value = [left, right]
		left.get_path.return_value = 'file://C:/left'
		right.get_path.return_value = 'file://C:/right'
		with patch('core.commands.iterdir', side_effect=lambda url: ['common', 'left-only'] if url.endswith('left') else ['common']), patch('core.commands.show_alert'):
			CompareDirectories(left)()
			self.assertEqual(['file://C:/left/left-only'], list(left.select.call_args.args[0]))
			self.assertEqual([], list(right.select.call_args.args[0]))

	def test_unconfigured_and_invalid_roles_do_no_metadata_or_launch(self):
		from core.comparator import compare
		for configuration in (None, {}, {'executable': 'bad.cmd', 'arguments': []}):
			with self.subTest(configuration=configuration), patch('core.comparator._capture', return_value=(('file://C:/left', 'file://C:/right'), 'token')), \
				patch('core.comparator._release') as release, patch('core.comparator.resolve') as resolve, \
				patch('core.comparator._load_settings', return_value={'file_comparator': configuration}), \
				patch('core.comparator.os.stat') as metadata, patch('core.comparator.submit_task') as submit, \
				patch('core.comparator.Popen') as launch, patch('core.comparator.show_alert') as alert:
				compare(Mock(), 'file')
				resolve.assert_not_called()
				metadata.assert_not_called()
				submit.assert_not_called()
				launch.assert_not_called()
				self.assertIn('Set file comparator', alert.call_args.args[0])
				release.assert_called_once_with('token')

	def test_settings_snapshot_is_locked_and_independent_before_validation(self):
		from core.comparator import compare
		for role in ('file', 'folder'):
			settings_lock = Lock()
			configuration = {'executable': sys.executable, 'arguments': ['--original']}
			def load_settings():
				self.assertTrue(settings_lock.locked())
				return {role + '_comparator': configuration}
			def copy_settings(value):
				self.assertTrue(settings_lock.locked())
				return deepcopy(value)
			def submit(task):
				self.assertFalse(settings_lock.locked())
				configuration['arguments'].append('--changed')
				self.assertEqual(['--original'], task.configuration['arguments'])
			with self.subTest(role=role), patch('core.comparator._settings_lock', settings_lock), \
				patch('core.comparator._capture', return_value=(('file://C:/left', 'file://C:/right'), 'token')), \
				patch('core.comparator._release') as release, patch('core.comparator._load_settings', side_effect=load_settings), \
				patch('core.comparator.deepcopy', side_effect=copy_settings), \
				patch('core.comparator.submit_task', side_effect=submit) as submitted, patch('core.comparator.show_alert') as alert:
				compare(Mock(), role)
				submitted.assert_called_once()
				alert.assert_not_called()
				release.assert_called_once_with('token')
				self.assertFalse(settings_lock.locked())

	def test_launch_handoff_is_nonblocking_and_cancellation_is_before_handoff(self):
		from core.comparator import _Compare
		from fman import Task
		configuration = {'executable': sys.executable, 'arguments': []}
		paths = ('C:\\left.txt', 'C:\\right.txt')
		with patch('core.comparator.resolve', side_effect=lambda url: url), patch('core.comparator.validate_operands'), patch('core.comparator.Popen') as launch:
			task = _Compare(tuple(as_url(path) for path in paths), configuration, 'file')
			task()
			launch.assert_called_once_with(args=[sys.executable, *paths], shell=False)
			launch.return_value.wait.assert_not_called()
			launch.return_value.poll.assert_not_called()
			launch.reset_mock()
			with patch.object(task, 'check_canceled', side_effect=Task.Canceled), self.assertRaises(Task.Canceled):
				task()
			launch.assert_not_called()

	def test_every_launch_exit_releases_pending_slot(self):
		from core.comparator import compare
		from fman import Task
		configuration = {'executable': sys.executable, 'arguments': []}
		for error in (OSError('Cannot launch'), ValueError('Missing file'), Task.Canceled()):
			with self.subTest(error=type(error)), patch('core.comparator._capture', return_value=(('file://C:/left', 'file://C:/right'), 'token')), \
				patch('core.comparator._release') as release, patch('core.comparator._load_settings', return_value={'file_comparator': configuration}), \
				patch('core.comparator.submit_task', side_effect=error), patch('core.comparator.show_alert') as alert:
				compare(Mock(), 'file')
				release.assert_called_once_with('token')
				if isinstance(error, Task.Canceled):
					alert.assert_not_called()
				else:
					self.assertIn(str(error), alert.call_args.args[0])