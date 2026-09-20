from collections.abc import Mapping
from copy import deepcopy
from dataclasses import dataclass
from core.external_program import _check_argv, _check_text, parse_arguments
from fman import QuicksearchItem, Task, load_json, save_json, show_alert, show_file_open_dialog, show_prompt, show_quicksearch, show_status_message, submit_task
from fman.fs import resolve
from fman.impl.util.qt.thread import run_in_main_thread
from fman.url import as_human_readable, splitscheme
from subprocess import Popen, list2cmdline
from threading import Lock

import os
import stat


SETTINGS = 'Core Settings.json'
MANUAL = 'Manual configuration'
PRESETS = (
	('Meld', 'Meld.exe', (), ()),
	('Beyond Compare', 'BCompare.exe', ('/solo',), ('/solo',)),
	('WinMerge', 'WinMergeU.exe', ('/s-', '/u'), ('/s-', '/u', '/r')),
	('SmartSynchronize', 'smartsynchronize.exe', (), ()),
)
_settings_lock = Lock()
_pending = {}


def _load_settings():
	settings = load_json(SETTINGS, default={})
	if not isinstance(settings, dict):
		raise ValueError('Core Settings.json must contain an object.')
	return settings


def configure(role):
	key = role + '_comparator'
	action = 'set'
	try:
		with _settings_lock:
			initial = deepcopy(_load_settings().get(key))
		executable, arguments = '', []
		if isinstance(initial, Mapping):
			executable = initial.get('executable', '')
			arguments = initial.get('arguments', [])
		if not isinstance(executable, str):
			executable = ''
		if not isinstance(arguments, list) or any(not isinstance(argument, str) for argument in arguments):
			arguments = []
		clear = 'Clear %s comparator' % role
		options = [preset[0] for preset in PRESETS] + [MANUAL, clear]
		choice = show_quicksearch(lambda query: (QuicksearchItem(option) for option in options
			if query.casefold() in option.casefold()))
		if not choice or choice[1] not in options:
			return
		selection = choice[1]
		configuration = None
		if selection == clear:
			action = 'clear'
		else:
			preset = next((preset for preset in PRESETS if preset[0] == selection), None)
			filter_text = '%s (%s);;Applications (*.exe)' % preset[:2] if preset else 'Applications (*.exe)'
			executable = show_file_open_dialog('Set %s comparator' % role, executable, filter_text)
			if not executable:
				return
			if preset:
				arguments = list(preset[2 if role == 'file' else 3])
			else:
				line, accepted = show_prompt('Arguments:', list2cmdline(arguments))
				if not accepted:
					return
				arguments = parse_arguments(line)
			configuration = {'executable': executable, 'arguments': arguments}
			_check_argv(configuration_args(configuration))
		with _settings_lock:
			settings = dict(_load_settings())
			if settings.get(key) != initial:
				raise ValueError('This comparator changed while setup was open. Retry setup.')
			if configuration is not None or settings.get(key) is not None:
				settings[key] = configuration
				save_json(SETTINGS, settings)
	except (OSError, ValueError, TypeError) as error:
		show_alert('Could not %s %s comparator: %s' % (action, role, error))
		return
	show_status_message('%s comparator %s.' % (role.capitalize(), 'cleared' if configuration is None else 'saved'), timeout_secs=3)
	return configuration


@dataclass(frozen=True)
class PaneSnapshot:
	path: str
	selected: tuple = ()
	cursor: str | None = None


def select_operands(role, panes, active):
	if role not in ('file', 'folder'):
		raise ValueError('Unknown comparator role.')
	if not 0 <= active < len(panes):
		raise ValueError('The invoking pane is no longer available.')
	if role == 'file':
		selected = panes[active].selected
		if len(selected) > 2:
			raise ValueError('Mark at most two files in the active pane.')
		if len(selected) == 2:
			return tuple(sorted(selected, key=lambda url: (url.casefold(), url))), (active,)
	if len(panes) != 2:
		raise ValueError('This comparison requires exactly two panes.')
	operands = []
	for label, pane in zip(('left', 'right'), panes):
		if role == 'folder':
			candidate = pane.path
		else:
			if len(pane.selected) > 1:
				raise ValueError('Mark at most one file in the %s pane for a cross-pane comparison.' % label)
			candidate = pane.selected[0] if pane.selected else pane.cursor
		if not candidate:
			raise ValueError('Choose a %s in the %s pane.' % (role, label))
		operands.append(candidate)
	return tuple(operands), (0, 1)


def native_paths(urls, check=lambda: None):
	paths = []
	for url in urls:
		check()
		_check_text(url)
		resolved = resolve(url)
		check()
		if splitscheme(resolved)[0] != 'file://':
			raise ValueError('Only local filesystem files and folders can be compared.')
		path = as_human_readable(resolved)
		_check_text(path)
		if not os.path.isabs(path):
			raise ValueError('Comparison paths must be absolute.')
		paths.append(path)
	return tuple(paths)


def configuration_args(configuration):
	if not isinstance(configuration, Mapping) or set(configuration) != {'executable', 'arguments'}:
		raise ValueError('Configure an executable and an argument list; legacy shell options are not supported.')
	executable, arguments = configuration['executable'], configuration['arguments']
	_check_text(executable)
	if not os.path.isabs(executable) or os.path.splitext(executable)[1].lower() != '.exe':
		raise ValueError('Choose an absolute .exe path.')
	if not isinstance(arguments, list):
		raise ValueError('Arguments must be a list of strings.')
	for argument in arguments:
		_check_text(argument)
	return [executable, *arguments]


def prepare_launch(configuration, paths):
	if len(paths) != 2:
		raise ValueError('Exactly two comparison paths are required.')
	for path in paths:
		_check_text(path)
		if not os.path.isabs(path):
			raise ValueError('Comparison paths must be absolute.')
	arguments = configuration_args(configuration) + list(paths)
	_check_argv(arguments)
	return {'args': arguments, 'shell': False}


def validate_operands(paths, role, check):
	identities = []
	for label, path in zip(('Left', 'Right'), paths):
		check()
		try:
			info = os.stat(path)
		except OSError as error:
			raise ValueError('%s %s is missing or inaccessible: %s' % (label, role, error)) from error
		check()
		valid = stat.S_ISDIR(info.st_mode) if role == 'folder' else stat.S_ISREG(info.st_mode)
		if not valid:
			raise ValueError('%s operand must be an existing %s.' % (label, role))
		if not info.st_ino:
			raise ValueError('Cannot determine the identity of the %s %s.' % (label.lower(), role))
		identities.append(info)
	if os.path.samestat(*identities):
		raise ValueError('Choose two different filesystem objects, not aliases of the same %s.' % role)


@run_in_main_thread
def _capture(pane, role):
	window = pane.window
	if window in _pending:
		raise ValueError('Another comparison is still validating or stopping.')
	panes = tuple(window.get_panes())
	if pane not in panes:
		raise ValueError('The invoking pane is no longer available.')
	selected = tuple(pane.get_selected_files()) if role == 'file' else ()
	if role == 'file' and len(selected) >= 2:
		snapshots = (PaneSnapshot(pane.get_path(), selected),)
		active = 0
	else:
		if len(panes) != 2:
			raise ValueError('This comparison requires exactly two panes.')
		snapshots = []
		for current in panes:
			marks = tuple(current.get_selected_files()) if role == 'file' else ()
			cursor = current.get_file_under_cursor() if role == 'file' and not marks else None
			snapshots.append(PaneSnapshot(current.get_path(), marks, cursor))
		active = panes.index(pane)
	urls, involved = select_operands(role, snapshots, active)
	token = object()
	_pending[window] = token
	return urls, token


@run_in_main_thread
def _release(token):
	for window, pending in tuple(_pending.items()):
		if pending is token:
			del _pending[window]
			break


class _Compare(Task):
	def __init__(self, urls, configuration, role):
		super().__init__('Validate %s comparison' % role)
		self.urls, self.configuration, self.role = urls, configuration, role

	def __call__(self):
		paths = native_paths(self.urls, self.check_canceled)
		validate_operands(paths, self.role, self.check_canceled)
		self.check_canceled()
		kwargs = prepare_launch(self.configuration, paths)
		self.check_canceled()
		Popen(**kwargs)


def compare(pane, role):
	token = None
	try:
		urls, token = _capture(pane, role)
		for url in urls:
			_check_text(url)
			splitscheme(url)
		with _settings_lock:
			configuration = deepcopy(_load_settings().get(role + '_comparator'))
		if configuration is None:
			show_alert('No %s comparator was set. Use "Set %s comparator" in Command Center.' % (role, role))
			return
		configuration_args(configuration)
		submit_task(_Compare(urls, configuration, role))
	except Task.Canceled:
		pass
	except (OSError, ValueError, TypeError, RuntimeError) as error:
		show_alert('Could not compare %ss: %s\nUse "Set %s comparator" in Command Center to check its configuration.' % (role, error, role))
	finally:
		if token is not None:
			_release(token)