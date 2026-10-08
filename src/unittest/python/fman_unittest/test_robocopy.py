from importlib import import_module
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
from threading import Event
from unittest import TestCase
from unittest.mock import Mock, patch

from fman.url import as_url

from fman_unittest.robocopy_fixture import PLUGIN_ROOT, plugin_module


class RobocopyPackagingTest(TestCase):
	def test_bundled_plugin_is_discovered_and_collected_by_existing_spec(self):
		import build
		import os
		from runpy import run_path
		from PyInstaller.building.utils import format_binaries_and_datas
		from fman.impl.plugins.discover import find_plugin_dirs
		root = Path(__file__).resolve().parents[4]
		self.assertTrue(PLUGIN_ROOT.is_dir(), 'Robocopy must ship alongside the other bundled plug-ins')
		self.assertFalse((root / 'plugins/Robocopy/robocopy_plugin').exists(), 'Do not maintain a second runtime copy')
		self.assertIn(str(PLUGIN_ROOT), build._environment()['PYTHONPATH'].split(os.pathsep))
		with TemporaryDirectory() as temporary:
			discovered = find_plugin_dirs(str(PLUGIN_ROOT.parent), str(Path(temporary) / 'Third-party'), str(Path(temporary) / 'User'))
		self.assertIn(str(PLUGIN_ROOT), discovered)
		with patch('PyInstaller.utils.hooks.collect_all', return_value=([], [], [])):
			specification = run_path(str(root / 'application.spec'), init_globals={
				'SPECPATH': str(root), 'Analysis': Mock(), 'PYZ': Mock(), 'EXE': Mock(), 'COLLECT': Mock()})
		datas = dict(format_binaries_and_datas(specification['datas'], workingdir=str(root)))
		for name in ('Robocopy.json', 'README.md', 'robocopy_plugin/__init__.py',
				'robocopy_plugin/engine.py', 'robocopy_plugin/windows.py', 'robocopy_plugin/logs.py'):
			self.assertEqual(str(PLUGIN_ROOT / name), datas[str(Path('resources/Plugins/Robocopy') / name)])


class RobocopyProcessTest(TestCase):
	def test_unrelated_inherited_writer_cannot_keep_reader_alive(self):
		import subprocess
		from threading import Thread
		with plugin_module():
			windows = import_module('robocopy_plugin.windows')
			library = windows.api()
			proxy = Mock(wraps=library)
			unrelated = []
			def launch(*args):
				unrelated.append(subprocess.Popen([sys.executable, '-B', '-c',
					'from threading import Event; Event().wait()'], close_fds=False))
				return library.CreateProcessW(*args)
			proxy.CreateProcessW.side_effect = launch
			process = closer = None
			try:
				with patch.object(windows, 'api', return_value=proxy):
					process = windows.OwnedProcess([sys.executable, '-B', '-c', "print('final output')"])
				self.assertEqual(0, library.WaitForSingleObject(process.process, 5000))
				closer = Thread(target=process.close, daemon=True)
				closer.start()
				closer.join(2)
				self.assertFalse(closer.is_alive(), 'Cleanup waited for an unrelated inherited writer')
				self.assertFalse(process.reader.is_alive())
				self.assertIn('final output', process.output.text())
				self.assertIsNone(unrelated[0].poll(), 'The unrelated child must remain alive')
			finally:
				for child in unrelated:
					child.kill()
					child.wait(timeout=5)
				if closer is not None:
					closer.join(5)
				if process is not None:
					process.close()

	def test_failed_assignment_resume_and_reader_close_native_handles(self):
		import ctypes
		from ctypes import wintypes
		with plugin_module():
			windows = import_module('robocopy_plugin.windows')
			library = windows.api()
			library.GetCurrentProcess.restype = wintypes.HANDLE
			library.GetProcessHandleCount.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
			library.GetProcessHandleCount.restype = wintypes.BOOL
			def count():
				value = wintypes.DWORD()
				self.assertTrue(library.GetProcessHandleCount(library.GetCurrentProcess(), ctypes.byref(value)))
				return value.value
			windows.run([sys.executable, '-B', '-c', 'pass'])
			before = count()
			for function, result in (('AssignProcessToJobObject', 0), ('ResumeThread', 0xffffffff), ('ReadFile', 0)):
				with self.subTest(function=function):
					proxy = Mock(wraps=library)
					def fail(*args):
						ctypes.set_last_error(5)
						return result
					getattr(proxy, function).side_effect = fail
					with patch.object(windows, 'api', return_value=proxy), self.assertRaises(OSError):
						windows.run([sys.executable, '-B', '-c', "from threading import Event; print('ready', flush=True); Event().wait()"], timeout=10)
					self.assertLessEqual(count(), before + 1)

	def test_parent_exit_kills_nested_job_and_large_pipe_is_bounded(self):
		import ctypes
		from ctypes import wintypes
		with plugin_module():
			windows = import_module('robocopy_plugin.windows')
			code, output = windows.run([sys.executable, '-B', '-c', "print('x' * 200000); print('end')"], timeout=10)
			self.assertEqual(0, code)
			self.assertLessEqual(len(output), 65536)
			self.assertTrue(output.endswith('end'))
			script = ('import os, runpy, sys; namespace = runpy.run_path(%r); '
				'child = namespace[\'OwnedProcess\']([sys.executable, \'-B\', \'-c\', '
				'\'from threading import Event; Event().wait()\']); print(child.pid, flush=True); os._exit(0)') % windows.__file__
			code, output = windows.run([sys.executable, '-B', '-c', script], timeout=10)
			self.assertEqual(0, code)
			pid = int(output.strip())
			library = windows.api()
			library.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
			library.OpenProcess.restype = wintypes.HANDLE
			handle = library.OpenProcess(0x100000, False, pid)
			if handle:
				try:
					self.assertEqual(0, library.WaitForSingleObject(handle, 5000))
				finally:
					library.CloseHandle(handle)
			else:
				self.assertEqual(87, ctypes.get_last_error())

	def test_owned_launch_captures_output_and_reaps(self):
		with plugin_module():
			windows = import_module('robocopy_plugin.windows')
			code, output = windows.run([sys.executable, '-B', '-c', "print('owned child')"], timeout=10)
			self.assertEqual(0, code)
			self.assertIn('owned child', output)

	def test_quiet_child_cancellation_reaps_reader(self):
		with plugin_module():
			windows = import_module('robocopy_plugin.windows')
			checks = []
			def cancel():
				checks.append(True)
				if len(checks) == 3:
					raise windows.Canceled()
			with self.assertRaises(windows.Canceled):
				windows.run([sys.executable, '-B', '-c', 'from threading import Event; Event().wait()'], check=cancel)


class RobocopyPlannerTest(TestCase):
	def test_shared_ancestry_keeps_same_file_and_source_log_overlap_guards(self):
		import os
		with plugin_module(), TemporaryDirectory() as temporary:
			engine = import_module('robocopy_plugin.engine')
			root = Path(temporary).resolve()
			source, destination = root / 'source', root / 'target'
			source.mkdir()
			destination.mkdir()
			selected = source / 'file.txt'
			selected.write_bytes(b'keep')
			os.link(selected, destination / 'file.txt')
			arguments = (as_url(source), (as_url(selected),), str(destination), 'robocopy', engine.Settings())
			with self.assertRaisesRegex(ValueError, 'same entry'):
				engine.prepare(*arguments)
			(destination / 'file.txt').unlink()
			with self.assertRaisesRegex(ValueError, 'log'):
				engine.prepare(*arguments, log=str(selected))
			self.assertEqual(b'keep', selected.read_bytes())
			self.assertEqual([], list(destination.iterdir()))

	def test_unsupported_case_query_is_unknown_and_access_failure_is_not_hidden(self):
		import ctypes
		with plugin_module(), TemporaryDirectory() as temporary:
			windows = import_module('robocopy_plugin.windows')
			library = windows.api()
			for code in (1, 50, 87, 5):
				with self.subTest(code=code):
					proxy = Mock(wraps=library)
					def fail(*args):
						ctypes.set_last_error(code)
						return 0
					proxy.GetFileInformationByHandleEx.side_effect = fail
					with patch.object(windows, 'api', return_value=proxy):
						if code == 5:
							with self.assertRaises(PermissionError):
								windows.case_sensitive(temporary)
						else:
							self.assertIsNone(windows.case_sensitive(temporary))

	def test_shared_file_ancestry_is_resolved_once_for_new_and_existing_targets(self):
		with plugin_module(), TemporaryDirectory() as temporary:
			engine = import_module('robocopy_plugin.engine')
			root = Path(temporary).resolve()
			source, destination = root / 'source', root / 'target'
			source.mkdir()
			names = tuple('file%02d.txt' % index for index in range(32))
			for name in names:
				(source / name).write_bytes(b'')
			for populated in (False, True):
				if populated:
					destination.mkdir()
					for name in names:
						(destination / name).write_bytes(b'old')
				with patch.object(engine, 'canonical', wraps=engine.canonical) as canonical, \
						patch.object(engine.windows, 'filenames', wraps=engine.windows.filenames) as filenames:
					plan = engine.prepare(as_url(source), tuple(as_url(source / name) for name in names),
						str(destination), 'robocopy', engine.Settings())
					self.assertEqual(2, canonical.call_count)
					filenames.assert_called_once()
					self.assertEqual(names, plan.jobs[0].filenames)

	def test_case_sensitive_and_short_alias_selection_refused(self):
		with plugin_module(), TemporaryDirectory() as temporary:
			engine = import_module('robocopy_plugin.engine')
			root = Path(temporary).resolve()
			(root / 'file.txt').write_bytes(b'keep')
			arguments = (as_url(root), (as_url(root / 'file.txt'),), str(root / 'destination'), 'robocopy', engine.Settings())
			with patch.object(engine.windows, 'case_sensitive', return_value=True), self.assertRaisesRegex(ValueError, 'case-sensitive'):
				engine.prepare(*arguments)
			def alias_names(*args):
				yield 'a different long name.txt', 'file.txt'
			with patch.object(engine.windows, 'filenames', side_effect=alias_names), \
					self.assertRaisesRegex(ValueError, '8.3 alias'):
				engine.prepare(*arguments)
			def ambiguous_names(*args):
				yield 'file.txt', ''
				yield 'FILE.txt', ''
			with patch.object(engine.windows, 'case_sensitive', return_value=None), \
					patch.object(engine.windows, 'filenames', side_effect=ambiguous_names), self.assertRaisesRegex(ValueError, 'Ambiguous'):
				engine.prepare(*arguments)
			self.assertFalse((root / 'destination').exists())

	def test_typed_settings_refuse_unsafe_options(self):
		with plugin_module():
			engine = import_module('robocopy_plugin.engine')
			self.assertEqual(8, engine.Settings.load({}).threads)
			for value in ({'threads': True}, {'threads': 33}, {'retries': -1}, {'raw': '/MIR'},
					{'open_log_on_finish': True}, {'log_enabled': 1}):
				with self.subTest(value=value), self.assertRaises(ValueError):
					engine.Settings.load(value)

	def test_mixed_selection_maps_exact_jobs(self):
		with plugin_module(), TemporaryDirectory() as directory:
			engine = import_module('robocopy_plugin.engine')
			root = Path(directory)
			source, destination = root / 'source', root / 'destination'
			source.mkdir()
			(source / 'a.txt').write_bytes(b'a')
			(source / 'other.txt').write_bytes(b'keep')
			(source / 'Photos').mkdir()
			plan = engine.prepare(as_url(source), (as_url(source / 'a.txt'), as_url(source / 'Photos')),
				str(destination), 'C:\\Windows\\System32\\robocopy.exe', engine.Settings())
			self.assertEqual(2, len(plan.jobs))
			self.assertEqual(('a.txt',), plan.jobs[0].filenames)
			self.assertEqual(str(destination / 'Photos'), plan.jobs[1].destination)
			self.assertFalse(destination.exists())

	def test_batches_fit_quoted_utf16_budget(self):
		with plugin_module():
			engine = import_module('robocopy_plugin.engine')
			entries = tuple(engine.Source('C:\\source\\' + name, name, False, (1, index, 0))
				for index, name in enumerate('file %d \U0001f600.txt' % index for index in range(40)))
			settings = engine.Settings()
			jobs = engine.build_jobs('C:\\source', 'C:\\destination', entries, 'C:\\Windows\\robocopy.exe',
				settings, limit=300)
			self.assertGreater(len(jobs), 1)
			self.assertEqual(tuple(entry.name for entry in entries), tuple(name for job in jobs for name in job.filenames))
			for job in jobs:
				self.assertLessEqual(engine.command_units(job.arguments('C:\\Windows\\robocopy.exe', settings)), 300)

	def test_invalid_paths_and_hyphen_names_fail_before_creation(self):
		with plugin_module(), TemporaryDirectory() as directory:
			engine = import_module('robocopy_plugin.engine')
			for path in ('relative', 'C:relative', 'file://C:/folder', 'C:\\file:stream', '\\\\?\\C:\\folder'):
				with self.subTest(path=path), self.assertRaises(ValueError):
					engine.absolute_path(path)
			root = Path(directory)
			(root / '-file.txt').write_bytes(b'keep')
			with self.assertRaisesRegex(ValueError, 'hyphen'):
				engine.prepare(as_url(root), (as_url(root / '-file.txt'),), str(root / 'new'), 'robocopy', engine.Settings())
			self.assertFalse((root / 'new').exists())


class RobocopyLogTest(TestCase):
	def test_placeholder_tags_allow_log_writes_but_retention_skips_reparse_files(self):
		from types import SimpleNamespace
		with plugin_module(), TemporaryDirectory() as temporary:
			logs = import_module('robocopy_plugin.logs')
			root = Path(temporary).resolve()
			lstat = logs.os.lstat
			def placeholder(path):
				info = lstat(path)
				return SimpleNamespace(st_mode=info.st_mode, st_size=info.st_size, st_dev=info.st_dev,
					st_ino=info.st_ino, st_nlink=info.st_nlink, st_file_attributes=0x400, st_reparse_tag=0x9000001A)
			with patch.object(logs.os, 'lstat', side_effect=placeholder):
				first = logs.TransferLog(logs.choose_path(root), 'Cloud attribute fixture')
				first.finish('Finished')
				second = logs.TransferLog(logs.choose_path(root), 'Current')
				second.finish('Finished')
				second.prune(1)
				self.assertTrue(first.path.exists())
				self.assertIn('Finished', second.path.read_text(encoding='utf-16'))
			for tag in (0xA0000003, 0xA000000C):
				info = placeholder(root)
				info.st_reparse_tag = tag
				with patch.object(logs.os, 'lstat', return_value=info), self.assertRaises(OSError):
					logs.safe_directory(root)

	def test_log_is_unicode_exclusive_and_prunes_only_finished_owned_files(self):
		with plugin_module(), TemporaryDirectory() as temporary:
			logs = import_module('robocopy_plugin.logs')
			first = logs.TransferLog(logs.choose_path(temporary), 'First')
			first.append('Unicode \u00e9tude')
			first.finish('Completed')
			second = logs.TransferLog(logs.choose_path(temporary), 'Second')
			second.finish('Canceled')
			unfinished = logs.TransferLog(logs.choose_path(temporary), 'Still active')
			unrelated = first.path.parent / 'notes.txt'
			unrelated.write_text('keep')
			second.prune(1)
			self.assertFalse(first.path.exists())
			self.assertTrue(second.path.exists())
			self.assertTrue(unfinished.path.exists())
			self.assertTrue(unrelated.exists())
			self.assertIn('Canceled', second.path.read_text(encoding='utf-16'))
			with self.assertRaises(FileExistsError):
				logs.TransferLog(str(second.path), 'Do not overwrite')

	def test_log_rejects_incomplete_native_output(self):
		with plugin_module(), TemporaryDirectory() as temporary:
			logs = import_module('robocopy_plugin.logs')
			log = logs.TransferLog(logs.choose_path(temporary), 'Header')
			with log.path.open('ab') as output:
				output.write(b'x')
			with self.assertRaises(OSError):
				log.append('Must not mask malformed output')


class RobocopyCommandTest(TestCase):
	def test_progress_uses_captured_job_not_raw_native_columns(self):
		with plugin_module() as plugin:
			engine = import_module('robocopy_plugin.engine')
			entry = engine.Source('C:\\source\\folder', 'VeryLongFolder' * 20, True, (1, 2, 3))
			job = engine.Job(entry.path, 'D:\\target\\folder', (entry,))
			task = plugin._Transfer('Robocopy', '', (), '', engine.Settings(), False, Event())
			task.plan = Mock(jobs=(job, job))
			task.current_job = job
			task.started_at = 0
			with patch.object(plugin, 'monotonic', return_value=70), patch.object(task, 'set_text') as text:
				task.activity('\tNew File\t82150C:\\misdecoded\ufffd\x00path')
				message = text.call_args.args[0]
			self.assertEqual('Copying | Job 1/2 (approximate) | 01:10', message.splitlines()[0])
			self.assertLessEqual(len(message.splitlines()[1]), 36)
			self.assertIn('...', message)
			for raw in ('New File', '82150', '\ufffd', '\x00', '\t'):
				self.assertNotIn(raw, message)
			task.current_job = engine.Job('C:\\source', 'D:\\target', (entry,), ('one.txt', 'two.txt'))
			with patch.object(task, 'set_text') as text:
				task.activity('')
				self.assertIn('Files: 2 selected', text.call_args.args[0])

	def test_completion_status_is_one_line_without_log_or_diagnostics(self):
		with plugin_module() as plugin:
			engine = import_module('robocopy_plugin.engine')
			task = plugin._Transfer('Robocopy', '', (), '', engine.Settings(), True, Event())
			task.plan = Mock(jobs=(Mock(),))
			task.codes.append(1)
			task.log = Mock(path=Path('C:/settings/' + 'long-path' * 100 + '.txt'))
			task.tail = '\ufffdgarbled native output'
			with patch.object(plugin.fman, 'show_status_message') as status:
				plugin._present(task, plugin.ui.UiOwner(), Event())
			message = status.call_args.args[0]
			self.assertEqual('Robocopy: 1/1 jobs finished | Copied files | Exit 1', message)
			self.assertNotIn('\n', message)
			self.assertLess(len(message), 120)

	def test_extra_only_merge_uses_status_but_mismatches_and_failures_alert(self):
		with plugin_module() as plugin:
			engine = import_module('robocopy_plugin.engine')
			for code in range(9):
				with self.subTest(code=code):
					task = plugin._Transfer('Robocopy', '', (), '', engine.Settings(), False, Event())
					task.plan = Mock(jobs=(Mock(),))
					task.codes.append(code)
					with patch.object(plugin.fman, 'show_status_message') as status, patch.object(plugin.fman, 'show_alert') as alert:
						plugin._present(task, plugin.ui.UiOwner(), Event())
						self.assertEqual(int(code < 4), status.call_count)
						self.assertEqual(int(code >= 4), alert.call_count)
						if code in (2, 3):
							self.assertIn('extra destination entries', status.call_args.args[0])

	def test_late_cancel_keeps_reaped_copy_and_move_receipt(self):
		for move in (False, True):
			with self.subTest(move=move), plugin_module() as plugin, TemporaryDirectory() as temporary:
				engine = import_module('robocopy_plugin.engine')
				root = Path(temporary).resolve()
				source = root / 'source'
				source.mkdir()
				(source / 'first.txt').write_bytes(b'completed')
				(source / 'Later').mkdir()
				closed = Event()
				task = plugin._Transfer('Robocopy', as_url(source),
					(as_url(source / 'first.txt'), as_url(source / 'Later')),
					str(root / 'target'), engine.Settings(log_enabled=True), move, closed)
				close = engine.windows.OwnedProcess.close
				def cancel_after_reap(process):
					close(process)
					closed.set()
				with patch.object(engine, 'probe'), patch.object(engine.windows.OwnedProcess, 'close', new=cancel_after_reap), \
						patch.object(plugin.fman, 'DATA_DIRECTORY', str(root / 'settings')), \
						patch.object(engine.windows, 'run', wraps=engine.windows.run) as run:
					task()
					run.assert_called_once()
				self.assertEqual([1], task.codes, task.summary())
				self.assertTrue(task.canceled)
				self.assertTrue(task.tail)
				self.assertIn('Exit 1:', task.log.path.read_text(encoding='utf-16'))
				self.assertIn('1/2 jobs finished; 1 remaining', task.summary())
				self.assertEqual(b'completed', (root / 'target' / 'first.txt').read_bytes())
				self.assertEqual(not move, (source / 'first.txt').exists())
				self.assertFalse((root / 'target' / 'Later').exists())
				if move:
					self.assertEqual(0, task.checked_roots)
					self.assertIn('Selected roots not checked: 2', task.summary())

	def test_failure_summary_never_invents_an_aggregate_exit_code(self):
		with plugin_module() as plugin:
			engine = import_module('robocopy_plugin.engine')
			task = plugin._Transfer('Copy with robocopy', '', (), '', engine.Settings(), False, Event())
			task.plan = Mock(jobs=(Mock(), Mock(), Mock()))
			task.codes.extend((1, 8))
			task.error = 'Stopped after native failure'
			self.assertIn('Last exit: 8', task.summary())
			self.assertNotIn('exit 9', task.summary())
			self.assertIn('2/3 jobs finished; 1 remaining', task.summary())

	def test_partial_move_cancellation_and_failed_job_prevent_later_jobs(self):
		with plugin_module() as plugin, TemporaryDirectory() as temporary:
			engine = import_module('robocopy_plugin.engine')
			root = Path(temporary).resolve()
			source = root / 'source'
			source.mkdir()
			(source / 'first.txt').write_bytes(b'first')
			(source / 'Later').mkdir()
			(source / 'Later' / 'keep.txt').write_bytes(b'keep')
			closed = Event()
			task = plugin._Transfer('Move with robocopy', as_url(source),
				(as_url(source / 'first.txt'), as_url(source / 'Later')), str(root / 'target'), engine.Settings(), True, closed)
			run = engine.windows.run
			def cancel_after_first(*args, **kwargs):
				result = run(*args, **kwargs)
				closed.set()
				return result
			with patch.object(engine, 'probe'), patch.object(engine.windows, 'run', side_effect=cancel_after_first) as launch:
				task()
				launch.assert_called_once()
			self.assertTrue(task.canceled)
			self.assertEqual(b'first', (root / 'target' / 'first.txt').read_bytes())
			self.assertFalse((source / 'first.txt').exists())
			self.assertTrue((source / 'Later' / 'keep.txt').exists())
			self.assertFalse((root / 'target' / 'Later').exists())
			closed.clear()
			(source / 'Never').mkdir()
			task = plugin._Transfer('Copy with robocopy', as_url(source), (as_url(source / 'Later'), as_url(source / 'Never')),
				str(root / 'failed'), engine.Settings(), False, closed)
			with patch.object(engine, 'probe'), patch.object(engine.windows, 'run', return_value=(8, 'native failure')) as launch:
				task()
				launch.assert_called_once()
			self.assertTrue(task.warning)
			self.assertIn('native failure', task.summary())
			self.assertIn('failure', task.error)

	def test_log_failure_before_and_after_first_job_never_retries_mutation(self):
		with plugin_module() as plugin, TemporaryDirectory() as temporary:
			engine = import_module('robocopy_plugin.engine')
			logs = import_module('robocopy_plugin.logs')
			root = Path(temporary).resolve()
			source = root / 'source'
			source.mkdir()
			(source / 'file.txt').write_bytes(b'copied')
			(source / 'Later').mkdir()
			def task():
				return plugin._Transfer('Copy with robocopy', as_url(source),
					(as_url(source / 'file.txt'), as_url(source / 'Later')), str(root / 'target'),
					engine.Settings(log_enabled=True), False, Event())
			with patch.object(plugin.fman, 'DATA_DIRECTORY', str(root / 'settings')), patch.object(engine, 'probe'):
				first = task()
				with patch.object(logs, 'TransferLog', side_effect=OSError('Log creation denied')), \
						patch.object(engine.windows, 'run') as run:
					first()
					run.assert_not_called()
				self.assertFalse((root / 'target').exists())
				second = task()
				append = logs.TransferLog.append
				def fail_footer(log, text):
					if text.startswith('Exit'):
						raise OSError('Disk full fixture')
					append(log, text)
				with patch.object(logs.TransferLog, 'append', new=fail_footer), \
						patch.object(engine.windows, 'run', wraps=engine.windows.run) as run:
					second()
					run.assert_called_once()
				self.assertEqual([1], second.codes)
				self.assertIn('Log writing failed after 1 finished jobs', second.error)
				self.assertEqual(b'copied', (root / 'target' / 'file.txt').read_bytes())
				self.assertFalse((root / 'target' / 'Later').exists())

	def test_viewer_runs_after_task_and_release_and_preserves_outcome_on_error(self):
		with plugin_module() as plugin:
			plugin.RobocopyOwner.owner = plugin.ui.UiOwner()
			pane, opposite = Mock(), Mock()
			pane.get_path.return_value = 'file://C:/source'
			pane.get_selected_files.return_value = ['file://C:/source/file.txt']
			opposite.get_path.return_value = 'file://D:/target'
			pane.window.get_panes.return_value = [pane, opposite]
			completed = Event()
			operations = []
			def submit(operation):
				self.assertEqual('C:\\typed', operation.destination)
				operation.log = Mock(path=Path('C:/settings/transfer.txt'))
				operation.codes.append(1)
				operation.plan = Mock(jobs=(Mock(),))
				operations.append(operation)
				completed.set()
			def open_log(path):
				self.assertTrue(completed.is_set())
				pane.on_closed.return_value.assert_not_called()
				release = plugin.ui.settings_resource('Robocopy operation').try_claim()
				self.assertIsNotNone(release)
				release()
				raise OSError('No association')
			with patch.object(plugin.fman, 'load_json', return_value={'log_enabled': True, 'open_log_on_finish': True}), \
					patch.object(plugin.fman, 'show_quicksearch', return_value=('C:\\typed', None)), \
					patch.object(plugin.fman, 'submit_task', side_effect=submit), \
					patch.object(plugin.os, 'startfile', side_effect=open_log) as viewer, \
					patch.object(plugin.fman, 'show_alert') as alert:
				plugin.CopyWithRobocopy(pane)()
				viewer.assert_called_once()
				self.assertIn('finished: 1/1', alert.call_args.args[0])
				self.assertIn('No association', alert.call_args.args[0])
				self.assertEqual('', operations[0].error)
			pane.on_closed.return_value.assert_called_once()

	def test_wizard_cancellation_has_no_probe_or_log_io(self):
		with plugin_module() as plugin:
			plugin.RobocopyOwner.owner = plugin.ui.UiOwner()
			pane = Mock()
			pane.get_path.return_value = 'file://C:/source'
			pane.get_selected_files.return_value = ['file://C:/source/file.txt']
			opposite = Mock()
			opposite.get_path.return_value = 'file://D:/target'
			pane.window.get_panes.return_value = [pane, opposite]
			with patch.object(plugin.fman, 'show_quicksearch', return_value=None) as wizard, \
					patch.object(plugin.fman, 'load_json', return_value={}), \
					patch.object(plugin.fman, 'submit_task') as submit:
				plugin.CopyWithRobocopy(pane)()
				submit.assert_not_called()
				self.assertEqual('D:\\target', wizard.call_args.kwargs['query'])
			release = plugin.ui.settings_resource('Robocopy operation').try_claim()
			self.assertIsNotNone(release)
			release()

	def test_draft_first_and_empty_selection_acceptance(self):
		with plugin_module() as plugin:
			items = list(plugin._destinations('C:\\typed', 'D:\\target', 'Copy with robocopy'))
			self.assertEqual(['C:\\typed', 'D:\\target'], [item.value for item in items])
			self.assertEqual(('Copy with robocopy',), plugin.CopyWithRobocopy.aliases)
			self.assertEqual(('Move with robocopy',), plugin.MoveWithRobocopy.aliases)

	def test_task_native_copy_logging_disabled_and_cancellation_text(self):
		with plugin_module() as plugin, TemporaryDirectory() as temporary:
			engine = import_module('robocopy_plugin.engine')
			root = Path(temporary).resolve()
			source, destination = root / 'source', root / 'destination'
			source.mkdir()
			(source / 'file.txt').write_bytes(b'copy')
			closed = Event()
			task = plugin._Transfer('Copy with robocopy', as_url(source), (as_url(source / 'file.txt'),),
				str(destination), engine.Settings(), False, closed)
			with patch.object(plugin.fman, 'DATA_DIRECTORY', str(root / 'settings')):
				task()
			self.assertFalse(task.warning, task.summary())
			self.assertEqual(b'copy', (destination / 'file.txt').read_bytes())
			self.assertFalse((root / 'settings').exists())
			self.assertEqual(0, task.get_size())
			closed.set()
			with patch.object(task, 'set_text') as text, self.assertRaises(task.Canceled):
				task.activity('Late output')
			text.assert_not_called()