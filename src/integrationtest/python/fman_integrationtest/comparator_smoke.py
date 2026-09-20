import json
import os
from pathlib import Path
from subprocess import Popen, list2cmdline
import sys
from tempfile import TemporaryDirectory
from threading import Event, Thread
from time import monotonic
import traceback
from unittest.mock import patch


def exercise(context, root, restart):
	from core import comparator
	from fman import load_json
	from fman.impl.quicksearch import Quicksearch
	from fman.impl.util.qt.thread import run_in_main_thread
	from fman.impl.widgets import Prompt
	from fman.url import as_url
	from PyQt5.QtCore import QTimer
	from PyQt5.QtWidgets import QApplication
	gui = lambda function: run_in_main_thread(function)()
	children, dialog_errors = [], []
	selection = comparator.MANUAL
	arguments = ['-c', 'import json,pathlib,sys,threading;pathlib.Path(sys.argv[1]).write_text(json.dumps(sys.argv[2:]));threading.Event().wait()', str(root / 'received.json')]
	def wait_for(predicate, message):
		ready = Event()
		def connect():
			timer = QTimer(context.main_window)
			timer.setInterval(10)
			def check():
				if predicate():
					timer.stop()
					timer.deleteLater()
					ready.set()
			timer.timeout.connect(check)
			timer.start()
			check()
		gui(connect)
		assert ready.wait(10), message
	def on_dialog(dialog):
		def answer():
			try:
				if isinstance(dialog, Quicksearch):
					dialog._query.setText(selection)
					dialog._on_return_pressed()
				elif isinstance(dialog, Prompt):
					dialog.setTextValue(list2cmdline(arguments))
					dialog.accept()
				else:
					raise AssertionError('Unexpected setup dialog')
			except BaseException as error:
				dialog_errors.append(error)
				dialog.reject()
		QTimer.singleShot(0, answer)
	def launch(**kwargs):
		assert kwargs['shell'] is False
		child = Popen(**kwargs)
		children.append(child)
		return child
	code = 1
	try:
		wait_for(lambda: len(context.window.get_panes()) == 2 and
			all(pane.get_file_under_cursor() for pane in context.window.get_panes()), 'Panes did not load')
		left, right = context.window.get_panes()
		for pane, name in ((left, 'left'), (right, 'right')):
			pane.place_cursor_at(as_url(root / name / 'sample.txt'))
		for identifier, label in (('compare_files', 'Compare files'), ('compare_folders', 'Compare folders'),
			('set_file_comparator', 'Set file comparator'), ('set_folder_comparator', 'Set folder comparator')):
			assert left.get_command_aliases(identifier) == (label,)
		bindings = context.key_bindings.get_sanitized_bindings()
		assert not any(binding.get('command') in ('compare_files', 'compare_folders', 'set_file_comparator', 'set_folder_comparator') for binding in bindings)
		gui(lambda: context.main_window.before_dialog.connect(on_dialog))
		if not restart:
			with patch.object(comparator, 'show_alert') as alert:
				left.run_command('compare_files')
				assert 'Set file comparator' in alert.call_args.args[0]
			with patch('fman.impl.widgets.QFileDialog.getOpenFileName', return_value=(sys.executable, 'Applications (*.exe)')):
				left.run_command('set_file_comparator')
				left.run_command('set_folder_comparator')
		assert not dialog_errors, dialog_errors
		settings = load_json(comparator.SETTINGS)
		assert settings['file_comparator']['arguments'] == arguments
		assert settings['folder_comparator']['arguments'] == arguments
		if restart:
			selection = 'Clear file comparator'
			left.run_command('set_file_comparator')
			settings = load_json(comparator.SETTINGS)
			assert settings['file_comparator'] is None
			assert settings['folder_comparator']['arguments'] == arguments
		with patch.object(comparator, 'Popen', side_effect=launch):
			commands = ('compare_folders',) if restart else ('compare_files', 'compare_folders')
			for command in commands:
				output = root / 'received.json'
				output.unlink(missing_ok=True)
				started = monotonic()
				left.run_command(command)
				elapsed = monotonic() - started
				assert children and children[-1].poll() is None, 'Child should still be running after command returns'
				wait_for(output.exists, 'Child did not receive operands')
				expected = [str(root / name / 'sample.txt') if command == 'compare_files' else str(root / name) for name in ('left', 'right')]
				assert json.loads(output.read_text()) == expected
				print('%s handoff: %.4f s' % (command, elapsed), flush=True)
		assert not comparator._pending
		gui(QApplication.processEvents)
		print('PASS: comparator %s, registration, settings and nonblocking argv handoff' % ('restart/clear' if restart else 'source startup/setup'), flush=True)
		code = 0
	except BaseException:
		traceback.print_exc()
	finally:
		for child in children:
			child.kill()
			child.wait(timeout=5)
		def stop_models():
			models = [pane._widget._model.sourceModel() for pane in context.window.get_panes()]
			for model in models:
				model.shutdown()
			return models
		for model in gui(stop_models):
			model._worker._thread.join(5)
			if model._worker._thread.is_alive():
				code = 1
		gui(lambda: context.app.exit(code))


def run_application(root, restart):
	os.environ['ROYIFILEMANAGER_USER_SETTINGS'] = str(root / 'UserSettings')
	from fman.impl.application_context import get_application_context
	from PyQt5.QtCore import QTimer
	context = get_application_context()
	_ = context.app
	context.session_manager.is_first_run = False
	sys.argv = [sys.argv[0], str(root / 'left'), str(root / 'right')]
	QTimer.singleShot(0, lambda: Thread(target=exercise, args=(context, root, restart), daemon=True).start())
	return context.run()


def main():
	if len(sys.argv) > 1:
		return run_application(Path(sys.argv[1]), '--restart' in sys.argv)
	from subprocess import run
	with TemporaryDirectory(prefix='comparator-smoke-') as temporary:
		root = Path(temporary)
		for name in ('left', 'right'):
			(root / name).mkdir()
			(root / name / 'sample.txt').write_text(name)
		for options in ([], ['--restart']):
			result = run([sys.executable, '-m', 'fman_integrationtest.comparator_smoke', str(root), *options], timeout=45)
			if result.returncode:
				return result.returncode
	return 0


if __name__ == '__main__':
	sys.exit(main())