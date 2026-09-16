from core.commands import UnpackArchive, _UnpackArchive, _unpack_archive_name, \
	_get_handler_for_archive, _unpack_error_text
from core.fs.zip import Extract, ZipFileSystem
from core.tests import StubFS
from fman import Task
from fman.impl.plugins.plugin import _get_command_name
from fman.url import as_url, splitscheme, as_human_readable
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import Mock, patch
from zipfile import ZipFile

import os

class UnpackArchiveTest(TestCase):
	def setUp(self):
		temporary = TemporaryDirectory()
		self.addCleanup(temporary.cleanup)
		self.root = Path(temporary.name)
		self.source = self.root / 'Reports.zip'
		with ZipFile(self.source, 'w') as archive:
			archive.writestr('file.txt', b'payload')
		self.original = self.source.read_bytes()
		self.pane = Mock()
		self.pane.get_path.return_value = as_url(self.root)
		self.pane.get_selected_files.return_value = []
		self.pane.get_file_under_cursor.return_value = as_url(self.source)
		self.command = UnpackArchive(self.pane)
		for name in ('show_alert', 'show_prompt', 'show_status_message', 'submit_task', 'load_json', 'samefile', 'is_dir', 'prepare_copy'):
			patcher = patch('core.commands.' + name)
			setattr(self, name, patcher.start())
			self.addCleanup(patcher.stop)
		self.load_json.return_value = {'archive_handlers': {'.zip': 'zip://'}}
		self.samefile.side_effect = lambda first, second: os.path.samefile(as_human_readable(first), as_human_readable(second))
		self.is_dir.side_effect = lambda url: Path(as_human_readable(url)).is_dir()
		self.backend = ZipFileSystem(StubFS(), {'.zip'})
		self.prepare_copy.side_effect = self.backend.prepare_copy
		self.submit_task.side_effect = lambda task: task()
		patcher = patch('fman.fs.notify_file_added')
		self.notification = patcher.start()
		self.addCleanup(patcher.stop)
		self.addCleanup(self.show_prompt.assert_not_called)
	def assert_no_success(self):
		self.show_status_message.assert_not_called()
		self.pane.place_cursor_at.assert_not_called()
		self.assertEqual(self.original, self.source.read_bytes())
	def test_registration_name_and_cursor_fallback(self):
		self.assertEqual('unpack_archive', _get_command_name(UnpackArchive))
		self.assertIn('Unpack archive', self.command.aliases)
		self.command()
		self.assertEqual(b'payload', (self.root / 'Reports/file.txt').read_bytes())
		self.assertEqual(self.original, self.source.read_bytes())
		self.pane.place_cursor_at.assert_called_once_with(as_url(self.root / 'Reports'))
		self.show_status_message.assert_called_once_with('Unpacked Reports', timeout_secs=5)
		self.show_alert.assert_not_called()
	def test_existing_file_or_directory_stops_before_submission(self):
		output = self.root / 'Reports'
		for directory in (False, True):
			with self.subTest(directory=directory):
				output.mkdir() if directory else output.write_bytes(b'existing')
				self.command()
				self.show_alert.assert_called_with('Destination already exists: Reports')
				self.submit_task.assert_not_called()
				self.prepare_copy.assert_not_called()
				self.assert_no_success()
				if directory:
					self.assertEqual([], list(output.iterdir()))
					output.rmdir()
				else:
					self.assertEqual(b'existing', output.read_bytes())
					output.unlink()
	def test_dangling_entry_stops_before_submission(self):
		with patch('core.commands.os.path.lexists', return_value=True):
			self.command()
		self.submit_task.assert_not_called()
		self.show_alert.assert_called_once_with('Destination already exists: Reports')
		self.assert_no_success()
	def test_invalid_selection(self):
		for chosen in ([], [as_url(self.source)] * 2, ['zip://archive.zip/file'], [as_url(self.root)]):
			with self.subTest(chosen=chosen):
				self.pane.get_selected_files.return_value = chosen
				self.pane.get_file_under_cursor.return_value = None
				self.command()
				self.submit_task.assert_not_called()
				self.assert_no_success()
	def test_selected_files_override_cursor(self):
		self.pane.get_selected_files.return_value = [as_url(self.source)]
		self.pane.get_file_under_cursor.return_value = 'file://unrelated.txt'
		self.command()
		self.assertTrue((self.root / 'Reports').is_dir())
	def test_parent_identity_and_errors(self):
		for result in (False, FileNotFoundError('missing parent'), PermissionError('parent denied')):
			with self.subTest(result=result):
				self.samefile.side_effect = result if isinstance(result, OSError) else None
				self.samefile.return_value = result
				self.command()
				self.submit_task.assert_not_called()
				self.assert_no_success()
	def test_parent_case_and_trailing_separator(self):
		self.pane.get_path.return_value = as_url(self.root).upper().replace('FILE://', 'file://') + '/'
		self.command()
		self.assertTrue((self.root / 'Reports').is_dir())
	def test_cancellation_does_not_report_success(self):
		def submit(task):
			try:
				with patch.object(Extract, '__call__', side_effect=Task.Canceled):
					task()
			except Task.Canceled:
				pass
		self.submit_task.side_effect = submit
		self.command()
		self.assert_no_success()
		self.show_alert.assert_not_called()
	def test_navigation_and_missing_cursor_are_best_effort(self):
		self.pane.get_path.side_effect = [as_url(self.root), 'file://elsewhere']
		self.command()
		self.pane.place_cursor_at.assert_not_called()
		self.show_status_message.assert_called_once()
	def test_closed_pane_does_not_turn_success_into_error(self):
		self.pane.get_path.side_effect = [as_url(self.root), RuntimeError('pane deleted')]
		self.command()
		self.show_status_message.assert_called_once()
		self.show_alert.assert_not_called()
	def test_missing_or_filtered_row_does_not_report_failure(self):
		self.pane.place_cursor_at.side_effect = ValueError('Row not found')
		self.command()
		self.show_status_message.assert_called_once()
		self.show_alert.assert_not_called()
	def test_late_conflict_alert_preserves_file(self):
		output = self.root / 'Reports'
		original_run = Extract.run_7zip_with_progress
		def extract(task, *args, **kwargs):
			original_run(task, *args, **kwargs)
			output.write_bytes(b'existing file')
		with patch.object(Extract, 'run_7zip_with_progress', autospec=True, side_effect=extract):
			self.command()
		self.show_alert.assert_called_once_with('Destination already exists: Reports')
		self.assertEqual(b'existing file', output.read_bytes())
		self.assert_no_success()
	def test_cleanup_failure_after_publication_is_not_a_conflict(self):
		from core.fs.zip import _cleanup_extraction
		def cleanup(task, temporary):
			_cleanup_extraction(task, temporary)
			raise OSError('cleanup failed')
		with patch('core.fs.zip._cleanup_extraction', side_effect=cleanup):
			self.command()
		self.show_alert.assert_called_once_with('cleanup failed')
		self.assertEqual(b'payload', (self.root / 'Reports/file.txt').read_bytes())
		self.assert_no_success()
	def test_invalid_settings_or_missing_backend_reports_failure(self):
		self.load_json.return_value = {'archive_handlers': []}
		self.command()
		self.submit_task.assert_not_called()
		self.show_alert.assert_called_with('Invalid archive_handlers in Core Settings.json.')
		self.load_json.return_value = {'archive_handlers': {'.zip': 'missing://'}}
		self.prepare_copy.side_effect = FileNotFoundError('Archive handler unavailable')
		self.command()
		self.show_alert.assert_called_with('Archive handler unavailable')
		self.assert_no_success()
	def test_existing_output_case_variant_blocks(self):
		output = self.root / 'REPORTS'
		output.mkdir()
		self.command()
		self.show_alert.assert_called_once_with('Destination already exists: Reports')
		self.submit_task.assert_not_called()
		self.assert_no_success()
	def test_archive_looking_output_is_local_but_nested_unpack_fails_closed(self):
		from core.commands import ArchiveOpenListener
		from core.fs.zip import SevenZipFileSystem, _run_7zip
		archive = self.root / 'archive.zip.7z'
		_run_7zip(['a', str(archive), self.source.name], cwd=str(self.root))
		original = archive.read_bytes()
		self.load_json.return_value = {'archive_handlers': {'.zip': 'zip://', '.7z': '7z://'}}
		self.prepare_copy.side_effect = SevenZipFileSystem(StubFS(), {'.7z'}).prepare_copy
		self.pane.get_file_under_cursor.return_value = as_url(archive)
		self.command()
		output = self.root / 'archive.zip'
		self.assertEqual(self.original, (output / self.source.name).read_bytes())
		self.assertEqual(original, archive.read_bytes())
		self.assertIsNone(ArchiveOpenListener(self.pane).on_command('open_directory', {'url': as_url(output)}))
		self.show_status_message.reset_mock()
		self.pane.place_cursor_at.reset_mock()
		self.pane.get_path.return_value = as_url(output)
		self.pane.get_file_under_cursor.return_value = as_url(output / self.source.name)
		self.prepare_copy.side_effect = self.backend.prepare_copy
		self.command()
		self.show_alert.assert_called_once()
		self.assertFalse((output / 'Reports').exists())
		self.assertEqual(self.original, (output / self.source.name).read_bytes())
		self.assert_no_success()
	def test_unsupported_prepared_task_never_runs(self):
		child = Task('Unsafe handler', fn=Mock())
		self.prepare_copy.side_effect = None
		self.prepare_copy.return_value = [child]
		self.command()
		self.show_alert.assert_called_once_with('This archive handler does not support safe Unpack.')
		self.assert_no_success()
	def test_parent_archive_substring_rejected_without_publication(self):
		parent = self.root / 'backup.zip.old'
		parent.mkdir()
		selected = parent / 'Reports.zip'
		selected.write_bytes(self.original)
		other = self.root / 'backup.zip'
		with ZipFile(other, 'w') as archive:
			archive.writestr('.old/Reports.zip', b'wrong source')
		other_bytes = other.read_bytes()
		self.pane.get_path.return_value = as_url(parent)
		self.pane.get_file_under_cursor.return_value = as_url(selected)
		self.command()
		self.assertIn('selected archive root', self.show_alert.call_args.args[0])
		self.assertFalse((parent / 'Reports').exists())
		self.assertEqual(self.original, selected.read_bytes())
		self.assertEqual(other_bytes, other.read_bytes())
		self.assert_no_success()
	def test_prepared_destination_mismatch_is_rejected(self):
		child = Extract(StubFS(), str(self.source), '', str(self.root / 'wrong'))
		self.prepare_copy.side_effect = None
		self.prepare_copy.return_value = [child]
		self.command()
		self.assertIn('different destination', self.show_alert.call_args.args[0])
		self.assertEqual([self.source], list(self.root.iterdir()))
		self.assert_no_success()
	def test_size_is_set_before_child_runs(self):
		task = _UnpackArchive(as_url(self.source), 'zip://' + splitscheme(as_url(self.source))[1], as_url(self.root / 'Reports'))
		with patch.object(Extract, '__call__', autospec=True, side_effect=lambda child: self.assertEqual(100, task.get_size())):
			task()
		self.assertTrue(task.succeeded)

class UnpackNamingTest(TestCase):
	def test_longest_suffix_and_legacy_wrapper(self):
		handlers = {'.zip': 'zip://', '.zipx': 'zip://', '.gz': 'gz://', '.tar.gz': 'tar://'}
		for name, expected in (('Reports.zip', ('Reports', 'zip://')), ('My FILE.ZIPX', ('My FILE', 'zip://')), ('backup.TAR.GZ', ('backup', 'tar://'))):
			with self.subTest(name=name):
				self.assertEqual(expected, _unpack_archive_name(name, handlers))
				with patch('core.commands.load_json', return_value={'archive_handlers': handlers}):
					self.assertEqual(expected[1], _get_handler_for_archive(name))
		with patch('core.commands.load_json', return_value={'archive_handlers': handlers}):
			self.assertIsNone(_get_handler_for_archive('plain.txt'))
	def test_invalid_names_and_configuration(self):
		for handlers in (None, [], {'.ZIP': 'zip://'}, {'zip': 'zip://'}, {'.': 'zip://'}, {'.zip': ''}, {'.zip': '://'}, {1: 'zip://'}):
			with self.subTest(handlers=handlers), self.assertRaisesRegex(ValueError, 'archive_handlers'):
				_unpack_archive_name('file.zip', handlers)
		for name in ('.zip', '..zip', '...zip', 'plain.txt'):
			with self.subTest(name=name), self.assertRaises(ValueError):
				_unpack_archive_name(name, {'.zip': 'zip://'})
	def test_publication_error_classification(self):
		destination = 'file://C:/data/Reports'
		path = as_human_readable(destination)
		for error_type in (FileExistsError, PermissionError):
			error = error_type(13, 'publish failed', 'temporary', None, path)
			with patch('core.commands.os.path.lexists', return_value=True):
				self.assertEqual('Destination already exists: Reports', _unpack_error_text(error, destination))
			with patch('core.commands.os.path.lexists', return_value=False):
				self.assertEqual(str(error), _unpack_error_text(error, destination))
		for error in (PermissionError('input denied'), OSError('cleanup failed'), FileExistsError('different conflict')):
			with patch('core.commands.os.path.lexists', return_value=True):
				self.assertEqual(str(error), _unpack_error_text(error, destination))