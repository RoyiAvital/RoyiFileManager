from errno import ENOENT
from core.fs.zip import ZipFileSystem, _7zip, _get_7zip_args_windows, \
	_7zipError, _7zipTaskWithProgress, Extract, _cleanup_extraction, \
	SevenZipFileSystem, TarFileSystem, CompressedTarFileSystem, Popen7Zip, PackArchive, \
	_MEMBER_LISTS, _MemberLists, _DIRECT, _StatusProgress, READ_ONLY_MESSAGE
from core.fs.zip import Popen7ZipWindows, _read_members
from core.tests import StubFS
from contextlib import contextmanager
from datetime import date
from fman.url import as_url, join, as_human_readable, splitscheme
from fman import Task
from io import UnsupportedOperation
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
import tarfile

def _run_7zip(args, cwd=None):
	with _7zip(args, cwd=cwd, allow_warning=False) as command:
		list(command.progress_records(lambda: None))

def _read_tree(path):
	"""{name: bytes or subtree} of a local folder."""
	return {child.name: _read_tree(child) if child.is_dir() else child.read_bytes()
		for child in Path(path).iterdir()}

def _write_tar(path, mode, entries):
	"""Write (name, bytes | None for a folder | ('link', target)) entries."""
	with tarfile.open(path, mode) as writer:
		for name, contents in entries:
			info = tarfile.TarInfo(name)
			info.mtime = 1_600_000_000
			if contents is None:
				info.type = tarfile.DIRTYPE
				writer.addfile(info)
			elif isinstance(contents, tuple):
				info.type = tarfile.SYMTYPE
				info.linkname = contents[1]
				writer.addfile(info)
			else:
				info.size = len(contents)
				writer.addfile(info, BytesIO(contents))

@contextmanager
def _count_7zip_starts():
	starts = []
	original = Popen7ZipWindows.__init__
	def init(self, args, *rest, **kwargs):
		starts.append(args)
		original(self, args, *rest, **kwargs)
	with patch.object(Popen7ZipWindows, '__init__', init):
		yield starts

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
		# An archive rewritten within one timestamp tick can keep its size and time.
		_MEMBER_LISTS.clear()
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
	def test_manifest_has_no_entry_depth_or_field_limits(self):
		def manifest(records):
			return _read_members(records, lambda: None).check_names(lambda: None)
		def records():
			for index in range(100001):
				yield 'Path = file' + str(index)
				yield 'Folder = -'
				yield 'Size = 0'
		self.assertEqual(100001, len(manifest(records())))
		deep = '/'.join(['folder'] * 129)
		self.assertEqual((deep, True), manifest(['Path = ' + deep, 'Folder = +'])[deep])
		self.assertEqual({'file': ('file', False)}, manifest(
			['Path = file'] + ['Field%d = value' % index for index in range(65)]))
	def test_manifest_ignores_non_naming_metadata(self):
		for metadata in ('Encrypted = +', 'Symbolic Link = target', 'Hard Link = target', 'Mode = lrwxrwxrwx', 'Size = unknown'):
			with self.subTest(metadata=metadata):
				self.assertEqual({'file': ('file', False)},
					_read_members(['Path = file', metadata], lambda: None).check_names(lambda: None))
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
	def test_overlapping_suffix_extracts_the_selected_source(self):
		# '.zip' is a prefix of '.zipx': the whole component decides the archive.
		self.create_task([('file', b'decoy')])
		selected = self.root / 'Reports.zipx'
		with ZipFile(selected, 'w') as writer:
			writer.writestr('file', b'payload')
		selected_bytes = selected.read_bytes()
		backend = ZipFileSystem(StubFS(), ('.zip', '.zipx'))
		archive_url = backend.scheme + splitscheme(as_url(selected))[1]
		task, = backend.prepare_copy(archive_url, as_url(self.output))
		task.require_new_directory(selected, self.output)
		task()
		self.assertEqual(b'payload', (self.output / 'file').read_bytes())
		self.assertEqual(selected_bytes, selected.read_bytes())
		self.assertEqual(self.original, self.archive.read_bytes())
	def test_tar_and_zip_symlinks_are_skipped_and_reported(self):
		linked_zip = self.root / 'linked.zip'
		link = ZipInfo('link')
		link.create_system = 3
		link.external_attr = 0o120777 << 16
		with ZipFile(linked_zip, 'w') as writer:
			writer.writestr('file', b'payload')
			writer.writestr(link, 'file')
		linked_tar = self.root / 'linked.tar'
		_write_tar(linked_tar, 'w', [('file', b'payload'), ('link', ('link', 'file'))])
		for archive in (linked_zip, linked_tar):
			with self.subTest(archive=archive.name):
				output = self.root / (archive.stem + '-' + archive.suffix[1:])
				original = archive.read_bytes()
				task = Extract(StubFS(), str(archive), '', str(output))
				task.require_new_directory(archive)
				with patch.object(task, 'show_alert') as alert:
					task()
				self.assertEqual(['file'], os.listdir(output))
				self.assertEqual(b'payload', (output / 'file').read_bytes())
				self.assertEqual(original, archive.read_bytes())
				alert.assert_called_once()
				self.assertIn('1 symbolic link was skipped', alert.call_args.args[0])
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
	def test_reader_start_failure_kills_before_wait(self):
		process = FakePipeProcess(quiet=True)
		archive = _7zip([])
		archive._process = process
		error = RuntimeError('start failed')
		with patch('core.fs.zip.Thread', side_effect=error):
			with self.assertRaises(RuntimeError) as raised:
				list(archive.progress_records(lambda: None))
			self.assertIs(error, raised.exception)
		self.assertTrue(process.killed)
		self.assertTrue(process.waited)
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
	def test_progress_is_monotonic_and_capped(self):
		task = _7zipTaskWithProgress('Extracting', size=100)
		process = FakePipeProcess(['0%\r50% item\r20% item\r100% item\n'])
		with patch('core.fs.zip.Popen7ZipWindows', return_value=process), \
			patch.object(task, 'set_progress', wraps=task.set_progress) as set_progress:
			task.run_7zip_with_progress(['x'], progress_limit=99)
			self.assertEqual([50, 99], [call.args[0] for call in set_progress.call_args_list])
	def test_extract_cancel_and_warning_do_not_publish(self):
		for error in (Task.Canceled(), _7zipError(1, ['x'], 'warning')):
			with self.subTest(error=type(error).__name__), TemporaryDirectory() as directory:
				archive = Path(directory, 'source.zip')
				with ZipFile(archive, 'w') as writer:
					writer.writestr('item', b'payload')
				filesystem = Mock()
				task = Extract(filesystem, str(archive), 'item', str(Path(directory, 'out')))
				with patch.object(task, 'run_7zip_with_progress', side_effect=error):
					with self.assertRaises((Task.Canceled, OSError)):
						task()
				filesystem.notify_file_changed.assert_not_called()
				self.assertEqual(['source.zip'], os.listdir(directory))
	def test_cancel_before_publication(self):
		with TemporaryDirectory() as directory:
			archive = Path(directory, 'source.zip')
			with ZipFile(archive, 'w') as writer:
				writer.writestr('item', b'payload')
			task = Extract(Mock(), str(archive), 'item', str(Path(directory, 'out')))
			original = task.run_7zip_with_progress
			def cancel(*args, **kwargs):
				original(*args, **kwargs)
				task._dialog._was_canceled = True
			with patch.object(task, 'run_7zip_with_progress', side_effect=cancel):
				with self.assertRaises(Task.Canceled):
					task()
			task._fman_fs.notify_file_changed.assert_not_called()
			self.assertEqual(['source.zip'], os.listdir(directory))
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
				members = _read_members(command.progress_records(lambda: None, truncate=False), lambda: None)
			self.assertTrue(all(members.get(path) is not None for path in paths))
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
			# List first so that Cancel hits the extraction.
			ZipFileSystem(StubFS(), {'.zip'}).members(str(archive))
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
				self.assertEqual(_read_tree(source), _read_tree(output / 'source'))
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
				cwd=temporary_directory
			) as process:
				list(process.progress_records(lambda: None))
			with ZipFile(archive) as zip_file:
				self.assertEqual(['smoke-test.txt'], zip_file.namelist())
				self.assertEqual(b'7za works', zip_file.read('smoke-test.txt'))

class ArchivePathSplitTest(TestCase):
	def test_split_uses_whole_components_and_skips_archive_named_folders(self):
		fs = ZipFileSystem(StubFS(), {'.zip', '.zipx'})
		with TemporaryDirectory() as directory:
			root = as_url(Path(directory).resolve())[len('file://'):]
			os.makedirs(os.path.join(directory, 'old.zip'))
			for path, expected in (
					('C:/my.zipper/a.zip/x/y.txt', ('C:/my.zipper/a.zip', 'x/y.txt')),
					('C:/data/a.ZIPX/x', ('C:/data/a.ZIPX', 'x')),
					('C:/a.zip', ('C:/a.zip', '')),
					('/dest.zip/a.txt', ('/dest.zip', 'a.txt')),
					('//server/share/a.zip/x', ('//server/share/a.zip', 'x')),
					(root + '/old.zip/new.zip/x', (root + '/old.zip/new.zip', 'x')),
					(root + '/missing.zip/inner.zip/x', (root + '/missing.zip', 'inner.zip/x'))):
				with self.subTest(path=path):
					self.assertEqual(expected, fs._split(path))
			with self.assertRaises(FileNotFoundError):
				fs._split('C:/data/archive.zip.old/x')

	def test_single_archive_component_needs_no_disk_check(self):
		fs = ZipFileSystem(StubFS(), {'.zip'})
		with patch('core.fs.zip.os.path.isdir') as isdir:
			self.assertEqual(('C:/a.zip', 'b/c.txt'), fs._split('C:/a.zip/b/c.txt'))
		isdir.assert_not_called()

	def test_resolve_treats_archive_named_folders_as_file_system_locations(self):
		with TemporaryDirectory() as directory:
			root = Path(directory).resolve()
			for name in ('ordinary.zip', 'my.zipper'):
				(root / name).mkdir()
				with ZipFile(root / name / 'container.zip', 'w') as writer:
					writer.writestr('report.txt', b'report')
			fs = ZipFileSystem(Mock(resolve=lambda url: url), {'.zip'})
			base = as_url(root)[len('file://'):]
			for name in ('ordinary.zip', 'my.zipper'):
				with self.subTest(name=name):
					# Going up from the archive reaches the containing folder.
					self.assertEqual(as_url(root / name), fs.resolve(base + '/' + name))
					self.assertEqual('zip://' + base + '/' + name + '/container.zip',
						fs.resolve(base + '/' + name + '/container.zip'))
			with self.assertRaises(FileNotFoundError):
				fs.resolve(base + '/missing.zip/item')

	def test_archive_below_an_archive_named_folder_reads_its_members(self):
		with TemporaryDirectory() as directory:
			archive = Path(directory).resolve() / 'real.zip' / 'container.zip'
			archive.parent.mkdir()
			with ZipFile(archive, 'w') as writer:
				writer.writestr('ordinary.zip/report.txt', b'report')
			filesystem = StubFS()
			fs = ZipFileSystem(filesystem, {'.zip'})
			filesystem.add_child(fs)
			base = as_url(archive, 'zip://')[len('zip://'):]
			self.assertEqual(['ordinary.zip'], list(fs.iterdir(base)))
			self.assertTrue(fs.is_dir(base + '/ordinary.zip'))
			self.assertEqual(['report.txt'], list(fs.iterdir(base + '/ordinary.zip')))
			self.assertTrue(fs.exists(base + '/ordinary.zip/report.txt'))

class ZipFileSystemTest(TestCase):
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
	def test_fractional_modified_time(self):
		members = _MemberLists()
		reader = Mock(kind='fake')
		from core.fs.zip import _read_members
		reader.read.side_effect = lambda path, check, progress: _read_members(
			['Path = file.txt', 'Modified = 2026-09-13 12:34:56.5872607', 'Size = 1'], check)
		entry = members.get(self._zip, reader).get('file.txt')
		self.assertEqual(date(2026, 9, 13), entry.mtime.date())
		self.assertEqual(1, entry.size_bytes)
	def test_every_change_is_refused_and_the_archive_is_unchanged(self):
		from fman.impl.plugins.mother_fs import MotherFileSystem
		from core import LocalFileSystem
		mother = MotherFileSystem()
		mother.add_child('file://', LocalFileSystem())
		mother.add_child('zip://', self._fs)
		before = Path(self._zip).read_bytes()
		with TemporaryDirectory() as directory:
			local = as_url(Path(directory, 'local.txt'))
			Path(directory, 'local.txt').write_text('local')
			item = self._url('ZipFileTest/file.txt')
			for name, call in (
					('copy into', lambda: mother.prepare_copy(local, self._url('ZipFileTest/new.txt'))),
					('move into', lambda: mother.prepare_move(local, self._url('ZipFileTest/new.txt'))),
					('move out', lambda: mother.prepare_move(item, as_url(Path(directory, 'out.txt')))),
					('move within', lambda: mother.prepare_move(item, self._url('ZipFileTest/renamed.txt'))),
					('rename', lambda: mother.rename_no_replace(item, self._url('ZipFileTest/renamed.txt'))),
					('delete', lambda: mother.prepare_delete(item)),
					('trash', lambda: mother.prepare_trash(item)),
					('new folder', lambda: mother.mkdir(self._url('ZipFileTest/new'))),
					('new file', lambda: mother.touch(self._url('ZipFileTest/new.txt')))):
				with self.subTest(name), self.assertRaisesRegex(UnsupportedOperation, 'Archives are read-only'):
					call()
			self.assertEqual('local', Path(directory, 'local.txt').read_text())
			self.assertEqual(['local.txt'], os.listdir(directory))
		self.assertEqual(before, Path(self._zip).read_bytes())
	def test_archive_items_copy_only_to_local_folders(self):
		with self.assertRaisesRegex(UnsupportedOperation, 'only be copied to a local folder'):
			self._fs.prepare_copy(self._url('ZipFileTest/file.txt'), 'other://C:/x')
		with self.assertRaisesRegex(UnsupportedOperation, 'read-only'):
			self._fs.prepare_copy(as_url(self._zip), self._url('ZipFileTest/x'))
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
		_MEMBER_LISTS.clear()
		self.addCleanup(_MEMBER_LISTS.clear)
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

_TAR_MODES = (('.tar.gz', 'w:gz'), ('.tgz', 'w:gz'), ('.tar.bz2', 'w:bz2'), ('.tbz2', 'w:bz2'),
	('.tbz', 'w:bz2'), ('.tar.xz', 'w:xz'), ('.txz', 'w:xz'), ('.tar.zst', 'w:zst'), ('.tzst', 'w:zst'))
_ENTRIES = (('docs/a.txt', b'A'), ('docs/sub/b.txt', b'BB'), ('top.txt', b'TTT'), (' lead.txt', b'L'),
	('\u00e9t\u00e9/x.txt', b'X'), ('@at.txt', b'@'), ('!bang.txt', b'!'))

class _ArchiveFixtures(TestCase):
	"""The same entries as .zip, .7z, .tar (with './' names) and .tar.gz."""
	def setUp(self):
		_MEMBER_LISTS.clear()
		self.addCleanup(_MEMBER_LISTS.clear)
		temporary = TemporaryDirectory()
		self.addCleanup(temporary.cleanup)
		self.root = Path(temporary.name)
		self.notified = patch('fman.fs.notify_file_added').start()
		self.addCleanup(patch.stopall)
	def archives(self):
		source = self.root / 'source'
		for name, contents in _ENTRIES:
			(source / name).parent.mkdir(parents=True, exist_ok=True)
			(source / name).write_bytes(contents)
		zip_path = self.root / 'x.zip'
		with ZipFile(zip_path, 'w') as writer:
			for name, contents in _ENTRIES:
				writer.writestr(ZipInfo(name, (2020, 1, 2, 3, 4, 6)), contents)
		seven = self.root / 'x.7z'
		# On the command line a name starting with '@' is a list file: pass a list.
		names = self.root / 'names.txt'
		names.write_text(''.join('"%s"\n' % name for name in sorted({name.split('/')[0] for name, _ in _ENTRIES})),
			encoding='utf-8')
		_run_7zip(['a', '-scsUTF-8', str(seven), '@' + str(names)], cwd=str(source))
		names.unlink()
		tar_entries = [('./', None), ('./docs', None)] + [('./' + name, contents) for name, contents in _ENTRIES]
		plain = self.root / 'x.tar'
		_write_tar(plain, 'w', tar_entries)
		compressed = self.root / 'x.tar.gz'
		_write_tar(compressed, 'w:gz', tar_entries)
		return [(ZipFileSystem(StubFS(), {'.zip'}), zip_path), (SevenZipFileSystem(StubFS(), {'.7z'}), seven),
			(TarFileSystem(StubFS(), {'.tar'}), plain), (CompressedTarFileSystem(StubFS(), {'.tar.gz'}), compressed)]
	def copies(self, fs, archive, members, destination, fman_fs=None):
		"""One Extract for `members` as CopyFiles would queue it."""
		base = fs.scheme + archive.as_posix()
		tasks = [fs.prepare_copy(base + '/' + member, as_url(destination / member.rsplit('/', 1)[-1]))[0]
			for member in members]
		for task in tasks:
			task._fman_fs = fman_fs or Mock()
		for task in tasks[1:]:
			self.assertTrue(tasks[0].absorb(task))
		return tasks[0]

class MemberListTest(_ArchiveFixtures):
	def test_every_type_lists_folders_sizes_and_dates(self):
		for fs, archive in self.archives():
			with self.subTest(archive=archive.name):
				base = archive.as_posix()
				self.assertEqual({'docs', 'top.txt', ' lead.txt', '\u00e9t\u00e9', '@at.txt', '!bang.txt'},
					set(fs.iterdir(base)))
				self.assertEqual({'a.txt', 'sub'}, set(fs.iterdir(base + '/docs')))
				self.assertTrue(fs.is_dir(base + '/docs/sub'))
				self.assertFalse(fs.is_dir(base + '/top.txt'))
				self.assertTrue(fs.exists(base + '/docs/sub/b.txt'))
				self.assertFalse(fs.exists(base + '/docs/missing'))
				self.assertEqual(3, fs.size_bytes(base + '/top.txt'))
				self.assertIsNotNone(fs.modified_datetime(base + '/top.txt'))
				with self.assertRaises(FileNotFoundError):
					fs.is_dir(base + '/missing')
	def test_one_listing_per_archive_version(self):
		fs, archive = self.archives()[0]
		base = archive.as_posix()
		with _count_7zip_starts() as starts:
			list(fs.iterdir(base))
			list(fs.iterdir(base + '/docs'))
			fs.is_dir(base + '/docs/sub')
			fs.exists(base + '/top.txt')
			fs.resolve(base + '/docs/a.txt')
			fs.size_bytes(base + '/top.txt')
			self.assertEqual(1, len(starts))
			with ZipFile(archive, 'a') as writer:
				writer.writestr('added.txt', b'new')
			self.assertIn('added.txt', set(fs.iterdir(base)))
			self.assertEqual(2, len(starts))
	def test_least_recently_used_lists_are_dropped(self):
		paths = []
		for index in range(2):
			path = self.root / ('%d.zip' % index)
			with ZipFile(path, 'w') as writer:
				writer.writestr('a', b'a')
				writer.writestr('b', b'b')
			paths.append(str(path))
		lists = _MemberLists()
		lists.LIMIT = 3
		with _count_7zip_starts() as starts:
			lists.get(paths[0], _DIRECT)
			lists.get(paths[1], _DIRECT)
			lists.get(paths[1], _DIRECT)
			self.assertEqual(2, len(starts))
			lists.get(paths[0], _DIRECT)
			self.assertEqual(3, len(starts))
		lists.LIMIT = 1
		lists.get(paths[1], _DIRECT)
		self.assertEqual(1, len(lists._lists))
	def test_names_outside_the_root_are_refused(self):
		for name in ('../outside.txt', 'C:/absolute.txt'):
			with self.subTest(name=name):
				_MEMBER_LISTS.clear()
				archive = self.root / 'outside.zip'
				with ZipFile(archive, 'w') as writer:
					writer.writestr('inside.txt', b'in')
					writer.writestr(name, b'out')
				fs = ZipFileSystem(StubFS(), {'.zip'})
				with self.assertRaisesRegex(OSError, 'outside its root'):
					list(fs.iterdir(archive.as_posix()))
		# A colon inside a name is not a drive, at the top or deeper.
		_MEMBER_LISTS.clear()
		with ZipFile(archive, 'w') as writer:
			writer.writestr('a:b.txt', b'ab')
			writer.writestr('dir/c:x.txt', b'cx')
		self.assertEqual({'a:b.txt', 'dir'}, set(fs.iterdir(archive.as_posix())))
		self.assertEqual(['c:x.txt'], list(fs.iterdir(archive.as_posix() + '/dir')))
	def test_a_damaged_archive_is_refused_with_the_reason(self):
		valid = self.root / 'valid.zip'
		with ZipFile(valid, 'w') as writer:
			for index in range(20):
				writer.writestr('f%d.txt' % index, os.urandom(1000))
		(self.root / 'truncated.zip').write_bytes(valid.read_bytes()[:3000])
		(self.root / 'random.zip').write_bytes(os.urandom(5000))
		source = self.root / 'a.txt'
		source.write_bytes(b'secret')
		_run_7zip(['a', '-t7z', '-psecret', '-mhe=on', str(self.root / 'locked.7z'), str(source)])
		fs = ZipFileSystem(StubFS(), {'.zip', '.7z'})
		for name, reason in (('truncated.zip', 'Unexpected end of archive'),
				('random.zip', 'Cannot open the file as [zip] archive'), ('locked.7z', 'The archive needs a password')):
			with self.subTest(name), self.assertRaises(OSError) as raised:
				list(fs.iterdir((self.root / name).as_posix()))
			self.assertEqual('Cannot read %s: %s' % (name, reason), raised.exception.strerror)
	def test_a_later_entry_of_the_same_path_replaces_a_link(self):
		members = _read_members(['Path = file', 'Symbolic Link = target', 'Path = file',
			'Path = folder', 'Symbolic Link = target', 'Path = folder/inner.txt',
			'Path = twice', 'Symbolic Link = a', 'Path = twice', 'Symbolic Link = b'], lambda: None)
		self.assertEqual({'twice'}, members.links)
		self.assertTrue(members.get('folder').is_dir)
	def test_a_listing_stopped_early_ends_7zip(self):
		# More output than the reader's queue holds: an unclosed listing would block 7-Zip forever.
		archive = self.root / 'many.zip'
		with ZipFile(archive, 'w') as writer:
			writer.writestr('../outside.txt', b'out')
			for index in range(20000):
				writer.writestr('file%05d.txt' % index, b'')
		def cancel_while_reading_members():
			if sys._getframe(1).f_code.co_name == '_read_members':
				raise Task.Canceled()
		for name, call, error in (
				('refused entry', lambda: list(ZipFileSystem(StubFS(), {'.zip'}).iterdir(archive.as_posix())), OSError),
				('cancel', lambda: _MemberLists().get(str(archive), _DIRECT, cancel_while_reading_members), Task.Canceled)):
			with self.subTest(name):
				_MEMBER_LISTS.clear()
				outcome = []
				def run():
					try:
						call()
					except BaseException as raised:
						outcome.append(raised)
				from threading import Thread
				thread = Thread(target=run, daemon=True)
				thread.start()
				thread.join(30)
				self.assertFalse(thread.is_alive(), 'The listing did not stop')
				self.assertIsInstance(outcome[0], error)
				self.assertFalse([thread for thread in enumerate_threads() if thread.name == '7zip-output'])
	def test_concurrent_reads_build_one_list_and_take_over_after_cancel(self):
		from core.fs.zip import _read_members
		from threading import Thread
		archive = self.root / 'x.zip'
		archive.write_bytes(b'listed by the fake reader')
		for cancel_first in (False, True):
			with self.subTest(cancel_first=cancel_first):
				lists = _MemberLists()
				started, release = Event(), Event()
				calls, results = [], []
				class Reader:
					kind = 'fake'
					def read(self, path, check, progress=None):
						calls.append(path)
						if len(calls) == 1:
							started.set()
							release.wait(5)
							if cancel_first:
								raise Task.Canceled()
						return _read_members(['Path = item'], check)
				def get():
					try:
						results.append(lists.get(str(archive), Reader()))
					except Task.Canceled:
						results.append('canceled')
				first = Thread(target=get)
				first.start()
				started.wait(5)
				second = Thread(target=get)
				second.start()
				release.set()
				first.join(5)
				second.join(5)
				self.assertEqual(2 if cancel_first else 1, len(calls))
				lists_built = [result for result in results if result != 'canceled']
				self.assertEqual(['item'], lists_built[-1].folder(''))

class ChosenItemsExtractTest(_ArchiveFixtures):
	def test_several_members_come_out_exactly_in_one_run(self):
		chosen = [' lead.txt', '\u00e9t\u00e9', '@at.txt', '!bang.txt', 'docs/a.txt']
		for fs, archive in self.archives():
			with self.subTest(archive=archive.name):
				output = self.root / ('out-' + archive.name)
				output.mkdir()
				fs.members(str(archive))
				task = self.copies(fs, archive, chosen, output)
				with _count_7zip_starts() as starts:
					task()
				self.assertEqual(1, len(starts))
				self.assertEqual('x', starts[0][0])
				self.assertEqual({' lead.txt': b'L', '\u00e9t\u00e9': {'x.txt': b'X'}, '@at.txt': b'@',
					'!bang.txt': b'!', 'a.txt': b'A'}, _read_tree(output))
				task._fman_fs.notify_file_changed.assert_called_once_with(as_url(output))
	def test_a_fully_chosen_folder_passes_its_name_and_the_root_passes_none(self):
		fs, archive = self.archives()[0]
		output = self.root / 'out'
		output.mkdir()
		import core.fs.zip as module
		with patch.object(module, '_write_list', wraps=module._write_list) as write_list:
			self.copies(fs, archive, ['docs/a.txt', 'docs/sub'], output)()
			self.assertEqual(['docs'], write_list.call_args.args[1])
			write_list.reset_mock()
			everything = self.root / 'everything'
			everything.mkdir()
			self.copies(fs, archive, [name for name in fs.iterdir(archive.as_posix())], everything)()
			write_list.assert_not_called()
		self.assertEqual({'a.txt': b'A', 'sub': {'b.txt': b'BB'}}, _read_tree(output))
		self.assertEqual(_read_tree(self.root / 'source'), _read_tree(everything))
	def test_replaces_only_where_agreed(self):
		fs, archive = self.archives()[0]
		output = self.root / 'out'
		output.mkdir()
		(output / 'top.txt').write_bytes(b'agreed')
		task = self.copies(fs, archive, ['top.txt', '@at.txt'], output)
		(output / '@at.txt').write_bytes(b'appeared later')
		with self.assertRaisesRegex(OSError, '@at.txt'):
			task()
		self.assertEqual(b'TTT', (output / 'top.txt').read_bytes())
		self.assertEqual(b'appeared later', (output / '@at.txt').read_bytes())
		self.assertEqual({'top.txt', '@at.txt'}, set(os.listdir(output)))
		task._fman_fs.notify_file_changed.assert_called_once_with(as_url(output))
	def test_a_folder_or_a_linked_file_is_never_replaced(self):
		fs, archive = self.archives()[0]
		output = self.root / 'out'
		output.mkdir()
		(output / 'sub').write_bytes(b'my file')
		(self.root / 'shared').write_bytes(b'shared')
		os.link(self.root / 'shared', output / 'top.txt')
		for member in ('docs/sub', 'top.txt'):
			with self.subTest(member=member):
				# Both destinations existed when the copy was prepared.
				with self.assertRaisesRegex(OSError, member.rsplit('/', 1)[-1]):
					self.copies(fs, archive, [member], output)()
		self.assertEqual(b'my file', (output / 'sub').read_bytes())
		self.assertEqual(b'shared', (output / 'top.txt').read_bytes())
		self.assertEqual({'sub', 'top.txt'}, set(os.listdir(output)))
	def test_cancel_while_publishing_keeps_moved_items_and_removes_the_rest(self):
		fs, archive = self.archives()[0]
		output = self.root / 'out'
		output.mkdir()
		task = self.copies(fs, archive, ['top.txt', '@at.txt', 'docs'], output)
		original, renamed = os.rename, []
		def rename(source, destination):
			original(source, destination)
			renamed.append(destination)
			task.check_canceled = Mock(side_effect=Task.Canceled)
		with patch('core.fs.zip.os.rename', side_effect=rename):
			with self.assertRaises(Task.Canceled):
				task()
		self.assertEqual(1, len(renamed))
		self.assertEqual(['top.txt'], os.listdir(output))
		self.assertEqual(b'TTT', (output / 'top.txt').read_bytes())
		task._fman_fs.notify_file_changed.assert_called_once_with(as_url(output))
	def test_a_failed_run_publishes_nothing_and_leaves_no_stage(self):
		fs, archive = self.archives()[0]
		output = self.root / 'out'
		output.mkdir()
		task = self.copies(fs, archive, ['top.txt', 'docs'], output)
		with patch.object(task, 'run_7zip_with_progress', side_effect=_7zipError(2, ['x'], 'ERROR')):
			with self.assertRaises(OSError):
				task()
		self.assertEqual([], os.listdir(output))
		task._fman_fs.notify_file_changed.assert_not_called()
	def test_a_chosen_link_is_skipped(self):
		archive = self.root / 'links.tar.gz'
		_write_tar(archive, 'w:gz', [('./file', b'payload'), ('./link', ('link', 'file'))])
		fs = CompressedTarFileSystem(StubFS(), {'.tar.gz'})
		output = self.root / 'out'
		output.mkdir()
		task = self.copies(fs, archive, ['file', 'link'], output)
		with patch.object(task, 'show_alert') as alert:
			task()
		self.assertEqual(['file'], os.listdir(output))
		self.assertIn('1 symbolic link was skipped', alert.call_args.args[0])
	def test_a_file_stored_after_a_link_of_its_name_is_copied(self):
		archive = self.root / 'updated.tar.gz'
		_write_tar(archive, 'w:gz', [('./file', ('link', 'elsewhere')), ('./file', b'payload'),
			('./twice', ('link', 'a')), ('./twice', ('link', 'b'))])
		output = self.root / 'out'
		output.mkdir()
		task = self.copies(CompressedTarFileSystem(StubFS(), {'.tar.gz'}), archive, ['file', 'twice'], output)
		with patch.object(task, 'show_alert') as alert:
			task()
		self.assertEqual({'file': b'payload'}, _read_tree(output))
		self.assertIn('1 symbolic link was skipped', alert.call_args.args[0])
	def test_names_that_differ_only_by_case_keep_their_own_content(self):
		zip_path = self.root / 'case.zip'
		with ZipFile(zip_path, 'w') as writer:
			writer.writestr('Makefile', b'upper')
			writer.writestr('makefile', b'lower')
		tar_path = self.root / 'case.tar.gz'
		_write_tar(tar_path, 'w:gz', [('./Makefile', b'upper'), ('./makefile', b'lower')])
		for fs, archive in ((ZipFileSystem(StubFS(), {'.zip'}), zip_path),
				(CompressedTarFileSystem(StubFS(), {'.tar.gz'}), tar_path)):
			for member, contents in (('Makefile', b'upper'), ('makefile', b'lower')):
				with self.subTest(archive=archive.name, member=member):
					output = self.root / ('out-%s-%s' % (archive.name, contents.decode()))
					output.mkdir()
					self.copies(fs, archive, [member], output)()
					self.assertEqual({member: contents}, _read_tree(output))
			with self.subTest(archive=archive.name, member='both'):
				# Both would become one file: neither is copied.
				output = self.root / ('out-%s-both' % archive.name)
				output.mkdir()
				with self.assertRaises(OSError) as raised:
					self.copies(fs, archive, ['Makefile', 'makefile'], output)()
				self.assertEqual('2 of 2 items were not copied: Makefile: another chosen item differs only by case; '
					'makefile: another chosen item differs only by case', raised.exception.strerror)
				self.assertEqual([], os.listdir(output))
	def test_an_archive_mixing_dot_slash_names_copies_files_but_no_folder(self):
		# 7-Zip takes './b' and 'b' for different names: a folder could come out incomplete.
		archive = self.root / 'mixed.tar'
		_write_tar(archive, 'w', [('./a/x.txt', b'X'), ('b/y.txt', b'Y'), ('b/z.txt', b'Z')])
		fs = TarFileSystem(StubFS(), {'.tar'})
		output = self.root / 'out'
		output.mkdir()
		with self.assertRaisesRegex(OSError, 'both with and without'):
			self.copies(fs, archive, ['b'], output)()
		self.assertEqual([], os.listdir(output))
		# Every file of 'b' is chosen: their own names are passed, not the folder's.
		self.copies(fs, archive, ['a/x.txt', 'b/y.txt', 'b/z.txt'], output)()
		self.assertEqual({'x.txt': b'X', 'y.txt': b'Y', 'z.txt': b'Z'}, _read_tree(output))
	def test_an_item_that_cannot_be_moved_is_skipped_and_named_once(self):
		archive = self.root / 'five.zip'
		names = ['f%d.txt' % index for index in range(1, 6)]
		with ZipFile(archive, 'w') as writer:
			for name in names:
				writer.writestr(name, name.encode())
		fs = ZipFileSystem(StubFS(), {'.zip'})
		for blocked, message in ((['f3.txt'], r'^1 of 5 items was not copied: f3\.txt: [^;]+$'),
				(names[1:], r'^4 of 5 items were not copied: f2\.txt: .+; f3\.txt: .+; f4\.txt: .+; \.\.\.$')):
			with self.subTest(blocked=blocked):
				output = self.root / ('out%d' % len(blocked))
				output.mkdir()
				for name in blocked:
					# Agreed to replace, but a read-only file refuses it.
					(output / name).write_bytes(b'kept')
					(output / name).chmod(0o444)
					self.addCleanup((output / name).chmod, 0o666)
				task = self.copies(fs, archive, names, output)
				with self.assertRaises(OSError) as raised:
					task()
				self.assertRegex(raised.exception.strerror, message)
				self.assertEqual({name: b'kept' if name in blocked else name.encode() for name in names},
					_read_tree(output))
				task._fman_fs.notify_file_changed.assert_called_once_with(as_url(output))
	def test_a_name_part_like_a_drive_stays_inside_the_stage(self):
		archive = self.root / 'drive.zip'
		with ZipFile(archive, 'w') as writer:
			writer.writestr('dir/c:x.txt', b'colon')
			writer.writestr('dir/x.txt', b'X')
		fs = ZipFileSystem(StubFS(), {'.zip'})
		output = self.root / 'out'
		output.mkdir()
		base = 'zip://' + archive.as_posix() + '/dir/'
		task, other = (fs.prepare_copy(base + member, as_url(output / name))[0]
			for member, name in (('c:x.txt', 'cx.txt'), ('x.txt', 'x.txt')))
		task._fman_fs = Mock()
		self.assertTrue(task.absorb(other))
		# 7-Zip writes 'c:x.txt' under another name; 'dir/x.txt' must not be taken for it.
		with self.assertRaises(OSError) as raised:
			task()
		self.assertEqual('1 of 2 items was not copied: cx.txt: not extracted', raised.exception.strerror)
		self.assertEqual({'x.txt': b'X'}, _read_tree(output))

class OrdinaryFileTest(TestCase):
	def test_a_copy_may_replace_a_cloud_file_but_no_link_or_hard_link(self):
		from core.fs.zip import _ordinary_file
		from stat import S_IFREG
		for tag, links, expected in ((0, 1, True), (0x9000601A, 1, True), (0, 2, False),
				(0xA000000C, 1, False), (0xA0000003, 1, False)):
			with self.subTest(tag=hex(tag), links=links):
				info = Mock(st_mode=S_IFREG | 0o666, st_nlink=links, st_reparse_tag=tag)
				with patch('core.fs.zip.os.lstat', return_value=info):
					self.assertEqual(expected, _ordinary_file('file'))

class CompressedTarTest(_ArchiveFixtures):
	def test_every_suffix_lists_and_extracts_without_other_files(self):
		fs = CompressedTarFileSystem(StubFS(), {suffix for suffix, mode in _TAR_MODES})
		for suffix, mode in _TAR_MODES:
			with self.subTest(suffix=suffix):
				archive = self.root / ('x' + suffix)
				_write_tar(archive, mode, [('./', None), ('./docs', None), ('./docs/a.txt', b'A'), ('./b.txt', b'B')])
				before = set(os.listdir(self.root))
				self.assertEqual({'docs', 'b.txt'}, set(fs.iterdir(archive.as_posix())))
				output = self.root / ('out' + suffix)
				output.mkdir()
				self.copies(fs, archive, ['docs'], output)()
				self.assertEqual({'docs': {'a.txt': b'A'}}, _read_tree(output))
				self.assertEqual(before | {output.name}, set(os.listdir(self.root)))
	def test_other_data_is_refused_and_keeps_no_list(self):
		import gzip
		valid = self.root / 'valid.tar.gz'
		_write_tar(valid, 'w:gz', [('./big.bin', os.urandom(1 << 20))])
		zip_bytes = BytesIO()
		with ZipFile(zip_bytes, 'w') as writer:
			writer.writestr('a.txt', b'a')
		plain = self.root / 'plain.tar'
		_write_tar(plain, 'w', [('a.txt', b'a')])
		fixtures = {'zip': zip_bytes.getvalue(), 'tar': plain.read_bytes(), 'text': b'just text\n',
			'small gzip': gzip.compress(b'just text\n'), 'large gzip': gzip.compress(b'text line\n' * 300_000),
			'truncated': valid.read_bytes()[:len(valid.read_bytes()) // 2]}
		fs = CompressedTarFileSystem(StubFS(), {'.tar.gz'})
		for name, contents in fixtures.items():
			with self.subTest(name):
				_MEMBER_LISTS.clear()
				archive = self.root / 'x.tar.gz'
				archive.write_bytes(contents)
				with self.assertRaisesRegex(OSError, 'Not a compressed tar archive'):
					list(fs.iterdir(archive.as_posix()))
				self.assertEqual(0, len(_MEMBER_LISTS._lists))
	def test_empty_tar_is_an_empty_folder(self):
		fs = CompressedTarFileSystem(StubFS(), {'.tar.gz'})
		# A tar of an empty folder holds only its '.' entry.
		for index, entries in enumerate(([], [('./', None)], [('.', None)])):
			with self.subTest(entries=entries):
				archive = self.root / ('empty%d.tar.gz' % index)
				_write_tar(archive, 'w:gz', entries)
				self.assertEqual([], list(fs.iterdir(archive.as_posix())))
	def test_the_type_check_reads_only_the_header_of_another_archive(self):
		archive = self.root / 'many.tar.gz'
		with ZipFile(archive, 'w') as writer:
			for index in range(5000):
				writer.writestr('f%05d' % index, b'')
		lines = []
		original = _7zip.progress_records
		def progress_records(command, check, truncate=True):
			records = original(command, check, truncate)
			try:
				for record in records:
					lines.append(record)
					yield record
			finally:
				records.close()
		with patch.object(_7zip, 'progress_records', progress_records):
			with self.assertRaisesRegex(OSError, 'Not a compressed tar archive'):
				list(CompressedTarFileSystem(StubFS(), {'.tar.gz'}).iterdir(archive.as_posix()))
		self.assertLess(len(lines), 100)
	def test_cancel_ends_both_processes(self):
		archive = self.root / 'big.tar.gz'
		_write_tar(archive, 'w:gz', [('./big.bin', os.urandom(8 << 20))])
		output = self.root / 'out'
		def cancel():
			raise Task.Canceled()
		with self.assertRaises(Task.Canceled):
			with _7zip(['x', '-y', '-o' + str(output), '-si', '-ttar'], allow_warning=False,
					pipe_from=str(archive)) as command:
				list(command.progress_records(cancel))
		self.assertIsNotNone(command._process.poll())
		self.assertIsNotNone(command._source.poll())
		self.assertFalse(any(thread.name.startswith('7zip') for thread in enumerate_threads()))
	def test_status_message_is_cleared_after_a_read_outside_a_task(self):
		archive = self.root / 'x.tar.gz'
		_write_tar(archive, 'w:gz', [('./a.txt', b'a')])
		fs = CompressedTarFileSystem(StubFS(), {'.tar.gz'})
		with patch('core.fs.zip._StatusProgress') as progress:
			list(fs.iterdir(archive.as_posix()))
		progress.assert_called_once_with('Reading x.tar.gz')
		progress.return_value.close.assert_called_once()
		_MEMBER_LISTS.clear()
		with patch('core.fs.zip._StatusProgress') as progress, \
				patch('core.fs.zip._read_members', side_effect=OSError('failed')):
			with self.assertRaises(OSError):
				list(fs.iterdir(archive.as_posix()))
		progress.return_value.close.assert_called_once()

class StatusProgressTest(TestCase):
	def test_changes_are_shown_at_most_every_250_ms_and_cleared(self):
		with patch('core.fs.zip.show_status_message') as show, \
				patch('core.fs.zip.clear_status_message') as clear, \
				patch('core.fs.zip.time.monotonic', side_effect=[0, .1, .3, .31, .6]):
			progress = _StatusProgress('Reading x.tar.gz')
			for percent in (10, 20, 30, 30, 40):
				progress(percent)
			progress.close()
		self.assertEqual(['Reading x.tar.gz: 10%', 'Reading x.tar.gz: 30%', 'Reading x.tar.gz: 40%'],
			[call.args[0] for call in show.call_args_list])
		clear.assert_called_once()

class PackArchiveTest(_ArchiveFixtures):
	def sources(self):
		(self.root / 'a' / 'sub').mkdir(parents=True)
		(self.root / 'a' / 'f.txt').write_bytes(b'F')
		(self.root / 'a' / 'sub' / 'g.txt').write_bytes(b'G')
		(self.root / 'b').mkdir()
		(self.root / 'b' / 'h.txt').write_bytes(b'H')
		return [str(self.root / 'a' / 'f.txt'), str(self.root / 'a' / 'sub'), str(self.root / 'b' / 'h.txt')]
	def test_one_run_per_type_stores_items_under_their_names(self):
		sources = self.sources()
		for kind, fs_type in (('zip', ZipFileSystem), ('7z', SevenZipFileSystem), ('tar', TarFileSystem)):
			with self.subTest(kind=kind):
				archive = self.root / ('packed.' + kind)
				with _count_7zip_starts() as starts:
					PackArchive(sources, str(archive), kind)()
				self.assertEqual(1, len(starts))
				fs = fs_type(StubFS(), {'.' + kind})
				self.assertEqual({'f.txt', 'sub', 'h.txt'}, set(fs.iterdir(archive.as_posix())))
				self.assertEqual(['g.txt'], list(fs.iterdir(archive.as_posix() + '/sub')))
				self.notified.assert_called_with(as_url(archive))
		self.assertEqual({'a', 'b', 'packed.zip', 'packed.7z', 'packed.tar'}, set(os.listdir(self.root)))
	def test_existing_name_and_duplicate_names_write_nothing(self):
		sources = self.sources()
		existing = self.root / 'existing.zip'
		existing.write_bytes(b'kept')
		with self.assertRaisesRegex(FileExistsError, 'existing.zip'):
			PackArchive(sources, str(existing), 'zip')()
		self.assertEqual(b'kept', existing.read_bytes())
		(self.root / 'b' / 'f.txt').write_bytes(b'other F')
		with self.assertRaises(OSError) as raised:
			PackArchive([sources[0], str(self.root / 'b' / 'f.txt')], str(self.root / 'twice.zip'), 'zip')()
		self.assertEqual('Two chosen items have the same name: f.txt', raised.exception.strerror)
		with self.assertRaisesRegex(FileNotFoundError, 'Destination folder does not exist'):
			PackArchive(sources, str(self.root / 'missing' / 'packed.zip'), 'zip')()
		self.assertEqual({'a', 'b', 'existing.zip'}, set(os.listdir(self.root)))
	def test_cancel_and_failure_leave_no_temporary_file(self):
		sources = self.sources()
		for error in (Task.Canceled(), _7zipError(2, ['a'], 'ERROR: failed')):
			with self.subTest(error=type(error).__name__):
				task = PackArchive(sources, str(self.root / 'packed.zip'), 'zip')
				with patch.object(task, 'run_7zip_with_progress', side_effect=error):
					with self.assertRaises((Task.Canceled, OSError)):
						task()
				self.assertEqual({'a', 'b'}, set(os.listdir(self.root)))
		self.notified.assert_not_called()
	def test_an_archive_inside_a_chosen_folder_holds_no_staging_files(self):
		self.sources()
		archive = self.root / 'a' / 'sub' / 'a.zip'
		PackArchive([str(self.root / 'a')], str(archive), 'zip')()
		with ZipFile(archive) as reader:
			self.assertEqual(['a/', 'a/f.txt', 'a/sub/', 'a/sub/g.txt'], sorted(reader.namelist()))
		self.assertEqual({'g.txt', 'a.zip'}, set(os.listdir(self.root / 'a' / 'sub')))