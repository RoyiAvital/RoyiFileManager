import hashlib
import json
import os
import sys
import traceback
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Event, Thread
from time import perf_counter


def exercise(context, root, output):
	from calculate_file_hash import _busy_panes
	from calculate_file_hash.ui import HashController
	from fman.impl.util.qt.thread import run_in_main_thread
	from fman.url import as_url
	from PyQt5.QtCore import QEvent, QPoint, Qt, QTimer
	from PyQt5.QtGui import QKeyEvent
	from PyQt5.QtWidgets import QApplication, QLineEdit, QPlainTextEdit, QToolButton
	gui = lambda function: run_in_main_thread(function)()
	def wait_for(predicate, message):
		ready = Event()
		def start():
			timer = QTimer(context.main_window)
			timer.setInterval(10)
			deadline = perf_counter() + 15
			def check():
				if predicate():
					ready.set()
				if ready.is_set() or perf_counter() > deadline:
					timer.stop()
					timer.deleteLater()
			timer.timeout.connect(check)
			timer.start()
			check()
		gui(start)
		assert ready.wait(16), message
	code = 1
	try:
		wait_for(lambda: len(context.window.get_panes()) == 2 and all(
			pane.get_path() == as_url(str(root)) and pane._widget._model.rowCount() > 0
			for pane in context.window.get_panes()), 'Startup panes did not restore')
		pane = context.window.get_panes()[0]
		path = root / 'sample \u03bb.txt'
		path.write_bytes(b'abc')
		pane.reload()
		wait_for(lambda: pane._widget._model.rowCount() >= 2, 'Fixture not listed')
		pane.place_cursor_at(as_url(str(path)))
		wait_for(lambda: pane.get_file_under_cursor() == as_url(str(path)), 'Cursor not placed')
		def picker_visible():
			dialog = QApplication.activeModalWidget()
			return dialog is not None and dialog.windowTitle() == 'Quicksearch'
		gui(lambda: pane.run_command('calculate_file_hash_by'))
		wait_for(picker_visible, 'Algorithm picker not shown')
		assert gui(lambda: pane not in HashController._sessions)
		gui(lambda: QApplication.sendEvent(QApplication.activeModalWidget(), QKeyEvent(QEvent.KeyPress, Qt.Key_Escape, Qt.NoModifier)))
		wait_for(lambda: not picker_visible(), 'Algorithm picker did not cancel')
		assert gui(lambda: pane not in HashController._sessions)
		pane.run_command('calculate_file_hash')
		wait_for(lambda: pane in HashController._sessions and HashController._sessions[pane].session.last is not None,
			'Hash result not published')
		window = gui(lambda: HashController._sessions[pane])
		assert gui(window.output.text) == hashlib.sha256(b'abc').hexdigest()
		def check_ui():
			window.raise_()
			window.activateWindow()
			QApplication.processEvents()
			assert window.frameGeometry().center() == context.main_window.frameGeometry().center()
			assert window.bottom_panel is None and context.main_window._panel_dock is None
			assert window.path_label.isVisible() and window.path_label.toolTip() == str(path)
			assert window.windowTitle() == str(path)
			assert window.output.title() == 'Hash Algorithm: SHA-256'
			assert window.layout().count() == 2
			focused = QApplication.focusWidget()
			assert focused is not None and (focused is window.output or window.output.isAncestorOf(focused))
			button = window.output.findChild(QToolButton)
			editor = window.output.findChild(QPlainTextEdit)
			assert button.mapTo(window.output, QPoint()).y() + button.height() <= editor.mapTo(window.output, QPoint()).y()
			image = button.icon().pixmap(32, 32).toImage()
			assert any(image.pixelColor(column, row).alpha() for row in range(image.height()) for column in range(image.width()))
			button.click()
			assert QApplication.clipboard().text() == window.output.text()
			QApplication.clipboard().setText('changed')
			QApplication.sendEvent(editor, QKeyEvent(QEvent.KeyPress, Qt.Key_Return, Qt.NoModifier))
			assert QApplication.clipboard().text() == window.output.text()
			QApplication.sendEvent(editor, QKeyEvent(QEvent.KeyPress, Qt.Key_Enter, Qt.KeypadModifier))
			assert QApplication.clipboard().text() == window.output.text()
			assert window.isVisible()
			window.grab().save(str(output))
		gui(check_ui)
		def capture_layout():
			point = QPoint(window.output.width() // 2, window.output.height() - 10)
			expected = window.output.grab().toImage()
			global_point = window.output.mapToGlobal(point)
			pixel = window.screen().grabWindow(0, global_point.x(), global_point.y(), 1, 1).toImage()
			if pixel.isNull() or pixel.pixelColor(0, 0) != expected.pixelColor(
				int(point.x() * expected.devicePixelRatio()), int(point.y() * expected.devicePixelRatio())):
				return False
			geometry = context.main_window.frameGeometry()
			return window.screen().grabWindow(0, geometry.x(), geometry.y(), geometry.width(), geometry.height()).save(
				str(output.with_name(output.stem + '-layout.png')))
		wait_for(capture_layout, 'Quick output was not painted above the main window')
		gui(lambda: pane.run_command('calculate_file_hash_by'))
		wait_for(picker_visible, 'Algorithm picker not shown')
		def select_algorithm():
			dialog = QApplication.activeModalWidget()
			query = dialog.findChild(QLineEdit)
			query.setText('sha512')
			dialog.grab().save(str(output.with_name(output.stem + '-picker.png')))
			QApplication.sendEvent(query, QKeyEvent(QEvent.KeyPress, Qt.Key_Return, Qt.NoModifier))
		gui(select_algorithm)
		wait_for(lambda: not window.busy and window.session.last[1] == 'sha512', 'Selected algorithm result not published')
		assert gui(window.output.text) == hashlib.sha512(b'abc').hexdigest()
		def check_by():
			QApplication.processEvents()
			assert window.frameGeometry().center() == context.main_window.frameGeometry().center()
			assert window.bottom_panel is None and context.main_window._panel_dock is None
			assert window.windowTitle() == str(path)
			assert window.path_label.toolTip() == str(path)
			assert window.output.title() == 'Hash Algorithm: SHA-512'
			assert window.layout().count() == 2
			window.grab().save(str(output.with_name(output.stem + '-sha512.png')))
		gui(check_by)
		pane.run_command('calculate_file_hash')
		wait_for(lambda: not window.busy and window.session.last[1] == 'sha256', 'Quick result not published')
		assert gui(window.output.text) == hashlib.sha256(b'abc').hexdigest()
		gui(window.close)
		wait_for(lambda: pane not in HashController._sessions and context.main_window._panel_dock is None, 'Result not disposed')
		if os.environ.get('HASH_SMOKE_LARGE') == '1':
			large = root / 'large.bin'
			with large.open('wb') as destination:
				destination.truncate(2 * 1024 ** 3)
			gui(lambda: pane.run_command('calculate_file_hash', {'url': as_url(str(large))}))
			wait_for(lambda: pane in HashController._sessions and HashController._sessions[pane].busy, 'Large hash did not start')
			started = perf_counter()
			gui(lambda: HashController._sessions[pane].close())
			wait_for(lambda: pane not in _busy_panes, 'Canceled reader did not stop')
			large.unlink()
			print('Large-file cancellation and handle release: %.1f ms' % ((perf_counter() - started) * 1000), flush=True)
		print('PASS: panel-free results, QuickSearch selection/cancel, path and algorithm titles, centering, SHA-256/SHA-512, copy, Enter, SVG pixels, and close', flush=True)
		code = 0
	except Exception:
		traceback.print_exc()
	finally:
		if os.environ.get('HASH_SMOKE_RESULT'):
			Path(os.environ['HASH_SMOKE_RESULT']).write_text(json.dumps({'ok': code == 0}), encoding='utf-8')
		def stop_models():
			models = [pane._widget._model.sourceModel() for pane in context.window.get_panes()]
			for model in models:
				model.shutdown()
			return models
		for model in gui(stop_models):
			model._worker._thread.join(2)
		gui(lambda: context.app.exit(code))


def start(context, root, output):
	def run():
		try:
			exercise(context, root, output)
		except Exception:
			message = traceback.format_exc()
			if os.environ.get('HASH_SMOKE_RESULT'):
				Path(os.environ['HASH_SMOKE_RESULT']).write_text(json.dumps({'ok': False, 'error': message}), encoding='utf-8')
			from fman.impl.util.qt.thread import run_in_main_thread
			run_in_main_thread(context.app.exit)(1)
	Thread(target=run, daemon=True).start()


def frozen(executable):
	import shutil
	import subprocess
	with TemporaryDirectory(prefix='hash-frozen-') as temporary:
		root = Path(temporary)
		settings = root / 'UserSettings'
		plugin = settings / 'Plugins' / 'User' / 'Smoke' / 'hash_smoke_plugin'
		plugin.mkdir(parents=True)
		shutil.copyfile(__file__, plugin / '__init__.py')
		result_path = root / 'result.json'
		output = Path(os.environ.get('HASH_SMOKE_IMAGE', 'target/hash-frozen.png')).resolve()
		environment = dict(os.environ, ROYIFILEMANAGER_USER_SETTINGS=str(settings), HASH_SMOKE_ROOT=str(root),
			HASH_SMOKE_RESULT=str(result_path), HASH_SMOKE_IMAGE=str(output))
		for name in ('PYTHONPATH', 'PYTHONHOME', 'QT_PLUGIN_PATH', 'QT_QPA_PLATFORM_PLUGIN_PATH', 'QML2_IMPORT_PATH'):
			environment.pop(name, None)
		windows = Path(environment['SYSTEMROOT'])
		environment['PATH'] = os.pathsep.join((str(windows / 'System32'), str(windows)))
		process = subprocess.run([str(executable), str(root), str(root)], env=environment, timeout=90)
		report = json.loads(result_path.read_text(encoding='utf-8')) if result_path.exists() else {}
		assert process.returncode == 0 and report.get('ok'), 'Frozen smoke failed: %s' % report
		print('PASS: frozen hash smoke', flush=True)
	return 0


def main():
	if len(sys.argv) == 3 and sys.argv[1] == '--frozen':
		return frozen(Path(sys.argv[2]).resolve())
	with TemporaryDirectory(prefix='hash-smoke-') as temporary:
		root = Path(temporary)
		os.environ['ROYIFILEMANAGER_USER_SETTINGS'] = str(root / 'UserSettings')
		from fman.impl.application_context import get_application_context
		from PyQt5.QtCore import QTimer
		context = get_application_context()
		_ = context.app
		context.session_manager.is_first_run = False
		sys.argv = [sys.argv[0], str(root), str(root)]
		output = Path(os.environ.get('HASH_SMOKE_IMAGE', 'target/hash-source.png')).resolve()
		output.parent.mkdir(parents=True, exist_ok=True)
		QTimer.singleShot(0, lambda: start(context, root, output))
		return context.run()


if __name__ == '__main__':
	sys.exit(main())
elif __name__ == 'hash_smoke_plugin':
	from fman.impl.application_context import get_application_context
	from PyQt5.QtCore import QTimer
	_context = get_application_context()
	_context.session_manager.is_first_run = False
	QTimer.singleShot(0, lambda: start(_context, Path(os.environ['HASH_SMOKE_ROOT']), Path(os.environ['HASH_SMOKE_IMAGE'])))