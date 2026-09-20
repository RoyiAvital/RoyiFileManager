from copy import deepcopy
from threading import Event

from fman import load_json, save_json
from fman.impl.ui import require_ui_thread, resource, submit_work
from PyQt5.QtCore import QDate, QEvent, QObject, QPoint, QRect, Qt, QSignalBlocker, QSize, pyqtSignal
from PyQt5.QtGui import QIcon, QKeySequence, QValidator
from PyQt5.QtWidgets import QAbstractSpinBox, QApplication, QComboBox, QDateEdit, QFrame, QHBoxLayout, QLabel, QLayout, QPushButton, QToolButton, QShortcut, QSizePolicy, QStyle, QWidget


class ExactIntegerInput(QAbstractSpinBox):
	value_changed = pyqtSignal()

	def __init__(self, minimum, maximum, parent=None):
		super().__init__(parent)
		self.minimum, self.maximum = minimum, maximum
		self._value = None
		self.lineEdit().textChanged.connect(self._edited)
		self.setMinimumWidth(110)

	def validate(self, content, position):
		if not content:
			state = QValidator.Acceptable
		elif not content.isascii() or not content.isdecimal() or len(content) > 20:
			state = QValidator.Invalid
		else:
			value = int(content)
			state = QValidator.Acceptable if self.minimum <= value <= self.maximum else QValidator.Invalid
		return state, content, position

	def fixup(self, content):
		return '' if self._value is None else str(self._value)

	def value(self):
		return self._value

	def set_value(self, value):
		self._value = value
		self.lineEdit().setText('' if value is None else str(value))

	def clear(self):
		self.set_value(None)

	def _edited(self, content):
		if self.validate(content, 0)[0] == QValidator.Acceptable:
			self._value = int(content) if content else None
			self.value_changed.emit()

	def stepBy(self, steps):
		self.set_value(self.minimum if self._value is None else max(self.minimum, min(self.maximum, self._value + steps)))

	def stepEnabled(self):
		flags = QAbstractSpinBox.StepNone
		if self._value is None or self._value < self.maximum:
			flags |= QAbstractSpinBox.StepUpEnabled
		if self._value is not None and self._value > self.minimum:
			flags |= QAbstractSpinBox.StepDownEnabled
		return flags


class OptionalDateInput(QDateEdit):
	value_changed = pyqtSignal()

	def __init__(self, parent=None):
		super().__init__(parent)
		self.setMinimumDate(QDate(1752, 9, 13))
		self.setSpecialValueText(' ')
		self.setDisplayFormat('yyyy-MM-dd')
		self.setCalendarPopup(True)
		self.set_value(None)
		self.dateChanged.connect(lambda date: self.value_changed.emit())
		self.lineEdit().textChanged.connect(self._edited)

	def validate(self, content, position):
		if not content.strip():
			return QValidator.Acceptable, content, position
		return super().validate(content, position)

	def dateTimeFromText(self, content):
		if not content.strip():
			return self.minimumDateTime()
		return super().dateTimeFromText(content)

	def _edited(self, content):
		if not content.strip() and self.date() != self.minimumDate():
			self.clear()

	def keyPressEvent(self, event):
		activating = self.value() is None and event.text().isascii() and event.text().isdigit()
		if activating:
			with QSignalBlocker(self):
				self.setDate(QDate.currentDate())
			self.setSelectedSection(QDateEdit.YearSection)
		if event.text() == '-' and self.lineEdit().hasSelectedText():
			event.accept()
			return
		super().keyPressEvent(event)
		if activating:
			self.value_changed.emit()

	def clear(self):
		self.set_value(None)

	def value(self):
		return None if self.date() == self.minimumDate() else self.date().toString('yyyy-MM-dd')

	def set_value(self, value):
		self.setDate(self.minimumDate() if value is None else QDate.fromString(value, 'yyyy-MM-dd'))


class OptionalField(QWidget):
	value_changed = pyqtSignal()

	def __init__(self, record, is_date, parent=None):
		super().__init__(parent)
		self.is_date = is_date
		layout = QHBoxLayout(self)
		layout.setContentsMargins(0, 0, 0, 0)
		layout.setSpacing(6)
		label = QLabel(record.label, self)
		layout.addWidget(label)
		if is_date:
			self.editor = OptionalDateInput(self)
			self.editor.calendarWidget().installEventFilter(self)
		else:
			self.editor = ExactIntegerInput(record.minimum, record.maximum, self)
		self.editor.value_changed.connect(self.value_changed)
		label.setBuddy(self.editor)
		self.editor.setAccessibleName(record.label)
		self.editor.setToolTip(record.tooltip or record.label)
		layout.addWidget(self.editor, 1)
		self.set_value(record.value)
		self.setFocusProxy(self.editor)

	def eventFilter(self, watched, event):
		if self.is_date and watched is self.editor.calendarWidget() and event.type() == QEvent.Show and self.value() is None:
			today = QDate.currentDate()
			watched.setCurrentPage(today.year(), today.month())
		if self.is_date and watched is self.editor.calendarWidget() and event.type() == QEvent.ShortcutOverride and event.key() == Qt.Key_Escape:
			event.accept()
			return True
		return super().eventFilter(watched, event)

	def value(self):
		return self.editor.value()

	def set_value(self, value):
		with QSignalBlocker(self.editor):
			self.editor.set_value(value)


class WrappingRow(QLayout):
	def __init__(self, parent=None):
		super().__init__(parent)
		self.items = []
		self.setContentsMargins(0, 0, 0, 0)
		self.setSpacing(8)

	def addItem(self, item):
		self.items.append(item)

	def count(self):
		return len(self.items)

	def itemAt(self, index):
		return self.items[index] if 0 <= index < len(self.items) else None

	def takeAt(self, index):
		return self.items.pop(index) if 0 <= index < len(self.items) else None

	def expandingDirections(self):
		return Qt.Horizontal

	def hasHeightForWidth(self):
		return True

	def heightForWidth(self, width):
		return self._arrange(QRect(0, 0, width, 0), False)

	def setGeometry(self, rect):
		super().setGeometry(rect)
		self._arrange(rect, True)

	def minimumSize(self):
		return QSize(max((item.minimumSize().width() for item in self.items), default=0),
			max((item.minimumSize().height() for item in self.items), default=0))

	def sizeHint(self):
		return QSize(sum(item.sizeHint().width() + self.spacing() for item in self.items), self.minimumSize().height())

	def _arrange(self, rect, apply):
		lines, line, used = [], [], 0
		for item in self.items:
			size = item.sizeHint().expandedTo(item.minimumSize()).boundedTo(item.maximumSize())
			size.setWidth(min(size.width(), rect.width()))
			if line and used + self.spacing() + size.width() > rect.width():
				lines.append(line)
				line, used = [], 0
			used += (self.spacing() if line else 0) + size.width()
			line.append((item, size))
		if line:
			lines.append(line)
		top = rect.y()
		for line in lines:
			height = max(size.height() for item, size in line)
			spare = rect.width() - sum(size.width() for item, size in line) - self.spacing() * (len(line) - 1)
			growing = [(item, size) for item, size in line
				if item.expandingDirections() & Qt.Horizontal and size.width() < item.maximumSize().width()]
			while spare > 0 and growing:
				share = max(1, spare // len(growing))
				for item, size in growing:
					added = min(share, spare, item.maximumSize().width() - size.width())
					size.setWidth(size.width() + added)
					spare -= added
				growing = [(item, size) for item, size in growing if size.width() < item.maximumSize().width()]
			left = rect.x()
			for item, size in line:
				if apply:
					item.setGeometry(QRect(QPoint(left, top + height - size.height()), size))
				left += size.width() + self.spacing()
			top += height + self.spacing()
		return top - rect.y() - (self.spacing() if lines else 0)


class IconButton(QToolButton):
	value_changed = pyqtSignal(object)

	def __init__(self, icon, label, parent=None):
		require_ui_thread()
		super().__init__(parent)
		if not label or not isinstance(icon, QIcon) or icon.isNull():
			raise ValueError('IconButton requires an icon and an accessible label.')
		self.setIcon(icon)
		self.setIconSize(QSize(16, 16))
		self.setToolTip(label)
		self.setAccessibleName(label)
		self.setCheckable(True)
		self.setAutoRaise(True)
		self.toggled.connect(lambda checked: self.value_changed.emit(checked))

	def accepts(self, value):
		return type(value) is bool

	def value(self):
		return self.isChecked()

	def set_value(self, value):
		if not self.accepts(value):
			raise ValueError('Expected a boolean setting.')
		self.setChecked(value)


class TextButton(QPushButton):
	value_changed = pyqtSignal(object)

	def __init__(self, text, parent=None, checkable=False, max_width=160):
		require_ui_thread()
		if type(max_width) is not int or max_width <= 0:
			raise ValueError('Button maximum width must be a positive integer.')
		super().__init__(text, parent)
		self._max_width = max_width
		self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
		self.setMaximumWidth(max(max_width, self.minimumSizeHint().width()))
		self.setAutoDefault(False)
		self.setCheckable(checkable)
		self.setAccessibleName(text)
		self.toggled.connect(lambda checked: self.value_changed.emit(checked))

	def event(self, event):
		result = super().event(event)
		if event.type() in (QEvent.Polish, QEvent.StyleChange, QEvent.FontChange, QEvent.LayoutRequest) and hasattr(self, '_max_width'):
			self.setMaximumWidth(max(self._max_width, self.minimumSizeHint().width()))
		return result

	def accepts(self, value):
		return self.isCheckable() and type(value) is bool

	def value(self):
		return self.isChecked()

	def set_value(self, value):
		if not self.accepts(value):
			raise ValueError('Only checkable text buttons can bind boolean settings.')
		self.setChecked(value)


class DropDown(QComboBox):
	value_changed = pyqtSignal(object)

	def __init__(self, choices, label, parent=None):
		require_ui_thread()
		super().__init__(parent)
		self.setAccessibleName(label)
		self.setToolTip(label)
		for title, value in choices:
			if type(value) not in (str, int, float, bool) or self.accepts(value):
				raise ValueError('Choices require unique scalar JSON values.')
			self.addItem(title, value)
		if not self.count():
			raise ValueError('DropDown requires at least one choice.')
		self.currentIndexChanged.connect(lambda: self.value_changed.emit(self.value()))

	def accepts(self, value):
		return any(type(self.itemData(index)) is type(value) and self.itemData(index) == value for index in range(self.count()))

	def value(self):
		return self.currentData()

	def set_value(self, value):
		for index in range(self.count()):
			if type(self.itemData(index)) is type(value) and self.itemData(index) == value:
				self.setCurrentIndex(index)
				return
		raise ValueError('Unknown choice value.')


class Panel(QFrame):
	def __init__(self, parent=None):
		require_ui_thread()
		super().__init__(parent)
		self.setObjectName('panel')
		self.setAttribute(Qt.WA_StyledBackground)
		layout = QHBoxLayout(self)
		layout.setContentsMargins(10, 7, 10, 7)
		layout.setSpacing(6)

	def add(self, widget, stretch=None):
		if stretch is None:
			stretch = 1 if isinstance(widget, TextButton) else 0
		self.layout().addWidget(widget, stretch)
		return widget

	def add_stretch(self):
		self.layout().addStretch()




class PanelDock(QFrame):
	def __init__(self, panel, close_session, parent, focus_session=None):
		super().__init__(parent)
		self.panel = panel
		self.close_session = close_session
		self.focus_session = focus_session
		self.setObjectName('plugin-panel-dock')
		self.setAttribute(Qt.WA_StyledBackground)
		layout = QHBoxLayout(self)
		layout.setContentsMargins(0, 0, 6, 0)
		layout.setSpacing(0)
		layout.addWidget(panel, 1)
		self.close_button = QToolButton(self)
		self.close_button.setIcon(self.style().standardIcon(QStyle.SP_TitleBarCloseButton))
		self.close_button.setIconSize(QSize(12, 12))
		self.close_button.setFixedSize(22, 22)
		self.close_button.setAutoRaise(True)
		self.close_button.setToolTip('Close panel')
		self.close_button.setAccessibleName('Close panel')
		self.close_button.clicked.connect(lambda checked=False: close_session())
		layout.addWidget(self.close_button, 0, Qt.AlignTop)
		self.escape = QShortcut(QKeySequence(Qt.Key_Escape), self)
		self.escape.setContext(Qt.WidgetWithChildrenShortcut)
		self.escape.activated.connect(close_session)
		for widget in self.panel.findChildren(QWidget):
			if not widget.isWindow():
				widget.installEventFilter(self)

	def eventFilter(self, watched, event):
		if event.type() in (QEvent.ShortcutOverride, QEvent.KeyPress) and event.key() in (Qt.Key_Tab, Qt.Key_Backtab) and not QApplication.activePopupWidget():
			if event.type() == QEvent.ShortcutOverride:
				event.accept()
				return True
			return self.focusNextPrevChild(event.key() == Qt.Key_Tab and not event.modifiers() & Qt.ShiftModifier)
		return super().eventFilter(watched, event)

	def focusNextPrevChild(self, next):
		controls = []
		widget = self.nextInFocusChain()
		while widget is not self:
			if self.isAncestorOf(widget) and widget.focusPolicy() & Qt.TabFocus and widget.isVisible() and widget.isEnabled():
				control = widget
				while control.focusProxy() is not None:
					control = control.focusProxy()
				if isinstance(control.parentWidget(), QAbstractSpinBox):
					control = control.parentWidget()
				if control not in controls:
					controls.append(control)
			widget = widget.nextInFocusChain()
		if hasattr(self.panel, 'tab_controls'):
			controls = [control for control in (*self.panel.tab_controls, self.close_button)
				if control.isVisible() and control.isEnabled()]
		current = QApplication.focusWidget()
		if current is not None and isinstance(current.parentWidget(), QAbstractSpinBox):
			current = current.parentWidget()
		if current in controls:
			index = controls.index(current) + (1 if next else -1)
			if 0 <= index < len(controls):
				controls[index].setFocus(Qt.TabFocusReason if next else Qt.BacktabFocusReason)
				return True
			if self.focus_session is not None:
				self.focus_session(not next)
				return True
			controls[0 if next else -1].setFocus()
			return True
		return False


class JsonSettings(QObject):
	changed = pyqtSignal(object)
	failed = pyqtSignal(str)
	busy_changed = pyqtSignal(bool)
	_delivered = pyqtSignal(object)

	def __init__(self, filename, parent, owner=None):
		require_ui_thread()
		super().__init__(parent)
		if not filename.endswith('.json') or '/' in filename or '\\' in filename:
			raise ValueError('Use a plug-in-specific JSON filename, not a path.')
		self.filename = filename
		self._resource = resource(filename)
		self._bindings = {}
		self._values = {}
		self._revision = -1
		self.busy = False
		self._alive = Event()
		self._alive.set()
		self._owner = owner
		self._delivered.connect(self._receive, Qt.QueuedConnection)
		alive, settings_resource, subscriber = self._alive, self._resource, self._publish
		def dispose():
			alive.clear()
			settings_resource.unsubscribe(subscriber)
			if owner:
				owner.detach(dispose)
		self.dispose = dispose
		self.destroyed.connect(dispose)
		if owner and not owner.attach(dispose):
			dispose()

	def bind(self, key, control, default):
		if self._revision >= 0 or self.busy:
			raise RuntimeError('Bind controls before loading settings.')
		if key in self._bindings or not isinstance(key, str) or not key:
			raise ValueError('Setting keys must be unique nonempty strings.')
		if not control.accepts(default):
			raise ValueError('Default does not match the control.')
		self._bindings[key] = (control, default)
		with QSignalBlocker(control):
			control.set_value(default)
		control.setEnabled(False)
		control.value_changed.connect(lambda value: self._save(key, value))

	def load(self):
		self._start(None)

	@property
	def loaded(self):
		return self._revision >= 0

	def _save(self, key, value):
		if not self._bindings[key][0].accepts(value):
			self._apply()
			self.failed.emit('Invalid value for setting: ' + key)
			return
		self._start((key, deepcopy(value)))

	def _start(self, change):
		if not self._alive.is_set():
			return
		if self.busy:
			self._apply()
			return
		self._set_busy(True)
		alive, settings_resource = self._alive, self._resource
		filename, subscriber = self.filename, self._publish
		def snapshot():
			value = deepcopy(load_json(filename, default={}))
			if not isinstance(value, dict):
				raise ValueError('Settings must be a JSON object: ' + filename)
			return value
		def operation():
			with settings_resource.lock:
				if not alive.is_set():
					return
				if change is None:
					return settings_resource.subscribe(subscriber, snapshot)
				values = snapshot()
				key, value = change
				values[key] = value
				save_json(filename, values)
				notification = settings_resource.committed(values)
			settings_resource.publish(notification)
			return notification[:2]
		def completed(result, error):
			if not alive.is_set():
				settings_resource.unsubscribe(subscriber)
				return
			try:
				self._delivered.emit(('completed', result, error))
			except RuntimeError:
				pass
		if not submit_work(operation, completed):
			self._set_busy(False)
			self._apply()
			self.failed.emit('Other operations are still finishing. Please try again.')

	def _publish(self, revision, values):
		if self._alive.is_set():
			try:
				self._delivered.emit(('snapshot', (revision, deepcopy(values)), None))
			except RuntimeError:
				pass

	def _receive(self, message):
		if not self._alive.is_set():
			return
		kind, result, error = message
		if result is not None:
			revision, values = result
			if revision >= self._revision:
				self._revision, self._values = revision, values
				self._apply()
				self.changed.emit(deepcopy(self._values))
		if kind == 'completed':
			self._set_busy(False)
			if error:
				self._apply()
				self.changed.emit(deepcopy(self._values))
				self.failed.emit(error)

	def _apply(self):
		for key, (control, default) in self._bindings.items():
			value = self._values.get(key, default)
			with QSignalBlocker(control):
				control.set_value(value if control.accepts(value) else default)

	def _set_busy(self, busy):
		self.busy = busy
		for control, default in self._bindings.values():
			control.setEnabled(not busy and self._revision >= 0)
		self.busy_changed.emit(busy)