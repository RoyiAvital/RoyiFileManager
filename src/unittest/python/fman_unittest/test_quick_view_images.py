from fman.impl.quick_view_images import (
	ImageRequest, MAX_FILE_BYTES, MAX_IMAGE_BYTES, fit_scale, load_image,
	valid_dimensions, zoom_scale
)
from unittest import TestCase
from unittest.mock import Mock


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
