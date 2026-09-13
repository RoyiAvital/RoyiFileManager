import json
import os
import sys
import traceback
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Event, Thread
from time import perf_counter


def exercise_split_focus(window, main):
	from PyQt5.QtCore import QPoint, Qt
	from PyQt5.QtTest import QTest
	from PyQt5.QtWidgets import QApplication, QWidget
	app = QApplication.instance()
	original = window.pos()
	geometry = window.screen().availableGeometry()
	positions = [QPoint(geometry.left() - window.width() // 2, geometry.top() + 30)]
	other_screens = [screen for screen in app.screens() if screen is not window.screen()]
	if other_screens:
		positions.append(other_screens[0].availableGeometry().center() - window.rect().center())
	selected = set(window.list.selected_ids)
	other = QWidget()
	other.setWindowTitle('Focus transition check')
	try:
		for position in positions:
			window.move(position)
			other.show()
			other.activateWindow()
			app.processEvents()
			window.lower()
			main.raise_()
			main.activateWindow()
			window.panel.choice.setFocus()
			app.processEvents()
			QTest.keyClick(window.panel.choice, Qt.Key_Tab, Qt.ShiftModifier)
			app.processEvents()
			assert app.focusWidget() is window.list.view, 'Shift+Tab did not recover list focus'
			QTest.keyClick(window.list.view, Qt.Key_Tab)
			app.processEvents()
			assert app.focusWidget() is window.panel.choice, 'Tab did not recover panel focus'
			main._panel_dock.close_button.setFocus()
			QTest.keyClick(main._panel_dock.close_button, Qt.Key_Tab)
			app.processEvents()
			assert app.focusWidget() is window.list.query, 'Tab did not recover filter focus'
			assert window.list.selected_ids == selected, 'Focus traversal changed selection'
	finally:
		other.close()
		other.deleteLater()
		window.move(original)
		window.raise_()
		window.activateWindow()
		app.processEvents()
	return bool(other_screens)


def exercise(context, root, output):
	from favorites import AddCurrentFolderToFavorites, _snapshot
	from favorites.store import Favorite
	from favorites.ui import FavoritesController, mutate
	from fman.impl.util.qt.thread import run_in_main_thread
	from fman.url import as_url
	from PyQt5.QtCore import QTimer, QSignalBlocker, Qt

	gui = lambda function: run_in_main_thread(function)()
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
		if not ready.wait(10):
			raise AssertionError(message)

	try:
		wait_for(lambda: len(context.window.get_panes()) == 2, 'No startup panes')
		wait_for(lambda: all(
			pane.get_path() == as_url(str(root)) and pane._widget._model.rowCount() > 0
			for pane in context.window.get_panes()
		), 'Startup panes did not finish restoring')
		pane = context.window.get_panes()[0]
		target = root / 'Projects'
		target.mkdir(exist_ok=True)
		location = as_url(str(target))
		ready = Event()
		pane.set_path(location, callback=ready.set, onerror=None)
		assert ready.wait(10), 'Initial pane navigation failed'
		AddCurrentFolderToFavorites(pane)()
		pane_height = gui(lambda: context.main_window._splitter.height())
		FavoritesController.show(pane)
		window = gui(lambda: FavoritesController._sessions[pane])
		wait_for(lambda: window.session.revision >= 0 and not window.busy, 'Favorites did not load')
		wait_for(lambda: window.panel.choice.isEnabled(), 'Panel settings did not load')
		assert gui(lambda: len(window.session.records)) == 1
		gui(lambda: FavoritesController.show(pane, 'proj'))
		assert gui(lambda: window.list.model.rowCount()) == 1
		gui(lambda: FavoritesController.show(pane))
		assert gui(lambda: window.list.query.text()) == 'proj'
		gui(lambda: window.panel.choice.setCurrentText('Name'))
		wait_for(lambda: not window.settings.busy, 'Panel settings did not save')
		ui_saved = root / 'UserSettings' / 'Plugins' / 'User' / 'Settings' / 'Favorites UI (Windows).json'
		assert json.loads(ui_saved.read_text(encoding='utf-8'))['sort'] == 'Name'
		captured = _snapshot()[0]
		mutate(captured, 'Renamed projects', FavoritesController.owner)
		wait_for(lambda: window.session.records[0].name == 'Renamed projects', 'Rename not refreshed')
		assert _snapshot()[0][0].name == 'Renamed projects'
		saved = root / 'UserSettings' / 'Plugins' / 'User' / 'Settings' / 'Favorites (Windows).json'
		assert json.loads(saved.read_text(encoding='utf-8'))['favorites'][0]['name'] == 'Renamed projects'
		gui(lambda: window.list.query.clear())
		gui(lambda: window.resize(520, 330))
		def check_buttons():
			from PyQt5.QtWidgets import QStyle, QStyleOptionButton
			for button in window.panel.buttons.values():
				option = QStyleOptionButton()
				button.initStyleOption(option)
				content = button.style().subElementRect(QStyle.SE_PushButtonContents, option, button)
				assert content.width() >= button.fontMetrics().horizontalAdvance(button.text()), 'Clipped action label: ' + button.text()
		gui(check_buttons)
		def check_adaptive_buttons():
			from PyQt5.QtWidgets import QApplication
			main = context.main_window
			original_size = main.size()
			widths = []
			try:
				for width in (640, 960, 1440):
					main.resize(width, original_size.height())
					QApplication.processEvents()
					check_buttons()
					buttons = tuple(window.panel.buttons.values())
					widths.append(buttons[0].width())
					assert all(button.width() <= 160 for button in buttons), 'Action exceeded width cap'
					assert main._panel_dock.close_button.width() == 22
					main._panel_dock.grab().save(str(output.with_name('panel-width-%d.png' % width)))
				assert widths[0] < widths[-1], 'Actions did not adapt to application width'
				assert widths[-1] == 160, 'Wide actions did not reach their cap'
			finally:
				main.resize(original_size)
				QApplication.processEvents()
		gui(check_adaptive_buttons)
		def select_current():
			from PyQt5.QtTest import QTest
			window.list.view.setFocus()
			QTest.keyClick(window.list.view, Qt.Key_Space)
			assert len(window.list.selected_ids) == 1
			assert window.windowFlags() & Qt.FramelessWindowHint
		gui(select_current)
		gui(lambda: window.grab().save(str(output)))
		def check_dock():
			from PyQt5.QtCore import QPoint
			main = context.main_window
			dock = main._panel_dock
			assert window.panel.parentWidget() is dock
			assert dock.width() == main.centralWidget().width()
			assert dock.mapTo(main, QPoint(0, dock.height())).y() == main.statusBar().mapTo(main, QPoint()).y()
			assert main._splitter.height() < pane_height
			assert not dock.close_button.icon().isNull()
			main.grab().save(str(output.with_name('favorites-docked-panel.png')))
		gui(check_dock)
		secondary_checked = gui(lambda: exercise_split_focus(window, context.main_window))
		print('PASS: partial-offscreen and activation/stacking focus recovery; second monitor: %s' %
			('checked' if secondary_checked else 'unavailable'), flush=True)
		def close_panel():
			from PyQt5.QtTest import QTest
			QTest.mouseClick(context.main_window._panel_dock.close_button, Qt.LeftButton)
		gui(close_panel)
		wait_for(lambda: not window.alive.is_set() and context.main_window._panel_dock is None,
			'Close icon did not end the docked session')
		wait_for(lambda: context.main_window._splitter.height() == pane_height, 'Pane height was not restored')
		assert FavoritesController.owner.active, 'Closing UI unloaded the plug-in'
		window = FavoritesController.show(pane)
		wait_for(lambda: window.session.revision >= 0 and not window.busy and window.panel.choice.isEnabled(),
			'Panel did not reopen after close')
		assert gui(lambda: window.panel.choice.currentText()) == 'Name'
		ready.clear()
		pane.set_path(as_url(str(root)), callback=ready.set, onerror=None)
		assert ready.wait(10)
		gui(lambda: window.session.action('goto'))
		wait_for(lambda: not window.alive.is_set(), 'Go To did not close manager')
		assert pane.get_path() == location
		FavoritesController.show(pane)
		window = gui(lambda: FavoritesController._sessions[pane])
		wait_for(lambda: window.session.revision >= 0 and not window.busy, 'Reopened manager did not load')
		wait_for(lambda: window.panel.choice.isEnabled(), 'Reopened panel did not load')
		assert gui(lambda: window.panel.choice.currentText()) == 'Name'
		assert gui(lambda: window.list.query.text()) == ''
		assert gui(lambda: window.session.records[0].name) == 'Renamed projects'
		def delete_current():
			from PyQt5.QtTest import QTest
			QTest.mouseClick(window.panel.buttons['delete'], Qt.LeftButton)
			assert window.prompt is None, 'Favorites Delete requested confirmation'
		gui(delete_current)
		wait_for(lambda: not window.session.records, 'Delete not refreshed')
		assert window.alive.is_set(), 'Delete closed the manager'
		assert target.is_dir(), 'Bookmark deletion removed a folder'
		assert not gui(lambda: window.panel.buttons['delete'].isEnabled())
		assert not _snapshot()[0]
		assert json.loads(saved.read_text(encoding='utf-8')).get('favorites', []) == []
		gui(window.close)
		rows = tuple(Favorite('Project %03d' % index, as_url(str(root / ('Folder%03d' % index)))) for index in range(200))
		FavoritesController.show(pane)
		window = gui(lambda: FavoritesController._sessions[pane])
		wait_for(lambda: window.session.revision >= 0 and not window.busy, 'Performance session did not load')
		wait_for(lambda: window.panel.choice.isEnabled(), 'Performance panel did not load')
		def benchmark():
			window.session.records = rows
			window.session._project()
			timings = []
			for index in range(40):
				started = perf_counter()
				with QSignalBlocker(window.panel.choice):
					window.panel.choice.setCurrentIndex(index % 3)
				window.session._project()
				window.list.query.setText('p%02d' % index)
				timings.append((perf_counter() - started) * 1000)
			return sorted(timings)[37]
		p95 = gui(benchmark)
		assert p95 < 50, 'Filter/sort p95 exceeded 50 ms'
		gui(window.close)
		def capture_components():
			from fman.ui import Panel, IconButton, TextButton, DropDown
			from PyQt5.QtWidgets import QStyle
			panel = Panel(context.main_window)
			panel.setWindowFlags(Qt.Tool | Qt.FramelessWindowHint)
			for style_icon, label, checked in (
				(QStyle.SP_FileDialogDetailedView, 'Match case', True),
				(QStyle.SP_FileDialogContentsView, 'Whole words', False),
				(QStyle.SP_DirIcon, 'Include subfolders', True)
			):
				button = panel.add(IconButton(panel.style().standardIcon(style_icon), label))
				button.setChecked(checked)
			panel.add(DropDown((('Current folder', 'current'), ('All folders', 'all')), 'Scope'), 1)
			panel.add(TextButton('Find'))
			panel.add(TextButton('Find All'))
			panel.resize(600, panel.sizeHint().height())
			panel.show()
			panel.layout().activate()
			panel.grab().save(str(output.with_name('ui-components-panel.png')))
			panel.close()
			panel.deleteLater()
		gui(capture_components)
		print('PASS: startup, dock geometry, close icon, pane restoration, reopen, session reuse, query, rename persistence, Go To, delete, empty state; 200-row filter/sort p95 %.2f ms' % p95, flush=True)
		if os.environ.get('FAVORITES_SMOKE_RESULT'):
			Path(os.environ['FAVORITES_SMOKE_RESULT']).write_text(json.dumps({'ok': True, 'p95_ms': p95}), encoding='utf-8')
		code = 0
	except Exception:
		traceback.print_exc()
		if os.environ.get('FAVORITES_SMOKE_RESULT'):
			Path(os.environ['FAVORITES_SMOKE_RESULT']).write_text(json.dumps({'ok': False, 'error': traceback.format_exc()}), encoding='utf-8')
		code = 1
	finally:
		def stop_models():
			models = [pane._widget._model.sourceModel() for pane in context.window.get_panes()]
			for model in models:
				model.shutdown()
			return models
		for model in gui(stop_models):
			model._worker._thread.join(2)
			if model._worker._thread.is_alive():
				print('FAIL: pane model worker did not stop', flush=True)
				code = 1
		gui(lambda: context.app.exit(code))


def start(context, root, output):
	Thread(target=exercise, args=(context, root, output), daemon=True).start()


def main():
	if len(sys.argv) == 3 and sys.argv[1] == '--frozen':
		return frozen(Path(sys.argv[2]).resolve())
	with TemporaryDirectory(prefix='favorites-smoke-') as temporary:
		root = Path(temporary)
		os.environ['ROYIFILEMANAGER_USER_SETTINGS'] = str(root / 'UserSettings')
		from fman.impl.application_context import get_application_context
		from fman.impl.model import SortedFileSystemModel
		from fman.impl.util.qt.thread import is_in_main_thread
		from PyQt5.QtCore import QTimer
		original = SortedFileSystemModel._begin_navigation
		hops = []
		def measured(model, request):
			worker = not is_in_main_thread()
			started = perf_counter()
			result = original(model, request)
			if worker:
				hops.append((perf_counter() - started) * 1000)
			return result
		SortedFileSystemModel._begin_navigation = measured
		context = get_application_context()
		_ = context.app
		context.session_manager.is_first_run = False
		sys.argv = [sys.argv[0], str(root), str(root)]
		output = Path('target/favorites-smoke-source.png').resolve()
		output.parent.mkdir(parents=True, exist_ok=True)
		QTimer.singleShot(0, lambda: start(context, root, output))
		try:
			return context.run()
		finally:
			SortedFileSystemModel._begin_navigation = original
			print('First two pane startup navigation hops (ms):', hops[:2], flush=True)


def frozen(executable):
	import shutil
	import subprocess
	with TemporaryDirectory(prefix='favorites-frozen-smoke-') as temporary:
		root = Path(temporary)
		settings = root / 'UserSettings'
		plugin = settings / 'Plugins' / 'User' / 'Smoke' / 'favorites_smoke_plugin'
		plugin.mkdir(parents=True)
		shutil.copyfile(__file__, plugin / '__init__.py')
		result_path = root / 'result.json'
		environment = dict(os.environ, ROYIFILEMANAGER_USER_SETTINGS=str(settings),
			FAVORITES_SMOKE_ROOT=str(root), FAVORITES_SMOKE_RESULT=str(result_path),
			FAVORITES_SMOKE_IMAGE=str(Path('target/favorites-smoke-frozen.png').resolve()))
		result = subprocess.run([str(executable), str(root), str(root)], env=environment, timeout=60)
		if result.returncode or not result_path.exists():
			raise RuntimeError('Frozen smoke failed: exit %s, result present %s' % (result.returncode, result_path.exists()))
		report = json.loads(result_path.read_text(encoding='utf-8'))
		print('Frozen smoke:', report)
		return 0 if report['ok'] else 1


if __name__ == '__main__':
	sys.exit(main())
elif __name__ == 'favorites_smoke_plugin':
	from fman.impl.application_context import get_application_context
	from PyQt5.QtCore import QTimer
	_context = get_application_context()
	_context.session_manager.is_first_run = False
	_root = Path(os.environ['FAVORITES_SMOKE_ROOT'])
	_output = Path(os.environ['FAVORITES_SMOKE_IMAGE'])
	QTimer.singleShot(0, lambda: start(_context, _root, _output))