from fman.impl.status_bar import ACTIVE_PANE, DEFAULT_SETTINGS, DISABLED, \
	PER_PANE, PaneStatusSnapshot, StatusCalculationService, StatusEntry, \
	PaneStatusWidget, _CancellationToken, calculate_status_summary, format_size, \
	next_status_bar_mode, validate_status_bar_settings
from PyQt5.QtCore import QCoreApplication, QEventLoop, QObject, QThread, \
	QTimer, pyqtSignal, pyqtSlot
from PyQt5.QtWidgets import QApplication
from unittest import TestCase


class _ResultReceiver(QObject):
	def __init__(self, event_loop):
		super().__init__()
		self._event_loop = event_loop
		self.result = None
		self.received_on_thread = None
	@pyqtSlot(object, int, object)
	def receive(self, owner_id, generation, summary):
		self.result = owner_id, generation, summary
		self.received_on_thread = QThread.currentThread()
		self._event_loop.quit()


class _Pane(QObject):
	status_changed = pyqtSignal()
	def enable_status_tracking(self):
		pass
	def disable_status_tracking(self):
		pass
	def get_status_snapshot(self):
		return PaneStatusSnapshot(
			'file:///',
			(StatusEntry('file:///selected.txt', False, True, True),),
			True, False
		)


class _FileSystem:
	def query(self, _url, _attribute):
		return 42


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


class PaneStatusWidgetTest(TestCase):
	def test_active_marker_follows_per_pane_active_state(self):
		app = QApplication.instance() or QApplication([])
		service = StatusCalculationService(_FileSystem())
		widget = PaneStatusWidget(service, 10, 1024, True)
		self.assertTrue(widget._active.isHidden())
		widget.set_active(True)
		self.assertFalse(widget._active.isHidden())
		widget.set_active(False)
		self.assertTrue(widget._active.isHidden())
		service.shutdown()
		self.assertIsNotNone(app)
	def test_active_marker_stays_hidden_in_active_pane_mode(self):
		app = QApplication.instance() or QApplication([])
		service = StatusCalculationService(_FileSystem())
		widget = PaneStatusWidget(service, 10, 1024, False)
		widget.set_active(True)
		self.assertTrue(widget._active.isHidden())
		service.shutdown()
		self.assertIsNotNone(app)
	def test_worker_result_renders_selected_details(self):
		app = QApplication.instance() or QApplication([])
		event_loop = QEventLoop()
		service = StatusCalculationService(_FileSystem())
		widget = PaneStatusWidget(service, 10, 1024, False)
		widget.bind(_Pane())
		QTimer.singleShot(500, event_loop.quit)
		event_loop.exec()
		service.shutdown()
		self.assertEqual('1 files', widget._files.text())
		self.assertEqual(
			'Selected: 0 dirs, 1 files, 42 B', widget._selection.text()
		)
		self.assertIsNotNone(app)


class StatusCalculationServiceTest(TestCase):
	def test_worker_result_is_published_on_qt_thread(self):
		app = QCoreApplication.instance() or QCoreApplication([])
		event_loop = QEventLoop()
		receiver = _ResultReceiver(event_loop)
		service = StatusCalculationService(_FileSystem())
		service.finished.connect(receiver.receive)
		snapshot = PaneStatusSnapshot(
			'file:///',
			(StatusEntry('file:///selected.txt', False, True, True),),
			True, False
		)
		QTimer.singleShot(
			0, lambda: service.submit(
				7, 3, snapshot, 10, _CancellationToken()
			)
		)
		QTimer.singleShot(2000, event_loop.quit)
		event_loop.exec()
		service.shutdown()
		self.assertIsNotNone(receiver.result)
		self.assertEqual((7, 3), receiver.result[:2])
		self.assertEqual(1, receiver.result[2].selected_file_count)
		self.assertEqual(service.thread(), receiver.received_on_thread)
		self.assertIsNotNone(app)