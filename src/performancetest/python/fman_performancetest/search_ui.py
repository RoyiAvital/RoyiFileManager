"""Native application search measurements with isolated settings and active-only probes."""

import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory
from threading import Event, Thread
from time import perf_counter

from fman_performancetest.filter_find import distribution, memory
from fman_performancetest.search_fixture import FILTER_QUERIES, FUZZY_QUERIES, RECURSIVE_QUERIES


def run_children(dataset, repeat, max_entries, output_directory):
	results = []
	for mode in ('filter', 'fuzzy', 'recursive'):
		command = [sys.executable, '-m', 'fman_performancetest.search_ui', str(dataset),
			'--mode', mode, '--repeat', str(repeat), '--max-entries', str(max_entries)]
		child = subprocess.run(command, capture_output=True, text=True, timeout=600)
		if child.returncode:
			raise RuntimeError(child.stdout + child.stderr)
		result = json.loads(next(line.removeprefix('SEARCH_UI_RESULT ')
			for line in child.stdout.splitlines() if line.startswith('SEARCH_UI_RESULT ')))
		results.append(result)
		output_directory.mkdir(parents=True, exist_ok=True)
		(output_directory / ('ui-' + mode + '.json')).write_text(json.dumps(result, indent=2) + '\n', encoding='utf-8')
		print('%s UI: worst query paint %.1f ms; worst active heartbeat gap %.1f ms' % (
			mode, max(sample['paint_ms'] for sample in result['samples']),
			max(sample['heartbeat_gap_ms']['max'] for sample in result['samples'])), flush=True)
	return results


def child(dataset, mode, repeat, max_entries, query_definitions=None, direct=False, viewport=(1280, 800)):
	with TemporaryDirectory(prefix='search-performance-') as temporary:
		settings = Path(temporary) / 'UserSettings'
		os.environ['ROYIFILEMANAGER_USER_SETTINGS'] = str(settings)
		from fman import DATA_DIRECTORY
		from fman.impl.application_context import get_application_context
		from fman.impl.model.listing import ListingModel
		from fman.impl.quicksearch import Quicksearch
		from fman.impl.util.qt.thread import run_in_main_thread
		from fman.impl.view import FileListView
		from fman.url import as_url
		from PyQt5.QtCore import QCoreApplication, QEvent, QObject, Qt, QTimer
		from PyQt5.QtGui import QKeyEvent
		if Path(DATA_DIRECTORY).resolve() != settings.resolve():
			raise RuntimeError('Settings isolation failed')
		user = settings / 'Plugins/User/Settings'
		user.mkdir(parents=True)
		(user / 'SearchFileFuzzy.json').write_text(json.dumps(dict(
			max_recursive_entries=max_entries, max_results=100, include_hidden=True, show_metadata=False)), encoding='utf-8')
		(user / 'Panes.json').write_text(json.dumps([dict(show_hidden_files=True)] * 2), encoding='utf-8')
		directory = dataset if direct else dataset / ('recursive' if mode == 'recursive' else 'flat')
		empty = Path(temporary) / 'empty'
		empty.mkdir()
		target = as_url(directory)
		context = get_application_context()
		app = context.app
		context.session_manager.is_first_run = False
		sys.argv = [sys.argv[0], str(directory), str(empty)]
		gui = lambda function: run_in_main_thread(function)()
		ready = Event()
		active = {}
		holders = {}
		report = dict(mode=mode, settings_isolated=True, max_entries=max_entries,
			platform=os.environ.get('QT_QPA_PLATFORM'), samples=[], errors=[],
			notes='Posted replacement-query key to completed Qt paint cycle, not compositor presentation. '
			'Heartbeat and queue probes cover active work only; no minimum sample padding. '
			'Fresh process per mode, warm OS caches, metadata off, no held-arrow workload.')
		original_hook = sys.excepthook
		def exception(error_type, error, traceback):
			report['errors'].append(str(error))
			original_hook(error_type, error, traceback)
		sys.excepthook = exception
		def finish_paint():
			if not active or not active.get('committed') or active['done'].is_set():
				return
			now = perf_counter()
			active['paint_ms'] = (now - active['start']) * 1000
			active['heartbeat'].append((now - active['last_tick']) * 1000)
			active['done'].set()
		original_commit = ListingModel._commit
		def commit(model, result):
			started = perf_counter()
			original_commit(model, result)
			if model.get_location() == target and active and active.get('delivered') and mode == 'filter':
				active['committed'] = True
				active['commit_ms'].append((perf_counter() - started) * 1000)
		ListingModel._commit = commit
		original_paint = FileListView.paintEvent
		def paint(view, event):
			result = original_paint(view, event)
			if view.model().get_location() == target:
				if view.model().sourceModel()._displayed is not None:
					holders['view'] = view
					ready.set()
				if mode == 'filter':
					finish_paint()
			return result
		FileListView.paintEvent = paint
		original_update = Quicksearch._update_items
		def update(dialog, query):
			started = perf_counter()
			original_update(dialog, query)
			if active and active.get('delivered'):
				active['committed'] = True
				active['commit_ms'].append((perf_counter() - started) * 1000)
				dialog.update()
		Quicksearch._update_items = update
		original_init = Quicksearch.__init__
		def initialize(dialog, *args, **kwargs):
			original_init(dialog, *args, **kwargs)
			holders['dialog'] = dialog
			dialog.installEventFilter(observer)
			dialog._query.installEventFilter(observer)
		Quicksearch.__init__ = initialize
		probe_type = QEvent.Type(QEvent.registerEventType())
		class ProbeEvent(QEvent):
			def __init__(self, phase, callback=None):
				super().__init__(probe_type)
				self.phase, self.callback, self.posted = phase, callback, perf_counter()
		class Observer(QObject):
			def event(self, event):
				if event.type() == probe_type:
					if active and event.phase == active['token'] and not active['done'].is_set():
						active['queue_ms'].append((perf_counter() - event.posted) * 1000)
						if event.callback:
							active['delivered'] = True
							event.callback()
					return True
				return super().event(event)
			def eventFilter(self, watched, event):
				if active and not active['done'].is_set():
					if event.type() == QEvent.KeyPress and event.text():
						active['delivered'] = True
						active.setdefault('key_dispatch_ms', (perf_counter() - active['start']) * 1000)
					if event.type() == QEvent.Paint and watched is holders.get('dialog'):
						QTimer.singleShot(0, finish_paint)
				return False
		observer = Observer()
		def tick():
			if active and not active['done'].is_set():
				now = perf_counter()
				active['heartbeat'].append((now - active['last_tick']) * 1000)
				active['last_tick'] = now
		timer = QTimer()
		timer.setInterval(10)
		timer.timeout.connect(tick)
		timer.start()
		def measure(label, post):
			started = perf_counter()
			active.clear()
			active.update(token=object(), start=started, last_tick=started, done=Event(),
				committed=False, delivered=False, heartbeat=[], queue_ms=[], commit_ms=[])
			post()
			deadline = started + 90
			while not active['done'].is_set():
				QCoreApplication.postEvent(observer, ProbeEvent(active['token']))
				if perf_counter() > deadline:
					raise TimeoutError(label)
				active['done'].wait(.01)
			result = dict(query=label, paint_ms=active['paint_ms'],
				key_dispatch_ms=active.get('key_dispatch_ms'),
				heartbeat_gap_ms=distribution(active['heartbeat']),
				queue_dispatch_ms=distribution(active['queue_ms']),
				qt_commit_ms=distribution(active['commit_ms']))
			result['heartbeat_samples_ms'] = list(active['heartbeat'])
			result['queue_samples_ms'] = list(active['queue_ms'])
			result['commit_samples_ms'] = list(active['commit_ms'])
			active.clear()
			return result
		def exercise():
			code = 1
			try:
				if not ready.wait(90):
					raise TimeoutError('Initial pane paint')
				pane = context.window.get_panes()[0]
				widget = pane._widget
				gui(lambda: context.main_window.resize(*viewport))
				if gui(lambda: widget.devicePixelRatioF()) != 1:
					raise RuntimeError('Unexpected DPI scale')
				input_widget = widget._filter_bar._input
				gui(lambda: input_widget.installEventFilter(observer))
				report['listing_entries'] = len(gui(widget.get_listing).names)
				if mode != 'filter':
					command = 'search_files_recursively' if mode == 'recursive' else 'search_files_in_current_folder'
					def launch():
						QCoreApplication.postEvent(observer, ProbeEvent(active['token'], lambda: pane.run_command(command)))
					report['open'] = measure(command, launch)
				if mode != 'filter':
					input_widget = holders['dialog']._query
				queries = dict(filter=FILTER_QUERIES, fuzzy=FUZZY_QUERIES, recursive=RECURSIVE_QUERIES)[mode]
				if query_definitions is not None:
					queries = tuple(query['text'] for query in query_definitions)
				for iteration in range(repeat):
					for query in queries:
						gui(input_widget.selectAll)
						result = measure(query, lambda: QCoreApplication.postEvent(input_widget,
							QKeyEvent(QEvent.KeyPress, 0, Qt.NoModifier, query)))
						result['iteration'] = iteration + 1
						if query_definitions is not None:
							result['query_id'] = next(item['id'] for item in query_definitions if item['text'] == query)
						result['rows'] = gui(lambda: holders['dialog']._items.model().rowCount()
							if mode != 'filter' else widget._model.rowCount())
						report['samples'].append(result)
				if mode != 'filter':
					started = perf_counter()
					gui(holders['dialog'].reject)
					report['close_dispatch_ms'] = (perf_counter() - started) * 1000
				report.update(memory())
				if report['errors']:
					raise RuntimeError('Application exceptions')
				print('SEARCH_UI_RESULT ' + json.dumps(report), flush=True)
				code = 0
			except BaseException:
				import traceback
				traceback.print_exc()
			finally:
				def stop():
					for dialog in app.topLevelWidgets():
						if isinstance(dialog, Quicksearch):
							dialog.reject()
					for pane in context.window.get_panes():
						pane._widget._model.shutdown()
					app.exit(code)
				gui(stop)
		QTimer.singleShot(0, lambda: Thread(target=exercise, daemon=True).start())
		return context.run()


def main():
	parser = argparse.ArgumentParser(description=__doc__)
	parser.add_argument('dataset', type=Path)
	parser.add_argument('--mode', choices=('filter', 'fuzzy', 'recursive'), required=True)
	parser.add_argument('--repeat', type=int, default=3)
	parser.add_argument('--max-entries', type=int, default=1_000_000_000)
	args = parser.parse_args()
	return child(args.dataset.resolve(strict=True), args.mode, args.repeat, args.max_entries)


if __name__ == '__main__':
	sys.exit(main())