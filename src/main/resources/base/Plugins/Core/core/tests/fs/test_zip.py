from errno import ENOENT
from core.fs.zip import ZipFileSystem, _7zip, _get_7zip_args_windows, \
	_7zipError, _7zipTaskWithProgress, Extract, _cleanup_extraction, \
	_tree_digest, UpdateArchive, Run7ZipViaWinpty, Run7ZipViaPty, \
	SevenZipFileSystem, TarFileSystem, Popen7Zip, _transfer_temp_directory
from core.fs.zip import _unpack_manifest
from core.fs.zip import Popen7ZipWindows, _run_7zip
from core.fileoperations import ArchiveUpdateError
from core.tests import StubFS
from contextlib import contextmanager
from datetime import date
from fman.url import as_url, join, as_human_readable, splitscheme
from fman import Task
from os import listdir
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Event, enumerate as enumerate_threads
from io import BytesIO
from unicodedata import normalize
from unittest import TestCase
from unittest.mock import Mock, patch
from zipfile import ZipFile, ZipInfo

import os
import os.path
import sys

class FakePipeProcess:
	def __init__(self, chunks=(), exit_code=0, quiet=False):
		self.chunks = chunks
		self.exit_code = exit_code
		self.quiet = quiet
		self.finished = Event()
		self.stdout = Mock()
		self.killed = False
		self.waited = False
	def output_chunks(self):
		if self.quiet:
			self.finished.wait(5)
		yield from self.chunks
		if not self.quiet:
			self.finished.set()
	def poll(self):
		return self.exit_code if self.finished.is_set() else None
	def kill(self):
		self.killed = True
		self.finished.set()
	def wait(self):
		if not self.finished.wait(5):
			raise AssertionError('Process not terminated')
		self.waited = True
		return self.exit_code

class UnpackExtractionTest(TestCase):
	def setUp(self):
		temporary = TemporaryDirectory()
		self.addCleanup(temporary.cleanup)
		self.root = Path(temporary.name)
		self.archive = self.root / 'Reports.zip'
		self.output = self.root / 'Reports'
		self.notification = patch('fman.fs.notify_file_added').start()
		self.addCleanup(patch.stopall)
	def create_task(self, entries):
		with ZipFile(self.archive, 'w') as writer:
			for name, contents in entries:
				writer.writestr(name, contents)
		self.original = self.archive.read_bytes()
		task = Extract(StubFS(), str(self.archive), '', str(self.output))
		task.require_new_directory(self.archive)
		return task
	def assert_rejected(self, task):
		with self.assertRaises(OSError):
			task()
		self.assertFalse(self.output.exists())
		self.assertEqual(self.original, self.archive.read_bytes())
		self.assertEqual([self.archive], list(self.root.iterdir()))
		self.notification.assert_not_called()
	def test_exact_tree_and_retained_source(self):
		task = self.create_task([('empty/', b''), ('nested/file.txt', b'payload')])
		task()
		self.assertEqual(b'payload', (self.output / 'nested/file.txt').read_bytes())
		self.assertEqual([], list((self.output / 'empty').iterdir()))
		self.assertEqual(self.original, self.archive.read_bytes())
		self.assertEqual({self.archive, self.output}, set(self.root.iterdir()))
		self.notification.assert_called_once_with(as_url(self.output))
	def test_colliding_entries_never_publish(self):
		for names in (('report.txt', 'REPORT.TXT'), ('same', 'same'), ('folder', 'folder/file'), ('a/file', 'A/other'),
			('report.txt', '../report.txt'), ('report.txt_', 'report.txt.'), ('_NUL.txt', 'NUL.txt')):
			with self.subTest(names=names):
				self.assert_rejected(self.create_task([(name, b'bytes') for name in names]))
	def test_names_that_7zip_may_rewrite_are_rejected(self):
		for name in ('../outside', '/absolute', 'C:/absolute', 'file:stream', 'NUL.txt', 'trailing.', 'a//b'):
			with self.subTest(name=name):
				task = self.create_task([(name, b'bytes')])
				with patch.object(task, 'run_7zip_with_progress') as extract:
					self.assert_rejected(task)
				extract.assert_not_called()
	def test_late_file_and_directory_survive(self):
		for directory in (False, True):
			with self.subTest(directory=directory):
				task = self.create_task([('file', b'new')])
				original_run = task.run_7zip_with_progress
				def extract(*args, **kwargs):
					original_run(*args, **kwargs)
					if directory:
						self.output.mkdir()
					else:
						self.output.write_bytes(b'existing')
				with patch.object(task, 'run_7zip_with_progress', side_effect=extract):
					with self.assertRaises(OSError):
						task()
				self.assertEqual(self.original, self.archive.read_bytes())
				self.notification.assert_not_called()
				if directory:
					self.assertEqual([], list(self.output.iterdir()))
					self.output.rmdir()
				else:
					self.assertEqual(b'existing', self.output.read_bytes())
					self.output.unlink()
	def test_cancellation_before_publication_cleans_staging(self):
		task = self.create_task([('file', b'bytes')])
		original_run = task.run_7zip_with_progress
		def extract(*args, **kwargs):
			original_run(*args, **kwargs)
			task.check_canceled = Mock(side_effect=Task.Canceled)
		with patch.object(task, 'run_7zip_with_progress', side_effect=extract):
			with self.assertRaises(Task.Canceled):
				task()
		self.assertEqual([self.archive], list(self.root.iterdir()))
		self.assertEqual(self.original, self.archive.read_bytes())
		self.notification.assert_not_called()
	def test_malformed_listing_fails_closed(self):
		for records in (['unexpected'], ['Folder = +'], ['Path = file', 'Folder = -', 'Folder = +']):
			with self.subTest(records=records), self.assertRaises(OSError):
				_unpack_manifest(records, lambda: None)
	def test_manifest_has_no_entry_depth_or_field_limits(self):
		def records():
			for index in range(100001):
				yield 'Path = file' + str(index)
				yield 'Folder = -'
				yield 'Size = 0'
		self.assertEqual(100001, len(_unpack_manifest(records(), lambda: None)))
		deep = '/'.join(['folder'] * 129)
		self.assertEqual((deep, True), _unpack_manifest(['Path = ' + deep, 'Folder = +'], lambda: None)[deep])
		self.assertEqual({'file': ('file', False)}, _unpack_manifest(
			['Path = file'] + ['Field%d = value' % index for index in range(65)], lambda: None))
	def test_manifest_ignores_non_naming_metadata(self):
		for metadata in ('Encrypted = +', 'Symbolic Link = target', 'Hard Link = target', 'Mode = lrwxrwxrwx', 'Size = unknown'):
			with self.subTest(metadata=metadata):
				self.assertEqual({'file': ('file', False)}, _unpack_manifest(['Path = file', metadata], lambda: None))
	def test_empty_archive(self):
		task = self.create_task([])
		task()
		self.assertEqual([], list(self.output.iterdir()))
	def test_native_7z_and_tar(self):
		with TemporaryDirectory() as fixture:
			Path(fixture, 'file.txt').write_bytes(b'payload')
			Path(fixture, 'empty').mkdir()
			for extension, backend_type in (('7z', SevenZipFileSystem), ('tar', TarFileSystem)):
				with self.subTest(extension=extension):
					archive = self.root / ('sample.' + extension)
					output = self.root / extension
					_run_7zip(['a', str(archive), 'file.txt', 'empty'], cwd=fixture)
					original = archive.read_bytes()
					backend = backend_type(StubFS(), {'.' + extension})
					archive_url = backend.scheme + splitscheme(as_url(archive))[1]
					task, = backend.prepare_copy(archive_url, as_url(output))
					task.require_new_directory(archive, output)
					task()
					self.assertEqual(b'payload', (output / 'file.txt').read_bytes())
					self.assertTrue((output / 'empty').is_dir())
					self.assertEqual(original, archive.read_bytes())
	def test_overlapping_suffix_does_not_extract_wrong_source(self):
		self.create_task([('file', b'payload')])
		selected = self.root / 'Reports.zipx'
		selected.write_bytes(self.original)
		backend = ZipFileSystem(StubFS(), ('.zip', '.zipx'))
		archive_url = backend.scheme + splitscheme(as_url(selected))[1]
		task, = backend.prepare_copy(archive_url, as_url(self.output))
		with self.assertRaisesRegex(OSError, 'selected archive root'):
			task.require_new_directory(selected, self.output)
		self.assertEqual(self.original, selected.read_bytes())
		self.assertEqual(self.original, self.archive.read_bytes())
		self.assertFalse(self.output.exists())
	def test_tar_symlink_uses_7zip_behavior(self):
		from tarfile import open as open_tar, TarInfo, SYMTYPE
		archive = self.root / 'linked.tar'
		with open_tar(archive, 'w') as writer:
			file_info = TarInfo('file')
			file_info.size = 7
			writer.addfile(file_info, BytesIO(b'payload'))
			link_info = TarInfo('link')
			link_info.type = SYMTYPE
			link_info.linkname = 'file'
			writer.addfile(link_info)
		original = archive.read_bytes()
		task = Extract(StubFS(), str(archive), '', str(self.output))
		task.require_new_directory(archive)
		try:
			task()
		except OSError as error:
			if isinstance(error.__cause__, _7zipError) and 'privilege' in str(error).lower():
				self.skipTest('7-Zip symlink creation requires Windows privilege')
			raise
		self.assertEqual(b'payload', (self.output / 'file').read_bytes())
		self.assertEqual(original, archive.read_bytes())
	def test_corrupt_archive_retained_without_output(self):
		task = self.create_task([('file', b'payload')])
		self.original = b'not an archive'
		self.archive.write_bytes(self.original)
		self.assert_rejected(task)
	def test_encrypted_archive_retained_without_prompt(self):
		with TemporaryDirectory() as fixture:
			Path(fixture, 'file.txt').write_bytes(b'payload')
			_run_7zip(['a', '-pfixture', str(self.archive), 'file.txt'], cwd=fixture)
		self.original = self.archive.read_bytes()
		task = Extract(StubFS(), str(self.archive), '', str(self.output))
		task.require_new_directory(self.archive)
		with patch.object(task, 'run_7zip_with_progress', wraps=task.run_7zip_with_progress) as extract:
			self.assert_rejected(task)
		extract.assert_called_once()
	def test_output_root_must_remain_a_directory(self):
		task = self.create_task([('file', b'payload')])
		def replace_output(args, **kwargs):
			output = Path(next(argument[2:] for argument in args if argument.startswith('-o')))
			output.rmdir()
			output.write_bytes(b'not a directory')
		with patch.object(task, 'run_7zip_with_progress', side_effect=replace_output):
			self.assert_rejected(task)
	def test_no_archive_copy_or_output_rescan(self):
		task = self.create_task([('file', b'payload')])
		with patch('core.fs.zip.open', create=True, side_effect=AssertionError('Archive copy')), \
			patch.object(Path, 'open', side_effect=AssertionError('Snapshot or verification read')), \
			patch.object(Path, 'iterdir', side_effect=AssertionError('Output rescan')):
			task()
		self.assertEqual(b'payload', (self.output / 'file').read_bytes())
		self.assertEqual(self.original, self.archive.read_bytes())
	def test_source_stat_change_prevents_publication(self):
		task = self.create_task([('file', b'payload')])
		original_run = task.run_7zip_with_progress
		def change_source(*args, **kwargs):
			original_run(*args, **kwargs)
			self.archive.write_bytes(b'external change')
		with patch.object(task, 'run_7zip_with_progress', side_effect=change_source):
			with self.assertRaisesRegex(OSError, 'Archive changed while being read'):
				task()
		self.assertEqual(b'external change', self.archive.read_bytes())
		self.assertEqual([self.archive], list(self.root.iterdir()))
		self.notification.assert_not_called()
	def test_dangling_destination_symlink_is_retained(self):
		task = self.create_task([('file', b'payload')])
		try:
			self.output.symlink_to(self.root / 'missing', target_is_directory=True)
		except OSError:
			self.skipTest('Windows symlink privilege unavailable')
		with self.assertRaises(FileExistsError):
			task()
		self.assertTrue(self.output.is_symlink())
		self.assertEqual(self.original, self.archive.read_bytes())
	def test_preflight_and_late_dangling_junction_survive(self):
		from subprocess import run
		for late in (False, True):
			with self.subTest(late=late):
				task = self.create_task([('file', b'payload')])
				target = self.root / 'junction-target'
				target.mkdir()
				def create_junction():
					result = run(['cmd.exe', '/c', 'mklink', '/J', str(self.output), str(target)], capture_output=True)
					if result.returncode:
						self.skipTest('Junction creation unavailable: ' + repr(result.stderr))
					target.rmdir()
				if late:
					original_run = task.run_7zip_with_progress
					def extract(*args, **kwargs):
						original_run(*args, **kwargs)
						create_junction()
					with patch.object(task, 'run_7zip_with_progress', side_effect=extract):
						with self.assertRaises(OSError):
							task()
				else:
					create_junction()
					with self.assertRaises(OSError):
						task()
				self.assertTrue(self.output.is_junction())
				self.assertEqual(self.original, self.archive.read_bytes())
				self.output.rmdir()

class ArchiveProcessTest(TestCase):
	def test_unpack_rejects_wrong_archive_or_member(self):
		with TemporaryDirectory() as directory:
			selected = Path(directory, 'selected.zip')
			other = Path(directory, 'other.zip')
			selected.touch()
			other.touch()
			for archive, member in ((other, ''), (selected, 'member')):
				with self.subTest(archive=archive.name, member=member):
					task = Extract(Mock(), str(archive), member, str(Path(directory, 'out')))
					with self.assertRaisesRegex(OSError, 'selected archive root'):
						task.require_new_directory(selected)
	def test_unpack_existing_output_never_extracts(self):
		with TemporaryDirectory() as directory:
			archive = Path(directory, 'source.zip')
			archive.touch()
			output = Path(directory, 'out')
			output.mkdir()
			task = Extract(Mock(), str(archive), '', str(output))
			task.require_new_directory(archive)
			with patch.object(task, 'run_7zip_with_progress') as extract:
				with self.assertRaises(FileExistsError):
					task()
			extract.assert_not_called()
			self.assertTrue(output.is_dir())
	def test_outer_cleanup_preserves_mandatory_stop(self):
		temporary = Mock()
		temporary.name = 'temporary-output'
		temporary.cleanup.side_effect = PermissionError('locked')
		error = ArchiveUpdateError(5, 'update failed')
		with patch('core.fs.zip.TemporaryDirectory', return_value=temporary):
			with self.assertRaises(ArchiveUpdateError) as caught:
				with _transfer_temp_directory(Mock()):
					raise error
		self.assertIs(error, caught.exception)
		self.assertEqual(3, temporary.cleanup.call_count)
	def test_real_quiet_child_is_terminated(self):
		children = []
		ready = Event()
		def spawn(args, cwd):
			code = "from threading import Event; print('READY', flush=True); Event().wait(30)"
			process = Popen7Zip(['-c', code], cwd,
				None, encoding='utf-8')
			children.append(process)
			return process
		def check():
			if ready.is_set():
				raise Task.Canceled()
		with patch('core.fs.zip._7ZIP_BINARY', sys.executable), \
			patch('core.fs.zip.Popen7ZipWindows', side_effect=spawn):
			with self.assertRaises(Task.Canceled):
				with _7zip([]) as command:
					for record in command.progress_records(check):
						if record == 'READY':
							ready.set()
		self.assertTrue(ready.is_set())
		self.assertIsNotNone(children[0].poll())
		self.assertTrue(children[0].stdout.closed)
	def test_cancel_after_eof_before_exit(self):
		class EarlyEof(FakePipeProcess):
			def output_chunks(self):
				return iter(())
		process = EarlyEof()
		checks = []
		def check():
			checks.append(True)
			if len(checks) >= 2:
				raise Task.Canceled()
		with patch('core.fs.zip.Popen7ZipWindows', return_value=process):
			with self.assertRaises(Task.Canceled):
				with _7zip(['x']) as command:
					list(command.progress_records(check))
		self.assertTrue(process.killed)
		self.assertTrue(process.waited)
	def test_cancel_during_mutation_does_not_kill_child(self):
		task = _7zipTaskWithProgress('Updating', size=100)
		class CancelOutput(FakePipeProcess):
			def output_chunks(self):
				task._dialog._was_canceled = True
				yield from super().output_chunks()
		process = CancelOutput(['10% item\r', '100% item\n'])
		with patch('core.fs.zip.Popen7ZipWindows', return_value=process), \
			patch.object(task, 'set_text') as set_text:
			task.run_7zip_with_progress(['d'], pty=False, cancellable=False)
			self.assertTrue(any('Canceling after' in call.args[0] for call in set_text.call_args_list))
		self.assertFalse(process.killed)
		self.assertEqual(100, task.get_progress())
	def test_progress_is_monotonic_and_capped(self):
		task = _7zipTaskWithProgress('Extracting', size=100)
		process = FakePipeProcess(['0%\r50% item\r20% item\r100% item\n'])
		with patch('core.fs.zip.Popen7ZipWindows', return_value=process), \
			patch.object(task, 'set_progress', wraps=task.set_progress) as set_progress:
			task.run_7zip_with_progress(['x'], pty=False, progress_limit=99)
			self.assertEqual([50, 99], [call.args[0] for call in set_progress.call_args_list])
	def test_existing_pty_readers(self):
		process = Mock()
		process.read.side_effect = ['\x1b[0m 10% file\r', EOFError()]
		self.assertEqual([' 10% file\r'], list(Run7ZipViaWinpty.Stdout(process)))
		reader = object.__new__(Run7ZipViaPty.Stdout)
		reader._encoding = 'utf-8'
		reader._source = BytesIO(b' 10% file\b\b\b\b\b\b\b\b\b 20% file\n')
		self.assertIn(' 10% file', list(reader))
	def test_verification_failure_does_not_publish(self):
		with TemporaryDirectory() as directory:
			filesystem = Mock()
			task = Extract(filesystem, 'source.zip', '', str(Path(directory, 'out')),
				expected_digest=b'wrong')
			with patch.object(task, 'run_7zip_with_progress'):
				with self.assertRaisesRegex(OSError, 'failed verification'):
					task()
			filesystem.move.assert_not_called()
			self.assertEqual([], list(Path(directory).iterdir()))
	def test_extract_cancel_and_warning_do_not_publish(self):
		for error in (Task.Canceled(), _7zipError(1, ['x'], 'warning')):
			with self.subTest(error=type(error).__name__), TemporaryDirectory() as directory:
				filesystem = Mock()
				task = Extract(filesystem, 'source.zip', '', str(Path(directory, 'out')))
				with patch.object(task, 'run_7zip_with_progress', side_effect=error):
					with self.assertRaises((Task.Canceled, OSError)):
						task()
				filesystem.move.assert_not_called()
				self.assertEqual([], list(Path(directory).iterdir()))
	def test_cancel_before_publication(self):
		with TemporaryDirectory() as directory:
			task = Extract(Mock(), 'source.zip', '', str(Path(directory, 'out')))
			def cancel(*args, **kwargs):
				task._dialog._was_canceled = True
			with patch.object(task, 'run_7zip_with_progress', side_effect=cancel):
				with self.assertRaises(Task.Canceled):
					task()
			task._fman_fs.move.assert_not_called()
			self.assertEqual([], list(Path(directory).iterdir()))
	def test_cleanup_failure_preserves_cancellation(self):
		task = Mock()
		temporary = Mock(name='temporary')
		temporary.name = 'temporary-output'
		temporary.cleanup.side_effect = PermissionError('locked')
		error = Task.Canceled()
		with self.assertRaises(Task.Canceled) as caught:
			try:
				raise error
			finally:
				_cleanup_extraction(task, temporary)
		self.assertIs(error, caught.exception)
		self.assertEqual(3, temporary.cleanup.call_count)
		task.show_alert.assert_called_once()
	def test_split_records_and_bounded_diagnostics(self):
		process = FakePipeProcess([' 1', '0% file\b\b 20%', ' file\r',
			' 100% done\n', 'x' * 10000 + '\n'] * 120)
		with patch('core.fs.zip.Popen7ZipWindows', return_value=process):
			with _7zip(['x'], allow_warning=False) as command:
				records = list(command.progress_records(lambda: None))
			self.assertIn(' 10% file', records)
			self.assertIn(' 20% file', records)
			self.assertLessEqual(max(map(len, records)), 4096)
			self.assertEqual(100, len(command._stdout_lines))
		self.assertFalse(process.killed)
		self.assertTrue(process.waited)
		process.stdout.close.assert_called_once()
	def test_listing_preserves_long_names_and_bounded_diagnostics(self):
		prefix = 'segment/' * 600
		paths = [prefix + 'first', prefix + 'second']
		text = ''.join('Path = ' + path + '\nFolder = -\n' for path in paths)
		process = FakePipeProcess([text[index:index + 4096] for index in range(0, len(text), 4096)])
		with patch('core.fs.zip.Popen7ZipWindows', return_value=process):
			with _7zip(['l'], allow_warning=False) as command:
				manifest = _unpack_manifest(command.progress_records(lambda: None, truncate=False), lambda: None)
			self.assertTrue(all(path in manifest for path in paths))
			self.assertLessEqual(max(map(len, command._stdout_lines)), 4096)
		process.stdout.close.assert_called_once()
	def test_cancel_quiet_process_reaps_and_joins(self):
		process = FakePipeProcess(quiet=True)
		checks = []
		def check():
			checks.append(True)
			if len(checks) == 2:
				raise Task.Canceled()
		with patch('core.fs.zip.Popen7ZipWindows', return_value=process):
			with self.assertRaises(Task.Canceled):
				with _7zip(['x']) as command:
					list(command.progress_records(check))
		self.assertTrue(process.killed)
		self.assertTrue(process.waited)
		self.assertFalse(any(thread.name == '7zip-output' for thread in enumerate_threads()))
		process.stdout.close.assert_called_once()
	def test_warning_policy_is_explicit(self):
		for allow_warning in (True, False):
			process = FakePipeProcess(exit_code=1)
			with self.subTest(allow_warning=allow_warning), \
				patch('core.fs.zip.Popen7ZipWindows', return_value=process):
				def run():
					with _7zip(['x'], allow_warning=allow_warning) as command:
						list(command.progress_records(lambda: None))
				if allow_warning:
					run()
				else:
					with self.assertRaises(_7zipError):
						run()

class SevenZipExecutableTest(TestCase):
	def test_cancel_real_extraction_cleans_staging(self):
		with TemporaryDirectory() as directory:
			archive = Path(directory, 'cancel.zip')
			with ZipFile(archive, 'w') as writer:
				writer.writestr('payload.bin', b'x' * (16 * 1024 * 1024))
			task = Extract(StubFS(), str(archive), '', str(Path(directory, 'out')))
			children = []
			def spawn(args, cwd):
				process = Popen7ZipWindows(args, cwd)
				children.append(process)
				original = process.output_chunks
				def output():
					for chunk in original():
						task._dialog._was_canceled = True
						yield chunk
				process.output_chunks = output
				return process
			with patch('core.fs.zip.Popen7ZipWindows', side_effect=spawn):
				with self.assertRaises(Task.Canceled):
					task()
			self.assertEqual(['cancel.zip'], os.listdir(directory))
			self.assertIsNotNone(children[0].poll())
			self.assertTrue(children[0].stdout.closed)
	def test_copy_verification_preserves_contents(self):
		with TemporaryDirectory() as directory:
			root = Path(directory)
			archive = root / 'copy.zip'
			with ZipFile(archive, 'w') as writer:
				writer.writestr('payload.bin', b'verified payload')
			_run_7zip(['x', str(archive), '-o' + str(root / 'baseline')])
			Extract(StubFS(), str(archive), '', str(root / 'verified'), verify_output=True)()
			self.assertEqual(_tree_digest(root / 'baseline', lambda: None),
				_tree_digest(root / 'verified', lambda: None))

	def test_multi_item_move_hash_read_budget(self):
		with TemporaryDirectory() as directory:
			root = Path(directory)
			archive, output = root / 'move.zip', root / 'output'
			output.mkdir()
			payload, retained = b'moved payload', b'retained payload'
			names = ('first.bin', 'second.bin')
			with ZipFile(archive, 'w') as writer:
				for name in names:
					writer.writestr(name, payload)
				writer.writestr('retained.bin', retained)
			filesystem = ZipFileSystem(StubFS(), {'.zip'})
			original_open = Path.open
			read_bytes = {'archive': 0, 'output': 0}
			@contextmanager
			def counted_open(path, *args, **kwargs):
				with original_open(path, *args, **kwargs) as stream:
					def read(*read_args):
						data = stream.read(*read_args)
						read_bytes['archive' if path == archive else 'output'] += len(data)
						return data
					proxy = Mock(wraps=stream)
					proxy.read.side_effect = read
					yield proxy
			def measured_digest(path, check):
				with patch.object(Path, 'open', counted_open):
					return _tree_digest(path, check)
			for name in names:
				read_bytes.update(archive=0, output=0)
				archive_size = archive.stat().st_size
				with patch('core.fs.zip._tree_digest', side_effect=measured_digest):
					filesystem.move(as_url(archive, 'zip://') + '/' + name, as_url(output / name))
				self.assertEqual(dict(archive=2 * archive_size, output=2 * len(payload)), read_bytes)
				self.assertEqual(payload, (output / name).read_bytes())
			with ZipFile(archive) as reader:
				self.assertEqual(['retained.bin'], reader.namelist())
				self.assertEqual(retained, reader.read('retained.bin'))
			self.assertEqual(set(names), {path.name for path in output.iterdir()})
			self.assertEqual({'move.zip', 'output'}, {path.name for path in root.iterdir()})

	def test_real_7z_and_tar_extraction(self):
		for suffix, filesystem_type in (('.7z', SevenZipFileSystem), ('.tar', TarFileSystem)):
			with self.subTest(suffix=suffix), TemporaryDirectory() as directory:
				root = Path(directory)
				source = root / 'source'
				(source / 'empty').mkdir(parents=True)
				(source / 'data.txt').write_text('verified payload')
				archive = root / ('archive' + suffix)
				with _7zip(['a', '-bsp1', str(archive), 'source'], cwd=directory,
					allow_warning=False) as command:
					list(command.progress_records(lambda: None))
				filesystem = filesystem_type(StubFS(), {suffix})
				output = root / 'out'
				filesystem.copy(as_url(archive, filesystem.scheme), as_url(output))
				self.assertEqual(_tree_digest(source, lambda: None),
					_tree_digest(output / 'source', lambda: None))
	def test_extract_pipe_progress(self):
		with TemporaryDirectory() as directory:
			archive = Path(directory, 'progress.zip')
			with ZipFile(archive, 'w') as writer:
				writer.writestr('payload.bin', b'x' * (16 * 1024 * 1024))
			output = Path(directory, 'output')
			with _7zip(['x', '-bsp1', '-y', str(archive), '-o' + str(output)],
				allow_warning=False) as command:
				records = list(command.progress_records(lambda: None))
			self.assertTrue(any('%' in record for record in records), records)
			self.assertEqual(16 * 1024 * 1024, (output / 'payload.bin').stat().st_size)
			print('7-Zip pipe progress:', [record for record in records if '%' in record])
	def test_windows_output_encoding_is_utf8(self):
		self.assertEqual(
			['-sccUTF-8', 'l', 'archive.zip'],
			_get_7zip_args_windows(['l', 'archive.zip'])
		)
	def test_create_archive_through_application_wrapper(self):
		with TemporaryDirectory() as temporary_directory:
			source = Path(temporary_directory, 'smoke-test.txt')
			source.write_text('7za works', encoding='utf-8')
			archive = Path(temporary_directory, 'smoke-test.zip')
			with _7zip(
				['a', str(archive), source.name],
				cwd=temporary_directory, pty=True
			) as process:
				list(process.stdout_lines)
			with ZipFile(archive) as zip_file:
				self.assertEqual(['smoke-test.txt'], zip_file.namelist())
				self.assertEqual(b'7za works', zip_file.read('smoke-test.txt'))

class ZipFileSystemTest(TestCase):
	def test_move_rejects_source_rewrite_with_unchanged_stat(self):
		with TemporaryDirectory() as directory:
			archive = Path(directory, 'source.zip')
			output = Path(directory, 'output')
			entry = ZipInfo('item.txt')
			with ZipFile(archive, 'w') as writer:
				writer.writestr(entry, b'original')
			before = archive.stat()
			original = Extract.__call__
			def extract(task):
				original(task)
				with ZipFile(archive, 'w') as writer:
					writer.writestr(entry, b'changed!')
				os.utime(archive, ns=(before.st_atime_ns, before.st_mtime_ns))
				after = archive.stat()
				for field in ('st_dev', 'st_ino', 'st_size', 'st_mtime_ns'):
					self.assertEqual(getattr(before, field), getattr(after, field), field)
			with patch.object(Extract, '__call__', extract):
				with self.assertRaisesRegex(OSError, 'Source archive changed'):
					self._fs.move(as_url(archive, 'zip://') + '/item.txt', as_url(output))
			self.assertEqual(b'original', output.read_bytes())
			with ZipFile(archive) as reader:
				self.assertEqual(b'changed!', reader.read('item.txt'))
	def test_move_rejects_changed_published_output(self):
		with TemporaryDirectory() as directory:
			output = Path(directory, 'output')
			before = Path(self._zip).read_bytes()
			original = self._fs._fs.move
			def publish(source, destination):
				original(source, destination)
				if destination == as_url(output):
					output.write_bytes(b'changed after publication')
			with patch.object(self._fs._fs, 'move', side_effect=publish):
				with self.assertRaisesRegex(OSError, 'Extracted output failed verification'):
					self._fs.move(self._url('ZipFileTest/file.txt'), as_url(output))
			self.assertEqual(before, Path(self._zip).read_bytes())
			self.assertEqual(b'changed after publication', output.read_bytes())
	def test_cancel_after_deletion_finishes_empty_parent_restoration(self):
		with TemporaryDirectory() as directory:
			path = 'ZipFileTest/Directory/Subdirectory/file 3.txt'
			root = self._fs.prepare_move(self._url(path), as_url(Path(directory, 'out')))[0]
			original = _7zipTaskWithProgress.run_7zip_with_progress
			def run(task, args, **kwargs):
				result = original(task, args, **kwargs)
				if isinstance(task, UpdateArchive) and args[0] == 'd':
					root._dialog._was_canceled = True
				return result
			with patch.object(_7zipTaskWithProgress, 'run_7zip_with_progress', run):
				with self.assertRaises(Task.Canceled):
					root()
			self.assertTrue(Path(directory, 'out').exists())
			self.assertFalse(self._fs.exists(self._path(path)))
			self.assertTrue(self._fs.is_dir(self._path('ZipFileTest/Directory/Subdirectory')))
	def test_move_literal_at_prefixed_entry(self):
		with ZipFile(self._zip, 'a') as writer:
			writer.writestr('@input.txt', 'literal entry')
		with TemporaryDirectory() as directory:
			archive = Path(directory, 'destination.zip')
			self._fs.move(self._url('@input.txt'), as_url(archive, 'zip://') + '/@output.txt')
			with ZipFile(archive) as reader:
				self.assertEqual(b'literal entry', reader.read('@output.txt'))
			with ZipFile(self._zip) as reader:
				self.assertNotIn('@input.txt', reader.namelist())
	def test_extract_cannot_overwrite_source_archive(self):
		before = Path(self._zip).read_bytes()
		with self.assertRaisesRegex(OSError, 'source archive'):
			self._fs.copy(self._url('ZipFileTest/file.txt'), as_url(self._zip))
		self.assertEqual(before, Path(self._zip).read_bytes())
	def test_extract_late_directory_conflict_retains_existing(self):
		with TemporaryDirectory() as directory:
			destination = Path(directory, 'Output')
			task = self._fs.prepare_copy(self._url('ZipFileTest/Directory'), as_url(destination))[0]
			run = task.run_7zip_with_progress
			def race(*args, **kwargs):
				run(*args, **kwargs)
				destination.mkdir()
				(destination / 'keep.txt').write_text('keep')
			with patch.object(task, 'run_7zip_with_progress', side_effect=race):
				with self.assertRaises(OSError):
					task()
			self.assertEqual(['keep.txt'], os.listdir(destination))
			self.assertEqual(['Output'], os.listdir(directory))
	def test_move_between_archive_aliases_is_rejected(self):
		with TemporaryDirectory() as directory:
			alias = Path(directory, 'alias.zip')
			os.link(self._zip, alias)
			before = Path(self._zip).read_bytes()
			with self.assertRaisesRegex(OSError, 'same archive'):
				self._fs.move(self._url('ZipFileTest/file.txt'), as_url(alias, 'zip://') + '/new.txt')
			self.assertEqual(before, Path(self._zip).read_bytes())
	def test_move_between_archives_verification_failure_retains_source(self):
		before = Path(self._zip).read_bytes()
		original = Extract.__call__
		def extract(task):
			if task._expected_digest is not None:
				raise OSError('verification failed')
			return original(task)
		with TemporaryDirectory() as directory, patch.object(Extract, '__call__', extract):
			destination = as_url(Path(directory, 'out.zip'), 'zip://') + '/item.txt'
			with self.assertRaisesRegex(OSError, 'verification failed'):
				self._fs.move(self._url('ZipFileTest/file.txt'), destination)
			self.assertEqual(before, Path(self._zip).read_bytes())
	def test_move_between_archives_directory_and_empty_directory(self):
		for path in ('ZipFileTest/Directory', 'ZipFileTest/Empty directory'):
			with self.subTest(path=path), TemporaryDirectory() as directory:
				expected = self._get_zip_contents(path_in_zip=path)
				archive = Path(directory, 'out.zip')
				self._fs.move(self._url(path), as_url(archive, 'zip://') + '/moved')
				self.assertEqual(expected, self._get_zip_contents(str(archive), 'moved'))
				self.assertFalse(self._fs.exists(self._path(path)))
	def test_move_directory_named_like_verification_output(self):
		path = 'ZipFileTest/Directory'
		expected = self._get_zip_contents(path_in_zip=path)
		with TemporaryDirectory() as directory:
			archive = Path(directory, 'out.zip')
			self._fs.move(self._url(path), as_url(archive, 'zip://') + '/verified-output')
			self.assertEqual(expected, self._get_zip_contents(str(archive), 'verified-output'))
			self.assertFalse(self._fs.exists(self._path(path)))
	def test_move_preparation_counts_one_root_with_fixed_budget(self):
		with TemporaryDirectory() as directory:
			prepared = self._fs.prepare_move(self._url('ZipFileTest/file.txt'), as_url(Path(directory, 'out')))
			self.assertEqual([200], [task.get_size() for task in prepared])
			bridge = self._fs.prepare_move(self._url('ZipFileTest/file.txt'), as_url(Path(directory, 'out.zip'), 'zip://') + '/out')
			self.assertEqual([400], [task.get_size() for task in bridge])
	def test_read_file_info_with_fractional_modified_time(self):
		file_info = self._fs._read_file_info(iter((
			'Path = file.txt\n',
			'Modified = 2026-09-13 12:34:56.5872607\n',
			'Size = 1\n',
			'\n'
		)))
		self.assertEqual(date(2026, 9, 13), file_info.mtime.date())
	def test_iterdir(self):
		self._expect_iterdir_result('', {'ZipFileTest'})
		self._expect_iterdir_result(
			'ZipFileTest',
			{'Directory', 'Empty directory', 'file.txt', 'ça va.txt'}
		)
		self._expect_iterdir_result(
			'ZipFileTest/Directory', {'Subdirectory', 'file 2.txt'}
		)
		self._expect_iterdir_result(
			'ZipFileTest/Directory/Subdirectory', {'file 3.txt'}
		)
		self._expect_iterdir_result('ZipFileTest/Empty directory', set())
	def test_iterdir_empty_zip(self):
		with TemporaryDirectory() as zip_container:
			zip_path = os.path.join(zip_container, 'test.zip')
			self._create_empty_zip(zip_path)
			self.assertEqual([], self._listdir(self._path('', zip_path)))
	def test_iterdir_sparse_zip(self):
		with TemporaryDirectory() as tmp_dir:
			zip_path = os.path.join(tmp_dir, 'test.zip')
			for depth in range(3):
				file_relpath = os.path.join(*(['dir'] * depth + ['file.txt']))
				with ZipFile(zip_path, 'w') as zip_file:
					zip_file.write(__file__, file_relpath)
				for level in range(depth):
					dir_path = self._path('/'.join(['dir'] * level), zip_path)
					self.assertEqual(
						['dir'], self._listdir(dir_path),
						'Failed at nesting level ' + file_relpath
					)
	def test_iterdir_nonexistent_zip(self):
		with self.assertRaises(FileNotFoundError):
			self._listdir('nonexistent.zip')
	def test_iterdir_nonexistent_path_in_zip(self):
		with self.assertRaises(FileNotFoundError):
			self._listdir(self._path('nonexistent'))
	def _listdir(self, zip_urlpath):
		return list(self._fs.iterdir(zip_urlpath))
	def test_is_dir(self):
		for dir_ in self._dirs_in_zip:
			self.assertTrue(self._fs.is_dir(self._path(dir_)), dir_)
		for nondir in self._files_in_zip:
			self.assertFalse(self._fs.is_dir(self._path(nondir)), nondir)
		for nonexistent in ('nonexistent', 'ZipFileTest/nonexistent'):
			with self.assertRaises(FileNotFoundError):
				self._fs.is_dir(self._path(nonexistent)), nonexistent
	def test_exists(self):
		for existent in self._dirs_in_zip + self._files_in_zip:
			self.assertTrue(self._fs.exists(self._path(existent)), existent)
		for nonexistent in ('nonexistent', 'ZipFileTest/nonexistent'):
			self.assertFalse(
				self._fs.exists(self._path(nonexistent)), nonexistent
			)
	def test_extract_entire_zip(self):
		self._test_extract_dir('')
	def _test_extract_dir(self, path_in_zip):
		expected_files = self._get_zip_contents(path_in_zip=path_in_zip)
		with TemporaryDirectory() as tmp_dir:
			# Create a subdirectory because the destination directory of a copy
			# operation must not yet exist:
			dst_dir = os.path.join(tmp_dir, 'dest')
			self._fs.copy(self._url(path_in_zip), as_url(dst_dir))
			self.assertEqual(expected_files, self._read_directory(dst_dir))
	def test_extract_subdir(self):
		self._test_extract_dir('ZipFileTest/Directory')
	def test_extract_empty_directory(self):
		self._test_extract_dir('ZipFileTest/Empty directory')
	def test_extract_file(self):
		with TemporaryDirectory() as tmp_dir:
			file_path = 'ZipFileTest/file.txt'
			dest_path = os.path.join(tmp_dir, 'file.txt')
			self._fs.copy(self._url(file_path), as_url(dest_path))
			self.assertEqual(['file.txt'], listdir(tmp_dir))
			expected_contents = self._get_zip_contents(path_in_zip=file_path)
			with open(dest_path) as f:
				self.assertEqual(expected_contents, f.read())
	def test_extract_nonexistent(self):
		with self.assertRaises(FileNotFoundError):
			with TemporaryDirectory() as tmp_dir:
				self._fs.copy(self._url('nonexistent'), as_url(tmp_dir))
	def test_add_file(self):
		with TemporaryDirectory() as tmp_dir:
			file_to_add = os.path.join(tmp_dir, 'tmp.txt')
			file_contents = 'added!'
			with open(file_to_add, 'w') as f:
				f.write(file_contents)
			dest_url_in_zip = self._url('ZipFileTest/Directory/added.txt')
			self._fs.copy(as_url(file_to_add), dest_url_in_zip)
			dest_url = join(as_url(tmp_dir), 'extracted.txt')
			self._fs.copy(dest_url_in_zip, dest_url)
			with open(as_human_readable(dest_url)) as f:
				actual_contents = f.read()
			self.assertEqual(file_contents, actual_contents)
	def test_add_directory(self):
		with TemporaryDirectory() as zip_contents:
			with ZipFile(self._zip) as zip_file:
				zip_file.extractall(zip_contents)
			with TemporaryDirectory() as zip_container:
				zip_path = os.path.join(zip_container, 'test.zip')
				self._create_empty_zip(zip_path)
				self._fs.copy(
					as_url(os.path.join(zip_contents, 'ZipFileTest')),
					join(as_url(zip_path, 'zip://'), 'ZipFileTest')
				)
				self._expect_zip_contents(self._get_zip_contents(), zip_path)
	def test_replace_file(self):
		with TemporaryDirectory() as tmp_dir:
			zip_path = os.path.join(tmp_dir, 'test.zip')
			some_file = os.path.join(tmp_dir, 'tmp.txt')
			with open(some_file, 'w') as f:
				f.write('added!')
			with ZipFile(zip_path, 'w') as zip_file:
				zip_file.write(some_file, 'tmp.txt')
			expected_contents = b'replaced!'
			with open(some_file, 'wb') as f:
				f.write(expected_contents)
			dest_url_in_zip = join(as_url(zip_path, 'zip://'), 'tmp.txt')
			self._fs.copy(as_url(some_file), dest_url_in_zip)
			with ZipFile(zip_path) as zip_file:
				# A primitive implementation would have two 'tmp.txt' entries:
				self.assertEqual(['tmp.txt'], zip_file.namelist())
				with zip_file.open('tmp.txt') as f_in_zip:
					self.assertEqual(expected_contents, f_in_zip.read())
	def test_mkdir(self):
		with TemporaryDirectory() as tmp_dir:
			zip_path = os.path.join(tmp_dir, 'test.zip')
			self._create_empty_zip(zip_path)
			self._fs.mkdir(splitscheme(as_url(zip_path, 'zip://'))[1] + '/dir')
			self._expect_zip_contents({'dir': {}}, zip_path)
	def test_mkdir_raises_fileexistserror(self):
		with TemporaryDirectory() as tmp_dir:
			zip_path = os.path.join(tmp_dir, 'test.zip')
			self._create_empty_zip(zip_path)
			dir_url_path = splitscheme(as_url(zip_path, 'zip://'))[1] + '/dir'
			self._fs.mkdir(dir_url_path)
			with self.assertRaises(FileExistsError):
				self._fs.mkdir(dir_url_path)
	def test_mkdir_raises_filenotfounderror(self):
		with TemporaryDirectory() as tmp_dir:
			zip_path = os.path.join(tmp_dir, 'test.zip')
			self._create_empty_zip(zip_path)
			zip_url_path = splitscheme(as_url(zip_path, 'zip://'))[1]
			with self.assertRaises(OSError) as cm:
				self._fs.mkdir(zip_url_path + '/nonexistent/dir')
			self.assertEqual(ENOENT, cm.exception.errno)
	def test_mkdir_empty(self):
		with TemporaryDirectory() as tmp_dir:
			zip_path = os.path.join(tmp_dir, 'test.zip')
			self._fs.mkdir(splitscheme(as_url(zip_path))[1])
			with ZipFile(zip_path) as zip_file:
				self.assertEqual([], zip_file.namelist())
	def test_delete_file(self):
		self._test_delete('ZipFileTest/Directory/Subdirectory/file 3.txt')
	def _test_delete(self, path_in_zip):
		expected_contents = self._get_zip_contents()
		self._pop_from_dir_dict(expected_contents, path_in_zip)
		self._fs.delete(self._path(path_in_zip))
		self.assertEqual(expected_contents, self._get_zip_contents())
	def test_delete_directory(self):
		self._test_delete('ZipFileTest/Directory')
	def test_delete_empty_directory(self):
		self._test_delete('ZipFileTest/Empty directory')
	def test_delete_main_directory(self):
		self._test_delete('ZipFileTest')
	def test_delete_nonexistent(self):
		with self.assertRaises(FileNotFoundError):
			self._fs.delete(self._path('nonexistent'))
	def test_move_file_out_of_archive(self):
		file_path = 'ZipFileTest/Directory/Subdirectory/file 3.txt'
		expected_zip_contents = self._get_zip_contents()
		removed = self._pop_from_dir_dict(expected_zip_contents, file_path)
		with TemporaryDirectory() as tmp_dir:
			dst = os.path.join(tmp_dir, 'test.tzt')
			self._fs.move(self._url(file_path), as_url(dst))
			self.assertEqual(expected_zip_contents, self._get_zip_contents())
			with open(dst) as f:
				self.assertEqual(removed, f.read())
	def test_move_dir_out_of_archive(self):
		self._test_move_dir_out_of_archive('ZipFileTest/Directory')
	def test_move_empty_dir_out_of_archive(self):
		self._test_move_dir_out_of_archive('ZipFileTest/Empty directory')
	def test_move_main_dir_out_of_archive(self):
		self._test_move_dir_out_of_archive('ZipFileTest')
	def _test_move_dir_out_of_archive(self, path_in_zip):
		expected_zip_contents = self._get_zip_contents()
		removed = self._pop_from_dir_dict(expected_zip_contents, path_in_zip)
		with TemporaryDirectory() as tmp_dir:
			dst_dir = os.path.join(tmp_dir, 'dest')
			self._fs.move(self._url(path_in_zip), as_url(dst_dir))
			self.assertEqual(expected_zip_contents, self._get_zip_contents())
			self.assertEqual(removed, self._read_directory(dst_dir))
	def test_move_file_into_archive(self):
		expected_zip_contents = self._get_zip_contents()
		with TemporaryDirectory() as tmp_dir:
			file_path = os.path.join(tmp_dir, 'test.txt')
			with open(file_path, 'w') as f:
				f.write('success!')
			dst_url = self._url('test_dest.txt')
			self._fs.move(as_url(file_path), dst_url)
			self.assertFalse(Path(file_path).exists())
			expected_zip_contents['test_dest.txt'] = 'success!'
			self.assertEqual(expected_zip_contents, self._get_zip_contents())
	def test_rename_directory(self):
		expected_contents = self._get_zip_contents()
		file_path = 'ZipFileTest/Directory'
		expected_contents['Destination'] = \
			self._pop_from_dir_dict(expected_contents, file_path)
		self._fs.move(self._url(file_path), self._url('Destination'))
		self.assertEqual(expected_contents, self._get_zip_contents())
	def test_rename_file(self):
		expected_contents = self._get_zip_contents()
		src_path = 'ZipFileTest/Directory/Subdirectory/file 3.txt'
		expected_contents['ZipFileTest']['Directory']['destination.txt'] = \
			self._pop_from_dir_dict(expected_contents, src_path)
		self._fs.move(
			self._url(src_path),
			self._url('ZipFileTest/Directory/destination.txt')
		)
		self.assertEqual(expected_contents, self._get_zip_contents())
	def test_move_file_between_archives(self, operation=None, get_contents=None):
		if operation is None:
			operation = self._fs.move
		if get_contents is None:
			get_contents = self._pop_from_dir_dict
		src_path = 'ZipFileTest/Directory/Subdirectory/file 3.txt'
		expected_contents = self._get_zip_contents()
		src_contents = get_contents(expected_contents, src_path)
		with TemporaryDirectory() as dst_dir:
			dst_zip = os.path.join(dst_dir, 'dest.zip')
			# Give the Zip file some contents:
			dummy_txt = os.path.join(dst_dir, 'dummy.txt')
			dummy_contents = 'some contents'
			with open(dummy_txt, 'w') as f:
				f.write(dummy_contents)
			with ZipFile(dst_zip, 'w') as zip_file:
				zip_file.write(dummy_txt, 'dummy.txt')
			dst_url = join(as_url(dst_zip, 'zip://'), 'dest.txt')
			operation(self._url(src_path), dst_url)
			self.assertEqual(expected_contents, self._get_zip_contents())
			self.assertEqual(
				{'dummy.txt': dummy_contents, 'dest.txt': src_contents},
				self._get_zip_contents(dst_zip)
			)
	def test_copy_file_between_archives(self):
		self.test_move_file_between_archives(
			self._fs.copy, self._get_from_dir_dict
		)
	def test_failed_destination_packing_keeps_source(self):
		before = Path(self._zip).read_bytes()
		for error in (OSError('failed'), Task.Canceled()):
			with self.subTest(error=type(error).__name__), TemporaryDirectory() as directory:
				destination = as_url(Path(directory, 'destination.zip'), 'zip://') + '/item.txt'
				with patch('core.fs.zip.AddToArchive.__call__', side_effect=error):
					with self.assertRaises((OSError, Task.Canceled)):
						self._fs.move(self._url('ZipFileTest/file.txt'), destination)
				self.assertEqual(before, Path(self._zip).read_bytes())
	def test_move_source_change_keeps_source(self):
		with TemporaryDirectory() as directory:
			def change_source(*args, **kwargs):
				with ZipFile(self._zip, 'a') as writer:
					writer.writestr('new.txt', 'added while extracting')
			with patch('core.fs.zip.Extract.__call__', side_effect=change_source):
				with self.assertRaisesRegex(OSError, 'changed during transfer'):
					self._fs.move(self._url('ZipFileTest/file.txt'), as_url(Path(directory, 'out')))
			with ZipFile(self._zip) as archive:
				self.assertIn('ZipFileTest/file.txt', archive.namelist())
	def test_size_bytes_file(self):
		file_path = 'ZipFileTest/Directory/Subdirectory/file 3.txt'
		file_contents = self._get_zip_contents(path_in_zip=file_path)
		self.assertEqual(
			len(file_contents), self._fs.size_bytes(self._path(file_path))
		)
	def test_size_bytes_dir(self):
		dir_path = self._path('ZipFileTest/Directory/Subdirectory')
		self.assertIn(self._fs.size_bytes(dir_path), (0, None))
	def test_size_bytes_root(self):
		self.assertIsNone(self._fs.size_bytes(self._path('')))
	def test_size_bytes_nonexistent_zip(self):
		with self.assertRaises(FileNotFoundError):
			self._fs.size_bytes('nonexistent')
	def test_size_bytes_nonexistent_path_in_zip(self):
		with self.assertRaises(FileNotFoundError):
			self._fs.size_bytes(self._path('nonexistent'))
	def test_modified_datetime_file(self):
		file_path = 'ZipFileTest/Directory/Subdirectory/file 3.txt'
		mtime = self._fs.modified_datetime(self._path(file_path))
		# Compare by date only because the time depends on the system time zone:
		self.assertEqual(date(2017, 11, 8), mtime.date())
	def test_modified_datetime_dir(self):
		dir_path = self._path('ZipFileTest/Empty directory')
		mtime = self._fs.modified_datetime(dir_path)
		# Compare by date only because the time depends on the system time zone:
		self.assertEqual(date(2017, 11, 8), mtime.date())
	def test_modified_datetime_root(self):
		self.assertIsNone(self._fs.modified_datetime(self._path('')))
	def test_modified_datetime_nonexistent_zip(self):
		with self.assertRaises(FileNotFoundError):
			self._fs.modified_datetime('nonexistent')
	def test_modified_datetime_nonexistent_path_in_zip(self):
		with self.assertRaises(FileNotFoundError):
			self._fs.modified_datetime(self._path('nonexistent'))
	def test_resolve_nonexistent_zip_raises_filenotfounderror(self):
		with self.assertRaises(FileNotFoundError):
			tmp_url = as_url(self._tmp_dir.name)
			self._fs.resolve(splitscheme(join(tmp_url, 'non-existent.zip'))[1])
	def test_resolve_nonexistent_file(self):
		with self.assertRaises(FileNotFoundError):
			self._fs.resolve('non-existent')
	def _expect_iterdir_result(self, path_in_zip, expected_contents):
		full_path = self._path(path_in_zip)
		self.assertEqual(
			set(self._normalize_unicode(s) for s in expected_contents),
			set(self._normalize_unicode(s) for s in self._fs.iterdir(full_path))
		)
	def _normalize_unicode(self, name):
		# Consider ç: It can be encoded in Unicode as "latin small letter c
		# with cedilla" (U+00E7) but also as a c followed by "combining
		# cedilla" (U+0327). This source file uses the former, but on Mac,
		# the file system gives us the latter. To accommodate this, we normalize
		# Unicode file names before comparing them:
		return normalize('NFC', name)
	def _url(self, path_in_zip):
		return as_url(self._path(path_in_zip), 'zip://')
	def _path(self, path_in_zip, zip_path=None):
		if zip_path is None:
			zip_path = self._zip
		return zip_path.replace(os.sep, '/') + \
			   ('/' if path_in_zip else '') + \
			   path_in_zip
	def _get_zip_contents(self, zip_path=None, path_in_zip=None):
		if zip_path is None:
			zip_path = self._zip
		with TemporaryDirectory() as tmp_dir:
			with ZipFile(zip_path) as zip_file:
				zip_file.extractall(tmp_dir)
			zip_contents = self._read_directory(tmp_dir)
			return self._get_from_dir_dict(zip_contents, path_in_zip)
	def _pop_from_dir_dict(self, dir_dict, path):
		parts = path.split('/')
		for part in parts[:-1]:
			dir_dict = dir_dict[part]
		return dir_dict.pop(parts[-1])
	def _get_from_dir_dict(self, dir_dict, path):
		if not path:
			return dir_dict
		for part in path.split('/'):
			dir_dict = dir_dict[part]
		return dir_dict
	def _read_directory(self, dir_path):
		result = {}
		for child in Path(dir_path).iterdir():
			if child.is_dir():
				child_contents = self._read_directory(child)
			else:
				child_contents = child.read_text()
			result[self._normalize_unicode(child.name)] = child_contents
		return result
	def _expect_zip_contents(self, contents, zip_file_path):
		with TemporaryDirectory() as tmp_dir:
			with ZipFile(zip_file_path) as zip_file:
				zip_file.extractall(tmp_dir)
			self.assertEqual(contents, self._read_directory(tmp_dir))
	def _create_empty_zip(self, path):
		ZipFile(path, 'w').close()
	def _create_test_zip(self, path):
		entries = {
			'ZipFileTest/Empty directory/': '',
			'ZipFileTest/file.txt': 'file contents',
			'ZipFileTest/ça va.txt': 'ça va',
			'ZipFileTest/Directory/file 2.txt': 'file 2 contents',
			'ZipFileTest/Directory/Subdirectory/file 3.txt': 'file 3 contents'
		}
		with ZipFile(path, 'w') as zip_file:
			for name, contents in entries.items():
				entry = ZipInfo(name, (2017, 11, 8, 12, 0, 0))
				zip_file.writestr(entry, contents)
	def setUp(self):
		super().setUp()
		fman_fs = StubFS()
		self._fs = ZipFileSystem(fman_fs, {'.zip'})
		fman_fs.add_child(self._fs)
		self._tmp_dir = TemporaryDirectory()
		self._zip = os.path.join(self._tmp_dir.name, 'ZipFileSystemTest.zip')
		self._create_test_zip(self._zip)
		self._dirs_in_zip = (
			'', 'ZipFileTest', 'ZipFileTest/Directory',
			'ZipFileTest/Directory/Subdirectory', 'ZipFileTest/Empty directory'
		)
		self._files_in_zip = (
			'ZipFileTest/file.txt', 'ZipFileTest/Directory/file 2.txt',
			'ZipFileTest/Directory/Subdirectory/file 3.txt'
		)
		self.maxDiff = None
	def tearDown(self):
		self._tmp_dir.cleanup()
		super().tearDown()