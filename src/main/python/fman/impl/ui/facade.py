from dataclasses import dataclass, field
from itertools import count, islice
import os
from pathlib import Path
from threading import Event
from types import MappingProxyType

from fman.impl.ui import UiOwner
from fman.impl.ui.panel import DropDown, OptionalField, Panel, TextButton, WrappingRow
from fman.impl.ui.session import MessageDialog, ToolWindow, navigate
from fman.impl.ui.table import Table
from fman.impl.ui.table_data import Action, Choice, DateField, IntegerField, Label, Select, Separator, TableAction, TableSchema, TextField, Toggle, panel_records, text, validate_field_value
from fman.impl.util.qt.thread import run_in_main_thread
from fman.url import as_human_readable, as_url
from PyQt5 import sip
from PyQt5.QtCore import QEvent, QSize, Qt, QSignalBlocker, QTimer, pyqtSignal
from PyQt5.QtGui import QColor, QIcon, QPainter, QPalette, QPixmap
from PyQt5.QtSvg import QSvgRenderer
from PyQt5.QtWidgets import QApplication, QButtonGroup, QFrame, QGridLayout, QHBoxLayout, QLabel, QLineEdit, QMenu, QSizePolicy, QSpacerItem, QToolButton, QVBoxLayout, QWidget


_keys = count(1)
_hosts = {}


@dataclass
class HandleState:
	key: int = field(default_factory=lambda: next(_keys))
	open: bool = True
	cell: object = None
	filter_text: str = ''
	values: object = field(default_factory=lambda: MappingProxyType({}))
	cancelled: Event = field(default_factory=Event)


class CancellationToken:
	__slots__ = ('__event',)

	def __init__(self, event):
		self.__event = event

	def is_set(self):
		return self.__event.is_set()


@run_in_main_thread
def _call(key, method, *args, **kwargs):
	host = _hosts.get(key)
	if host is None or not host.alive.is_set() or not host.owner.active:
		if method == 'close':
			return
		raise RuntimeError('The UI handle is closed.')
	return getattr(host, method)(*args, **kwargs)


class TableHandle:
	__slots__ = ('__state',)

	def __init__(self, state):
		self.__state = state

	@property
	def is_open(self):
		return self.__state.open and not self.__state.cancelled.is_set()

	@property
	def current_cell(self):
		return self.__state.cell if self.is_open else None

	@property
	def filter_text(self):
		return self.__state.filter_text

	@filter_text.setter
	def filter_text(self, value):
		_call(self.__state.key, 'set_filter', value)

	def refresh(self):
		_call(self.__state.key, 'refresh')

	def close(self):
		_call(self.__state.key, 'close')


class PanelHandle:
	__slots__ = ('__state',)

	def __init__(self, state):
		self.__state = state

	@property
	def is_open(self):
		return self.__state.open and not self.__state.cancelled.is_set()

	@property
	def cancelled(self):
		return CancellationToken(self.__state.cancelled)

	def snapshot(self):
		return self.__state.values

	def update(self, values=None, enabled=None):
		_call(self.__state.key, 'update_controls', values, enabled)

	def set_activity_status(self, text=None, *, get_text=None):
		_call(self.__state.key, 'set_activity', text, get_text)

	def close(self):
		_call(self.__state.key, 'close')

	def _key(self):
		return self.__state.key


class ElidedLabel(QLabel):
	def __init__(self, content='', parent=None):
		super().__init__(parent)
		self.setTextFormat(Qt.PlainText)
		self.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
		self.setMinimumWidth(0)
		self.content = ''
		self.set_content(content)

	def set_content(self, content):
		self.content = text(content, 'Label text')
		self.setToolTip(content)
		self.setText(self.fontMetrics().elidedText(content, Qt.ElideMiddle, max(1, self.width())))

	def resizeEvent(self, event):
		super().resizeEvent(event)
		self.set_content(self.content)


def _validate_callbacks(*callbacks):
	if any(callback is not None and not callable(callback) for callback in callbacks):
		raise TypeError('UI callbacks must be callable or None.')


def _require_owner(owner):
	if not isinstance(owner, UiOwner) or not owner.active:
		raise RuntimeError('UI services require an active registered plug-in owner.')


def _finished_callback(callback, owner):
	if callback is not None and owner.active:
		try:
			callback()
		except Exception:
			import logging
			logging.exception('UI close callback failed')


class ChoiceButtons(QWidget):
	changed = pyqtSignal()

	def __init__(self, record, session, parent):
		super().__init__(parent)
		self.options = record.options
		self.group = QButtonGroup(self)
		self.group.setExclusive(True)
		self.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Preferred)
		layout = QHBoxLayout(self)
		layout.setContentsMargins(0, 0, 0, 0)
		layout.setSpacing(3)
		for index, (value, icon, tooltip) in enumerate(self.options):
			button = QToolButton(self)
			button.setAutoRaise(True)
			button.setCheckable(True)
			button.setFixedSize(28, 28)
			button.setIcon(session.icon(icon))
			button.setIconSize(QSize(16, 16))
			button.setToolTip(tooltip)
			button.setAccessibleName(record.label + ': ' + tooltip)
			session.icon_controls.append((button, icon))
			self.group.addButton(button, index)
			layout.addWidget(button)
			button.setChecked(value == record.value)
		self.group.buttonToggled.connect(lambda button, checked: self.changed.emit() if checked else None)

	def value(self):
		return self.options[self.group.checkedId()][0]

	def set_value(self, value):
		index = next(index for index, option in enumerate(self.options) if option[0] == value)
		self.group.button(index).setChecked(True)


class PanelForm(QWidget):
	def __init__(self, session, rows):
		super().__init__()
		self.session = session
		self.rows = []
		self.narrow = None
		self.fields = []
		self.structured = any(isinstance(record, (Select, DateField, IntegerField, Separator)) for row in rows for record in row)
		self.aligned = any(isinstance(row[0], TextField) for row in rows) and all(
			(isinstance(row[0], Label) or isinstance(row[0], TextField) and row[0].max_width is not None)
			and not any(isinstance(record, (TextField, Label)) for record in row[1:]) for row in rows)
		grid = QGridLayout(self)
		grid.setContentsMargins(0, 0, 0, 0)
		grid.setSpacing(6)
		grid.setColumnStretch(0, 1)
		if self.aligned:
			grid.addItem(QSpacerItem(0, 0, QSizePolicy.Expanding, QSizePolicy.Minimum), 0, 2)
		for row in rows:
			body = QWidget(self)
			toolbar = self.structured and isinstance(row[0], Label) and row[0].icon and any(isinstance(record, Action) for record in row)
			body_layout = WrappingRow(body) if self.structured and not toolbar else QHBoxLayout(body)
			body_layout.setContentsMargins(0, 0, 0, 0)
			if toolbar:
				body_layout.setSpacing(3)
				body_layout.setAlignment(Qt.AlignBottom)
			actions = QWidget(self)
			action_layout = QHBoxLayout(actions)
			action_layout.setContentsMargins(0, 0, 0, 0)
			action_layout.setSpacing(3)
			has_actions = False
			previous = None
			bound_group = None
			divider = None
			for record in row:
				widget, control = self.create(record)
				session.controls[record.id] = (record, control)
				if isinstance(record, Separator):
					divider = widget
					continue
				if divider is not None:
					group = QWidget(body)
					layout = QHBoxLayout(group)
					layout.setContentsMargins(0, 0, 0, 0)
					layout.setSpacing(8)
					layout.addWidget(divider)
					layout.addWidget(widget)
					group.setSizePolicy(widget.sizePolicy())
					group.setMaximumWidth(min(16777215, widget.maximumWidth() + 17))
					widget, divider = group, None
				if self.structured:
					if isinstance(record, Select) and isinstance(previous, IntegerField):
						bound_group.layout().addWidget(widget)
					elif isinstance(record, IntegerField):
						bound_group = QWidget(body)
						bound_group.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
						bound_layout = QHBoxLayout(bound_group)
						bound_layout.setContentsMargins(0, 0, 0, 0)
						bound_layout.setSpacing(6)
						bound_layout.addWidget(widget)
						body_layout.addWidget(bound_group)
					else:
						body_layout.addWidget(widget)
				elif isinstance(record, Action) or self.aligned and not isinstance(record, (TextField, Label)):
					action_layout.addWidget(widget)
					has_actions = True
				else:
					body_layout.addWidget(widget, 1 if isinstance(record, (TextField, Label)) else 0)
				if toolbar and record is row[0]:
					body_layout.addStretch(1)
				previous = record
			if divider is not None:
				body_layout.addWidget(divider)
			if not self.structured and not self.aligned and any(isinstance(record, TextField) and record.max_width is not None for record in row):
				body_layout.addStretch()
			if has_actions:
				actions.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Preferred)
			else:
				actions.deleteLater()
			self.rows.append((body, actions if has_actions else None))
		self.tab_controls = []
		for record, control in session.controls.values():
			if isinstance(record, Choice):
				self.tab_controls.extend(control.group.buttons())
			elif isinstance(record, (DateField, IntegerField)):
				self.tab_controls.append(control.editor)
			elif not isinstance(record, (Label, Separator)):
				self.tab_controls.append(control)
		for previous, current in zip(self.tab_controls, self.tab_controls[1:]):
			QWidget.setTabOrder(previous, current)
		self.reflow(False)

	def create(self, record):
		session = self.session
		if isinstance(record, TextField):
			widget = QWidget(self)
			layout = QHBoxLayout(widget)
			layout.setContentsMargins(0, 0, 0, 0)
			label = QLabel(record.label, widget)
			label.setTextFormat(Qt.PlainText)
			label.setToolTip(record.tooltip or record.label)
			self.fields.append((record, widget, label))
			control = QLineEdit(record.value, widget)
			control.setMaxLength(4096)
			control.setMinimumWidth(min(80, record.max_width or 80))
			if self.structured and record.max_width is not None:
				control.setMaximumWidth(record.max_width)
				label.ensurePolished()
				layout.setSpacing(6)
				widget.setMaximumWidth(label.sizeHint().width() + 6 + record.max_width)
			if self.structured:
				widget.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
			label.setBuddy(control)
			layout.addWidget(label)
			layout.addWidget(control, 1)
			control.textChanged.connect(session.controls_changed)
		elif isinstance(record, Separator):
			widget = control = QWidget(self)
			widget.setFixedSize(9, 28)
			layout = QHBoxLayout(widget)
			layout.setContentsMargins(4, 4, 4, 4)
			line = QFrame(widget)
			line.setFrameShape(QFrame.VLine)
			line.setFrameShadow(QFrame.Plain)
			layout.addWidget(line)
		elif isinstance(record, Label):
			widget = control = ElidedLabel(record.text, self)
			if record.icon:
				widget = QWidget(self)
				layout = QHBoxLayout(widget)
				layout.setContentsMargins(0, 0, 0, 0)
				layout.setSpacing(6)
				icon = QLabel(widget)
				icon.setObjectName('panel-label-icon')
				icon.setFixedSize(24, 28)
				icon.setAlignment(Qt.AlignCenter)
				icon.setPixmap(session.icon(record.icon, size=20).pixmap(20, 20))
				icon.setToolTip(record.tooltip)
				icon.setAccessibleName(record.tooltip)
				session.icon_labels.append((icon, record.icon))
				layout.addWidget(icon)
				layout.addWidget(control, 1)
		elif isinstance(record, Choice):
			widget = control = ChoiceButtons(record, session, self)
			control.changed.connect(session.controls_changed)
		elif isinstance(record, (DateField, IntegerField)):
			widget = control = OptionalField(record, isinstance(record, DateField), self)
			control.value_changed.connect(session.controls_changed)
		elif isinstance(record, Select):
			widget = QWidget(self)
			widget.setToolTip(record.tooltip or record.label)
			layout = QHBoxLayout(widget)
			layout.setContentsMargins(0, 0, 0, 0)
			control = DropDown(tuple((label, value) for value, label in record.options), record.label, widget)
			control.set_value(record.value)
			if record.label:
				label = QLabel(record.label, widget)
				label.setToolTip(record.tooltip or record.label)
				label.setBuddy(control)
				layout.addWidget(label)
			layout.addWidget(control)
			control.value_changed.connect(session.controls_changed)
		else:
			if isinstance(record, Toggle) or record.icon is not None and not record.label:
				control = QToolButton(self)
				control.setAutoRaise(True)
				control.setFixedSize(28, 28)
			else:
				control = TextButton(record.label, self)
			widget = control
			if isinstance(record, Action):
				control.setProperty('panelAction', record.id)
			if record.icon:
				session.icon_controls.append((control, record.icon))
				control.setIcon(session.control_icon(control, record.icon))
				control.setIconSize(QSize(16, 16))
			if isinstance(record, Toggle):
				control.setCheckable(True)
				control.setChecked(record.value)
				control.toggled.connect(session.controls_changed)
			else:
				control.clicked.connect(lambda checked=False, name=record.id: session.action(name))
		if self.structured:
			if not isinstance(record, TextField):
				widget.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
			if isinstance(record, (DateField, IntegerField)):
				control.editor.setFixedSize(120 if isinstance(record, DateField) else 110, 28)
			elif isinstance(record, (TextField, Select, Label)):
				control.setFixedHeight(28)
			if isinstance(record, Label):
				control.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
				control.setMaximumWidth(240)
		if not isinstance(record, (Label, Separator)):
			control.setAccessibleName(record.label or record.tooltip)
			control.setToolTip(record.tooltip or record.label)
		return widget, control

	def resizeEvent(self, event):
		super().resizeEvent(event)
		self.reflow(self.width() < 620)

	def reflow(self, narrow):
		if self.structured:
			for record, control in self.session.controls.values():
				if isinstance(record, Label):
					control.ensurePolished()
					control.setMinimumWidth(min(240, control.fontMetrics().horizontalAdvance(control.content) + 2))
					control.set_content(control.content)
			for position, (body, actions) in enumerate(self.rows):
				self.layout().addWidget(body, position, 0)
			return
		for record, widget, label in self.fields:
			label.ensurePolished()
		label_width = max((label.sizeHint().width() for record, widget, label in self.fields), default=0)
		for record, widget, label in self.fields:
			label.setFixedWidth(label_width)
			if record.max_width is not None:
				widget.setMaximumWidth(label_width + widget.layout().spacing() + record.max_width)
		if self.aligned:
			grid = self.layout()
			maximum_width = max(widget.maximumWidth() for record, widget, label in self.fields)
			for position, (body, actions) in enumerate(self.rows):
				body.setMaximumWidth(maximum_width)
				grid.addWidget(body, position, 0)
				if actions is not None:
					grid.addWidget(actions, position, 1, Qt.AlignLeft)
			grid.invalidate()
			self.updateGeometry()
			return
		if narrow == self.narrow:
			return
		self.narrow = narrow
		grid = self.layout()
		while grid.count():
			grid.takeAt(0)
		position = 0
		for body, actions in self.rows:
			if actions is not None:
				body.layout().removeWidget(actions)
			grid.addWidget(body, position, 0)
			if actions is not None:
				if narrow:
					position += 1
					grid.addWidget(actions, position, 0, Qt.AlignRight)
				else:
					body.layout().addWidget(actions)
			position += 1
		grid.invalidate()
		self.updateGeometry()


class PanelSession(ToolWindow):
	def __init__(self, owner, pane, rows, on_change, on_action, on_closed):
		self.state = HandleState()
		super().__init__(pane.window._widget, owner)
		self.main, self.pane = pane.window._widget, pane
		self._main_closing = False
		self.on_change, self.on_action, self.on_closed = on_change, on_action, on_closed
		self.controls, self.icon_bytes, self.icon_controls = {}, {}, []
		self.icon_labels = []
		self.table_window = None
		self.status = None
		self.status_provider = None
		self.activity_timer = QTimer(self)
		self.activity_timer.setInterval(200)
		self.activity_timer.timeout.connect(self.tick_activity)
		self.panel = Panel()
		self.disposed.connect(self.cleanup)
		self.disposed.connect(pane.on_closed(self.close))
		_hosts[self.state.key] = self
		try:
			self.form = PanelForm(self, rows)
			self.panel.tab_controls = self.form.tab_controls
			self.panel.add(self.form, stretch=1)
			self.main.set_bottom_panel(self.panel, self.close, self.focus_from_panel)
			self.main.installEventFilter(self)
			self.capture_values()
			self.focus_panel()
		except Exception:
			self.on_closed = None
			self.close()
			raise

	def invalidate(self):
		self.state.cancelled.set()
		super().invalidate()

	def control_icon(self, control, name):
		color = QColor('#ff5252') if control.property('panelAction') == 'stop' else None
		return self.icon(name, color=color)

	def icon(self, name, size=16, color=None):
		if name not in self.icon_bytes:
			if not self.owner.resource_root:
				raise ValueError('This UI owner has no plug-in resource root.')
			root = Path(self.owner.resource_root).resolve(strict=True)
			candidate = Path(name)
			if candidate.is_absolute() or '..' in candidate.parts:
				raise ValueError('Icon names must be relative to the plug-in resource root.')
			path = (root / candidate).resolve(strict=True)
			if not path.is_relative_to(root) or path.suffix.lower() != '.svg' or path.stat().st_size > 131072:
				raise ValueError('Icon must be a bounded SVG inside the plug-in resource root.')
			self.icon_bytes[name] = path.read_bytes()
		renderer = QSvgRenderer(self.icon_bytes[name])
		if not renderer.isValid():
			raise ValueError('Invalid SVG icon: ' + name)
		scale = self.main.devicePixelRatioF()
		image = QPixmap(round(size * scale), round(size * scale))
		image.fill(Qt.transparent)
		painter = QPainter(image)
		renderer.render(painter)
		painter.setCompositionMode(QPainter.CompositionMode_SourceIn)
		painter.fillRect(image.rect(), color or self.main.palette().color(QPalette.WindowText))
		painter.end()
		image.setDevicePixelRatio(scale)
		return QIcon(image)

	def capture_values(self):
		values = {}
		for name, (record, control) in self.controls.items():
			if isinstance(record, TextField):
				values[name] = control.text()
			elif isinstance(record, (Choice, Select, DateField, IntegerField)):
				values[name] = control.value()
			elif isinstance(record, Toggle):
				values[name] = control.isChecked()
				control.setToolTip((record.tooltip or record.label) + (' (On)' if control.isChecked() else ' (Off)'))
			elif isinstance(record, Label):
				values[name] = control.content
		self.state.values = MappingProxyType(values)

	def controls_changed(self, *args):
		self.capture_values()
		if self.on_change is not None:
			self.invoke(self.on_change, self.state.values)

	def invoke(self, callback, *args):
		if self.alive.is_set() and self.owner.active:
			try:
				callback(*args)
			except Exception as error:
				self.alert(str(error))

	def action(self, name):
		if self.on_action is not None:
			self.invoke(self.on_action, name, self.state.values)

	def alert(self, message):
		self._open_prompt(MessageDialog('Panel', str(message), False, self.main), lambda result: None)

	def update_controls(self, values=None, enabled=None):
		values, enabled = dict(values or {}), dict(enabled or {})
		for name, value in values.items():
			if name not in self.controls or isinstance(self.controls[name][0], (Action, Separator)):
				raise ValueError('Unknown value control: ' + name)
			record = self.controls[name][0]
			if isinstance(record, Toggle):
				if type(value) is not bool:
					raise TypeError('Toggle values must be boolean.')
			elif isinstance(record, Choice):
				if value not in tuple(option[0] for option in record.options):
					raise ValueError('Unknown choice value: ' + str(value))
			elif isinstance(record, (Select, DateField, IntegerField)):
				validate_field_value(record, value)
			else:
				text(value, 'Control value', 4096 if isinstance(record, TextField) else None)
		for name, value in enabled.items():
			if name not in self.controls or type(value) is not bool:
				raise ValueError('Enabled states require known control IDs and boolean values.')
		for name, value in values.items():
			record, control = self.controls[name]
			with QSignalBlocker(control):
				if isinstance(record, Toggle):
					control.setChecked(value)
				elif isinstance(record, (Choice, Select, DateField, IntegerField)):
					control.set_value(value)
				elif isinstance(record, TextField):
					control.setText(value)
				else:
					control.set_content(value)
		for name, value in enabled.items():
			self.controls[name][1].setEnabled(value)
		self.capture_values()

	def set_activity(self, content=None, provider=None):
		_validate_callbacks(provider)
		if content is not None:
			text(content, 'Status')
		self.activity_timer.stop()
		self.status_provider = provider
		if content is None and provider is None:
			if self.status is not None:
				self.main.statusBar().removeWidget(self.status)
				self.status.deleteLater()
				self.status = None
			return
		if self.status is None:
			self.status = ElidedLabel(parent=self.main.statusBar())
			self.status.setObjectName('plugin-activity-status')
			self.main.statusBar().addWidget(self.status, 1)
		self.status.set_content(content or '')
		if provider is not None:
			self.tick_activity()
			if self.status_provider is not None:
				self.activity_timer.start()

	def tick_activity(self):
		if self.status_provider is not None and self.alive.is_set() and self.owner.active:
			try:
				self.status.set_content(self.status_provider())
			except Exception as error:
				self.activity_timer.stop()
				self.status_provider = None
				self.status.set_content(str(error))

	def focus_panel(self, backwards=False):
		controls = [widget for widget in self.main._panel_dock.findChildren(QWidget)
			if widget.isVisible() and widget.isEnabled() and widget.focusPolicy() & Qt.TabFocus]
		if controls:
			self.main.activateWindow()
			controls[-1 if backwards else 0].setFocus(Qt.BacktabFocusReason if backwards else Qt.TabFocusReason)

	def focus_from_panel(self, backwards=False):
		window = self.table_window
		if window and window.alive.is_set() and window.isVisible():
			window.raise_()
			window.activateWindow()
			(window.table.view if backwards else window.table.focusProxy()).setFocus()
		else:
			self.focus_panel(backwards)

	def eventFilter(self, watched, event):
		if watched is self.main:
			if event.type() == QEvent.Close:
				self._main_closing = True
				self.close()
			elif event.type() in (QEvent.PaletteChange, QEvent.StyleChange):
				for control, name in self.icon_controls:
					control.setIcon(self.control_icon(control, name))
				for label, name in self.icon_labels:
					label.setPixmap(self.icon(name, size=20).pixmap(20, 20))
		return False

	def cleanup(self):
		target = self.main._active_pane or self.pane._widget
		self.state.cancelled.set()
		self.state.open = False
		_hosts.pop(self.state.key, None)
		if self.table_window is not None:
			self.table_window.close()
		self.main.removeEventFilter(self)
		self.set_activity()
		self.main.remove_bottom_panel(self.panel)
		self.panel.deleteLater()
		self.icon_bytes.clear()
		self.icon_controls.clear()
		self.controls.clear()
		callback, self.on_closed = self.on_closed, None
		self.on_change = self.on_action = None
		_finished_callback(callback, self.owner)
		if self._main_closing or not self.owner.active or sip.isdeleted(self.main) or not self.main.isVisible():
			return
		if self.main._panel_dock is not None or QApplication.activeModalWidget() not in (None, self):
			return
		active = QApplication.activeWindow()
		if active not in (None, self.main, self, self.table_window):
			return
		if isinstance(target, QWidget) and not sip.isdeleted(target) and target.isVisible() and target.isEnabled():
			self.main.activateWindow()
			target.setFocus(Qt.OtherFocusReason)


class TableWindow(ToolWindow):
	def __init__(self, owner, main, pane, panel, schema, rows, provider, title,
			fuzzy, modal, close_on_navigate, summary, get_details, on_activate, get_menu, on_closed, get_count_text=None):
		self.state = HandleState()
		super().__init__(main, owner)
		self.setWindowFlags(Qt.Dialog)
		self.setWindowModality(Qt.WindowModal if modal else Qt.NonModal)
		self.setWindowTitle(title or 'Table')
		self.resize(820, 520)
		self.setMinimumSize(460, 280)
		self.main, self.pane, self.panel_session = main, pane, panel
		self.provider, self.schema = provider, schema
		self.close_on_navigate = modal if close_on_navigate is None else close_on_navigate
		self.navigated = False
		self.get_details, self.on_activate, self.get_menu = get_details, on_activate, get_menu
		self.on_closed = on_closed
		self.action_generation = 0
		self.menu = None
		self.pending = False
		self.retry_queued = False
		self.table = Table(schema, rows, self, fuzzy, get_count_text)
		self.table.view.setColumnWidth(0, 300)
		self.focus_widget = self.table
		layout = QVBoxLayout(self)
		layout.setContentsMargins(14, 12, 14, 12)
		self.summary = ElidedLabel(summary, self)
		self.summary.setVisible(bool(summary))
		self.details = ElidedLabel(parent=self)
		self.details.setVisible(get_details is not None)
		layout.addWidget(self.summary)
		layout.addWidget(self.table, 1)
		layout.addWidget(self.details)
		self.table.state_changed.connect(self.changed)
		self.table.view.cell_activated.connect(self.activate_cell)
		self.table.view.menu_requested.connect(self.open_menu)
		self.disposed.connect(self.cleanup)
		self.main.installEventFilter(self)
		if pane is not None:
			self.disposed.connect(pane.on_closed(self.close))
		if panel is not None:
			panel.table_window = self
		_hosts[self.state.key] = self
		self.changed()

	def invalidate(self):
		self.state.cancelled.set()
		super().invalidate()

	def changed(self):
		self.action_generation += 1
		self.close_menu()
		if not self.alive.is_set() or not self.owner.active:
			return
		self.state.cell = self.table.current_cell
		self.state.filter_text = self.table.query.text()
		if self.get_details is not None and self.state.cell is not None:
			try:
				self.details.set_content(self.get_details(*self.state.cell))
			except Exception as error:
				self.details.set_content(str(error))
		else:
			self.details.set_content('')

	def refresh(self):
		rows = self.schema.snapshot(self.provider)
		self.table.replace(rows)

	def set_filter(self, value):
		self.table.query.setText(text(value, 'Filter', 4096))

	def valid_action(self, row, column, generation):
		cell = self.table.current_cell
		return self.alive.is_set() and self.owner.active and generation == self.action_generation and cell is not None and cell[0] is row and cell[1] == column

	def activate_cell(self, row, column):
		if self.busy:
			return
		try:
			if column in self.schema.roles:
				path = self.schema.target(row, column)
				if path is not None and self.pane is not None:
					self.go_to(row, column, path, self.action_generation)
			elif self.on_activate is not None:
				self.on_activate(row, column)
		except Exception as error:
			self.alert(str(error))

	def go_to(self, row, column, path, generation):
		if self.busy or self.pane is None or not self.valid_action(row, column, generation):
			return
		role = self.schema.roles[column]
		def check(url):
			valid = os.path.exists(path) if role == 'entry' else os.path.isfile(path) if role == 'file' else os.path.isdir(path)
			if not valid:
				raise OSError('The target is missing, inaccessible or not a %s: %s' % (role, path))
		def complete(outcome, message):
			if not self.valid_action(row, column, generation):
				return
			if outcome == 'success':
				if self.close_on_navigate:
					self.navigated = True
					self.close()
			else:
				self.alert(message or 'Navigation did not complete.')
		navigate(self.pane, as_url(path), complete, window=self, check=check)

	def open_menu(self, row, column, position):
		self.close_menu()
		generation = self.action_generation
		try:
			path = self.schema.target(row, column)
			custom = tuple(islice(self.get_menu(row, column), 33)) if self.get_menu is not None else ()
			if len(custom) > 32:
				raise ValueError('At most 32 custom menu actions are supported.')
			ids = {'copy_path', 'go_to'}
			for item in custom:
				if not isinstance(item, TableAction) or not callable(item.callback):
					raise TypeError('Menus require TableAction records with callable callbacks.')
				if not text(item.id, 'Action ID', 128) or item.id in ids or not text(item.label, 'Action label', 128):
					raise ValueError('Menu action IDs and labels must be nonempty and unique.')
				ids.add(item.id)
			if path is None and not custom:
				return
			menu = QMenu(self)
			self.menu = menu
			def guarded(callback):
				def invoke(checked=False):
					if self.valid_action(row, column, generation):
						try:
							callback()
						except Exception as error:
							self.alert(str(error))
				return invoke
			if path is not None:
				menu.addAction('Copy Path', guarded(lambda: QApplication.clipboard().setText(path)))
				go = menu.addAction('Go To', guarded(lambda: self.go_to(row, column, path, generation)))
				go.setEnabled(self.pane is not None and not self.busy)
				if custom:
					menu.addSeparator()
			for item in custom:
				menu.addAction(item.label, guarded(lambda item=item: item.callback(row, column)))
			menu.aboutToHide.connect(menu.deleteLater)
			menu.destroyed.connect(lambda: self.menu_gone(menu))
			menu.popup(position)
		except Exception as error:
			self.alert(str(error))

	def menu_gone(self, menu):
		if self.menu is menu:
			self.menu = None

	def close_menu(self):
		if self.menu is not None:
			menu, self.menu = self.menu, None
			menu.close()
			menu.deleteLater()

	def present(self):
		self.pending = True
		app = QApplication.instance()
		app.installEventFilter(self)
		app.applicationStateChanged.connect(self.schedule_present)
		self.try_present()

	def schedule_present(self, *args):
		if self.pending and not self.retry_queued:
			self.retry_queued = True
			QTimer.singleShot(0, self.try_present)

	def try_present(self):
		self.retry_queued = False
		if not self.pending or not self.alive.is_set() or not self.owner.active:
			return
		app = QApplication.instance()
		if app.applicationState() != Qt.ApplicationActive or app.activeWindow() is not self.main or app.activeModalWidget() is not None:
			if self.panel_session is not None:
				self.panel_session.set_activity('Results ready')
			return
		self.stop_presenting()
		if self.panel_session is not None:
			self.panel_session.set_activity()
		if self.windowModality() == Qt.WindowModal:
			self.open()
		else:
			self.show()
		self.table.setFocus()

	def stop_presenting(self):
		if self.pending:
			self.pending = False
			app = QApplication.instance()
			app.removeEventFilter(self)
			app.applicationStateChanged.disconnect(self.schedule_present)

	def eventFilter(self, watched, event):
		if watched is self.main and event.type() == QEvent.Close:
			self.close()
		elif self.pending and event.type() in (QEvent.WindowActivate, QEvent.Hide, QEvent.Close, QEvent.DeferredDelete):
			self.schedule_present()
		return False

	def focusNextPrevChild(self, next):
		if self.windowModality() == Qt.NonModal and self.panel_session is not None:
			current = QApplication.focusWidget()
			if current is self.table.view and next or current is self.table.focusProxy() and not next:
				self.panel_session.focus_panel(not next)
				return True
		return super().focusNextPrevChild(next)

	def cleanup(self):
		self.state.cancelled.set()
		self.state.open = False
		self.state.cell = None
		_hosts.pop(self.state.key, None)
		self.stop_presenting()
		self.main.removeEventFilter(self)
		self.close_menu()
		self.table.dispose()
		self.schema.resolver = None
		panel = self.panel_session
		restore_panel = panel is not None and panel.table_window is self
		if restore_panel:
			panel.table_window = None
		callback, self.on_closed = self.on_closed, None
		self.provider = self.get_details = self.get_menu = self.on_activate = None
		_finished_callback(callback, self.owner)
		if not self.owner.active or sip.isdeleted(self.main) or not self.main.isVisible():
			return
		if panel is not None:
			if not restore_panel or not panel.alive.is_set() or sip.isdeleted(panel) or panel.table_window is not None:
				return
			dock = self.main._panel_dock
			if dock is None or sip.isdeleted(dock) or dock.panel is not panel.panel:
				return
		if QApplication.activeModalWidget() not in (None, self):
			return
		if self.navigated and self.pane is not None:
			target = self.pane._widget
			if isinstance(target, QWidget) and not sip.isdeleted(target) and target.isVisible() and target.isEnabled():
				self.main.activateWindow()
				target.setFocus(Qt.OtherFocusReason)
		elif restore_panel:
			panel.focus_panel()


@run_in_main_thread
def show_panel(*, owner, pane, rows, on_change=None, on_action=None, on_closed=None):
	_require_owner(owner)
	_validate_callbacks(on_change, on_action, on_closed)
	if pane is None:
		raise ValueError('A docked Panel requires its public directory pane.')
	session = PanelSession(owner, pane, panel_records(rows), on_change, on_action, on_closed)
	return PanelHandle(session.state)


@run_in_main_thread
def show_table(*, owner, get_rows, num_columns, columns_header, pane=None,
		panel=None, title='', fuzzy=True, file_path_column=None, folder_path_column=None,
		resolve_path=None, base_path=None, modal=True, close_on_navigate=None,
		summary='', get_details=None, on_activate=None, get_menu=None, on_closed=None,
		entry_path_column=None, get_count_text=None):
	_require_owner(owner)
	_validate_callbacks(get_details, on_activate, get_menu, on_closed, get_count_text)
	for value in (fuzzy, modal):
		if type(value) is not bool:
			raise TypeError('fuzzy and modal must be boolean.')
	if close_on_navigate is not None and type(close_on_navigate) is not bool:
		raise TypeError('close_on_navigate must be bool or None.')
	text(title, 'Title')
	text(summary, 'Summary')
	panel_session = None
	if panel is not None:
		if not isinstance(panel, PanelHandle) or not panel.is_open:
			raise ValueError('panel must be an open PanelHandle.')
		panel_session = _hosts.get(panel._key())
		if panel_session is None or panel_session.owner is not owner or pane is not None and pane is not panel_session.pane:
			raise ValueError('Panel, pane and Table must have the same owner and target pane.')
		if panel_session.table_window is not None:
			raise RuntimeError('This Panel already owns a Table.')
		pane = panel_session.pane
	if base_path is None and pane is not None and any(column is not None for column in (file_path_column, folder_path_column, entry_path_column)):
		location = pane.get_path()
		if isinstance(location, str) and location.startswith('file://'):
			base_path = as_human_readable(location)
	schema = TableSchema(num_columns, columns_header, file_path_column, folder_path_column, resolve_path, base_path, entry_path_column)
	rows = schema.snapshot(get_rows)
	if pane is None:
		from fman import _get_ui
		main = _get_ui()
	else:
		main = pane.window._widget
	window = TableWindow(owner, main, pane, panel_session, schema, rows, get_rows,
		title, fuzzy, modal, close_on_navigate, summary, get_details, on_activate, get_menu, on_closed, get_count_text)
	window.present()
	return TableHandle(window.state)