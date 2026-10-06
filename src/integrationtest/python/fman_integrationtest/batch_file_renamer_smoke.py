"""Opt-in source-app batch rename smoke and execution measurement on disposable files."""

import argparse
import json
import os
from pathlib import Path
from shutil import copytree
import sys
from tempfile import TemporaryDirectory
from threading import Event, Thread
from time import perf_counter
import traceback


def exercise(context, root, count, output, outcome):
	from fman.impl.util.qt.thread import run_in_main_thread
	from fman.impl.ui.quick_board import QuickBoardWindow
	from fman.impl.ui.facade import QuickTableWindow
	from fman.url import as_url
	from PyQt5.QtCore import QTimer
	from PyQt5.QtWidgets import QApplication
	gui = lambda callback: run_in_main_thread(callback)()
	timers, failures, ticks = [], [], []
	def wait_for(predicate, message):
		ready = Event()
		def install():
			timer = QTimer(context.main_window)
			timers.append(timer)
			timer.setInterval(10)
			def check():
				try:
					if predicate():
						timer.stop()
						ready.set()
				except BaseException:
					failures.append(traceback.format_exc())
					timer.stop()
					ready.set()
			timer.timeout.connect(check)
			timer.start()
		gui(install)
		assert ready.wait(90), message
		assert not failures, '\n'.join(failures)
	def board():
		return next((widget for widget in QApplication.topLevelWidgets() if isinstance(widget, QuickBoardWindow)
			and widget.alive.is_set() and not widget.pending and widget.table.settled), None)
	def report():
		return next((widget for widget in QApplication.topLevelWidgets() if isinstance(widget, QuickTableWindow)
			and widget.alive.is_set() and widget.windowTitle() == 'Batch File Renamer Results'), None)
	try:
		wait_for(lambda: len(context.window.get_panes()) == 2 and all(pane.get_path() == as_url(root)
			for pane in context.window.get_panes()), 'Startup did not restore sample folder')
		pane = context.window.get_panes()[0]
		urls = tuple(as_url(root / ('sample_%05d.txt' % index)) for index in range(count))
		gui(lambda: pane.select(urls))
		assert len(pane.get_selected_files()) == count
		assert 'batch_file_renamer' in pane.get_commands()
		gui(lambda: pane.run_command('batch_file_renamer'))
		wait_for(board, 'Batch File Renamer did not open')
		window = gui(board)
		gui(lambda: window.input.setText('renamed_{index:05d}{ext}'))
		wait_for(lambda: not window.pending and window.mapping == tuple(range(count)), 'Mapped preview did not settle')
		gui(lambda: window.grab().save(str(output)))
		counts = {'added': 0, 'removed': 0, 'scans': 0}
		def added(url):
			counts['added'] += 1
		def removed(url):
			counts['removed'] += 1
		context.mother_fs.file_added.add_callback(added)
		context.mother_fs.file_removed.add_callback(removed)
		models = gui(lambda: tuple(candidate._widget._model.sourceModel() for candidate in context.window.get_panes()))
		revisions = gui(lambda: tuple(model._scan_revision for model in models))
		def heartbeat():
			timer = QTimer(context.main_window)
			timers.append(timer)
			timer.timeout.connect(lambda: ticks.append(perf_counter()))
			timer.start(10)
		gui(heartbeat)
		started = perf_counter()
		gui(window.request_accept)
		wait_for(report, 'Rename operation/results did not finish')
		elapsed = perf_counter() - started
		result_window = gui(report)
		assert '%d renamed; 0 excluded' % count in gui(lambda: result_window.summary.content)
		wait_for(lambda: len(pane.get_selected_files()) == count and
			all('/renamed_' in url for url in pane.get_selected_files()) and
			pane.get_file_under_cursor() == as_url(root / 'renamed_00000.txt'), 'Renamed selection/cursor was not restored after loading')
		cursor = gui(pane.get_file_under_cursor)
		assert cursor == as_url(root / 'renamed_00000.txt'), (cursor, pane.get_selected_files())
		elapsed = perf_counter() - started
		gui(lambda: [timer.stop() for timer in timers])
		counts['scans'] = gui(lambda: sum(model._scan_revision - revision for model, revision in zip(models, revisions)))
		for index in range(count):
			assert not (root / ('sample_%05d.txt' % index)).exists()
			assert (root / ('renamed_%05d.txt' % index)).read_text() == 'payload-%d' % index
		assert counts['added'] == count and counts['removed'] == count
		gap = max((later - earlier for earlier, later in zip(ticks, ticks[1:])), default=0)
		print(json.dumps(dict(files=count, seconds=round(elapsed, 3), max_heartbeat_ms=round(gap * 1000, 2),
			notifications=counts, selected=len(pane.get_selected_files()), capture=str(output)), indent=2), flush=True)
		gui(result_window.close)
		outcome.append(0)
	except BaseException:
		traceback.print_exc()
		outcome.append(1)
	finally:
		def close():
			for timer in timers:
				timer.stop()
			for widget in QApplication.topLevelWidgets():
				if isinstance(widget, (QuickBoardWindow, QuickTableWindow)):
					widget.close()
			context.main_window.close()
		gui(close)


def main():
	parser = argparse.ArgumentParser(description=__doc__)
	parser.add_argument('--count', type=int, default=8)
	arguments = parser.parse_args()
	if not 1 <= arguments.count <= 10000:
		parser.error('count must be 1-10000')
	output = Path('target/batch-file-renamer-source.png').resolve()
	output.parent.mkdir(parents=True, exist_ok=True)
	with TemporaryDirectory(prefix='batch-renamer-smoke-') as directory:
		root = Path(directory).resolve()
		settings = root / 'UserSettings'
		copytree(Path(__file__).resolve().parents[4] / 'plugins/BatchFileRenamer', settings / 'Plugins/Third-party/BatchFileRenamer')
		for index in range(arguments.count):
			(root / ('sample_%05d.txt' % index)).write_text('payload-%d' % index)
		os.environ['ROYIFILEMANAGER_USER_SETTINGS'] = str(settings)
		from fman.impl.application_context import get_application_context
		from PyQt5.QtCore import QTimer
		context = get_application_context()
		_ = context.app
		context.session_manager.is_first_run = False
		sys.argv = [sys.argv[0], str(root), str(root)]
		outcome = []
		worker = Thread(target=exercise, args=(context, root, arguments.count, output, outcome), daemon=True)
		QTimer.singleShot(0, worker.start)
		result = context.run()
		worker.join(5)
		assert not worker.is_alive(), 'Smoke worker did not finish'
		return result or (outcome[0] if outcome else 1)


if __name__ == '__main__':
	sys.exit(main())