from collections.abc import Mapping
from core.util import strformat_dict_values
from fman import QuicksearchItem, load_json, save_json, show_alert, \
	show_file_open_dialog, show_prompt, show_quicksearch, show_status_message
from fman.fs import resolve
from fman.url import as_human_readable, splitscheme
from subprocess import Popen, list2cmdline

import os


PRESETS = (
	('Notepad++', ('-multiInst', '-nosession', '-notabbar'),
		('-multiInst', '-nosession', '-notabbar', '-ro')),
	('CudaText', ('-n', '-ns', '-nh'), ('-r', '-n', '-ns', '-nh')),
	('Notepad 4', ('-ns',), ('-ro', '-ns')),
)
MAX_COMMAND_UNITS = 32766
SETTINGS = 'Core Settings.json'
MANUAL = 'Manual configuration'


def _check_text(value):
	if not isinstance(value, str) or '\0' in value:
		raise ValueError('Executable and arguments must be text without NUL characters.')
	if len(value.encode('utf-16-le')) // 2 > MAX_COMMAND_UNITS:
		raise ValueError('The command is too long.')


def parse_arguments(text):
	_check_text(text)
	if not text.strip():
		return []
	import ctypes
	from ctypes import wintypes
	command = 'program.exe ' + text
	_check_text(command)
	shell = ctypes.WinDLL('shell32', use_last_error=True)
	kernel = ctypes.WinDLL('kernel32', use_last_error=True)
	shell.CommandLineToArgvW.argtypes = (wintypes.LPCWSTR, ctypes.POINTER(ctypes.c_int))
	shell.CommandLineToArgvW.restype = ctypes.POINTER(wintypes.LPWSTR)
	kernel.LocalFree.argtypes = (wintypes.HLOCAL,)
	kernel.LocalFree.restype = wintypes.HLOCAL
	count = ctypes.c_int()
	arguments = shell.CommandLineToArgvW(command, ctypes.byref(count))
	if not arguments:
		raise ctypes.WinError(ctypes.get_last_error())
	try:
		return list(arguments[1:count.value])
	finally:
		kernel.LocalFree(ctypes.cast(arguments, wintypes.HLOCAL))


def _check_argv(arguments):
	if not isinstance(arguments, list) or not arguments:
		raise ValueError('The command must contain an executable and an argument list.')
	for argument in arguments:
		_check_text(argument)
	_check_text(list2cmdline(arguments))
	if not arguments[0] or not os.path.isfile(arguments[0]):
		raise ValueError('The configured executable was not found.')


def prepare_launch(configuration, file_path):
	_check_text(file_path)
	if not isinstance(configuration, Mapping):
		raise ValueError('No valid program is configured.')
	if 'executable' in configuration:
		executable = configuration['executable']
		arguments = configuration.get('arguments')
		_check_text(executable)
		if not isinstance(arguments, list):
			raise ValueError('Arguments must be a list of strings.')
		if os.path.splitext(executable)[1].lower() != '.exe':
			raise ValueError('Choose an .exe file.')
		result = {'args': [executable, *arguments, file_path], 'shell': False}
	else:
		try:
			result = strformat_dict_values(configuration, {'file': file_path})
		except (KeyError, IndexError, AttributeError, TypeError, ValueError) as error:
			raise ValueError('Invalid legacy program template: %s' % error) from error
	_check_argv(result.get('args'))
	return result


def _load_settings():
	settings = load_json(SETTINGS, default={})
	if not isinstance(settings, dict):
		raise ValueError('Core Settings.json must contain an object.')
	return settings


def _prefill(configuration):
	if not isinstance(configuration, Mapping):
		return '', ''
	executable = configuration.get('executable', '')
	arguments = configuration.get('arguments', [])
	if 'executable' not in configuration:
		legacy_args = configuration.get('args')
		if isinstance(legacy_args, list) and legacy_args:
			executable = legacy_args[0]
			arguments = [argument for argument in legacy_args[1:]
				if isinstance(argument, str) and '{file}' not in argument]
	if not isinstance(executable, str):
		executable = ''
	if not isinstance(arguments, list) or any(not isinstance(arg, str) for arg in arguments):
		arguments = []
	return executable, list2cmdline(arguments)


def configure(role):
	action = 'set'
	try:
		executable, argument_line = _prefill(_load_settings().get(role))
		clear_option = 'Clear %s' % role
		options = [preset[0] for preset in PRESETS] + [MANUAL, clear_option]
		choice = show_quicksearch(lambda query: (
			QuicksearchItem(option) for option in options
			if query.casefold() in option.casefold()
		))
		if not choice or choice[1] not in options:
			return
		selection = choice[1]
		if selection == clear_option:
			action = 'clear'
			settings = dict(_load_settings())
			if settings.get(role) is not None:
				settings[role] = None
				save_json(SETTINGS, settings)
			show_status_message('Text %s cleared.' % role, timeout_secs=3)
			return
		executable = show_file_open_dialog(
			'Set text %s' % role, executable, 'Applications (*.exe)'
		)
		if not executable:
			return
		if selection == MANUAL:
			argument_line, accepted = show_prompt('Arguments:', argument_line)
			if not accepted:
				return
			arguments = parse_arguments(argument_line)
		else:
			preset = next(preset for preset in PRESETS if preset[0] == selection)
			arguments = list(preset[1 if role == 'editor' else 2])
		configuration = {'executable': executable, 'arguments': arguments}
		prepare_launch(configuration, '')
		settings = dict(_load_settings())
		settings[role] = configuration
		save_json(SETTINGS, settings)
	except (OSError, ValueError, TypeError) as error:
		show_alert('Could not %s text %s: %s' % (action, role, error))
		return
	show_status_message('Text %s saved.' % role, timeout_secs=3)
	return configuration


def open_file(url, role):
	if not url:
		show_alert('No file is selected!')
		return
	try:
		url = resolve(url)
		scheme = splitscheme(url)[0]
		if scheme != 'file://':
			raise ValueError('Opening %s files in a text %s is not supported.' % (scheme, role))
		file_path = as_human_readable(url)
		if not os.path.isfile(file_path):
			raise ValueError('Choose an existing file, not a folder.')
		configuration = _load_settings().get(role)
		if not configuration:
			show_alert('No text %s was set. Use "Set text %s" in Command Center '
				'to define a text %s.' % (role, role, role))
			return
		kwargs = prepare_launch(configuration, file_path)
		Popen(**kwargs)
	except (OSError, ValueError, TypeError) as error:
		show_alert('Could not open file in text %s: %s\n'
			'Use "Set text %s" in Command Center to check its configuration.' % (role, error, role))