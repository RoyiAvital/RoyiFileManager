from core.directory_size.calculator import DirSize, scan_parents, walk_directory
from itertools import count
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import patch
from unittest.mock import Mock

import os
import subprocess


class DirectorySizeCommandTest(TestCase):
	def test_nested_pane_rows_only_inherit_unknown_parent_errors(self):
		from core.directory_size import DirectorySizeService, _key, format_result
		from fman.url import as_url
		service = DirectorySizeService(Mock(), Mock())
		parent = as_url('C:\\A\\B')
		child = as_url('C:\\A\\B\\C')
		for result in (DirSize(12), DirSize(12, complete=True), DirSize(12, errors=True)):
			service._results[_key(parent)] = result
			self.assertEqual('...', format_result(service.result(child)))
		unknown = DirSize(None, complete=True, errors=True)
		service._results[_key(parent)] = unknown
		self.assertIs(unknown, service.result(child))
		self.assertEqual('?', format_result(service.result(child)))
		own = DirSize(3, complete=True)
		service._results[_key(child)] = own
		self.assertIs(own, service.result(child))

	def test_settings_and_partial_formatting(self):
		from core.directory_size import settings_snapshot, format_result, summary_text
		self.assertEqual({'enabled': False, 'max_files': 10000000}, settings_snapshot({}))
		for invalid in (True, -1, '100', None):
			self.assertEqual({'enabled': False, 'max_files': 10000000},
				settings_snapshot({'enabled': 'yes', 'max_files': invalid}))
		for limit in (0, 2, 10000000):
			self.assertEqual(limit, settings_snapshot({'max_files': limit})['max_files'])
		self.assertEqual(10000000, settings_snapshot({'max_entries': 200000})['max_files'])
		self.assertEqual('...', format_result(None))
		self.assertEqual('2 B...', format_result(DirSize(2)))
		self.assertEqual('2 B+?', format_result(DirSize(2, complete=True, capped=True, errors=True)))
		self.assertEqual('', format_result(DirSize(None, skipped_link=True)))
		text = summary_text(['first', 'second'], [DirSize(2, 1, 3, True, capped=True), DirSize(None, complete=True, errors=True)])
		self.assertIn('at least 2 B (1 files)', text)
		self.assertIn('file limit, errors', text)
		self.assertIn('linked directories skipped', summary_text(['link'], [DirSize(None, skipped_link=True)]))

	def test_column_reads_results_without_scanning_and_sorts_both_directions(self):
		from core import Size
		service = Mock(enabled=True, _active=True)
		service.result.return_value = DirSize(12, complete=True)
		filesystem = Mock()
		filesystem.is_dir.side_effect = lambda url: 'folder' in url
		filesystem.query.return_value = 1024
		column = Size(filesystem)
		with patch('core.directory_size._service', service), patch('core.directory_size.scan_parents', side_effect=AssertionError()):
			self.assertEqual('12 B', column.get_str('file://folder'))
			self.assertEqual('', column.get_str('zip://folder'))
			on_keys = [column.get_sort_value('file://folder', ascending) for ascending in (False, True)]
			for ascending in (False, True):
				values = [column.get_sort_value(url, ascending) for url in ('file://file', 'file://folder')]
				sorted(values, reverse=not ascending)
			from fman.impl.status_bar import format_size
			for enabled in (False, True):
				service.enabled = enabled
				for divisor in (1000, 1024):
					with patch('fman.impl.status_bar._size_divisor', divisor):
						for url in ('file://file', 'zip://file'):
							self.assertEqual(format_size(1024, divisor), column.get_str(url))
			service.result.return_value = None
			self.assertEqual('...', column.get_str('file://folder'))
			self.assertEqual((-1,), column.get_sort_value('file://folder', True)[1])
			service.enabled = False
			self.assertEqual('', column.get_str('file://folder'))
			for index, ascending in enumerate((False, True)):
				sorted([on_keys[index], column.get_sort_value('file://folder', ascending)])

	def test_toggle_saves_only_own_settings_and_notifies_after_success(self):
		from core.directory_size import DirectorySizeService
		service = DirectorySizeService(Mock(), Mock(active=True))
		service._active = True
		service.set_enabled = lambda enabled: setattr(service, 'enabled', enabled)
		with patch('core.directory_size.save_json') as save, patch('core.directory_size.show_status_message') as status:
			service.toggle()
			save.assert_called_once_with('DirectorySize.json', dict(service.settings, enabled=True))
			status.assert_called_once_with('Directory sizes: On', timeout_secs=5)
			service.toggle()
			self.assertEqual('Directory sizes: Off', status.call_args.args[0])
		with patch('core.directory_size.save_json', side_effect=PermissionError('denied')), \
			patch('core.directory_size.show_status_message') as status, patch('core.directory_size.show_alert') as alert:
			service.toggle()
			self.assertFalse(service.enabled)
			status.assert_not_called()
			alert.assert_called_once()


class CalculatorTest(TestCase):
	def setUp(self):
		self.temporary = TemporaryDirectory()
		self.addCleanup(self.temporary.cleanup)
		self.root = Path(self.temporary.name)

	def walk(self, path=None, limit=10000000, check=lambda: None, clock=lambda: 0):
		return list(walk_directory(path or self.root, limit, check, clock))

	def test_nested_empty_and_metadata_only(self):
		(self.root / 'empty').mkdir()
		(self.root / 'nested').mkdir()
		(self.root / 'file').write_bytes(b'abc')
		(self.root / 'nested' / 'file').write_bytes(b'payload')
		with patch('builtins.open', side_effect=AssertionError('content read')):
			self.assertEqual(DirSize(10, 2, 4, True), self.walk()[-1])
		self.assertEqual(DirSize(complete=True), self.walk(self.root / 'empty')[-1])

	def test_running_subtotals_and_cap(self):
		for index in range(5):
			(self.root / str(index)).write_bytes(b'ab')
		clock = count(step=.25).__next__
		results = self.walk(clock=clock)
		self.assertFalse(results[0].complete)
		self.assertLess(results[0].size_bytes, results[-1].size_bytes)
		self.assertEqual(10, results[-1].size_bytes)
		self.assertEqual(DirSize(4, 2, 3, True, True), self.walk(limit=2)[-1])
		self.assertEqual(DirSize(10, 5, 5, True), self.walk(limit=5)[-1])
		self.assertEqual(DirSize(10, 5, 5, True), self.walk(limit=0)[-1])

	def test_file_limit_excludes_directories(self):
		(self.root / 'empty').mkdir()
		(self.root / 'nested').mkdir()
		(self.root / 'nested' / 'file').write_bytes(b'ab')
		self.assertEqual(DirSize(2, 1, 3, True), self.walk(limit=1)[-1])

	def test_scan_progresses_beyond_former_entry_limit(self):
		from contextlib import nullcontext
		from itertools import repeat
		from types import SimpleNamespace
		entry_count = 200256
		info = SimpleNamespace(st_size=2)
		entry = SimpleNamespace(is_symlink=lambda: False, is_junction=lambda: False,
			is_dir=lambda **kwargs: False, is_file=lambda **kwargs: True,
			stat=lambda **kwargs: info)
		with patch('core.directory_size.calculator.os.scandir',
			return_value=nullcontext(repeat(entry, entry_count))):
			results = self.walk(clock=count(step=.001).__next__)
		self.assertTrue(any(not result.complete and result.entries > 200000 for result in results))
		self.assertEqual(DirSize(entry_count * 2, entry_count, entry_count, True), results[-1])

	def test_missing_and_unreadable_root(self):
		self.assertEqual(DirSize(None, complete=True, errors=True), self.walk(self.root / 'missing')[-1])
		with patch('core.directory_size.calculator.os.scandir', side_effect=PermissionError()):
			self.assertEqual(DirSize(None, complete=True, errors=True), self.walk()[-1])

	def test_subdirectory_error_retains_subtotal(self):
		(self.root / 'blocked').mkdir()
		(self.root / 'file').write_bytes(b'abc')
		real_scandir = os.scandir
		def scandir(path):
			if Path(path).name == 'blocked':
				raise PermissionError()
			return real_scandir(path)
		with patch('core.directory_size.calculator.os.scandir', side_effect=scandir):
			self.assertEqual(DirSize(3, 1, 2, True, errors=True), self.walk()[-1])

	def test_cancel_closes_iterator_without_final_result(self):
		(self.root / 'file').write_bytes(b'ab')
		results = []
		def check():
			if results:
				raise InterruptedError()
		with self.assertRaises(InterruptedError):
			for result in walk_directory(self.root, 100, check, count(step=.25).__next__):
				results.append(result)
		self.assertFalse(any(result.complete for result in results))
		(self.root / 'file').unlink()

	def test_root_and_descendant_junction(self):
		target = self.root / 'target'
		target.mkdir()
		(target / 'file').write_bytes(b'abc')
		container = self.root / 'container'
		container.mkdir()
		junction = container / 'link'
		subprocess.run(['cmd', '/c', 'mklink', '/J', str(junction), str(target)], capture_output=True, check=True)
		self.assertEqual(DirSize(None, complete=True, skipped_link=True), self.walk(junction)[-1])
		self.assertEqual(DirSize(0, 0, 1, True), self.walk(container)[-1])

	def test_cancellation_inside_enumeration_is_not_a_filesystem_error(self):
		(self.root / 'file').write_bytes(b'ab')
		check = Mock(side_effect=[None, None, InterruptedError()])
		with self.assertRaises(InterruptedError):
			self.walk(check=check)
		(self.root / 'file').unlink()
		(self.root / 'folder').mkdir()
		publish = Mock()
		with patch('core.directory_size.calculator.walk_directory', side_effect=InterruptedError()):
			with self.assertRaises(InterruptedError):
				scan_parents([str(self.root)], 100, lambda: None, publish)
		publish.assert_not_called()

	def test_root_symlink(self):
		link = self.root / 'link'
		try:
			link.symlink_to(self.root, target_is_directory=True)
		except OSError:
			self.skipTest('Windows symlink privilege unavailable')
		self.assertTrue(self.walk(link)[-1].skipped_link)

	def test_batches_throttle_and_flush(self):
		for index in range(20):
			(self.root / str(index)).mkdir()
		batches = []
		scan_parents([str(self.root)], 100, lambda: None, batches.append, clock=lambda: 0)
		self.assertEqual(2, len(batches))
		self.assertEqual(1, len(batches[0]))
		self.assertEqual(19, len(batches[1]))
		self.assertTrue(all(result.complete for batch in batches for result in batch.values()))

	def test_native_incremental_scan_sample(self):
		from time import monotonic
		for directory_index in range(20):
			directory = self.root / str(directory_index)
			directory.mkdir()
			for file_index in range(300):
				(directory / str(file_index)).write_bytes(b'payload')
		for scan_index in range(2):
			started = monotonic()
			arrivals = []
			latest = {}
			def publish(changed):
				arrivals.append(monotonic() - started)
				latest.update(changed)
			scan_parents([str(self.root)], 200000, lambda: None, publish)
			elapsed = monotonic() - started
			self.assertEqual(20, len(latest))
			self.assertEqual(6000, sum(result.files for result in latest.values()))
			self.assertTrue(all(result.complete and result.size_bytes == 2100 for result in latest.values()))
			self.assertGreaterEqual(len(arrivals), 2)
			print('DirectorySize native scan %d: 6000 files; first %.3fs, final %.3fs, %d batches' %
				(scan_index + 1, arrivals[0], elapsed, len(arrivals)))