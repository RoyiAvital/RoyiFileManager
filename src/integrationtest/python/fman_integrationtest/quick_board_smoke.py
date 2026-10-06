"""Opt-in source-app QuickBoard captures with disposable settings."""

import os
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
from threading import Event, Thread
import traceback


def exercise(context, root, output, outcome):
	from fman.impl.ui.facade import QuickTableWindow
	from fman.impl.ui.quick_board import QuickBoardWindow, _slots
	from fman.impl.util.qt.thread import run_in_main_thread
	from fman.ui import QuickTableColumn, QuickTableRow, show_quick_board, show_quick_table
	from fman.url import as_url
	from PyQt5.QtCore import QTimer, Qt
	from PyQt5.QtTest import QTest
	from PyQt5.QtWidgets import QApplication
	gui = lambda callback: run_in_main_thread(callback)()
	timers, failures = [], []
	columns = (QuickTableColumn('Original Name', 'file_name'), QuickTableColumn('Proposed Name', 'file_name'),
		QuickTableColumn('Size', 'numeric', unit='bytes'), QuickTableColumn('Status'))
	def preview(text):
		if text == '{invalid':
			raise ValueError('Expected a closing brace.')
		return tuple(QuickTableRow(('IMG_%04d.JPG' % (2041 + index), text.format(index=index + 1),
			(4 + index) * 1048576, 'Ready')) for index in range(12))
	def until(predicate, action):
		def install():
			timer = QTimer(context.main_window)
			timers.append(timer)
			timer.setInterval(10)
			def check():
				try:
					value = predicate()
					if value:
						timer.stop()
						action(value)
				except BaseException:
					timer.stop()
					failures.append(traceback.format_exc())
					for widget in QApplication.topLevelWidgets():
						if isinstance(widget, (QuickBoardWindow, QuickTableWindow)):
							widget.close()
			timer.timeout.connect(check)
			timer.start()
		gui(install)
	def open_window(kind):
		return next((widget for widget in QApplication.topLevelWidgets() if isinstance(widget, kind)
			and widget.alive.is_set() and widget.isVisible() and widget.table.settled
			and not getattr(widget, 'pending', False)), None)
	def capture(window, name):
		QApplication.processEvents()
		footer = window.status if isinstance(window, QuickBoardWindow) else window.table.counts
		for widget in (window.summary, window.table, window.table.view, footer):
			assert widget.isVisible() and widget.parentWidget().rect().contains(widget.geometry()), name
		if isinstance(window, QuickBoardWindow):
			assert window.input.geometry().bottom() < window.table.view.geometry().top()
			assert window.table.view.geometry().bottom() < footer.geometry().top()
			assert window.header.isVisible() and window.header.content == window.windowTitle()
			assert window.rect().contains(window.header.geometry())
			assert window.summary.toolTip() == window.summary.content
			assert window.windowFlags() & Qt.FramelessWindowHint
		image = window.grab().toImage()
		assert not image.isNull()
		assert image.width() == round(window.width() * window.devicePixelRatioF())
		colors = {image.pixelColor(horizontal, vertical).rgba()
			for horizontal in range(0, image.width(), 7) for vertical in range(0, image.height(), 7)}
		assert len(colors) > 8, 'Blank capture'
		assert image.save(str(output / (name + '.png')))
		print(name, window.width(), window.height(), 'DPR', window.devicePixelRatioF(), flush=True)
	try:
		ready = Event()
		until(lambda: len(context.window.get_panes()) == 2 and all(pane.get_path() == as_url(root)
			for pane in context.window.get_panes()), lambda value: ready.set())
		assert ready.wait(15), 'Startup panes did not restore'
		summary = '12 captured files | Names are a preview; the caller owns validation and execution.'
		def board_capture(window):
			window.resize(820, 520)
			capture(window, 'quickboard-normal')
			assert context.main_window.grab().save(str(output / 'quickboard-app.png'))
			window.resize(460, 280)
			capture(window, 'quickboard-narrow')
			window.resize(820, 520)
			window.table.open_filter_menu(2)
			QApplication.processEvents()
			assert window.table.filter_menu.grab().save(str(output / 'quickboard-filter.png'))
			QTest.keyClick(window.table.filter_menu, Qt.Key_Escape)
			window.input.setText('{invalid')
			def error_capture(board):
				capture(board, 'quickboard-error')
				QTest.keyClick(board.table.view, Qt.Key_Escape)
			until(lambda: window if window.preview_error else None, error_capture)
		until(lambda: open_window(QuickBoardWindow), board_capture)
		assert show_quick_board(columns=columns, get_rows=preview,
			text='Trip_{index:03d}.JPG', title='Compose names', summary=summary) == ('{invalid', False)
		def table_capture(window):
			capture(window, 'quicktable-reference')
			QTest.keyClick(window.table.query, Qt.Key_Escape)
		until(lambda: open_window(QuickTableWindow), table_capture)
		assert show_quick_table(columns=columns, rows=preview('Trip_{index:03d}.JPG'),
			title='Names', summary=summary) is None
		assert not failures, '\n'.join(failures)
		assert _slots._value == 2, 'QuickBoard lease retained'
		outcome.append(0)
		print('PASS: source startup, themed QuickBoard/QuickTable geometry, menus, inline error and cancellation', flush=True)
	except BaseException:
		traceback.print_exc()
		outcome.append(1)
	finally:
		def close():
			for timer in timers:
				timer.stop()
			context.main_window.close()
		gui(close)


def main():
	output = Path(os.environ.get('QUICK_BOARD_SMOKE_OUTPUT', 'target/quickboard')).resolve()
	output.mkdir(parents=True, exist_ok=True)
	with TemporaryDirectory(prefix='quick-board-smoke-') as directory:
		root = Path(directory).resolve()
		os.environ['ROYIFILEMANAGER_USER_SETTINGS'] = str(root / 'UserSettings')
		from fman.impl.application_context import get_application_context
		from PyQt5.QtCore import QTimer
		context = get_application_context()
		_ = context.app
		context.session_manager.is_first_run = False
		sys.argv = [sys.argv[0], str(root), str(root)]
		outcome, closed = [], []
		context.main_window.closed.connect(lambda: closed.append(True))
		worker = Thread(target=exercise, args=(context, root, output, outcome), daemon=True)
		QTimer.singleShot(0, worker.start)
		result = context.run()
		worker.join(5)
		assert not worker.is_alive() and closed == [True], 'Source shutdown did not finish'
		return result or (outcome[0] if outcome else 1)


if __name__ == '__main__':
	sys.exit(main())