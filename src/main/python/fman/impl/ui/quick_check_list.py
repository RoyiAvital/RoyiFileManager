"""QuickCheckList: a modal, QuickSearch-styled list with a state indicator per item."""

from copy import deepcopy
from threading import Event
from typing import NamedTuple

from fman.impl.quicksearch import QuicksearchItemRenderer
from fman.impl.theme import CHECK_COLORS
from fman.impl.ui import UiOwner, match_positions, require_ui_thread
from fman.impl.ui.check_list_data import label, next_state, prepare, result
from fman.impl.ui.facade import ElidedLabel
from fman.impl.ui.quicklist import _subsequence_match
from fman.impl.ui.session import ToolWindow
from fman.impl.util.qt.thread import is_in_main_thread, run_in_main_thread
from PyQt5.QtCore import QAbstractListModel, QEvent, QEventLoop, QItemSelectionModel, \
	QModelIndex, QPointF, QRectF, Qt, pyqtSignal
from PyQt5.QtGui import QColor, QFont, QFontMetricsF, QPainter, QPainterPath, QPen, QPolygonF
from PyQt5.QtWidgets import QAbstractItemView, QApplication, QHBoxLayout, QLabel, QLineEdit, \
	QListView, QStyledItemDelegate, QVBoxLayout, QWidget

import math


# Width of the indicator column left of the title, in pixels.
INDICATOR = 22
MAX_VISIBLE_ROWS = 12
DEFAULT_CSS = {
	'padding-top_px': 1, 'padding-left_px': 4, 'padding-right_px': 4,
	'border-top-width_px': 1, 'border-bottom-width_px': 1,
	'title': {'font-size_pts': 10, 'color': QColor('#c8c8c8'), 'highlight': {'color': QColor('white')}},
	'hint': {'font-size_pts': 8, 'color': QColor('white')},
	'description': {'font-size_pts': 9, 'color': QColor('#8f908a')},
}
# Lists are owner-free plain data, like QuickList.
_owner = UiOwner()


def _main_window():
	from fman import _get_ui
	return _get_ui()


def _one_line(text):
	"""Header, summary and status are single elided lines; the tooltip keeps the text."""
	return ' '.join(text.splitlines())


class _Visible(NamedTuple):
	item: object
	matches: tuple


class _RendererItem(NamedTuple):
	title: str
	hint: str
	description: str
	highlight: list


def paint_indicator(painter, rect, state, colors):
	"""Paint a preset state centered in rect, scaled to its height."""
	size = rect.height() * 0.75
	scale = size / 13
	box = QRectF(rect.center().x() - size / 2, rect.center().y() - size / 2, size, size)
	outline, active, mark = colors['state'], colors['active'], colors['mark']
	if state in ('empty', 'filled'):
		points = []
		for corner in range(10):
			radius = size * (0.58 if corner % 2 == 0 else 0.25)
			angle = -math.pi / 2 + corner * math.pi / 5
			points.append(QPointF(box.center().x() + radius * math.cos(angle),
				box.center().y() + radius * math.sin(angle)))
		filled = state == 'filled'
		painter.setPen(QPen(active if filled else outline, 1.3 * scale, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
		painter.setBrush(active if filled else Qt.NoBrush)
		painter.drawPolygon(QPolygonF(points))
		return
	if state == 'on':
		painter.setPen(QPen(active, 1.2 * scale))
		painter.setBrush(active)
		painter.drawRoundedRect(box, 2 * scale, 2 * scale)
		painter.setPen(QPen(mark, 2 * scale, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
		path = QPainterPath(QPointF(box.left() + 3 * scale, box.center().y()))
		path.lineTo(box.left() + 5.5 * scale, box.bottom() - 3.5 * scale)
		path.lineTo(box.right() - 3 * scale, box.top() + 3.5 * scale)
		painter.setBrush(Qt.NoBrush)
		painter.drawPath(path)
	elif state == 'mixed':
		painter.setPen(QPen(active, 1.2 * scale))
		painter.setBrush(mark)
		painter.drawRoundedRect(box, 2 * scale, 2 * scale)
		painter.fillRect(QRectF(box.left() + 3.5 * scale, box.center().y() - scale, 6 * scale, 2 * scale), active)
	else:
		painter.setPen(QPen(outline, 1.4 * scale))
		painter.setBrush(Qt.NoBrush)
		painter.drawRoundedRect(box, 2 * scale, 2 * scale)


class CheckModel(QAbstractListModel):
	def __init__(self, owner):
		super().__init__(owner)
		self.owner = owner
		self.rows = ()

	def rowCount(self, parent=QModelIndex()):
		return 0 if parent.isValid() else len(self.rows)

	def data(self, index, role=Qt.DisplayRole):
		if not index.isValid() or not 0 <= index.row() < len(self.rows):
			return None
		row = self.rows[index.row()]
		if role == Qt.UserRole:
			return row
		if role == Qt.DisplayRole:
			return row.item.title
		description = '%s: %s' % (row.item.title, label(self.owner.prepared.states, self.owner.states[row.item.id]))
		if role == Qt.ToolTipRole:
			return description
		if role == Qt.AccessibleTextRole:
			return ', '.join(part for part in (description, row.item.hint, row.item.description,
				'' if row.item.enabled else 'unavailable') if part)

	def replace(self, rows):
		self.beginResetModel()
		self.rows = tuple(rows)
		self.endResetModel()


class CheckDelegate(QStyledItemDelegate):
	def __init__(self, parent, css, owner):
		super().__init__(parent)
		css = deepcopy(css)
		css['padding-left_px'] += INDICATOR
		css.setdefault('check', {key: QColor(default) for key, selector, default in CHECK_COLORS})
		self.css = css
		dim = css['description']['color']
		self.disabled_css = deepcopy(css)
		for role in ('title', 'hint'):
			self.disabled_css[role]['color'] = dim
		self.disabled_css['title']['highlight']['color'] = dim
		self.owner = owner

	def _renderer(self, option, index):
		row = index.data(Qt.UserRole)
		self.initStyleOption(option, index)
		css = self.css if row.item.enabled else self.disabled_css
		item = _RendererItem(row.item.title, row.item.hint, row.item.description, list(row.matches))
		return QuicksearchItemRenderer(item, option, css), row

	def sizeHint(self, option, index):
		return self._renderer(option, index)[0].sizeHint()

	def indicator_rect(self, rect, font):
		"""The indicator area of a row: left of the title, as high as the title line."""
		font = QFont(font)
		font.setPointSize(int(self.css['title']['font-size_pts']))
		top = rect.top() + self.css['border-top-width_px'] + self.css['padding-top_px']
		return QRectF(rect.left() + 4, top, INDICATOR - 6, QFontMetricsF(font).height())

	def paint(self, painter, option, index):
		renderer, row = self._renderer(option, index)
		renderer.render(painter)
		painter.save()
		painter.setRenderHint(QPainter.Antialiasing)
		if not row.item.enabled:
			painter.setOpacity(0.45)
		paint_indicator(painter, self.indicator_rect(option.rect, option.font),
			self.owner.states[row.item.id], self.css['check'])
		painter.restore()


class CheckView(QListView):
	cycle_requested = pyqtSignal(int, bool)
	approve_requested = pyqtSignal(bool)

	def keyPressEvent(self, event):
		key = event.key()
		shift = bool(event.modifiers() & Qt.ShiftModifier)
		if key == Qt.Key_Space:
			self.cycle_requested.emit(-1 if shift else 1, False)
		elif key == Qt.Key_Insert:
			self.cycle_requested.emit(1, True)
		elif key in (Qt.Key_Return, Qt.Key_Enter):
			self.approve_requested.emit(shift)
		else:
			super().keyPressEvent(event)

	def mousePressEvent(self, event):
		index = self.indexAt(event.pos())
		super().mousePressEvent(event)
		if index.isValid() and event.button() == Qt.LeftButton and \
				event.pos().x() - self.visualRect(index).left() < self.itemDelegate().css['padding-left_px']:
			self.cycle_requested.emit(1, False)


class QuickCheckList(QWidget):
	approved = pyqtSignal(str)

	def __init__(self, parent, prepared, css):
		require_ui_thread()
		super().__init__(parent)
		self.setAttribute(Qt.WA_StyledBackground)
		self.prepared = prepared
		self.states = {item.id: item.state for item in prepared.items}
		self.header = ElidedLabel(_one_line(prepared.title), self)
		self.header.setObjectName('quick-check-list-title')
		font = self.header.font()
		font.setBold(True)
		self.header.setFont(font)
		self.header.setCursor(Qt.SizeAllCursor)
		self.header.setVisible(bool(prepared.title))
		self.summary = ElidedLabel(_one_line(prepared.summary), self)
		self.summary.setVisible(bool(prepared.summary))
		self.query = QLineEdit(self)
		self.query.setAccessibleName('Filter')
		self.query.setVisible(prepared.fuzzy)
		self.view = CheckView(self)
		self.view.setAccessibleName(prepared.title or 'Items')
		self.view.setSelectionMode(QAbstractItemView.SingleSelection)
		self.view.setTabKeyNavigation(False)
		self.view.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
		# Rows taller than the viewport (multiline descriptions) stay scrollable.
		self.view.setVerticalScrollMode(QAbstractItemView.ScrollPerPixel)
		self.model = CheckModel(self)
		self.view.setModel(self.model)
		self.view.setItemDelegate(CheckDelegate(self.view, css, self))
		self.empty = QLabel('No matches', self)
		self.empty.setVisible(False)
		bar = QWidget(self)
		bar.setObjectName('quick-check-list-status')
		bar.setAttribute(Qt.WA_StyledBackground)
		self.status = ElidedLabel(_one_line(prepared.status), bar)
		self.count = QLabel(bar)
		self.count.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
		footer = QHBoxLayout(bar)
		footer.setContentsMargins(4, 3, 4, 1)
		footer.addWidget(self.status, 1)
		footer.addWidget(self.count)
		layout = QVBoxLayout(self)
		layout.setContentsMargins(6, 6, 6, 4)
		layout.setSpacing(4)
		for widget in (self.header, self.summary, self.query, self.empty):
			layout.addWidget(widget)
		layout.addWidget(self.view, 1)
		layout.addWidget(bar)
		self.setFocusProxy(self.query if prepared.fuzzy else self.view)
		self.query.textChanged.connect(self.refresh)
		self.query.installEventFilter(self)
		self.view.cycle_requested.connect(self.cycle)
		self.view.approve_requested.connect(self.approve)
		self.refresh()
		self.update_count()

	def refresh(self, *_):
		index = self.view.currentIndex()
		current = self.model.rows[index.row()].item.id if index.isValid() else None
		query = self.query.text()
		rows = []
		for item in self.prepared.items:
			if not query:
				rows.append(_Visible(item, ()))
				continue
			matches = match_positions(_subsequence_match, item.title, query)
			if matches is not None or match_positions(_subsequence_match, item.hint, query) is not None:
				rows.append(_Visible(item, matches or ()))
		self.model.replace(rows)
		row = next((position for position, visible in enumerate(rows) if visible.item.id == current), 0)
		if rows:
			self.view.selectionModel().setCurrentIndex(self.model.index(row, 0), QItemSelectionModel.ClearAndSelect)
		self.empty.setVisible(not rows)

	def cycle(self, step, advance=False):
		index = self.view.currentIndex()
		if not index.isValid():
			return
		item = self.model.rows[index.row()].item
		if item.enabled:
			self.states[item.id] = next_state(self.prepared.states, item.state, self.states[item.id], step)
			self.model.dataChanged.emit(index, index)
			self.update_count()
		if advance and index.row() + 1 < self.model.rowCount():
			self.view.setCurrentIndex(self.model.index(index.row() + 1, 0))

	def update_count(self):
		changed = sum(self.states[item.id] != item.state for item in self.prepared.items)
		self.count.setText('%d changed' % changed)

	def approve(self, alternate):
		if alternate and not self.prepared.alternate:
			return
		self.approved.emit('alternate' if alternate else 'primary')

	def result(self, approval):
		return result(self.prepared.items, self.states, approval)

	def fit_rows(self, limit):
		"""Size the list for up to MAX_VISIBLE_ROWS rows, but at most `limit` pixels high."""
		self.ensurePolished()
		rows = min(self.model.rowCount(), MAX_VISIBLE_ROWS)
		height = sum(self.view.sizeHintForRow(row) for row in range(rows))
		self.view.setMinimumHeight(min(height + 2 * self.view.frameWidth(), limit))

	def eventFilter(self, watched, event):
		if watched is self.query and event.type() == QEvent.KeyPress:
			if event.key() in (Qt.Key_Up, Qt.Key_Down, Qt.Key_PageUp, Qt.Key_PageDown):
				self.view.setFocus(Qt.OtherFocusReason)
				self.view.keyPressEvent(event)
				return True
			if event.key() in (Qt.Key_Return, Qt.Key_Enter):
				self.approve(bool(event.modifiers() & Qt.ShiftModifier))
				return True
		return super().eventFilter(watched, event)


class _Session:
	def __init__(self):
		self.done = Event()
		self.result = None
		self.window = None
		self.loop = None


class QuickCheckListWindow(ToolWindow):
	def __init__(self, main, session, prepared):
		super().__init__(main, _owner)
		self.setWindowFlags(Qt.Dialog | Qt.FramelessWindowHint)
		self.setWindowModality(Qt.WindowModal)
		self.setWindowTitle(prepared.title or 'QuickCheckList')
		self.main, self.session = main, session
		self.approval = None
		self.drag = None
		try:
			css = main._theme.get_quicksearch_item_css()
		except AttributeError:
			css = None
		self.list = QuickCheckList(self, prepared, css if isinstance(css, dict) else DEFAULT_CSS)
		self.focus_widget = self.list
		layout = QVBoxLayout(self)
		layout.setContentsMargins(1, 1, 1, 1)
		layout.addWidget(self.list)
		self.list.header.installEventFilter(self)
		self.list.approved.connect(self.finish)
		self.disposed.connect(self.cleanup)
		self.main.installEventFilter(self)

	def available_geometry(self):
		return (self.main.screen() or QApplication.primaryScreen()).availableGeometry()

	def present(self):
		available = self.available_geometry()
		# Half the screen for rows leaves room for the header, query and status bar.
		self.list.fit_rows(available.height() // 2)
		hint = self.sizeHint()
		self.resize(min(max(560, hint.width()), available.width()), min(hint.height(), available.height()))
		self.show()
		self.raise_()
		self.activateWindow()
		self.list.setFocus(Qt.OtherFocusReason)

	def finish(self, approval):
		self.approval = approval
		self.close()

	def eventFilter(self, watched, event):
		if watched is self.main and event.type() == QEvent.Close:
			self.close()
		elif watched is self.list.header:
			# The frameless window moves by dragging its title.
			if event.type() == QEvent.MouseButtonPress and event.button() == Qt.LeftButton:
				self.drag = event.globalPos() - self.frameGeometry().topLeft()
			elif event.type() == QEvent.MouseMove and self.drag is not None:
				self.move(event.globalPos() - self.drag)
			elif event.type() == QEvent.MouseButtonRelease:
				self.drag = None
		return False

	def cleanup(self):
		self.main.removeEventFilter(self)
		session = self.session
		session.result = self.list.result(self.approval)
		session.done.set()
		if session.loop is not None:
			session.loop.quit()


@run_in_main_thread
def _open(session, prepared):
	window = QuickCheckListWindow(_main_window(), session, prepared)
	session.window = window
	window.present()


def show_quick_check_list(*, items, states='checkbox', title='', summary='', status='', filter=None,
		alternate=False):
	"""Block until the user approves (Enter / Shift+Enter) or cancels; return CheckListResult."""
	prepared = prepare(items, states, title, summary, status, filter, alternate)
	session = _Session()
	_open(session, prepared)
	if is_in_main_thread():
		if not session.done.is_set():
			session.loop = QEventLoop()
			session.loop.exec_()
	else:
		session.done.wait()
	return session.result
