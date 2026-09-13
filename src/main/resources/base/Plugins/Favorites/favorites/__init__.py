from fman.ui import matchers
from fman import DirectoryPaneCommand, NO, QuicksearchItem, YES, load_json, \
	save_json, show_alert, show_prompt, show_quicksearch, show_status_message
from fman.fs import exists
from fman.url import as_human_readable, normalize
from itertools import chain

from favorites.store import FavoritesStore
from favorites.ui import FavoritesController, settings_resource


_SETTINGS_NAME = 'Favorites.json'
_MATCHERS = (
	matchers.path_starts_with, matchers.basename_starts_with,
	matchers.contains_substring, matchers.contains_chars
)
_resource = settings_resource
_LOCK = _resource.lock
_invalid_entries_reported = False


class AddCurrentFolderToFavorites(DirectoryPaneCommand):
	aliases = ('Add current folder to favorites',)

	def __call__(self):
		url = self.pane.get_path()
		if url == 'null://':
			show_status_message(
				'The empty pane cannot be added to favorites.', timeout_secs=3
			)
			return
		confirmed_eviction = False
		while True:
			with _LOCK:
				if not FavoritesController.owner.active:
					return
				store = _load_store()
				if not store.would_evict(url) or confirmed_eviction:
					result = store.add(url)
					notification = _commit(store)
					invalid_count = store.invalid_count
					break
			choice = show_alert(
				'Favorites is full. Replace the oldest favorite?',
				YES | NO, NO
			)
			if not choice & YES:
				return
			confirmed_eviction = True
		_resource.publish(notification)
		_report_invalid_entries(invalid_count)
		show_status_message(
			'Added %s to favorites.' % result.favorite.name, timeout_secs=3
		)

	def is_visible(self):
		return self.pane.get_path() != 'null://'


class ShowFavorites(DirectoryPaneCommand):
	aliases = ('Favorites Manager', 'Favorites', 'Show favorites')

	def __call__(self, query=''):
		FavoritesController.show(self.pane, query)


class RemoveFromFavorites(DirectoryPaneCommand):
	aliases = ('Remove from favorites',)

	def is_visible(self):
		return False

	def __call__(self):
		favorites, invalid_count = _snapshot()
		_report_invalid_entries(invalid_count)
		if not favorites:
			show_status_message('No favorites saved.', timeout_secs=3)
			return
		current_url = normalize(self.pane.get_path())
		favorite = _find_favorite(favorites, current_url)
		if favorite is None:
			favorite = _choose_favorite(favorites)
		if favorite is None:
			return
		choice = show_alert(
			'Remove %s from favorites?' % favorite.name, YES | NO, NO
		)
		if not choice & YES:
			return
		with _LOCK:
			if not FavoritesController.owner.active:
				return
			store = _load_store()
			removed = store.remove(favorite.url) if store.find(favorite.url) == favorite else None
			if removed is not None:
				notification = _commit(store)
		if removed is None:
			show_status_message('Favorite no longer exists.', timeout_secs=3)
		else:
			_resource.publish(notification)
			show_status_message(
				'Removed %s from favorites.' % removed.name, timeout_secs=3
			)


class RenameFavorite(DirectoryPaneCommand):
	aliases = ('Rename favorite',)

	def is_visible(self):
		return False

	def __call__(self):
		favorites, invalid_count = _snapshot()
		_report_invalid_entries(invalid_count)
		if not favorites:
			show_status_message('No favorites saved.', timeout_secs=3)
			return
		favorite = _choose_favorite(favorites)
		if favorite is None:
			return
		name, accepted = show_prompt(
			'Rename favorite:', favorite.name, 0, len(favorite.name)
		)
		name = name.strip()
		if not accepted or not name:
			return
		with _LOCK:
			if not FavoritesController.owner.active:
				return
			store = _load_store()
			renamed = store.find(favorite.url) == favorite and store.rename(favorite.url, name)
			if renamed:
				notification = _commit(store)
		if not renamed:
			show_status_message('Favorite no longer exists.', timeout_secs=3)
		else:
			_resource.publish(notification)


def get_favorite_items(favorites, query):
	if not query:
		return [_to_quicksearch_item(favorite) for favorite in favorites]
	name_matches = [[] for _ in _MATCHERS]
	path_matches = [[] for _ in _MATCHERS]
	for favorite in favorites:
		hint = as_human_readable(favorite.url)
		for index, matcher in enumerate(_MATCHERS):
			highlight = _match_case_insensitive(
				matcher, favorite.name, query
			)
			if highlight is not None:
				name_matches[index].append(
					_to_quicksearch_item(favorite, highlight)
				)
				break
		else:
			for index, matcher in enumerate(_MATCHERS):
				if _match_case_insensitive(matcher, hint, query) is not None:
					path_matches[index].append(_to_quicksearch_item(favorite))
					break
	return list(chain.from_iterable(name_matches + path_matches))


def _match_case_insensitive(matcher, text, query):
	return matcher(text.casefold(), query.casefold())


def _to_quicksearch_item(favorite, highlight=None):
	return QuicksearchItem(
		favorite.url, favorite.name, highlight, as_human_readable(favorite.url)
	)


def _get_tab_completion(query, item):
	if item is not None:
		return item.hint


def _choose_favorite(favorites):
	result = show_quicksearch(
		lambda query: get_favorite_items(favorites, query),
		_get_tab_completion
	)
	if result and result[1]:
		return _find_favorite(favorites, result[1])


def _find_favorite(favorites, url):
	key = FavoritesStore.key(url)
	for favorite in favorites:
		if FavoritesStore.key(favorite.url) == key:
			return favorite


def _snapshot():
	with _LOCK:
		store = _load_store()
		return store.favorites, store.invalid_count


def _load_store():
	return FavoritesStore.load(load_json(_SETTINGS_NAME, default={}))


def _commit(store):
	save_json(_SETTINGS_NAME, store.to_json())
	return _resource.committed(store.favorites)


def _report_invalid_entries(count):
	global _invalid_entries_reported
	if not count:
		return
	with _LOCK:
		if _invalid_entries_reported:
			return
		_invalid_entries_reported = True
	show_status_message(
		'Ignored %d invalid or excess favorite entr%s.' %
		(count, 'y' if count == 1 else 'ies'),
		timeout_secs=4
	)