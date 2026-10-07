"""Real Ctrl+A/F5 copy measurements using verified, disposable destinations."""

import hashlib
import json
import math
import os
from pathlib import Path
import shutil
import sys
from tempfile import TemporaryDirectory
from threading import Event, Thread
from time import perf_counter
import traceback


def file_paths(directory):
	result = {}
	for root, folders, files in os.walk(directory, followlinks=False):
		for name in folders:
			path = Path(root, name)
			if path.is_symlink() or path.is_junction():
				raise ValueError('Copy fixture directory links are forbidden')
		for name in files:
			path = Path(root, name)
			result[path.relative_to(directory).as_posix()] = path
	return result


def verify_files(directory, expected, size):
	paths = file_paths(directory)
	if paths.keys() != expected.keys():
		raise ValueError('Copy file count or names differ')
	for name, path in paths.items():
		metadata = path.lstat()
		if path.is_symlink() or path.is_junction() or not path.is_file() or metadata.st_nlink != 1:
			raise ValueError('Copy fixture must contain ordinary files')
		if metadata.st_size != size or hashlib.sha256(path.read_bytes()).hexdigest() != expected[name]:
			raise ValueError('Copy contents differ: ' + path.name)
	expected_directories = {Path('.')}
	for name in expected:
		expected_directories.update(Path(name).parents)
	actual_directories = {Path(root).relative_to(directory) for root, folders, files in os.walk(directory)}
	if expected_directories != actual_directories:
		raise ValueError('Copy directory structure differs')


def validate_result(result, count, size, selected_count=None):
	if result.get('errors') or result.get('settings_isolated') is not True or result.get('verified') is not True:
		raise ValueError('Copy workload failed verification')
	samples = result.get('samples', [])
	if len(samples) != 2 or [sample.get('action_id') for sample in samples] != ['copy.selection', 'copy.transfer']:
		raise ValueError('Incomplete copy samples')
	selection, transfer = samples
	if selection.get('selected_count') != (count if selected_count is None else selected_count) or transfer.get('copied_count') != count or transfer.get('bytes_copied') != count * size:
		raise ValueError('Copy selection or payload count differs')
	for sample, fields in ((selection, ('paint_ms', 'input_ready_ms', 'readback_ms')),
			(transfer, ('wall_ms', 'first_file_ms', 'preparation_ms', 'prompt_ms', 'throughput_mib_s', 'queued_task_count'))):
		for field in fields:
			value = sample.get(field)
			if type(value) not in (int, float) or not math.isfinite(value) or value < 0:
				raise ValueError('Invalid copy metric: ' + field)
	if selection['input_ready_ms'] < selection['paint_ms']:
		raise ValueError('Selection input-ready must include the selection paint interval')
	if not 0 < transfer['first_file_ms'] <= transfer['wall_ms'] or transfer['queued_task_count'] < 1:
		raise ValueError('Invalid copy timing order')
	return result


def child(directory, viewport, count, size, scratch=None):
	directory = Path(directory).resolve(strict=True)
	expected = {name: hashlib.sha256(path.read_bytes()).hexdigest() for name, path in file_paths(directory).items()}
	top_level = {name.split('/')[0] for name in expected}
	row_count = len(top_level)
	expected_directories = {parent.as_posix() for name in expected for parent in Path(name).parents if parent != Path('.')}
	if len(expected) != count:
		raise ValueError('Copy fixture count differs from catalog')
	verify_files(directory, expected, size)
	if shutil.disk_usage(directory).free < count * size + 64 * 1024**2:
		raise OSError('Insufficient space for copy benchmark destination')
	with TemporaryDirectory(prefix='copy-benchmark-', dir=scratch) as temporary:
		root = Path(temporary)
		destination, settings = root / 'destination', root / 'UserSettings'
		destination.mkdir()
		os.environ['ROYIFILEMANAGER_USER_SETTINGS'] = str(settings)
		import core.commands as commands
		from core.fileoperations import CopyFiles
		from fman import DATA_DIRECTORY
		from fman.impl.application_context import get_application_context
		from fman.impl.util.qt.thread import run_in_main_thread
		from fman.impl.view import FileListView
		from fman.impl.widgets import ProgressDialog
		from fman.url import as_url
		from PyQt5.QtCore import QTimer, Qt
		from PyQt5.QtTest import QTest
		from PyQt5.QtWidgets import QApplication, QInputDialog, QMessageBox
		import win32api
		import win32process
		if Path(DATA_DIRECTORY).resolve() != settings.resolve():
			raise RuntimeError('Copy benchmark settings are not isolated')
		context = get_application_context()
		_ = context.app
		context.session_manager.is_first_run = False
		sys.argv = [sys.argv[0], str(directory), str(destination)]
		selection = dict(action_id='copy.selection', row_count=row_count, selected_count=0)
		transfer = dict(action_id='copy.transfer', copied_count=0, bytes_copied=0,
			progress_visible_ms=0, progress_shown_count=0)
		state, errors, samples, timers = {}, [], [], []
		finished, painted, moved = Event(), Event(), Event()
		committed = set()
		original_paint, original_gather, original_copy = FileListView.paintEvent, CopyFiles._gather_files, commands.Copy.__call__
		original_show = ProgressDialog.showEvent
		gui = lambda callback: run_in_main_thread(callback)()
		memory = lambda: win32process.GetProcessMemoryInfo(win32api.GetCurrentProcess())['WorkingSetSize'] / 2**20
		peak_memory = lambda: win32process.GetProcessMemoryInfo(win32api.GetCurrentProcess())['PeakWorkingSetSize'] / 2**20

		def paint(view, event):
			original_paint(view, event)
			if view is state.get('view') and 'selection_started' in state:
				if not painted.is_set() and view.selectionModel().hasSelection():
					selection['paint_ms'] = (perf_counter() - state['selection_started']) * 1000
					painted.set()
				if state.get('followup') and not moved.is_set() and view.currentIndex().row() == state['cursor'] + 1:
					selection['input_ready_ms'] = (perf_counter() - state['selection_started']) * 1000
					moved.set()

		def gather(operation):
			started, before = perf_counter(), memory()
			peak_before = peak_memory()
			result = original_gather(operation)
			transfer.update(preparation_ms=(perf_counter() - started) * 1000,
				queued_task_count=len(operation._tasks), preparation_memory_mib=max(0, memory() - before),
				working_set_before_mib=before, working_set_mib=memory(),
				peak_working_set_before_mib=peak_before, peak_working_set_mib=peak_memory())
			transfer['estimated_bytes_per_task'] = transfer['preparation_memory_mib'] * 2**20 / max(1, len(operation._tasks))
			transfer['estimated_200000_tasks_mib'] = transfer['estimated_bytes_per_task'] * 200000 / 2**20
			return result

		def copy(command, *args, **kwargs):
			try:
				return original_copy(command, *args, **kwargs)
			except BaseException:
				errors.append(traceback.format_exc())
			finally:
				if 'confirmed' in state:
					transfer['wall_ms'] = (perf_counter() - state['confirmed']) * 1000
				finished.set()

		def progress_show(dialog, event):
			original_show(dialog, event)
			if 'confirmed' in state and not transfer['progress_shown_count']:
				transfer.update(progress_visible_ms=(perf_counter() - state['confirmed']) * 1000, progress_shown_count=1)

		def before_dialog(dialog):
			if isinstance(dialog, QInputDialog) and 'f5_started' in state and 'confirmed' not in state:
				transfer['prompt_ms'] = (perf_counter() - state['f5_started']) * 1000
				if dialog.textValue() != str(destination):
					errors.append('Copy prompt proposed the wrong destination')
					dialog.reject()
					return
				def accept():
					state['confirmed'] = perf_counter()
					dialog.accept()
				QTimer.singleShot(0, accept)
			else:
				errors.append('Unexpected benchmark dialog: ' + type(dialog).__name__)
				QTimer.singleShot(0, dialog.reject)

		def added(url):
			if url.startswith(as_url(destination) + '/'):
				name = url[len(as_url(destination)) + 1:]
				if name in expected_directories:
					return
				if name not in expected or name in committed:
					errors.append('Unexpected or duplicate copy notification')
				committed.add(name)
				transfer.setdefault('first_file_ms', (perf_counter() - state['confirmed']) * 1000)

		def wait_for(predicate, label, timeout=90):
			ready = Event()
			def install():
				timer = QTimer(context.main_window)
				timers.append(timer)
				def tick():
					try:
						if predicate():
							timer.stop()
							ready.set()
					except BaseException:
						errors.append(traceback.format_exc())
						timer.stop()
						ready.set()
				timer.timeout.connect(tick)
				timer.start(10)
			gui(install)
			if not ready.wait(timeout):
				raise TimeoutError(label)
			if errors:
				raise RuntimeError('\n'.join(errors))

		def exercise():
			try:
				def loaded():
					panes = context.window.get_panes()
					return (len(panes) == 2 and panes[0].get_path() == as_url(directory) and
						panes[0]._widget._model.rowCount() == row_count and panes[1].get_path() == as_url(destination))
				wait_for(loaded, 'Copy fixture did not load')
				pane, opposite = context.window.get_panes()
				view = pane._widget._file_view
				state['view'] = view
				def prepare_selection():
					context.main_window.resize(*viewport)
					context.main_window.set_extended_status_bar(dict(mode='disabled', max_entries=5000, size_divisor=1024))
					pane.focus()
					pane.clear_selection()
					view.setCurrentIndex(view.model().index(row_count // 2, 0))
					state['cursor'] = view.currentIndex().row()
					view.viewport().repaint()
					state['selection_started'] = perf_counter()
					QTest.keyClick(view, Qt.Key_A, Qt.ControlModifier)
				gui(prepare_selection)
				if not painted.wait(30):
					raise TimeoutError('Select All did not paint')
				def followup():
					state['followup'] = True
					QTest.keyClick(view, Qt.Key_Down)
				gui(followup)
				if not moved.wait(10):
					raise TimeoutError('Selection input did not respond')
				started = perf_counter()
				selected = pane.get_selected_files()
				selection['readback_ms'] = (perf_counter() - started) * 1000
				selection['selected_count'] = len(selected)
				if set(selected) != {as_url(directory / name) for name in top_level} or len(selected) != row_count:
					raise ValueError('Select All returned the wrong files')
				context.mother_fs.file_added.add_callback(added)
				gui(lambda: context.main_window.before_dialog.connect(before_dialog))
				state['f5_started'] = perf_counter()
				gui(lambda: QTest.keyClick(view, Qt.Key_F5))
				if not finished.wait(180):
					raise TimeoutError('Copy command did not finish')
				if errors:
					raise RuntimeError('\n'.join(errors))
				wait_for(lambda: opposite._widget._model.rowCount() == row_count, 'Destination pane did not refresh')
				transfer['refresh_complete_ms'] = (perf_counter() - state['confirmed']) * 1000
				transfer.update(copied_count=len(committed), bytes_copied=count * size,
					throughput_mib_s=count * size / 2**20 / (transfer['wall_ms'] / 1000))
				verify_files(directory, expected, size)
				verify_files(destination, expected, size)
				samples.extend((selection, transfer))
			except BaseException:
				errors.append(traceback.format_exc())
			finally:
				def stop():
					for timer in timers:
						timer.stop()
					for dialog in QApplication.topLevelWidgets():
						if isinstance(dialog, ProgressDialog):
							dialog.request_cancel()
						elif isinstance(dialog, (QInputDialog, QMessageBox)):
							dialog.reject()
				gui(stop)
				if 'f5_started' in state and not finished.is_set():
					finished.wait(10)
				gui(context.main_window.close)

		FileListView.paintEvent, CopyFiles._gather_files, commands.Copy.__call__ = paint, gather, copy
		ProgressDialog.showEvent = progress_show
		worker = Thread(target=exercise, daemon=True)
		try:
			QTimer.singleShot(0, worker.start)
			status = context.run()
			worker.join(15)
			if worker.is_alive() or status:
				errors.append('Copy benchmark shutdown failed')
		finally:
			FileListView.paintEvent, CopyFiles._gather_files, commands.Copy.__call__ = original_paint, original_gather, original_copy
			ProgressDialog.showEvent = original_show
		result = dict(errors=errors, settings_isolated=Path(DATA_DIRECTORY).resolve() == settings.resolve(),
			verified=not errors and len(samples) == 2, samples=samples)
		if not errors:
			validate_result(result, count, size, row_count)
		print('SUITE_RESULT ' + json.dumps(result), flush=True)
		return int(bool(errors))