from _quick_view_pdf_worker import MAX_EDGE, MAX_PIXELS
from bisect import bisect_right
from collections import OrderedDict
from math import floor, sqrt
from PyQt5.QtCore import QEvent, QRectF, Qt, QTimer, pyqtSignal
from PyQt5.QtGui import QImage, QPainter
from PyQt5.QtWidgets import (
	QAbstractScrollArea, QButtonGroup, QGridLayout, QHBoxLayout, QLabel,
	QLineEdit, QSizePolicy, QStyle, QToolButton, QVBoxLayout, QWidget
)


MARGIN = 12
GAP = 16
MAX_SCROLL = 1000000000
CACHE_BYTES = 64 * 1024 * 1024
CACHE_PAGES = 6


def raster_size(width, height, ratio):
	width, height = max(1, width * ratio), max(1, height * ratio)
	factor = min(1, MAX_EDGE / width, MAX_EDGE / height, sqrt(MAX_PIXELS / (width * height)))
	return max(1, floor(width * factor)), max(1, floor(height * factor))


def page_layout(sizes, width, height, mode, zoom):
	available_width, available_height = max(1, width - MARGIN * 2), max(1, height - MARGIN * 2)
	scaled = []
	for page_width, page_height in sizes:
		if mode == 'fit_page':
			scale = min(available_width / page_width, available_height / page_height)
		elif mode == 'fit_width':
			scale = available_width / page_width
		else:
			scale = zoom * 96 / 72
		scaled.append((page_width * scale, page_height * scale, scale))
	content_width = max([width] + [item[0] + MARGIN * 2 for item in scaled])
	position = MARGIN
	rects, scales = [], []
	for page_width, page_height, scale in scaled:
		rects.append(QRectF((content_width - page_width) / 2, position, page_width, page_height))
		scales.append(scale)
		position += page_height + GAP
	return rects, scales, content_width, max(height, position - GAP + MARGIN)


class PdfCanvas(QAbstractScrollArea):
	requested = pyqtSignal(int, object)
	changed = pyqtSignal()

	def __init__(self, source, parent=None):
		super().__init__(parent)
		self.source = source
		self.sizes = ()
		self.rects = []
		self.scales = []
		self.tops = []
		self.cache = OrderedDict()
		self.errors = {}
		self.cache_bytes = 0
		self.mode = 'fit_page'
		self.zoom = 1.0
		self.revision = 0
		self.current_page = 0
		self.message = 'Loading PDF'
		self._vertical_unit = self._horizontal_unit = 1.0
		self._updating = False
		self._ratio = self.devicePixelRatioF()
		self._last_size = self.viewport().size()
		self._last_top = 0
		self._direction = 1
		self.timer = QTimer(self)
		self.timer.setSingleShot(True)
		self.timer.setInterval(100)
		self.timer.timeout.connect(self.request_pages)
		self.setFocusPolicy(Qt.StrongFocus)
		self.setAccessibleName('QuickView PDF')
		self.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOn)
		for bar in (self.horizontalScrollBar(), self.verticalScrollBar()):
			bar.setFocusPolicy(Qt.NoFocus)
			bar.valueChanged.connect(self._scrolled)

	def clear(self, message='Loading PDF'):
		self.timer.stop()
		self.sizes = ()
		self.rects = self.scales = self.tops = []
		self.cache.clear()
		self.errors.clear()
		self.cache_bytes = 0
		self.message = message
		self.current_page = 0
		self.revision += 1
		self.horizontalScrollBar().setRange(0, 0)
		self.verticalScrollBar().setRange(0, 0)
		self.viewport().update()
		self.changed.emit()

	def set_document(self, sizes):
		self.clear('')
		self.sizes = sizes
		self.mode, self.zoom = 'fit_page', 1.0
		self._refresh(anchor=(0, .5, 0))
		self.verticalScrollBar().setValue(0)
		self.timer.stop()
		self.request_pages()

	def _offset(self):
		return (self.horizontalScrollBar().value() * self._horizontal_unit,
			self.verticalScrollBar().value() * self._vertical_unit)

	def _visible(self):
		if not self.rects:
			return []
		horizontal, vertical = self._offset()
		bounds = QRectF(horizontal, vertical, self.viewport().width(), self.viewport().height())
		first = max(0, bisect_right(self.tops, vertical) - 1)
		visible = []
		for page in range(first, len(self.rects)):
			if self.rects[page].top() > bounds.bottom():
				break
			if self.rects[page].intersects(bounds):
				visible.append(page)
		return visible

	def _anchor(self):
		if not self.rects:
			return 0, .5, 0
		page = min(self.current_page, len(self.rects) - 1)
		rect = self.rects[page]
		horizontal, vertical = self._offset()
		return (page, (horizontal + self._last_size.width() / 2 - rect.left()) / rect.width(),
			(vertical + self._last_size.height() / 2 - rect.top()) / rect.height())

	def _refresh(self, anchor=None):
		if self._updating:
			return
		anchor = anchor if anchor is not None else self._anchor()
		self._updating = True
		try:
			for _ in range(2):
				size = self.viewport().size()
				self.rects, self.scales, width, height = page_layout(self.sizes, size.width(), size.height(), self.mode, self.zoom)
				for bar, total, visible, attribute in (
					(self.horizontalScrollBar(), width, size.width(), '_horizontal_unit'),
					(self.verticalScrollBar(), height, size.height(), '_vertical_unit')
				):
					extent = max(0, total - visible)
					unit = max(1, extent / MAX_SCROLL)
					setattr(self, attribute, unit)
					bar.setRange(0, min(MAX_SCROLL, round(extent / unit)))
					bar.setPageStep(max(1, round(visible / unit)))
					bar.setSingleStep(max(1, round(40 / unit)))
			self.tops = [rect.top() for rect in self.rects]
			if self.rects:
				page, fraction_x, fraction_y = anchor
				rect = self.rects[min(page, len(self.rects) - 1)]
				self.horizontalScrollBar().setValue(round((rect.left() + rect.width() * fraction_x - size.width() / 2) / self._horizontal_unit))
				self.verticalScrollBar().setValue(round((rect.top() + rect.height() * fraction_y - size.height() / 2) / self._vertical_unit))
			self._ratio = self.devicePixelRatioF()
			self._last_size = size
		finally:
			self._updating = False
		self.revision += 1
		self._update_current()
		self.viewport().update()
		if self.sizes:
			self.timer.start()

	def _update_current(self):
		visible = self._visible()
		if visible:
			horizontal, vertical = self._offset()
			bounds = QRectF(horizontal, vertical, self.viewport().width(), self.viewport().height())
			def area(page):
				rect = self.rects[page].intersected(bounds)
				return rect.width() * rect.height()
			self.current_page = max(visible, key=area)
		self.changed.emit()

	def _scrolled(self):
		if self._updating:
			return
		top = self._offset()[1]
		self._direction = 1 if top >= self._last_top else -1
		self._last_top = top
		self._update_current()
		self.viewport().update()
		if not self.timer.isActive():
			self.request_pages()

	def request_pages(self):
		visible = self._visible()
		if not visible:
			return
		ordered = sorted(visible, key=lambda page: (abs(page - self.current_page), page))
		neighbor = (visible[-1] + 1) if self._direction > 0 else (visible[0] - 1)
		if 0 <= neighbor < len(self.rects):
			ordered.append(neighbor)
		targets, budget, count = [], 0, 0
		for page in ordered:
			if page in self.errors:
				continue
			rect = self.rects[page]
			width, height = raster_size(rect.width(), rect.height(), self._ratio)
			cost = width * height * 4
			if count == CACHE_PAGES or budget + cost > CACHE_BYTES:
				break
			count += 1
			budget += cost
			key = page, width, height
			if key in self.cache:
				self.cache.move_to_end(key)
			else:
				targets.append(key)
		self.requested.emit(self.revision, tuple(targets))

	def set_page(self, revision, request, result):
		if revision != self.revision:
			return
		header, pixels = result
		image = QImage(pixels, header['width'], header['height'], header['stride'], QImage.Format_RGB32).copy()
		if image.isNull():
			self.set_error(request['page'], 'Cannot allocate PDF page')
			return
		page = request['page']
		for key in tuple(self.cache):
			if key[0] == page:
				self.cache_bytes -= self.cache.pop(key).sizeInBytes()
		key = page, request['width'], request['height']
		self.cache[key] = image
		self.cache_bytes += image.sizeInBytes()
		while len(self.cache) > CACHE_PAGES or self.cache_bytes > CACHE_BYTES:
			self.cache_bytes -= self.cache.popitem(last=False)[1].sizeInBytes()
		self.viewport().update()
		self.request_pages()

	def set_error(self, page, message):
		self.errors[page] = message
		self.viewport().update()
		self.request_pages()

	def set_mode(self, mode):
		if self.sizes:
			self.mode = mode
			self._refresh()

	def zoom_by(self, steps):
		if not self.sizes:
			return
		anchor = self._anchor()
		zoom = self.scales[self.current_page] * 72 / 96 if self.mode != 'manual' else self.zoom
		self.zoom = max(.25, min(4, zoom * 1.25 ** max(-40, min(40, steps))))
		self.mode = 'manual'
		self._refresh(anchor)

	def go_to(self, page):
		if self.rects:
			page = max(0, min(len(self.rects) - 1, page))
			self.verticalScrollBar().setValue(round(self.rects[page].top() / self._vertical_unit))

	def resizeEvent(self, event):
		super().resizeEvent(event)
		self._refresh()

	def paintEvent(self, event):
		if self._ratio != self.devicePixelRatioF():
			self._refresh()
		painter = QPainter(self.viewport())
		painter.fillRect(self.viewport().rect(), self.palette().base())
		if not self.rects:
			painter.setPen(self.palette().text().color())
			painter.drawText(self.viewport().rect().adjusted(12, 12, -12, -12), Qt.AlignCenter | Qt.TextWordWrap, self.message)
			return
		horizontal, vertical = self._offset()
		painter.setRenderHint(QPainter.SmoothPixmapTransform)
		for page in self._visible():
			rect = self.rects[page].translated(-horizontal, -vertical)
			painter.fillRect(rect, Qt.white)
			image = next((image for key, image in reversed(self.cache.items()) if key[0] == page), None)
			if image is not None:
				painter.drawImage(rect, image)
			else:
				painter.setPen(Qt.darkGray)
				painter.drawText(rect.intersected(QRectF(self.viewport().rect())).adjusted(8, 8, -8, -8),
					Qt.AlignCenter | Qt.TextWordWrap, self.errors.get(page, 'Loading page %d' % (page + 1)))
			painter.setPen(self.palette().mid().color())
			painter.drawRect(rect)

	def wheelEvent(self, event):
		if event.modifiers() == Qt.ControlModifier:
			self.zoom_by(event.angleDelta().y() / 120)
			event.accept()
		else:
			super().wheelEvent(event)

	def event(self, event):
		if event.type() == QEvent.KeyPress and event.key() in (Qt.Key_Tab, Qt.Key_Backtab, Qt.Key_Escape) and event.modifiers() in (Qt.NoModifier, Qt.ShiftModifier):
			self.source.setFocus()
			event.accept()
			return True
		return super().event(event)

	def keyPressEvent(self, event):
		key, modifiers = event.key(), event.modifiers() & ~Qt.KeypadModifier
		if modifiers == Qt.NoModifier and key in (Qt.Key_F, Qt.Key_W):
			self.set_mode('fit_page' if key == Qt.Key_F else 'fit_width')
		elif modifiers in (Qt.NoModifier, Qt.ShiftModifier) and key in (Qt.Key_Plus, Qt.Key_Equal, Qt.Key_Minus):
			self.zoom_by(-1 if key == Qt.Key_Minus else 1)
		elif modifiers == Qt.NoModifier and key in (Qt.Key_Up, Qt.Key_Down, Qt.Key_Left, Qt.Key_Right, Qt.Key_PageUp, Qt.Key_PageDown, Qt.Key_Home, Qt.Key_End):
			bar = self.horizontalScrollBar() if key in (Qt.Key_Left, Qt.Key_Right) else self.verticalScrollBar()
			if key in (Qt.Key_Home, Qt.Key_End):
				bar.setValue(bar.minimum() if key == Qt.Key_Home else bar.maximum())
			else:
				step = bar.pageStep() if key in (Qt.Key_PageUp, Qt.Key_PageDown) else bar.singleStep()
				bar.setValue(bar.value() + step * (-1 if key in (Qt.Key_Up, Qt.Key_Left, Qt.Key_PageUp) else 1))
		else:
			self.source.setFocus()
			self.source._controller.handle_shortcut(self.source, event)
		event.accept()


class PdfPreview(QWidget):
	def __init__(self, source, parent=None):
		super().__init__(parent)
		self.canvas = PdfCanvas(source, self)
		layout = QVBoxLayout(self)
		layout.setContentsMargins(0, 0, 0, 0)
		layout.setSpacing(4)
		layout.addWidget(self.canvas, 1)
		self.footer = QGridLayout()
		self.footer.setContentsMargins(0, 0, 0, 0)
		self.footer.setSpacing(4)
		layout.addLayout(self.footer)
		self.groups = []
		self.buttons = {}
		for _ in range(3):
			group = QWidget(self)
			group.setSizePolicy(QSizePolicy.Maximum, QSizePolicy.Fixed)
			row = QHBoxLayout(group)
			row.setContentsMargins(0, 0, 0, 0)
			row.setSpacing(4)
			self.groups.append(group)
		def button(group, name, text, tooltip, action, icon=None):
			widget = QToolButton(self)
			widget.setText(text)
			widget.setToolTip(tooltip)
			widget.setAccessibleName(tooltip)
			widget.setFocusPolicy(Qt.NoFocus)
			if icon is not None:
				widget.setIcon(self.style().standardIcon(icon))
			widget.clicked.connect(action)
			self.groups[group].layout().addWidget(widget)
			self.buttons[name] = widget
			return widget
		button(0, 'previous', '', 'Previous page', lambda: self.canvas.go_to(self.canvas.current_page - 1), QStyle.SP_ArrowUp)
		self.page_input = QLineEdit(self)
		self.page_input.setFixedWidth(46)
		self.page_input.setMaxLength(4)
		self.page_input.setAlignment(Qt.AlignCenter)
		self.page_input.setAccessibleName('PDF page number')
		self.page_input.setToolTip('Go to page')
		self.page_input.returnPressed.connect(self._commit_page)
		self.page_input.installEventFilter(self)
		self.groups[0].layout().addWidget(self.page_input)
		self.total = QLabel(self)
		self.groups[0].layout().addWidget(self.total)
		button(0, 'next', '', 'Next page', lambda: self.canvas.go_to(self.canvas.current_page + 1), QStyle.SP_ArrowDown)
		self.modes = QButtonGroup(self)
		for mode, text in (('fit_page', 'Fit Page'), ('fit_width', 'Fit Width')):
			widget = button(1, mode, text, text, lambda checked=False, mode=mode: self.canvas.set_mode(mode))
			widget.setCheckable(True)
			self.modes.addButton(widget)
		button(2, 'zoom_out', '-', 'Zoom out', lambda: self.canvas.zoom_by(-1))
		self.percentage = QLabel(self)
		self.percentage.setMinimumWidth(45)
		self.percentage.setAlignment(Qt.AlignCenter)
		self.groups[2].layout().addWidget(self.percentage)
		button(2, 'zoom_in', '+', 'Zoom in', lambda: self.canvas.zoom_by(1))
		self.canvas.changed.connect(self.update_controls)
		self._columns = None
		self.update_controls()

	def _commit_page(self):
		try:
			page = int(self.page_input.text())
			if 1 <= page <= len(self.canvas.sizes):
				self.canvas.go_to(page - 1)
		except ValueError:
			pass
		self.page_input.setText(str(self.canvas.current_page + 1) if self.canvas.sizes else '')
		self.canvas.setFocus()

	def update_controls(self):
		count = len(self.canvas.sizes)
		for widget in self.buttons.values():
			widget.setEnabled(bool(count))
		self.page_input.setEnabled(bool(count))
		if not self.page_input.hasFocus():
			self.page_input.setText(str(self.canvas.current_page + 1) if count else '')
		self.total.setText('/ %d' % count if count else '/ -')
		self.buttons['previous'].setEnabled(count > 0 and self.canvas.current_page > 0)
		self.buttons['next'].setEnabled(count > 0 and self.canvas.current_page + 1 < count)
		self.modes.setExclusive(False)
		for mode in ('fit_page', 'fit_width'):
			self.buttons[mode].setChecked(self.canvas.mode == mode)
		self.modes.setExclusive(True)
		self.percentage.setText('%g%%' % round(self.canvas.scales[self.canvas.current_page] * 75, 1) if count and self.canvas.scales else '')

	def resizeEvent(self, event):
		super().resizeEvent(event)
		columns = 3 if self.width() >= sum(group.sizeHint().width() for group in self.groups) + 8 else (2 if self.width() >= 340 else 1)
		if columns != self._columns:
			self._columns = columns
			for group in self.groups:
				self.footer.removeWidget(group)
			for index, group in enumerate(self.groups):
				self.footer.addWidget(group, index // columns, index % columns, Qt.AlignLeft)

	def eventFilter(self, watched, event):
		if watched is self.page_input and event.type() == QEvent.KeyPress:
			key, modifiers = event.key(), event.modifiers() & ~Qt.KeypadModifier
			if key == Qt.Key_Escape and modifiers == Qt.NoModifier:
				self.page_input.setText(str(self.canvas.current_page + 1))
				self.canvas.setFocus()
				return True
			if key in (Qt.Key_Tab, Qt.Key_Backtab) and modifiers in (Qt.NoModifier, Qt.ShiftModifier):
				self.canvas.source.setFocus()
				return True
			if modifiers & (Qt.AltModifier | Qt.MetaModifier) or (modifiers & Qt.ControlModifier and key not in
				(Qt.Key_A, Qt.Key_C, Qt.Key_V, Qt.Key_X, Qt.Key_Z, Qt.Key_Y, Qt.Key_Left, Qt.Key_Right, Qt.Key_Home, Qt.Key_End, Qt.Key_Backspace, Qt.Key_Delete)):
				self.canvas.source.setFocus()
				self.canvas.source._controller.handle_shortcut(self.canvas.source, event)
				return True
		return super().eventFilter(watched, event)