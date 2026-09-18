from contextlib import contextmanager
from process_pane.processes import ProcessError, ProcessProvider, ProcessRecord, Snapshot, WindowsApi, get_provider
from unittest import TestCase, skipUnless
from unittest.mock import Mock, patch

import os
import subprocess
import sys


class SnapshotTest(TestCase):
	def test_large_snapshot_is_replaced_and_unicode_names_preserved(self):
		snapshot = Snapshot()
		records = [ProcessRecord(pid, 'report\u00e9.exe', pid + 1) for pid in range(10000)]
		provider = Mock(return_value=records)
		paths = snapshot.refresh(provider)
		self.assertEqual(10000, len(paths))
		self.assertEqual(list(range(10000)), [snapshot.get(path).pid for path in paths])
		self.assertIn('report\u00e9.exe', paths[0])
		provider.assert_called_once_with()
		self.assertEqual((), snapshot.refresh(lambda: []))
		self.assertEqual({}, snapshot._records)

	def test_reused_pid_never_resolves_old_row(self):
		snapshot = Snapshot()
		old = ProcessRecord(123, 'application.exe', 100)
		old_path, = snapshot.refresh(lambda: [old])
		new = ProcessRecord(123, 'application.exe', 200)
		new_path, = snapshot.refresh(lambda: [new])
		self.assertNotEqual(old_path, new_path)
		with self.assertRaises(FileNotFoundError):
			snapshot.get(old_path)
		self.assertEqual(new, snapshot.get(new_path))

	def test_names_and_unknown_identities(self):
		snapshot = Snapshot()
		records = [ProcessRecord(1, 'a/b\\c~d\x00', None), ProcessRecord(2, '..', 12)]
		paths = snapshot.refresh(lambda: records)
		self.assertEqual(('a_b_c_d_~1~unknown-1', 'Process~2~c'), paths)
		updated = snapshot.refresh(lambda: records)
		self.assertNotEqual(paths[0], updated[0])
		self.assertEqual(paths[1], updated[1])

	def test_queries_do_not_scan_and_refresh_replaces_snapshot(self):
		snapshot = Snapshot()
		provider = Mock(return_value=[ProcessRecord(10, 'test.exe', 99)])
		path, = snapshot.refresh(provider)
		for iteration in range(100):
			self.assertEqual(10, snapshot.get(path).pid)
		provider.assert_called_once_with()
		self.assertEqual((), snapshot.refresh(lambda: []))
		for invalid in (path, '', '../test', 'test/child'):
			with self.assertRaises(FileNotFoundError):
				snapshot.get(invalid)


def windows_error(code):
	error = OSError('Windows error %d' % code)
	error.winerror = code
	return error


class ProviderTest(TestCase):
	def setUp(self):
		self.handle = object()
		self.closed = []
		@contextmanager
		def opened(pid, access):
			try:
				yield self.handle
			finally:
				self.closed.append(self.handle)
		self.api = Mock()
		self.api.open.side_effect = opened
		self.api.creation_time.return_value = 100
		self.api.image_name.return_value = 'C:\\Apps\\application.exe'
		self.api.is_critical.return_value = False
		self.enumerate_pids = Mock(return_value=[123])
		self.provider = ProcessProvider(self.enumerate_pids, self.api)
		self.record = ProcessRecord(123, 'application.exe', 100)

	def test_name_and_identity_use_same_handle(self):
		self.assertEqual([self.record], list(self.provider.snapshot()))
		self.api.open.assert_called_once_with(123, 0x1000)
		self.api.creation_time.assert_called_once_with(self.handle)
		self.api.image_name.assert_called_once_with(self.handle)
		self.assertEqual([self.handle], self.closed)

	def test_idle_process_is_listed_without_opening_a_handle(self):
		self.enumerate_pids.return_value = [0, 4]
		def denied(pid, access):
			raise windows_error(87 if pid == 0 else 5)
		self.api.open.side_effect = denied
		self.assertEqual([
			ProcessRecord(0, 'System Idle Process', None),
			ProcessRecord(4, 'System', None),
		], list(self.provider.snapshot()))
		self.api.open.assert_called_once_with(4, 0x1000)

	def test_denied_details_are_restricted_and_exited_rows_skipped(self):
		for code, expected in ((5, [ProcessRecord(123, 'Unavailable', None)]), (87, [])):
			with self.subTest(code=code):
				self.api.open.side_effect = windows_error(code)
				self.assertEqual(expected, list(self.provider.snapshot()))

	def test_termination_uses_verified_handle_and_closes_it(self):
		check = Mock()
		self.provider.end(self.record, check)
		self.api.open.assert_called_once_with(123, 0x1001)
		self.api.creation_time.assert_called_once_with(self.handle)
		self.api.is_critical.assert_called_once_with(self.handle)
		check.assert_called_once_with()
		self.api.terminate.assert_called_once_with(self.handle)
		self.assertEqual([self.handle], self.closed)

	def test_self_system_unknown_and_stale_are_refused(self):
		for record in (ProcessRecord(0, 'idle', 100), ProcessRecord(4, 'system', 100), ProcessRecord(os.getpid(), 'self', 100), ProcessRecord(123, 'unknown', None)):
			with self.assertRaises(ProcessError):
				self.provider.end(record, Mock())
		self.api.open.assert_not_called()
		self.api.creation_time.return_value = 200
		with self.assertRaisesRegex(ProcessError, 'changed'):
			self.provider.end(self.record, Mock())
		self.api.terminate.assert_not_called()
		self.assertEqual([self.handle], self.closed)

	def test_critical_or_uncheckable_process_is_refused(self):
		for result in (True, windows_error(5)):
			self.api.is_critical.side_effect = [result]
			with self.assertRaises(ProcessError):
				self.provider.end(self.record, Mock())
		self.api.terminate.assert_not_called()
		self.assertEqual([self.handle, self.handle], self.closed)

	def test_cancellation_immediately_before_termination_closes_handle(self):
		with self.assertRaises(KeyboardInterrupt):
			self.provider.end(self.record, Mock(side_effect=KeyboardInterrupt))
		self.api.terminate.assert_not_called()
		self.assertEqual([self.handle], self.closed)

	def test_failures_are_actionable_and_handles_close(self):
		for code, message in ((5, 'Access denied.*may already be exiting.*Refresh'), (87, 'already exited'), (6, 'Could not end')):
			self.api.terminate.side_effect = windows_error(code)
			with self.assertRaisesRegex(ProcessError, message):
				self.provider.end(self.record, Mock())
		self.assertEqual([self.handle] * 3, self.closed)

	def test_native_handle_closes_on_exception(self):
		api = WindowsApi.__new__(WindowsApi)
		api.kernel = Mock()
		api.kernel.OpenProcess.return_value = self.handle
		with self.assertRaises(ValueError):
			with api.open(123, 0x1000) as handle:
				self.assertIs(self.handle, handle)
				raise ValueError('test')
		api.kernel.CloseHandle.assert_called_once_with(self.handle)


class ProviderCompatibilityTest(TestCase):
	def test_missing_process_safety_api_is_actionable(self):
		get_provider.cache_clear()
		self.addCleanup(get_provider.cache_clear)
		kernel = Mock(spec=[
			'OpenProcess', 'CloseHandle', 'GetProcessTimes',
			'QueryFullProcessImageNameW', 'TerminateProcess',
		])
		with patch('process_pane.processes.sys.platform', 'win32'), \
			patch.dict(sys.modules, {'win32process': Mock()}), \
			patch('ctypes.WinDLL', return_value=kernel, create=True):
			with self.assertRaisesRegex(ProcessError, 'Windows 8.1.*IsProcessCritical'):
				get_provider()
		kernel.OpenProcess.assert_not_called()
		kernel.TerminateProcess.assert_not_called()


class PaneCommandTest(TestCase):
	def setUp(self):
		import process_pane
		self.plugin = process_pane
		self.pane = Mock()
		self.pane.get_path.return_value = process_pane.ROOT
		self.pane.get_selected_files.return_value = []
		self.record = ProcessRecord(123, 'application.exe', 100)
		self.url = process_pane.ROOT + self.record.path(1)
		self.pane.get_file_under_cursor.return_value = self.url
		self.provider = Mock()
		for name, options in (
			('get_provider', {'return_value': self.provider}),
			('query', {'return_value': self.record}),
			('show_alert', {'return_value': process_pane.NO}),
			('show_status_message', {}),
			('submit_task', {'side_effect': lambda task: task()}),
		):
			patcher = patch('process_pane.' + name, **options)
			patcher.start()
			self.addCleanup(patcher.stop)

	def test_default_no_and_cancel_does_nothing(self):
		self.plugin.EndProcess(self.pane)()
		self.assertEqual((self.plugin.YES | self.plugin.NO, self.plugin.NO), self.plugin.show_alert.call_args.args[1:])
		self.assertIn('PID 123', self.plugin.show_alert.call_args.args[0])
		self.plugin.submit_task.assert_not_called()
		self.provider.end.assert_not_called()
		self.pane.reload.assert_not_called()

	def test_confirmation_preserves_plain_process_name_and_line_breaks(self):
		self.plugin.query.return_value = ProcessRecord(123, 'Research & Development.exe', 100)
		self.plugin.EndProcess(self.pane)()
		self.plugin.show_alert.assert_called_once_with(
			'End process "Research & Development.exe" (PID 123)?\n\nForce termination may lose unsaved data. Child processes will not be ended.',
			self.plugin.YES | self.plugin.NO, self.plugin.NO
		)
		self.provider.end.assert_not_called()

	def test_confirm_uses_captured_record_and_only_reloads_current_pane(self):
		def confirm(*args):
			self.pane.get_file_under_cursor.return_value = 'process://different~321~200'
			return self.plugin.YES
		self.plugin.show_alert.side_effect = confirm
		self.plugin.EndProcess(self.pane)()
		self.assertEqual(self.record, self.provider.end.call_args.args[0])
		self.plugin.show_status_message.assert_called_once_with(
			'Termination requested for application.exe (PID 123).', timeout_secs=5
		)
		self.pane.reload.assert_called_once()
		self.pane.window.get_panes.assert_not_called()

	def test_navigation_away_during_confirmation_is_not_reversed(self):
		def confirm(*args):
			self.pane.get_path.return_value = 'file://C:/'
			return self.plugin.YES
		self.plugin.show_alert.side_effect = confirm
		self.plugin.EndProcess(self.pane)()
		self.provider.end.assert_called_once()
		self.pane.reload.assert_not_called()
		self.pane.set_path.assert_not_called()

	def test_explicit_target_and_invalid_multiple_or_root_targets(self):
		self.plugin.EndProcess(self.pane)(urls=[self.url])
		self.plugin.query.assert_called_once_with(self.url, 'process_record')
		self.plugin.query.reset_mock()
		for urls in ([], [self.url, self.url], ['file://C:/a'], ['process://'], self.url):
			self.plugin.EndProcess(self.pane)(urls=urls)
		self.plugin.query.assert_not_called()
		self.provider.end.assert_not_called()

	def test_denied_and_stale_targets(self):
		self.plugin.show_alert.return_value = self.plugin.YES
		self.provider.end.side_effect = ProcessError('Access denied')
		self.plugin.EndProcess(self.pane)()
		self.plugin.show_alert.assert_called_with('Access denied')
		self.plugin.show_status_message.assert_not_called()
		self.plugin.query.side_effect = FileNotFoundError('Refresh the list')
		self.plugin.submit_task.reset_mock()
		self.plugin.EndProcess(self.pane)()
		self.plugin.submit_task.assert_not_called()

	def test_delete_rewrite_preserves_args_and_other_panes(self):
		listener = self.plugin.ProcessPaneListener(self.pane)
		args = {'urls': [self.url]}
		for command in ('move_to_trash', 'delete_permanently'):
			self.assertEqual(('end_process', args), listener.on_command(command, args))
		self.assertIsNone(listener.on_command('end_process', args))
		self.pane.get_path.return_value = 'file://C:/'
		self.assertIsNone(listener.on_command('move_to_trash', args))
		self.assertFalse(self.plugin.EndProcess(self.pane).is_visible())
		self.plugin.EndProcess(self.pane)()
		self.plugin.get_provider.assert_not_called()

	def test_transfer_interception_from_both_panes_and_drop(self):
		other = Mock()
		other.get_path.return_value = 'file://C:/'
		self.pane.window.get_panes.return_value = [self.pane, other]
		listener = self.plugin.ProcessPaneListener(self.pane)
		for command in ('copy', 'move'):
			self.assertEqual(('process_operation_unsupported', {}), listener.on_command(command, {}))
		self.pane.get_path.return_value = 'file://C:/'
		other.get_path.return_value = self.plugin.ROOT
		self.assertEqual(('process_operation_unsupported', {}), listener.on_command('copy', {}))
		other.get_path.return_value = 'file://D:/'
		self.assertIsNone(listener.on_command('copy', {}))
		self.assertEqual(('process_operation_unsupported', {}), listener.on_command('move', {'files': ['file://C:/a'], 'dest_dir': self.plugin.ROOT}))
		self.provider.assert_not_called()

	def test_show_refresh_and_missing_dependency(self):
		self.plugin.ShowProcesses(self.pane)()
		self.pane.reload.assert_called_once()
		self.pane.get_path.return_value = 'file://C:/'
		self.plugin.ShowProcesses(self.pane)()
		self.pane.set_path.assert_called_once_with(self.plugin.ROOT)
		self.plugin.get_provider.side_effect = ProcessError('Missing pywin32')
		self.pane.set_path.reset_mock()
		self.plugin.ShowProcesses(self.pane)()
		self.plugin.show_alert.assert_called_with('Missing pywin32')
		self.pane.set_path.assert_not_called()


class FilesystemTest(TestCase):
	def test_flat_listing_columns_and_no_generic_destruction(self):
		from process_pane import Processes, Pid
		filesystem = Processes()
		provider = Mock()
		provider.snapshot.return_value = [ProcessRecord(123, 'report.exe', 100)]
		with patch('process_pane.get_provider', return_value=provider):
			self.assertTrue(filesystem.is_dir(''))
			provider.snapshot.assert_not_called()
			path, = filesystem.iterdir('')
			self.assertEqual('report.exe', filesystem.name(path))
			self.assertFalse(filesystem.is_dir(path))
			self.assertEqual('process://' + path, filesystem.resolve(path))
			self.assertEqual(('core.Name', 'process_pane.Pid'), filesystem.get_default_columns(''))
			with patch('process_pane.query', return_value=filesystem.process_record(path)):
				self.assertEqual(123, Pid().get_sort_value('process://' + path))
				self.assertEqual('123', Pid().get_str('process://' + path))
			with self.assertRaises(NotADirectoryError):
				filesystem.iterdir(path)
			for method in (filesystem.delete, filesystem.prepare_delete, filesystem.move_to_trash, filesystem.prepare_trash, filesystem.mkdir, filesystem.touch):
				with self.assertRaises(NotImplementedError):
					method(path)
			provider.snapshot.assert_called_once()
			provider.end.assert_not_called()


@skipUnless(sys.platform == 'win32', 'Windows process handles required')
class NativeProcessTest(TestCase):
	def test_owned_child_enumeration_identity_and_termination(self):
		import ctypes
		if ctypes.windll.shell32.IsUserAnAdmin():
			self.skipTest('Standard-user termination must be tested from a non-elevated process')
		child = subprocess.Popen(
			[sys.executable, '-c', 'import sys; sys.stdin.buffer.read(1)'],
			stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
		)
		try:
			provider = get_provider()
			record = next(record for record in provider.snapshot() if record.pid == child.pid)
			self.assertIsNotNone(record.created)
			self.assertTrue(record.name.lower().endswith('.exe'))
			with self.assertRaisesRegex(ProcessError, 'changed'):
				provider.end(ProcessRecord(record.pid, record.name, record.created + 1), lambda: None)
			self.assertIsNone(child.poll())
			provider.end(record, lambda: None)
			self.assertEqual(1, child.wait(timeout=5))
		finally:
			if child.poll() is None:
				child.terminate()
				child.wait(timeout=5)
			child.stdin.close()

	def test_no_native_import_or_scan_until_used(self):
		check = subprocess.run(
			[sys.executable, '-c', 'import sys; import process_pane; assert "win32process" not in sys.modules; filesystem = process_pane.Processes(); assert filesystem.exists(""); assert not filesystem.exists("old~123~1"); assert "win32process" not in sys.modules'],
			capture_output=True, text=True, timeout=10
		)
		self.assertEqual(0, check.returncode, check.stderr)