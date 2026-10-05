from fman import show_alert, show_prompt, show_status_message
from fman.fs import exists, is_dir
from fman.ui import Action, ListItem, UiController, settings_resource as resource, show_panel, \
	show_quick_list
from fman.url import as_human_readable
from favorites.store import FavoritesStore, NO_USAGE
from datetime import datetime
from hashlib import sha1
from threading import Lock, Thread

import favorites


settings_resource = resource('Favorites.json')
_sessions = {}
_sessions_lock = Lock()
# show_quick_list bounds titles to 512 and hints to 2048 characters; stored favorites can be longer.
_MAX_TITLE, _MAX_HINT = 512, 2048


class FavoritesController(UiController):
	"""Carries the plug-in owner; Favorites builds no widgets of its own."""


def item_id(url):
	return sha1(FavoritesStore.key(url).encode('utf-8', 'surrogatepass')).hexdigest()


def _bounded(text, limit):
	return text if len(text) <= limit else text[:limit - 1] + '\u2026'


def _moment(value):
	if not value:
		return None
	moment = datetime.fromisoformat(value)
	return moment.timestamp(), moment.strftime('%Y-%m-%d %H:%M')


def project(records, usages=()):
	usages = usages or (NO_USAGE,) * len(records)
	items = []
	for index, (record, usage) in enumerate(zip(records, usages)):
		added, opened = _moment(usage.added), _moment(usage.opened)
		metadata = {
			# Store order is the add order, also for entries saved before dates were recorded.
			'Added': (len(records) - index, added[1] if added else ''),
			'Last opened': opened or (),
			'Opened': usage.count
		}
		items.append(ListItem(item_id(record.url), _bounded(record.name, _MAX_TITLE),
			_bounded(as_human_readable(record.url), _MAX_HINT), metadata=metadata))
	return tuple(items)


def record_open(url, owner):
	try:
		with favorites._LOCK:
			if not owner.active:
				return
			store = favorites._load_store()
			if not store.record_open(url):
				return
			notification = favorites._commit(store)
		favorites._resource.publish(notification)
	except Exception as error:
		show_status_message('Could not record the favorite use: %s' % error, timeout_secs=5)


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


def show_manager(pane, query=''):
	owner = FavoritesController.require_owner()
	with _sessions_lock:
		previous = _sessions.get(pane.window)
		if previous is not None and previous.is_open:
			if previous.pane is pane and not query:
				previous.handle.focus()
				return
			previous.handle.close()
		session = _sessions[pane.window] = FavoritesSession(pane, owner)
	session.run(query)


class FavoritesSession:
	def __init__(self, pane, owner):
		self.pane, self.owner = pane, owner
		self.handle = self.panel = None
		self.records = ()
		self.usages = ()
		self.revision = -1
		self.navigation = 0
		self.state_lock = Lock()
		self.action_lock = Lock()

	@property
	def is_open(self):
		return self.handle is not None and self.handle.is_open

	def run(self, query):
		with favorites._LOCK:
			store = favorites._load_store()
		favorites._report_invalid_entries(store.invalid_count)
		self.records, self.usages = store.favorites, store.usages
		try:
			result = show_quick_list(items=project(self.records, self.usages), title='Favorites Manager',
				modal=False, query=query, title_label='Name', hint_label='Path', settings='Favorites UI.json',
				on_open=self.attach)
		finally:
			self.dispose()
		if result:
			self.go_to(result, close=False)

	def attach(self, handle):
		self.handle = handle
		if not self.owner.attach(handle.close):
			handle.close()
			return
		self.panel = show_panel(owner=self.owner, pane=self.pane, rows=((
			Action('rename', 'Rename'), Action('delete', 'Delete'), Action('go_to', 'Go To')),),
			on_action=self.on_action, on_closed=handle.close)
		def snapshot():
			store = favorites._load_store()
			return (store.favorites, store.usages), store.invalid_count
		revision, (payload, invalid_count) = favorites._resource.subscribe(self.receive, snapshot)
		self.receive(revision, payload)

	def receive(self, revision, payload):
		records, usages = payload
		with self.state_lock:
			if revision <= self.revision or not self.is_open:
				return
			self.revision, self.records, self.usages = revision, records, usages
			self.handle.set_items(project(records, usages))

	def dispose(self):
		if self.handle is not None:
			self.owner.detach(self.handle.close)
		favorites._resource.unsubscribe(self.receive)
		if self.panel is not None:
			self.panel.close()
		with _sessions_lock:
			if _sessions.get(self.pane.window) is self:
				del _sessions[self.pane.window]

	def on_action(self, name, values):
		Thread(target=self.action, args=(name,), daemon=True).start()

	def action(self, name):
		if not self.action_lock.acquire(blocking=False):
			return
		try:
			if not self.is_open or not self.owner.active:
				return
			state = self.handle.snapshot()
			if name == 'delete':
				self.delete(state.chosen)
			elif name == 'rename':
				self.rename(state.current)
			elif name == 'go_to':
				self.go_to(state.chosen, close=True)
		except Exception as error:
			if self.is_open and self.owner.active:
				show_alert('Favorites could not %s: %s' % (name.replace('_', ' '), error))
		finally:
			self.action_lock.release()

	def find(self, ids):
		by_id = {item_id(record.url): record for record in self.records}
		return tuple(by_id[value] for value in ids if value in by_id)

	def delete(self, chosen):
		targets = self.find(chosen)
		if targets:
			self.report(mutate(targets, None, self.owner, lambda: self.is_open))

	def rename(self, current):
		targets = self.find((current,)) if current is not None else ()
		if not targets:
			return
		record = targets[0]
		name, accepted = show_prompt('Rename favorite:', record.name, 0, len(record.name))
		if accepted and name.strip():
			self.report(mutate(targets, name.strip(), self.owner, lambda: self.is_open))

	def report(self, conflicts):
		if conflicts:
			show_alert('%d favorites changed or no longer exist; they were not modified.' % len(conflicts))

	def go_to(self, chosen, close):
		"""close: close the list once the pane has loaded the location (Panel Go To)."""
		if len(chosen) != 1:
			show_status_message('Select one favorite for Go To.', timeout_secs=3)
			return
		targets = self.find(chosen)
		if not targets:
			return
		url = targets[0].url
		try:
			try:
				present = exists(url)
			except NotImplementedError:
				present = True
			if not present:
				raise FileNotFoundError('Favorite location not found: ' + as_human_readable(url))
			if not is_dir(url):
				raise NotADirectoryError('Favorites must point to folders: ' + as_human_readable(url))
		except OSError as error:
			show_alert(str(error))
			return
		with self.state_lock:
			self.navigation += 1
			navigation = self.navigation
		reported = []
		def current():
			return navigation == self.navigation and self.owner.active and (self.is_open or not close)
		def succeeded():
			if navigation == self.navigation and self.owner.active:
				Thread(target=record_open, args=(url, self.owner), daemon=True).start()
			if close and current():
				self.handle.close()
		def failed(error, failed_url):
			if not reported and current():
				reported.append(error)
				message = 'Could not open %s: %s' % (as_human_readable(url), error)
				Thread(target=show_alert, args=(message,), daemon=True).start()
			# Returning the same URL ends the navigation without a fallback.
			return failed_url
		try:
			self.pane.set_path(url, callback=succeeded, onerror=failed)
		except Exception as error:
			if not reported:
				failed(error, url)
