from calculate_file_hash.hashing import AVAILABLE_ALGORITHMS, available_algorithms, compute_hash, default_algorithm, settings_snapshot
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import patch

import hashlib
import os
import zlib


class HashingTest(TestCase):
	def setUp(self):
		self.directory = TemporaryDirectory()
		self.addCleanup(self.directory.cleanup)
		self.path = Path(self.directory.name) / 'input.txt'

	def test_vectors_and_chunked_progress(self):
		for data in (b'', b'a', b'abc', bytes(range(256)) * 3):
			self.path.write_bytes(data)
			for algorithm, label in AVAILABLE_ALGORITHMS:
				with self.subTest(data_size=len(data), algorithm=algorithm):
					progress = []
					result = compute_hash(self.path, algorithm, progress.append, lambda: None, chunk_size=17)
					expected = '%08X' % zlib.crc32(data) if algorithm == 'crc32' else hashlib.new(algorithm, data).hexdigest()
					self.assertEqual(expected, result.digest)
					self.assertEqual(len(data), result.bytes_read)
					self.assertFalse(result.changed)
					self.assertEqual(sorted(progress), progress)
					self.assertEqual(len(data), progress[-1])

	def test_cancellation_closes_file(self):
		self.path.write_bytes(b'abcdef')
		opened = []
		real_open = open
		def capture(*args, **kwargs):
			source = real_open(*args, **kwargs)
			opened.append(source)
			return source
		progress = []
		def cancel():
			if progress and progress[-1] > 0:
				raise InterruptedError('Canceled')
		with patch('calculate_file_hash.hashing.open', side_effect=capture):
			with self.assertRaises(InterruptedError):
				compute_hash(self.path, 'sha256', progress.append, cancel, chunk_size=2)
		self.assertTrue(opened[0].closed)
		self.path.unlink()

	def test_changed_timestamp_is_rejected(self):
		self.path.write_bytes(b'abcdef')
		before = self.path.stat()
		def report(done):
			if done:
				os.utime(self.path, ns=(before.st_atime_ns, before.st_mtime_ns + 1000000000))
		self.assertTrue(compute_hash(self.path, 'sha256', report, lambda: None, 2).changed)

	def test_path_replacement_is_rejected(self):
		self.path.write_bytes(b'abc')
		info = self.path.stat()
		replacement = SimpleNamespace(st_dev=info.st_dev, st_ino=info.st_ino + 1, st_size=info.st_size, st_mtime_ns=info.st_mtime_ns)
		with patch('calculate_file_hash.hashing.os.stat', return_value=replacement):
			self.assertTrue(compute_hash(self.path, 'sha256', lambda done: None, lambda: None).changed)

	def test_read_error_propagates_and_invalid_chunk(self):
		with self.assertRaises(FileNotFoundError):
			compute_hash(self.path, 'sha256', lambda done: None, lambda: None)
		for value in (0, -1, True, '4'):
			with self.assertRaises(ValueError):
				compute_hash(self.path, 'sha256', lambda done: None, lambda: None, value)

	def test_availability_and_strong_fallback(self):
		real_new = hashlib.new
		def unavailable(name):
			if name == 'sha256':
				raise ValueError('Unavailable')
			return real_new(name)
		with patch('calculate_file_hash.hashing.hashlib.new', side_effect=unavailable):
			available = available_algorithms()
		self.assertNotIn('sha256', dict(available))
		self.assertEqual('sha512', default_algorithm('sha256', available))
		weak = (('sha1', 'SHA-1'), ('md5', 'MD5'), ('crc32', 'CRC32'))
		with self.assertRaises(ValueError):
			default_algorithm('missing', weak)
		self.assertEqual('md5', default_algorithm('md5', weak))

	def test_settings_are_copied_and_validated(self):
		for value, expected in ((0, 1), (65, 64), (True, 4), ('8', 4), (8, 8)):
			original = {'chunk_size_mib': value, 'custom': 'keep'}
			settings = settings_snapshot(original)
			self.assertEqual(expected, settings['chunk_size_mib'])
			settings['default_algorithm'] = 'md5'
			self.assertNotIn('default_algorithm', original)
			self.assertEqual('keep', settings['custom'])


class HashCommandTest(TestCase):
	def setUp(self):
		import calculate_file_hash as plugin
		from calculate_file_hash.ui import HashRequest
		from fman.ui import UiOwner
		from threading import Event
		from unittest.mock import Mock
		self.plugin = plugin
		self.directory = TemporaryDirectory()
		self.addCleanup(self.directory.cleanup)
		self.path = Path(self.directory.name) / 'sample.txt'
		self.path.write_bytes(b'abc')
		self.url = 'file://' + self.path.as_posix()
		self.pane = Mock()
		self.pane.get_path.return_value = 'file://C:/'
		self.pane.get_file_under_cursor.return_value = self.url
		self.settings = {}
		self.owner = UiOwner()
		self.alive = Event()
		self.alive.set()
		self.session = Mock()
		self.session.begin.side_effect = lambda url, algorithm, auto_copy: HashRequest(url, algorithm, auto_copy, self.owner, self.alive)
		def submit(task):
			try:
				task()
			except plugin.Task.Canceled:
				pass
		for target, options in (
			('HashController.owner', {'new': self.owner}),
			('HashController.show', {'return_value': SimpleNamespace(session=self.session)}),
			('load_json', {'return_value': self.settings}),
			('save_json', {}), ('show_status_message', {}),
			('submit_task', {'side_effect': submit}),
			('_warned_default', {'new': False}),
		):
			patcher = patch('calculate_file_hash.' + target, **options)
			patcher.start()
			self.addCleanup(patcher.stop)

	def test_default_and_explicit_algorithm(self):
		self.plugin.CalculateFileHash(self.pane)()
		request, result, error, status_only = self.session.complete.call_args.args
		self.assertEqual('sha256', request.algorithm)
		self.assertEqual(hashlib.sha256(b'abc').hexdigest(), result.digest)
		self.assertIsNone(error)
		self.plugin.CalculateFileHash(self.pane)(algorithm='crc32')
		self.assertEqual('352441C2', self.session.complete.call_args.args[1].digest)

	def test_missing_directory_and_invalid_algorithm(self):
		self.pane.get_file_under_cursor.return_value = None
		self.plugin.CalculateFileHash(self.pane)()
		self.plugin.submit_task.assert_not_called()
		self.plugin.CalculateFileHash(self.pane)(url=self.url, algorithm='no-such-hash')
		self.plugin.submit_task.assert_not_called()
		self.plugin.CalculateFileHash(self.pane)(url='file://' + Path(self.directory.name).as_posix())
		self.plugin.submit_task.assert_not_called()
		self.assertTrue(self.session.complete.call_args.args[3])

	def test_visibility_has_no_filesystem_io(self):
		with patch('calculate_file_hash.os.stat') as file_stat:
			self.assertTrue(self.plugin.CalculateFileHash(self.pane).is_visible())
			self.pane.get_path.return_value = 'zip://archive'
			self.assertFalse(self.plugin.CalculateFileHash(self.pane).is_visible())
			file_stat.assert_not_called()

	def test_cancel_read_error_and_changed_result(self):
		from calculate_file_hash.hashing import HashResult
		with patch('calculate_file_hash.compute_hash', side_effect=self.plugin.Task.Canceled()):
			self.plugin.CalculateFileHash(self.pane)()
		self.assertIsNone(self.session.complete.call_args.args[1])
		with patch('calculate_file_hash.compute_hash', side_effect=PermissionError('locked')):
			self.plugin.CalculateFileHash(self.pane)()
		self.assertIn('Could not read', self.session.complete.call_args.args[2])
		with patch('calculate_file_hash.compute_hash', return_value=HashResult('bad', 3, True)):
			self.plugin.CalculateFileHash(self.pane)()
		self.assertIsNone(self.session.complete.call_args.args[1])
		self.assertIn('changed', self.session.complete.call_args.args[2])

	def test_picker_command_label_has_no_ellipsis(self):
		self.assertEqual('Calculate file hash by', self.plugin.CalculateFileHashBy.aliases[0])

	def test_picker_cancel_and_captured_target(self):
		with patch('calculate_file_hash.show_quicksearch', return_value=None):
			self.plugin.CalculateFileHashBy(self.pane)()
		self.session.begin.assert_not_called()
		self.plugin.HashController.show.assert_not_called()
		def choose(*args, **kwargs):
			self.plugin.HashController.show.assert_not_called()
			self.pane.get_file_under_cursor.return_value = 'file://C:/elsewhere.txt'
			return '', 'sha512'
		with patch('calculate_file_hash.show_quicksearch', side_effect=choose):
			self.plugin.CalculateFileHashBy(self.pane)()
		self.assertEqual(self.url, self.session.complete.call_args.args[0].url)
		self.assertEqual(hashlib.sha512(b'abc').hexdigest(), self.session.complete.call_args.args[1].digest)

	def test_remember_copies_settings_and_save_failure_still_hashes(self):
		self.settings.update(remember_last_algorithm=True, chunk_size_mib=65, auto_copy='invalid', custom='preserved')
		self.plugin.CalculateFileHash(self.pane)(algorithm='sha512')
		saved = self.plugin.save_json.call_args.args[1]
		self.assertEqual(dict(self.settings, default_algorithm='sha512'), saved)
		self.assertNotIn('default_algorithm', self.settings)
		self.plugin.save_json.side_effect = OSError('read-only settings')
		self.plugin.CalculateFileHash(self.pane)(algorithm='sha512')
		self.assertIsNotNone(self.session.complete.call_args.args[1])
		self.assertNotIn('default_algorithm', self.settings)

	def test_unloaded_and_busy_commands_do_not_hash(self):
		self.owner.invalidate()
		self.plugin.CalculateFileHash(self.pane)()
		self.plugin.submit_task.assert_not_called()
		self.owner.active = True
		self.plugin._busy_panes[self.pane] = True
		try:
			self.plugin.CalculateFileHash(self.pane)()
			self.plugin.submit_task.assert_not_called()
		finally:
			self.plugin._busy_panes.pop(self.pane)