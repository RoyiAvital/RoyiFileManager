from dataclasses import dataclass
from threading import Condition, Thread
from pathlib import PureWindowsPath
from PyQt5.QtCore import QFile, QIODevice
from PyQt5.QtGui import QImage, QImageReader
from fman.url import as_human_readable, splitscheme

import os
import stat


MAX_FILE_BYTES = 64 * 1024 * 1024
MAX_EDGE = 65536
MAX_PIXELS = 128000000
MAX_IMAGE_BYTES = MAX_PIXELS * 4
FORMATS = frozenset((b'jpeg', b'jpg', b'png', b'bmp', b'gif', b'ico', b'tiff', b'tif', b'webp'))


@dataclass(frozen=True)
class ImageRequest:
	generation: int
	url: str
	mode: str = 'rendered'
	colors: tuple = ('#dddddd', '#252525')
	content: object = None


@dataclass(frozen=True)
class ImageResult:
	image: object = None
	message: str = ''
	format: str = ''
	fingerprint: tuple = ()
	kind: str = 'image'


def load_preview(request, canceled, resolve=None):
	if canceled():
		return None
	if request.content is not None:
		from fman.impl.quick_view_text import convert_text
		return convert_text(request.content, request.mode, request.colors, canceled)
	if PureWindowsPath(request.url).suffix.lower() in (
		'.jpg', '.jpeg', '.png', '.bmp', '.gif', '.ico', '.tif', '.tiff', '.webp', '.avif', '.heic'
	):
		return load_image(request, canceled, resolve)
	from fman.impl.quick_view_text import load_text
	return load_text(request, canceled, resolve)


def valid_dimensions(width, height):
	return 0 < width <= MAX_EDGE and 0 < height <= MAX_EDGE and width * height <= MAX_PIXELS


def fit_scale(width, height, viewport_width, viewport_height, ratio):
	if min(width, height, viewport_width, viewport_height, ratio) <= 0:
		return 1.0
	return min(1.0, viewport_width * ratio / width, viewport_height * ratio / height)


def zoom_scale(scale, steps):
	return max(.05, min(8.0, scale * 1.25 ** max(-40, min(40, steps))))


def _fingerprint(info):
	return info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns


def load_image(request, canceled, resolve=None):
	def check():
		if canceled():
			raise InterruptedError()
	try:
		check()
		if not request.url:
			return ImageResult(message='No file selected', kind='error')
		if splitscheme(request.url)[0] != 'file://':
			return ImageResult(message='Only local files can be previewed', kind='error')
		if resolve is None:
			from fman.fs import resolve
		url = resolve(request.url)
		check()
		if splitscheme(url)[0] != 'file://':
			return ImageResult(message='Only local files can be previewed', kind='error')
		path = as_human_readable(url)
		before = os.stat(path)
		check()
		if stat.S_ISDIR(before.st_mode):
			return ImageResult(message='Folder', kind='error')
		if not stat.S_ISREG(before.st_mode):
			return ImageResult(message='Not a regular file', kind='error')
		if before.st_size > MAX_FILE_BYTES:
			return ImageResult(message='File exceeds 64 MiB', kind='error')
		device = QFile(path)
		if not device.open(QIODevice.ReadOnly):
			return ImageResult(message='Cannot read file: ' + device.errorString(), kind='error')
		try:
			if device.size() > MAX_FILE_BYTES:
				return ImageResult(message='File exceeds 64 MiB', kind='error')
			check()
			reader = QImageReader(device)
			reader.setDecideFormatFromContent(True)
			image_format = bytes(reader.format()).lower()
			if image_format not in FORMATS:
				return ImageResult(message='Unsupported image format or unavailable codec', kind='error')
			reader.setFormat(image_format)
			reader.setDecideFormatFromContent(False)
			reader.setAutoDetectImageFormat(False)
			reader.setAutoTransform(True)
			size = reader.size()
			if not valid_dimensions(size.width(), size.height()):
				return ImageResult(message='Image dimensions unavailable or exceed 128 MP / 65,536 pixels', kind='error')
			check()
			image = reader.read()
			check()
			if image.isNull():
				return ImageResult(message='Cannot decode image: ' + reader.errorString(), kind='error')
			if not valid_dimensions(image.width(), image.height()):
				return ImageResult(message='Decoded image exceeds size limits', kind='error')
			image = image.convertToFormat(QImage.Format_ARGB32_Premultiplied if image.hasAlphaChannel() else QImage.Format_RGB32)
			if image.isNull() or image.sizeInBytes() > MAX_IMAGE_BYTES:
				return ImageResult(message='Decoded image exceeds memory allowance', kind='error')
			image.setDevicePixelRatio(1)
			check()
			if _fingerprint(before) != _fingerprint(os.stat(path)):
				return ImageResult(message='File changed while loading', kind='error')
			return ImageResult(image, format=image_format.decode('ascii'), fingerprint=_fingerprint(before))
		finally:
			device.close()
	except InterruptedError:
		return None
	except (OSError, ValueError) as error:
		return ImageResult(message='Cannot preview file: ' + str(error), kind='error')


class ImageLoader:
	def __init__(self, notify, load=load_image):
		self._notify = notify
		self._load = load
		self._condition = Condition()
		self._thread = None
		self._generation = 0
		self._pending = None
		self._result = None
		self._closed = False

	def invalidate(self):
		with self._condition:
			self._generation += 1
			self._pending = self._result = None
			self._condition.notify_all()
			return self._generation

	def submit(self, request):
		with self._condition:
			if self._closed or request.generation != self._generation:
				return
			self._pending = request
			if self._thread is None:
				self._thread = Thread(target=self._run, name='QuickView image', daemon=True)
				self._thread.start()
			self._condition.notify_all()

	def take_result(self):
		with self._condition:
			result, self._result = self._result, None
			self._condition.notify_all()
			return result

	def _canceled(self, generation):
		with self._condition:
			return self._closed or generation != self._generation

	@property
	def busy(self):
		with self._condition:
			return self._thread is not None

	def _run(self):
		while True:
			with self._condition:
				if self._closed or self._pending is None:
					self._thread = None
					if not self._closed:
						try:
							self._notify()
						except RuntimeError:
							self.close()
					return
				request, self._pending = self._pending, None
			try:
				result = self._load(request, lambda: self._canceled(request.generation))
			except Exception:
				result = ImageResult(message='Unable to preview file', kind='error')
			with self._condition:
				if self._closed or request.generation != self._generation or result is None:
					result = None
					continue
				self._result = request, result
				result = None
				try:
					self._notify()
				except RuntimeError:
					self.close()
				while self._result is not None and not self._closed:
					self._condition.wait()

	def close(self):
		with self._condition:
			self._closed = True
			self._pending = self._result = self._notify = None
			self._condition.notify_all()