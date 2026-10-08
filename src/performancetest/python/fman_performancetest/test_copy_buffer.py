"""Opt-in correctness checks for an unshipped small-file copy-buffer candidate."""

from contextlib import contextmanager
from io import BytesIO
import os
from pathlib import Path
from stat import S_IWRITE
from tempfile import TemporaryDirectory
from unittest import TestCase, skipUnless
from unittest.mock import Mock, patch

from core.fs.local import CopyFile, LocalFileSystem, copystat
from fman import Task
from fman.url import as_url


SMALL_BUFFER_SIZE = 64 * 1024
_original_copy_bytes = CopyFile._copy_bytes


def small_copy_bytes(task, source, destination):
	if not 0 < task.get_size() <= SMALL_BUFFER_SIZE:
		return _original_copy_bytes(task, source, destination)
	written = 0
	while True:
		task.check_canceled()
		buffer = source.read(SMALL_BUFFER_SIZE)
		if not buffer:
			break
		written += destination.write(buffer)
		task.set_progress(written)


class RecordingReader(BytesIO):
	def __init__(self, content, limit=None):
		super().__init__(content)
		self.read_sizes = []
		self.limit = limit

	def read(self, size=-1):
		self.read_sizes.append(size)
		return super().read(size if self.limit is None else min(size, self.limit))


def payload(size):
	return (bytes(range(256)) * ((size + 255) // 256))[:size]


class SmallCopyBufferTest(TestCase):
	def test_boundaries_and_unknown_size_keep_exact_bytes(self):
		for length, hint in ((0, 0), (1, 1), (4096, 4096), (65535, 65535),
				(65536, 65536), (65537, 65537), (2 * 1024 * 1024 + 7, 2 * 1024 * 1024 + 7),
				(4096, 0), (4096, 1024 * 1024)):
			with self.subTest(length=length, hint=hint):
				content = payload(length)
				source, destination = RecordingReader(content), BytesIO()
				task = Task('Copy buffer probe', size=hint)
				with patch(__name__ + '._original_copy_bytes', wraps=_original_copy_bytes) as original:
					small_copy_bytes(task, source, destination)
					if 0 < hint <= SMALL_BUFFER_SIZE:
						original.assert_not_called()
						expected = SMALL_BUFFER_SIZE
					else:
						original.assert_called_once_with(task, source, destination)
						expected = 1024 * 1024
				self.assertEqual(content, destination.getvalue())
				self.assertEqual({expected}, set(source.read_sizes))
				self.assertEqual(length, task.get_progress())

	def test_short_reads_continue_until_eof(self):
		content = payload(1000)
		source, destination = RecordingReader(content, limit=7), BytesIO()
		task = Task('Short-read probe', size=len(content))
		small_copy_bytes(task, source, destination)
		self.assertEqual(content, destination.getvalue())
		self.assertEqual({SMALL_BUFFER_SIZE}, set(source.read_sizes))
		self.assertGreater(len(source.read_sizes), 100)
		self.assertEqual(len(content), task.get_progress())

	def test_stale_small_hint_does_not_truncate_larger_input(self):
		content = payload(3 * SMALL_BUFFER_SIZE + 17)
		source, destination = RecordingReader(content), BytesIO()
		task = Task('Stale size hint', size=1)
		small_copy_bytes(task, source, destination)
		self.assertEqual(content, destination.getvalue())
		self.assertEqual([SMALL_BUFFER_SIZE] * 5, source.read_sizes)
		self.assertEqual(len(content), task.get_progress())

	def test_cancellation_before_read_does_not_write(self):
		source, destination = RecordingReader(b'keep'), BytesIO()
		task = Task('Canceled before read', size=4)
		task._dialog._was_canceled = True
		with self.assertRaises(Task.Canceled):
			small_copy_bytes(task, source, destination)
		self.assertEqual([], source.read_sizes)
		self.assertEqual(b'', destination.getvalue())


@skipUnless(os.name == 'nt', 'The real copier targets Windows')
class SmallCopyBufferFileTest(TestCase):
	@contextmanager
	def files(self, content=b'new contents', existing=None):
		with TemporaryDirectory(prefix='SmallCopyBufferTest-') as directory:
			root = Path(directory)
			source, destination = root / 'source.bin', root / 'destination.bin'
			source.write_bytes(content)
			if existing is not None:
				destination.write_bytes(existing)
			task = CopyFile(LocalFileSystem(), as_url(source), as_url(destination), len(content))
			try:
				with patch.object(task, '_copy_bytes', side_effect=lambda reader, writer:
						small_copy_bytes(task, reader, writer)):
					yield root, source, destination, task
			finally:
				for path in (source, destination):
					if path.exists():
						path.chmod(S_IWRITE)

	def assert_clean(self, root, destination_exists):
		self.assertEqual({'source.bin', 'destination.bin'} if destination_exists else {'source.bin'},
			{path.name for path in root.iterdir()})

	def test_real_file_boundaries_match_baseline(self):
		for size in (0, 1, 65535, 65536, 65537, 2 * 1024 * 1024 + 7):
			for existing in (None, b'old contents'):
				with self.subTest(size=size, overwrite=existing is not None), self.files(payload(size), existing) as case:
					root, source, destination, task = case
					stamp = 1700000000000000000
					os.utime(source, ns=(stamp, stamp))
					baseline = root / 'baseline.bin'
					if existing is not None:
						baseline.write_bytes(existing)
					CopyFile(LocalFileSystem(), as_url(source), as_url(baseline), size)()
					task()
					self.assertEqual(source.read_bytes(), destination.read_bytes())
					self.assertEqual(baseline.read_bytes(), destination.read_bytes())
					self.assertEqual(baseline.stat().st_mtime_ns, destination.stat().st_mtime_ns)
					self.assertEqual(stamp, destination.stat().st_mtime_ns)
					self.assertEqual(size, task.get_progress())
					baseline.unlink()
					self.assert_clean(root, True)

	def test_file_growing_between_reads_is_copied_to_eof(self):
		initial, extra = payload(4096), payload(2 * SMALL_BUFFER_SIZE + 17)
		with self.files(initial) as (root, source, destination, task):
			progress = task.set_progress
			grown = False
			def append_after_first_write(value):
				nonlocal grown
				progress(value)
				if not grown:
					grown = True
					with source.open('ab') as stream:
						stream.write(extra)
			with patch.object(task, 'set_progress', side_effect=append_after_first_write):
				task()
			self.assertTrue(grown)
			self.assertEqual(initial + extra, source.read_bytes())
			self.assertEqual(initial + extra, destination.read_bytes())
			self.assertEqual(len(initial) + len(extra), task.get_progress())
			self.assert_clean(root, True)

	def test_read_write_and_cancellation_failures_preserve_destination(self):
		for existing in (None, b'old contents'):
			for failure in ('read', 'write', 'cancel'):
				with self.subTest(overwrite=existing is not None, failure=failure), self.files(existing=existing) as case:
					root, source, destination, task = case
					def interrupted(reader, writer):
						if failure == 'read':
							reader = Mock(read=Mock(side_effect=[b'n', OSError(5, 'Fixture read failed')]))
						elif failure == 'write':
							def fail_write(data):
								writer.write(data[:1])
								raise OSError(28, 'Fixture write failed')
							return small_copy_bytes(task, reader, Mock(write=Mock(side_effect=fail_write)))
						return small_copy_bytes(task, reader, writer)
					progress = task.set_progress
					def cancel_after_write(value):
						progress(value)
						if failure == 'cancel':
							task._dialog._was_canceled = True
					with patch.object(task, '_copy_bytes', side_effect=interrupted), \
							patch.object(task, 'set_progress', side_effect=cancel_after_write), \
							patch.object(task._fs, 'notify_file_added') as added, \
							patch.object(task._fs, 'notify_file_changed') as changed:
						with self.assertRaises(Task.Canceled if failure == 'cancel' else OSError):
							task()
						added.assert_not_called()
						changed.assert_not_called()
					self.assertEqual(b'new contents', source.read_bytes())
					self.assertEqual(existing is not None, destination.exists())
					if existing is not None:
						self.assertEqual(existing, destination.read_bytes())
					self.assert_clean(root, existing is not None)

	def test_cancel_at_publication_keeps_old_file(self):
		with self.files(existing=b'old contents') as (root, source, destination, task):
			def cancel_after_metadata(*args, **kwargs):
				copystat(*args, **kwargs)
				task._dialog._was_canceled = True
			with patch('core.fs.local.copystat', side_effect=cancel_after_metadata):
				with self.assertRaises(Task.Canceled):
					task()
			self.assertEqual(b'new contents', source.read_bytes())
			self.assertEqual(b'old contents', destination.read_bytes())
			self.assert_clean(root, True)

	def test_competing_destination_is_not_overwritten(self):
		for existing in (None, b'old contents'):
			with self.subTest(overwrite=existing is not None), self.files(existing=existing) as case:
				root, source, destination, task = case
				def competing_write(*args, **kwargs):
					copystat(*args, **kwargs)
					destination.write_bytes(b'competing contents, different size')
				with patch('core.fs.local.copystat', side_effect=competing_write):
					with self.assertRaises(OSError):
						task()
				self.assertEqual(b'new contents', source.read_bytes())
				self.assertEqual(b'competing contents, different size', destination.read_bytes())
				self.assert_clean(root, True)

	def test_readonly_source_and_destination_policies(self):
		for readonly_source in (True, False):
			with self.subTest(readonly_source=readonly_source), self.files(existing=b'old contents') as case:
				root, source, destination, task = case
				(source if readonly_source else destination).chmod(0o444)
				if readonly_source:
					task()
					self.assertEqual(b'new contents', destination.read_bytes())
					self.assertFalse(destination.stat().st_mode & S_IWRITE)
				else:
					with self.assertRaises(PermissionError):
						task()
					self.assertEqual(b'old contents', destination.read_bytes())
				self.assertEqual(b'new contents', source.read_bytes())
				self.assert_clean(root, True)