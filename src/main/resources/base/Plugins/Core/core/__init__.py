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
from fman.url import basename
from PyQt5.QtCore import QLocale, QDateTime
from unicodedata import decimal

import fman.fs
import re

_DIGITS = re.compile(r'(\d+)')

def _natural_name_key(name):
	parts = _DIGITS.split(name.lower())
	for index in range(1, len(parts), 2):
		digits = parts[index]
		if not digits.isascii():
			digits = ''.join(str(decimal(character)) for character in digits)
		digits = digits.lstrip('0') or '0'
		if len(digits) <= 6:
			parts[index] = '0' + digits.zfill(6)
		else:
			length = str(len(digits))
			parts[index] = '1' + '1' * len(length) + '0' + length + digits
	return ''.join(parts)

# Define here so get_default_columns(...) can reference it as core.Name:
class Name(Column):
	keys_depend_on_external_data = False

	def __init__(self, fs=fman.fs):
		super().__init__()
		self._fs = fs
	def get_str(self, url):
		return self._fs.query(url, 'name')
	def text(self, listing, index):
		return listing.display_names[index]
	def keys(self, listing, ascending):
		result = []
		for name, is_dir in zip_columns(listing.display_names, listing.is_dir):
			result.append((is_dir ^ ascending, _natural_name_key(name)))
		return tuple(result)
	def get_sort_value(self, url, is_ascending):
		try:
			is_dir = self._fs.is_dir(url)
		except FileNotFoundError:
			raise
		except OSError:
			is_dir = False
		major = is_dir ^ is_ascending
		minor = _natural_name_key(self.get_str(url))
		return major, minor

# Define here so get_default_columns(...) can reference it as core.Size:
class Size(Column):
	def __init__(self, fs=fman.fs):
		super().__init__()
		self._fs = fs
	def get_str(self, url):
		try:
			is_dir = self._fs.is_dir(url)
		except FileNotFoundError:
			raise
		except OSError:
			return ''
		if is_dir:
			value = directory_size.get_value(url)
			return value[0] if value is not None else ''
		try:
			size_bytes = self._get_size(url)
		except OSError:
			return ''
		if size_bytes is None:
			return ''
		return format_size(size_bytes)
	def get_sort_value(self, url, is_ascending):
		try:
			is_dir = self._fs.is_dir(url)
		except FileNotFoundError:
			raise
		except OSError:
			is_dir = False
		if is_dir:
			value = directory_size.get_value(url)
			if value is not None:
				minor = (value[1],)
			else:
				ord_ = ord if is_ascending else lambda c: -ord(c)
				minor = tuple(ord_(c) for c in basename(url).lower())
		else:
			try:
				minor = self._get_size(url)
			except OSError:
				minor = 0
		return is_dir ^ is_ascending, minor
	def _get_size(self, url):
		return self._fs.query(url, 'size_bytes')
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

	def __init__(self, fs=fman.fs):
		super().__init__()
		self._fs = fs
	def get_str(self, url):
		try:
			mtime = self._get_mtime(url)
		except OSError:
			return ''
		if mtime is None:
			return ''
		try:
			timestamp = mtime.timestamp()
		except OSError:
			# This can occur on Windows. To reproduce:
			#     datetime.min.timestamp()
			# This raises `OSError: [Errno 22] Invalid argument`.
			return ''
		mtime_qt = QDateTime.fromMSecsSinceEpoch(int(timestamp * 1000))
		time_format = QLocale().dateTimeFormat(QLocale.ShortFormat)
		# Always show two-digit years, not four digits:
		time_format = time_format.replace('yyyy', 'yy')
		return mtime_qt.toString(time_format)
	def get_sort_value(self, url, is_ascending):
		try:
			is_dir = self._fs.is_dir(url)
		except FileNotFoundError:
			raise
		except OSError:
			is_dir = False
		try:
			mtime = self._get_mtime(url)
		except OSError:
			mtime = None
		return is_dir ^ is_ascending, mtime or datetime.min
	def _get_mtime(self, url):
		return self._fs.query(url, 'modified_datetime')
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