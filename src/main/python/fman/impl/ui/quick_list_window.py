from copy import deepcopy
from threading import Event, Lock, Thread
from weakref import WeakKeyDictionary

from fman.impl.ui import UiOwner, resource
from fman.impl.ui.facade import ElidedLabel
from fman.impl.ui.quick_list_data import QuickListState, prepare_items, requested_sort, \
	result_ids, selected_ids, settings_name, sort_label
from fman.impl.ui.quicklist import QuickList
from fman.impl.ui.session import ToolWindow
from fman.impl.ui.table_data import text
from fman.impl.util.qt.thread import is_in_main_thread, run_in_main_thread
from PyQt5 import sip
from PyQt5.QtCore import QEvent, QEventLoop, Qt
from PyQt5.QtWidgets import QApplication, QVBoxLayout, QWidget


# Lists are plain data, independent of plug-in lifetimes; drivers attach handle.close to their owner.
_list_owner = UiOwner()
# Main window -> open modeless lists, most recently active last (global Tab).
_open_lists = WeakKeyDictionary()


def _main_window():
	from fman import _get_ui
	return _get_ui()


class _Session:
	def __init__(self, title_label, hint_label):
		self.title_label, self.hint_label = title_label, hint_label
		self.lock = Lock()
		self.state = QuickListState()
		self.ids = frozenset()
		self.done = Event()
		self.result = None
		self.window = None
		self.loop = None


@run_in_main_thread
def _on_window(session, method, *args):
	window = session.window
	if window is not None and not session.done.is_set() and not sip.isdeleted(window):
		getattr(window, method)(*args)


class QuickListHandle:
	__slots__ = ('__session',)

	def __init__(self, session):
		self.__session = session

	@property
	def is_open(self):
		return not self.__session.done.is_set()

	def snapshot(self):
		with self.__session.lock:
			return self.__session.state

	def set_items(self, items):
		session = self.__session
		prepared = prepare_items(items, session.title_label, session.hint_label)
		if not session.done.is_set():
			_on_window(session, 'apply_items', prepared)

	def focus(self):
		_on_window(self.__session, 'present')

	def close(self, result=None):
		session = self.__session
		with session.lock:
			known = session.ids
		_on_window(session, 'finish', result_ids(result, known))


class QuickListWindow(ToolWindow):
	def __init__(self, main, session, prepared, title, summary, modal, fuzzy, query, selected, sort, settings):
		super().__init__(main, _list_owner)
		self.setWindowFlags(Qt.Dialog)
		self.setWindowModality(Qt.WindowModal if modal else Qt.NonModal)
		self.setWindowTitle(title or 'QuickList')
		self.resize(680, 430)
		self.setMinimumSize(420, 260)
		self.main, self.session, self.modal, self.settings = main, session, modal, settings
		self.result = None
		self.saving = Lock()
		self.pending_sort = None
		try:
			css = main._theme.get_quicksearch_item_css()
		except AttributeError:
			css = None
		self.list = QuickList(self, fuzzy=fuzzy, css=css if isinstance(css, dict) else None)
		self.list.view.setAccessibleName(title or 'Items')
		self.list.requested_sort = sort
		self.list.selected_ids = set(selected)
		self.list.set_sortable_items(prepared.items, prepared.labels, prepared.keys)
		if query:
			self.list.query.setText(query)
		self.focus_widget = self.list
		layout = QVBoxLayout(self)
		layout.setContentsMargins(4, 6, 4, 4)
		self.summary = ElidedLabel(summary, self)
		self.summary.setContentsMargins(10, 0, 10, 0)
		self.summary.setVisible(bool(summary))
		layout.addWidget(self.summary)
		layout.addWidget(self.list, 1)
		self.list.activated.connect(self.accept_chosen)
		self.list.state_changed.connect(self.publish)
		self.list.sort_changed.connect(self.sort_changed)
		self.disposed.connect(self.cleanup)
		self.main.installEventFilter(self)
		if not modal:
			_open_lists.setdefault(main, []).append(self)
		self.publish()

	def publish(self, *_):
		items = self.list.items
		chosen_ids = self.list.selected_ids
		selected = tuple(item.id for item in items if item.id in chosen_ids)
		current = self.list.current_id
		state = QuickListState(selected, selected or ((current,) if current is not None else ()),
			current, self.list.query.text(), self.list.effective_sort)
		with self.session.lock:
			self.session.state = state
			self.session.ids = frozenset(item.id for item in items)

	def apply_items(self, prepared):
		self.list.set_sortable_items(prepared.items, prepared.labels, prepared.keys)
		self.publish()

	def present(self):
		if not self.isVisible():
			self.show()
		self.raise_()
		self.activateWindow()
		self.list.setFocus(Qt.OtherFocusReason)

	def accept_chosen(self):
		chosen = self.session.state.chosen
		if chosen:
			self.finish(chosen)

	def finish(self, result):
		self.result = result
		self.close()

	def sort_changed(self):
		self.publish()
		if self.settings is not None and self.list.effective_sort is not None:
			with self.saving:
				start = self.pending_sort is None
				self.pending_sort = self.list.effective_sort
			if start:
				Thread(target=self._save_sort, daemon=True).start()

	def _save_sort(self):
		from fman import load_json, save_json, show_status_message
		settings = resource(self.settings)
		while True:
			with self.saving:
				sort = self.pending_sort
				if sort is None:
					return
			try:
				with settings.lock:
					values = deepcopy(load_json(self.settings, default={}))
					if not isinstance(values, dict):
						raise ValueError('Settings must be a JSON object: ' + self.settings)
					values['sort'], values['ascending'] = sort
					save_json(self.settings, values)
					notification = settings.committed(values)
				settings.publish(notification)
			except Exception as error:
				try:
					show_status_message('Could not save the sort: %s' % error, timeout_secs=5)
				except Exception:
					pass
			with self.saving:
				if self.pending_sort == sort:
					self.pending_sort = None
					return

	def focusNextPrevChild(self, next):
		dock = getattr(self.main, '_panel_dock', None)
		if not self.modal and dock is not None and not sip.isdeleted(dock):
			current = QApplication.focusWidget()
			if current is not None and self.isAncestorOf(current):
				candidate = current.nextInFocusChain() if next else current.previousInFocusChain()
				while candidate is not self and candidate is not current:
					if candidate.isVisible() and candidate.isEnabled() and candidate.focusPolicy() & Qt.TabFocus:
						return super().focusNextPrevChild(next)
					candidate = candidate.nextInFocusChain() if next else candidate.previousInFocusChain()
				controls = getattr(dock.panel, 'tab_controls', None) or [widget for widget in dock.findChildren(QWidget)
					if widget.focusPolicy() & Qt.TabFocus]
				controls = [control for control in controls if control.isVisible() and control.isEnabled()]
				if controls:
					self.main.activateWindow()
					controls[0 if next else -1].setFocus(Qt.TabFocusReason if next else Qt.BacktabFocusReason)
					return True
		return super().focusNextPrevChild(next)

	def focus_from_panel(self, backwards):
		self.raise_()
		self.activateWindow()
		if backwards or self.list.query.isHidden():
			self.list.view.setFocus(Qt.BacktabFocusReason if backwards else Qt.TabFocusReason)
		else:
			self.list.query.setFocus(Qt.TabFocusReason)

	def event(self, event):
		if event.type() == QEvent.WindowActivate and not self.modal:
			windows = _open_lists.setdefault(self.main, [])
			if self in windows:
				windows.remove(self)
			windows.append(self)
		return super().event(event)

	def eventFilter(self, watched, event):
		if watched is self.main and event.type() == QEvent.Close:
			self.close()
		return False

	def cleanup(self):
		windows = _open_lists.get(self.main)
		if windows is not None and self in windows:
			windows.remove(self)
		self.main.removeEventFilter(self)
		self.publish()
		session = self.session
		session.result = self.result
		session.done.set()
		if session.loop is not None:
			session.loop.quit()


def recent_list(main):
	"""The most recently active open modeless list of a main window, for Tab from its Panel."""
	for window in reversed(_open_lists.get(main, ())):
		if not sip.isdeleted(window) and window.isVisible() and not window.session.done.is_set():
			return window
	return None


def _load_sort(settings):
	from fman import load_json
	try:
		values = load_json(settings, default={})
	except Exception:
		return None
	if not isinstance(values, dict) or not isinstance(values.get('sort'), str):
		return None
	ascending = values.get('ascending', True)
	try:
		return sort_label(values['sort'], 'Saved sort'), ascending if type(ascending) is bool else True
	except (TypeError, ValueError):
		return None


@run_in_main_thread
def _build(session, prepared, arguments):
	window = QuickListWindow(_main_window(), session, prepared, **arguments)
	session.window = window
	return window


def show_quick_list(*, items, title='', summary='', modal=True, filter='fuzzy', query='',
		selected=(), title_label=None, hint_label=None, sort=None, settings=None, on_open=None):
	text(title, 'Title', 512)
	text(summary, 'Summary', 2048)
	text(query, 'Query', 4096)
	if type(modal) is not bool:
		raise TypeError('modal must be boolean.')
	if filter not in ('fuzzy', None):
		raise ValueError("filter must be 'fuzzy' or None.")
	if on_open is not None and not callable(on_open):
		raise TypeError('on_open must be callable or None.')
	title_label = sort_label(title_label, 'title_label')
	hint_label = sort_label(hint_label, 'hint_label')
	sort = requested_sort(sort)
	settings = settings_name(settings)
	prepared = prepare_items(items, title_label, hint_label)
	selected = selected_ids(selected, prepared)
	if settings is not None:
		sort = _load_sort(settings) or sort
	session = _Session(title_label, hint_label)
	_build(session, prepared, dict(title=title, summary=summary, modal=modal, fuzzy=filter == 'fuzzy',
		query=query, selected=selected, sort=sort, settings=settings))
	handle = QuickListHandle(session)
	if on_open is not None:
		try:
			on_open(handle)
		except BaseException:
			handle.close()
			raise
	if not session.done.is_set():
		_on_window(session, 'present')
	if is_in_main_thread():
		if not session.done.is_set():
			session.loop = QEventLoop()
			session.loop.exec_()
	else:
		session.done.wait()
	return session.result
