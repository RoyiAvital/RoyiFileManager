"""Opt-in selection measurements against the real application pane."""

import random


PATTERNS = ('single', 'all', 'contiguous', 'alternating', 'scattered')


def selection_rows(pattern, row_count, requested):
	if pattern == 'all':
		return tuple(range(row_count))
	if type(requested) is not int or requested < 1 or requested > row_count:
		raise ValueError('Invalid selection count')
	if pattern == 'single':
		return (row_count // 2,)
	if pattern == 'contiguous':
		first = (row_count - requested) // 2
		return tuple(range(first, first + requested))
	if pattern == 'alternating':
		if requested * 2 > row_count:
			raise ValueError('Alternating selection does not fit the pane')
		first = (row_count - requested * 2) // 2
		return tuple(range(first, first + requested * 2, 2))
	if pattern == 'scattered':
		return tuple(random.Random(1731).sample(range(row_count), requested))
	raise ValueError('Unknown selection pattern: ' + pattern)


def selection_cases(count):
	return [dict(action_id='selection.' + pattern, pattern=pattern,
		requested_count=None if pattern == 'all' else 1 if pattern == 'single' else count)
		for pattern in PATTERNS]


def measure(view, gui, pane, case):
	import json
	from threading import Event
	from time import perf_counter, process_time
	from fman.impl.view import FileListView
	from PyQt5.QtCore import QCoreApplication, QEvent, QObject, QTimer

	measurement = dict(case, status='running')
	active = {}
	painted = Event()
	original_paint = FileListView.paintEvent
	event_type = QEvent.Type(QEvent.registerEventType())

	def progress(stage):
		measurement['stage'] = stage
		print('SELECTION_PROGRESS ' + json.dumps(measurement), flush=True)

	def prepare():
		model = view.model()
		count = model.rowCount()
		if count != case['row_count']:
			raise ValueError('Selection fixture row count differs: %d != %d' % (count, case['row_count']))
		requested = count if case['requested_count'] is None else case['requested_count']
		rows = selection_rows(case['pattern'], count, requested)
		urls = tuple(model.url(model.index(row, 0)) for row in rows)
		pane.clear_selection()
		view.setCurrentIndex(model.index(count // 2, 0))
		if pane._widget._status_tracking:
			raise RuntimeError('Selection benchmark requires status disabled')
		view.scrollTo(view.currentIndex(), view.PositionAtCenter)
		view.viewport().repaint()
		measurement.update(row_count=count, requested_count=requested,
			initial_count=0, expected_count=len(rows))
		return urls, set(urls), (
			view.currentIndex().row(), view.verticalScrollBar().value())

	class Probe(QObject):
		def event(self, event):
			if event.type() == event_type:
				if active:
					active['queue'].append((perf_counter() - active['posted']) * 1000)
					active.pop('posted', None)
				return True
			return super().event(event)

	def tick():
		if active:
			now = perf_counter()
			active['gaps'].append((now - active['last']) * 1000)
			active['last'] = now
			if 'posted' not in active:
				active['posted'] = now
				QCoreApplication.postEvent(probe, QEvent(event_type))

	def paint(widget, event):
		result = original_paint(widget, event)
		if widget is view and active.get('mutated') and not painted.is_set():
			measurement['paint_ms'] = (perf_counter() - active['start']) * 1000
			painted.set()
		return result

	def install():
		probe = Probe(view)
		timer = QTimer(probe)
		timer.setInterval(10)
		timer.timeout.connect(tick)
		FileListView.paintEvent = paint
		return probe, timer

	def begin():
		now = perf_counter()
		active.update(start=now, last=now, posted=now, gaps=[], queue=[])
		QCoreApplication.postEvent(probe, QEvent(event_type))
		timer.start()

	def finish(prefix=''):
		now = perf_counter()
		active['gaps'].append((now - active['last']) * 1000)
		if 'posted' in active:
			active['queue'].append((now - active['posted']) * 1000)
		measurement[prefix + 'heartbeat_gap_ms'] = {'max': max(active['gaps'])}
		measurement[prefix + 'queue_dispatch_ms'] = {'max': max(active['queue'], default=0)}
		timer.stop()
		active.clear()

	requested_urls, expected_urls, before = gui(prepare)
	progress('prepared')
	probe, timer = gui(install)
	try:
		gui(begin)
		dispatched = perf_counter()
		def mutate():
			active['start'] = dispatched
			start, cpu = perf_counter(), process_time()
			if case['pattern'] == 'all':
				pane.select_all()
			else:
				pane.select(requested_urls)
			measurement.update(wall_ms=(perf_counter() - start) * 1000,
				cpu_ms=(process_time() - cpu) * 1000)
			progress('mutated')
			active['mutated'] = True
			view.viewport().update()
		gui(mutate)
		if not painted.wait(30):
			raise TimeoutError('Selection completed paint')
		gui(finish)
		progress('painted')
		gui(begin)
		def readback():
			start, cpu = perf_counter(), process_time()
			selected = pane.get_selected_files()
			measurement.update(readback_ms=(perf_counter() - start) * 1000,
				readback_cpu_ms=(process_time() - cpu) * 1000, selected_count=len(selected))
			return selected
		selected = gui(readback)
		def responsive():
			finish('readback_')
			measurement['responsive_ms'] = (perf_counter() - dispatched) * 1000
		gui(responsive)
		progress('readback')
		if len(selected) != len(set(selected)) or set(selected) != expected_urls:
			raise RuntimeError('Incorrect or duplicate selection readback')
		after = gui(lambda: (view.currentIndex().row(), view.verticalScrollBar().value()))
		if after != before:
			raise RuntimeError('Selection changed cursor or scroll')
		measurement.update(status='passed', state_preserved=True)
		progress('verified')
		return measurement
	finally:
		def uninstall():
			timer.stop()
			active.clear()
			FileListView.paintEvent = original_paint
			probe.deleteLater()
		gui(uninstall)