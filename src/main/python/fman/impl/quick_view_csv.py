"""QuickView Table View for CSV/TSV files, backed by the DuckDB helper process."""

from collections import OrderedDict
from pathlib import Path, PureWindowsPath
from PyQt5.QtCore import QAbstractTableModel, QEvent, QItemSelection, QItemSelectionModel, QModelIndex, QObject, QPoint, \
	QProcess, QProcessEnvironment, QTimer, Qt, pyqtSignal
from PyQt5.QtGui import QIcon, QKeySequence, QPalette
from PyQt5.QtWidgets import QAbstractItemView, QApplication, QCheckBox, QComboBox, QHBoxLayout, QHeaderView, QLabel, \
	QLineEdit, QMenu, QPlainTextEdit, QSizePolicy, QStackedLayout, QStyle, QTableView, QToolButton, QVBoxLayout, QWidget, \
	QWidgetAction

import os
import stat
import sys
import weakref


SUFFIXES = frozenset(('.csv', '.tsv'))
SETTINGS = 'Core Settings.json'
SETTING = 'quickview_table_max_file_mb'
PRESETS = ((512, 192), (1024, 384), (2048, 768))
DEFAULT_PRESET = 2048
TEXT_LIMIT = 2 * 1024 * 1024
PAGE_ROWS = 100
PAGE_CACHE_BYTES = 32 * 1024 * 1024
WINDOW_ROWS = 10000000
WINDOW_MARGIN = 1000000
START_TIMEOUT = 15000
CANCEL_TIMEOUT = 2000
FILTER_DELAY = 200
PENDING_PAGES = 6
DELIMITER_OPTIONS = (('auto', 'Auto'), ('comma', 'Comma'), ('semicolon', 'Semicolon'), ('tab', 'Tab'), ('pipe', 'Pipe'))
ENCODING_OPTIONS = (('auto', 'Auto'), ('utf-8', 'UTF-8'), ('utf-16', 'UTF-16 LE (BOM)'), ('latin-1', 'Latin-1'))
HEADER_OPTIONS = (('auto', 'Header: Auto'), ('yes', 'Header: First record'), ('no', 'Header: None'))
DEFAULT_OPTIONS = {'delimiter': 'auto', 'encoding': 'auto', 'header': 'auto'}


def is_table_file(url_or_path):
	return PureWindowsPath(url_or_path).suffix.lower() in SUFFIXES


def table_preset(settings):
	value = settings.get(SETTING) if isinstance(settings, dict) else None
	return value if type(value) is int and value in dict(PRESETS) else DEFAULT_PRESET


def load_table_preset():
	from fman import load_json
	try:
		return table_preset(load_json(SETTINGS, default={}))
	except (OSError, ValueError):
		return DEFAULT_PRESET


def save_table_preset(megabytes):
	from fman import load_json, save_json
	if megabytes not in dict(PRESETS):
		raise ValueError('Unsupported QuickView table limit')
	settings = load_json(SETTINGS, default={})
	if not isinstance(settings, dict):
		raise ValueError('%s must contain an object.' % SETTINGS)
	settings = dict(settings)
	settings[SETTING] = megabytes
	save_json(SETTINGS, settings)


def preset_limits(megabytes):
	return megabytes * 1000 * 1000, dict(PRESETS)[megabytes]


def cache_root():
	from fman import DATA_DIRECTORY
	return os.path.join(DATA_DIRECTORY, 'Cache', 'QuickViewCsv')


def notify_table_limit_changed():
	from fman.impl.util.qt.thread import run_in_main_thread
	@run_in_main_thread
	def notify():
		for widget in QApplication.topLevelWidgets():
			session = widget.__dict__.get('_quick_view_session')
			if session is not None:
				session.table_limit_changed()
	notify()


def load_csv_preview(request, canceled, resolve=None):
	"""Loader-thread routing: metadata-first Table View eligibility, or full-file Text View within 2 MiB."""
	from fman.impl.quick_view_images import ImageResult, _fingerprint
	from fman.url import as_human_readable, splitscheme
	try:
		if canceled():
			return None
		if not request.url or splitscheme(request.url)[0] != 'file://':
			return ImageResult(message='Only local files can be previewed', kind='error')
		if resolve is None:
			from fman.fs import resolve
		url = resolve(request.url)
		if canceled():
			return None
		if splitscheme(url)[0] != 'file://':
			return ImageResult(message='Only local files can be previewed', kind='error')
		path = as_human_readable(url)
		info = os.stat(path)
		if stat.S_ISDIR(info.st_mode):
			return ImageResult(message='Folder', kind='error')
		if not stat.S_ISREG(info.st_mode):
			return ImageResult(message='Not a regular file', kind='error')
		if request.mode == 'csv-text':
			if info.st_size > TEXT_LIMIT:
				return ImageResult(message='Text View is available only for CSV/TSV files up to 2 MiB.', kind='error')
			from dataclasses import replace
			from fman.impl.quick_view_text import load_text
			result = load_text(replace(request, mode='source'), canceled, resolve)
			if getattr(getattr(result, 'content', None), 'truncated', False):
				return ImageResult(message='The file grew beyond the 2 MiB Text View limit.', kind='error')
			return result
		limit = request.limit or preset_limits(DEFAULT_PRESET)[0]
		if info.st_size > limit:
			return ImageResult(kind='error', message='%s exceeds the %s MB Table View limit (%s bytes). Use "Set QuickView '
				'table limit" to choose a larger preset.' % (PureWindowsPath(path).name, format(limit // 1000000, ','),
				format(info.st_size, ',')))
		return ImageResult(kind='csv', path=path, fingerprint=_fingerprint(info))
	except (OSError, ValueError) as error:
		return ImageResult(message='Cannot preview file: ' + str(error), kind='error')


class CsvController(QObject):
	"""Owns one DuckDB helper process per window: one active operation, latest pending requests."""

	preview = pyqtSignal(int, object, object)
	imported = pyqtSignal(int, int)
	projected = pyqtSignal(int, int, int)
	page_ready = pyqtSignal(int, int, int, object)
	action_done = pyqtSignal(int, str, object, object)
	failed = pyqtSignal(int, str, str, str)

	def __init__(self, window=None, command=None):
		super().__init__(QApplication.instance())
		from _quick_view_pdf_worker import FrameDecoder
		self._decoder_type = FrameDecoder
		self._window = weakref.ref(window) if window is not None else lambda: None
		self._command = command
		self.process = None
		self.job = None
		self._epoch = 0
		self._operation = 0
		self._ready = False
		self._retiring = False
		self._disposed = False
		self._active = None
		self._canceling = False
		self._generation = None
		self._revision = 0
		self._open = None
		self._query = None
		self._action = None
		self._pages = []
		self._release = False
		self._owned = set()
		self._decoder = FrameDecoder()
		self.stderr = bytearray()
		self.deadline = QTimer(self)
		self.deadline.setSingleShot(True)
		self.deadline.timeout.connect(self._timeout)
		self.drain = QTimer(self)
		self.drain.setSingleShot(True)
		self.drain.timeout.connect(self._read)
		QApplication.instance().aboutToQuit.connect(self.shutdown)
		if window is not None:
			window.closed.connect(self.shutdown)

	@property
	def busy(self):
		return self._active is not None

	# -- requests ------------------------------------------------------------------------

	def open(self, generation, path, limit, memory, options):
		if self._disposed:
			return
		self._generation, self._revision = generation, 0
		self._open = dict(path=path, limit=limit, memory=memory, options=dict(options), cache=cache_root())
		self._query = self._action = None
		self._pages = []
		self._release = False
		self._supersede()
		self._ensure_process()
		self._pump()

	def query(self, generation, revision, filters, text, sort):
		if generation != self._generation or self._disposed:
			return
		self._revision = revision
		self._query = dict(filters=[list(item) for item in filters], text=text, sort=None if sort is None else list(sort))
		self._pages = []
		# Actions carry positions of the old projection; they must not run against the new one.
		self._action = None
		if self._active is not None and self._active['type'] in ('query', 'page', 'find', 'copy', 'cell'):
			self._cancel()
		self._pump()

	def request_page(self, generation, revision, start):
		if generation != self._generation or revision != self._revision or self._disposed:
			return
		if start in self._pages:
			self._pages.remove(start)
		self._pages.append(start)
		del self._pages[:-PENDING_PAGES]
		self._pump()

	def action(self, generation, kind, **values):
		if generation != self._generation or self._disposed:
			return
		self._action = dict(values, type=kind)
		if self._active is not None and self._active['type'] in ('find', 'copy', 'cell'):
			self._cancel()
		self._pump()

	def cancel_action(self):
		self._action = None
		if self._active is not None and self._active['type'] in ('find', 'copy', 'cell'):
			self._cancel()

	def invalidate(self):
		"""Drop the current table; the helper stays available for the next Table View file."""
		had_table = self._generation is not None
		self._generation = None
		self._open = self._query = self._action = None
		self._pages = []
		if had_table and self.process is not None and not self._retiring:
			self._release = True
			self._supersede()
			self._pump()

	def retire(self):
		"""Stop work and close the helper; its owned cache is removed by the helper or the next activation."""
		self._generation = None
		self._open = self._query = self._action = None
		self._pages = []
		self._release = False
		if self.process is not None and not self._retiring:
			self._retiring = True
			if self._ready and self._active is None and self.process.state() == QProcess.Running:
				self._send('close', CANCEL_TIMEOUT)
			else:
				self._kill()

	def shutdown(self):
		self._disposed = True
		self.retire()
		if self.process is None:
			self.deleteLater()

	# -- process -------------------------------------------------------------------------

	def _supersede(self):
		if self._active is not None:
			self._cancel()

	def _cancel(self):
		if self._active is None or self._canceling or self.process is None:
			return
		self._canceling = True
		from _quick_view_pdf_worker import encode_frame
		header = dict(type='cancel', epoch=self._epoch, generation=0, operation=self._active['operation'], revision=0)
		self.process.write(encode_frame(header))
		self.deadline.start(CANCEL_TIMEOUT)

	def _ensure_process(self):
		if self.process is not None:
			return
		self._epoch += 1
		self._ready = self._retiring = self._canceling = False
		self._active = None
		self._decoder = self._decoder_type()
		self.stderr.clear()
		process = self.process = QProcess(self)
		if self._command is not None:
			program, *arguments = self._command
		elif getattr(sys, 'frozen', False):
			program, arguments = sys.executable, ['--quick-view-csv-worker']
		else:
			entry = Path(__file__).resolve().parents[1] / 'main.py'
			program, arguments = sys.executable, ['-B', str(entry), '--quick-view-csv-worker']
			environment = QProcessEnvironment.systemEnvironment()
			environment.insert('PYTHONPATH', str(entry.parent.parent))
			process.setProcessEnvironment(environment)
		process.setWorkingDirectory(str(Path(sys.executable).parent))
		process.started.connect(self._started)
		process.readyReadStandardOutput.connect(self._read)
		process.readyReadStandardError.connect(self._read_error)
		process.finished.connect(self._finished)
		process.errorOccurred.connect(self._process_error)
		self.deadline.start(START_TIMEOUT)
		process.start(program, arguments)

	def _started(self):
		process = self.process
		if process is None:
			return
		if self._retiring:
			self._kill()
			return
		try:
			from fman.impl.quick_view_pdf import ProcessJob
			self.job = ProcessJob(int(process.processId()))
		except Exception:
			self._fail('Cannot safely start the Table View helper')

	def _send(self, kind, timeout=None, **values):
		from _quick_view_pdf_worker import encode_frame
		self._operation += 1
		self._active = dict(type=kind, epoch=self._epoch, generation=self._generation or 0,
			operation=self._operation, revision=self._revision, **values)
		self._canceling = False
		if timeout is None:
			self.deadline.stop()
		else:
			self.deadline.start(timeout)
		self.process.write(encode_frame(self._active))

	def _pump(self):
		if not self._ready or self._retiring or self._active is not None or self.process is None:
			return
		if self._release:
			self._release = False
			self._send('release', CANCEL_TIMEOUT)
		elif self._open is not None:
			values, self._open = self._open, None
			self._send('open', **values)
		elif self._generation is None:
			return
		elif self._query is not None:
			values, self._query = self._query, None
			self._send('query', **values)
		elif self._action is not None:
			values, self._action = self._action, None
			kind = values.pop('type')
			self._send(kind, **values)
		elif self._pages:
			start = self._pages.pop()
			self._send('page', start=start, count=PAGE_ROWS - start % PAGE_ROWS)

	def _read(self):
		process = self.process
		if process is None:
			return
		from _quick_view_pdf_worker import PdfError
		try:
			frames = self._decoder.feed(bytes(process.read(256 * 1024)))
			for header, payload in frames:
				if self.process is not process:
					return
				self._receive(header, payload)
		except (PdfError, TypeError, KeyError, ValueError, OverflowError):
			self._fail('Invalid Table View helper response')
			return
		if process is self.process and process.bytesAvailable() and not self.drain.isActive():
			self.drain.start(0)

	def _receive(self, header, payload):
		import json
		kind = header.get('type')
		if not self._ready:
			if kind != 'ready' or payload or self.job is None:
				raise ValueError('Invalid Table View helper startup')
			self._ready = True
			self.deadline.stop()
			self._pump()
			return
		active = self._active
		if active is None or any(type(header.get(key)) is not int or header[key] != active[key]
				for key in ('epoch', 'generation', 'operation', 'revision')):
			raise ValueError('Unexpected Table View helper response')
		data = json.loads(payload.decode('utf-8')) if payload else {}
		generation, revision, operation = active['generation'], active['revision'], active['type']
		current = generation == self._generation and not self._retiring
		if kind == 'preview' and operation == 'open':
			directory = header.get('directory')
			if isinstance(directory, str) and os.path.dirname(os.path.normcase(directory)) == os.path.normcase(active['cache']) \
					and os.path.basename(directory).startswith('s-'):
				self._owned.add(directory)
			if current:
				self.preview.emit(generation, header, data.get('rows', []))
			return
		self._active = None
		self._canceling = False
		self.deadline.stop()
		if kind == 'close':
			return
		if kind == 'error':
			if current and header.get('kind') != 'canceled':
				stage = 'open' if operation == 'open' else 'query' if operation in ('query', 'page') else operation
				if operation == 'open' or revision == self._revision:
					self.failed.emit(generation, stage, str(header.get('kind', '')), str(header.get('message', ''))[:1024])
		elif kind == 'imported' and current:
			self.imported.emit(generation, int(header['count']))
		elif kind == 'projection' and current and revision == self._revision:
			self.projected.emit(generation, revision, int(header['count']))
		elif kind == 'page' and current and revision == self._revision:
			self.page_ready.emit(generation, revision, int(header['start']), data.get('rows', []))
		elif kind in ('copy', 'cell', 'found') and current and revision == self._revision:
			self.action_done.emit(generation, kind, header, data)
		self._pump()

	def _read_error(self):
		process = self.process
		if process is None:
			return
		process.setReadChannel(QProcess.StandardError)
		data = bytes(process.read(65537))
		process.setReadChannel(QProcess.StandardOutput)
		self.stderr.extend(data[:max(0, 65536 - len(self.stderr))])

	def _timeout(self):
		if self._retiring:
			self._kill()
		else:
			self._fail('The Table View helper stopped responding' if self._ready else 'The Table View helper could not start')

	def _fail(self, message):
		generation = self._generation
		self._generation = None
		self._open = self._query = self._action = None
		self._pages = []
		if not self._retiring and generation is not None:
			self.failed.emit(generation, 'helper', 'resource', message)
		self._retiring = True
		self._kill()

	def _kill(self):
		self.deadline.stop()
		self.drain.stop()
		if self.job is not None:
			self.job.close()
			self.job = None
		if self.process is not None:
			self.process.kill()

	def _process_error(self, error):
		if self._retiring:
			return
		self._fail('The Table View helper could not start' if error == QProcess.FailedToStart else
			'The Table View helper stopped unexpectedly')
		if error == QProcess.FailedToStart:
			self._finished()

	def _finished(self, *_):
		if self.process is None:
			return
		if not self._retiring:
			self._fail('The Table View helper stopped unexpectedly')
		self.deadline.stop()
		self.drain.stop()
		if self.job is not None:
			self.job.close()
			self.job = None
		self.process.deleteLater()
		self.process = None
		self._active = None
		self._ready = self._retiring = self._canceling = False
		self._decoder = self._decoder_type()
		if self._owned:
			# A killed helper cannot remove its own cache; clean it off the Qt thread.
			from shutil import rmtree
			from threading import Thread
			owned, self._owned = tuple(self._owned), set()
			Thread(target=lambda: [rmtree(path, ignore_errors=True) for path in owned], daemon=True).start()
		if self._disposed:
			self.deleteLater()
		elif self._open is not None:
			self._ensure_process()


class _Row:
	__slots__ = ('rid', 'cells', 'truncated', 'highlights')

	def __init__(self, rid, cells, truncated):
		self.rid = rid
		self.cells = tuple(cell + '\u2026' if index in truncated else cell for index, cell in enumerate(cells))
		self.truncated = frozenset(truncated)
		self.highlights = ()


class CsvModel(QAbstractTableModel):
	"""Windowed view of a whole-file projection; data() reads cached pages only."""

	def __init__(self, parent):
		super().__init__(parent)
		self.labels = ()
		self.count = 0
		self.base = 0
		self.pages = OrderedDict()
		self.sizes = {}
		self.bytes = 0
		self.right_aligned = frozenset()
		self.request = lambda start: None

	def reset(self, labels, count, pages=()):
		self.beginResetModel()
		self.labels, self.count, self.base = tuple(labels), count, 0
		self.pages.clear()
		self.sizes.clear()
		self.bytes = 0
		for start, rows in pages:
			self._store(start, rows)
		self.endResetModel()

	def set_count(self, count):
		self.beginResetModel()
		self.count = count
		self.base = min(self.base, max(0, count - WINDOW_ROWS))
		self.endResetModel()

	def shift(self, base):
		base = max(0, min(base, max(0, self.count - WINDOW_ROWS)))
		if base == self.base:
			return False
		self.beginResetModel()
		self.base = base
		self.endResetModel()
		return True

	def rowCount(self, parent=QModelIndex()):
		return 0 if parent.isValid() else min(WINDOW_ROWS, max(0, self.count - self.base))

	def columnCount(self, parent=QModelIndex()):
		return 0 if parent.isValid() else len(self.labels)

	def row(self, position):
		start = position - position % PAGE_ROWS
		rows = self.pages.get(start)
		if rows is None:
			self.request(start)
			return None
		self.pages.move_to_end(start)
		offset = position - start
		if offset < len(rows):
			return rows[offset]
		if position < self.count:
			# The helper shortens pages of wide rows to its frame budget; fetch the rest of this page.
			self.request(start + len(rows))
		return None

	def data(self, index, role=Qt.DisplayRole):
		if not index.isValid():
			return None
		row = self.row(self.base + index.row())
		if role == Qt.UserRole:
			return row if row is not None else _Row(0, ('',) * len(self.labels), ())
		if role == Qt.UserRole + 1:
			return ()
		if row is None:
			return None
		if role in (Qt.DisplayRole, Qt.ToolTipRole, Qt.AccessibleTextRole):
			return row.cells[index.column()]
		return None

	def headerData(self, section, orientation, role=Qt.DisplayRole):
		if role != Qt.DisplayRole:
			return None
		if orientation == Qt.Horizontal:
			return self.labels[section] if 0 <= section < len(self.labels) else None
		start = self.base + section
		rows = self.pages.get(start - start % PAGE_ROWS)
		offset = start % PAGE_ROWS
		return format(rows[offset].rid, ',') if rows is not None and offset < len(rows) else ''

	def add_page(self, start, rows):
		self._store(start, rows)
		first, last = start - self.base, start + len(rows) - 1 - self.base
		if last >= 0 and first < self.rowCount():
			first, last = max(0, first), min(self.rowCount() - 1, last)
			self.dataChanged.emit(self.index(first, 0), self.index(last, max(0, len(self.labels) - 1)))
			self.headerDataChanged.emit(Qt.Vertical, first, last)

	def _store(self, start, rows):
		rows = tuple(_Row(rid, cells, truncated) for rid, cells, truncated in rows)
		key = start - start % PAGE_ROWS
		if key != start:
			previous = self.pages.get(key)
			if previous is None or key + len(previous) != start:
				return
			rows = (previous + rows)[:PAGE_ROWS]
		start = key
		size = sum(sum(len(cell) for cell in row.cells) * 2 + 96 for row in rows)
		if start in self.pages:
			self.bytes -= self.sizes.pop(start)
		self.pages[start] = rows
		self.sizes[start] = size
		self.bytes += size
		while self.bytes > PAGE_CACHE_BYTES and len(self.pages) > 1:
			old, _ = self.pages.popitem(last=False)
			self.bytes -= self.sizes.pop(old)


class _Schema:
	def __init__(self, labels):
		from fman.impl.ui.table_data import QuickTableColumn
		self.columns = tuple(QuickTableColumn(label) for label in labels)
		self.headers = tuple(labels)
		self.dates = None

	def column(self, index):
		return self.columns[index]


class CsvTableView(QTableView):
	def __init__(self, preview):
		super().__init__(preview)
		self.preview = preview

	def keyPressEvent(self, event):
		modifiers = event.modifiers() & (Qt.ControlModifier | Qt.ShiftModifier | Qt.AltModifier)
		model = self.model()
		if event.key() in (Qt.Key_Home, Qt.Key_End) and modifiers & Qt.ControlModifier and model.count > WINDOW_ROWS:
			self.preview.go_to(0 if event.key() == Qt.Key_Home else model.count - 1, self.currentIndex().column())
			event.accept()
			return
		super().keyPressEvent(event)


class CsvPreview(QWidget):
	"""Read-only, whole-file Table View that mirrors QuickTable's header, filter and sort presentation."""

	mode_requested = pyqtSignal(str)
	options_changed = pyqtSignal(object)
	retry_requested = pyqtSignal()

	def __init__(self, source, parent):
		from fman.impl.ui.table import TableDelegate, TableHeader
		super().__init__(parent)
		self.source = source
		self.controller = None
		self.generation = None
		self.revision = 0
		self.filters = {}
		self.text = ''
		self.sort_column = None
		self.sort_descending = False
		self.text_matching = 'fuzzy'
		self.pending = False
		self.ready = False
		self.labels = ()
		self.schema = _Schema(())
		self.filter_menu = None
		self.restore = None
		self.inspected = None
		self.find_target = None
		layout = QVBoxLayout(self)
		layout.setContentsMargins(0, 0, 0, 0)
		layout.setSpacing(4)
		top = QHBoxLayout()
		self.query = QLineEdit(self)
		self.query.setPlaceholderText('Filter all columns')
		self.query.setAccessibleName('Filter all columns')
		self.query.installEventFilter(self)
		top.addWidget(self.query, 1)
		self.option_boxes = {}
		for name, options in (('delimiter', DELIMITER_OPTIONS), ('encoding', ENCODING_OPTIONS), ('header', HEADER_OPTIONS)):
			box = QComboBox(self)
			box.setAccessibleName('Table ' + name)
			box.setToolTip({'delimiter': 'Field delimiter', 'encoding': 'Table View encoding (strict)',
				'header': 'Use the first record as column labels'}[name])
			for value, label in options:
				box.addItem(label, value)
			box.setFocusPolicy(Qt.NoFocus)
			box.activated.connect(self._options_activated)
			self.option_boxes[name] = box
			top.addWidget(box)
		self.retry = QToolButton(self)
		self.retry.setText('Retry')
		self.retry.setToolTip('Retry Table View with the selected options')
		self.retry.setFocusPolicy(Qt.NoFocus)
		self.retry.clicked.connect(self.retry_requested)
		top.addWidget(self.retry)
		layout.addLayout(top)
		self.stack = QStackedLayout()
		self.view = CsvTableView(self)
		self.view.setObjectName('results-table-view')
		self.model = CsvModel(self)
		self.model.request = self._request_page
		self.header = TableHeader(self)
		self.view.setHorizontalHeader(self.header)
		self.view.setModel(self.model)
		self.view.setItemDelegate(TableDelegate(self.view))
		self.view.setSelectionMode(QAbstractItemView.ContiguousSelection)
		self.view.setSelectionBehavior(QAbstractItemView.SelectItems)
		self.view.setCornerButtonEnabled(False)
		self.view.setEditTriggers(QAbstractItemView.NoEditTriggers)
		self.view.setTabKeyNavigation(False)
		self.view.setAlternatingRowColors(True)
		self.view.setWordWrap(False)
		self.view.setShowGrid(False)
		self.view.setAccessibleName('QuickView table')
		self.view.installEventFilter(self)
		self.view.setContextMenuPolicy(Qt.CustomContextMenu)
		self.view.customContextMenuRequested.connect(self._cell_menu)
		vertical = self.view.verticalHeader()
		vertical.setSectionResizeMode(QHeaderView.Fixed)
		vertical.setDefaultSectionSize(max(26, self.fontMetrics().height() + 10))
		vertical.setDefaultAlignment(Qt.AlignRight | Qt.AlignVCenter)
		vertical.setToolTip('Source record number')
		self.header.setSectionsMovable(False)
		self.header.setSectionResizeMode(QHeaderView.Interactive)
		self.header.setMinimumSectionSize(48)
		self.header.setStretchLastSection(True)
		self.header.setContextMenuPolicy(Qt.CustomContextMenu)
		self.header.customContextMenuRequested.connect(self._header_menu)
		# Header clicks sort, as in QuickTable; they must not also select whole columns.
		for signal in (self.header.sectionPressed, self.header.sectionEntered):
			try:
				signal.disconnect()
			except TypeError:
				pass
		self.header.sectionClicked.connect(self.sort_by)
		self.header.filter_requested.connect(lambda column: self.open_filter_menu(column))
		self.view.verticalScrollBar().valueChanged.connect(self._scrolled)
		self.view.selectionModel().currentChanged.connect(self._current_changed)
		self.frozen = None
		self.message = QLabel(self)
		self.message.setTextFormat(Qt.PlainText)
		self.message.setWordWrap(True)
		self.message.setAlignment(Qt.AlignCenter)
		self.message.setMargin(16)
		self.stack.addWidget(self.view)
		self.stack.addWidget(self.message)
		layout.addLayout(self.stack, 1)
		self.find_bar = QWidget(self)
		find_layout = QHBoxLayout(self.find_bar)
		find_layout.setContentsMargins(0, 0, 0, 0)
		self.find_input = QLineEdit(self.find_bar)
		self.find_input.setPlaceholderText('Find in table')
		self.find_input.setAccessibleName('Find in table')
		self.find_input.installEventFilter(self)
		self.find_input.returnPressed.connect(self.find_next)
		find_layout.addWidget(self.find_input, 1)
		self.find_column = QCheckBox('Current column', self.find_bar)
		self.find_case = QCheckBox('Match case', self.find_bar)
		for box in (self.find_column, self.find_case):
			box.setFocusPolicy(Qt.NoFocus)
			find_layout.addWidget(box)
		for label, icon, callback in (('Previous match', QStyle.SP_ArrowUp, lambda: self.find_next(True)),
				('Next match', QStyle.SP_ArrowDown, self.find_next), ('Close Find', QStyle.SP_DialogCloseButton, self.close_find)):
			button = QToolButton(self.find_bar)
			button.setIcon(self.style().standardIcon(icon))
			button.setToolTip(label)
			button.setAccessibleName(label)
			button.setFocusPolicy(Qt.NoFocus)
			button.clicked.connect(lambda checked=False, action=callback: action())
			find_layout.addWidget(button)
		self.find_state = QLabel(self.find_bar)
		find_layout.addWidget(self.find_state)
		layout.addWidget(self.find_bar)
		self.find_bar.hide()
		self.inspector = QPlainTextEdit(self)
		self.inspector.setReadOnly(True)
		self.inspector.setAccessibleName('Selected cell')
		self.inspector.setMaximumHeight(160)
		self.inspector.installEventFilter(self)
		self.inspector.hide()
		layout.addWidget(self.inspector)
		footer = QHBoxLayout()
		self.text_button = QToolButton(self)
		self.text_button.setText('Text View')
		self.text_button.setToolTip('Show the file as text (files up to 2 MiB)')
		self.text_button.setFocusPolicy(Qt.NoFocus)
		self.text_button.clicked.connect(lambda: self.mode_requested.emit('csv-text'))
		footer.addWidget(self.text_button)
		self.status = QLabel(self)
		self.status.setTextFormat(Qt.PlainText)
		self.status.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
		footer.addWidget(self.status, 1)
		self.inspect_button = QToolButton(self)
		self.inspect_button.setText('Inspect')
		self.inspect_button.setToolTip('Show the complete selected cell')
		self.inspect_button.setCheckable(True)
		self.inspect_button.setFocusPolicy(Qt.NoFocus)
		self.inspect_button.toggled.connect(self.set_inspector)
		footer.addWidget(self.inspect_button)
		layout.addLayout(footer)
		self.filter_timer = QTimer(self)
		self.filter_timer.setSingleShot(True)
		self.filter_timer.setInterval(FILTER_DELAY)
		self.filter_timer.timeout.connect(self.submit_query)
		self.query.textChanged.connect(lambda: self.filter_timer.start())
		self.inspect_timer = QTimer(self)
		self.inspect_timer.setSingleShot(True)
		self.inspect_timer.setInterval(120)
		self.inspect_timer.timeout.connect(self._inspect)
		self.setFocusProxy(self.view)
		self.clear()

	# -- QuickTable header contract -------------------------------------------------------

	def filterable(self, column):
		return self.ready

	def sortable(self, column):
		return self.ready

	def header_tooltip(self, column, on_filter):
		label = self.labels[column] if 0 <= column < len(self.labels) else ''
		if on_filter:
			active = self.filters.get(column)
			return ('Filtered: ' + active.description) if active else 'Filter ' + label + ' (Alt+Down)'
		if self.sort_column == column:
			return '%s: sorted %s; click to %s' % (label, 'descending' if self.sort_descending else 'ascending',
				'restore the original order' if self.sort_descending else 'sort descending')
		return 'Sort by ' + label

	# -- lifecycle -----------------------------------------------------------------------

	def clear(self, message=''):
		self.close_filter_menu()
		if self.frozen is not None:
			self.toggle_frozen()
		self.filter_timer.stop()
		self.generation = None
		self.ready = self.pending = False
		self.filters = {}
		self.text = ''
		self.sort_column = None
		self.sort_descending = False
		self.restore = None
		self.inspected = None
		self.find_target = None
		self.labels = ()
		self.schema = _Schema(())
		self.query.blockSignals(True)
		self.query.clear()
		self.query.blockSignals(False)
		self.model.reset((), 0)
		self.inspector.clear()
		self.find_state.clear()
		self.status.setText(message)
		self.retry.hide()
		self.stack.setCurrentWidget(self.view)
		self._set_controls_enabled(False)

	def start(self, controller, generation, options, text_available, state=None):
		self.clear('Validating\u2026')
		self.controller, self.generation = controller, generation
		self.restore = state
		self.set_options(options)
		self.text_button.setVisible(text_available)

	def show_error(self, message, text_available, options):
		self.clear()
		self.set_options(options)
		self.text_button.setVisible(text_available)
		self.message.setText('Table View unavailable: ' + message)
		self.stack.setCurrentWidget(self.message)
		self.status.setText('Table View unavailable')
		self.retry.show()
		for box in self.option_boxes.values():
			box.setEnabled(True)

	def set_options(self, options):
		for name, box in self.option_boxes.items():
			box.setCurrentIndex(max(0, box.findData(options.get(name, 'auto'))))

	def options(self):
		return {name: box.currentData() for name, box in self.option_boxes.items()}

	def state(self):
		if not self.ready:
			return self.restore
		index = self.view.currentIndex()
		return dict(filters=dict(self.filters), text=self.query.text(), sort=(self.sort_column, self.sort_descending),
			position=self.model.base + index.row() if index.isValid() else 0, column=index.column() if index.isValid() else 0)

	def _set_controls_enabled(self, enabled):
		self.query.setEnabled(enabled)
		for box in self.option_boxes.values():
			box.setEnabled(True)

	# -- controller events ---------------------------------------------------------------

	def show_preview(self, header, rows):
		self.labels = tuple(header.get('labels', ()))
		self.schema = _Schema(self.labels)
		self.set_options(dict(self.options(), **{name: value for name, value in (
			('delimiter', {',': 'comma', ';': 'semicolon', '\t': 'tab', '|': 'pipe'}.get(header.get('delimiter'))),
			('encoding', header.get('encoding')), ('header', 'yes' if header.get('header') else 'no')) if value}))
		pages = [(start, rows[start:start + PAGE_ROWS]) for start in range(0, len(rows), PAGE_ROWS)]
		self.model.reset(self.labels, len(rows), pages)
		self._autosize(rows)
		width = self.fontMetrics().horizontalAdvance('0' * 12) + 16
		self.view.verticalHeader().setFixedWidth(width)
		self.status.setText('Validating\u2026 showing the first {:,} records'.format(len(rows)))
		self.stack.setCurrentWidget(self.view)
		if rows:
			self.view.setCurrentIndex(self.model.index(0, 0))

	def show_imported(self, count):
		self.ready = True
		self._set_controls_enabled(True)
		self.model.set_count(count)
		self.header.viewport().update()
		self.view.verticalHeader().setFixedWidth(self.fontMetrics().horizontalAdvance(format(max(count, 1), ',') + '00') + 16)
		state, self.restore = self.restore, None
		if state:
			self.filters = dict(state.get('filters') or {})
			self.query.blockSignals(True)
			self.query.setText(state.get('text', ''))
			self.query.blockSignals(False)
			self.sort_column, self.sort_descending = state.get('sort', (None, False))
			self.find_target = (state.get('position', 0), state.get('column', 0))
			if self.filters or self.query.text() or self.sort_column is not None:
				self.submit_query()
				return
			self.go_to(*self.find_target)
			self.find_target = None
		self._update_status()

	def show_projection(self, revision, count):
		if revision != self.revision:
			return
		self.pending = False
		self.model.reset(self.labels, count)
		self.header.viewport().update()
		if self.find_target is not None:
			self.go_to(*self.find_target)
			self.find_target = None
		elif count:
			self.view.setCurrentIndex(self.model.index(0, 0))
		self._update_status()

	def add_page(self, revision, start, rows):
		if revision == self.revision and not self.pending:
			self.model.add_page(start, rows)
			if self.inspected is None and self.inspector.isVisible():
				self.inspect_timer.start()

	def query_failed(self, message):
		self.pending = False
		self._update_status('Query failed: ' + message)

	def action_done(self, kind, header, payload):
		if kind == 'copy':
			QApplication.clipboard().setText(payload.get('text', ''))
			self._update_status('Copied to the clipboard')
		elif kind == 'cell':
			if self.inspected == (header.get('position'), header.get('column')):
				self.inspector.setPlainText(payload.get('text', ''))
		elif kind == 'found':
			position, column = header.get('position', -1), header.get('column', -1)
			if position < 0:
				self.find_state.setText('Not found')
			else:
				self.find_state.setText('Wrapped' if header.get('wrapped') else '')
				self.go_to(position, column)

	def action_failed(self, message):
		self._update_status(message)
		if self.find_bar.isVisible():
			self.find_state.setText('Find failed')

	def _update_status(self, note=''):
		if not self.ready:
			return
		total = self.model.count
		if self.pending:
			text = 'Updating\u2026'
		elif self.filters or self.query.text():
			text = '{:,} matching records'.format(total)
			if self.filters:
				text += ' \u00b7 %d column filter%s' % (len(self.filters), '' if len(self.filters) == 1 else 's')
		else:
			text = '{:,} records'.format(total)
		if self.sort_column is not None and not self.pending:
			text += ' \u00b7 sorted by ' + self.labels[self.sort_column]
		self.status.setText(' \u00b7 '.join(part for part in (text, note) if part))

	# -- queries -------------------------------------------------------------------------

	def submit_query(self):
		self.filter_timer.stop()
		if not self.ready or self.controller is None:
			return
		self.revision += 1
		self.pending = True
		self.close_filter_menu()
		self.controller.query(self.generation, self.revision,
			[(column, item.operator, item.first) for column, item in sorted(self.filters.items())],
			self.query.text(), None if self.sort_column is None else (self.sort_column, self.sort_descending))
		self.header.viewport().update()
		self._update_status()

	def _request_page(self, start):
		if self.controller is not None and self.ready and not self.pending:
			self.controller.request_page(self.generation, self.revision, start)

	def sort_by(self, column):
		if not self.ready:
			return
		if self.sort_column != column:
			self.set_sort(column, False)
		elif not self.sort_descending:
			self.set_sort(column, True)
		else:
			self.set_sort(None)

	def set_sort(self, column, descending=False):
		self.sort_column, self.sort_descending = column, bool(descending) and column is not None
		self.submit_query()

	def set_column_filter(self, column, column_filter):
		if column_filter is None:
			self.filters.pop(column, None)
		else:
			self.filters[column] = column_filter
		self.submit_query()

	def clear_all_filters(self):
		self.filters.clear()
		self.query.blockSignals(True)
		self.query.clear()
		self.query.blockSignals(False)
		self.submit_query()

	def open_filter_menu(self, column=None, position=None):
		from fman.impl.ui.table import FilterEditor, defer, table_icon
		if not self.ready:
			return None
		if column is None:
			column = max(0, self.view.currentIndex().column())
		if not 0 <= column < len(self.labels):
			return None
		self.close_filter_menu()
		menu = QMenu(self)
		menu.setObjectName('table-filter-menu')
		editor = FilterEditor(self, column, self.filters.get(column), menu)
		holder = QWidgetAction(menu)
		holder.setDefaultWidget(editor)
		menu.addAction(holder)
		menu.addSeparator()
		color = self.palette().color(QPalette.WindowText)
		ratio = self.devicePixelRatioF()
		apply = menu.addAction(QIcon(table_icon('filter', color, ratio)), 'Apply Filter')
		apply.triggered.connect(lambda: editor.compiled is not None and self.set_column_filter(column, editor.compiled))
		clear = menu.addAction('Clear Filter', lambda: self.set_column_filter(column, None))
		clear.setEnabled(column in self.filters)
		clear_all = menu.addAction('Clear All Filters', self.clear_all_filters)
		clear_all.setEnabled(bool(self.filters or self.query.text()))
		menu.addSeparator()
		menu.addAction(QIcon(table_icon('sort-ascending', color, ratio)), 'Sort Ascending', lambda: self.set_sort(column, False))
		menu.addAction(QIcon(table_icon('sort-descending', color, ratio)), 'Sort Descending', lambda: self.set_sort(column, True))
		original = menu.addAction('Original Order', lambda: self.set_sort(None))
		original.setEnabled(self.sort_column is not None)
		editor.validity_changed.connect(apply.setEnabled)
		apply.setEnabled(editor.compiled is not None)
		def submit():
			if editor.compiled is not None:
				menu.close()
				self.set_column_filter(column, editor.compiled)
		editor.submitted.connect(submit)
		def hidden():
			if self.filter_menu is menu:
				self.filter_menu = None
			defer(self, lambda: self.view.setFocus(Qt.PopupFocusReason))
		menu.aboutToHide.connect(hidden)
		menu.aboutToHide.connect(menu.deleteLater)
		self.filter_menu = menu
		if position is None:
			x = self.header.sectionViewportPosition(column)
			position = self.header.viewport().mapToGlobal(QPoint(max(0, x), self.header.height()))
		menu.popup(position)
		defer(editor, editor.focus_first)
		return menu

	def close_filter_menu(self):
		menu, self.filter_menu = self.filter_menu, None
		if menu is not None:
			menu.close()

	# -- navigation, copy, find, inspect ---------------------------------------------------

	def go_to(self, position, column=0):
		count = self.model.count
		if not count:
			return
		position = max(0, min(position, count - 1))
		if not self.model.base <= position < self.model.base + WINDOW_ROWS:
			self.model.shift(position - WINDOW_ROWS // 2)
		index = self.model.index(position - self.model.base, max(0, min(column, len(self.labels) - 1)))
		self.view.setCurrentIndex(index)
		self.view.scrollTo(index, QAbstractItemView.PositionAtCenter)

	def _scrolled(self, value):
		model = self.model
		if model.count <= WINDOW_ROWS:
			return
		top = self.view.rowAt(0)
		if top < 0:
			return
		if top > WINDOW_ROWS - WINDOW_MARGIN and model.base + WINDOW_ROWS < model.count:
			self.go_to(model.base + top + WINDOW_MARGIN // 2)
		elif top < WINDOW_MARGIN // 10 and model.base > 0:
			self.go_to(model.base + top - WINDOW_MARGIN // 2)

	def selection_range(self):
		ranges = self.view.selectionModel().selection()
		if ranges.isEmpty():
			index = self.view.currentIndex()
			if not index.isValid():
				return None
			top = bottom = index.row()
			left = right = index.column()
		else:
			span = ranges[0]
			top, bottom, left, right = span.top(), span.bottom(), span.left(), span.right()
		columns = [column for column in range(left, right + 1) if not self.view.isColumnHidden(column)]
		return [self.model.base + top, self.model.base + bottom + 1], columns

	def copy(self, headers=False, whole_rows=False):
		selection = self.selection_range()
		if selection is None or not self.ready or self.pending:
			self._update_status('Copy is unavailable until the table is ready')
			return
		rows, columns = selection
		if whole_rows:
			columns = [column for column in range(len(self.labels)) if not self.view.isColumnHidden(column)]
		self.controller.action(self.generation, 'copy', rows=rows, columns=columns, headers=headers, labels=list(self.labels))
		self._update_status('Copying\u2026')

	def select_column(self, column):
		model = self.model
		if model.rowCount():
			selection = QItemSelection(model.index(0, column), model.index(model.rowCount() - 1, column))
			self.view.selectionModel().select(selection, QItemSelectionModel.ClearAndSelect)

	def open_find(self):
		self.find_bar.show()
		self.find_input.setFocus()
		self.find_input.selectAll()

	def close_find(self):
		self.find_bar.hide()
		self.find_state.clear()
		self.view.setFocus()

	def find_next(self, backwards=False):
		text = self.find_input.text()
		if not text:
			self.open_find()
			return
		if not self.ready or self.pending:
			self.find_state.setText('Table is not ready')
			return
		index = self.view.currentIndex()
		if index.isValid():
			position, current = self.model.base + index.row(), index.column()
		else:
			position, current = (self.model.count - 1, len(self.labels)) if backwards else (0, -1)
		column = max(0, index.column()) if self.find_column.isChecked() else None
		self.find_state.setText('Searching\u2026')
		self.controller.action(self.generation, 'find', text=text, column=column, case=self.find_case.isChecked(),
			position=max(0, position), current=current, backwards=backwards)

	def set_inspector(self, visible):
		self.inspector.setVisible(visible)
		if visible:
			self._inspect()

	def _current_changed(self, current, previous):
		if self.inspector.isVisible():
			self.inspect_timer.start()

	def _inspect(self):
		index = self.view.currentIndex()
		if not index.isValid() or not self.inspector.isVisible():
			return
		position, column = self.model.base + index.row(), index.column()
		row = self.model.row(position)
		if row is None:
			self.inspected = None
			return
		self.inspected = (position, column)
		if column in row.truncated and self.ready and not self.pending:
			self.inspector.setPlainText('Loading the complete value\u2026')
			self.controller.action(self.generation, 'cell', position=position, column=column)
		else:
			self.inspector.setPlainText(row.cells[column])

	def _autosize(self, rows):
		metrics = self.fontMetrics()
		for column, label in enumerate(self.labels):
			width = metrics.horizontalAdvance(label) + 52
			for row in rows[:50]:
				width = max(width, metrics.horizontalAdvance(row[1][column][:80]) + 20)
			self.view.setColumnWidth(column, max(60, min(width, 360)))

	# -- menus and freezing --------------------------------------------------------------

	def _cell_menu(self, position):
		menu = QMenu(self)
		ready = self.ready and not self.pending
		for label, callback in (('Copy', self.copy), ('Copy with headers', lambda: self.copy(True)),
				('Copy rows', lambda: self.copy(whole_rows=True))):
			action = menu.addAction(label, callback)
			action.setEnabled(ready)
		menu.addSeparator()
		index = self.view.indexAt(position)
		column = index.column() if index.isValid() else self.view.currentIndex().column()
		select = menu.addAction('Select column', lambda: self.select_column(column))
		select.setEnabled(ready and column >= 0)
		inspect = menu.addAction('Inspect cell')
		inspect.setCheckable(True)
		inspect.setChecked(self.inspect_button.isChecked())
		inspect.toggled.connect(self.inspect_button.setChecked)
		menu.addAction('Find\u2026', self.open_find).setEnabled(ready)
		freeze = menu.addAction('Freeze first column', self.toggle_frozen)
		freeze.setCheckable(True)
		freeze.setChecked(self.frozen is not None)
		menu.exec_(self.view.viewport().mapToGlobal(position))

	def _header_menu(self, position):
		menu = QMenu(self)
		visible = [column for column in range(len(self.labels)) if not self.view.isColumnHidden(column)]
		for column, label in enumerate(self.labels):
			action = menu.addAction(label)
			action.setCheckable(True)
			action.setChecked(column in visible)
			action.setEnabled(not (column in visible and len(visible) == 1))
			action.toggled.connect(lambda shown, value=column: self.view.setColumnHidden(value, not shown))
		menu.addSeparator()
		menu.addAction('Show all columns', lambda: [self.view.setColumnHidden(column, False) for column in range(len(self.labels))])
		menu.exec_(self.header.viewport().mapToGlobal(position))

	def toggle_frozen(self):
		if self.frozen is not None:
			self.header.sectionResized.disconnect(self._frozen_geometry)
			self.frozen.deleteLater()
			self.frozen = None
			return
		from fman.impl.ui.table import TableDelegate
		frozen = self.frozen = QTableView(self.view)
		frozen.setModel(self.model)
		frozen.setSelectionModel(self.view.selectionModel())
		frozen.setItemDelegate(TableDelegate(frozen))
		frozen.setFocusPolicy(Qt.NoFocus)
		frozen.verticalHeader().hide()
		frozen.verticalHeader().setDefaultSectionSize(self.view.verticalHeader().defaultSectionSize())
		frozen.horizontalHeader().setSectionResizeMode(QHeaderView.Fixed)
		frozen.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
		frozen.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
		frozen.setShowGrid(False)
		frozen.setAlternatingRowColors(True)
		frozen.setSelectionMode(QAbstractItemView.ContiguousSelection)
		frozen.setEditTriggers(QAbstractItemView.NoEditTriggers)
		for column in range(1, len(self.labels)):
			frozen.setColumnHidden(column, True)
		frozen.verticalScrollBar().valueChanged.connect(self.view.verticalScrollBar().setValue)
		self.view.verticalScrollBar().valueChanged.connect(frozen.verticalScrollBar().setValue)
		self.header.sectionResized.connect(self._frozen_geometry)
		frozen.show()
		self._frozen_geometry()

	def _frozen_geometry(self, *_):
		frozen = self.frozen
		if frozen is None:
			return
		frozen.setColumnWidth(0, self.view.columnWidth(0))
		frozen.horizontalHeader().setFixedHeight(self.header.height())
		frozen.setGeometry(self.view.verticalHeader().width() + self.view.frameWidth(), self.view.frameWidth(),
			self.view.columnWidth(0), self.view.viewport().height() + self.header.height())
		frozen.verticalScrollBar().setValue(self.view.verticalScrollBar().value())

	def resizeEvent(self, event):
		super().resizeEvent(event)
		self._frozen_geometry()

	# -- keyboard ------------------------------------------------------------------------

	def _options_activated(self, *_):
		self.options_changed.emit(self.options())

	def eventFilter(self, watched, event):
		if event.type() == QEvent.ShortcutOverride and watched in (self.view, self.query, self.find_input, self.inspector):
			event.accept()
			return True
		if event.type() != QEvent.KeyPress:
			return False
		key, modifiers = event.key(), event.modifiers() & (Qt.ControlModifier | Qt.ShiftModifier | Qt.AltModifier | Qt.MetaModifier)
		if key in (Qt.Key_Tab, Qt.Key_Backtab, Qt.Key_Escape):
			if key == Qt.Key_Escape and watched is self.find_input:
				self.close_find()
			elif key == Qt.Key_Escape and watched is self.query and self.query.text():
				self.query.clear()
			else:
				self.source.setFocus()
		elif key == Qt.Key_F and modifiers == Qt.ControlModifier:
			self.query.setFocus()
			self.query.selectAll()
		elif key == Qt.Key_F3 and modifiers in (Qt.NoModifier, Qt.ShiftModifier):
			if self.find_bar.isVisible() and self.find_input.text():
				self.find_next(modifiers == Qt.ShiftModifier)
			else:
				self.open_find()
		elif key == Qt.Key_Down and modifiers == Qt.AltModifier and watched is self.view:
			self.open_filter_menu()
		elif key == Qt.Key_C and modifiers in (Qt.ControlModifier, Qt.ControlModifier | Qt.ShiftModifier) and watched is self.view:
			self.copy(headers=modifiers & Qt.ShiftModifier == Qt.ShiftModifier)
		elif watched is self.view and (key in (Qt.Key_Left, Qt.Key_Right, Qt.Key_Up, Qt.Key_Down, Qt.Key_Home, Qt.Key_End,
				Qt.Key_PageUp, Qt.Key_PageDown) and not modifiers & (Qt.AltModifier | Qt.MetaModifier) or
				(key == Qt.Key_A and modifiers == Qt.ControlModifier)):
			return False
		elif watched in (self.query, self.find_input) and key in (Qt.Key_Down, Qt.Key_Up) and modifiers == Qt.NoModifier:
			self.view.setFocus()
		elif watched is not self.view:
			return False
		elif key in (Qt.Key_Shift, Qt.Key_Control, Qt.Key_Alt, Qt.Key_Meta, Qt.Key_AltGr):
			return False
		else:
			self.source.setFocus()
			if self.source.hasFocus():
				self.source._controller.handle_shortcut(self.source, event)
		event.accept()
		return True
