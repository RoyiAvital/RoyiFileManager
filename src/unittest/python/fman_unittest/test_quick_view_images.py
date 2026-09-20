from fman.impl.quick_view_images import (
	ImageRequest, MAX_FILE_BYTES, MAX_IMAGE_BYTES, fit_scale, load_image,
	valid_dimensions, zoom_scale
)
from unittest import TestCase
from unittest.mock import Mock
from unittest import skipUnless

import os
import subprocess
import sys


class ImageGeometryTest(TestCase):
	def test_limits_without_large_allocations(self):
		for width, height, allowed in (
			(16000, 8000, True), (16001, 8000, False), (65536, 1, True),
			(1, 65536, True), (65537, 1, False), (1, 65537, False),
			(65536, 65536, False), (0, 2, False), (-1, 2, False)
		):
			with self.subTest(width=width, height=height):
				self.assertEqual(allowed, valid_dimensions(width, height))
		self.assertEqual(512000000, MAX_IMAGE_BYTES)
		self.assertEqual(67108864, MAX_FILE_BYTES)

	def test_fit_uses_physical_pixels_without_upscaling(self):
		for ratio in (1, 1.25, 1.5, 2):
			self.assertEqual(400 * ratio / 1600, fit_scale(1600, 800, 400, 400, ratio))
			self.assertEqual(1, fit_scale(40, 20, 400, 400, ratio))
		self.assertLess(fit_scale(16000, 8000, 100, 100, 1), .05)

	def test_zoom_limits(self):
		self.assertEqual(1.25, zoom_scale(1, 1))
		self.assertEqual(.8, zoom_scale(1, -1))
		self.assertEqual(8, zoom_scale(8, 1))
		self.assertEqual(.05, zoom_scale(.01, -1))

	def test_canceled_and_remote_requests_do_no_resolution(self):
		resolve = Mock(side_effect=AssertionError('Unexpected I/O'))
		self.assertIsNone(load_image(ImageRequest(1, 'file://missing'), lambda: True, resolve))
		for url in ('zip://archive/file.png', 'https://example/file.png', ''):
			self.assertIsNone(load_image(ImageRequest(1, url), lambda: False, resolve).image)
		resolve.assert_not_called()


@skipUnless(os.environ.get('QUICK_VIEW_PERFORMANCE_TESTS') == '1' and sys.platform == 'win32', 'Opt-in Windows image memory measurement')
class ImageMemoryTest(TestCase):
	def test_128mp_peak_in_fresh_process(self):
		from pathlib import Path
		from tempfile import TemporaryDirectory
		from PyQt5.QtGui import QImage, QColor
		with TemporaryDirectory() as temporary:
			path = Path(temporary) / '128mp.png'
			image = QImage(16000, 8000, QImage.Format_ARGB32)
			image.fill(QColor(30, 100, 170, 128))
			self.assertTrue(image.save(str(path), 'PNG'))
			del image
			code = '''
from fman.impl.quick_view_images import ImageLoader, ImageRequest, load_image, MAX_IMAGE_BYTES
from fman.url import as_url
from time import perf_counter
from PyQt5.QtCore import QCoreApplication, QObject, QTimer, Qt, pyqtSignal
import sys, win32api, win32process
app = QCoreApplication([])
class Delivery(QObject):
	ready = pyqtSignal()
delivery = Delivery()
loader = ImageLoader(delivery.ready.emit, lambda request, canceled: load_image(request, canceled, lambda url: url))
results = []
ticks = []
timer = QTimer()
timer.setInterval(10)
timer.timeout.connect(lambda: ticks.append(perf_counter()))
timer.start()
def receive():
	packet = loader.take_result()
	if packet is not None:
		results.append(packet[1])
		ticks.append(perf_counter())
		app.quit()
delivery.ready.connect(receive, Qt.QueuedConnection)
handle = win32api.GetCurrentProcess()
before = win32process.GetProcessMemoryInfo(handle)['WorkingSetSize']
started = perf_counter()
ticks.append(started)
loader.submit(ImageRequest(loader.invalidate(), as_url(sys.argv[1])))
QTimer.singleShot(90000, app.quit)
app.exec_()
assert results, 'Image delivery timed out'
result = results.pop()
assert result.image is not None, result.message
assert result.image.sizeInBytes() == MAX_IMAGE_BYTES
assert (result.image.width(), result.image.height()) == (16000, 8000)
assert result.image.pixelColor(15999, 7999).alpha() == 128
memory = win32process.GetProcessMemoryInfo(handle)
max_gap = max(later - earlier for earlier, later in zip(ticks, ticks[1:]))
print('128 MP: %.3f s; buffer %.2f MiB; incremental peak %.2f MiB; max Qt heartbeat gap %.1f ms' %
    (perf_counter() - started, result.image.sizeInBytes() / 1048576,
	(memory['PeakWorkingSetSize'] - before) / 1048576, max_gap * 1000), flush=True)
loader.close()
del result
print('After release: %.2f MiB above baseline' %
    ((win32process.GetProcessMemoryInfo(handle)['WorkingSetSize'] - before) / 1048576), flush=True)
assert max_gap < .1, 'Qt heartbeat gap exceeded the 100 ms target'
'''
			result = subprocess.run([sys.executable, '-c', code, str(path)], capture_output=True, text=True, timeout=120)
			self.assertEqual(0, result.returncode, result.stderr)
			print(result.stdout, end='')