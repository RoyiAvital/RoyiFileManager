from builtins import zip as zip_columns
from core.commands import *
from core.fs import *
from core import directory_size
from core.directory_size import DirectorySizeService, ToggleDirectorySizeColumn, \
	RecalculateDirectorySizes, SortByDirectorySize, ShowDirectorySize
from core.quick_view import QuickViewService, ToggleQuickView, QuickViewFit, \
	QuickViewActualSize, QuickViewZoomIn, QuickViewZoomOut, QuickViewPan
from datetime import datetime
from fman.fs import Column
from fman.impl.status_bar import format_size
from fman.impl.util.natural import natural_key
from PyQt5.QtCore import QLocale, QDateTime

# Define here so get_default_columns(...) can reference it as core.Name:
class Name(Column):
	keys_depend_on_external_data = False

	def text(self, listing, index):
		return listing.display_names[index]
	def keys(self, listing, ascending):
		result = []
		for name, is_dir in zip_columns(listing.display_names, listing.is_dir):
			result.append((is_dir ^ ascending, natural_key(name)))
		return tuple(result)

# Define here so get_default_columns(...) can reference it as core.Size:
class Size(Column):
	def text(self, listing, index):
		if listing.is_dir[index]:
			value = directory_size.get_value(listing.location.rstrip('/') + '/' + listing.names[index])
			return value[0] if value is not None else ''
		return '' if listing.sizes[index] is None else format_size(listing.sizes[index])
	def keys(self, listing, ascending):
		result = []
		for index, name in enumerate(listing.names):
			is_dir = listing.is_dir[index]
			if is_dir:
				value = directory_size.get_value(listing.location.rstrip('/') + '/' + name)
				minor = (value[1],) if value is not None else tuple(
					ord(character) if ascending else -ord(character) for character in name.lower())
			else:
				minor = listing.sizes[index] or 0
			result.append((is_dir ^ ascending, minor))
		return tuple(result)

# Define here so get_default_columns(...) can reference it as core.Modified:
class Modified(Column):
	keys_depend_on_external_data = False

	def text(self, listing, index):
		if listing.mtimes_ns[index] is None:
			return ''
		try:
			mtime = datetime.fromtimestamp(listing.mtimes_ns[index] / 1_000_000_000)
			timestamp = mtime.timestamp()
		except (OSError, OverflowError, ValueError):
			return ''
		mtime_qt = QDateTime.fromMSecsSinceEpoch(int(timestamp * 1000))
		return mtime_qt.toString(QLocale().dateTimeFormat(QLocale.ShortFormat).replace('yyyy', 'yy'))
	def keys(self, listing, ascending):
		result = []
		convert, minimum = datetime.fromtimestamp, datetime.min
		for is_dir, modified in zip_columns(listing.is_dir, listing.mtimes_ns):
			try:
				mtime = minimum if modified is None else convert(modified / 1_000_000_000)
			except (OSError, OverflowError, ValueError):
				mtime = minimum
			result.append((is_dir ^ ascending, mtime))
		return tuple(result)