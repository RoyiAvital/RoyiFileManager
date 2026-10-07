import ctypes
from dataclasses import replace
import hashlib
import json
from pathlib import Path
import struct
from tempfile import TemporaryDirectory
from threading import Event, get_ident
from time import monotonic
from unittest import TestCase
from unittest.mock import Mock, patch
from zipfile import ZipFile

from everything_search.ipc import CopyData, Hit, IpcClient, ProtocolError, \
	REQUEST_FLAGS, encode_query, parse_highlight, parse_reply
from everything_search.instance import Manager, ProcessRuntime, Settings, \
	State, add_folder, contains, make_ini, normalize_folder, normalize_folders
from everything_search.ipc import NotRunning, Results, QueryTimeout
import everything_search as commands


def reply_fixture(path='C:\\Data\\sample.txt', marked='C:\\Data\\*sample*.txt',
		flags=0, size=0, modified=116444736000000000):
	def text(value):
		encoded = value.encode('utf-16-le')
		return struct.pack('<I', len(encoded) // 2) + encoded + b'\0\0'
	return struct.pack('<7I', 1, 1, 0, REQUEST_FLAGS, 1, flags, 28) + \
		text(path) + struct.pack('<qQI', size, modified, 0) + text(marked)


class EverythingIpcTest(TestCase):
	def test_official_query_layout(self):
		data = encode_query(0x123456789, 7, 'abc')
		self.assertEqual(bytes.fromhex(
			'896745230700000000000000000000006400000054810000010000006100620063000000'), data)
		self.assertEqual(24 if ctypes.sizeof(ctypes.c_void_p) == 8 else 12,
			ctypes.sizeof(CopyData))

	def test_zero_size_and_filetime(self):
		result = parse_reply(reply_fixture())
		self.assertEqual(1, result.total)
		self.assertEqual(Hit('C:\\Data\\sample.txt', False, 0, 0,
			tuple(range(8, 14))), result.hits[0])

	def test_unicode_folder_and_drive_root(self):
		for path, flags in (('C:\\', 2), ('C:\\caf\u00e9\U0001f600', 1)):
			with self.subTest(path=path):
				hit = parse_reply(reply_fixture(path, path, flags, -1, 0)).hits[0]
				self.assertTrue(hit.is_folder)
				self.assertIsNone(hit.size)
				self.assertIsNone(hit.modified_ns)
				self.assertEqual(path, hit.path)

	def test_highlight_escaping_and_path_separators(self):
		self.assertEqual(('* abc', (2, 3, 4)), parse_highlight('** *abc*'))
		self.assertEqual(('a\\b', (0, 1, 2)), parse_highlight('*a\\b*'))
		self.assertEqual(('caf\u00e9', (3,)), parse_highlight('caf*\u00e9*'))
		with self.assertRaises(ProtocolError):
			parse_highlight('*unclosed')

	def test_rejects_truncated_packets(self):
		packet = reply_fixture()
		for length in range(len(packet)):
			with self.subTest(length=length), self.assertRaises(ProtocolError):
				parse_reply(packet[:length])

	def test_rejects_invalid_headers_offsets_and_strings(self):
		for position, value in ((4, 101), (8, 1), (12, 0), (16, 999),
				(24, 0), (24, 0xffffffff), (28, 0xffffffff)):
			packet = bytearray(reply_fixture())
			struct.pack_into('<I', packet, position, value)
			with self.subTest(position=position), self.assertRaises(ProtocolError):
				parse_reply(packet)
		with self.assertRaises(ProtocolError):
			parse_reply(reply_fixture(marked='wrong'))

	def test_query_input_bounds(self):
		for query, limit, sort in (('a\0b', 100, 'name'), ('x', 0, 'name'),
				('x', 1001, 'name'), ('x', 100, 'unknown')):
			with self.assertRaises(ValueError):
				encode_query(1, 1, query, limit, sort)

	def test_construction_and_unused_close_do_not_start_native_work(self):
		with patch('everything_search.ipc.Native') as native, \
				patch('everything_search.ipc.Thread') as thread:
			client = IpcClient()
			client.close()
			native.assert_not_called()
			thread.assert_not_called()

	def test_preparation_starts_once_and_close_can_signal_without_waiting(self):
		client = IpcClient()
		with patch('everything_search.ipc.Thread') as thread:
			thread.return_value.start.side_effect = client._ready.set
			client.start()
			client.start()
			thread.assert_called_once()
			client.close(wait=False)
			thread.return_value.join.assert_not_called()
			client.close()
			thread.return_value.join.assert_called_once_with(0.6)
			with self.assertRaises(NotRunning):
				client.start()

	def test_stale_and_wrong_sender_replies_are_ignored(self):
		client = IpcClient()
		client._latest = 3
		client._current = (3, 42)
		client._reply = None
		data = reply_fixture()
		buffer = ctypes.create_string_buffer(data)
		for request_id, sender, expected in ((2, 42, 0), (3, 99, 0), (3, 42, 1)):
			copied = CopyData(request_id, len(data), ctypes.addressof(buffer))
			self.assertEqual(expected, client._receive(1, 0x4a, sender, ctypes.addressof(copied)))
		self.assertEqual(data, client._reply)

	def test_query_deadline_includes_waiting_for_worker(self):
		client = IpcClient()
		client._thread = Mock()
		client._ready.set()
		started = monotonic()
		with self.assertRaises(QueryTimeout):
			client.query('Private', (42, 1, 'exe'), 'query', timeout_ms=10)
		self.assertLess(monotonic() - started, 0.5)
		self.assertTrue(client._queue.get_nowait()[-1].cancelled())
		client.close()

	def test_result_superseded_during_parsing_is_rejected(self):
		client = IpcClient()
		client._latest = 1
		client._native = Mock()
		client._native.find_instance.return_value = 42
		client._native.identity.return_value = (42, 1, 'exe')
		def send(*args):
			ctypes.cast(args[-1], ctypes.POINTER(ctypes.c_size_t)).contents.value = 1
			client._reply = reply_fixture()
			return 1
		client._native.send.side_effect = send
		def parse(*args):
			client._latest = 2
			return Results(0, ())
		with patch('everything_search.ipc.parse_reply', side_effect=parse), self.assertRaises(QueryTimeout):
			client._execute(1, (1, 'Private', (42, 1, 'exe'), 'query', 100, 'name',
				monotonic() + 1, Mock()))


class EverythingInstanceTest(TestCase):
	def test_ready_still_rejects_admin_and_appdata_storage(self):
		with patch('everything_search.instance.Native') as native:
			runtime = ProcessRuntime('unused', 'unused')
			for admin, appdata in ((0, 0), (1, 0), (0, 1), (1, 1)):
				with self.subTest(admin=admin, appdata=appdata):
					values = {0: 1, 1: 4, 2: 1, 3: 1032, 401: 1, 403: admin, 404: appdata}
					native.return_value.probe.side_effect = lambda window, command: values[command]
					if admin or appdata:
						with self.assertRaisesRegex(RuntimeError, 'without admin privileges or AppData'):
							runtime._ready(42)
					else:
						self.assertTrue(runtime._ready(42))

	def test_normalize_root_list_removes_aliases_and_covered_children(self):
		paths = ('C:/Data/Child/', 'c:\\data\\child\\.', 'C:/Data/other/..',
			'C:\\Database', 'Z:/Offline/../Offline/', 'z:\\OFFLINE')
		with patch('os.path.isdir', side_effect=AssertionError('No filesystem scan')):
			self.assertEqual(('C:\\Data', 'C:\\Database', 'Z:\\Offline'), normalize_folders(paths))
		self.assertEqual((('C:\\Data',), ()), add_folder(('C:/Data/', 'c:\\DATA'), 'C:/Data/child'))

	def test_component_aware_roots_and_parent_replacement(self):
		self.assertFalse(contains('C:\\Data', 'C:\\Database'))
		self.assertTrue(contains('C:\\Data', 'c:\\DATA\\child'))
		roots = ('C:\\Data\\one', 'C:\\Data\\two', 'D:\\Other')
		self.assertEqual((('D:\\Other', 'c:\\data'), roots[:2]), add_folder(roots, 'c:\\data'))
		self.assertEqual((roots, ()), add_folder(roots, 'C:\\Data\\one\\child'))

	def test_rejects_nonlocal_relative_and_control_paths(self):
		for path in ('folder', 'C:folder', '\\folder', '\\\\server\\share',
				'file://C:/folder', 'C:\\folder\nother', 'C:\\folder"other'):
			with self.subTest(path=path), self.assertRaises(ValueError):
				normalize_folder(path)

	def test_settings_keep_offline_roots_without_filesystem_access(self):
		with patch('os.path.isdir', side_effect=AssertionError('No scanning')):
			settings = Settings.load({'folders': ['Z:\\Offline', 'Z:\\Offline\\child']})
		self.assertEqual(('Z:\\Offline',), settings.folders)
		for data in ({'instance': ''}, {'instance': 'bad)'}, {'max_results': True},
				{'query_timeout_ms': 501}, {'sort': []}, {'folders': 'wrong'},
				{'exit_with_application': 'false'}):
			with self.subTest(data=data), self.assertRaises(ValueError):
				Settings.load(data)

	def test_ini_quotes_commas_and_unicode_and_disables_external_indexing(self):
		folders = ('C:\\Folder, with space\\caf\u00e9', 'Z:\\Offline')
		ini = make_ini(Settings(folders=folders), 'C:\\UserSettings\\Local\\Everything')
		values = dict(line.split('=', 1) for line in ini.splitlines()[1:])
		self.assertEqual(list(folders), json.loads('[' + values['folders'] + ']'))
		self.assertEqual('1,1', values['folder_monitor_changes'])
		for key in ('app_data', 'run_as_admin', 'http_server_enabled', 'etp_server_enabled',
				'auto_include_fixed_volumes', 'auto_include_removable_volumes',
				'auto_include_fixed_refs_volumes', 'auto_include_removable_refs_volumes'):
			self.assertEqual('0', values[key])

	def test_empty_unused_manager_performs_no_work(self):
		factory = Mock()
		manager = Manager('unused', 'unused', runtime_factory=factory)
		self.assertEqual('stopped', manager.request(Settings()).status)
		manager.close()
		factory.assert_not_called()
		self.assertIsNone(manager._thread)

	def test_worker_coalesces_updates_and_rejects_old_results(self):
		started, release, finished = Event(), Event(), Event()
		calls, notifications = [], []
		caller = get_ident()
		runtime = Mock()

		def apply(settings, canceled):
			calls.append((settings.folders, get_ident()))
			if len(calls) == 1:
				started.set()
				self.assertTrue(release.wait(2))
			return (42, 1, 'everything.exe')

		def notify(state):
			notifications.append(state)
			finished.set()

		runtime.apply.side_effect = apply
		manager = Manager('unused', 'unused', notify, Mock(return_value=runtime))
		try:
			manager.request(Settings(folders=('C:\\One',)))
			self.assertTrue(started.wait(2))
			manager.request(Settings(folders=('C:\\Two',)))
			manager.request(Settings(folders=('C:\\Three',)))
			release.set()
			self.assertTrue(finished.wait(2))
			self.assertEqual([('C:\\One',), ('C:\\Three',)], [call[0] for call in calls])
			self.assertTrue(all(thread != caller for _, thread in calls))
			self.assertEqual([3], [state.generation for state in notifications])
			self.assertEqual('ready', manager.snapshot().status)
		finally:
			release.set()
			manager.close()
		runtime.close.assert_called_once_with(True)
		self.assertFalse(manager._thread.is_alive())

	def test_failure_is_visible_and_can_be_retried(self):
		delivered = Event()
		runtime = Mock()
		runtime.apply.side_effect = RuntimeError('Missing executable')
		manager = Manager('unused', 'unused', lambda state: delivered.set(), Mock(return_value=runtime))
		try:
			settings = Settings(folders=('C:\\Offline',), exit_with_application=False)
			manager.request(settings)
			self.assertTrue(delivered.wait(2))
			self.assertEqual('error', manager.snapshot().status)
			self.assertIn('Missing executable', manager.snapshot().error)
			self.assertEqual(settings, manager._settings)
			delivered.clear()
			runtime.apply.side_effect = None
			runtime.apply.return_value = (42, 1, 'everything.exe')
			manager.request(settings)
			self.assertTrue(delivered.wait(2))
			self.assertEqual('ready', manager.snapshot().status)
		finally:
			manager.close()
		runtime.close.assert_called_once_with(False)

	def test_query_process_loss_allows_unchanged_settings_retry(self):
		for collision in (False, True):
			with self.subTest(collision=collision):
				delivered = Event()
				runtime = Mock()
				runtime.apply.return_value = (42, 1, 'everything.exe')
				manager = Manager('unused', 'unused', lambda state: delivered.set(), Mock(return_value=runtime))
				settings = Settings(folders=('C:\\Data',))
				service = Mock(closed=False, manager=manager)
				service.client.query.side_effect = NotRunning('Everything instance changed.')
				try:
					manager.request(settings)
					self.assertTrue(delivered.wait(2))
					old = manager.snapshot()
					self.assertIn('Reopen search', commands.search_items(service, settings, 'query')[0].title)
					self.assertEqual('error', manager.snapshot().status)
					self.assertEqual(1, runtime.apply.call_count)
					if collision:
						runtime.apply.side_effect = RuntimeError('Foreign instance; refusing to stop it.')
					delivered.clear()
					manager.request(settings)
					self.assertTrue(delivered.wait(2))
					self.assertEqual(2, runtime.apply.call_count)
					self.assertEqual('error' if collision else 'ready', manager.snapshot().status)
					current = manager.snapshot()
					manager.invalidate(old, 'Stale query')
					self.assertEqual(current, manager.snapshot())
				finally:
					manager.close()

	def test_owned_process_record_is_pretty_json(self):
		with TemporaryDirectory() as temporary, patch('everything_search.instance.Native') as native, \
				patch('everything_search.instance.subprocess.Popen') as spawn:
			directory = Path(temporary).resolve()
			executable = directory / 'Everything.exe'
			executable.touch()
			settings = Settings(folders=('C:\\Data',))
			identity = (42, 1, str(executable).casefold())
			native.return_value.find_instance.side_effect = (0, 42)
			native.return_value.identity_for_pid.return_value = identity
			native.return_value.identity.return_value = identity
			spawn.return_value.poll.return_value = None
			runtime = ProcessRuntime(directory, executable)
			try:
				with patch.object(runtime, '_ready', return_value=True):
					self.assertEqual(identity, runtime.apply(settings, Event()))
				text = (directory / 'owner.json').read_text(encoding='utf-8')
				record = json.loads(text)
				self.assertEqual({'instance': settings.instance, 'identity': list(identity),
					'config_hash': hashlib.sha256(make_ini(settings, directory).encode('utf-8')).hexdigest()},
					record)
				self.assertEqual(json.dumps(record, indent=2) + '\n', text)
				self.assertFalse((directory / 'owner.json.tmp').exists())
			finally:
				runtime.close(False)

	def test_adopts_only_matching_owned_configuration_without_restart(self):
		with TemporaryDirectory() as temporary, patch('everything_search.instance.Native') as native:
			directory = Path(temporary).resolve()
			executable = directory / 'Everything.exe'
			executable.touch()
			settings = Settings(folders=('C:\\Data',), exit_with_application=False)
			identity = (42, 1, str(executable).casefold())
			config_hash = hashlib.sha256(make_ini(settings, directory).encode('utf-8')).hexdigest()
			for saved_hash in (config_hash, 'different', None):
				with self.subTest(saved_hash=saved_hash):
					(directory / 'owner.json').write_text(json.dumps({'instance': settings.instance,
						'identity': identity, 'config_hash': saved_hash}), encoding='utf-8')
					native.return_value.find_instance.return_value = 42
					native.return_value.identity.return_value = identity
					native.return_value.probe.side_effect = lambda window, command: {
						0: 1, 1: 4, 2: 1, 3: 1032, 401: 1, 403: 0, 404: 0}[command]
					runtime = ProcessRuntime(directory, executable)
					def stop():
						native.return_value.find_instance.return_value = 0
						runtime.identity = None
					try:
						with patch.object(runtime, 'stop', side_effect=stop) as stopped, \
								patch('everything_search.instance.subprocess.Popen', side_effect=RuntimeError('restart requested')) as spawn:
							if saved_hash == config_hash:
								self.assertEqual(identity, runtime.apply(settings, Event()))
								self.assertEqual(identity, runtime.apply(replace(settings, exit_with_application=True), Event()))
								stopped.assert_not_called()
								spawn.assert_not_called()
								with self.assertRaisesRegex(RuntimeError, 'restart requested'):
									runtime.apply(replace(settings, folders=('D:\\Changed',)), Event())
							else:
								with self.assertRaisesRegex(RuntimeError, 'restart requested'):
									runtime.apply(settings, Event())
							stopped.assert_called_once()
							spawn.assert_called_once()
					finally:
						runtime.close(False)

	def test_foreign_named_instance_is_never_stopped(self):
		with patch('everything_search.instance.Native') as native:
			runtime = ProcessRuntime('unused', 'unused')
			runtime.identity = (42, 1, 'owned.exe')
			runtime.name = 'RoyiFileManager'
			native.return_value.find_instance.return_value = 123
			native.return_value.identity.return_value = (43, 2, 'foreign.exe')
			with self.assertRaisesRegex(RuntimeError, 'refusing'):
				runtime.stop()
			native.return_value.probe.assert_not_called()


def _activate_service(test):
	test.service = Mock(closed=False, owner=Mock(active=True))
	patcher = patch.object(commands, '_service', test.service)
	patcher.start()
	test.addCleanup(patcher.stop)


class EverythingCommandsTest(TestCase):
	def setUp(self):
		_activate_service(self)
		self.service.manager.snapshot.return_value = State(1, 'ready', (42, 1, 'everything.exe'))
		self.settings = Settings(folders=('C:\\Data',))

	def test_metadata_highlights_count_and_hidden_metadata(self):
		hit = Hit('C:\\Data\\sample.txt', False, 0, 0, (8, 9))
		self.service.client.query.return_value = Results(12345, (hit,))
		items = commands.search_items(self.service, self.settings, '*.txt')
		self.assertEqual('', items[-1].value)
		self.assertEqual('Showing 1 of 12,345', items[-1].title)
		self.assertEqual([8, 9], items[0].highlight)
		self.assertIn('0', items[0].description)
		items = commands.search_items(self.service, replace(self.settings, show_metadata=False), '*.txt')
		self.assertEqual(' ', items[0].description)
		self.service.client.query.assert_called_with('RoyiFileManager', (42, 1, 'everything.exe'),
			'*.txt', 100, 'name', 50)

	def test_hints_are_not_navigable_and_starting_never_queries(self):
		for state in (State(), State(1, 'starting'), State(1, 'error', error='Failed activation')):
			self.service.manager.snapshot.return_value = state
			self.assertEqual('', commands.search_items(self.service, self.settings, 'x')[0].value)
		self.service.client.query.assert_not_called()
		self.service.manager.snapshot.return_value = State(1, 'ready', (42, 1, 'everything.exe'))
		for error in (QueryTimeout('busy'), ProtocolError('unsupported')):
			self.service.client.query.side_effect = error
			self.assertEqual('', commands.search_items(self.service, self.settings, 'x')[0].value)

	def test_stale_reconfiguration_result_is_rejected(self):
		self.service.client.query.return_value = Results(1, (Hit('C:\\x', False, 1, None, ()),))
		self.service.manager.snapshot.side_effect = [State(1, 'ready', (42, 1, 'exe')), State(2, 'starting')]
		self.assertEqual('', commands.search_items(self.service, self.settings, 'x')[0].value)

	def test_accept_navigates_and_hint_does_not(self):
		pane = Mock()
		with patch.object(commands, '_read_settings', return_value=({}, self.settings)), \
				patch.object(commands, '_get_service', return_value=self.service), \
				patch.object(commands, 'show_quicksearch', return_value=('x', 'file://C:/Data/x.txt')):
			commands.SearchFileByEverything(pane)()
		pane.run_command.assert_called_once_with('open_directory', {'url': 'file://C:/Data/x.txt'})
		pane.reset_mock()
		with patch.object(commands, '_read_settings', return_value=({}, self.settings)), \
				patch.object(commands, '_get_service', return_value=self.service), \
				patch.object(commands, 'show_quicksearch', return_value=('x', '')):
			commands.SearchFileByEverything(pane)()
		pane.run_command.assert_not_called()

	def test_parent_replacement_requires_confirmation(self):
		data = {'folders': ['C:\\Data\\Child'], 'unrelated': 'keep'}
		with patch.object(commands, '_default_folder', return_value=''), \
				patch.object(commands, '_validate_new_folder', return_value='C:\\Data'), \
				patch.object(commands, 'show_prompt', return_value=('C:\\Data', True)), \
				patch.object(commands, 'load_json', return_value=data), \
				patch.object(commands, 'save_json') as save, \
				patch.object(commands, '_get_service') as get_service, \
				patch.object(commands, 'show_status_message'), \
				patch.object(commands, 'show_alert', return_value=commands.NO) as alert:
			commands.AddFolderToEverythingDatabase(Mock())()
			save.assert_not_called()
			alert.return_value = commands.YES
			commands.AddFolderToEverythingDatabase(Mock())()
			save.assert_called_once_with('Everything.json', {'folders': ['C:\\Data'], 'unrelated': 'keep'})
			get_service.assert_called_once()

	def test_offline_root_can_be_removed_without_filesystem_access(self):
		data = {'folders': ['Z:\\Offline']}
		pane = Mock()
		pane.get_path.return_value = commands.FOLDERS_ROOT
		with patch.object(commands, 'load_json', return_value=data), \
				patch.object(commands, 'show_alert', return_value=commands.YES) as alert, \
				patch.object(commands, 'save_json') as save, \
				patch.object(commands, '_get_service') as get_service, \
				patch.object(commands, 'show_status_message'), \
				patch('os.path.isdir', side_effect=AssertionError('No scan')):
			commands.RemoveEverythingFolders(pane)(urls=[commands.FOLDERS_ROOT + commands._folder_key('Z:\\Offline')])
			save.assert_called_once_with('Everything.json', {'folders': []})
			get_service.assert_called_once_with(Settings(), force=True)
			self.assertIn('Folders on disk are not deleted', alert.call_args.args[0])
			self.assertEqual(commands.NO, alert.call_args.args[2])

	def test_service_start_has_no_feature_io_threads_or_signals(self):
		with patch.object(commands, 'Manager') as manager, patch.object(commands, 'IpcClient') as client, \
				patch.object(commands, 'Notifications') as notifications, patch.object(commands, '_service'):
			service = commands.EverythingService(Mock(), Mock(active=True))
			service.start()
			service.dispose()
			manager.assert_not_called()
			client.assert_not_called()
			notifications.assert_not_called()

	def test_stale_settings_commit_does_not_overwrite_new_roots(self):
		with patch.object(commands, 'load_json', return_value={'folders': ['C:\\Changed']}), \
				patch.object(commands, 'save_json') as save, \
				patch.object(commands, '_get_service') as get_service:
			with self.assertRaisesRegex(RuntimeError, 'settings changed'):
				commands._save_roots({'folders': ['C:\\Old']}, ('C:\\Added',), self.service)
			save.assert_not_called()
			get_service.assert_not_called()

	def test_every_commit_persists_canonical_roots_and_restarts_once(self):
		data = {'folders': ['Z:/Offline/', 'z:\\OFFLINE'], 'unrelated': 'keep'}
		with patch.object(commands, 'load_json', return_value=data), \
				patch.object(commands, 'save_json') as save, \
				patch.object(commands, '_get_service') as service, \
				patch.object(commands, 'show_status_message'):
			commands._save_roots(data, ('Z:/Offline/', 'z:\\OFFLINE',
				'C:/Data/child', 'C:\\Data', 'c:\\DATA\\.'), self.service)
			save.assert_called_once_with('Everything.json',
				{'folders': ['Z:\\Offline', 'C:\\Data'], 'unrelated': 'keep'})
			service.assert_called_once_with(Settings(folders=('Z:\\Offline', 'C:\\Data')), force=True)

	def test_cleaning_existing_roots_does_not_restart_and_clean_noop_does_not_save(self):
		data = {'folders': ['C:/Data/', 'c:\\DATA', 'C:/Data/child']}
		with patch.object(commands, 'load_json', return_value=data), \
				patch.object(commands, 'save_json') as save, \
				patch.object(commands, '_get_service') as service:
			commands._save_roots(data, ('C:\\Data',), self.service)
			save.assert_called_once_with('Everything.json', {'folders': ['C:\\Data']})
			service.assert_not_called()
		data = {'folders': ['C:\\Data']}
		with patch.object(commands, 'load_json', return_value=data), \
				patch.object(commands, 'save_json') as save, \
				patch.object(commands, '_get_service') as service:
			self.assertFalse(commands._save_roots(data, ('C:\\Data',), self.service))
			save.assert_not_called()
			service.assert_not_called()

	def test_replaced_service_rejects_commit_before_settings_or_notifications(self):
		provider = commands.EverythingFolders()
		with patch.object(commands, '_service', Mock(closed=False, owner=Mock(active=True))), \
				patch.object(commands, 'load_json') as load, patch.object(commands, 'save_json') as save, \
				patch.object(commands, '_get_service') as activate, \
				patch.object(provider, 'notify_file_changed') as notify:
			self.assertIsNone(commands._save_roots({}, ('C:\\Added',), self.service))
			for operation in (load, save, activate, notify):
				operation.assert_not_called()


class EverythingFoldersTest(TestCase):
	setUp = _activate_service

	def test_manage_only_navigates_and_reloads_without_starting_everything(self):
		pane = Mock()
		pane.get_path.return_value = 'file://C:'
		with patch.object(commands, '_get_service') as service:
			commands.ManageEverythingFolders(pane)()
			pane.set_path.assert_called_once_with(commands.FOLDERS_ROOT)
			pane.get_path.return_value = commands.FOLDERS_ROOT
			commands.ManageEverythingFolders(pane)()
			pane.reload.assert_called_once()
			service.assert_not_called()

	def test_listener_routes_navigation_removal_and_transfers_without_touching_files(self):
		pane, other = Mock(), Mock()
		pane.window.get_panes.return_value = [pane, other]
		pane.get_path.return_value = commands.FOLDERS_ROOT
		other.get_path.return_value = 'file://C:'
		url = commands.FOLDERS_ROOT + commands._folder_key('C:\\Data')
		pane.get_file_under_cursor.return_value = url
		listener = commands.EverythingFoldersListener(pane)
		for name in ('open', 'open_file', 'open_directory'):
			self.assertEqual(('open_everything_folder', {'url': url}), listener.on_command(name, {'url': url}))
		for name in ('move_to_trash', 'delete_permanently'):
			self.assertEqual(('remove_everything_folders', {}), listener.on_command(name, {}))
		for name in ('copy', 'move', 'symlink', 'rename', 'pack', 'cut', 'copy_to_clipboard', 'new_empty_file'):
			self.assertEqual(('everything_folder_operation_unsupported', {}), listener.on_command(name, {}))
		self.assertEqual(('copy_everything_folder_paths', {}), listener.on_command('copy_paths_to_clipboard', {}))
		pane.get_path.return_value = 'file://C:'
		other.get_path.return_value = commands.FOLDERS_ROOT
		self.assertEqual(('add_everything_folders', {'files': None, 'dest_dir': commands.FOLDERS_ROOT}),
			listener.on_command('copy', {}))
		self.assertEqual(('everything_folder_operation_unsupported', {}), listener.on_command('move', {}))
		self.assertIsNone(listener.on_command('delete_permanently', {}))
		self.assertEqual(('open_everything_folder', {'url': url}), listener.on_command('open_directory', {'url': url}))

	def test_bulk_remove_cancel_and_commit_refresh_all_providers_once(self):
		data = {'folders': ['C:\\Data', 'Z:\\Offline', 'D:\\Keep']}
		pane = Mock()
		pane.get_path.return_value = commands.FOLDERS_ROOT
		urls = [commands.FOLDERS_ROOT + commands._folder_key(path) for path in data['folders'][:2]]
		providers = [commands.EverythingFolders(), commands.EverythingFolders()]
		callbacks = [Mock(), Mock()]
		for provider, callback in zip(providers, callbacks):
			provider._add_file_changed_callback('', callback)
		with patch.object(commands, 'load_json', return_value=data), \
				patch.object(commands, 'save_json') as save, \
				patch.object(commands, '_get_service') as service, \
				patch.object(commands, 'show_status_message'), \
				patch.object(commands, 'show_alert', return_value=commands.NO) as alert:
			command = commands.RemoveEverythingFolders(pane)
			self.assertFalse(command.is_visible())
			command(urls=urls)
			save.assert_not_called()
			alert.return_value = commands.YES
			command(urls=urls)
			save.assert_called_once_with('Everything.json', {'folders': ['D:\\Keep']})
			service.assert_called_once()
			for callback in callbacks:
				callback.assert_called_once_with(commands.FOLDERS_ROOT)

	def test_add_batch_normalizes_and_skips_files_with_one_commit(self):
		with TemporaryDirectory() as temporary:
			folder = Path(temporary) / 'folder'
			folder.mkdir()
			file = Path(temporary) / 'file.txt'
			file.touch()
			with patch.object(commands, 'submit_task', side_effect=lambda task: task()), \
					patch.object(commands, '_add_roots', return_value=True) as add, \
					patch.object(commands, 'show_status_message') as status:
				commands.AddEverythingFolders(Mock())(files=[commands.as_url(folder), commands.as_url(folder),
					commands.as_url(file), 'zip://archive'], dest_dir=commands.FOLDERS_ROOT)
				add.assert_called_once_with((str(folder),), self.service)
				self.assertIn('skipped 2', status.call_args.args[0])

	def test_canceled_add_does_not_commit_and_stale_rows_cannot_remove(self):
		with patch.object(commands, 'submit_task'), patch.object(commands, '_add_roots') as add:
			commands.AddEverythingFolders(Mock())(files=['file://C:/Data'], dest_dir=commands.FOLDERS_ROOT)
			add.assert_not_called()
		with self.assertRaises(ValueError):
			commands._paths_for_rows([commands.FOLDERS_ROOT + 'missing'], ('C:\\Data',))
		with self.assertRaises(ValueError):
			commands._paths_for_rows(['file://C:/Data'], ('C:\\Data',))

	def test_open_checks_target_only_on_demand_and_f11_copies_real_paths(self):
		pane = Mock()
		url = commands.FOLDERS_ROOT + commands._folder_key('Z:\\Offline')
		pane.get_selected_files.return_value = [url]
		with patch.object(commands, 'load_json', return_value={'folders': ['Z:\\Offline']}), \
				patch.object(commands.os.path, 'isdir', return_value=False) as exists, \
				patch.object(commands, 'show_alert') as alert, patch.object(commands.clipboard, 'clear'), \
				patch.object(commands.clipboard, 'set_text') as copy:
			commands.OpenEverythingFolder(pane)(url)
			pane.run_command.assert_not_called()
			alert.assert_called_once()
			exists.return_value = True
			commands.OpenEverythingFolder(pane)(url)
			pane.run_command.assert_called_once_with('open_directory', {'url': 'file://Z:/Offline'})
			commands.CopyEverythingFolderPaths(pane)()
			copy.assert_called_once_with('Z:\\Offline')

	def test_listing_is_offline_read_only_and_has_stable_identities(self):
		from search_file_fuzzy.indexer import index_listing
		data = {'folders': ['Z:/Offline', 'C:/Data', 'c:\\DATA', 'C:/']}
		provider = commands.EverythingFolders()
		with patch.object(commands, 'load_json', return_value=data), \
				patch.object(commands, '_get_service') as service, \
				patch('os.path.isdir', side_effect=AssertionError('No target scan')):
			listing = provider.scan('', lambda: None)
			self.assertEqual(('Z:\\Offline', 'C:\\'), listing.column('path'))
			self.assertEqual(('Offline', 'C:\\'), listing.display_names)
			self.assertEqual((False, False), listing.is_dir)
			self.assertEqual(list(listing.display_names), [entry.name for entry in index_listing(listing).entries])
			self.assertEqual(32, len(listing.identities))
			self.assertEqual('Z:\\Offline', provider.folder_path(listing.names[0]))
			self.assertEqual(commands.FOLDERS_ROOT + listing.names[0], provider.resolve(listing.names[0]))
			self.assertTrue(provider.exists(''))
			self.assertFalse(provider.exists('missing'))
			self.assertEqual(commands._folder_key('z:\\OFFLINE'), listing.names[0])
			self.assertEqual('Z:\\Offline', commands.IndexedFolderPath().text(listing, 0))
			service.assert_not_called()
		for operation in (provider.delete, provider.move_to_trash, provider.mkdir, provider.touch):
			with self.assertRaises(NotImplementedError):
				operation('unused')
		with self.assertRaises(NotADirectoryError):
			provider.scan('child', lambda: None)

	def test_listing_propagates_cancellation(self):
		with patch.object(commands, 'load_json', return_value={'folders': ['C:\\Data']}):
			with self.assertRaises(InterruptedError):
				commands.EverythingFolders().scan('', Mock(side_effect=InterruptedError))


class EverythingFavoritesTest(TestCase):
	setUp = _activate_service

	def test_snapshot_and_batch_import_preserve_favorites_and_merge_once(self):
		favorites = {'favorites': [
			{'name': 'Child', 'url': 'file://C:/Data/Child/'},
			{'name': 'Parent', 'url': 'file://C:/Data'},
			{'name': 'Duplicate', 'url': 'file://c:/DATA'},
			{'name': 'Offline', 'url': 'file://Z:/Offline'},
			{'name': 'Archive', 'url': 'zip://C:/archive.zip'},
			{'name': 'Network', 'url': 'file:////server/share'},
			{'name': 'File', 'url': 'file://C:/file.txt'},
			{'name': '', 'url': 'file://C:/invalid'},
		]}
		data = {'folders': ['C:/Existing/', 'c:\\EXISTING'], 'unrelated': 'keep'}
		def validate(path, allow_unavailable=False):
			self.assertTrue(allow_unavailable)
			if path.endswith('file.txt') or 'server' in path:
				raise ValueError('Not a local folder')
			return normalize_folder(path)
		with patch.object(commands, 'load_json', side_effect=lambda name, **kwargs:
				favorites if name == 'Favorites.json' else data), \
				patch.object(commands, '_validate_new_folder', side_effect=validate), \
				patch.object(commands, 'save_json') as save, \
				patch.object(commands, '_get_service') as service, \
				patch.object(commands, 'show_status_message') as status, \
				patch.object(commands, 'show_alert') as alert:
			commands.AddFavoritesToEverythingDatabase(Mock())()
			save.assert_called_once_with('Everything.json',
				{'folders': ['C:\\Existing', 'C:\\Data', 'Z:\\Offline'], 'unrelated': 'keep'})
			service.assert_called_once_with(Settings(folders=('C:\\Existing', 'C:\\Data', 'Z:\\Offline')), force=True)
			self.assertIn('Skipped 5', status.call_args.args[0])
			alert.assert_not_called()
		self.assertEqual(8, len(favorites['favorites']))
		self.assertEqual(['C:/Existing/', 'c:\\EXISTING'], data['folders'])

	def test_parent_replacement_is_one_confirmation_and_cancel_is_atomic(self):
		data = {'folders': ['C:\\Data\\One', 'C:\\Data\\Two', 'D:\\Keep']}
		with patch.object(commands, '_favorite_paths', return_value=(('C:\\Data', 'E:\\New'), 0)), \
				patch.object(commands, 'load_json', return_value=data), \
				patch.object(commands, 'save_json') as save, \
				patch.object(commands, '_get_service') as service, \
				patch.object(commands, 'show_status_message'), \
				patch.object(commands, 'show_alert', return_value=commands.NO) as alert:
			commands.AddFavoritesToEverythingDatabase(Mock())()
			alert.assert_called_once()
			save.assert_not_called()
			service.assert_not_called()
			alert.reset_mock()
			alert.return_value = commands.YES
			commands.AddFavoritesToEverythingDatabase(Mock())()
			alert.assert_called_once()
			save.assert_called_once_with('Everything.json', {'folders': ['D:\\Keep', 'C:\\Data', 'E:\\New']})
			service.assert_called_once()

	def test_already_covered_favorites_and_empty_import_do_not_restart(self):
		for paths in (('C:\\Data\\Child',), ()):
			with self.subTest(paths=paths), \
					patch.object(commands, '_favorite_paths', return_value=(paths, 0)), \
					patch.object(commands, 'load_json', return_value={'folders': ['C:\\Data']}), \
					patch.object(commands, 'save_json') as save, \
					patch.object(commands, '_get_service') as service, \
					patch.object(commands, 'show_status_message'):
				commands.AddFavoritesToEverythingDatabase(Mock())()
				save.assert_not_called()
				service.assert_not_called()

	def test_unavailable_favorite_is_allowed_but_existing_file_is_not(self):
		with TemporaryDirectory() as directory:
			missing = str(Path(directory) / 'offline')
			self.assertEqual(missing, commands._validate_new_folder(missing, allow_unavailable=True))
			with self.assertRaises(ValueError):
				commands._validate_new_folder(missing)
			file = Path(directory) / 'file.txt'
			file.touch()
			with self.assertRaises(ValueError):
				commands._validate_new_folder(str(file), allow_unavailable=True)


class EverythingBuildTest(TestCase):
	def test_verified_download_and_offline_reuse(self):
		import build
		binary, license_text = b'fixture portable executable', b'fixture\r\nlicense\r\n'
		with TemporaryDirectory() as temporary:
			destination = Path(temporary) / 'bin'
			license_source = Path(temporary) / 'reviewed.txt'
			license_source.write_bytes(license_text)
			license_destination = destination.parent / 'licenses/Everything.txt'
			def download(url, path, expected):
				self.assertEqual(build.EVERYTHING_ARCHIVE_URLS, url)
				with ZipFile(path, 'w') as zipped:
					zipped.writestr('everything.exe', binary)
			with patch.object(build, 'EVERYTHING_BINARY_SHA256', hashlib.sha256(binary).hexdigest()), \
					patch.object(build, 'EVERYTHING_LICENSE_SHA256', hashlib.sha256(license_text.replace(b'\r\n', b'\n')).hexdigest()), \
					patch.object(build, 'EVERYTHING_LICENSE', license_source), \
					patch.object(build, '_download', side_effect=download) as fetch:
				build._ensure_everything(destination)
				self.assertEqual(1, fetch.call_count)
				self.assertEqual(binary, (destination / 'Everything.exe').read_bytes())
				self.assertEqual(license_text, license_destination.read_bytes())
				fetch.reset_mock()
				build._ensure_everything(destination)
				fetch.assert_not_called()
				license_destination.write_bytes(b'altered')
				build._ensure_everything(destination)
				fetch.assert_not_called()
				self.assertEqual(license_text, license_destination.read_bytes())
				license_source.write_bytes(b'altered')
				with self.assertRaisesRegex(SystemExit, 'license failed'):
					build._ensure_everything(destination)
				fetch.assert_not_called()

	def test_reviewed_license_matches_pin(self):
		import build
		build._verify_everything_license(build.EVERYTHING_LICENSE)

	def test_official_archive_is_tried_before_the_mirror(self):
		import build
		official, mirror = build.EVERYTHING_ARCHIVE_URLS
		self.assertEqual(build.EVERYTHING_ARCHIVE_URL, official)
		self.assertEqual('https://github.com/RoyiAvital/RoyiFileManager/releases/download/'
			f'v0.10.2/Everything-{build.EVERYTHING_VERSION}.x64.zip', mirror)

	def test_download_falls_back_to_the_next_verified_source(self):
		import build
		from io import BytesIO
		from urllib.error import HTTPError
		payload = b'pinned archive'
		responses = {
			'https://official/a.zip': [503, 403],
			'https://tampered/a.zip': [b'tampered'],
			'https://mirror/a.zip': [payload],
		}
		requests = []
		def urlopen(request, timeout):
			requests.append((request.full_url, request.get_header('User-agent')))
			response = responses[request.full_url].pop(0)
			if isinstance(response, int):
				raise HTTPError(request.full_url, response, 'error', {}, BytesIO())
			return BytesIO(response)
		with TemporaryDirectory() as temporary, \
				patch.object(build, 'urlopen', side_effect=urlopen), \
				patch.object(build, 'DOWNLOAD_RETRY_DELAYS', (0,)), \
				patch.object(build, 'DOWNLOAD_SETTLE_SECONDS', 0):
			destination = Path(temporary) / 'a.zip'
			build._download(tuple(responses), destination, hashlib.sha256(payload).hexdigest())
			self.assertEqual(payload, destination.read_bytes())
		self.assertEqual(['https://official/a.zip'] * 2 + ['https://tampered/a.zip', 'https://mirror/a.zip'],
			[url for url, _ in requests])
		self.assertEqual({build.DOWNLOAD_USER_AGENT}, {agent for _, agent in requests})

	def test_download_fails_when_no_source_is_verified(self):
		import build
		from io import BytesIO
		from urllib.error import HTTPError, URLError
		def urlopen(request, timeout):
			if 'official' in request.full_url:
				raise HTTPError(request.full_url, 403, 'Forbidden', {}, BytesIO())
			if 'offline' in request.full_url:
				raise URLError('unreachable')
			return BytesIO(b'tampered')
		urls = ('https://official/a.zip', 'https://offline/a.zip', 'https://mirror/a.zip')
		with TemporaryDirectory() as temporary, \
				patch.object(build, 'urlopen', side_effect=urlopen), \
				patch.object(build, 'DOWNLOAD_SETTLE_SECONDS', 0):
			destination = Path(temporary) / 'a.zip'
			with self.assertRaises(SystemExit) as raised:
				build._download(urls, destination, 'pinned')
			self.assertFalse(destination.exists())
		message = str(raised.exception)
		for expected in ('official/a.zip: HTTP Error 403', 'offline/a.zip: <urlopen error unreachable>',
				'mirror/a.zip: SHA-256', 'expected pinned'):
			self.assertIn(expected, message)

	def test_published_files_inherit_destination_permissions(self):
		import build
		import shutil
		from uuid import uuid4
		import win32security
		binary = b'fixture portable executable'
		# Temporary directories are owner-only on Windows; an ordinary folder is needed here.
		root = Path(build.ROOT) / 'target' / ('everything-acl-' + uuid4().hex)
		destination = root / 'bin'
		destination.mkdir(parents=True)
		def download(url, path, expected):
			with ZipFile(path, 'w') as zipped:
				zipped.writestr('everything.exe', binary)
		def access(path):
			descriptor = win32security.GetFileSecurity(str(path), win32security.DACL_SECURITY_INFORMATION)
			return win32security.ConvertSecurityDescriptorToStringSecurityDescriptor(
				descriptor, win32security.SDDL_REVISION_1, win32security.DACL_SECURITY_INFORMATION)
		try:
			with patch.object(build, 'EVERYTHING_BINARY_SHA256', hashlib.sha256(binary).hexdigest()), \
					patch.object(build, '_download', side_effect=download):
				build._ensure_everything(destination)
			ordinary = destination / 'ordinary.exe'
			ordinary.write_bytes(binary)
			for path in (destination / 'Everything.exe', root / 'licenses' / 'Everything.txt'):
				self.assertEqual(access(ordinary), access(path), path)
			self.assertEqual({'Everything.exe', 'ordinary.exe'}, {path.name for path in destination.iterdir()})
		finally:
			shutil.rmtree(root)

	def test_unverified_executable_is_never_published(self):
		import build
		with TemporaryDirectory() as temporary:
			destination = Path(temporary) / 'bin'
			def download(url, path, expected):
				with ZipFile(path, 'w') as zipped:
					zipped.writestr('everything.exe', b'wrong content')
			with patch.object(build, '_download', side_effect=download), self.assertRaises(SystemExit):
				build._ensure_everything(destination)
			self.assertFalse(destination.exists())

	def test_packaged_smoke_uses_verified_bundle_without_provisioning(self):
		import build
		with TemporaryDirectory() as temporary, patch.object(build, 'ROOT', Path(temporary)), \
				patch.object(build, 'DIST_DIR', Path(temporary) / 'frozen'), \
				patch.object(build, '_require_windows'), \
				patch.object(build, '_environment', return_value={'PYTHONPATH': 'source-imports'}), \
				patch.object(build, '_verify_everything') as verify, \
				patch.object(build, '_verify_native_parser_packaged'), \
				patch.object(build, '_ensure_everything') as provision, \
				patch.object(build, '_run_restricted') as run:
			self.assertIsNone(build.main(['smoke-everything']))
			plugin = build.DIST_DIR / '_internal/resources/Plugins/Everything'
			verify.assert_called_once_with(plugin / 'bin')
			provision.assert_not_called()
			run.assert_called_once()
			command, environment, log, timeout = run.call_args.args
			self.assertEqual(['--exe', str(plugin / 'bin/Everything.exe')], command[-2:])
			self.assertIn('fman_integrationtest.everything_smoke', command)
			self.assertEqual(str(plugin) + build.os.pathsep + 'source-imports', environment['PYTHONPATH'])
			self.assertEqual(build.ROOT / 'UserSettings/Local/EverythingSmoke.log', log)
			self.assertEqual(180, timeout)
			run.reset_mock()
			verify.side_effect = SystemExit('Unverified bundled executable')
			with self.assertRaisesRegex(SystemExit, 'Unverified'):
				build.smoke_everything()
			run.assert_not_called()

	def test_build_entry_points_provision_and_package_only_verifies(self):
		import build
		with TemporaryDirectory() as temporary, patch.object(build, 'DIST_DIR', Path(temporary)), \
				patch.object(build, '_require_windows'), patch.object(build, '_ensure_7za'), \
				patch.object(build, '_ensure_conda_lock'), patch.object(build, '_remove_previous_freeze'), \
				patch.object(build, '_copy_dependency_manifests'), patch.object(build, '_run_test_directory'), \
				patch.object(build.subprocess, 'run'), patch.object(build, '_ensure_everything') as ensure:
			for entry in (build.run, build.test, build.freeze):
				ensure.reset_mock()
				entry()
				ensure.assert_called_once_with()
			ensure.reset_mock()
			with self.assertRaises(SystemExit):
				build.package()
			ensure.assert_not_called()

	def test_spec_includes_executable_and_license(self):
		import ast
		import build
		tree = ast.parse((build.ROOT / 'application.spec').read_text(encoding='utf-8'))
		hidden_imports = next(node.value for node in tree.body
			if isinstance(node, ast.Assign) and any(isinstance(target, ast.Name) and
				target.id == 'hidden_imports' for target in node.targets))
		# The literal list is the leftmost operand of `[...] + collected + ...`.
		while isinstance(hidden_imports, ast.BinOp):
			hidden_imports = hidden_imports.left
		self.assertIn('uuid', ast.literal_eval(hidden_imports))
		pairs = [ast.literal_eval(node) for node in ast.walk(tree)
			if isinstance(node, ast.Tuple) and all(isinstance(item, ast.Constant) for item in node.elts)]
		self.assertIn(('src/main/resources/base/Plugins/Everything/bin/Everything.exe',
			'resources/Plugins/Everything/bin'), pairs)
		self.assertIn(('src/main/resources/base/Plugins/Everything/licenses/Everything.txt',
			'resources/Plugins/Everything/licenses'), pairs)