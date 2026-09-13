from fman.impl.ui import require_ui_thread
from fman.impl.ui.panel import IconButton
from PyQt5.QtCore import QEvent, QRectF, Qt, pyqtSignal
from PyQt5.QtGui import QFontDatabase, QIcon, QPainter, QPalette, QPixmap
from PyQt5.QtSvg import QSvgRenderer
from PyQt5.QtWidgets import QApplication, QFrame, QHBoxLayout, QLabel, QPlainTextEdit, QSizePolicy, QVBoxLayout


class _CopyButton(IconButton):
	def keyPressEvent(self, event):
		if event.key() in (Qt.Key_Return, Qt.Key_Enter) and event.modifiers() in (Qt.NoModifier, Qt.KeypadModifier):
			if not event.isAutoRepeat():
				self.click()
			event.accept()
		else:
			super().keyPressEvent(event)


class OutputTextBox(QFrame):
	copied = pyqtSignal()

	def __init__(self, text='', parent=None, *, title=''):
		require_ui_thread()
		if not isinstance(text, str):
			raise TypeError('Output text must be a string.')
		if not isinstance(title, str):
			raise TypeError('Output title must be a string.')
		super().__init__(parent)
		from fman.impl.application_context import get_application_context
		self.setObjectName('output-text-box')
		self.setAccessibleName('Output text')
		self._renderer = QSvgRenderer(get_application_context().get_resource('icons/copy.svg'), self)
		if not self._renderer.isValid():
			raise RuntimeError('Could not load the copy icon.')
		self._button = _CopyButton(self._icon(), 'Copy text', self)
		self._button.setCheckable(False)
		self._button.setFixedSize(24, 24)
		self._button.clicked.connect(self.copy_text)
		self._editor = QPlainTextEdit(self)
		self._editor.setAccessibleName('Output text')
		self._editor.setReadOnly(True)
		self._editor.setUndoRedoEnabled(False)
		self._editor.setAcceptDrops(False)
		self._editor.viewport().setAcceptDrops(False)
		self._editor.setTabChangesFocus(True)
		self._editor.setFont(QFontDatabase.systemFont(QFontDatabase.FixedFont))
		self._editor.setFrameShape(QFrame.NoFrame)
		self._editor.installEventFilter(self)
		self.setFocusProxy(self._editor)
		self.setFocusPolicy(Qt.StrongFocus)
		header = QHBoxLayout()
		header.setContentsMargins(0, 0, 0, 0)
		header.addWidget(self._button)
		self._title = ''
		self._title_label = QLabel(self)
		self._title_label.setObjectName('output-title')
		self._title_label.setTextFormat(Qt.PlainText)
		self._title_label.setMinimumWidth(0)
		self._title_label.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
		self._title_label.installEventFilter(self)
		header.addWidget(self._title_label, 1)
		layout = QVBoxLayout(self)
		layout.setContentsMargins(6, 4, 6, 6)
		layout.setSpacing(2)
		layout.addLayout(header)
		layout.addWidget(self._editor, 1)
		self.setFrameShape(QFrame.StyledPanel)
		self.set_text(text)
		self.set_title(title)

	def set_title(self, title):
		require_ui_thread()
		if not isinstance(title, str):
			raise TypeError('Output title must be a string.')
		self._title = title
		self._title_label.setToolTip(title)
		self._title_label.setAccessibleName(title)
		self._update_title()

	def title(self):
		require_ui_thread()
		return self._title

	def _update_title(self):
		self._title_label.setText(self._title_label.fontMetrics().elidedText(
			self._title, Qt.ElideMiddle, self._title_label.contentsRect().width()))

	def set_text(self, text):
		require_ui_thread()
		if not isinstance(text, str):
			raise TypeError('Output text must be a string.')
		self._text = text
		self._editor.setPlainText(text)
		self._button.setEnabled(bool(text))

	def text(self):
		require_ui_thread()
		return self._text

	def copy_text(self):
		require_ui_thread()
		if self.isEnabled() and self._text:
			QApplication.clipboard().setText(self._text)
			self.copied.emit()

	def eventFilter(self, watched, event):
		if watched is getattr(self, '_title_label', None) and event.type() in (QEvent.Resize, QEvent.FontChange, QEvent.StyleChange):
			self._update_title()
		if watched is self._editor and event.type() == QEvent.KeyPress:
			if event.key() in (Qt.Key_Return, Qt.Key_Enter) and event.modifiers() in (Qt.NoModifier, Qt.KeypadModifier):
				if not event.isAutoRepeat():
					self.copy_text()
				return True
		return super().eventFilter(watched, event)

	def event(self, event):
		result = super().event(event)
		if event.type() in (QEvent.PaletteChange, QEvent.StyleChange, QEvent.Show) and hasattr(self, '_button'):
			self._button.setIcon(self._icon())
		return result

	def _icon(self):
		ratio = self.devicePixelRatioF()
		pixmap = QPixmap(round(16 * ratio), round(16 * ratio))
		pixmap.setDevicePixelRatio(ratio)
		pixmap.fill(Qt.transparent)
		painter = QPainter(pixmap)
		self._renderer.render(painter, QRectF(0, 0, 16, 16))
		painter.setCompositionMode(QPainter.CompositionMode_SourceIn)
		painter.fillRect(0, 0, 16, 16, self.palette().color(QPalette.Text))
		painter.end()
		return QIcon(pixmap)