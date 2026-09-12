from fman.impl.status_bar import ACTIVE_PANE, DEFAULT_SETTINGS, DISABLED, \
	PER_PANE, StatusEntry, calculate_status_summary, format_size, \
	next_status_bar_mode, validate_status_bar_settings
from unittest import TestCase


class StatusBarSettingsTest(TestCase):
	def test_defaults_and_mode_cycle(self):
		self.assertEqual(DEFAULT_SETTINGS, validate_status_bar_settings(None))
		self.assertEqual(ACTIVE_PANE, next_status_bar_mode(DISABLED))
		self.assertEqual(PER_PANE, next_status_bar_mode(ACTIVE_PANE))
		self.assertEqual(DISABLED, next_status_bar_mode(PER_PANE))
	def test_invalid_values_fall_back_independently(self):
		self.assertEqual({
			'mode': PER_PANE, 'max_entries': 5000, 'size_divisor': 1024
		}, validate_status_bar_settings({
			'mode': PER_PANE, 'max_entries': True, 'size_divisor': 7
		}))


class FormatSizeTest(TestCase):
	def test_binary_units(self):
		self.assertEqual('1.0 KiB', format_size(1024))
		self.assertEqual('1.0 MiB', format_size(1024 ** 2))
	def test_decimal_units(self):
		self.assertEqual('1.0 KB', format_size(1000, 1000))
		self.assertEqual('1.0 MB', format_size(1000 ** 2, 1000))


class CalculateStatusSummaryTest(TestCase):
	def test_counts_and_sizes_visible_entries(self):
		entries = (
			StatusEntry('file://dir', True, True, True),
			StatusEntry('file://a', False, True, True),
			StatusEntry('file://b', False, True, False)
		)
		result = calculate_status_summary(
			entries, {'file://a': 10, 'file://b': 20}.__getitem__, True, 10
		)
		self.assertEqual((1, 2, 30), result[:3])
		self.assertEqual((1, 1, 10), result[6:9])
		self.assertTrue(result.size_complete)
	def test_unloaded_and_limited_entries_are_incomplete(self):
		entries = (
			StatusEntry('file://a', False, True, False),
			StatusEntry('file://b', False, True, True),
			StatusEntry('file://c', False, False, True)
		)
		result = calculate_status_summary(entries, lambda _: 5, False, 1)
		self.assertEqual(5, result.size_bytes)
		self.assertTrue(result.size_limited)
		self.assertFalse(result.size_complete)
		self.assertFalse(result.selected_size_complete)
	def test_unsupported_sizes_show_as_unsupported(self):
		def unsupported(_):
			raise NotImplementedError()
		result = calculate_status_summary(
			(StatusEntry('drives://C', False, True, False),),
			unsupported, True, 10
		)
		self.assertFalse(result.size_supported)
	def test_cancellation_discards_result(self):
		result = calculate_status_summary(
			(StatusEntry('file://a', False, True, False),),
			lambda _: 1, True, 10, lambda: True
		)
		self.assertIsNone(result)