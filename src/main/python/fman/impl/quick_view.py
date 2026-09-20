from PyQt5.QtCore import QEvent, QObject, QPoint, QPointF, QRect, QRectF, Qt, QTimer, pyqtSignal, pyqtSlot
from PyQt5.QtGui import QBrush, QIcon, QImage, QPainter
from PyQt5.QtWidgets import (
	QAbstractScrollArea, QApplication, QButtonGroup, QHBoxLayout, QLabel,
	QSizePolicy, QStyle, QToolButton, QVBoxLayout, QWidget
)
from PyQt5 import sip
from fman.impl.quick_view_images import ImageLoader, ImageRequest, fit_scale, zoom_scale
from fman.impl.util.qt.thread import run_in_main_thread
from fman.url import basename
from math import ceil
from html import escape


class PreviewCanvas(QAbstractScrollArea):
	image_action = pyqtSignal(str, object)
	changed = pyqtSignal()

	def __init__(self, source, parent):
		super().__init__(parent)
		self.source = source
		self.message = 'No file selected'
		self.image = None
		self.mode = 'fit'
		self.scale = 1.0
		self._ratio = self.devicePixelRatioF()
		self._last_size = self.viewport().size()
		self._updating = False
		self._drag = None
		self.setFocusPolicy(Qt.StrongFocus)
		self.horizontalScrollBar().setFocusPolicy(Qt.NoFocus)
		self.verticalScrollBar().setFocusPolicy(Qt.NoFocus)
		self.setAccessibleName('QuickView image')
		self.setAcceptDrops(False)
		self.viewport().setAcceptDrops(False)
		self.horizontalScrollBar().valueChanged.connect(self.viewport().update)
		self.verticalScrollBar().valueChanged.connect(self.viewport().update)
		self._checker = QImage(24, 24, QImage.Format_RGB32)
		self._checker.fill(self.palette().light().color())
		painter = QPainter(self._checker)
		painter.fillRect(0, 0, 12, 12, self.palette().midlight())
		painter.fillRect(12, 12, 12, 12, self.palette().midlight())
		painter.end()

	def set_image(self, image, mode='fit', message=''):
		self.image = image
		self.message = message
		self.mode = mode
		self.scale = 1.0
		self._drag = None
		self.viewport().setCursor(Qt.OpenHandCursor if image is not None else Qt.ArrowCursor)
		self._refresh(center=True)

	def _origin(self, size=None):
		if self.image is None:
			return QPointF()
		size = size or self.viewport().size()
		factor = self.scale / self._ratio
		return QPointF(
			max(0, (size.width() - self.image.width() * factor) / 2) - self.horizontalScrollBar().value(),
			max(0, (size.height() - self.image.height() * factor) / 2) - self.verticalScrollBar().value()
		)

	def _image_point(self, position, size=None):
		return (QPointF(position) - self._origin(size)) * (self._ratio / self.scale)

	def _refresh(self, center=False, anchor=None, position=None):
		if self._updating:
			return
		self._updating = True
		try:
			if self.image is not None and anchor is None:
				anchor = QPointF(self.image.width() / 2, self.image.height() / 2) if center else self._image_point(QPointF(self._last_size.width() / 2, self._last_size.height() / 2), self._last_size)
			self._ratio = self.devicePixelRatioF()
			for _ in range(2):
				size = self.viewport().size()
				if self.image is None or self.mode == 'fit':
					self.horizontalScrollBar().setRange(0, 0)
					self.verticalScrollBar().setRange(0, 0)
					if self.image is not None:
						self.scale = fit_scale(self.image.width(), self.image.height(), size.width(), size.height(), self._ratio)
				else:
					factor = self.scale / self._ratio
					self.horizontalScrollBar().setRange(0, max(0, ceil(self.image.width() * factor - size.width())))
					self.verticalScrollBar().setRange(0, max(0, ceil(self.image.height() * factor - size.height())))
				self.horizontalScrollBar().setPageStep(size.width())
				self.verticalScrollBar().setPageStep(size.height())
			if self.image is not None and anchor is not None:
				position = position or QPointF(self.viewport().width() / 2, self.viewport().height() / 2)
				factor = self.scale / self._ratio
				self.horizontalScrollBar().setValue(round(anchor.x() * factor - position.x()))
				self.verticalScrollBar().setValue(round(anchor.y() * factor - position.y()))
			self._last_size = self.viewport().size()
		finally:
			self._updating = False
		self.viewport().update()
		self.changed.emit()

	def set_mode(self, mode):
		if self.image is None:
			return
		anchor = self._image_point(QPointF(self.viewport().width() / 2, self.viewport().height() / 2))
		self.mode = mode
		if mode == 'actual_size':
			self.scale = 1.0
		self._refresh(anchor=anchor)

	def zoom(self, steps, position=None):
		if self.image is None:
			return
		position = position or QPointF(self.viewport().width() / 2, self.viewport().height() / 2)
		anchor = self._image_point(position)
		self.mode = 'custom'
		self.scale = zoom_scale(self.scale, steps)
		self._refresh(anchor=anchor, position=position)

	def pan(self, direction, large=False):
		if self.image is None or direction not in ('left', 'right', 'up', 'down'):
			return
		bar = self.horizontalScrollBar() if direction in ('left', 'right') else self.verticalScrollBar()
		bar.setValue(bar.value() + (128 if large else 32) * (-1 if direction in ('left', 'up') else 1))

	def resizeEvent(self, event):
		super().resizeEvent(event)
		self._refresh()

	def focusNextPrevChild(self, forward):
		return False

	def keyPressEvent(self, event):
		key, modifiers = event.key(), event.modifiers()
		if key in (Qt.Key_Shift, Qt.Key_Control, Qt.Key_Alt, Qt.Key_Meta, Qt.Key_AltGr):
			event.accept()
			return
		if key in (Qt.Key_Tab, Qt.Key_Backtab, Qt.Key_Escape):
			self.source.setFocus()
		elif modifiers == Qt.NoModifier and key in (Qt.Key_F, Qt.Key_1):
			self.image_action.emit('fit' if key == Qt.Key_F else 'actual_size', None)
		elif modifiers in (Qt.NoModifier, Qt.ShiftModifier) and key in (Qt.Key_Plus, Qt.Key_Equal, Qt.Key_Minus):
			self.image_action.emit('zoom', -1 if key == Qt.Key_Minus else 1)
		elif modifiers in (Qt.NoModifier, Qt.ShiftModifier) and key in (Qt.Key_Left, Qt.Key_Right, Qt.Key_Up, Qt.Key_Down):
			direction = {Qt.Key_Left: 'left', Qt.Key_Right: 'right', Qt.Key_Up: 'up', Qt.Key_Down: 'down'}[key]
			self.image_action.emit('pan', (direction, modifiers == Qt.ShiftModifier))
		else:
			self.source.setFocus()
			if self.source.hasFocus():
				self.source._controller.handle_shortcut(self.source, event)
		event.accept()

	def mousePressEvent(self, event):
		self.source.setFocus(Qt.MouseFocusReason)
		self.setFocus(Qt.MouseFocusReason)
		if self.image is not None and event.button() == Qt.LeftButton:
			self._drag = event.pos(), self.horizontalScrollBar().value(), self.verticalScrollBar().value()
			self.viewport().setCursor(Qt.ClosedHandCursor)
			event.accept()
		else:
			super().mousePressEvent(event)

	def mouseMoveEvent(self, event):
		if self._drag is not None:
			position, horizontal, vertical = self._drag
			delta = event.pos() - position
			self.horizontalScrollBar().setValue(horizontal - delta.x())
			self.verticalScrollBar().setValue(vertical - delta.y())
			event.accept()
		else:
			super().mouseMoveEvent(event)

	def mouseReleaseEvent(self, event):
		self._drag = None
		self.viewport().setCursor(Qt.OpenHandCursor if self.image is not None else Qt.ArrowCursor)
		super().mouseReleaseEvent(event)

	def wheelEvent(self, event):
		if event.modifiers() & Qt.ControlModifier:
			self.zoom(event.angleDelta().y() / 120, QPointF(event.pos()))
			event.accept()
		elif event.modifiers() & Qt.ShiftModifier:
			bar = self.horizontalScrollBar()
			bar.setValue(bar.value() - event.angleDelta().y())
			event.accept()
		else:
			super().wheelEvent(event)

	def paintEvent(self, event):
		if self._ratio != self.devicePixelRatioF():
			self._refresh()
		painter = QPainter(self.viewport())
		painter.fillRect(self.viewport().rect(), self.palette().base())
		if self.image is None:
			painter.setPen(self.palette().text().color())
			painter.drawText(self.viewport().rect().adjusted(16, 16, -16, -16), Qt.AlignCenter | Qt.TextWordWrap, self.message)
			return
		factor = self.scale / self._ratio
		origin = self._origin()
		if self.scale == 1:
			origin = QPointF(round(origin.x() * self._ratio) / self._ratio, round(origin.y() * self._ratio) / self._ratio)
		destination = QRectF(origin.x(), origin.y(), self.image.width() * factor, self.image.height() * factor)
		visible = destination.intersected(QRectF(self.viewport().rect()))
		if visible.isEmpty():
			return
		painter.fillRect(visible, QBrush(self._checker))
		region = QRectF((visible.x() - origin.x()) / factor, (visible.y() - origin.y()) / factor, visible.width() / factor, visible.height() / factor)
		painter.setRenderHint(QPainter.SmoothPixmapTransform, self.scale != 1)
		painter.drawImage(visible, self.image, region)


class QuickViewOverlay(QWidget):
	close_requested = pyqtSignal()

	def __init__(self, window, source, target):
		super().__init__(window.centralWidget())
		self.source, self.target = source, target
		self.splitter = window._splitter
		self._disposed = False
		self._title = 'QuickView'
		self.image_format = ''
		self.setAutoFillBackground(True)
		self.setAcceptDrops(False)
		self.setObjectName('QuickView')
		self.setMinimumSize(0, 0)
		layout = QVBoxLayout(self)
		layout.setContentsMargins(6, 6, 6, 6)
		layout.setSpacing(4)
		header = QHBoxLayout()
		self.title = QLabel('QuickView', self)
		self.title.setTextFormat(Qt.PlainText)
		self.title.setMinimumWidth(0)
		self.title.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
		header.addWidget(self.title, 1)
		close = QToolButton(self)
		close.setIcon(self.style().standardIcon(QStyle.SP_TitleBarCloseButton))
		close.setToolTip('Close QuickView')
		close.setAccessibleName('Close QuickView')
		close.setFocusPolicy(Qt.NoFocus)
		close.clicked.connect(self.close_requested)
		header.addWidget(close)
		layout.addLayout(header)
		self.canvas = PreviewCanvas(source, self)
		layout.addWidget(self.canvas, 1)
		controls = QHBoxLayout()
		self.buttons = {}
		self.modes = QButtonGroup(self)
		for name, text, tooltip, icon in (
			('fit', 'Fit', 'Fit image', ''), ('actual_size', '100%', 'One image pixel per screen pixel', ''),
			('zoom_out', '-', 'Zoom out', 'zoom-out'), ('zoom_in', '+', 'Zoom in', 'zoom-in')
		):
			button = QToolButton(self)
			button.setText(text)
			if icon and not QIcon.fromTheme(icon).isNull():
				button.setIcon(QIcon.fromTheme(icon))
			button.setToolTip(tooltip)
			button.setAccessibleName(tooltip)
			button.setFocusPolicy(Qt.NoFocus)
			if name in ('fit', 'actual_size'):
				button.setCheckable(True)
				self.modes.addButton(button)
			button.clicked.connect(lambda checked=False, action=name: self.canvas.image_action.emit(action, None))
			self.buttons[name] = button
			controls.addWidget(button)
		self.metadata = QLabel(self)
		self.metadata.setTextFormat(Qt.PlainText)
		self.metadata.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
		controls.addWidget(self.metadata, 1)
		layout.addLayout(controls)
		self.canvas.changed.connect(self.update_controls)
		self.update_controls()
		self.target.installEventFilter(self)
		self.splitter.installEventFilter(self)
		self.splitter.splitterMoved.connect(self.sync_geometry)
		self.sync_geometry()

	def focus_canvas(self):
		self.source.setFocus()
		self.canvas.setFocus()

	def set_title(self, title):
		self._title = title or 'QuickView'
		self.title.setToolTip('<qt>' + escape(self._title) + '</qt>')
		self.title.setText(self.title.fontMetrics().elidedText(self._title, Qt.ElideMiddle, self.title.width()))

	def resizeEvent(self, event):
		super().resizeEvent(event)
		self.set_title(self._title)

	def update_controls(self):
		canvas = self.canvas
		self.modes.setExclusive(False)
		for name, button in self.buttons.items():
			button.setEnabled(canvas.image is not None)
			if button.isCheckable():
				button.setChecked(name == canvas.mode)
		self.modes.setExclusive(True)
		text = '' if canvas.image is None else '%s  %s x %s  |  %g%%' % (self.image_format.upper(), canvas.image.width(), canvas.image.height(), round(canvas.scale * 100, 1))
		self.metadata.setText(text)
		self.metadata.setToolTip(text)

	def sync_geometry(self, *_):
		if self._disposed:
			return
		self.setGeometry(QRect(self.target.mapTo(self.parentWidget(), QPoint(0, 0)), self.target.size()))
		self.setVisible(self.target.isVisible())
		self.raise_()

	def eventFilter(self, watched, event):
		if self._disposed:
			return False
		if watched is self.target and event.type() == QEvent.Hide:
			self.hide()
		elif (watched is self.target and event.type() in (QEvent.Resize, QEvent.Move, QEvent.Show)) or (
			watched is self.splitter and event.type() in (QEvent.Resize, QEvent.Move)
		):
			self.sync_geometry()
		return False

	def dispose(self):
		if self._disposed:
			return
		self._disposed = True
		if not sip.isdeleted(self.target):
			self.target.removeEventFilter(self)
		if not sip.isdeleted(self.splitter):
			self.splitter.removeEventFilter(self)
			self.splitter.splitterMoved.disconnect(self.sync_geometry)
		if not sip.isdeleted(self.source) and self.isAncestorOf(QApplication.focusWidget()):
			self.source.setFocus()
		self.canvas.set_image(None)
		self.hide()
		self.deleteLater()


class LoaderBridge(QObject):
	ready = pyqtSignal()

	def __init__(self, window, load=None):
		super().__init__(window)
		self.window = window
		self.closed = False
		self.loader = ImageLoader(self.ready.emit, **({'load': load} if load is not None else {}))
		self.ready.connect(self.receive, Qt.QueuedConnection)
		window.closed.connect(self.close)

	@pyqtSlot()
	def receive(self):
		if self.closed:
			return
		result = self.loader.take_result()
		session = getattr(self.window, '_quick_view_session', None)
		if session is not None and result is not None:
			request, image = result
			if request.generation == session.generation:
				session.show_result(image)
		if session is None and not self.loader.busy:
			self.close()

	def close(self):
		if self.closed:
			return
		self.closed = True
		self.loader.close()
		self.ready.disconnect(self.receive)
		try:
			self.window.closed.disconnect(self.close)
		except (RuntimeError, TypeError):
			pass
		if getattr(self.window, '_quick_view_loader', None) is self:
			self.window._quick_view_loader = None
		self.deleteLater()


class QuickViewSession(QObject):
	def __init__(self, window, source, target, owner=None, load=None):
		super().__init__(window)
		from fman import load_json
		self.window, self.source, self.target, self.owner = window, source, target, owner
		self.closed = False
		self._connections = []
		self._loading_location = False
		self._url = None
		settings = load_json('QuickView.json', default={})
		self.preferred_mode = settings.get('image_mode', 'fit') if isinstance(settings, dict) else 'fit'
		if self.preferred_mode not in ('fit', 'actual_size'):
			self.preferred_mode = 'fit'
		self.bridge = getattr(window, '_quick_view_loader', None)
		if self.bridge is None:
			self.bridge = window._quick_view_loader = LoaderBridge(window, load)
		self.generation = self.bridge.loader.invalidate()
		self.overlay = QuickViewOverlay(window, source, target)
		self.timer = QTimer(self)
		self.timer.setSingleShot(True)
		self.timer.setInterval(100)
		self._connect(self.timer.timeout, self._submit)
		self._connect(self.overlay.close_requested, self.close)
		self._connect(self.overlay.canvas.image_action, self.image_action)
		self._connect(source._file_view.selectionModel().currentChanged, self.cursor_changed)
		self._connect(source._model.modelAboutToBeReset, self._reset)
		self._connect(source._model.modelReset, self.cursor_changed)
		self._connect(source._model.location_changed, self._location_changed)
		self._connect(source._model.location_loaded, self._location_loaded)
		self._connect(source.destroyed, self.shutdown)
		self._connect(target.destroyed, self.shutdown)
		self._connect(window.closed, self.shutdown)
		window._quick_view_session = self
		if owner is not None and not owner.attach(self.shutdown):
			self.shutdown()
			return
		self.cursor_changed()

	def _connect(self, signal, callback):
		signal.connect(callback)
		self._connections.append((signal, callback))

	def _reset(self, *_):
		self._url = ''
		self._clear('Loading folder')

	def _location_changed(self, *_):
		self._loading_location = True
		self._reset()

	def _location_loaded(self, *_):
		self._loading_location = False
		self.cursor_changed()

	def _clear(self, message):
		self.timer.stop()
		self.generation = self.bridge.loader.invalidate()
		self.overlay.image_format = ''
		self.overlay.canvas.set_image(None, self.preferred_mode, message)

	def cursor_changed(self, *_):
		if self.closed or self._loading_location:
			return
		url = self.source.get_file_under_cursor()
		if url == self._url:
			return
		self._url = url
		self._clear('Loading' if url else 'No file selected')
		self.overlay.set_title(basename(url) if url else 'QuickView')
		if url:
			self.timer.start()

	def _submit(self):
		if not self.closed and self._url:
			self.bridge.loader.submit(ImageRequest(self.generation, self._url))

	def show_result(self, result):
		self.overlay.image_format = result.format
		self.overlay.canvas.set_image(result.image, self.preferred_mode, result.message)

	def switch_focus(self, pane_index=None):
		if self.closed:
			return False
		if pane_index is None:
			to_source = self.overlay.isAncestorOf(QApplication.focusWidget())
		else:
			pane = self.window.get_panes()[pane_index]
			to_source = pane is self.source
		if to_source:
			self.source.setFocus()
		else:
			self.overlay.focus_canvas()
		return True

	def image_action(self, name, value=None):
		canvas = self.overlay.canvas
		if canvas.image is None:
			return
		if name in ('fit', 'actual_size'):
			canvas.set_mode(name)
			self.preferred_mode = name
			from fman import load_json, save_json
			try:
				settings = load_json('QuickView.json', default={})
				settings = dict(settings) if isinstance(settings, dict) else {}
				settings['image_mode'] = name
				save_json('QuickView.json', settings)
			except (OSError, ValueError):
				self.window.show_status_message('QuickView preference could not be saved.', 3)
		elif name in ('zoom', 'zoom_in', 'zoom_out'):
			canvas.zoom(value if name == 'zoom' else (1 if name == 'zoom_in' else -1))
		elif name == 'pan':
			canvas.pan(*value)

	def close(self, *_):
		if self.closed:
			return
		self.closed = True
		self.timer.stop()
		self.bridge.loader.invalidate()
		for signal, callback in self._connections:
			try:
				signal.disconnect(callback)
			except (RuntimeError, TypeError):
				pass
		self._connections.clear()
		if self.owner is not None:
			self.owner.detach(self.shutdown)
		if getattr(self.window, '_quick_view_session', None) is self:
			self.window._quick_view_session = None
		self.overlay.dispose()
		if not self.bridge.loader.busy:
			self.bridge.close()
		self.deleteLater()

	@run_in_main_thread
	def shutdown(self, *_):
		self.close()
		self.bridge.close()