from fman.impl.quick_view_animation import ApngMovie, MAX_ANIMATION_PIXELS, PNG_SIGNATURE, parse_apng
from fman.impl.quick_view_images import ImageRequest, load_image
from fman.url import as_url
from pathlib import Path
from PyQt5.QtGui import QMovie
from PyQt5.QtWidgets import QApplication
from tempfile import TemporaryDirectory
from unittest import TestCase

import struct
import zlib

BLACK, WHITE, RED = (0, 0, 0, 255), (255, 255, 255, 255), (255, 0, 0, 255)


def gif_bytes(frames=2, delay=5, loops=0):
	"""A 1x1 GIF whose frames alternate between black and white."""
	data = b'GIF89a\x01\x00\x01\x00\x80\x00\x00' + b'\x00\x00\x00\xff\xff\xff'
	data += b'\x21\xff\x0bNETSCAPE2.0\x03\x01' + struct.pack('<H', loops) + b'\x00'
	for index in range(frames):
		data += b'\x21\xf9\x04\x00' + struct.pack('<H', delay) + b'\x00\x00'
		data += b'\x2c\x00\x00\x00\x00\x01\x00\x01\x00\x00'
		data += b'\x02\x02' + (b'\x44' if index % 2 == 0 else b'\x4c') + b'\x01\x00'
	return data + b'\x3b'


def _chunk(kind, body):
	return struct.pack('>I', len(body)) + kind + body + struct.pack('>I', zlib.crc32(kind + body) & 0xffffffff)


def _pixels(width, height, color):
	row = b'\x00' + bytes(color) * width
	return zlib.compress(row * height)


def apng_bytes(frames=((0, 0, 2, 2, RED, 0, 0), (0, 0, 2, 2, WHITE, 0, 0)), size=(2, 2), plays=0, delay=(5, 100)):
	"""An RGBA APNG; each frame is (x, y, width, height, color, dispose, blend)."""
	width, height = size
	data = PNG_SIGNATURE + _chunk(b'IHDR', struct.pack('>IIBBBBB', width, height, 8, 6, 0, 0, 0))
	data += _chunk(b'acTL', struct.pack('>II', len(frames), plays))
	sequence = 0
	for index, (x, y, frame_width, frame_height, color, dispose, blend) in enumerate(frames):
		data += _chunk(b'fcTL', struct.pack('>IIIIIHHBB', sequence, frame_width, frame_height, x, y, delay[0], delay[1], dispose, blend))
		sequence += 1
		pixels = _pixels(frame_width, frame_height, color)
		if index == 0:
			data += _chunk(b'IDAT', pixels)
		else:
			data += _chunk(b'fdAT', struct.pack('>I', sequence) + pixels)
			sequence += 1
	return data + _chunk(b'IEND', b'')


def color(image, x, y):
	pixel = image.pixelColor(x, y)
	return pixel.red(), pixel.green(), pixel.blue(), pixel.alpha()


class AnimationTest(TestCase):
	def setUp(self):
		self.app = QApplication.instance() or QApplication([])
		temporary = TemporaryDirectory()
		self.addCleanup(temporary.cleanup)
		self.root = Path(temporary.name)

	def load(self, name, data):
		path = self.root / name
		path.write_bytes(data)
		return load_image(ImageRequest(1, as_url(path)), lambda: False, lambda url: url)

	def test_loader_marks_only_multi_frame_files_animated(self):
		for name, data, frames in (('two.gif', gif_bytes(), 2), ('one.gif', gif_bytes(1), 0),
				('anim.png', apng_bytes(), 2), ('single.apng.png', apng_bytes(frames=((0, 0, 2, 2, RED, 0, 0),)), 0)):
			with self.subTest(name=name):
				result = self.load(name, data)
				self.assertIsNotNone(result.image, result.message)
				self.assertEqual(frames, result.frames)
				self.assertEqual(bool(frames), bool(result.path))
				self.assertEqual(name == 'anim.png', result.animation is not None)

	def test_plain_png_and_corrupt_apng_stay_still(self):
		from PyQt5.QtGui import QImage
		image = QImage(3, 3, QImage.Format_ARGB32)
		image.fill(0)
		path = self.root / 'plain.png'
		image.save(str(path), 'PNG')
		result = load_image(ImageRequest(1, as_url(path)), lambda: False, lambda url: url)
		self.assertEqual((0, None), (result.frames, result.animation))
		bad = apng_bytes(frames=((0, 0, 2, 2, RED, 0, 0), (1, 1, 2, 2, WHITE, 0, 0)))
		result = self.load('bad.png', bad)
		self.assertIsNotNone(result.image)
		self.assertEqual(0, result.frames)

	def test_large_animations_stay_still(self):
		side = int(MAX_ANIMATION_PIXELS ** .5) + 1
		self.assertIsNone(parse_apng(apng_bytes(size=(side, side), frames=((0, 0, 1, 1, RED, 0, 0), (0, 0, 1, 1, RED, 0, 0)))))

	def test_short_control_chunks_keep_the_still_image(self):
		from fman.impl.quick_view_images import ImageLoader
		from threading import Event
		valid = apng_bytes()
		header = valid[:valid.index(b'acTL') - 4]
		first = valid.index(b'fcTL') - 4
		frame = valid[first:valid.index(b'fcTL', first + 8) - 4]
		for name, middle in (
				('short-frame.png', _chunk(b'acTL', struct.pack('>II', 2, 0)) + frame + _chunk(b'fcTL', b'')),
				('short-control.apng', _chunk(b'acTL', b'\x00\x00') + frame)):
			with self.subTest(name=name):
				data = header + middle + _chunk(b'IEND', b'')
				result = self.load(name, data)
				self.assertIsNotNone(result.image, result.message)
				self.assertEqual((0, None), (result.frames, result.animation))
				with self.assertRaises(ValueError):
					parse_apng(data)
				done = Event()
				loader = ImageLoader(done.set, lambda request, canceled: load_image(request, canceled, lambda url: url))
				self.addCleanup(loader.close)
				loader.submit(ImageRequest(loader.invalidate(), as_url(self.root / name)))
				self.assertTrue(done.wait(10))
				request, delivered = loader.take_result()
				self.assertIsNotNone(delivered.image, delivered.message)
				self.assertEqual(0, delivered.frames)

	def test_apng_suffix_and_png_suffix_both_play(self):
		from fman.impl.quick_view_images import load_preview
		for name in ('anim.apng', 'anim.png', 'ANIM.APNG'):
			with self.subTest(name=name):
				path = self.root / name
				path.write_bytes(apng_bytes())
				result = load_preview(ImageRequest(1, as_url(path)), lambda: False, lambda url: url)
				self.assertEqual(('image', 2), (result.kind, result.frames))

	def test_parse_reads_timing_loops_and_frame_data(self):
		animation = parse_apng(apng_bytes(plays=3, delay=(1, 0)))
		self.assertEqual((2, 2, 3), (animation.width, animation.height, animation.plays))
		self.assertEqual([20, 20], [frame.delay_ms for frame in animation.frames])
		self.assertEqual(500, parse_apng(apng_bytes(delay=(1, 2))).frames[0].delay_ms)
		self.assertIsNone(parse_apng(b'not a png'))
		with self.assertRaises(ValueError):
			parse_apng(apng_bytes()[:-20])

	def frames(self, data):
		movie = ApngMovie(parse_apng(data))
		images = []
		movie.frameChanged.connect(lambda index: images.append(movie.currentImage()))
		movie.start()
		movie.stop()
		while len(images) < len(movie._animation.frames):
			movie._state = QMovie.Running
			movie._next()
			movie.stop()
		return movie, images

	def test_dispose_and_blend_operations(self):
		half = (0, 0, 1, 2)
		cases = (
			# Over-blend a transparent area keeps the first frame; source replaces it.
			(((0, 0, 2, 2, RED, 0, 0), (*half, (0, 0, 0, 0), 0, 1)), RED),
			(((0, 0, 2, 2, RED, 0, 0), (*half, (0, 0, 0, 0), 0, 0)), (0, 0, 0, 0)),
			# Background dispose clears the first frame's area before the second.
			(((0, 0, 2, 2, RED, 1, 0), (1, 0, 1, 2, WHITE, 0, 0)), (0, 0, 0, 0)),
		)
		for frames, left in cases:
			with self.subTest(frames=frames):
				_, images = self.frames(apng_bytes(frames=frames))
				self.assertEqual(left, color(images[1], 0, 0))
		frames = ((0, 0, 2, 2, RED, 0, 0), (*half, WHITE, 2, 0), (1, 0, 1, 2, BLACK, 0, 0))
		_, images = self.frames(apng_bytes(frames=frames))
		self.assertEqual(WHITE, color(images[1], 0, 0))
		# Previous dispose restores the canvas from before the second frame.
		self.assertEqual((RED, BLACK), (color(images[2], 0, 0), color(images[2], 1, 0)))

	def test_play_count_pause_and_restart(self):
		movie = ApngMovie(parse_apng(apng_bytes(plays=1)))
		events = []
		movie.frameChanged.connect(lambda index: events.append(index))
		movie.finished.connect(lambda: events.append('finished'))
		movie.start()
		self.assertEqual(QMovie.Running, movie.state())
		movie.setPaused(True)
		self.assertEqual(QMovie.Paused, movie.state())
		self.assertFalse(movie._timer.isActive())
		movie.setPaused(False)
		self.assertTrue(movie._timer.isActive())
		movie._next()
		movie._next()
		self.assertEqual([0, 1, 'finished'], events)
		self.assertEqual(QMovie.NotRunning, movie.state())
		self.assertEqual(WHITE, color(movie.currentImage(), 0, 0))
		movie.start()
		self.assertEqual(0, events[-1])
		self.assertEqual(RED, color(movie.currentImage(), 0, 0))
		movie.stop()

	def test_undecodable_frame_reports_error(self):
		data = bytearray(apng_bytes())
		start = data.index(b'fdAT') + 8
		data[start:start + 4] = b'\xff\xff\xff\xff'
		movie = ApngMovie(parse_apng(bytes(data)))
		errors = []
		movie.error.connect(errors.append)
		movie.start()
		movie._next()
		self.assertEqual([0], errors)
		self.assertEqual(QMovie.NotRunning, movie.state())
