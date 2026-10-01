"""Opt-in selection measurements against the real application pane."""

import random


PATTERNS = ('contiguous', 'alternating', 'scattered')


def selection_rows(pattern, row_count, requested):
	if type(requested) is not int or requested < 1 or requested > row_count:
		raise ValueError('Invalid selection count')
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


def selection_cases(counts):
	cases = []
	for status in (False, True):
		prefix = 'status-on' if status else 'status-off'
		for pattern in PATTERNS:
			for requested in counts:
				actions = ('select', 'reselect', 'overlap', 'deselect') if requested == max(counts) else ('select',)
				for action in actions:
					cases.append(dict(action_id=f'{prefix}.{pattern}.{requested}.{action}',
						pattern=pattern, requested_count=requested, action=action, status_enabled=status))
		for action in ('select-all', 'clear', 'invert'):
			cases.append(dict(action_id=prefix + '.full.' + action, pattern='full',
				requested_count=None, action=action, status_enabled=status))
	return cases


def measure(view, gui, pane, window, case):
	import json
	from threading import Event
	from time import perf_counter, process_time
	from core.commands import InvertSelection
	from fman.impl.status_bar import PER_PANE
	from fman.impl.view import FileListView
	from PyQt5.QtCore import QCoreApplication, QEvent, QItemSelection, QItemSelectionModel, QObject, QTimer

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
		urls = tuple(model.url(model.index(row, 0)) for row in range(count))
		requested = count if case['requested_count'] is None else case['requested_count']
		rows = tuple(range(count)) if case['pattern'] == 'full' else selection_rows(case['pattern'], count, requested)
		desired = set(rows)
		outside = next((row for row in range(count) if row not in desired), None)
		action = case['action']
		initial = set()
		expected = desired
		if action == 'reselect':
			initial = desired
		elif action == 'overlap':
			initial = set(rows[:requested // 2]) | {outside}
			expected = desired | {outside}
		elif action == 'deselect':
			initial = desired | {outside}
			expected = {outside}
		elif action == 'clear':
			initial, expected = desired, set()
		elif action == 'invert':
			initial = set(range(count // 2))
			expected = desired - initial
		if None in initial or None in expected:
			raise ValueError('Selection case requires an unmarked outside row')
		selection = QItemSelection()
		ordered = sorted(initial)
		first = last = None
		for row in ordered:
			if last is not None and row != last + 1:
				selection.select(model.index(first, 0), model.index(last, model.columnCount() - 1))
				first = None
			if first is None:
				first = row
			last = row
		if first is not None:
			selection.select(model.index(first, 0), model.index(last, model.columnCount() - 1))
		view.selectionModel().select(selection, QItemSelectionModel.ClearAndSelect)
		view.setCurrentIndex(model.index(count // 2, 0))
		if case['status_enabled']:
			window.set_extended_status_bar(dict(window._status_settings, mode=PER_PANE))
			pane._widget.layout().activate()
		if pane._widget._status_tracking != case['status_enabled']:
			raise RuntimeError('Wrong selection status mode')
		view.scrollTo(view.currentIndex(), view.PositionAtCenter)
		view.viewport().repaint()
		measurement.update(row_count=count, requested_count=requested,
			initial_count=len(initial), expected_count=len(expected))
		return tuple(urls[row] for row in rows), {urls[row] for row in expected}, (
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
			action = case['action']
			if action in ('select', 'reselect', 'overlap'):
				pane.select(requested_urls)
			elif action == 'deselect':
				pane.deselect(requested_urls)
			elif action == 'select-all':
				pane.select_all()
			elif action == 'clear':
				pane.clear_selection()
			elif action == 'invert':
				InvertSelection(pane)()
			else:
				raise ValueError('Unknown selection action: ' + action)
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
		gui(lambda: finish('readback_'))
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