"""Animated image playback for QuickView: QMovie for GIF/WebP and a small APNG player."""

from dataclasses import dataclass
from PyQt5.QtCore import QObject, QRect, QTimer, pyqtSignal
from PyQt5.QtGui import QImage, QMovie, QPainter

import struct
import zlib

PNG_SIGNATURE = b'\x89PNG\r\n\x1a\n'
MAX_ANIMATION_PIXELS = 16000000
MIN_DELAY_MS = 20
# Chunks that apply to every frame and must precede the image data.
_SHARED_CHUNKS = frozenset((b'PLTE', b'tRNS', b'gAMA', b'cHRM', b'sRGB', b'iCCP', b'sBIT'))
_CONTROL_LENGTHS = {b'IHDR': 13, b'acTL': 8, b'fcTL': 26, b'fdAT': 4}


@dataclass(frozen=True)
class ApngFrame:
	x: int
	y: int
	width: int
	height: int
	delay_ms: int
	dispose: int
	blend: int
	parts: tuple


@dataclass(frozen=True)
class ApngAnimation:
	data: bytes
	width: int
	height: int
	plays: int
	header: bytes
	shared: bytes
	frames: tuple


def has_apng_control(device):
	"""True when a PNG device has an acTL chunk before its image data; leaves the position at 0."""
	try:
		device.seek(0)
		if bytes(device.read(8)) != PNG_SIGNATURE:
			return False
		position = 8
		while True:
			device.seek(position)
			head = bytes(device.read(8))
			if len(head) < 8:
				return False
			length, kind = struct.unpack('>I', head[:4])[0], head[4:]
			if kind == b'acTL':
				return True
			if kind in (b'IDAT', b'IEND'):
				return False
			position += 12 + length
	finally:
		device.seek(0)


def parse_apng(data):
	"""Index an APNG's frames; None when the file is not an animation with two or more frames."""
	if not data.startswith(PNG_SIGNATURE):
		return None
	position, header, control, current, after_data = 8, None, None, None, False
	shared, frames = [], []
	while position + 12 <= len(data):
		length = struct.unpack('>I', data[position:position + 4])[0]
		kind = data[position + 4:position + 8]
		start, end = position + 8, position + 8 + length
		if end + 4 > len(data):
			raise ValueError('Truncated PNG chunk')
		if length < _CONTROL_LENGTHS.get(kind, 0):
			raise ValueError('Short %s chunk' % kind.decode('ascii'))
		if kind == b'IHDR':
			header = data[start:end]
		elif kind == b'acTL':
			control = struct.unpack('>II', data[start:start + 8])
		elif kind == b'fcTL':
			_, width, height, x, y, numerator, denominator, dispose, blend = struct.unpack('>IIIIIHHBB', data[start:start + 26])
			current = [x, y, width, height, _delay(numerator, denominator), dispose, blend, []]
			frames.append(current)
		elif kind == b'IDAT':
			after_data = True
			if current is not None:
				current[7].append((start, end))
		elif kind == b'fdAT':
			if current is None:
				raise ValueError('Frame data before frame control')
			current[7].append((start + 4, end))
		elif kind == b'IEND':
			break
		elif kind in _SHARED_CHUNKS and not after_data:
			shared.append(data[position:end + 4])
		position = end + 4
	if header is None or control is None or len(frames) < 2:
		return None
	width, height = struct.unpack('>II', header[:8])
	if not 0 < width * height <= MAX_ANIMATION_PIXELS:
		return None
	result = []
	for x, y, frame_width, frame_height, delay, dispose, blend, parts in frames:
		if (frame_width == 0 or frame_height == 0 or x + frame_width > width or y + frame_height > height
				or dispose > 2 or blend > 1 or not parts):
			raise ValueError('Invalid APNG frame')
		result.append(ApngFrame(x, y, frame_width, frame_height, delay, dispose, blend, tuple(parts)))
	return ApngAnimation(data, width, height, control[1], header, b''.join(shared), tuple(result))


def _delay(numerator, denominator):
	milliseconds = numerator * 1000 // (denominator or 100)
	return max(MIN_DELAY_MS, milliseconds)


def _chunk(kind, body):
	return struct.pack('>I', len(body)) + kind + body + struct.pack('>I', zlib.crc32(kind + body) & 0xffffffff)


def decode_frame(animation, frame):
	"""Decode one frame with Qt's PNG reader by wrapping its data as a standalone PNG."""
	data = animation.data
	header = struct.pack('>II', frame.width, frame.height) + animation.header[8:]
	body = b''.join(data[start:end] for start, end in frame.parts)
	png = PNG_SIGNATURE + _chunk(b'IHDR', header) + animation.shared + _chunk(b'IDAT', body) + _chunk(b'IEND', b'')
	image = QImage.fromData(png, 'PNG')
	if image.isNull() or (image.width(), image.height()) != (frame.width, frame.height):
		raise ValueError('Cannot decode APNG frame')
	return image


class ApngMovie(QObject):
	"""The QMovie subset QuickView uses, for APNG, which Qt 5 cannot animate."""

	frameChanged = pyqtSignal(int)
	finished = pyqtSignal()
	error = pyqtSignal(int)

	def __init__(self, animation, parent=None):
		super().__init__(parent)
		self._animation = animation
		self._state = QMovie.NotRunning
		self._timer = QTimer(self)
		self._timer.setSingleShot(True)
		self._timer.timeout.connect(self._next)
		self._canvas = self._saved = None
		self._index = -1
		self._loops = 0
		self._delay = MIN_DELAY_MS

	def frameCount(self):
		return len(self._animation.frames)

	def state(self):
		return self._state

	def currentImage(self):
		return QImage() if self._canvas is None else QImage(self._canvas)

	def start(self):
		if self._state == QMovie.Paused:
			self.setPaused(False)
		elif self._state == QMovie.NotRunning:
			self._index, self._loops, self._canvas = -1, 0, None
			self._state = QMovie.Running
			self._next()

	def setPaused(self, paused):
		if paused and self._state == QMovie.Running:
			self._timer.stop()
			self._state = QMovie.Paused
		elif not paused and self._state == QMovie.Paused:
			self._state = QMovie.Running
			self._timer.start(self._delay)

	def stop(self):
		self._timer.stop()
		self._state = QMovie.NotRunning

	def _next(self):
		frames = self._animation.frames
		index = self._index + 1
		if index == len(frames):
			self._loops += 1
			if self._animation.plays and self._loops >= self._animation.plays:
				self.stop()
				self.finished.emit()
				return
			index, self._canvas = 0, None
		try:
			self._render(index)
		except ValueError:
			self.stop()
			self.error.emit(0)
			return
		self._index = index
		self._delay = frames[index].delay_ms
		if self._state == QMovie.Running:
			self._timer.start(self._delay)
		self.frameChanged.emit(index)

	def _render(self, index):
		frames = self._animation.frames
		if self._canvas is None:
			self._canvas = QImage(self._animation.width, self._animation.height, QImage.Format_ARGB32_Premultiplied)
			self._canvas.fill(0)
			self._saved = None
		elif index > 0:
			previous = frames[index - 1]
			area = QRect(previous.x, previous.y, previous.width, previous.height)
			if previous.dispose == 1 or (previous.dispose == 2 and self._saved is None):
				painter = QPainter(self._canvas)
				painter.setCompositionMode(QPainter.CompositionMode_Clear)
				painter.fillRect(area, 0)
				painter.end()
			elif previous.dispose == 2:
				self._canvas = self._saved
		frame = frames[index]
		image = decode_frame(self._animation, frame)
		# The first frame's "previous" is the cleared canvas, so saving is only needed afterwards.
		self._saved = QImage(self._canvas) if frame.dispose == 2 and index > 0 else None
		painter = QPainter(self._canvas)
		if frame.blend == 0:
			painter.setCompositionMode(QPainter.CompositionMode_Source)
		painter.drawImage(frame.x, frame.y, image)
		painter.end()


def create_movie(result, parent):
	"""A playing-capable movie for an animated ImageResult, or None."""
	if result.animation is not None:
		return ApngMovie(result.animation, parent)
	movie = QMovie(result.path, result.format.encode('ascii'), parent)
	movie.setCacheMode(QMovie.CacheNone)
	return movie if movie.isValid() else None
