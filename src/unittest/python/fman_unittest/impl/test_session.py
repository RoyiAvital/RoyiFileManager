from unittest import TestCase
from unittest.mock import Mock, patch

from fman.impl.session import SessionManager, _encode
from fman.impl.util.settings import Settings
from pathlib import Path
from tempfile import TemporaryDirectory

import json


class SettingsSafetyTest(TestCase):
	def test_pretty_nested_settings_round_trip(self):
		value = {'window': {'size': [1280, 800], 'title': 'caf\u00e9'},
			'panes': [{'location': 'file://C:/Work', 'hidden': False}], 'optional': None}
		with TemporaryDirectory() as directory:
			path = Path(directory, 'Session.json')
			path.write_text(json.dumps(value), encoding='utf-8')
			settings = Settings(path)
			settings.flush()
			self.assertEqual(json.dumps(value, indent=2) + '\n', path.read_text(encoding='utf-8'))
			restarted = Settings(path)
			for key, expected in value.items():
				self.assertEqual(expected, restarted.get(key, None))
			restarted.flush()
			self.assertEqual(json.dumps(value, indent=2) + '\n', path.read_text(encoding='utf-8'))
			self.assertEqual([path], list(Path(directory).iterdir()))

	def test_unknown_link_count_allows_settings_save(self):
		from types import SimpleNamespace
		with TemporaryDirectory() as directory:
			path = Path(directory, 'settings.json')
			path.write_text('{"saved": 1}')
			settings = Settings(path)
			settings['saved'] = 2
			metadata = SimpleNamespace(st_mode=path.stat().st_mode, st_nlink=0)
			with patch('fman.impl.util.settings.os.lstat', return_value=metadata):
				settings.flush()
			self.assertEqual(2, Settings(path).get('saved', None))
			self.assertEqual([path], list(Path(directory).iterdir()))

	def test_hardlinked_settings_are_not_replaced(self):
		import os
		with TemporaryDirectory() as directory:
			path, alias = Path(directory, 'settings.json'), Path(directory, 'alias.json')
			path.write_text('{"saved": 1}')
			os.link(path, alias)
			settings = Settings(path)
			settings['saved'] = 2
			with self.assertRaises(OSError):
				settings.flush()
			self.assertTrue(os.path.samefile(path, alias))
			self.assertEqual('{"saved": 1}', alias.read_text())
	def test_failed_serialization_and_replace_preserve_old_json(self):
		for serialize_failure in (False, True):
			with self.subTest(serialize_failure=serialize_failure), TemporaryDirectory() as directory:
				path = Path(directory, 'settings.json')
				path.write_text('{"saved": 1}')
				settings = Settings(path)
				settings['new'] = object() if serialize_failure else 2
				with patch('fman.impl.util.settings.os.replace', side_effect=PermissionError('locked')):
					with self.assertRaises((TypeError, PermissionError)):
						settings.flush()
				self.assertEqual('{"saved": 1}', path.read_text())
				self.assertEqual([path], list(Path(directory).iterdir()))
	def test_non_object_roots_reset_and_round_trip(self):
		for root in ('[]', 'null', '42', '"text"'):
			with self.subTest(root=root), TemporaryDirectory() as directory:
				path = Path(directory, 'settings.json')
				path.write_text(root)
				settings = Settings(path)
				self.assertIsNone(settings.get('missing', None))
				settings['saved'] = 1
				settings.flush()
				self.assertEqual(1, Settings(path).get('saved', None))


class SessionManagerWindowTest(TestCase):
	def test_linked_settings_save_failure_is_reported_once(self):
		import os
		with TemporaryDirectory() as directory:
			path, alias = Path(directory, 'Session.json'), Path(directory, 'alias.json')
			path.write_text('{}')
			os.link(path, alias)
			errors = Mock()
			manager = SessionManager(Settings(path), Mock(), errors, 'test', True)
			window = Mock()
			window.saveGeometry.return_value = b'geometry'
			window.saveState.return_value = b'state'
			window.get_panes.return_value = []
			manager.reset_window_geometry(window)
			manager.on_close(window)
			manager.on_close(window)
			errors.report.assert_called_once()
			self.assertIn('Session state could not be saved', errors.report.call_args.args[0])
			self.assertIn('linked settings', errors.report.call_args.args[0])
			self.assertEqual({'exc': False}, errors.report.call_args.kwargs)
			self.assertTrue(os.path.samefile(path, alias))
			self.assertEqual('{}', alias.read_text())
			self.assertEqual({path, alias}, set(Path(directory).iterdir()))

	def test_named_widths_and_legacy_widths_are_forwarded(self):
		manager = SessionManager({}, Mock(), Mock(), 'test', True)
		for named in (None, {'core.Name': 181, 'core.Size': 91}):
			with self.subTest(named=named):
				pane = Mock()
				settings = {'location': 'file://C:/', 'col_widths': [171, 83]}
				if named is not None:
					settings['column_widths_by_name'] = named
				manager._init_pane(pane, None, settings)
				pane._widget.restore_column_widths.assert_called_once_with(named, [171, 83])

	def test_startup_version_messages_and_persistence(self):
		version = '0.3.0'
		for key, previous_version in (
			(None, None), ('app_version', version),
			('app_version', '0.2.2'), ('fman_version', '1.7.5')
		):
			with self.subTest(key=key, previous_version=previous_version):
				settings = _Settings({})
				if key is not None:
					settings[key] = previous_version
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
				self.assertEqual(version, settings['app_version'])
				self.assertNotIn('fman_version', settings)
				self.assertEqual(1, settings.flush_calls)
				restored = SessionManager(settings, None, None, version, True)
				window.show_status_message.reset_mock()
				restored._show_startup_messages(window)
				window.show_status_message.assert_called_once_with(
					'v%s ready.' % version, timeout_secs=5
				)

	def test_current_app_version_takes_precedence_over_legacy_value(self):
		settings = _Settings({
			'app_version': '0.3.0',
			'fman_version': '1.7.5'
		})
		manager = SessionManager(settings, None, None, '0.3.0', True)
		window = Mock()

		manager._show_startup_messages(window)

		window.show_status_message.assert_called_once_with(
			'v0.3.0 ready.', timeout_secs=5
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

	def test_reset_window_geometry_survives_close_and_restart(self):
		settings = _Settings({
			'window_geometry': _encode(b'previous position'),
			'window_state': _encode(b'previous state'),
			'panes': [{}, {}]
		})
		manager = SessionManager(settings, None, None, 'test', True)
		window = Mock()
		window._widget.saveGeometry.return_value = b'previous position'
		window._widget.saveState.return_value = b'previous state'
		window._widget.get_panes.return_value = []

		manager.reset_window_geometry(window)
		manager.on_close(window._widget)

		self.assertNotIn('window_geometry', settings)
		self.assertNotIn('window_state', settings)
		self.assertEqual('test', settings['app_version'])
		self.assertEqual(2, settings.flush_calls)
		restarted = _Window()
		with patch('fman.impl.session.Thread'):
			SessionManager(settings, None, None, 'test', True).show_main_window(restarted)
		self.assertEqual([], restarted._widget.restored_geometries)
		self.assertEqual([], restarted._widget.restored_states)
		self.assertEqual([(1280, 800)], restarted._widget.resize_calls)

	def test_existing_session_without_geometry_uses_default_size(self):
		window = _Window()
		manager = SessionManager({'panes': [{}, {}]}, None, None, 'test', True)

		with patch('fman.impl.session.Thread'):
			manager.show_main_window(window)

		self.assertEqual([(1280, 800)], window._widget.resize_calls)
		self.assertEqual([], window._widget.restored_geometries)
		self.assertEqual(1, window._widget.show_calls)


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
