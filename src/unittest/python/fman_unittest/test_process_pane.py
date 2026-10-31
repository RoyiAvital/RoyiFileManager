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
		with patch.dict(sys.modules, {'win32process': Mock()}), \
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

	def test_show_os_processes_label_preserves_command_id(self):
		from fman.impl.plugins.command_registry import PaneCommandRegistry
		from fman.impl.plugins.plugin import _get_command_name
		command_name = _get_command_name(self.plugin.ShowProcesses)
		self.assertEqual('show_processes', command_name)
		registry = PaneCommandRegistry(Mock(), Mock())
		registry.register_command(command_name, self.plugin.ShowProcesses)
		self.assertEqual(("Show OS' processes",), registry.get_command_aliases('show_processes'))

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
			listing = filesystem.scan('', Mock())
			self.assertEqual(('report.exe',), listing.display_names)
			self.assertEqual((123,), Pid().keys(listing, True))
			self.assertEqual((123,), Pid().keys(listing, False))
			self.assertEqual('123', Pid().text(listing, 0))
			with self.assertRaises(NotADirectoryError):
				filesystem.iterdir(path)
			for method in (filesystem.delete, filesystem.prepare_delete, filesystem.move_to_trash, filesystem.prepare_trash, filesystem.mkdir, filesystem.touch):
				with self.assertRaises(NotImplementedError):
					method(path)
			self.assertEqual(2, provider.snapshot.call_count)
			provider.end.assert_not_called()


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


class LockFinderTest(TestCase):
	def setUp(self):
		from pathlib import Path
		from tempfile import TemporaryDirectory
		import _winapi
		temporary = TemporaryDirectory()
		self.addCleanup(temporary.cleanup)
		self.root = Path(temporary.name).resolve() / 'chosen'
		for relative in ('a.txt', 'sub/b.txt', 'sub/deep/c.txt', '../outside/o.txt'):
			path = self.root / relative
			path.parent.mkdir(parents=True, exist_ok=True)
			path.write_text(relative)
		self.junction = self.root / 'link'
		_winapi.CreateJunction(str(self.root.parent / 'outside'), str(self.junction))
		self.addCleanup(lambda: self.junction.exists() and os.rmdir(self.junction))

	def test_folder_walk_skips_junction_contents_and_counts_failures(self):
		from process_pane import locks
		queried = []
		def query(path):
			queried.append(path)
			if path.endswith('b.txt'):
				raise PermissionError(5, 'Access is denied')
			return (7,) if path.endswith(('c.txt', 'chosen')) else ()
		progress, check = Mock(), Mock()
		usage = locks.find(str(self.root), check, progress, query)
		self.assertEqual([(str(self.root), (7,)), (str(self.root / 'sub/deep/c.txt'), (7,))], sorted(usage.items))
		self.assertEqual((7, 1, True), (usage.checked, usage.failed, usage.complete))
		self.assertIn(str(self.junction), queried)
		self.assertFalse(any('outside' in path or path.startswith(str(self.junction) + os.sep) for path in queried))
		self.assertEqual(9, check.call_count)

	def test_item_limit_root_errors_and_cancellation(self):
		from process_pane import locks
		with patch.object(locks, 'MAX_ITEMS', 3):
			usage = locks.find(str(self.root), query=lambda path: ())
		self.assertEqual((3, False), (usage.checked, usage.complete))
		file_usage = locks.find(str(self.root / 'a.txt'), query=lambda path: (9,))
		self.assertEqual([(str(self.root / 'a.txt'), (9,))], file_usage.items)
		with self.assertRaises(FileNotFoundError):
			locks.find(str(self.root / 'missing.txt'), query=locks.process_ids)
		with self.assertRaises(KeyboardInterrupt):
			locks.find(str(self.root), Mock(side_effect=KeyboardInterrupt), query=lambda path: ())

	def test_retained_matches_are_bounded_while_the_scan_continues(self):
		from process_pane import locks
		for limits in ({'MAX_RESULT_ROWS': 2}, {'MAX_RESULT_BYTES': 1}):
			with self.subTest(limits=limits), patch.multiple(locks, **limits):
				usage = locks.find(str(self.root), query=lambda path: (11, 12))
			self.assertTrue(usage.complete)
			self.assertTrue(usage.limited)
			self.assertEqual(7, usage.checked)
			retained = sum(len(ids) for path, ids in usage.items)
			self.assertEqual(2 if 'MAX_RESULT_ROWS' in limits else 0, retained)

	def test_single_file_cancellation_prevents_or_discards_the_query(self):
		from fman import Task
		from process_pane import locks
		query = Mock(return_value=(9,))
		with self.assertRaises(Task.Canceled):
			locks.find(str(self.root / 'a.txt'), Mock(side_effect=Task.Canceled), query=query)
		query.assert_not_called()
		with self.assertRaises(Task.Canceled):
			locks.find(str(self.root / 'a.txt'), Mock(side_effect=[None, Task.Canceled()]), query=query)
		query.assert_called_once()

	def test_cancellation_during_describe_stops_remaining_processes(self):
		from fman import Task
		from process_pane import locks
		opened = []
		api = Mock()
		@contextmanager
		def open_process(pid, access):
			opened.append(pid)
			yield pid
		def check():
			if opened:
				raise Task.Canceled()
		api.open.side_effect = open_process
		api.image_name.return_value = 'C:\\Apps\\editor.exe'
		with self.assertRaises(Task.Canceled):
			locks.describe((11, 12, 13), api, check)
		self.assertEqual([11], opened)

	def test_describe_names_programs_and_denied_processes(self):
		from process_pane import locks
		api = Mock()
		@contextmanager
		def opened(pid, access):
			self.assertEqual(0x1000, access)
			if pid != 12:
				raise windows_error(5)
			yield 'handle'
		api.open.side_effect = opened
		api.image_name.return_value = 'C:\\Apps\\editor.exe'
		self.assertEqual({12: ('editor.exe', 'C:\\Apps\\editor.exe'), 4: ('System', ''), 99: ('Unavailable', '')},
			locks.describe((12, 4, 99), api))


class NativeLockTest(TestCase):
	def test_regular_user_query_finds_exclusive_file_working_folder_and_executable(self):
		from pathlib import Path
		from process_pane import locks
		from tempfile import TemporaryDirectory
		with TemporaryDirectory() as temporary:
			root = Path(temporary).resolve()
			folder = root / 'work'
			folder.mkdir()
			locked, free = folder / 'locked.txt', root / 'free.txt'
			locked.write_text('x')
			free.write_text('x')
			# Share mode 0: other programs cannot open, rename or delete the file.
			child = subprocess.Popen([sys.executable, '-c', 'import _winapi, sys; '
				'_winapi.CreateFile(sys.argv[1], 0x80000000, 0, 0, 3, 0, 0); print("ready", flush=True); sys.stdin.read(1)',
				str(locked)], cwd=folder, stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True)
			try:
				self.assertEqual('ready', child.stdout.readline().strip())
				self.assertIn(child.pid, locks.process_ids(str(locked)))
				self.assertEqual((), locks.process_ids(str(free)))
				self.assertIn(os.getpid(), locks.process_ids(sys.executable))
				usage = locks.find(str(root))
				found = {path: ids for path, ids in usage.items}
				self.assertIn(child.pid, found[str(folder)])
				self.assertIn(child.pid, found[str(locked)])
				self.assertNotIn(str(free), found)
				self.assertEqual((0, True), (usage.failed, usage.complete))
				name, program = locks.describe((child.pid,), WindowsApi())[child.pid]
				self.assertEqual(os.path.basename(program), name)
				self.assertTrue(name.lower().endswith('.exe'))
			finally:
				child.kill()
				child.wait(timeout=5)
				child.stdin.close()
				child.stdout.close()

	def test_delete_sharing_user_does_not_prevent_rename_or_delete(self):
		from pathlib import Path
		from process_pane import locks
		from tempfile import TemporaryDirectory
		with TemporaryDirectory() as temporary:
			source = Path(temporary).resolve() / 'shared.txt'
			destination = source.with_name('renamed.txt')
			source.write_bytes(b'shared fixture')
			script = ('import _winapi, sys; handle = _winapi.CreateFile(sys.argv[1], '
				'0x80000000, 7, 0, 3, 0, 0); print("ready", flush=True); '
				'sys.stdin.read(1); _winapi.CloseHandle(handle)')
			child = subprocess.Popen([sys.executable, '-c', script, str(source)],
				stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True)
			try:
				self.assertEqual('ready', child.stdout.readline().strip())
				self.assertIn(child.pid, locks.process_ids(str(source)))
				source.rename(destination)
				destination.unlink()
				self.assertFalse(source.exists() or destination.exists())
			finally:
				child.kill()
				child.wait(timeout=5)
				child.stdin.close()
				child.stdout.close()


class FindLockingProcessesTest(TestCase):
	def setUp(self):
		import process_pane
		from process_pane.locks import Usage
		self.plugin = process_pane
		self.Usage = Usage
		self.pane = Mock()
		self.pane.get_path.return_value = 'file://C:/work'
		self.pane.get_selected_files.return_value = ['file://C:/work/report.docx']
		self.pane.get_file_under_cursor.return_value = None
		def submit(task):
			try:
				task()
			except process_pane.Task.Canceled:
				pass
		for name, options in (
			('show_alert', {}), ('show_status_message', {}), ('show_quick_table', {}),
			('submit_task', {'side_effect': submit}), ('WindowsApi', {}),
			('locks.find', {}), ('locks.describe', {}),
		):
			patcher = patch('process_pane.' + name, **options)
			patcher.start()
			self.addCleanup(patcher.stop)
		self.find, self.describe = process_pane.locks.find, process_pane.locks.describe

	def run_command(self):
		self.plugin.FindLockingProcesses(self.pane)()

	def test_visibility_and_selection_guard(self):
		command = self.plugin.FindLockingProcesses(self.pane)
		self.assertTrue(command.is_visible())
		self.pane.get_selected_files.return_value = ['file://C:/work/a', 'file://C:/work/b']
		self.assertFalse(command.is_visible())
		for selected in ([], ['file://C:/work/a', 'file://C:/work/b']):
			self.pane.get_selected_files.return_value = selected
			self.plugin.show_status_message.reset_mock()
			self.run_command()
			self.plugin.show_status_message.assert_called_once_with(
				'Find blocking processes: choose one local file or folder.', timeout_secs=5)
		self.pane.get_path.return_value = 'process://'
		self.pane.get_selected_files.return_value = ['process://editor.exe~12~1']
		self.assertFalse(command.is_visible())
		self.run_command()
		self.plugin.submit_task.assert_not_called()
		self.find.assert_not_called()

	def test_unused_item_cancellation_and_errors(self):
		self.find.return_value = self.Usage(checked=1)
		self.run_command()
		self.assertEqual(os.path.normpath('C:/work/report.docx'), self.find.call_args.args[0])
		self.plugin.show_alert.assert_called_once_with('No process is using "report.docx".')
		self.describe.assert_not_called()
		self.plugin.show_alert.reset_mock()
		self.find.return_value = self.Usage(checked=40, failed=2, complete=False)
		self.run_command()
		self.assertEqual('No process is using "report.docx".\n\n2 items or folders could not be checked.'
			'\n\nStopped after 40 items; the rest of the folder was not checked.', self.plugin.show_alert.call_args.args[0])
		self.find.side_effect = FileNotFoundError(2, 'The system cannot find the file specified')
		self.run_command()
		self.plugin.show_alert.assert_called_with('Could not check "report.docx": The system cannot find the file specified')
		self.find.side_effect = self.plugin.Task.Canceled()
		self.run_command()
		self.plugin.show_status_message.assert_called_once_with('Find blocking processes cancelled.', timeout_secs=5)
		self.plugin.show_quick_table.assert_not_called()

	def test_users_are_listed_per_item_with_navigable_paths(self):
		self.pane.get_selected_files.return_value = ['file://C:/work']
		inner = os.path.normpath('C:/work/sub/data.db')
		self.find.return_value = self.Usage([(os.path.normpath('C:/work'), (30,)), (inner, (12, 30))], checked=5, failed=1)
		self.describe.return_value = {12: ('editor.exe', 'C:\\Apps\\editor.exe'), 30: ('Unavailable', '')}
		self.run_command()
		self.assertEqual({12, 30}, set(self.describe.call_args.args[0]))
		arguments = self.plugin.show_quick_table.call_args.kwargs
		self.assertEqual(('Processes using work', '2 processes \u00b7 5 items checked \u00b7 1 could not be checked'
			' \u00b7 Users may not block rename or delete', False),
			(arguments['title'], arguments['summary'], arguments['truncated']))
		self.assertIs(self.pane, arguments['pane'])
		self.assertEqual(['Process', 'PID', 'Item', 'Program'], [column.label for column in arguments['columns']])
		self.assertEqual([
			(('editor.exe', 12, os.path.join('work', 'sub', 'data.db'), 'C:\\Apps\\editor.exe'), (None, None, inner, 'C:\\Apps\\editor.exe')),
			(('Unavailable', 30, 'work', ''), (None, None, os.path.normpath('C:/work'), None)),
			(('Unavailable', 30, os.path.join('work', 'sub', 'data.db'), ''), (None, None, inner, None)),
		], [(row.cells, row.targets) for row in arguments['rows']])
		from fman.impl.ui.table_data import TableSchema
		shown = TableSchema(arguments['columns']).snapshot(arguments['rows'])
		self.assertEqual(['12', '30', '30'], [row.cells[1] for row in shown])

	def test_result_rows_are_bounded_before_construction(self):
		usage = self.Usage([(os.path.normpath('C:/work/file.txt'), tuple(range(5)))], checked=1)
		processes = {pid: ('Worker', '') for pid in range(5)}
		constructor = self.plugin.QuickTableRow
		with patch.object(self.plugin, '_MAX_ROWS', 2), \
				patch.object(self.plugin, 'QuickTableRow', wraps=constructor) as make_row:
			rows, truncated = self.plugin._rows(usage, processes, os.path.normpath('C:/work'))
		self.assertEqual(2, len(rows))
		self.assertEqual(2, make_row.call_count)
		self.assertTrue(truncated)

	def test_long_result_paths_fit_the_table_payload_budget(self):
		from fman.impl.ui.table_data import TableSchema
		root = os.path.normpath('C:/work')
		prefix = os.path.join(root, *('folder-%03d' % index for index in range(220)))
		usage = self.Usage([(os.path.join(prefix, 'item-%05d.txt' % index), (11,))
			for index in range(5000)], checked=5000)
		rows, truncated = self.plugin._rows(usage, {11: ('Worker', '')}, root)
		self.assertTrue(truncated)
		self.assertTrue(0 < len(rows) < 5000)
		self.assertEqual(len(rows), len(TableSchema(self.plugin._COLUMNS).snapshot(rows)))

	def test_result_preparation_honors_cancellation(self):
		usage = self.Usage([(os.path.normpath('C:/work/file.txt'), (11,))], checked=1)
		with self.assertRaises(self.plugin.Task.Canceled):
			self.plugin._rows(usage, {11: ('Worker', '')}, os.path.normpath('C:/work'),
				Mock(side_effect=self.plugin.Task.Canceled))

	def test_aliases_and_context_menu_entry_after_properties(self):
		import yaml
		from fman import DirectoryPane, DirectoryPaneCommand
		from fman.impl.plugins.command_registry import ApplicationCommandRegistry, PaneCommandRegistry
		from fman.impl.plugins.context_menu import ContextMenuProvider
		from fman.impl.plugins.key_bindings import KeyBindings
		from fman.impl.plugins.plugin import _get_command_name
		from pathlib import Path
		class ShowExplorerProperties(DirectoryPaneCommand):
			def __call__(self):
				pass
		registry = PaneCommandRegistry(None, None)
		for command in (ShowExplorerProperties, self.plugin.FindLockingProcesses):
			registry.register_command(_get_command_name(command), command)
		self.assertEqual(('Find blocking processes',),
			registry.get_command_aliases('find_locking_processes'))
		plugins = Path(self.plugin.__file__).resolve().parents[2]
		provider = ContextMenuProvider(registry, ApplicationCommandRegistry(None, None, None), KeyBindings())
		core = yaml.safe_load((plugins / 'Core/File Context Menu.yaml').read_text(encoding='utf-8'))
		self.assertEqual([], provider.load([entry for entry in core if entry.get('id') == 'properties'
			or entry.get('command') in registry.get_commands()], '', provider.FILE_CONTEXT))
		own = yaml.safe_load((plugins / 'ProcessPane/File Context Menu.yaml').read_text(encoding='utf-8'))
		self.assertEqual([], provider.load(own, '', provider.FILE_CONTEXT))
		url = 'file://C:/work/report.docx'
		for location, selected, expected in (
				('file://C:/work', [], ['P&roperties', 'Find &blocking processes']),
				('file://C:/work', [url, 'file://C:/work/other.txt'], ['P&roperties']),
				('process://', [], ['P&roperties'])):
			with self.subTest(location=location, selected=selected):
				widget = Mock()
				widget.get_location.return_value = location
				widget.get_selected_files.return_value = selected
				widget.get_file_under_cursor.return_value = url
				pane = DirectoryPane(None, widget, registry)
				self.assertEqual(expected, [entry[0] for entry in provider.get_context_menu(pane, url)])