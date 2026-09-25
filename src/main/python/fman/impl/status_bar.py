from collections import namedtuple
from concurrent.futures import ThreadPoolExecutor
from PyQt5.QtCore import QObject, pyqtSignal, pyqtSlot, QTimer
from PyQt5.QtWidgets import QWidget, QHBoxLayout, QLabel


DISABLED = 'disabled'
ACTIVE_PANE = 'single'
PER_PANE = 'dual'
MODES = DISABLED, ACTIVE_PANE, PER_PANE
DEFAULT_SETTINGS = {
	'mode': DISABLED,
	'max_entries': 5000,
	'size_divisor': 1024
}
_size_divisor = 1024

StatusEntry = namedtuple(
	'StatusEntry', ('url', 'is_dir', 'is_loaded', 'is_selected')
)
StatusSummary = namedtuple(
	'StatusSummary', (
		'directory_count', 'file_count', 'size_bytes', 'size_complete',
		'size_supported', 'size_limited', 'selected_directory_count',
		'selected_file_count', 'selected_size_bytes',
		'selected_size_complete'
	)
)
PaneStatusSnapshot = namedtuple(
	'PaneStatusSnapshot', ('location', 'entries', 'all_rows_loaded', 'show_hidden')
)


def validate_status_bar_settings(value):
	result = DEFAULT_SETTINGS.copy()
	if not isinstance(value, dict):
		return result
	if value.get('mode') in MODES:
		result['mode'] = value['mode']
	max_entries = value.get('max_entries')
	if isinstance(max_entries, int) and not isinstance(max_entries, bool) \
		and max_entries > 0:
		result['max_entries'] = max_entries
	if value.get('size_divisor') in (1000, 1024):
		result['size_divisor'] = value['size_divisor']
	return result


def next_status_bar_mode(mode):
	try:
		return MODES[(MODES.index(mode) + 1) % len(MODES)]
	except ValueError:
		return DISABLED


def set_size_divisor(divisor):
	global _size_divisor
	if divisor not in (1000, 1024):
		raise ValueError('divisor must be 1000 or 1024')
	_size_divisor = divisor


def format_size(size_bytes, divisor=None):
	if divisor is None:
		divisor = _size_divisor
	if divisor not in (1000, 1024):
		raise ValueError('divisor must be 1000 or 1024')
	units = ('B', 'KB', 'MB', 'GB', 'TB') if divisor == 1000 else \
		('B', 'KiB', 'MiB', 'GiB', 'TiB')
	value = max(0, size_bytes)
	unit_index = 0
	while value >= divisor and unit_index < len(units) - 1:
		value /= divisor
		unit_index += 1
	if unit_index == 0:
		return '%d %s' % (value, units[unit_index])
	return '%.1f %s' % (value, units[unit_index])


def calculate_status_summary(
	entries, query_size, all_rows_loaded, max_entries, is_cancelled=lambda: False
):
	directory_count = file_count = 0
	selected_directory_count = selected_file_count = 0
	size_bytes = selected_size_bytes = 0
	size_supported = True
	size_limited = False
	selected_size_complete = True
	size_complete = all_rows_loaded
	queried = 0
	for entry in entries:
		if is_cancelled():
			return None
		if entry.is_dir:
			directory_count += 1
			if entry.is_selected:
				selected_directory_count += 1
			continue
		file_count += 1
		if entry.is_selected:
			selected_file_count += 1
		if not entry.is_loaded:
			size_complete = False
			if entry.is_selected:
				selected_size_complete = False
			continue
		if queried >= max_entries:
			size_limited = True
			if entry.is_selected:
				selected_size_complete = False
			continue
		queried += 1
		try:
			size = query_size(entry.url)
		except NotImplementedError:
			size_complete = False
			size_supported = False
			if entry.is_selected:
				selected_size_complete = False
			continue
		except (FileNotFoundError, OSError):
			size_complete = False
			if entry.is_selected:
				selected_size_complete = False
			continue
		if size is None:
			size_complete = False
			size_supported = False
			if entry.is_selected:
				selected_size_complete = False
			continue
		size_bytes += size
		if entry.is_selected:
			selected_size_bytes += size
	return StatusSummary(
		directory_count, file_count, size_bytes,
		size_complete and not size_limited, size_supported, size_limited,
		selected_directory_count, selected_file_count, selected_size_bytes,
		selected_size_complete
	)


class _CancellationToken:
	def __init__(self):
		self.cancelled = False


class StatusCalculationService(QObject):

	finished = pyqtSignal(object, int, object)

	def __init__(self, fs, parent=None):
		super().__init__(parent)
		self._fs = fs
		self._executor = ThreadPoolExecutor(
			max_workers=1, thread_name_prefix='status-bar'
		)
		self._shutdown = False
	def submit(self, owner_id, generation, snapshot, max_entries, token):
		future = self._executor.submit(
			calculate_status_summary, snapshot.entries,
			lambda url: self._fs.query(url, 'size_bytes'),
			snapshot.all_rows_loaded, max_entries,
			lambda: token.cancelled
		)
		future.add_done_callback(
			lambda result: self._on_finished(owner_id, generation, result)
		)
	def _on_finished(self, owner_id, generation, future):
		if self._shutdown or future.cancelled():
			return
		try:
			result = future.result()
		except Exception:
			result = None
		if result is not None:
			try:
				self.finished.emit(owner_id, generation, result)
			except RuntimeError:
				pass
	def shutdown(self):
		self._shutdown = True
		self._executor.shutdown(wait=False, cancel_futures=True)


class PaneStatusWidget(QWidget):
	def __init__(
		self, service, max_entries, size_divisor, show_active, parent=None
	):
		super().__init__(parent)
		self.setObjectName('pane-status')
		self.setProperty('active', False)
		self._service = service
		self._max_entries = max_entries
		self._size_divisor = size_divisor
		self._pane = None
		self._generation = 0
		self._token = None
		self._show_active = show_active
		self._active = QLabel('Active', self)
		self._active.setVisible(False)
		self._hidden = QLabel(self)
		self._directories = QLabel(self)
		self._files = QLabel(self)
		self._size = QLabel(self)
		self._selection = QLabel(self)
		layout = QHBoxLayout(self)
		layout.setContentsMargins(4, 1, 4, 1)
		layout.setSpacing(8)
		for label in (
			self._active, self._hidden, self._directories, self._files,
			self._size, self._selection
		):
			layout.addWidget(label)
		layout.addStretch()
		self._timer = QTimer(self)
		self._timer.setInterval(150)
		self._timer.setSingleShot(True)
		self._timer.timeout.connect(self._calculate)
		service.finished.connect(self._on_finished)
	def bind(self, pane):
		if pane is self._pane:
			return
		if self._pane is not None:
			self._pane.status_changed.disconnect(self.schedule_refresh)
			self._pane.disable_status_tracking()
		self._cancel()
		self._pane = pane
		if pane is not None:
			pane.status_changed.connect(self.schedule_refresh)
			pane.enable_status_tracking()
			self.schedule_refresh()
	def set_active(self, active):
		self._active.setVisible(self._show_active and active)
		if self.property('active') == active:
			return
		self.setProperty('active', active)
		self.style().unpolish(self)
		self.style().polish(self)
	def schedule_refresh(self):
		self._cancel()
		self._timer.start()
	def deactivate(self):
		self._timer.stop()
		self.bind(None)
		try:
			self._service.finished.disconnect(self._on_finished)
		except TypeError:
			pass
	def _cancel(self):
		self._generation += 1
		if self._token is not None:
			self._token.cancelled = True
		self._token = None
	def _calculate(self):
		if self._pane is None:
			return
		snapshot = self._pane.get_status_snapshot()
		self._hidden.setText(
			'Hidden: shown' if snapshot.show_hidden else 'Hidden: hidden'
		)
		if snapshot.location.startswith('null://'):
			self._clear()
			return
		self._token = _CancellationToken()
		self._service.submit(
			id(self), self._generation, snapshot, self._max_entries,
			self._token
		)
	@pyqtSlot(object, int, object)
	def _on_finished(self, owner_id, generation, summary):
		if owner_id != id(self) or generation != self._generation:
			return
		self._render(summary)
	def _render(self, summary):
		self._directories.setText('%d dirs' % summary.directory_count)
		self._files.setText('%d files' % summary.file_count)
		if not summary.size_supported:
			size = '-'
		elif summary.size_limited:
			size = format_size(summary.size_bytes, self._size_divisor) + '+'
		elif not summary.size_complete:
			size = '...'
		else:
			size = format_size(summary.size_bytes, self._size_divisor)
		self._size.setText('Size: ' + size)
		selected = summary.selected_directory_count + summary.selected_file_count
		if not selected:
			self._selection.clear()
			return
		if not summary.size_supported:
			selected_size = '-'
		elif not summary.selected_size_complete:
			selected_size = '...'
		else:
			selected_size = format_size(
				summary.selected_size_bytes, self._size_divisor
			)
		self._selection.setText(
			'Selected: %d dirs, %d files, %s' % (
				summary.selected_directory_count, summary.selected_file_count,
				selected_size
			)
		)
	def _clear(self):
		for label in (
			self._hidden, self._directories, self._files, self._size,
			self._selection
		):
			label.clear()