from dataclasses import replace
from heapq import nlargest
from fman.impl.ui import match_positions, utf16_span
from PyQt5.QtCore import QAbstractListModel, QEvent, QModelIndex, QSize, Qt, \
	QItemSelectionModel, pyqtSignal
from PyQt5.QtGui import QColor, QFont, QFontMetrics, QPainter, QTextLayout, QTextCharFormat, QPalette, QKeySequence
from PyQt5.QtWidgets import QApplication, QAbstractItemView, QHBoxLayout, QLabel, \
	QLineEdit, QListView, QShortcut, QSizePolicy, QStyle, QStyledItemDelegate, \
	QVBoxLayout, QWidget


ARROWS = {True: '\u25b2', False: '\u25bc'}
MAX_SORT_KEYS = 10
# Values longer than this many average characters elide inside their cell.
MAX_CELL_CHARACTERS = 24
CELL_GAP = 16


def label_slot(metrics, label):
	"""Width of a label plus its sort-arrow slot and gap, whether or not it is sorted."""
	return metrics.horizontalAdvance(label + ' ') + max(map(metrics.horizontalAdvance, ARROWS.values())) + 8


class SortKeys(QLabel):
	"""'Sort (Ctrl+F1…F5): Name ▲ | Path | …', painted with a fixed arrow slot per field."""

	def __init__(self, owner):
		super().__init__(owner)
		self.owner = owner
		self.setTextFormat(Qt.PlainText)
		self.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)

	def labels(self):
		return self.owner.sort_labels[:MAX_SORT_KEYS]

	def update_text(self):
		labels, sort = self.labels(), self.owner.effective_sort
		fields = ' | '.join(label + (' ' + ARROWS[sort[1]] if sort and sort[0] == label else '') for label in labels)
		self.setText('%s%s' % (self.prefix(len(labels)), fields) if labels else '')
		self.setToolTip(self.text())
		self.setVisible(bool(labels))
		self.update()

	@staticmethod
	def prefix(count):
		return 'Sort (Ctrl+F1): ' if count == 1 else 'Sort (Ctrl+F1\u2026F%d): ' % count

	def paintEvent(self, event):
		labels, sort = self.labels(), self.owner.effective_sort
		painter = QPainter(self)
		color = self.palette().color(self.foregroundRole())
		muted = QColor(color)
		muted.setAlphaF(0.5)
		metrics = self.fontMetrics()
		arrow = max(map(metrics.horizontalAdvance, ARROWS.values()))
		gap = metrics.horizontalAdvance('  ')
		y = (self.height() - metrics.height()) // 2 + metrics.ascent()
		x = 0
		for index, label in enumerate(labels):
			if index:
				# A drawn line: a thin glyph gets colored subpixel fringes.
				painter.setPen(muted)
				painter.drawLine(x, y - metrics.ascent() + 1, x, y + metrics.descent())
				x += gap
			part = (self.prefix(len(labels)) if index == 0 else '') + label + ' '
			painter.setPen(color)
			painter.drawText(x, y, part)
			x += metrics.horizontalAdvance(part)
			if sort and sort[0] == label:
				painter.drawText(x, y, ARROWS[sort[1]])
			x += arrow + gap
		painter.end()


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
			lines = [item.title, item.hint]
			if item.metadata:
				lines.append('  '.join('%s %s' % (label, text) for label, key, text in item.metadata))
			return '\n'.join(lines)
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
		self.owner = None

	def font(self, option, role):
		font = QFont(option.font)
		settings = self.css.get(role, {})
		if 'font-size_pts' in settings:
			font.setPointSizeF(settings['font-size_pts'])
		return font

	def sizeHint(self, option, index):
		height = 12
		for role in ('title', 'hint'):
			height += QFontMetrics(self.font(option, role)).height()
		item = index.data(Qt.UserRole)
		minimum = 48
		if item is not None and item.metadata:
			extra = QFontMetrics(self.font(option, 'hint')).height()
			height += extra
			minimum += extra
		width = option.widget.viewport().width() if isinstance(option.widget, QAbstractItemView) else option.rect.width()
		return QSize(max(1, width), max(minimum, height))

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
			if item.metadata:
				offset = QFontMetrics(self.font(option, 'title')).height() if line_number else 0
				position.setY(position.y() + 6 + offset)
			else:
				position.setY(position.y() + 6 + line_number * (option.rect.height() - 12) // 2)
			layout.draw(painter, position)
		if item.metadata:
			self.paint_metadata(painter, option, item, selected)
		if isinstance(option.widget, QAbstractItemView) and index == option.widget.currentIndex():
			painter.setPen(option.palette.color(QPalette.HighlightedText if selected else QPalette.Highlight))
			painter.drawRect(option.rect.adjusted(1, 1, -2, -2))
		painter.restore()

	def paint_metadata(self, painter, option, item, selected):
		font = self.font(option, 'hint')
		metrics = QFontMetrics(font)
		columns = self.owner.metadata_columns(font) if self.owner is not None else None
		sort = self.owner.effective_sort if self.owner is not None else None
		settings = self.css.get('hint', {})
		color = option.palette.color(QPalette.HighlightedText if selected else QPalette.Text)
		if not selected and 'color' in settings:
			color = settings['color']
		painter.setPen(color)
		painter.setFont(font)
		y = option.rect.y() + 6 + QFontMetrics(self.font(option, 'title')).height() + metrics.height() + metrics.ascent()
		x = option.rect.x() + 10
		right = option.rect.right() - 10
		for index, (label, key, text) in enumerate(item.metadata):
			if x >= right:
				break
			painter.drawText(x, y, label)
			# The arrow has a reserved slot, so sorting never moves any text.
			if sort is not None and sort[0] == label:
				painter.drawText(x + metrics.horizontalAdvance(label + ' '), y, ARROWS[sort[1]])
			label_width = label_slot(metrics, label)
			width = columns[index] if columns is not None else label_width + metrics.horizontalAdvance(text)
			value_width = max(0, min(width, right - x) - label_width)
			painter.drawText(x + label_width, y, metrics.elidedText(text, Qt.ElideRight, value_width))
			x += width + CELL_GAP
			if index + 1 < len(item.metadata) and x < right:
				# A drawn line: a thin glyph gets colored subpixel fringes.
				line = x - CELL_GAP // 2
				painter.save()
				muted = QColor(color)
				muted.setAlphaF(0.4)
				painter.setPen(muted)
				painter.drawLine(line, y - metrics.ascent() + 2, line, y + metrics.descent() - 1)
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
	sort_changed = pyqtSignal()

	def __init__(self, parent=None, matcher=None, css=None, preserve_sort=False, fuzzy=False):
		from fman.impl.ui import require_ui_thread
		require_ui_thread()
		super().__init__(parent)
		self.setAttribute(Qt.WA_StyledBackground)
		if fuzzy and matcher is None:
			matcher = _subsequence_match
		self.matcher = matcher
		self.preserve_sort = preserve_sort
		self.sort_labels = ()
		self.sort_keys = {}
		self.requested_sort = None
		self._ordered = None
		self._columns = None
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
		self.view.itemDelegate().owner = self
		self.model = ItemModel(self)
		self.view.setModel(self.model)
		self.counts = QLabel(self)
		self.counts.setTextFormat(Qt.PlainText)
		self.counts.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
		self.sort_keys_label = SortKeys(self)
		self.sort_keys_label.setVisible(False)
		self.empty = QLabel('No items', self)
		layout = QVBoxLayout(self)
		layout.setContentsMargins(10, 10, 10, 6)
		layout.addWidget(self.query)
		layout.addWidget(self.empty)
		layout.addWidget(self.view, 1)
		# Keys on the left and counts on the right keep both in place as numbers change.
		footer = QHBoxLayout()
		footer.setContentsMargins(0, 0, 0, 0)
		footer.addWidget(self.sort_keys_label, 1)
		footer.addWidget(self.counts)
		layout.addLayout(footer)
		shortcuts = [('Ctrl+I', self.invert_selection), ('Ctrl+Shift+A', self.clear_selection)]
		shortcuts += [('Ctrl+F%d' % (index + 1), lambda position=index: self.sort_by(position))
			for index in range(MAX_SORT_KEYS)]
		for sequence, slot in shortcuts:
			shortcut = QShortcut(QKeySequence(sequence), self)
			shortcut.setContext(Qt.WidgetWithChildrenShortcut)
			shortcut.activated.connect(slot)
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
		self.set_sortable_items(items, (), {})

	def set_sortable_items(self, items, labels, keys):
		"""keys: label -> sort keys aligned with items, None for an empty value."""
		self.items = tuple(items)
		self.sort_labels = tuple(labels)
		self.sort_keys = keys
		self._ordered = None
		self._columns = None
		self.selected_ids.intersection_update(item.id for item in self.items)
		self.refresh()

	@property
	def effective_sort(self):
		sort = self.requested_sort
		return sort if sort is not None and sort[0] in self.sort_labels else None

	def sort_by(self, position):
		"""Ascending, then descending, then the original item order."""
		if position >= len(self.sort_labels):
			return
		label = self.sort_labels[position]
		current = self.effective_sort
		if current is None or current[0] != label:
			self.requested_sort = (label, True)
		elif current[1]:
			self.requested_sort = (label, False)
		else:
			self.requested_sort = None
		self._ordered = None
		self.refresh()
		self.view.scrollTo(self.view.currentIndex())
		self.view.viewport().update()
		self.sort_changed.emit()

	def ordered_items(self):
		if self._ordered is None:
			sort = self.effective_sort
			if sort is None:
				self._ordered = self.items
			else:
				keys = self.sort_keys[sort[0]]
				# Stable in both directions; empty values stay last.
				present = sorted((row for row, key in enumerate(keys) if key is not None),
					key=keys.__getitem__, reverse=not sort[1])
				empty = [row for row, key in enumerate(keys) if key is None]
				self._ordered = tuple(self.items[row] for row in present + empty)
		return self._ordered

	def metadata_columns(self, font):
		if self._columns is None or self._columns[0] != font.key():
			metrics = QFontMetrics(font)
			cap = metrics.horizontalAdvance('0') * MAX_CELL_CHARACTERS
			labels = self.items[0].metadata if self.items else ()
			widths = []
			for index, (label, key, text) in enumerate(labels):
				# Width tracks length closely enough; measuring every text costs seconds at 10,000 items.
				longest = nlargest(16, {item.metadata[index][2] for item in self.items}, key=len)
				value = max((metrics.horizontalAdvance(text) for text in longest), default=0)
				# +4: integer advances can round below the real text width and elide it.
				widths.append(label_slot(metrics, label) + min(cap, value) + 4)
			self._columns = (font.key(), tuple(widths))
		return self._columns[1]

	def invert_selection(self):
		self.selected_ids = {item.id for item in self.items} - self.selected_ids
		self.refresh()

	def clear_selection(self):
		self.selected_ids = set()
		self.refresh()

	def refresh(self, *_):
		current = self.current_id
		visible = []
		query = self.query.text()
		for item in self.ordered_items():
			if not query or self.matcher is None:
				visible.append(item)
				continue
			title = match_positions(self.matcher, item.title, query)
			hint = match_positions(self.matcher, item.hint, query)
			if title is not None or hint is not None:
				visible.append(replace(
					item, title_matches=title or (), hint_matches=hint or ()
				))
		if query and self.matcher is not None and not self.preserve_sort and not self.sort_labels:
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
			self.counts.setText('%d selected (%d hidden)' % (len(self.selected_ids), self.hidden_selected_count))
			self.sort_keys_label.update_text()
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