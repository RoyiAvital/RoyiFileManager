from core.util import strformat_dict_values
from fman import load_json, show_alert
from subprocess import Popen

def get_popen_kwargs_for_opening(files, with_):
	args = [with_] + files
	return {'args': args}

def open_terminal_in_directory(dir_path):
	settings = load_json('Core Settings.json', default={})
	app = settings.get('terminal', {})
	if app:
		_run_app_from_setting(app, dir_path)
	else:
		show_alert(
			'Could not determine the Popen(...) arguments for opening the '
			'terminal. Please configure the "terminal" dictionary in '
			'"Core Settings.json".'
		)

def open_native_file_manager(dir_path):
	settings = load_json('Core Settings.json', default={})
	app = settings.get('native_file_manager', {})
	if app:
		_run_app_from_setting(app, dir_path)
	else:
		show_alert(
			'Could not determine the Popen(...) arguments for opening the '
			'native file manager. Please configure the '
			'"native_file_manager" dictionary in "Core Settings.json".'
		)

def _run_app_from_setting(app, curr_dir):
	popen_kwargs = strformat_dict_values(app, {'curr_dir': curr_dir})
	Popen(**popen_kwargs)
