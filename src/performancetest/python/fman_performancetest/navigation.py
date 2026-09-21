"""Posted navigation and mouse-wheel latency through completed pane paints."""

from threading import Event
from time import perf_counter


KEYS = ('page-up', 'page-down', 'home', 'end')


def valid_move(key, before, after, count):
	if not 0 <= after < count or before == after:
		return False
	if key == 'home':
		return after == 0
	if key == 'end':
		return after == count - 1
	if key == 'page-up':
		return after < before - 1
	if key == 'page-down':
		return after > before + 1
	return False


def measure(view, gui, repetitions=5):
	from fman.impl.view import FileListView
	from PyQt5.QtCore import QCoreApplication, QEvent, QObject, QPoint, QPointF, Qt
	from PyQt5.QtGui import QKeyEvent, QWheelEvent
	from PyQt5.QtWidgets import QApplication
	keys = dict(zip(KEYS, (Qt.Key_PageUp, Qt.Key_PageDown, Qt.Key_Home, Qt.Key_End)))
	methods = dict(zip(KEYS, ('move_cursor_page_up', 'move_cursor_page_down', 'move_cursor_home', 'move_cursor_end')))
	active, originals, samples = {}, {}, []
	original_paint = FileListView.paintEvent
	class Observer(QObject):
		def eventFilter(self, watched, event):
			if active and ((watched is view and event.type() == QEvent.KeyPress and event.key() == keys.get(active['key'])) or
				(watched is view.viewport() and event.type() == QEvent.Wheel and active['wheel'])):
				active.setdefault('received', perf_counter())
				active['received_count'] += 1
			return False
	def wrap(key, original):
		def moved(widget, *args, **kwargs):
			result = original(widget, *args, **kwargs)
			if widget is view and active and active['key'] == key and 'received' in active:
				active['changed'] = perf_counter()
				active['after'] = widget.currentIndex().row()
				if not valid_move(key, active['before'], active['after'], widget.model().rowCount()):
					active['error'] = 'Navigation did not reach the expected destination'
					active['done'].set()
				widget.viewport().update()
			return result
		return moved
	def scrolled(value):
		if active and active['wheel'] and 'received' in active:
			active['changed'] = perf_counter()
			active['after'] = value
	def paint(widget, event):
		result = original_paint(widget, event)
		if widget is view and active and 'changed' in active and active['received_count'] == active['event_count'] and not active['done'].is_set():
			active['paint'] = perf_counter()
			active['done'].set()
		return result
	def install():
		observer = Observer(view)
		view.installEventFilter(observer)
		view.viewport().installEventFilter(observer)
		view.verticalScrollBar().valueChanged.connect(scrolled)
		for key, method in methods.items():
			originals[method] = getattr(FileListView, method)
			setattr(FileListView, method, wrap(key, originals[method]))
		FileListView.paintEvent = paint
		lines = QApplication.wheelScrollLines()
		QApplication.setWheelScrollLines(3)
		return observer, lines
	observer, previous_lines = gui(install)
	try:
		cases = [(key, 0, 1) for key in KEYS] + [('wheel-up', 120, 1), ('wheel-down', -120, 1), ('wheel-burst-down', -120, 10)]
		for key, delta, count in cases:
			for iteration in range(repetitions):
				def prepare():
					rows = view.model().rowCount()
					if rows < 4:
						raise ValueError('Navigation benchmark requires at least four rows')
					view.setFocus()
					view.setCurrentIndex(view.model().index(rows // 2, 0))
					view.scrollTo(view.currentIndex(), view.PositionAtCenter)
					view.viewport().repaint()
					position = view.viewport().rect().center()
					return view.currentIndex().row(), view.verticalScrollBar().value(), position, view.viewport().mapToGlobal(position)
				row, scroll, position, global_position = gui(prepare)
				active.update(key=key, wheel=bool(delta), before=scroll if delta else row,
					event_count=count, received_count=0, done=Event(), start=perf_counter())
				for event_index in range(count):
					if delta:
						event = QWheelEvent(QPointF(position), QPointF(global_position), QPoint(), QPoint(0, delta),
							Qt.NoButton, Qt.NoModifier, Qt.NoScrollPhase, False)
						QCoreApplication.postEvent(view.viewport(), event)
					else:
						QCoreApplication.postEvent(view, QKeyEvent(QEvent.KeyPress, keys[key], Qt.NoModifier))
				if not active['done'].wait(10):
					raise TimeoutError(key + ' movement/paint')
				if 'error' in active:
					raise RuntimeError(active['error'])
				if delta and ((active['after'] - scroll) * delta >= 0 or gui(lambda: view.currentIndex().row()) != row):
					raise RuntimeError('Wheel did not scroll correctly or changed the cursor')
				sample = dict(action_id='navigation.' + key, iteration=iteration + 1,
					position_before=active['before'], position_after=active['after'], event_count=count,
					event_dispatch_ms=(active['received'] - active['start']) * 1000,
					input_to_paint_ms=(active['paint'] - active['start']) * 1000)
				sample['input_to_scroll_ms' if delta else 'key_to_cursor_ms'] = (active['changed'] - active['start']) * 1000
				samples.append(sample)
				active.clear()
	finally:
		def uninstall():
			FileListView.paintEvent = original_paint
			for method, original in originals.items():
				setattr(FileListView, method, original)
			view.verticalScrollBar().valueChanged.disconnect(scrolled)
			view.removeEventFilter(observer)
			view.viewport().removeEventFilter(observer)
			observer.deleteLater()
			QApplication.setWheelScrollLines(previous_lines)
		gui(uninstall)
	return samples