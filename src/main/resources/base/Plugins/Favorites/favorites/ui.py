from fman.fs import exists, is_dir
from fman.ui import ListItem, UiController, QuickList, Panel, TextButton, \
	DropDown, JsonSettings, navigate, settings_resource as resource
from fman.url import as_human_readable
from favorites.store import FavoritesStore
from PyQt5.QtCore import Qt
from PyQt5.QtGui import QKeySequence
from PyQt5.QtWidgets import QLabel, QShortcut, QVBoxLayout
from threading import Lock

import favorites


settings_resource = resource('Favorites.json')


def project(records, order):
	items = tuple(ListItem(FavoritesStore.key(record.url), record.name, as_human_readable(record.url)) for record in records)
	if order == 'Name':
		return tuple(sorted(items, key=lambda item: (item.title.casefold(), item.hint.casefold(), item.id)))
	if order == 'Path':
		return tuple(sorted(items, key=lambda item: (item.hint.casefold(), item.title.casefold(), item.id)))
	return items


def mutate(records, name, owner, allowed=lambda: True):
	with favorites._LOCK:
		if not owner.active or not allowed():
			return ()
		store = favorites._load_store()
		conflicts = []
		changed = False
		for captured in records:
			current = store.find(captured.url)
			if current != captured:
				conflicts.append(captured.name)
			elif name is None:
				store.remove(captured.url)
				changed = True
			elif current.name != name:
				store.rename(captured.url, name)
				changed = True
		if changed:
			notification = favorites._commit(store)
		else:
			notification = None
	if notification:
		favorites._resource.publish(notification)
	return tuple(conflicts)


class FavoritesController(UiController):
	@classmethod
	def build(cls, window, pane):
		window.setWindowTitle('Favorites Manager')
		window.list = QuickList(window, fuzzy=True, css=window.item_css, preserve_sort=True)
		window.focus_widget = window.list
		window.list.view.setAccessibleName('Favorites')
		window.panel = Panel(window)
		label = window.panel.add(QLabel('Sort By'))
		window.panel.choice = window.panel.add(DropDown(tuple((name, name) for name in ('Recent', 'Name', 'Path')), 'Sort By'))
		label.setBuddy(window.panel.choice)
		window.panel.add_stretch()
		window.panel.buttons = {}
		for action_id, title in (('delete', 'Delete'), ('rename', 'Rename'), ('goto', 'Go To')):
			button = window.panel.add(TextButton(title))
			button.clicked.connect(lambda checked=False, action=action_id: window.session.action(action))
			window.panel.buttons[action_id] = button
		window.settings = JsonSettings('Favorites UI.json', window.panel, window.owner)
		window.settings.bind('sort', window.panel.choice, 'Recent')
		window.settings.failed.connect(window.alert)
		window.panel.buttons['delete'].setToolTip('Delete selected favorites, or the highlighted favorite when none are selected')
		window.panel.buttons['delete'].setAccessibleDescription(window.panel.buttons['delete'].toolTip())
		layout = QVBoxLayout(window)
		layout.setContentsMargins(1, 1, 1, 1)
		layout.setSpacing(0)
		layout.addWidget(window.list, 1)
		window.set_panel(window.panel)
		window.session = FavoritesSession(window, pane)
		session = window.session
		window.settings.changed.connect(session._project)
		window.panel.choice.value_changed.connect(session._project)
		window.list.activated.connect(lambda: session.action('goto'))
		window.list.delete_requested.connect(lambda: session.action('delete'))
		window.list.state_changed.connect(session._update_actions)
		window.shortcut = QShortcut(QKeySequence('Ctrl+B'), window)
		window.shortcut.setContext(Qt.WidgetWithChildrenShortcut)
		window.shortcut.activated.connect(window.list.query.setFocus)
		window.destroyed.connect(lambda: favorites._resource.unsubscribe(session._subscriber))
		window.disposed.connect(session.dispose)
		window.shown.connect(session.on_shown)
		window.busy_changed.connect(session._update_actions)
		window.work(session._subscribe, session._apply_snapshot)
		window.settings.load()


class FavoritesSession:
	def __init__(self, window, pane):
		self.window = window
		self.pane = pane
		self.list = window.list
		self.panel = window.panel
		self.settings = window.settings
		self.records = ()
		self.revision = -1
		self.navigation = None
		self._snapshot_lock = Lock()
		self._pending_snapshot = None
		self._subscriber = self._receive

	def on_shown(self, query):
		if self.revision < 0 and not self.window.busy and self.window.prompt is None:
			self.window.work(self._subscribe, self._apply_snapshot)
		if not self.settings.loaded and not self.settings.busy and self.window.prompt is None:
			self.settings.load()

	def _subscribe(self):
		try:
			def snapshot():
				store = favorites._load_store()
				return store.favorites, store.invalid_count
			revision, (records, invalid_count) = favorites._resource.subscribe(self._subscriber, snapshot)
			favorites._report_invalid_entries(invalid_count)
			return revision, records
		finally:
			if not self.window.alive.is_set():
				favorites._resource.unsubscribe(self._subscriber)

	def _receive(self, revision, records):
		if not self.window.alive.is_set():
			return
		with self._snapshot_lock:
			pending = self._pending_snapshot
			if pending is None or revision > pending[0]:
				self._pending_snapshot = (revision, records)
		if pending is None:
			self.window.post(self._flush_snapshot)

	def _flush_snapshot(self):
		with self._snapshot_lock:
			snapshot = self._pending_snapshot
			self._pending_snapshot = None
		if snapshot:
			self._apply_snapshot(snapshot)

	def _apply_snapshot(self, snapshot):
		revision, records = snapshot
		if revision > self.revision:
			self.revision = revision
			self.records = records
			self._project()

	def _project(self, *_):
		self.list.set_items(project(self.records, self.panel.choice.currentText()))

	def _update_actions(self, *_):
		current = self.list.current_id is not None
		for action in ('rename', 'goto'):
			self.panel.buttons[action].setEnabled(not self.window.busy and current)
		self.panel.buttons['delete'].setEnabled(not self.window.busy and (current or bool(self.list.selected_ids)))

	def action(self, action):
		if action == 'close':
			self.window.close()
			return
		if self.window.busy or not self.window.alive.is_set():
			return
		by_id = {FavoritesStore.key(record.url): record for record in self.records}
		current = by_id.get(self.list.current_id)
		if action == 'delete':
			selected = self.list.selected_ids
			targets = tuple(record for key, record in by_id.items() if key in selected) if selected else ((current,) if current else ())
			if not targets:
				return
			self._mutate(targets, None)
		elif action == 'rename' and current:
			self.window.rename_prompt('Rename favorite:', current.name, lambda name: self._rename(current, name))
		elif action == 'goto' and current:
			self._go_to(current)

	def _rename(self, record, name):
		if name.strip():
			self._mutate((record,), name.strip())

	def _mutate(self, records, name):
		def operation():
			if not self.window.alive.is_set():
				return ()
			return mutate(records, name, self.window.owner, self.window.alive.is_set)
		def completed(conflicts):
			if conflicts:
				self.window.alert('%d favorites changed or no longer exist; they were not modified.' % len(conflicts))
		self.window.work(operation, completed)

	def _go_to(self, record):
		def check(url):
			try:
				present = exists(url)
			except NotImplementedError:
				present = True
			if not present:
				raise FileNotFoundError('Favorite location not found: ' + as_human_readable(url))
			if not is_dir(url):
				raise NotADirectoryError('Favorites must point to folders: ' + as_human_readable(url))
		self.navigation = navigate(self.pane, record.url, self._navigated, window=self.window, check=check)

	def _navigated(self, outcome, message):
		self.window.set_busy(False)
		if outcome == 'success':
			self.window.close()
		elif outcome == 'failure':
			self.window.alert(message)

	def dispose(self):
		self.settings.dispose()
		if self.navigation:
			self.navigation.cancel()
		favorites._resource.unsubscribe(self._subscriber)