from collections import OrderedDict
import ctypes
from ctypes import wintypes
from pathlib import PureWindowsPath
from struct import pack
from threading import Lock, Thread

from PyQt5.QtCore import QObject, Qt, pyqtSignal
from PyQt5.QtGui import QIcon, QImage, QPixmap
from PyQt5.QtWidgets import QApplication, QStyle


def extract_icon(path, attributes, generic, size=32):
	class ShellInfo(ctypes.Structure):
		_fields_ = [('icon', wintypes.HANDLE), ('index', ctypes.c_int),
			('attributes', wintypes.DWORD), ('name', wintypes.WCHAR * 260),
			('type', wintypes.WCHAR * 80)]
	with_com = ctypes.OleDLL('ole32')
	with_com.CoInitialize(None)
	shell = ctypes.WinDLL('shell32', use_last_error=True)
	user = ctypes.WinDLL('user32', use_last_error=True)
	gdi = ctypes.WinDLL('gdi32', use_last_error=True)
	for library, name, arguments, result in (
		(shell, 'SHGetFileInfoW', [wintypes.LPCWSTR, wintypes.DWORD, ctypes.c_void_p,
			wintypes.UINT, wintypes.UINT], ctypes.c_size_t),
		(user, 'DestroyIcon', [wintypes.HANDLE], wintypes.BOOL),
		(user, 'DrawIconEx', [wintypes.HDC, ctypes.c_int, ctypes.c_int, wintypes.HANDLE,
			ctypes.c_int, ctypes.c_int, wintypes.UINT, wintypes.HBRUSH, wintypes.UINT], wintypes.BOOL),
		(gdi, 'CreateCompatibleDC', [wintypes.HDC], wintypes.HDC),
		(gdi, 'CreateDIBSection', [wintypes.HDC, ctypes.c_void_p, wintypes.UINT,
			ctypes.c_void_p, wintypes.HANDLE, wintypes.DWORD], wintypes.HBITMAP),
		(gdi, 'SelectObject', [wintypes.HDC, wintypes.HANDLE], wintypes.HANDLE),
		(gdi, 'DeleteObject', [wintypes.HANDLE], wintypes.BOOL),
		(gdi, 'DeleteDC', [wintypes.HDC], wintypes.BOOL)):
		function = getattr(library, name)
		function.argtypes, function.restype = arguments, result
	info = ShellInfo()
	dc = bitmap = previous = None
	try:
		if not shell.SHGetFileInfoW(path, attributes, ctypes.byref(info), ctypes.sizeof(info),
			0x100 | (0x10 if generic else 0)):
			return None
		dc = gdi.CreateCompatibleDC(None)
		bits = ctypes.c_void_p()
		header = ctypes.create_string_buffer(pack('<IiiHHIIiiII', 40, size, -size, 1, 32, 0, size * size * 4, 0, 0, 0, 0))
		bitmap = gdi.CreateDIBSection(dc, header, 0, ctypes.byref(bits), None, 0)
		if not dc or not bitmap:
			return None
		previous = gdi.SelectObject(dc, bitmap)
		ctypes.memset(bits, 0, size * size * 4)
		if not user.DrawIconEx(dc, 0, 0, info.icon, size, size, 0, None, 3):
			return None
		pixels = ctypes.string_at(bits, size * size * 4)
		return pixels
	finally:
		if previous:
			gdi.SelectObject(dc, previous)
		if bitmap:
			gdi.DeleteObject(bitmap)
		if dc:
			gdi.DeleteDC(dc)
		if info.icon:
			user.DestroyIcon(info.icon)
		with_com.CoUninitialize()


class ListingIcons(QObject):
	changed = pyqtSignal(object)
	_ready = pyqtSignal(object, object)

	def __init__(self, parent=None, loader=extract_icon):
		super().__init__(parent)
		self._loader = loader
		self._cache = OrderedDict()
		self._pending = OrderedDict()
		self._inflight = set()
		self._lock = Lock()
		self._running = False
		self._closed = False
		style = QApplication.style()
		self._file = style.standardIcon(QStyle.SP_FileIcon)
		self._folder = style.standardIcon(QStyle.SP_DirIcon)
		self._ready.connect(self._receive, Qt.QueuedConnection)
		self.destroyed.connect(self.close)

	def key(self, listing, index):
		name = listing.names[index]
		if not listing.location.startswith('file://'):
			return 'provider', listing.is_dir[index]
		suffix = PureWindowsPath(name).suffix.lower()
		individual = listing.is_dir[index] or suffix in ('.exe', '.lnk', '.ico', '.url') or not suffix
		if individual:
			path = (listing.location[7:].rstrip('/') + '/' + name).replace('/', '\\')
			return path, listing.identity(index), listing.mtimes_ns[index]
		return suffix

	def icon(self, listing, index):
		attributes = listing.attributes[index]
		fallback = self._folder if listing.is_dir[index] else self._file
		if not listing.location.startswith('file://') or attributes & (0x400 | 0x1000 | 0x400000):
			return fallback
		key = self.key(listing, index)
		if key in self._cache:
			self._cache.move_to_end(key)
			return self._cache[key] or fallback
		with self._lock:
			if not self._closed and key not in self._pending and key not in self._inflight \
				and len(self._pending) + len(self._inflight) < 128:
				generic = isinstance(key, str)
				self._pending[key] = ('file' + key if generic else key[0], attributes, generic)
				if not self._running:
					self._running = True
					Thread(target=self._run, daemon=True).start()
		return fallback

	def _run(self):
		while True:
			with self._lock:
				if self._closed or not self._pending:
					self._running = False
					return
				key, arguments = self._pending.popitem(last=False)
				self._inflight.add(key)
			try:
				pixels = self._loader(*arguments)
			except Exception:
				pixels = None
			with self._lock:
				if self._closed:
					self._running = False
					return
			try:
				self._ready.emit(key, pixels)
			except RuntimeError:
				return

	def _receive(self, key, pixels):
		with self._lock:
			self._inflight.discard(key)
		if self._closed:
			return
		self._cache[key] = QIcon(QPixmap.fromImage(QImage(pixels, 32, 32,
			QImage.Format_ARGB32).copy())) if pixels else None
		while len(self._cache) > 256:
			self._cache.popitem(last=False)
		self.changed.emit(key)

	def close(self, *_):
		with self._lock:
			self._closed = True
			self._pending.clear()
			self._inflight.clear()