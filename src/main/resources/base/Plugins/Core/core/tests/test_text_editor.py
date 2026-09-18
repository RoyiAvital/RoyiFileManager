from copy import deepcopy
from core.text_editor import MAX_COMMAND_UNITS, MANUAL, PRESETS, SETTINGS, \
	configure, open_file, parse_arguments, prepare_launch
from fman.impl.plugins.config import Config
from fman.url import as_url
from pathlib import Path
from subprocess import check_output, list2cmdline
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import patch

import json
import sys


class TextEditorArgumentsTest(TestCase):
	def test_every_preset_reaches_child_in_order_for_both_roles(self):
		for name, editor_arguments, viewer_arguments in PRESETS:
			for role, arguments in (('editor', editor_arguments), ('viewer', viewer_arguments)):
				with self.subTest(preset=name, role=role):
					configuration = {'executable': sys.executable, 'arguments': [
						'-c', 'import json,sys;print(json.dumps(sys.argv[1:]))', *arguments]}
					kwargs = prepare_launch(configuration, 'file {name} \u754c.txt')
					self.assertEqual([*arguments, 'file {name} \u754c.txt'],
						json.loads(check_output(**kwargs, text=True)))

	def test_windows_arguments_round_trip_and_child_receives_file_last(self):
		arguments = ['--session', 'C:\\My Files\\session.ini', '', 'a"b',
			'C:\\directory with spaces\\', 'slashes\\\\"quote', '{literal}', '%PATH%', '&',
			'\u754c\u00e9']
		parsed = parse_arguments(list2cmdline(arguments))
		self.assertEqual(arguments, parsed)
		with TemporaryDirectory() as root:
			file_path = str(Path(root, 'file {name} \u754c.txt'))
			Path(file_path).touch()
			configuration = {'executable': sys.executable, 'arguments': [
				'-c', 'import json,sys;print(json.dumps(sys.argv[1:]))', *parsed]}
			before = deepcopy(configuration)
			received = json.loads(check_output(**prepare_launch(configuration, file_path), text=True))
			self.assertEqual([*arguments, file_path], received)
			self.assertEqual(before, configuration)


	def test_empty_arguments(self):
		for text in ('', '  \t'):
			self.assertEqual([], parse_arguments(text))
		self.assertEqual([''], parse_arguments('""'))

	def test_new_configuration_has_no_templates_or_shell(self):
		configuration = {'executable': sys.executable, 'arguments': ['{file}', '{', '%PATH%']}
		self.assertEqual({'args': [sys.executable, '{file}', '{', '%PATH%', 'file {data}.txt'],
			'shell': False}, prepare_launch(configuration, 'file {data}.txt'))

	def test_legacy_options_and_templates_are_preserved(self):
		configuration = {'args': [sys.executable, '--flag', '{file}'],
			'cwd': 'C:\\Tools', 'shell': True, 'creationflags': 0}
		before = deepcopy(configuration)
		self.assertEqual({'args': [sys.executable, '--flag', 'C:\\file {one}.txt'],
			'cwd': 'C:\\Tools', 'shell': True, 'creationflags': 0},
			prepare_launch(configuration, 'C:\\file {one}.txt'))
		self.assertEqual(before, configuration)
		minimal = prepare_launch({'args': [sys.executable, '{file}']}, 'target.txt')
		self.assertEqual({'args': [sys.executable, 'target.txt']}, minimal)

	def test_invalid_configuration(self):
		for configuration in (None, [], {}, {'args': []}, {'args': 'not argv'},
			{'args': [None]}, {'args': [sys.executable, '{unknown}']},
			{'args': [sys.executable, '{']}, {'args': [sys.executable, '\0']},
			{'executable': sys.executable}, {'executable': None, 'arguments': []},
			{'executable': 'missing.exe', 'arguments': []},
			{'executable': sys.executable, 'arguments': [False]},
			{'executable': 'program.cmd', 'arguments': []}):
			with self.subTest(configuration=configuration), self.assertRaises(ValueError):
				prepare_launch(configuration, 'file.txt')
		for text in ('\0', 'x' * (MAX_COMMAND_UNITS + 1), '\U0001f600' * (MAX_COMMAND_UNITS // 2 + 1)):
			with self.assertRaises(ValueError):
				parse_arguments(text)
		with self.assertRaises(ValueError):
			prepare_launch({'executable': sys.executable, 'arguments': []}, 'file\0.txt')
		with self.assertRaises(ValueError):
			prepare_launch({'executable': sys.executable, 'arguments': ['x' * MAX_COMMAND_UNITS]}, 'file.txt')


class TextEditorWizardTest(TestCase):
	def setUp(self):
		self.directory = TemporaryDirectory()
		self.addCleanup(self.directory.cleanup)
		self.config = Config('Windows')
		self.config.add_dir(self.directory.name)
		self.original = {'editor': {'args': [sys.executable, '{file}']},
			'viewer': {'executable': sys.executable, 'arguments': ['--viewer']},
			'unrelated': {'keep': True}}
		self.config.save_json(SETTINGS, deepcopy(self.original))
		self.mocks = {}
		for name in ('show_quicksearch', 'show_file_open_dialog', 'show_prompt',
			'show_status_message', 'show_alert', 'Popen', 'load_json', 'save_json', 'resolve'):
			patcher = patch('core.text_editor.' + name)
			self.mocks[name] = patcher.start()
			self.addCleanup(patcher.stop)
		self.mocks['load_json'].side_effect = self.config.load_json
		self.mocks['save_json'].side_effect = self.config.save_json
		self.mocks['resolve'].side_effect = lambda url: url
		self.mocks['show_quicksearch'].return_value = ('', MANUAL)
		self.mocks['show_file_open_dialog'].return_value = sys.executable
		self.mocks['show_prompt'].return_value = ('', True)
		self.target = str(Path(self.directory.name, 'target {data}.txt'))
		Path(self.target).touch()

	def assert_persisted(self, expected):
		reloaded = Config('Windows')
		reloaded.add_dir(self.directory.name)
		self.assertEqual(expected, reloaded.load_json(SETTINGS))

	def test_all_presets_for_both_independent_roles(self):
		self.assertEqual(['Notepad++', 'CudaText', 'Notepad 4'], [preset[0] for preset in PRESETS])
		self.assertIn(('Notepad++', ('-multiInst', '-nosession', '-notabbar'),
			('-multiInst', '-nosession', '-notabbar', '-ro')), PRESETS)
		self.assertIn(('Notepad 4', ('-ns',), ('-ro', '-ns')), PRESETS)
		for role in ('editor', 'viewer'):
			for name, editor_args, viewer_args in PRESETS:
				with self.subTest(role=role, preset=name):
					self.config.save_json(SETTINGS, deepcopy(self.original))
					self.mocks['show_quicksearch'].return_value = ('', name)
					result = configure(role)
					arguments = list(editor_args if role == 'editor' else viewer_args)
					self.assertEqual({'executable': sys.executable, 'arguments': arguments}, result)
					self.assert_persisted(dict(self.original, **{role: result}))
					self.assertEqual([sys.executable, *arguments, self.target],
						prepare_launch(result, self.target)['args'])
		self.mocks['show_prompt'].assert_not_called()
		self.mocks['Popen'].assert_not_called()
		get_items = self.mocks['show_quicksearch'].call_args.args[0]
		self.assertEqual([preset[0] for preset in PRESETS] + [MANUAL, 'Clear viewer'],
			[item.value for item in get_items('')])
		self.assertEqual(['CudaText'], [item.value for item in get_items('cuda')])

	def test_clear_role_is_last_and_persists_without_other_dialogs(self):
		for role in ('editor', 'viewer'):
			with self.subTest(role=role):
				self.config.save_json(SETTINGS, deepcopy(self.original))
				self.mocks['show_quicksearch'].return_value = ('', 'Clear %s' % role)
				self.assertIsNone(configure(role))
				get_items = self.mocks['show_quicksearch'].call_args.args[0]
				self.assertEqual([preset[0] for preset in PRESETS] + [MANUAL, 'Clear %s' % role],
					[item.value for item in get_items('')])
				self.assert_persisted(dict(self.original, **{role: None}))
				self.mocks['show_status_message'].assert_called_with(
					'Text %s cleared.' % role, timeout_secs=3)
				self.mocks['show_alert'].reset_mock()
				open_file(as_url(self.target), role)
				self.mocks['show_alert'].assert_called_once_with(
					'No text %s was set. Use "Set text %s" in Command Center to define a text %s.' % (role, role, role))
		for name in ('show_file_open_dialog', 'show_prompt', 'Popen'):
			self.mocks[name].assert_not_called()

	def test_clear_masks_inherited_settings_after_reload(self):
		base = str(Path(self.directory.name, 'base'))
		user = str(Path(self.directory.name, 'user'))
		config = Config('Windows')
		config.add_dir(base)
		config.save_json(SETTINGS, deepcopy(self.original))
		config.add_dir(user)
		self.mocks['load_json'].side_effect = config.load_json
		self.mocks['save_json'].side_effect = config.save_json
		for role in ('editor', 'viewer'):
			with self.subTest(role=role):
				config.save_json(SETTINGS, deepcopy(self.original))
				self.mocks['show_quicksearch'].return_value = ('', 'Clear %s' % role)
				configure(role)
				reloaded = Config('Windows')
				reloaded.add_dir(base)
				self.assertEqual(self.original, reloaded.load_json(SETTINGS))
				reloaded.add_dir(user)
				self.assertEqual(dict(self.original, **{role: None}), reloaded.load_json(SETTINGS))
		self.mocks['show_alert'].assert_not_called()

	def test_clear_save_failure_preserves_settings_and_reports_error(self):
		cached = self.config.load_json(SETTINGS)
		for role in ('editor', 'viewer'):
			for error in (OSError('Read-only settings directory'), ValueError('Cannot save')):
				with self.subTest(role=role, error=error):
					self.mocks['show_quicksearch'].return_value = ('', 'Clear %s' % role)
					self.mocks['save_json'].side_effect = error
					configure(role)
					self.assertEqual(self.original, cached)
					self.assertEqual(self.original, self.config.load_json(SETTINGS))
					self.assert_persisted(self.original)
					self.mocks['show_alert'].assert_called_with('Could not clear text %s: %s' % (role, error))
		for name in ('show_status_message', 'show_file_open_dialog', 'show_prompt', 'Popen'):
			self.mocks[name].assert_not_called()

	def test_clear_already_unset_role_does_not_save(self):
		for role in ('editor', 'viewer'):
			for settings in ({'unrelated': 123}, {'unrelated': 123, role: None}):
				with self.subTest(role=role, settings=settings):
					self.config.save_json(SETTINGS, settings)
					self.mocks['show_quicksearch'].return_value = ('', 'Clear %s' % role)
					configure(role)
					self.assert_persisted(settings)
		self.mocks['save_json'].assert_not_called()
		self.mocks['show_alert'].assert_not_called()
		self.mocks['Popen'].assert_not_called()

	def test_manual_prefill_and_literal_arguments(self):
		arguments = ['--session', 'C:\\My Files\\session.ini', '', '{file}']
		self.mocks['show_prompt'].return_value = (list2cmdline(arguments), True)
		result = configure('viewer')
		self.assertEqual(arguments, result['arguments'])
		self.mocks['show_file_open_dialog'].assert_called_once_with(
			'Set text viewer', sys.executable, 'Applications (*.exe)')
		self.mocks['show_prompt'].assert_called_once_with('Arguments:', '--viewer')
		self.assert_persisted(dict(self.original, viewer=result))

	def test_other_settings_changed_during_dialog_are_preserved(self):
		def change_settings(*args):
			self.config.load_json(SETTINGS)['unrelated'] = 'changed during wizard'
			return '', True
		self.mocks['show_prompt'].side_effect = change_settings
		result = configure('editor')
		self.assert_persisted(dict(self.original, editor=result, unrelated='changed during wizard'))

	def test_cancellation_at_each_step_does_not_save_or_launch(self):
		for name, value in (('show_quicksearch', None), ('show_quicksearch', ('no match', None)),
			('show_file_open_dialog', ''),
			('show_prompt', ('ignored', False))):
			with self.subTest(step=name):
				previous = self.mocks[name].return_value
				self.mocks[name].return_value = value
				self.assertIsNone(configure('editor'))
				self.mocks[name].return_value = previous
				self.assert_persisted(self.original)
		self.mocks['save_json'].assert_not_called()
		self.mocks['Popen'].assert_not_called()

	def test_invalid_executable_and_save_failure_leave_cache_unchanged(self):
		cached = self.config.load_json(SETTINGS)
		self.mocks['show_file_open_dialog'].return_value = self.directory.name
		self.assertIsNone(configure('editor'))
		self.mocks['save_json'].assert_not_called()
		self.mocks['show_file_open_dialog'].return_value = sys.executable
		self.mocks['save_json'].side_effect = OSError('Read-only settings directory')
		self.assertIsNone(configure('editor'))
		self.assertEqual(self.original, cached)
		self.assertEqual(self.original, self.config.load_json(SETTINGS))
		self.assert_persisted(self.original)
		self.mocks['show_status_message'].assert_not_called()
		self.assertIn('Read-only settings directory', self.mocks['show_alert'].call_args.args[0])

	def test_target_validation_precedes_setup(self):
		for url in (None, 'archive://file', as_url(self.directory.name),
			as_url(str(Path(self.directory.name, 'missing.txt')))):
			open_file(url, 'viewer')
		self.mocks['load_json'].assert_not_called()
		self.mocks['show_quicksearch'].assert_not_called()
		self.mocks['Popen'].assert_not_called()

	def test_unset_role_only_shows_command_center_message(self):
		for role in ('viewer', 'editor'):
			for empty in (None, {}):
				with self.subTest(role=role, configuration=empty):
					settings = deepcopy(self.original)
					if empty is None:
						settings.pop(role)
					else:
						settings[role] = empty
					self.config.save_json(SETTINGS, settings)
					self.mocks['show_alert'].reset_mock()
					open_file(as_url(self.target), role)
					self.mocks['show_alert'].assert_called_once_with(
						'No text %s was set. Use "Set text %s" in Command Center to define a text %s.' % (role, role, role))
					self.assert_persisted(settings)
		for name in ('show_quicksearch', 'show_file_open_dialog', 'show_prompt', 'save_json', 'Popen'):
			self.mocks[name].assert_not_called()

	def test_invalid_role_reports_error_without_setup_or_launch(self):
		for role in ('viewer', 'editor'):
			settings = deepcopy(self.original)
			settings[role] = {'executable': 'missing.exe', 'arguments': []}
			self.config.save_json(SETTINGS, settings)
			self.mocks['show_alert'].reset_mock()
			open_file(as_url(self.target), role)
			self.mocks['show_alert'].assert_called_once()
			self.assertIn('The configured executable was not found.', self.mocks['show_alert'].call_args.args[0])
			self.assertIn('"Set text %s" in Command Center' % role, self.mocks['show_alert'].call_args.args[0])
			self.assert_persisted(settings)
		for name in ('show_quicksearch', 'show_file_open_dialog', 'show_prompt', 'save_json', 'Popen'):
			self.mocks[name].assert_not_called()

	def test_configured_roles_launch_without_wizard_or_rewriting(self):
		open_file(as_url(self.target), 'editor')
		self.mocks['Popen'].assert_called_once_with(args=[sys.executable, self.target])
		self.mocks['Popen'].reset_mock()
		open_file(as_url(self.target), 'viewer')
		self.mocks['Popen'].assert_called_once_with(args=[sys.executable, '--viewer', self.target], shell=False)
		self.mocks['show_quicksearch'].assert_not_called()
		self.mocks['save_json'].assert_not_called()
		self.assert_persisted(self.original)

	def test_launch_and_resolution_errors_are_reported(self):
		for error in (OSError('Cannot launch'), ValueError('bad kwargs'), TypeError('bad option')):
			self.mocks['Popen'].side_effect = error
			open_file(as_url(self.target), 'editor')
			self.assertIn('"Set text editor" in Command Center', self.mocks['show_alert'].call_args.args[0])
		self.mocks['resolve'].side_effect = OSError('Cannot resolve')
		open_file(as_url(self.target), 'viewer')
		self.assertIn('Cannot resolve', self.mocks['show_alert'].call_args.args[0])