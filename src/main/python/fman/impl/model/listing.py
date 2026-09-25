from collections import OrderedDict
from dataclasses import dataclass, replace
from threading import Event as ThreadEvent, Lock, Thread
from time import perf_counter, sleep
import sys

from fman.impl.model.drag_and_drop import DragAndDrop
from fman.impl.model.file_watcher import FileWatcher
from fman.impl.status_bar import StatusEntry
from fman.impl.util import Event
from fman.impl.util.qt.thread import run_in_main_thread
from fman.listing import reconcile
from fman.url import basename, dirname, join
from PyQt5.QtCore import QModelIndex, Qt, pyqtSignal


class Canceled(Exception):
	pass


class ScanObservation:
	def __init__(self, fs, location):
		self._fs, self._location = fs, location
		self.changed = ThreadEvent()
		self._closed = False
		self._lock = Lock()
		fs.file_added.add_callback(self._changed)
		fs.file_removed.add_callback(self._changed)
		try:
			fs.add_file_changed_callback(location, self._changed)
		except BaseException:
			fs.file_added.remove_callback(self._changed)
			fs.file_removed.remove_callback(self._changed)
			raise

	def _changed(self, url):
		if url == self._location or dirname(url) == self._location:
			self.changed.set()

	def close(self):
		with self._lock:
			if self._closed:
				return
			self._closed = True
			try:
				self._fs.remove_file_changed_callback(self._location, self._changed)
			except (ValueError, FileNotFoundError):
				pass
			self._fs.file_added.remove_callback(self._changed)
			self._fs.file_removed.remove_callback(self._changed)


class LatestJobs:
	def __init__(self, capacity=1, cooperative=False):
		self._capacity = capacity
		self._cooperative = cooperative
		self._lock = Lock()
		self._active = set()
		self._pending = None
		self._closed = False

	def submit(self, work, deliver, canceled_callback=None):
		failed = None
		with self._lock:
			if self._closed:
				retired = work, deliver, canceled_callback
			else:
				retired = self._pending
				for canceled in self._active:
					canceled.set()
				self._pending = work, deliver, canceled_callback
				failed = self._start()
		self._retire(retired)
		if failed is not None:
			job, error = failed
			self._retire(job)
			raise error

	@staticmethod
	def _retire(job):
		if job is not None and job[2] is not None:
			job[2]()

	def _start(self):
		if self._pending is None or len(self._active) >= self._capacity:
			return
		work, deliver, canceled_callback = self._pending
		self._pending = None
		canceled = ThreadEvent()
		self._active.add(canceled)
		try:
			Thread(target=self._run, args=(work, deliver, canceled, canceled_callback), daemon=True).start()
		except BaseException as error:
			self._active.remove(canceled)
			return (work, deliver, canceled_callback), error

	def _run(self, work, deliver, canceled, canceled_callback):
		deadline = perf_counter() + .004
		def check():
			nonlocal deadline
			if canceled.is_set():
				raise Canceled()
			if self._cooperative and perf_counter() >= deadline:
				sleep(.001)
				if canceled.is_set():
					raise Canceled()
				deadline = perf_counter() + .004
		try:
			try:
				check()
				result = work(check)
				check()
			except Canceled:
				if canceled_callback is not None:
					canceled_callback()
				return
			except Exception as error:
				if canceled.is_set():
					if canceled_callback is not None:
						canceled_callback()
				else:
					deliver(None, error)
			else:
				deliver(result, None)
		finally:
			with self._lock:
				self._active.remove(canceled)
				failed = self._start()
			if failed is not None:
				job, error = failed
				job[1](None, error)

	def cancel(self):
		with self._lock:
			retired, self._pending = self._pending, None
			for canceled in self._active:
				canceled.set()
		self._retire(retired)

	def close(self):
		with self._lock:
			self._closed = True
			retired, self._pending = self._pending, None
			for canceled in self._active:
				canceled.set()
		self._retire(retired)


@dataclass(frozen=True, slots=True)
class Projection:
	listing: object
	visible: tuple
	rows: dict
	remap: dict | None
	column: int
	ascending: bool
	prefix: str = ''
	preferred: object = None
	highlights: object = None
	order: object = None
	columns: tuple = ()


def project(listing, previous, column, column_index, ascending, filters, check, prefix='', search=None, order=None):
	check()
	highlights = None
	if search is not None:
		engine, query = search
		visible, highlights = engine(listing, query, check)
		prefix = ''
	else:
		if order is None:
			keys = column.keys(listing, ascending)
			check()
			order = tuple(sorted(range(len(listing.names)), key=keys.__getitem__, reverse=not ascending))
		visible = order
		for predicate in filters:
			select = getattr(predicate, 'filter_indices', None)
			if select is not None:
				visible = select(listing, visible, check)
				continue
			filtered = []
			for position, index in enumerate(visible):
				if position % 256 == 0:
					check()
				if predicate(listing, index):
					filtered.append(index)
			visible = filtered
	check()
	remap = {} if previous is None or previous is listing else reconcile(previous, listing, check)
	return Projection(listing, tuple(visible), {entry: row for row, entry in enumerate(visible)},
		remap, column_index, ascending, prefix,
		next((entry for entry in visible if listing.display_names[entry].lower().startswith(prefix)), None) if prefix else None,
		highlights, order)


class ListingModel(DragAndDrop):
	location_loaded = pyqtSignal(str)
	all_rows_loaded = pyqtSignal()
	file_renamed = pyqtSignal(str, str)
	location_disappeared = pyqtSignal(str)
	files_changed = pyqtSignal()
	sort_order_changed = pyqtSignal(int, int)
	about_to_commit = pyqtSignal()
	committed = pyqtSignal(object)
	_result = pyqtSignal(str, int, object, object)
	_invalidate = pyqtSignal()

	def __init__(self, fs, location, columns, scanner, scan_jobs, view_jobs,
		sort_column=0, ascending=True, filters=None, listing=None, icons=None, observation=None):
		super().__init__()
		self._fs, self._location, self._columns = fs, location, columns
		self._scanner = scanner
		self._observation = observation
		self._icons = icons
		if icons is not None:
			icons.changed.connect(self._icons_changed)
		self._scan_jobs, self._view_jobs = scan_jobs, view_jobs
		self._sort_column, self._sort_ascending = sort_column, ascending
		self._filters = list(filters or ())
		self._listing = listing
		self._displayed = None
		self._visible = ()
		self._row_numbers = {}
		self._names = None
		self._text_cache = OrderedDict()
		self._icon_cells = OrderedDict()
		self._search = None
		self._highlights = {}
		self._restore_from = None
		self._order_cache = None
		self._pending_columns = None
		self._columns_callback = None
		self._revision = 0
		self._committed_revision = 0
		self._scan_revision = 0
		self._scanning = False
		self._dirty = False
		self._shutdown = False
		self._navigation_request = None
		self._columns_recreated = False
		self._callback = None
		self._watching = False
		self._file_watcher = FileWatcher(fs, self)
		self.transaction_ended = Event()
		self._result.connect(self._receive, Qt.QueuedConnection)
		self._invalidate.connect(self._request_scan, Qt.QueuedConnection)

	def start(self, callback):
		self._callback = callback
		if self._listing is not None:
			self.update()
		self._request_scan()

	def _deliver(self, kind, revision, result, error):
		if not self._shutdown:
			try:
				self._result.emit(kind, revision, result, error)
			except RuntimeError:
				pass

	def _request_scan(self):
		if self._shutdown:
			return
		if self._scanning:
			self._dirty = True
			return
		self._scanning = True
		self._scan_revision += 1
		revision = self._scan_revision
		scanner, location = self._scanner, self._location
		def work(check):
			check()
			if not self._watching:
				self._file_watcher.start()
				self._watching = True
				if self._shutdown:
					self._file_watcher.shutdown()
					check()
				if self._observation is not None:
					observation, self._observation = self._observation, None
					observation.close()
					if not observation.changed.is_set():
						return self._listing
			self._fs.clear_cache(location)
			return scanner(check)
		self._scan_jobs.submit(work,
			lambda result, error: self._deliver('scan', revision, result, error),
			lambda: self._deliver('scan', revision, None, Canceled()))

	def _capture_filters(self):
		result = []
		for predicate in self._filters:
			factory = getattr(predicate, 'snapshot_filter', None)
			owner = getattr(predicate, '__self__', None)
			if factory is None and owner is not None:
				factory = getattr(owner, 'snapshot_filter', None)
			if factory is None:
				raise TypeError('Filter does not support immutable listings')
			else:
				result.append(factory())
		return tuple(result)

	@run_in_main_thread
	def update(self):
		if self._shutdown:
			return
		self._revision += 1
		if self._listing is None:
			return
		revision = self._revision
		listing = self._listing
		previous = self._restore_from if self._restore_from is not None else self._displayed
		index, ascending = self._sort_column, self._sort_ascending
		columns = self._pending_columns if self._pending_columns is not None else self._columns
		column, filters = columns[index], self._capture_filters()
		prefix = ''
		for predicate in self._filters:
			owner = getattr(predicate, '__self__', None)
			if owner is not None and hasattr(owner, 'snapshot_prefix'):
				prefix = owner.snapshot_prefix()
		search = self._search
		cache = self._order_cache
		order = cache[3] if cache is not None and cache[0] is listing and cache[1:3] == (index, ascending) else None
		self._view_jobs.submit(lambda check:
			replace(project(listing, previous, column, index, ascending, filters, check, prefix, search, order),
				columns=tuple(columns)),
			lambda result, error: self._deliver('view', revision, result, error))

	@run_in_main_thread
	def set_columns(self, columns, sort_index, ascending, callback):
		self._pending_columns = tuple(columns)
		self._sort_column, self._sort_ascending = sort_index, ascending
		self._order_cache = None
		self._columns_callback = callback
		self.update()

	def _receive(self, kind, revision, result, error):
		if self._shutdown:
			return
		if kind == 'scan':
			if revision != self._scan_revision:
				return
			self._scanning = False
			if isinstance(error, Canceled):
				return
			if error is None:
				if result is None:
					error = OSError('Snapshot enumeration is no longer supported for this folder')
				elif result is not self._listing:
					self._listing = result
					self.update()
			if self._dirty:
				self._dirty = False
				self._request_scan()
		elif revision != self._revision:
			return
		elif error is None:
			self._committed_revision = revision
			self._commit(result)
		if error is not None:
			if self._navigation_request and self._navigation_request.active:
				self._navigation_request.fail(error)
			elif isinstance(error, (FileNotFoundError, PermissionError, NotADirectoryError)) or \
				isinstance(error, OSError) and getattr(error, 'winerror', None) in (2, 3, 5, 21):
				self.location_disappeared.emit(self._location)
			else:
				sys.excepthook(type(error), error, error.__traceback__)

	def _commit(self, result):
		self.about_to_commit.emit()
		self.beginResetModel()
		self._columns = result.columns
		self._pending_columns = None
		self._displayed = result.listing
		self._visible, self._row_numbers = result.visible, result.rows
		self._highlights = result.highlights or {}
		self._restore_from = None
		if result.order is not None:
			self._order_cache = result.listing, result.column, result.ascending, result.order
		self._names = None
		self._text_cache.clear()
		self._icon_cells.clear()
		self.endResetModel()
		self.committed.emit(result)
		columns_callback, self._columns_callback = self._columns_callback, None
		if columns_callback is not None:
			columns_callback()
		callback, self._callback = self._callback, None
		if callback is not None:
			callback()
			self.location_loaded.emit(self._location)
		self.sort_order_changed.emit(result.column,
			Qt.AscendingOrder if result.ascending else Qt.DescendingOrder)
		self.transaction_ended.trigger()
		self.files_changed.emit()
		self.all_rows_loaded.emit()

	def rowCount(self, parent=QModelIndex()):
		return 0 if parent.isValid() else len(self._visible)
	def columnCount(self, parent=QModelIndex()):
		return 0 if parent.isValid() else len(self._columns)
	def data(self, index, role=Qt.DisplayRole):
		if not index.isValid() or not 0 <= index.row() < len(self._visible):
			return None
		if role == Qt.UserRole + 1 and index.column() == 0:
			return self._highlights.get(self._visible[index.row()])
		if role in (Qt.DisplayRole, Qt.EditRole, Qt.ToolTipRole):
			key = self._visible[index.row()], index.column()
			if key not in self._text_cache:
				self._text_cache[key] = self._columns[index.column()].text(self._displayed, key[0])
				if len(self._text_cache) > 512:
					self._text_cache.popitem(last=False)
			return self._text_cache[key]
		if role == Qt.DecorationRole and index.column() == 0:
			if self._icons is not None:
				entry = self._visible[index.row()]
				key = self._icons.key(self._displayed, entry)
				self._icon_cells[index.row()] = key
				if len(self._icon_cells) > 512:
					self._icon_cells.popitem(last=False)
				return self._icons.icon(self._displayed, entry, key=key)
			from PyQt5.QtGui import QIcon
			return QIcon()
		return None
	def _icons_changed(self, key):
		if not self._shutdown:
			for row, requested in tuple(self._icon_cells.items()):
				if requested == key:
					self.dataChanged.emit(self.index(row, 0), self.index(row, 0), [Qt.DecorationRole])
	def headerData(self, section, orientation, role=Qt.DisplayRole):
		if orientation == Qt.Horizontal and role == Qt.DisplayRole:
			return self._columns[section].display_name
		return None
	def flags(self, index):
		if not index.isValid():
			return Qt.ItemIsDropEnabled
		result = Qt.ItemIsSelectable | Qt.ItemIsEnabled
		if index.column() == 0:
			result |= Qt.ItemIsEditable | Qt.ItemIsDragEnabled
			if self._displayed.is_dir[self._visible[index.row()]]:
				result |= Qt.ItemIsDropEnabled
		return result
	def setData(self, index, value, role=Qt.EditRole):
		if role == Qt.EditRole and index.isValid():
			self.file_renamed.emit(self.url(index), value)
			return True
		return False
	def get_location(self):
		return self._location
	def get_columns(self):
		return self._columns
	def get_rows(self):
		return range(len(self._displayed.names)) if self._displayed else ()
	def url(self, index):
		if not index.isValid() or not 0 <= index.row() < len(self._visible):
			raise ValueError('Invalid index')
		return join(self._location, self._displayed.names[self._visible[index.row()]])
	def find(self, url):
		if self._names is None:
			self._names = {self._displayed.names[entry]: row
				for row, entry in enumerate(self._visible)} if self._displayed else {}
		if dirname(url) != self._location or basename(url) not in self._names:
			raise ValueError('%r is not in list' % url)
		return self.index(self._names[basename(url)], 0)
	def get_status_entries(self, selected_urls):
		"""Return fully loaded status entries for the currently displayed rows.

		Pending scans and unknown size or modification-time metadata do not
		affect this completeness guarantee.
		"""
		entries = []
		for index in self._visible:
			url = join(self._location, self._displayed.names[index])
			entries.append(StatusEntry(url, self._displayed.is_dir[index], True, url in selected_urls))
		return tuple(entries)
	@run_in_main_thread
	def sort(self, column, order=Qt.AscendingOrder):
		ascending = order == Qt.AscendingOrder
		if (column, ascending) != (self._sort_column, self._sort_ascending):
			self._sort_column, self._sort_ascending = column, ascending
			self.update()
	@run_in_main_thread
	def add_filter(self, predicate):
		self._filters.append(predicate)
		self.update()
	@run_in_main_thread
	def remove_filter(self, predicate):
		self._filters.remove(predicate)
		self.update()
	def reload(self):
		self._invalidate.emit()
	def notify_file_added(self, url):
		self.reload()
	def notify_file_removed(self, url):
		self.reload()
	def notify_file_changed(self, url):
		self._fs.clear_cache(url)
		self.reload()
	def notify_file_renamed(self, old_url, new_url):
		self.reload()
	@run_in_main_thread
	def refresh_files(self, urls):
		if self._shutdown:
			return
		self._text_cache.clear()
		columns = self._pending_columns if self._pending_columns is not None else self._columns
		if columns[self._sort_column].keys_depend_on_external_data:
			self._order_cache = None
			self.update()
		elif self._visible:
			self.dataChanged.emit(self.index(0, 0),
				self.index(len(self._visible) - 1, len(self._columns) - 1), [Qt.DisplayRole])
	def shutdown(self):
		if self._shutdown:
			return
		self._shutdown = True
		if self._icons is not None:
			self._icons.changed.disconnect(self._icons_changed)
		self._scan_jobs.cancel()
		self._view_jobs.cancel()
		if self._navigation_request:
			self._navigation_request.cancel()
		def cleanup():
			self._file_watcher.shutdown()
			if self._observation is not None:
				self._observation.close()
		Thread(target=cleanup, daemon=True).start()