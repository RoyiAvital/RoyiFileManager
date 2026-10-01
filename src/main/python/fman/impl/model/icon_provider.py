from fman.url import splitscheme
from pathlib import Path, PurePosixPath
from PyQt5.QtCore import QFileInfo

class IconProvider:
	def __init__(self, qt_icon_provider, fs, cache_dir):
		self._qt_icon_provider = qt_icon_provider
		self._fs = fs
		self._folder_icon = self._get_qt_icon(cache_dir)
		self._cache_dir = cache_dir
		self._cache = {
			f.suffix: self._get_qt_icon(f)
			for f in Path(cache_dir).glob('file*')
		}
	def get_icon(self, url):
		scheme, path = splitscheme(url)
		if scheme == 'file://':
			return self._get_qt_icon(path)
		url = self._fs.resolve(url)
		scheme, path = splitscheme(url)
		if scheme == 'file://':
			return self._get_qt_icon(path)
		if self._fs.is_dir(url):
			return self._folder_icon
		suffix = PurePosixPath(path).suffix
		if suffix not in self._cache:
			surrogate = Path(self._cache_dir, 'file' + suffix)
			with surrogate.open('w') as f:
				f.write('fman')
			self._cache[suffix] = self._get_qt_icon(surrogate)
		return self._cache[suffix]
	def _get_qt_icon(self, path):
		if not isinstance(path, str):
			path = str(path)
		return self._qt_icon_provider.icon(QFileInfo(path))


