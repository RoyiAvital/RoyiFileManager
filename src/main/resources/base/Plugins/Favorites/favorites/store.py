from collections import namedtuple
from os import name as os_name

from fman.url import as_human_readable, basename, normalize, splitscheme


DEFAULT_MAX_FAVORITES = 200
Favorite = namedtuple('Favorite', 'name url')
AddResult = namedtuple('AddResult', 'favorite evicted')


class FavoritesStore:
	def __init__(
		self, favorites=(), max_favorites=DEFAULT_MAX_FAVORITES,
		invalid_count=0, windows=None
	):
		self._windows = os_name == 'nt' if windows is None else windows
		self._favorites = list(favorites)
		self._keys = [self.key(favorite.url, self._windows)
					  for favorite in self._favorites]
		self.max_favorites = max_favorites
		self.invalid_count = invalid_count

	@classmethod
	def load(cls, value, windows=None):
		invalid_count = 0
		if not isinstance(value, dict):
			value = {}
			invalid_count += 1
		max_favorites = value.get('max_favorites', DEFAULT_MAX_FAVORITES)
		if isinstance(max_favorites, bool) or \
				not isinstance(max_favorites, int) or max_favorites < 1:
			max_favorites = DEFAULT_MAX_FAVORITES
			invalid_count += 1
		entries = value.get('favorites', [])
		if not isinstance(entries, list):
			entries = []
			invalid_count += 1
		store = cls((), max_favorites, invalid_count, windows)
		seen = set()
		for entry in entries:
			favorite = store._parse_entry(entry)
			if favorite is None:
				store.invalid_count += 1
				continue
			key = store.key(favorite.url, store._windows)
			if key in seen:
				store.invalid_count += 1
				continue
			seen.add(key)
			if len(store._favorites) == max_favorites:
				store.invalid_count += 1
				continue
			store._favorites.append(favorite)
			store._keys.append(key)
		return store

	@property
	def favorites(self):
		return tuple(self._favorites)

	def contains(self, url):
		return self.find(url) is not None

	def find(self, url):
		key = self.key(url, self._windows)
		try:
			return self._favorites[self._keys.index(key)]
		except ValueError:
			pass

	def would_evict(self, url):
		return not self.contains(url) and \
			len(self._favorites) >= self.max_favorites

	def add(self, url, name=None):
		url = self._normalize_url(url)
		key = self.key(url, self._windows)
		try:
			index = self._keys.index(key)
		except ValueError:
			pass
		else:
			favorite = self._favorites.pop(index)
			self._favorites.insert(0, favorite)
			self._keys.insert(0, self._keys.pop(index))
			return AddResult(favorite, None)
		if name is None:
			name = self._default_name(url)
		name = self._normalize_name(name)
		favorite = Favorite(name, url)
		self._favorites.insert(0, favorite)
		self._keys.insert(0, key)
		evicted = None
		if len(self._favorites) > self.max_favorites:
			evicted = self._favorites.pop()
			self._keys.pop()
		return AddResult(favorite, evicted)

	def remove(self, url):
		key = self.key(url, self._windows)
		try:
			index = self._keys.index(key)
		except ValueError:
			return
		self._keys.pop(index)
		return self._favorites.pop(index)

	def rename(self, url, name):
		name = self._normalize_name(name)
		key = self.key(url, self._windows)
		try:
			index = self._keys.index(key)
		except ValueError:
			return False
		favorite = self._favorites[index]
		self._favorites[index] = Favorite(name, favorite.url)
		return True

	def to_json(self):
		return {
			'favorites': [favorite._asdict() for favorite in self._favorites],
			'max_favorites': self.max_favorites
		}

	def _parse_entry(self, entry):
		if not isinstance(entry, dict):
			return None
		name = entry.get('name')
		url = entry.get('url')
		try:
			name = self._normalize_name(name)
			url = self._normalize_url(url)
		except (TypeError, ValueError):
			return None
		return Favorite(name, url)

	@staticmethod
	def key(url, windows=None):
		url = FavoritesStore._normalize_url(url)
		scheme = splitscheme(url)[0]
		if windows is None:
			windows = os_name == 'nt'
		if windows and scheme == 'file://':
			return url.casefold()
		return url

	@staticmethod
	def _normalize_url(url):
		if not isinstance(url, str):
			raise TypeError()
		return normalize(url)

	@staticmethod
	def _normalize_name(name):
		if not isinstance(name, str):
			raise TypeError()
		name = name.strip()
		if not name:
			raise ValueError()
		return name

	@staticmethod
	def _default_name(url):
		name = basename(url)
		if name:
			scheme = splitscheme(url)[0]
			if scheme == 'file://' and name.endswith(':'):
				return name + '\\'
			return name
		return as_human_readable(url)