from time import perf_counter

from fman.impl.ui import match_positions, matchers, require_ui_thread, utf16_span
from fman.impl.ui.table_filters import BYTE_UNITS, compile_filter, operators
from fman.impl.util.natural import natural_key
from PyQt5.QtCore import QAbstractTableModel, QEvent, QModelIndex, QPoint, QPointF, QRect, QSize, Qt, QTimer, pyqtSignal
from PyQt5.QtGui import QColor, QFont, QIcon, QKeySequence, QPainter, QPalette, QPixmap, QTextCharFormat, QTextLayout
from PyQt5.QtSvg import QSvgRenderer
from PyQt5.QtWidgets import QAbstractItemView, QApplication, QComboBox, QGridLayout, QHeaderView, QLabel, QLineEdit, \
	QMenu, QShortcut, QStyle, QStyleOptionHeader, QStyledItemDelegate, QTableView, QToolTip, QVBoxLayout, QWidget, QWidgetAction

ICON_SIZE = 14
_renderers = {}
_pixmaps = {}


def table_icon(name, color, ratio=1.0, size=ICON_SIZE):
	key = (name, color.rgba(), size, ratio)
	if key not in _pixmaps:
		if name not in _renderers:
			from fman.impl.application_context import get_application_context
			renderer = QSvgRenderer(get_application_context().get_resource('icons/%s.svg' % name))
			if not renderer.isValid():
				raise RuntimeError('Could not load the %s icon.' % name)
			_renderers[name] = renderer
		pixmap = QPixmap(round(size * ratio), round(size * ratio))
		pixmap.fill(Qt.transparent)
		painter = QPainter(pixmap)
		_renderers[name].render(painter)
		painter.setCompositionMode(QPainter.CompositionMode_SourceIn)
		painter.fillRect(pixmap.rect(), color)
		painter.end()
		pixmap.setDevicePixelRatio(ratio)
		if len(_pixmaps) > 64:
			_pixmaps.clear()
		_pixmaps[key] = pixmap
	return _pixmaps[key]


def defer(owner, callback):
	# The timer is owner's child, so the callback never runs after owner is deleted.
	timer = QTimer(owner)
	timer.setSingleShot(True)
	timer.timeout.connect(callback)
	timer.timeout.connect(timer.deleteLater)
	timer.start(0)


class TableModel(QAbstractTableModel):
	def __init__(self, headers, parent):
		super().__init__(parent)
		self.headers = headers
		self.rows = ()
		self.matches = {}
		self.right_aligned = frozenset()

	def rowCount(self, parent=QModelIndex()):
		return 0 if parent.isValid() else len(self.rows)

	def columnCount(self, parent=QModelIndex()):
		return 0 if parent.isValid() else len(self.headers)

	def headerData(self, section, orientation, role=Qt.DisplayRole):
		if orientation == Qt.Horizontal and role == Qt.DisplayRole and 0 <= section < len(self.headers):
			return self.headers[section]

	def data(self, index, role=Qt.DisplayRole):
		if not index.isValid() or not 0 <= index.row() < len(self.rows):
			return None
		row = self.rows[index.row()]
		if role in (Qt.DisplayRole, Qt.ToolTipRole, Qt.AccessibleTextRole):
			return row.cells[index.column()]
		if role == Qt.UserRole:
			return row
		if role == Qt.UserRole + 1:
			return self.matches.get((id(row), index.column()), ())

	def replace(self, rows, matches):
		self.beginResetModel()
		self.rows, self.matches = tuple(rows), matches
		self.endResetModel()


class TableDelegate(QStyledItemDelegate):
	def sizeHint(self, option, index):
		return QSize(80, max(26, option.fontMetrics.height() + 10))

	def paint(self, painter, option, index):
		self.initStyleOption(option, index)
		row = index.data(Qt.UserRole)
		if row is None:
			return
		# One space per tab keeps highlight offsets; Qt tab stops would push text out of the cell.
		value = row.cells[index.column()].replace('\t', ' ')
		visible = option.fontMetrics.elidedText(value, Qt.ElideRight, max(1, option.rect.width() - 16))
		option.text = ''
		option.state &= ~(QStyle.State_Children | QStyle.State_Open)
		style = option.widget.style() if option.widget else QApplication.style()
		painter.save()
		painter.setClipRect(option.rect)
		style.drawControl(QStyle.CE_ItemViewItem, option, painter, option.widget)
		layout = QTextLayout(visible, option.font)
		formats = []
		for start, end in row.highlights[index.column()] if row.highlights else ():
			end = min(end, len(visible))
			if start >= end or visible[start:end] != value[start:end]:
				continue
			span = QTextLayout.FormatRange()
			span.start = len(visible[:start].encode('utf-16-le')) // 2
			span.length = len(visible[start:end].encode('utf-16-le')) // 2
			span.format = QTextCharFormat()
			color = option.palette.color(QPalette.HighlightedText if option.state & QStyle.State_Selected else QPalette.Highlight)
			color.setAlpha(100)
			span.format.setBackground(color)
			formats.append(span)
		for position in index.data(Qt.UserRole + 1):
			if position >= len(visible) or visible[position] != value[position]:
				continue
			span = QTextLayout.FormatRange()
			span.start, span.length = utf16_span(visible, position)
			span.format = QTextCharFormat()
			span.format.setFontUnderline(True)
			span.format.setFontWeight(QFont.Bold)
			formats.append(span)
		layout.setFormats(formats)
		layout.beginLayout()
		line = layout.createLine()
		line.setLineWidth(max(1, option.rect.width() - 16))
		layout.endLayout()
		selected = option.state & QStyle.State_Selected
		painter.setPen(option.palette.color(QPalette.HighlightedText if selected else QPalette.Text))
		x = option.rect.x() + 8
		if index.column() in index.model().right_aligned:
			x = max(x, option.rect.right() - 8 - line.naturalTextWidth())
		layout.draw(painter, QPointF(x,
			option.rect.y() + (option.rect.height() - line.height()) / 2))
		if index == option.widget.currentIndex():
			painter.setPen(option.palette.color(QPalette.HighlightedText if selected else QPalette.Highlight))
			painter.drawRect(option.rect.adjusted(1, 1, -2, -2))
		painter.restore()


class TableView(QTableView):
	cell_activated = pyqtSignal(object, int)
	menu_requested = pyqtSignal(object, int, object)

	def activate_current(self):
		index = self.currentIndex()
		if index.isValid():
			self.cell_activated.emit(index.data(Qt.UserRole), index.column())

	def mousePressEvent(self, event):
		if not self.indexAt(event.pos()).isValid():
			self.setFocus()
			event.accept()
			return
		super().mousePressEvent(event)

	def mouseDoubleClickEvent(self, event):
		index = self.indexAt(event.pos())
		if event.button() == Qt.LeftButton and index.isValid():
			self.setCurrentIndex(index)
			self.activate_current()
			event.accept()
			return
		event.accept()

	def contextMenuEvent(self, event):
		index = self.currentIndex() if event.reason() == event.Keyboard else self.indexAt(event.pos())
		if index.isValid():
			self.setCurrentIndex(index)
			position = self.viewport().mapToGlobal(self.visualRect(index).center()) if event.reason() == event.Keyboard else event.globalPos()
			self.menu_requested.emit(index.data(Qt.UserRole), index.column(), position)
		else:
			position = self.viewport().mapToGlobal(self.viewport().rect().center()) if event.reason() == event.Keyboard else event.globalPos()
			self.menu_requested.emit(None, -1, position)
		event.accept()

	def keyPressEvent(self, event):
		if event.key() in (Qt.Key_Return, Qt.Key_Enter):
			if not event.modifiers() & (Qt.ControlModifier | Qt.AltModifier | Qt.ShiftModifier):
				self.activate_current()
			event.accept()
			return
		super().keyPressEvent(event)


class TableHeader(QHeaderView):
	filter_requested = pyqtSignal(int)

	def __init__(self, table):
		super().__init__(Qt.Horizontal, table)
		self.table = table
		self.hover = -1
		self.pressed_filter = -1
		self.setMouseTracking(True)
		self.setSectionsClickable(True)
		self.setHighlightSections(False)
		self.setSortIndicatorShown(False)
		self.setDefaultAlignment(Qt.AlignLeft | Qt.AlignVCenter)

	def sizeHint(self):
		hint = super().sizeHint()
		return QSize(hint.width(), max(hint.height(), self.fontMetrics().height() + 14))

	def icon_rects(self, logical, rect=None):
		if rect is None:
			rect = QRect(self.sectionViewportPosition(logical), 0, self.sectionSize(logical), self.height())
		top = rect.top() + (rect.height() - ICON_SIZE) // 2
		right = rect.right() - 6
		sort_rect = filter_rect = None
		if self.table.filterable(logical):
			filter_rect = QRect(right - ICON_SIZE + 1, top, ICON_SIZE, ICON_SIZE)
			right -= ICON_SIZE + 5
		if self.table.sort_column == logical:
			sort_rect = QRect(right - ICON_SIZE + 1, top, ICON_SIZE, ICON_SIZE)
		return sort_rect, filter_rect

	def filter_hit(self, position):
		logical = self.logicalIndexAt(position)
		if logical < 0:
			return -1
		filter_rect = self.icon_rects(logical)[1]
		return logical if filter_rect is not None and filter_rect.adjusted(-3, -4, 3, 4).contains(position) else -1

	def paintSection(self, painter, rect, logical):
		if not rect.isValid():
			return
		option = QStyleOptionHeader()
		self.initStyleOption(option)
		option.rect = rect
		option.section = logical
		option.text = ''
		option.sortIndicator = QStyleOptionHeader.None_
		option.textAlignment = Qt.AlignLeft | Qt.AlignVCenter
		if logical == self.hover:
			option.state |= QStyle.State_MouseOver
		visual, count = self.visualIndex(logical), self.count()
		option.position = QStyleOptionHeader.OnlyOneSection if count == 1 else \
			QStyleOptionHeader.Beginning if visual == 0 else \
			QStyleOptionHeader.End if visual == count - 1 else QStyleOptionHeader.Middle
		painter.save()
		style = self.style()
		style.drawControl(QStyle.CE_HeaderSection, option, painter, self)
		sort_rect, filter_rect = self.icon_rects(logical, rect)
		icons = [item for item in (sort_rect, filter_rect) if item is not None]
		right = min(item.left() for item in icons) - 4 if icons else rect.right() - 6
		label_rect = QRect(rect.left() + 8, rect.top(), max(0, right - rect.left() - 8), rect.height())
		label = self.model().headerData(logical, Qt.Horizontal, Qt.DisplayRole) if self.model() else ''
		option.rect = label_rect
		option.text = self.fontMetrics().elidedText(str(label or ''), Qt.ElideRight, label_rect.width())
		style.drawControl(QStyle.CE_HeaderLabel, option, painter, self)
		color = self.palette().color(QPalette.ButtonText)
		ratio = self.devicePixelRatioF()
		if sort_rect is not None:
			name = 'sort-descending' if self.table.sort_descending else 'sort-ascending'
			painter.drawPixmap(sort_rect.topLeft(), table_icon(name, color, ratio))
		if filter_rect is not None:
			active = logical in self.table.filters
			tint = QColor(self.palette().color(QPalette.Highlight) if active else color)
			if not active and logical != self.hover:
				tint.setAlphaF(0.45)
			painter.drawPixmap(filter_rect.topLeft(), table_icon('filter', tint, ratio))
		painter.restore()

	def mousePressEvent(self, event):
		self.pressed_filter = self.filter_hit(event.pos()) if event.button() == Qt.LeftButton else -1
		if self.pressed_filter >= 0:
			event.accept()
			return
		super().mousePressEvent(event)

	def mouseReleaseEvent(self, event):
		if self.pressed_filter >= 0:
			logical, self.pressed_filter = self.pressed_filter, -1
			if self.filter_hit(event.pos()) == logical:
				self.filter_requested.emit(logical)
			event.accept()
			return
		super().mouseReleaseEvent(event)

	def mouseMoveEvent(self, event):
		hover = self.logicalIndexAt(event.pos())
		if hover != self.hover:
			self.hover = hover
			self.viewport().update()
		super().mouseMoveEvent(event)

	def viewportEvent(self, event):
		if event.type() == QEvent.Leave and self.hover != -1:
			self.hover = -1
			self.viewport().update()
		elif event.type() == QEvent.ToolTip:
			logical = self.logicalIndexAt(event.pos())
			if logical < 0:
				QToolTip.hideText()
			else:
				QToolTip.showText(event.globalPos(), self.table.header_tooltip(logical, self.filter_hit(event.pos()) == logical), self)
			return True
		return super().viewportEvent(event)


class FilterEditor(QWidget):
	submitted = pyqtSignal()
	validity_changed = pyqtSignal(bool)

	def __init__(self, table, index, current, parent=None):
		super().__init__(parent)
		self.setObjectName('table-filter-editor')
		self.table, self.index = table, index
		self.column = table.schema.column(index)
		self.compiled = None
		layout = QGridLayout(self)
		layout.setContentsMargins(10, 8, 10, 6)
		layout.setHorizontalSpacing(6)
		layout.setVerticalSpacing(4)
		title = QLabel('Filter ' + self.column.label, self)
		title.setObjectName('table-filter-title')
		title.setTextFormat(Qt.PlainText)
		layout.addWidget(title, 0, 0, 1, 5)
		self.operator = QComboBox(self)
		self.operator.setAccessibleName(self.column.label + ' filter operator')
		for value, label in operators(self.column):
			self.operator.addItem(label, value)
		self.first = QLineEdit(self)
		self.second = QLineEdit(self)
		self.conjunction = QLabel('and', self)
		placeholder = {'date': 'YYYY-MM-DD', 'number': 'Value'}.get(self.column.policy, 'Text')
		for field, name in ((self.first, 'value'), (self.second, 'second value')):
			field.setPlaceholderText(placeholder)
			field.setAccessibleName('%s filter %s' % (self.column.label, name))
			field.setMinimumWidth(130 if self.column.policy == 'date' else 110)
			field.installEventFilter(self)
		self.unit = None
		layout.addWidget(self.operator, 1, 0)
		layout.addWidget(self.first, 1, 1)
		layout.addWidget(self.conjunction, 1, 2)
		layout.addWidget(self.second, 1, 3)
		if self.column.typed:
			# The menu is sized once at popup; reserve the Between layout so switching operators cannot squeeze it.
			for widget in (self.first, self.conjunction, self.second):
				policy = widget.sizePolicy()
				policy.setRetainSizeWhenHidden(True)
				widget.setSizePolicy(policy)
		if self.column.unit == 'bytes':
			self.unit = QComboBox(self)
			self.unit.setAccessibleName(self.column.label + ' filter unit')
			for name, factor in BYTE_UNITS:
				self.unit.addItem(name, name)
			layout.addWidget(self.unit, 1, 4)
		self.error = QLabel(self)
		self.error.setObjectName('table-filter-error')
		self.error.setTextFormat(Qt.PlainText)
		self.error.setWordWrap(True)
		layout.addWidget(self.error, 2, 0, 1, 5)
		if current is not None:
			self.operator.setCurrentIndex(max(0, self.operator.findData(current.operator)))
			self.first.setText(current.first)
			self.second.setText(current.second)
			if self.unit is not None:
				self.unit.setCurrentIndex(max(0, self.unit.findData(current.unit)))
		elif self.column.policy == 'text' or self.column.policy == 'natural':
			self.operator.setCurrentIndex(max(0, self.operator.findData(table.text_matching)))
		self.operator.currentIndexChanged.connect(self.validate)
		self.first.textChanged.connect(self.validate)
		self.second.textChanged.connect(self.validate)
		if self.unit is not None:
			self.unit.currentIndexChanged.connect(self.validate)
		self.validate()

	def validate(self, *args):
		operator = self.operator.currentData()
		self.first.setVisible(operator != 'missing')
		ranged = operator == 'between'
		self.conjunction.setVisible(ranged)
		self.second.setVisible(ranged)
		if self.unit is not None:
			self.unit.setVisible(operator != 'missing')
		try:
			self.compiled = compile_filter(self.column, self.index, operator, self.first.text(),
				self.second.text(), self.unit.currentData() if self.unit is not None else 'B', self.table.schema.dates)
		except ValueError as error:
			self.compiled = None
			blank = not self.first.text().strip() and not (ranged and self.second.text().strip())
			self.error.setText('' if blank else str(error))
		else:
			self.error.setText('')
		self.error.setVisible(bool(self.error.text()))
		self.validity_changed.emit(self.compiled is not None)

	def focus_first(self):
		(self.first if self.first.isVisible() else self.operator).setFocus(Qt.PopupFocusReason)
		if self.first.hasFocus():
			self.first.selectAll()

	def eventFilter(self, watched, event):
		if event.type() == QEvent.KeyPress and event.key() in (Qt.Key_Return, Qt.Key_Enter):
			self.submitted.emit()
			return True
		return super().eventFilter(watched, event)


class Table(QWidget):
	state_changed = pyqtSignal()

	def __init__(self, schema, rows, parent=None, text_filter='fuzzy', truncated=None):
		require_ui_thread()
		super().__init__(parent)
		self.setObjectName('results-table')
		self.schema = schema
		self.rows = rows
		self.compile_text_filter = text_filter if callable(text_filter) else None
		self.text_matching = 'substring' if text_filter == 'substring' else 'fuzzy'
		self.truncated = truncated
		self.compiled_query = None
		self.sort_keys = {}
		self.error = ''
		self.filters = {}
		self.filter_menu = None
		self.generation = 0
		self.pending = False
		self.closed = False
		self.sort_column = None
		self.sort_descending = False
		self.last_column = next((index for index in range(schema.num_columns) if self.filterable(index)), 0)
		self.query = QLineEdit(self)
		self.query.setPlaceholderText('Filter')
		self.query.setAccessibleName('Filter table')
		self.query.setClearButtonEnabled(False)
		self.query.setVisible(text_filter is not None)
		self.query.installEventFilter(self)
		self.view = TableView(self)
		self.view.setObjectName('results-table-view')
		self.model = TableModel(schema.headers, self)
		self.model.right_aligned = frozenset(index for index, column in enumerate(schema.columns) if column.policy == 'number')
		self.view.setHorizontalHeader(TableHeader(self))
		self.view.setModel(self.model)
		self.view.setItemDelegate(TableDelegate(self.view))
		self.view.setSelectionMode(QAbstractItemView.SingleSelection)
		self.view.setSelectionBehavior(QAbstractItemView.SelectRows)
		self.view.setCornerButtonEnabled(False)
		self.view.setEditTriggers(QAbstractItemView.NoEditTriggers)
		self.view.setTabKeyNavigation(False)
		self.view.setAlternatingRowColors(True)
		self.view.setWordWrap(False)
		self.view.setShowGrid(False)
		self.view.verticalHeader().hide()
		self.view.verticalHeader().setSectionResizeMode(QHeaderView.Fixed)
		self.view.verticalHeader().setDefaultSectionSize(max(26, self.fontMetrics().height() + 10))
		header = self.view.horizontalHeader()
		header.setSectionsMovable(False)
		header.setSectionResizeMode(QHeaderView.Interactive)
		header.setMinimumSectionSize(60)
		header.setStretchLastSection(True)
		header.sectionClicked.connect(self.sort_by)
		header.filter_requested.connect(lambda column: self.open_filter_menu(column))
		metrics = self.fontMetrics()
		for index, column in enumerate(schema.columns):
			if column.policy == 'date':
				sample = '0000-00-00' if column.date_display == 'date' else '0000-00-00T00:00:00+00:00'
				self.view.setColumnWidth(index, metrics.horizontalAdvance(sample) + 2 * ICON_SIZE + 36)
			elif column.policy == 'number':
				self.view.setColumnWidth(index, metrics.horizontalAdvance('000,000,000,000 B') + 2 * ICON_SIZE + 36)
		self.counts = QLabel(self)
		self.counts.setTextFormat(Qt.PlainText)
		layout = QVBoxLayout(self)
		layout.setContentsMargins(0, 0, 0, 0)
		layout.setSpacing(6)
		layout.addWidget(self.query)
		layout.addWidget(self.view, 1)
		layout.addWidget(self.counts)
		self.query.textChanged.connect(self.project)
		self.view.selectionModel().currentChanged.connect(self.current_changed)
		self.setFocusProxy(self.query if text_filter is not None else self.view)
		shortcut = QShortcut(QKeySequence('Ctrl+F'), self)
		shortcut.setContext(Qt.WidgetWithChildrenShortcut)
		shortcut.activated.connect(self.focus_filter)
		filter_shortcut = QShortcut(QKeySequence('Alt+Down'), self)
		filter_shortcut.setContext(Qt.WidgetWithChildrenShortcut)
		filter_shortcut.activated.connect(lambda: self.open_filter_menu())
		self.project()

	@property
	def current_cell(self):
		index = self.view.currentIndex()
		return (index.data(Qt.UserRole), index.column()) if index.isValid() else None

	@property
	def settled(self):
		return not self.closed and not self.pending and not self.error

	def visible_positions(self):
		# Positions in the caller's input order; identical row objects share visibility.
		visible = {id(row) for row in self.model.rows}
		return tuple(index for index, row in enumerate(self.rows) if id(row) in visible)

	def current_changed(self, current, previous):
		if current.isValid():
			self.last_column = current.column()
		self.state_changed.emit()

	def filterable(self, column):
		return self.schema.columns[column].filterable

	def sortable(self, column):
		return self.schema.columns[column].sortable

	def header_tooltip(self, column, on_filter):
		label = self.schema.headers[column]
		if on_filter:
			active = self.filters.get(column)
			return ('Filtered: ' + active.description) if active else 'Filter ' + label + ' (Alt+Down)'
		if not self.sortable(column):
			return label
		if self.sort_column == column:
			return '%s: sorted %s; click to %s' % (label, 'descending' if self.sort_descending else 'ascending',
				'restore the original order' if self.sort_descending else 'sort descending')
		return 'Sort by ' + label

	def focus_filter(self):
		if not self.query.isHidden():
			self.query.setFocus()
			self.query.selectAll()

	def eventFilter(self, watched, event):
		if watched is self.query and event.type() == QEvent.KeyPress:
			if event.key() in (Qt.Key_Return, Qt.Key_Enter):
				if not event.modifiers() & (Qt.ControlModifier | Qt.AltModifier | Qt.ShiftModifier):
					self.view.activate_current()
				return True
			if event.key() in (Qt.Key_Up, Qt.Key_Down):
				self.view.setFocus()
				return True
		return super().eventFilter(watched, event)

	def sort_by(self, column):
		if not self.sortable(column):
			return
		if self.sort_column != column:
			self.set_sort(column, False)
		elif not self.sort_descending:
			self.set_sort(column, True)
		else:
			self.set_sort(None)

	def set_sort(self, column, descending=False):
		self.sort_column, self.sort_descending = column, bool(descending) and column is not None
		self.view.horizontalHeader().viewport().update()
		self.project()

	def active_column(self):
		cell = self.current_cell
		column = cell[1] if cell is not None else self.last_column
		return column if self.filterable(column) else self.last_column

	def set_column_filter(self, column, column_filter):
		if column_filter is None:
			self.filters.pop(column, None)
		else:
			self.filters[column] = column_filter
		self.view.horizontalHeader().viewport().update()
		self.project()

	def clear_all_filters(self):
		self.filters.clear()
		self.view.horizontalHeader().viewport().update()
		if self.query.text():
			self.query.clear()
		else:
			self.project()

	def open_filter_menu(self, column=None, position=None):
		if self.closed:
			return None
		column = self.active_column() if column is None else column
		if not self.filterable(column):
			return None
		self.close_filter_menu()
		self.last_column = column
		# Only refocus known children; other widgets may be deleted before the deferred restore runs.
		restore_to = self.query if QApplication.focusWidget() is self.query else self.view
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
		if self.sortable(column):
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
			if not self.closed:
				defer(self, lambda: restore_to.setFocus(Qt.PopupFocusReason))
		menu.aboutToHide.connect(hidden)
		# A direct Python deleteLater() call detaches the wrapper from its parent; with the closure
		# cycles above, the garbage collector could then clear it while Qt still owns the menu.
		menu.aboutToHide.connect(menu.deleteLater)
		self.filter_menu = menu
		if position is None:
			header = self.view.horizontalHeader()
			x = header.sectionViewportPosition(column)
			position = header.viewport().mapToGlobal(QPoint(max(0, x), header.height()))
		menu.popup(position)
		defer(editor, editor.focus_first)
		return menu

	def close_filter_menu(self):
		menu, self.filter_menu = self.filter_menu, None
		if menu is not None:
			menu.close()

	def text_predicate(self, query):
		if self.compiled_query is None or self.compiled_query[0] != query:
			try:
				predicate = self.compile_text_filter(query)
				if not callable(predicate):
					raise TypeError('The text filter compiler must return a callable predicate.')
			except Exception as error:
				self.compiled_query = (query, None, str(error) or type(error).__name__)
			else:
				self.compiled_query = (query, predicate, '')
		if self.compiled_query[2]:
			raise ValueError(self.compiled_query[2])
		return self.compiled_query[1]

	def count_text(self, visible, total):
		if self.error:
			return self.error
		notes = ['%d / %d rows' % (visible, total)]
		if self.filters:
			notes.append('%d column filter%s' % (len(self.filters), '' if len(self.filters) == 1 else 's'))
		if self.truncated:
			notes.append('truncated')
		return ' \u00b7 '.join(notes)

	def sort_rows(self, visible):
		column = self.sort_column
		policy = self.schema.columns[column].policy
		if policy in ('date', 'number'):
			known = [row for row in visible if row.values[column] is not None]
			known.sort(key=lambda row: row.values[column], reverse=self.sort_descending)
			return known + [row for row in visible if row.values[column] is None]
		# Keys are computed once per snapshot and column; projections re-sort on every query edit.
		keys = self.sort_keys.get(column)
		if keys is None:
			key = natural_key if policy == 'natural' else str.casefold
			keys = self.sort_keys[column] = {id(row): key(row.cells[column]) for row in self.rows}
		return sorted(visible, key=lambda row: keys[id(row)], reverse=self.sort_descending)

	def project(self):
		self.generation += 1
		generation = self.generation
		self.pending = True
		self.state_changed.emit()
		current = self.current_cell
		anchor = self.view.verticalScrollBar().value()
		query = self.query.text()
		folded_query = query.casefold()
		rows = self.rows
		matches, ranked = {}, []
		filters = tuple(item.predicate for item in self.filters.values())
		searchable = self.schema.searchable
		substring = self.text_matching == 'substring'
		matcher = matchers.contains_substring if substring else matchers.contains_chars
		position = 0
		self.error = ''
		def fail(message):
			if self.closed or generation != self.generation:
				return
			self.error = 'Filter error: ' + message
			self.pending = False
			self.model.replace((), {})
			self.counts.setText(self.error)
			self.state_changed.emit()
		predicate = None
		if query and self.compile_text_filter is not None:
			try:
				predicate = self.text_predicate(query)
			except ValueError as error:
				fail(str(error))
				return
		def finish():
			if self.closed or generation != self.generation:
				return
			ordered = sorted(ranked, key=lambda item: item[0])
			visible = [item[1] for item in ordered]
			if self.sort_column is not None:
				visible = self.sort_rows(visible)
			self.model.replace(visible, matches)
			if visible:
				index = next((index for index, row in enumerate(visible) if current and row is current[0]), 0)
				self.view.setCurrentIndex(self.model.index(index, current[1] if current else 0))
				self.view.verticalScrollBar().setValue(anchor)
			self.counts.setText(self.count_text(len(visible), len(rows)))
			self.pending = False
			self.state_changed.emit()
		def step():
			nonlocal position
			if self.closed or generation != self.generation:
				return
			deadline = perf_counter() + .006
			while position < len(rows):
				row = rows[position]
				position += 1
				if filters and not all(test(row) for test in filters):
					pass
				elif not query:
					ranked.append(((0, 0), row))
				elif predicate is not None:
					try:
						accepted = predicate(tuple(row.cells[column] for column in searchable))
					except Exception as error:
						fail(str(error) or type(error).__name__)
						return
					if type(accepted) is not bool:
						fail('The text filter must return True or False.')
						return
					if accepted:
						ranked.append(((0, 0), row))
				else:
					best = None
					for column in searchable:
						value = row.cells[column]
						if value.isascii():
							locations = matcher(value.lower(), folded_query)
						else:
							locations = match_positions(matcher, value, query)
						if locations is not None:
							matches[id(row), column] = locations
							score = (locations[-1] - locations[0] + 1 - len(locations), locations[0]) if locations else (0, 0)
							best = score if best is None else min(best, score)
					if best is not None:
						ranked.append((best, row))
				if perf_counter() >= deadline:
					defer(self, step)
					return
			finish()
		if not query and not filters:
			ranked = [((0, 0), row) for row in rows]
			finish()
		else:
			step()

	def dispose(self):
		self.closed = True
		self.close_filter_menu()
		self.compile_text_filter = None
		self.compiled_query = None
		self.filters.clear()
		self.sort_keys.clear()
		self.generation += 1
		self.rows = ()
		self.model.replace((), {})