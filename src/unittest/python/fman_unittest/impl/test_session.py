from unittest import TestCase
from unittest.mock import Mock, patch

from fman.impl.session import SessionManager, _encode


class SessionManagerWindowTest(TestCase):
	def test_startup_version_messages_and_persistence(self):
		version = '0.3.0'
		for previous_version in (None, version, '0.2.2', '1.7.5'):
			with self.subTest(previous_version=previous_version):
				settings = _Settings({})
				if previous_version is not None:
					settings['fman_version'] = previous_version
				manager = SessionManager(settings, None, None, version, True)
				window = Mock()
				window.saveGeometry.return_value = b'geometry'
				window.saveState.return_value = b'state'
				window.get_panes.return_value = []
				expected = 'v%s ready.' % version
				if previous_version and previous_version != version:
					expected = 'Updated to v%s.' % version

				manager._show_startup_messages(window)

				window.show_status_message.assert_called_once_with(
					expected, timeout_secs=5
				)
				self.assertEqual(expected, manager._get_startup_message())
				manager.on_close(window)
				self.assertEqual(version, settings['fman_version'])
				self.assertEqual(1, settings.flush_calls)
				restored = SessionManager(settings, None, None, version, True)
				window.show_status_message.reset_mock()
				restored._show_startup_messages(window)
				window.show_status_message.assert_called_once_with(
					'v%s ready.' % version, timeout_secs=5
				)

	def test_first_run_starts_windowed_at_default_size(self):
		window = _Window()
		manager = SessionManager({}, None, None, '1.7.5', True)

		with patch('fman.impl.session.Thread'):
			manager.show_main_window(window)

		self.assertEqual([(1280, 800)], window._widget.resize_calls)
		self.assertEqual(1, window._widget.show_calls)
		self.assertEqual(0, window._widget.show_maximized_calls)

	def test_saved_window_geometry_and_state_are_restored(self):
		geometry = b'geometry'
		state = b'state'
		settings = {
			'window_geometry': _encode(geometry),
			'window_state': _encode(state),
			'panes': [{}, {}]
		}
		window = _Window()
		manager = SessionManager(settings, None, None, '1.7.5', True)

		with patch('fman.impl.session.Thread'):
			manager.show_main_window(window)

		self.assertEqual([geometry], window._widget.restored_geometries)
		self.assertEqual([(state, manager._MAIN_WINDOW_VERSION)],
						 window._widget.restored_states)
		self.assertEqual([], window._widget.resize_calls)
		self.assertEqual(1, window._widget.show_calls)

	def test_reset_window_geometry_clears_settings_and_resizes_window(self):
		settings = _Settings({
			'window_geometry': 'geometry',
			'window_state': 'state',
			'panes': [{}, {}]
		})
		window = _Window()
		manager = SessionManager(settings, None, None, '1.7.5', True)

		manager.reset_window_geometry(window)

		self.assertNotIn('window_geometry', settings)
		self.assertNotIn('window_state', settings)
		self.assertIn('panes', settings)
		self.assertEqual(1, settings.flush_calls)
		self.assertEqual([(1280, 800)], window.reset_geometry_calls)


class _Window:
	def __init__(self):
		self._widget = _MainWindow()
		self.reset_geometry_calls = []

	def add_pane(self):
		return object()

	def reset_geometry(self, width, height):
		self.reset_geometry_calls.append((width, height))


class _Settings(dict):
	def __init__(self, values):
		super().__init__(values)
		self.flush_calls = 0

	def flush(self):
		self.flush_calls += 1


class _MainWindow:
	def __init__(self):
		self.resize_calls = []
		self.show_calls = 0
		self.show_maximized_calls = 0
		self.restored_geometries = []
		self.restored_states = []

	def resize(self, width, height):
		self.resize_calls.append((width, height))

	def show(self):
		self.show_calls += 1

	def showMaximized(self):
		self.show_maximized_calls += 1

	def restoreGeometry(self, geometry):
		self.restored_geometries.append(geometry)

	def restoreState(self, state, version):
		self.restored_states.append((state, version))

	def show_status_message(self, text, timeout_secs=None):
		pass
