from time import perf_counter

from fman.impl.ui import match_positions, matchers, require_ui_thread, utf16_span
from PyQt5.QtCore import QAbstractTableModel, QEvent, QModelIndex, QPointF, QSize, Qt, QTimer, pyqtSignal
from PyQt5.QtGui import QFont, QKeySequence, QPalette, QTextCharFormat, QTextLayout
from PyQt5.QtWidgets import QAbstractItemView, QApplication, QHeaderView, QLabel, QLineEdit, QShortcut, QStyle, QStyledItemDelegate, QTableView, QVBoxLayout, QWidget


class TableModel(QAbstractTableModel):
	def __init__(self, headers, parent):
		super().__init__(parent)
		self.headers = headers
		self.rows = ()
		self.matches = {}

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
			return self.matches.get((row.id, index.column()), ())

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
		value = row.cells[index.column()]
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
		layout.draw(painter, QPointF(option.rect.x() + 8,
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
		event.accept()

	def keyPressEvent(self, event):
		if event.key() in (Qt.Key_Return, Qt.Key_Enter):
			if not event.modifiers() & (Qt.ControlModifier | Qt.AltModifier | Qt.ShiftModifier):
				self.activate_current()
			event.accept()
			return
		super().keyPressEvent(event)


class Table(QWidget):
	state_changed = pyqtSignal()

	def __init__(self, schema, rows, parent=None, fuzzy=True, get_count_text=None):
		require_ui_thread()
		super().__init__(parent)
		self.setObjectName('results-table')
		self.schema = schema
		self.rows = rows
		self.get_count_text = get_count_text
		self.generation = 0
		self.closed = False
		self.sort_column = None
		self.sort_descending = False
		self.query = QLineEdit(self)
		self.query.setPlaceholderText('Filter')
		self.query.setAccessibleName('Filter table')
		self.query.setClearButtonEnabled(False)
		self.query.setVisible(fuzzy)
		self.query.installEventFilter(self)
		self.view = TableView(self)
		self.view.setObjectName('results-table-view')
		self.model = TableModel(schema.headers, self)
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
		self.counts = QLabel(self)
		self.counts.setTextFormat(Qt.PlainText)
		layout = QVBoxLayout(self)
		layout.setContentsMargins(0, 0, 0, 0)
		layout.setSpacing(6)
		layout.addWidget(self.query)
		layout.addWidget(self.view, 1)
		layout.addWidget(self.counts)
		self.query.textChanged.connect(self.project)
		self.view.selectionModel().currentChanged.connect(lambda *args: self.state_changed.emit())
		self.setFocusProxy(self.query if fuzzy else self.view)
		shortcut = QShortcut(QKeySequence('Ctrl+F'), self)
		shortcut.setContext(Qt.WidgetWithChildrenShortcut)
		shortcut.activated.connect(self.focus_filter)
		self.project()

	@property
	def current_cell(self):
		index = self.view.currentIndex()
		return (index.data(Qt.UserRole), index.column()) if index.isValid() else None

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

	def replace(self, rows):
		self.rows = rows
		self.project()

	def sort_by(self, column):
		if self.sort_column != column:
			self.sort_column, self.sort_descending = column, False
		elif not self.sort_descending:
			self.sort_descending = True
		else:
			self.sort_column = None
		header = self.view.horizontalHeader()
		header.setSortIndicatorShown(self.sort_column is not None)
		header.setSortIndicator(column, Qt.DescendingOrder if self.sort_descending else Qt.AscendingOrder)
		self.project()

	def project(self):
		self.generation += 1
		generation = self.generation
		self.state_changed.emit()
		current = self.current_cell
		anchor = self.view.verticalScrollBar().value()
		query = self.query.text()
		folded_query = query.casefold()
		rows = self.rows
		matches, ranked = {}, []
		position = 0
		def finish():
			if self.closed or generation != self.generation:
				return
			ordered = sorted(ranked, key=lambda item: item[0])
			visible = [item[1] for item in ordered]
			if self.sort_column is not None:
				visible.sort(key=lambda row: row.cells[self.sort_column].casefold(), reverse=self.sort_descending)
			self.model.replace(visible, matches)
			if visible:
				index = next((index for index, row in enumerate(visible) if current and row.id == current[0].id), 0)
				self.view.setCurrentIndex(self.model.index(index, current[1] if current else 0))
				self.view.verticalScrollBar().setValue(anchor)
			if self.get_count_text is None:
				self.counts.setText('%d / %d rows' % (len(visible), len(rows)))
			else:
				try:
					self.counts.setText(str(self.get_count_text(len(visible), len(rows))))
				except Exception as error:
					self.counts.setText(str(error))
			self.state_changed.emit()
		def step():
			nonlocal position
			if self.closed or generation != self.generation:
				return
			deadline = perf_counter() + .006
			while position < len(rows):
				row = rows[position]
				position += 1
				best = None
				for column, value in enumerate(row.cells):
					if value.isascii():
						locations = matchers.contains_chars(value.lower(), folded_query)
					else:
						locations = match_positions(matchers.contains_chars, value, query)
					if locations is not None:
						matches[row.id, column] = locations
						score = (locations[-1] - locations[0] + 1 - len(locations), locations[0]) if locations else (0, 0)
						best = score if best is None else min(best, score)
				if best is not None:
					ranked.append((best, row))
				if perf_counter() >= deadline:
					QTimer.singleShot(0, step)
					return
			finish()
		if not query:
			ranked = [((0, 0), row) for row in rows]
			finish()
		else:
			step()

	def dispose(self):
		self.closed = True
		self.get_count_text = None
		self.generation += 1
		self.rows = ()
		self.model.replace((), {})