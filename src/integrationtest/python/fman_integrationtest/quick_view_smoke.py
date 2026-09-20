import os
from pathlib import Path
from subprocess import run
import sys
from tempfile import TemporaryDirectory
from threading import Event, Thread
import traceback


def exercise(context, root, restart):
	from fman import load_json, save_json
	from fman.impl.quicksearch import Quicksearch
	from fman.impl.util.qt.thread import run_in_main_thread
	from fman.url import as_url
	from PyQt5.QtCore import Qt, QTimer
	from PyQt5.QtTest import QTest
	from PyQt5.QtWidgets import QApplication
	gui = lambda function: run_in_main_thread(function)()
	def wait_for(predicate, message):
		ready = Event()
		def start():
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
		gui(start)
		assert ready.wait(15), message
	code = 1
	try:
		wait_for(lambda: len(context.window.get_panes()) == 2 and all(pane.get_file_under_cursor() for pane in context.window.get_panes()), 'Panes did not load')
		assert 'fman.impl.quick_view' not in sys.modules, 'Disabled QuickView imported its renderer'
		left, right = context.window.get_panes()
		window = context.main_window
		assert getattr(window, '_quick_view_session', None) is None
		assert getattr(window, '_quick_view_loader', None) is None
		assert left.get_command_aliases('toggle_quick_view') == ('Toggle QuickView',)
		assert any(binding['keys'] == ['Ctrl+Q'] and binding['command'] == 'toggle_quick_view' for binding in context.key_bindings.get_sanitized_bindings())
		if not restart:
			save_json('QuickView.json', {'untouched': 'preserved'})
		left.place_cursor_at(as_url(root / 'left' / 'image.png'))
		right_before = right.get_path(), right.get_file_under_cursor(), right.get_selected_files()
		geometry_before = gui(lambda: (right._widget.layout(), right._widget._model, right._widget.focusProxy(), window.minimumSize(), window._splitter.sizes()))
		left.focus()
		gui(lambda: QTest.keyClick(left._widget._file_view, Qt.Key_Q, Qt.ControlModifier))
		wait_for(lambda: getattr(window, '_quick_view_session', None) is not None and window._quick_view_session.overlay.canvas.image is not None, 'Ctrl+Q did not load image')
		session = gui(lambda: window._quick_view_session)
		canvas = session.overlay.canvas
		assert gui(lambda: canvas.mode) == ('actual_size' if restart else 'fit')
		assert load_json('QuickView.json')['untouched'] == 'preserved'
		gui(lambda: QTest.keyClick(left._widget._file_view, Qt.Key_Tab))
		wait_for(canvas.hasFocus, 'Tab did not focus canvas')
		assert gui(context.plugin_support.get_active_pane) is None
		assert gui(lambda: window._active_pane is left._widget)
		gui(lambda: QTest.keyClick(canvas, Qt.Key_Escape))
		assert left._has_focus()
		left.run_command('quick_view_actual_size')
		assert gui(lambda: canvas.scale) == 1
		assert load_json('QuickView.json')['image_mode'] == 'actual_size'
		left.run_command('quick_view_zoom_in')
		assert gui(lambda: canvas.scale) == 1.25
		left.run_command('quick_view_pan', {'direction': 'right', 'large': True})
		gui(session.overlay.focus_canvas)
		gui(lambda: QTest.keyClick(canvas, Qt.Key_Z))
		assert left._has_focus() and not left._widget.is_filtering()
		dialog_closed = Event()
		dialog_errors = []
		def reject_dialog(dialog):
			def reject():
				if not isinstance(dialog, Quicksearch):
					dialog_errors.append(type(dialog).__name__)
				dialog.reject()
				dialog_closed.set()
			QTimer.singleShot(0, reject)
		gui(lambda: window.before_dialog.connect(reject_dialog))
		gui(session.overlay.focus_canvas)
		gui(lambda: QTest.keyClick(canvas, Qt.Key_P, Qt.ControlModifier | Qt.ShiftModifier))
		assert dialog_closed.wait(10), 'Command Center did not open'
		assert not dialog_errors, dialog_errors
		wait_for(left._has_focus, 'Command Center did not return source focus')
		gui(lambda: window.before_dialog.disconnect(reject_dialog))
		left.run_command('quick_view_fit')
		for width, height in ((960, 600), (1280, 800)):
			gui(lambda: window.resize(width, height))
			gui(QApplication.processEvents)
			assert gui(lambda: session.overlay.geometry().size() == right._widget.size())
			def check_pixels():
				pixels = canvas.viewport().grab().toImage()
				color = pixels.pixelColor(pixels.width() // 2, pixels.height() // 2)
				assert color.green() > color.red() and color.green() > color.blue(), 'Image center is not the green fixture'
			gui(check_pixels)
		image_path = Path(os.environ.get('QUICK_VIEW_SMOKE_IMAGE', 'target/quick-view-source.png')).resolve()
		image_path.parent.mkdir(parents=True, exist_ok=True)
		assert gui(lambda: window.grab().save(str(image_path)))
		left.run_command('quick_view_actual_size')
		gui(session.overlay.focus_canvas)
		gui(lambda: QTest.keyClick(canvas, Qt.Key_Q, Qt.ControlModifier))
		wait_for(lambda: getattr(window, '_quick_view_session', None) is None and getattr(window, '_quick_view_loader', None) is None, 'Toggle did not release session/loader')
		assert right_before == (right.get_path(), right.get_file_under_cursor(), right.get_selected_files())
		assert geometry_before[:4] == gui(lambda: (right._widget.layout(), right._widget._model, right._widget.focusProxy(), window.minimumSize()))
		left.run_command('switch_panes')
		assert right._has_focus()
		right.run_command('toggle_quick_view')
		wait_for(lambda: getattr(window, '_quick_view_session', None) is not None, 'Right source could not enable')
		gui(window._quick_view_owner.invalidate)
		assert getattr(window, '_quick_view_session', None) is None
		right.run_command('toggle_quick_view')
		assert getattr(window, '_quick_view_session', None) is None, 'Invalidated owner reopened QuickView'
		print('PASS: QuickView %s, lazy startup, real shortcuts/commands, Command Center, preferences, both sources, layout preservation and owner cleanup' % ('restart' if restart else 'source'), flush=True)
		code = 0
	except BaseException:
		traceback.print_exc()
	finally:
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
	from PyQt5.QtCore import QRect
	from PyQt5.QtGui import QColor, QImage, QPainter
	with TemporaryDirectory(prefix='quick-view-smoke-') as temporary:
		root = Path(temporary).resolve(strict=True)
		for name in ('left', 'right'):
			(root / name).mkdir()
			(root / name / 'target.txt').write_text(name)
		image = QImage(1280, 960, QImage.Format_ARGB32)
		image.fill(QColor('#e7eceb'))
		painter = QPainter(image)
		for index, color in enumerate(('#b43f48', '#318978', '#d7a23b')):
			painter.fillRect(QRect(80 + index * 400, 100, 320, 760), QColor(color))
		painter.end()
		assert image.save(str(root / 'left' / 'image.png'))
		for options in ([], ['--restart']):
			result = run([sys.executable, '-m', 'fman_integrationtest.quick_view_smoke', str(root), *options], timeout=60)
			if result.returncode:
				return result.returncode
	return 0


if __name__ == '__main__':
	sys.exit(main())