"""QuickView Table View: time from toggling QuickView on a CSV to its first painted rows and painted full import."""

import json
import os
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
from threading import Event, Thread
from time import perf_counter, process_time

from fman_performancetest.filter_find import distribution, memory
from fman_performancetest.fixtures import CSV_HEADER, CSV_NAME, csv_fields, csv_records


def helper_memory(process_id):
	"""Working set of the DuckDB helper process, read before it exits."""
	if sys.platform != 'win32':
		return {}
	import win32api
	import win32con
	import win32process
	handle = win32api.OpenProcess(win32con.PROCESS_QUERY_INFORMATION | win32con.PROCESS_VM_READ, False, process_id)
	try:
		values = win32process.GetProcessMemoryInfo(handle)
	finally:
		handle.Close()
	return dict(working_set_mib=values['WorkingSetSize'] / 1048576,
		peak_working_set_mib=values['PeakWorkingSetSize'] / 1048576)


def child(directory, viewport, specification, timeout=90):
	with TemporaryDirectory(prefix='quickview-csv-performance-', ignore_cleanup_errors=True) as temporary:
		settings = Path(temporary) / 'UserSettings'
		os.environ['ROYIFILEMANAGER_USER_SETTINGS'] = str(settings)
		from fman import DATA_DIRECTORY
		from fman.impl.application_context import get_application_context
		from fman.impl.util.qt.thread import run_in_main_thread
		from fman.url import as_url
		from PyQt5.QtCore import QCoreApplication, QEvent, QObject, QTimer
		if Path(DATA_DIRECTORY).resolve() != settings:
			raise RuntimeError('Settings isolation failed')
		user = settings / 'Plugins/User/Settings'
		user.mkdir(parents=True)
		(user / 'Panes.json').write_text(json.dumps([{'show_hidden_files': True}] * 2), encoding='utf-8')
		empty = Path(temporary) / 'empty'
		empty.mkdir()
		source = Path(directory) / CSV_NAME
		context = get_application_context()
		app = context.app
		window = context.main_window
		context.session_manager.is_first_run = False
		sys.argv = [sys.argv[0], str(directory), str(empty)]
		gui = lambda function: run_in_main_thread(function)()
		report = dict(settings_isolated=True, samples=[], errors=[], source_bytes=source.stat().st_size,
			records=csv_records(specification), columns=len(CSV_HEADER),
			notes='Warm filesystem cache, fresh application process and first helper start. Production 100 ms '
			'debounce included. Paint means completed Qt paint cycle, not compositor presentation. '
			'Content validation is untimed.')
		original_hook = sys.excepthook
		def exception(error_type, error, trace):
			report['errors'].append(str(error))
			original_hook(error_type, error, trace)
		sys.excepthook = exception
		def session():
			return getattr(window, '_quick_view_session', None)
		def table():
			current = session()
			return current.overlay.csv_view if current is not None else None
		def first_rows():
			view = table()
			return view is not None and view.model.rowCount() > 0 and 0 in view.model.pages
		def imported():
			view = table()
			return first_rows() and view.ready and not view.pending and view.model.count == report['records']
		marks = {}
		active = dict(start=None, done=Event(), gaps=[], queue=[], tick=0)
		probe_type = QEvent.Type(QEvent.registerEventType())
		class Probe(QEvent):
			def __init__(self, action=None):
				super().__init__(probe_type)
				self.action, self.started = action, perf_counter()
		def painted():
			now = perf_counter()
			if 'first' not in marks and first_rows():
				marks['first'] = now
			if 'full' not in marks and imported():
				marks['full'] = now
				active['done'].set()
		class Observer(QObject):
			def event(self, event):
				if event.type() == probe_type:
					if not active['done'].is_set():
						active['queue'].append((perf_counter() - event.started) * 1000)
					if event.action:
						event.action()
					return True
				return super().event(event)
			def eventFilter(self, watched, event):
				if active['start'] is not None and not active['done'].is_set() and event.type() == QEvent.Paint:
					view = table()
					if view is not None and watched is view.view.viewport():
						QTimer.singleShot(0, painted)
				return False
		observer = Observer()
		app.installEventFilter(observer)
		def tick():
			if active['start'] is not None and not active['done'].is_set():
				now = perf_counter()
				active['gaps'].append((now - active['tick']) * 1000)
				active['tick'] = now
		timer = QTimer()
		timer.setInterval(10)
		timer.timeout.connect(tick)
		timer.start()
		def wait_until(predicate, label):
			done = Event()
			def install():
				poll = QTimer(window)
				poll.setInterval(10)
				def check():
					if predicate():
						poll.stop()
						poll.deleteLater()
						done.set()
				poll.timeout.connect(check)
				poll.start()
				check()
			gui(install)
			if not done.wait(timeout):
				raise TimeoutError(label)
		def exercise():
			code = 1
			try:
				panes = context.window.get_panes()
				def loaded():
					for pane, location in zip(panes, (directory, empty)):
						listing = pane._widget.get_listing()
						model = pane._widget._model.sourceModel()
						if listing is None or listing.location != as_url(location) or model._scanning or model._committed_revision != model._revision:
							return False
					return len(panes) == 2
				wait_until(loaded, 'Requested pane listings')
				left = panes[0]
				gui(lambda: window.resize(*viewport))
				if gui(window.devicePixelRatioF) != 1:
					raise RuntimeError('Unexpected DPI scale')
				report['viewport'] = gui(lambda: [window.width(), window.height()])
				gui(lambda: left.place_cursor_at(as_url(source)))
				wait_until(lambda: left.get_file_under_cursor() == as_url(source), 'CSV cursor')
				cpu = process_time()
				active['start'] = active['tick'] = perf_counter()
				QCoreApplication.postEvent(observer, Probe(lambda: left.run_command('toggle_quick_view')))
				while not active['done'].wait(.01):
					if perf_counter() - active['start'] > timeout:
						raise TimeoutError('Table View import')
					QCoreApplication.postEvent(observer, Probe())
				cpu_ms = (process_time() - cpu) * 1000
				for identity, mark in (('csv.first-rows', 'first'), ('csv.full', 'full')):
					report['samples'].append(dict(action_id=identity, input_to_paint_ms=(marks[mark] - active['start']) * 1000,
						**({} if mark == 'first' else dict(cpu_ms=cpu_ms, heartbeat_gap_ms=distribution(active['gaps']),
							queue_dispatch_ms=distribution(active['queue']), heartbeat_samples_ms=active['gaps'],
							queue_samples_ms=active['queue'], **memory()))))
				def validate():
					view = table()
					expected = csv_fields(specification['seed'], 0)
					row = view.model.row(0)
					if list(view.labels) != list(CSV_HEADER) or row is None or list(row.cells[:len(expected)]) != list(expected):
						raise RuntimeError('Table View content differs from the fixture')
					return view.controller.process.processId()
				report['samples'].append(dict(action_id='csv.helper', **helper_memory(int(gui(validate)))))
				gui(lambda: left.run_command('toggle_quick_view'))
				wait_until(lambda: getattr(window, '_quick_view_csv_controller', None) is None or
					window._quick_view_csv_controller.process is None, 'Table View helper exit')
				if report['errors']:
					raise RuntimeError('Application exceptions')
				print('QUICKVIEW_RESULT ' + json.dumps(report), flush=True)
				code = 0
			except BaseException:
				import traceback
				traceback.print_exc()
			finally:
				def stop():
					current = session()
					if current is not None:
						current.shutdown()
					for pane in context.window.get_panes():
						pane._widget._model.shutdown()
					app.exit(code)
				gui(stop)
		QTimer.singleShot(0, lambda: Thread(target=exercise, daemon=True).start())
		return context.run()
