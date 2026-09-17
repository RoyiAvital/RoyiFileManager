from fman.impl.model.model import Model
from fman.impl.model.drag_and_drop import DragAndDrop
from fman.impl.model.diff import ComputeDiff
from fman.impl.model.file_watcher import FileWatcher
from fman.impl.model.table import TableModel, Cell, Row
from fman.impl.util.qt.thread import run_in_main_thread
from fman.impl.util.url import is_pardir
from fman.url import dirname, splitscheme
from PyQt5.QtCore import pyqtSignal, QSortFilterProxyModel, Qt

import errno
import sip

class SortedFileSystemModel(QSortFilterProxyModel):

	location_changed = pyqtSignal(str)
	location_loaded = pyqtSignal(str)
	all_rows_loaded = pyqtSignal()
	file_renamed = pyqtSignal(str, str)
	files_dropped = pyqtSignal(list, str, bool)
	sort_order_changed = pyqtSignal(int, int)
	transaction_ended = pyqtSignal()
	files_changed = pyqtSignal()

	def __init__(self, parent, fs, null_location):
		super().__init__(parent)
		self._fs = fs
		self._null_location = null_location
		self._filters = []
		self._already_visited = set()
		self._num_rows_to_preload = 0
		self._navigation_request = None
		self._location_generation = 0
		self._extra_columns = {}
		self._default_columns = ()
		self.set_location(null_location)
		self._fs.file_removed.add_callback(self._on_file_removed)
	def set_num_rows_to_preload(self, preload_rows):
		self._num_rows_to_preload = preload_rows
	def set_location(
		self, url, sort_column='', ascending=True, callback=None, onerror=None
	):
		from fman.impl.navigation import current_request
		request = current_request()
		generation = self._begin_navigation(request)
		if request and not request.active:
			request.cancel()
			return
		if callback is None:
			callback = lambda: None
		if onerror is None:
			def onerror(*_):
				raise
		error_urls = {url}
		while True:
			try:
				self._set_location(url, sort_column, ascending, callback, request, generation)
				break
			except Exception as e:
				url = onerror(e, url)
				if url in error_urls:
					raise
				error_urls.add(url)
	@run_in_main_thread
	def _begin_navigation(self, request):
		if self._navigation_request and self._navigation_request is not request:
			self._navigation_request.cancel()
		self._navigation_request = request
		self._location_generation += 1
		return self._location_generation
	def _set_location(self, url, sort_column, ascending, callback, request=None, generation=None):
		try:
			url_resolved = self._fs.resolve(url)
		except FileNotFoundError:
			raise
		except OSError as e:
			if e.errno == errno.ENOENT:
				raise
			# For example: On Windows, Path(...).resolve()'ing on a directory
			# in a Cryptomator mapped drive gives:
			# 	OSError: [WinError 1] Incorrect function
			# But we can still list the dir's contents and do everything else
			# that's required. So ignore the error and continue:
			url_resolved = url
		if splitscheme(url_resolved)[0] != splitscheme(url)[0]:
			# In general, we do not want to simply rewrite the URL to its
			# resolved form. This is for instance because we don't want to
			# rewrite C:\Windows\System32 -> ...\SysWOW64. However, if the
			# file system changes, we do need to follow the rewrite to support
			# cases such as zip:/// resolving to file:///.
			url = url_resolved
		old_model = self.sourceModel()
		if old_model:
			if url == old_model.get_location() and request is None:
				callback()
				return
		columns = self._fs.get_columns(url)
		sort_col_index = 0
		if sort_column:
			column_names = [col.get_qualified_name() for col in columns]
			try:
				sort_col_index = column_names.index(sort_column)
			except ValueError:
				pass
		if url in self._already_visited and request is None:
			orig_callback = callback
			def callback():
				orig_callback()
				self.reload()
		self._set_location_main(
			url, columns, sort_col_index, ascending, callback, request, generation,
			sort_column=sort_column
		)
	@run_in_main_thread
	def _set_location_main(
		self, url, columns, sort_col_index, ascending, callback, request=None, generation=None,
		recreating=False, sort_column=''
	):
		if generation is not None and generation != self._location_generation:
			if request:
				request.cancel()
			return
		if request and not request.active:
			request.cancel()
			return
		self._default_columns = tuple(columns)
		columns = self._with_extra_columns(url, columns)
		if sort_column:
			names = [column.get_qualified_name() for column in columns]
			sort_col_index = names.index(sort_column) if sort_column in names else 0
		old_model = self.sourceModel()
		if old_model:
			old_model.shutdown()
			self._disconnect_signals(old_model)
		new_model = Model(
			self._fs, url, columns, sort_col_index, ascending,
			self._num_rows_to_preload, self._filters
		)
		new_model._columns_recreated = recreating
		if request:
			request.started = True
			new_model._navigation_request = request
			original_callback = callback
			def callback():
				if request.active and generation == self._location_generation:
					try:
						original_callback()
					except Exception as error:
						request.fail(error)
					else:
						request.finish('success')
				else:
					request.cancel()
		self.setSourceModel(new_model)
		self._connect_signals(new_model)
		self._already_visited.add(url)
		if not recreating:
			self.location_changed.emit(url)
		order = Qt.AscendingOrder if ascending else Qt.DescendingOrder
		self.sort_order_changed.emit(sort_col_index, order)
		# Start model at the very end to ensure the above signals, in particular
		# location_changed, are processed beforehand. The motivation for this is
		# that the FilterBar relies on this signal to clear its filter. If we
		# start the model before the FilterBar has had a chance to do this, then
		# the model may start loading files with the wrong filter.
		new_model.start(callback)
	def _with_extra_columns(self, url, defaults):
		names = [column.get_qualified_name() for column in defaults]
		extra_names = []
		for schemes in self._extra_columns.values():
			for name in schemes.get(splitscheme(url)[0], ()):
				if name not in names and name not in extra_names:
					extra_names.append(name)
		return tuple(defaults) + (self._fs.get_optional_columns(extra_names) if extra_names else ())
	def set_extra_columns(self, owner, schemes, sort_column, ascending, callback):
		if self._extra_columns.get(owner, {}) == schemes:
			return False
		if schemes:
			self._extra_columns[owner] = schemes
		else:
			self._extra_columns.pop(owner, None)
		url = self.get_location()
		columns = self._with_extra_columns(url, self._default_columns)
		if columns == tuple(self.get_columns()):
			return False
		names = [column.get_qualified_name() for column in columns]
		if sort_column not in names:
			sort_column, ascending = 'core.Name', True
		sort_index = names.index(sort_column) if sort_column in names else 0
		self._set_location_main(url, self._default_columns, sort_index, ascending, callback, recreating=True)
		return True
	def refresh_files(self, urls):
		self.sourceModel().refresh_files(tuple(urls))
	def setSourceModel(self, model):
		# Without this call, #sourceModel() sometimes returns None on Arch:
		sip.transferto(model, None)
		super().setSourceModel(model)
	def row_is_loaded(self, i):
		source_row = self.mapToSource(self.index(i, 0)).row()
		return self.sourceModel().row_is_loaded(source_row)
	def load_rows(self, rows, callback=None):
		source_rows = [self._map_row_to_source(row) for row in rows]
		self.sourceModel().load_rows(source_rows, callback)
	def _map_row_to_source(self, i):
		return self.mapToSource(self.index(i, 0)).row()
	def get_location(self):
		return self.sourceModel().get_location()
	def get_columns(self):
		return self.sourceModel().get_columns()
	def get_status_entries(self, selected_urls):
		return self.sourceModel().get_status_entries(selected_urls)
	def reload(self):
		self.sourceModel().reload()
	def sort(self, column, order=Qt.AscendingOrder):
		self.sourceModel().sort(column, order)
	def add_filter(self, filter_):
		self._filters.append(filter_)
		self.sourceModel().add_filter(filter_)
	def remove_filter(self, filter_):
		self._filters.remove(filter_)
		self.sourceModel().remove_filter(filter_)
	def url(self, index):
		return self.sourceModel().url(self.mapToSource(index))
	def find(self, url):
		return self.mapFromSource(self.sourceModel().find(url))
	def _on_file_removed(self, url):
		if is_pardir(url, self.get_location()):
			dir_ = dirname(url)
			if dir_ == url:
				self.set_location(self._null_location)
			else:
				try:
					self.set_location(dir_)
				except OSError:
					# In a perfect world, would like to only handle
					# FileNotFoundError here. But there can of course also be
					# other reasons. For example, when on a network share on
					# Windows, we may get a PermissionError trying to list a
					# parent directory we don't have access to. So catch all
					# OSErrors and in the worst case go to null://.
					self._on_file_removed(dir_)
	def _connect_signals(self, model):
		# Would prefer signal.connect(self.signal.emit) here. But PyQt doesn't
		# support it. So we need Python wrappers "_emit_...":
		model.location_loaded.connect(self._emit_location_loaded)
		model.all_rows_loaded.connect(self._emit_all_rows_loaded)
		model.files_changed.connect(self._emit_files_changed)
		model.location_disappeared.connect(self._on_file_removed)
		model.file_renamed.connect(self._emit_file_renamed)
		model.files_dropped.connect(self._emit_files_dropped)
		model.sort_order_changed.connect(self._emit_sort_order_changed)
		model.transaction_ended.add_callback(self._emit_transaction_ended)
	def _disconnect_signals(self, model):
		# Would prefer signal.disconnect(self.signal.emit) here. But PyQt
		# doesn't support it. So we need Python wrappers "_emit_...":
		model.location_loaded.disconnect(self._emit_location_loaded)
		model.all_rows_loaded.disconnect(self._emit_all_rows_loaded)
		model.files_changed.disconnect(self._emit_files_changed)
		model.location_disappeared.disconnect(self._on_file_removed)
		model.file_renamed.disconnect(self._emit_file_renamed)
		model.files_dropped.disconnect(self._emit_files_dropped)
		model.sort_order_changed.disconnect(self._emit_sort_order_changed)
		model.transaction_ended.remove_callback(self._emit_transaction_ended)
	def _emit_location_loaded(self, location):
		if not self.sourceModel()._columns_recreated:
			self.location_loaded.emit(location)
	def _emit_all_rows_loaded(self):
		self.all_rows_loaded.emit()
	def _emit_files_changed(self):
		if self.sender() is self.sourceModel():
			self.files_changed.emit()
	def _emit_file_renamed(self, old, new):
		self.file_renamed.emit(old, new)
	def _emit_files_dropped(self, urls, dest, is_copy):
		self.files_dropped.emit(urls, dest, is_copy)
	def _emit_sort_order_changed(self, column, order):
		self.sort_order_changed.emit(column, order)
	def _emit_transaction_ended(self):
		self.transaction_ended.emit()
	def __str__(self):
		return '<%s: %s>' % (self.__class__.__name__, self.get_location())