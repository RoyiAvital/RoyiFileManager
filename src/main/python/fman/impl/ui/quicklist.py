from dataclasses import replace
from fman.impl.ui import match_positions, utf16_span
from PyQt5.QtCore import QAbstractListModel, QEvent, QModelIndex, QSize, Qt, \
	QItemSelectionModel, pyqtSignal
from PyQt5.QtGui import QFont, QFontMetrics, QTextLayout, QTextCharFormat, QPalette, QKeySequence
from PyQt5.QtWidgets import QApplication, QAbstractItemView, QLabel, \
	QLineEdit, QListView, QStyle, QStyledItemDelegate, \
	QVBoxLayout, QWidget


class ItemModel(QAbstractListModel):
	def __init__(self, parent):
		super().__init__(parent)
		self.items = ()

	def rowCount(self, parent=QModelIndex()):
		return 0 if parent.isValid() else len(self.items)

	def data(self, index, role=Qt.DisplayRole):
		if not index.isValid() or not 0 <= index.row() < len(self.items):
			return None
		item = self.items[index.row()]
		if role == Qt.UserRole:
			return item
		if role in (Qt.DisplayRole, Qt.AccessibleTextRole):
			return item.title + '\n' + item.hint
		if role == Qt.ToolTipRole:
			return item.hint or item.title

	def replace(self, items):
		self.beginResetModel()
		self.items = tuple(items)
		self.endResetModel()


class ItemDelegate(QStyledItemDelegate):
	def __init__(self, parent, css=None):
		super().__init__(parent)
		self.css = css or {}

	def sizeHint(self, option, index):
		height = 12
		for role in ('title', 'hint'):
			font = QFont(option.font)
			font.setPointSizeF(self.css.get(role, {}).get('font-size_pts', font.pointSizeF()))
			height += QFontMetrics(font).height()
		width = option.widget.viewport().width() if isinstance(option.widget, QAbstractItemView) else option.rect.width()
		return QSize(max(1, width), max(48, height))

	def paint(self, painter, option, index):
		self.initStyleOption(option, index)
		item = index.data(Qt.UserRole)
		painter.save()
		painter.setClipRect(option.rect)
		style = option.widget.style() if option.widget else QApplication.style()
		style.drawPrimitive(
			QStyle.PE_PanelItemViewItem, option, painter, option.widget
		)
		selected = bool(option.state & QStyle.State_Selected)
		if selected:
			painter.fillRect(option.rect, option.palette.brush(QPalette.Highlight))
		for line_number, (text, matches, role) in enumerate((
			(item.title, item.title_matches, 'title'),
			(item.hint, item.hint_matches, 'hint')
		)):
			font = QFont(option.font)
			settings = self.css.get(role, {})
			if 'font-size_pts' in settings:
				font.setPointSizeF(settings['font-size_pts'])
			font.setBold(line_number == 0)
			metrics = QFontMetrics(font)
			visible = metrics.elidedText(text, Qt.ElideRight, option.rect.width() - 20)
			layout = QTextLayout(visible, font)
			formats = []
			for position in matches:
				if position >= len(visible) or visible[position] != text[position]:
					continue
				span = QTextLayout.FormatRange()
				span.start, span.length = utf16_span(visible, position)
				span.format = QTextCharFormat()
				span.format.setFontUnderline(True)
				span.format.setFontWeight(QFont.Bold)
				if not selected:
					highlight = self.css.get('title', {}).get('highlight', {})
					if 'color' in highlight:
						span.format.setForeground(highlight['color'])
				formats.append(span)
			layout.setFormats(formats)
			layout.beginLayout()
			line = layout.createLine()
			line.setLineWidth(max(1, option.rect.width() - 20))
			layout.endLayout()
			color = option.palette.color(
				QPalette.HighlightedText if selected else QPalette.Text
			)
			if not selected and 'color' in settings:
				color = settings['color']
			painter.setPen(color)
			position = option.rect.topLeft()
			position.setX(position.x() + 10)
			position.setY(position.y() + 6 + line_number * (option.rect.height() - 12) // 2)
			layout.draw(painter, position)
		if isinstance(option.widget, QAbstractItemView) and index == option.widget.currentIndex():
			painter.setPen(option.palette.color(QPalette.HighlightedText if selected else QPalette.Highlight))
			painter.drawRect(option.rect.adjusted(1, 1, -2, -2))
		painter.restore()


class ItemView(QListView):
	activate_current = pyqtSignal()
	delete_requested = pyqtSignal()

	def keyPressEvent(self, event):
		key = event.key()
		selection = self.selectionModel()
		current = self.currentIndex()
		moves = {
			Qt.Key_Up: self.MoveUp, Qt.Key_Down: self.MoveDown,
			Qt.Key_Home: self.MoveHome, Qt.Key_End: self.MoveEnd,
			Qt.Key_PageUp: self.MovePageUp, Qt.Key_PageDown: self.MovePageDown
		}
		if key in (Qt.Key_Space, Qt.Key_Insert):
			if current.isValid():
				selection.select(current, QItemSelectionModel.Toggle)
				if key == Qt.Key_Insert:
					self._move_current(self.moveCursor(self.MoveDown, Qt.NoModifier))
		elif key in moves:
			if event.modifiers() & Qt.ShiftModifier and current.isValid():
				if key in (Qt.Key_Up, Qt.Key_Down):
					selection.select(current, QItemSelectionModel.Toggle)
				else:
					destination = self.moveCursor(moves[key], Qt.NoModifier)
					for row in range(min(current.row(), destination.row()), max(current.row(), destination.row()) + 1):
						selection.select(self.model().index(row, 0), QItemSelectionModel.Toggle)
			self._move_current(self.moveCursor(moves[key], Qt.NoModifier))
			if key in (Qt.Key_PageUp, Qt.Key_PageDown):
				self._move_current(self.moveCursor(self.MoveUp if key == Qt.Key_PageUp else self.MoveDown, Qt.NoModifier))
		elif event.matches(QKeySequence.SelectAll):
			self.selectAll()
		elif key in (Qt.Key_Return, Qt.Key_Enter):
			self.activate_current.emit()
		elif key == Qt.Key_Delete:
			self.delete_requested.emit()
		else:
			super().keyPressEvent(event)

	def _move_current(self, index):
		if index.isValid():
			self.selectionModel().setCurrentIndex(index, QItemSelectionModel.NoUpdate)
			self.scrollTo(index)

	def selectionCommand(self, index, event=None):
		if event and event.type() == QEvent.MouseButtonPress and event.button() == Qt.RightButton:
			return QItemSelectionModel.Toggle if index.isValid() else QItemSelectionModel.NoUpdate
		if event and event.type() == QEvent.MouseButtonPress and \
				event.modifiers() & (Qt.ControlModifier | Qt.ShiftModifier):
			command = super().selectionCommand(index, event)
			return command & ~QItemSelectionModel.Select | QItemSelectionModel.Toggle
		return QItemSelectionModel.NoUpdate


class QuickList(QWidget):
	activated = pyqtSignal()
	delete_requested = pyqtSignal()
	state_changed = pyqtSignal()

	def __init__(self, parent=None, matcher=None, css=None, preserve_sort=False, fuzzy=False):
		from fman.impl.ui import require_ui_thread
		require_ui_thread()
		super().__init__(parent)
		self.setAttribute(Qt.WA_StyledBackground)
		if fuzzy and matcher is None:
			matcher = _subsequence_match
		self.matcher = matcher
		self.preserve_sort = preserve_sort
		self.items = ()
		self.selected_ids = set()
		self._updating = False
		self.query = QLineEdit(self)
		self.query.setAccessibleName('Filter')
		self.query.setVisible(matcher is not None)
		self.view = ItemView(self)
		self.view.setAccessibleName('Items')
		self.setFocusProxy(self.query if matcher is not None else self.view)
		self.view.setSelectionMode(QAbstractItemView.ExtendedSelection)
		self.view.setTabKeyNavigation(False)
		self.view.setUniformItemSizes(True)
		self.view.setResizeMode(QListView.Adjust)
		self.view.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
		self.view.setItemDelegate(ItemDelegate(self.view, css))
		self.model = ItemModel(self)
		self.view.setModel(self.model)
		self.counts = QLabel(self)
		self.empty = QLabel('No items', self)
		layout = QVBoxLayout(self)
		layout.setContentsMargins(10, 10, 10, 6)
		layout.addWidget(self.query)
		layout.addWidget(self.empty)
		layout.addWidget(self.view, 1)
		layout.addWidget(self.counts)
		self.query.textChanged.connect(self.refresh)
		self.query.returnPressed.connect(self.activated)
		self.query.installEventFilter(self)
		self.view.activate_current.connect(self.activated)
		self.view.doubleClicked.connect(self.activated)
		self.view.delete_requested.connect(self.delete_requested)
		self.view.selectionModel().selectionChanged.connect(self._selection_changed)
		self.view.selectionModel().currentChanged.connect(self._state_changed)

	@property
	def current_id(self):
		index = self.view.currentIndex()
		return self.model.items[index.row()].id if index.isValid() else None

	@property
	def hidden_selected_count(self):
		return len(self.selected_ids - {item.id for item in self.model.items})

	@property
	def selected_items(self):
		return tuple(item for item in self.items if item.id in self.selected_ids)

	@property
	def current_item(self):
		index = self.view.currentIndex()
		return self.model.items[index.row()] if index.isValid() else None

	def set_items(self, items):
		self.items = tuple(items)
		self.selected_ids.intersection_update(item.id for item in self.items)
		self.refresh()

	def refresh(self, *_):
		current = self.current_id
		visible = []
		query = self.query.text()
		for item in self.items:
			if not query or self.matcher is None:
				visible.append(item)
				continue
			title = match_positions(self.matcher, item.title, query)
			hint = match_positions(self.matcher, item.hint, query)
			if title is not None or hint is not None:
				visible.append(replace(
					item, title_matches=title or (), hint_matches=hint or ()
				))
		if query and self.matcher is not None and not self.preserve_sort:
			def match_order(item):
				positions = item.title_matches or item.hint_matches
				return (not bool(item.title_matches), positions[-1] - positions[0], positions[0])
			visible.sort(key=match_order)
		self._updating = True
		try:
			self.model.replace(visible)
			selection = self.view.selectionModel()
			current_index = self.model.index(0, 0)
			for row, item in enumerate(visible):
				index = self.model.index(row, 0)
				if item.id in self.selected_ids:
					selection.select(index, QItemSelectionModel.Select)
				if item.id == current:
					current_index = index
			selection.setCurrentIndex(current_index, QItemSelectionModel.NoUpdate)
		finally:
			self._updating = False
		self.empty.setText('No matches' if self.items else 'No items')
		self.empty.setVisible(not visible)
		self._state_changed()

	def _selection_changed(self, *_):
		if not self._updating:
			self.selected_ids.difference_update(item.id for item in self.model.items)
			self.selected_ids.update(
				self.model.items[index.row()].id
				for index in self.view.selectionModel().selectedIndexes()
			)
			self._state_changed()

	def _state_changed(self, *_):
		if not self._updating:
			self.counts.setText('%d selected (%d hidden)' % (
				len(self.selected_ids), self.hidden_selected_count
			))
			self.state_changed.emit()

	def eventFilter(self, watched, event):
		if watched is self.query and event.type() == QEvent.KeyPress and \
				event.key() in (Qt.Key_Up, Qt.Key_Down, Qt.Key_PageUp, Qt.Key_PageDown):
			self.view.setFocus(Qt.OtherFocusReason)
			self.view.keyPressEvent(event)
			return True
		return super().eventFilter(watched, event)


def _subsequence_match(text, query):
	positions = []
	start = 0
	for char in query:
		position = text.find(char, start)
		if position < 0:
			return None
		positions.append(position)
		start = position + 1
	return positions