from core.commands import *
from core.fs import *
from datetime import datetime
from fman.fs import Column
from fman.impl.status_bar import format_size
from fman.url import basename
from PyQt5.QtCore import QLocale, QDateTime

import fman.fs
import re

_DIGITS = re.compile(r'\d+')

# Define here so get_default_columns(...) can reference it as core.Name:
class Name(Column):
	def __init__(self, fs=fman.fs):
		super().__init__()
		self._fs = fs
	def get_str(self, url):
		return self._fs.query(url, 'name')
	def get_sort_value(self, url, is_ascending):
		try:
			is_dir = self._fs.is_dir(url)
		except FileNotFoundError:
			raise
		except OSError:
			is_dir = False
		major = is_dir ^ is_ascending
		str_ = self.get_str(url).lower()
		minor = _DIGITS.sub(
			lambda match: '%06d' % int(match.group(0)), str_
		)
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
			return ''
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

# Define here so get_default_columns(...) can reference it as core.Modified:
class Modified(Column):
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