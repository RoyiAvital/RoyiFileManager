from dataclasses import FrozenInstanceError, replace
import os
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import patch

from fman.listing import Listing, reconcile


class ListingTest(TestCase):
	def test_provider_columns_are_detached_and_missing_metadata_is_explicit(self):
		labels, pids = ['Example'], [123]
		listing = Listing.create('process://', ['123'], labels=labels, extra=[('pid', pids)])
		labels[0], pids[0] = 'Changed', 456
		self.assertEqual(('Example',), listing.display_names)
		self.assertEqual((123,), listing.column('pid'))
		self.assertEqual((None,), listing.sizes)
		self.assertEqual((None,), listing.mtimes_ns)
		with self.assertRaises(ValueError):
			Listing.create('process://', ['123'], extra=[('pid', [object()])])
		with self.assertRaises(ValueError):
			Listing.create('process://', ['123'], labels=[])

	def listing(self, names=('first', 'second'), ids=(1, 2), created=None):
		count = len(names)
		return Listing('file://C:/fixture', names, (False,) * count, (1,) * count,
			(10,) * count, (0,) * count, created or (5,) * count,
			b''.join(identity.to_bytes(16, 'little') for identity in ids),
			(123, (100).to_bytes(16, 'little')))

	def test_storage_is_immutable_and_detached(self):
		names = ['first', 'second']
		listing = self.listing(names)
		names[0] = 'changed'
		self.assertEqual(('first', 'second'), listing.names)
		with self.assertRaises(FrozenInstanceError):
			listing.names = ()
		with self.assertRaises(TypeError):
			listing.names[0] = 'changed'

	def test_rejects_malformed_columns(self):
		listing = self.listing()
		for changes in ({'names': ('same', 'same')}, {'sizes': ()},
			{'sizes': (-1, 1)}, {'is_dir': (0, 1)}, {'identities': b''},
			{'scope': (1, b'')}, {'names': ('../escape', 'ok')},
			{'mtimes_ns': ('invalid', 1)}, {'attributes': ([], 1)}):
			with self.subTest(changes=changes), self.assertRaises(ValueError):
				replace(listing, **changes)

	def test_exact_rename_and_hardlink_identity(self):
		self.assertEqual({0: 1, 1: 0}, reconcile(self.listing(),
			self.listing(('second', 'renamed'), (2, 1))))
		self.assertEqual({0: 0}, reconcile(self.listing(ids=(1, 1)),
			self.listing(('first', 'renamed'), (1, 1))))
		self.assertEqual({}, reconcile(self.listing(ids=(1, 1)),
			self.listing(('renamed',), (1,))))

	def test_replacements_reused_ids_and_unknown_ids_do_not_match(self):
		self.assertEqual({}, reconcile(self.listing(), self.listing(ids=(3, 4))))
		self.assertEqual({}, reconcile(self.listing(), self.listing(created=(6, 6))))
		self.assertEqual({}, reconcile(self.listing(ids=(0, 0)), self.listing(ids=(0, 0))))

	def test_unchanged_reconciliation_keeps_only_known_ids_including_hardlinks(self):
		previous = self.listing(('first', 'alias', 'unknown'), (1, 1, 0))
		current = replace(previous, sizes=(3, 4, 5), mtimes_ns=(6, 7, 8))
		with patch.object(Listing, 'identity', side_effect=AssertionError('No per-entry identity tuples')):
			self.assertEqual({0: 0, 1: 1}, reconcile(previous, current))

	def test_unchanged_known_ids_use_sentinel_including_cross_boundary_zeros(self):
		previous = self.listing(('first', 'second', 'alias'), (1, 1 << 120, 1))
		current = replace(previous, sizes=(3, 4, 5), mtimes_ns=(6, 7, 8))
		with patch.object(Listing, 'identity', side_effect=AssertionError('No per-entry identity tuples')):
			self.assertIsNone(reconcile(previous, current))
		empty = Listing.create('file://C:/fixture', ())
		self.assertIsNone(reconcile(empty, replace(empty)))

	def test_aligned_zero_ids_never_use_sentinel(self):
		identities = (1, 1 << 120, 256, 1, 1 << 120)
		names = tuple('entry%d' % index for index in range(len(identities)))
		for unknown in range(len(identities)):
			with self.subTest(unknown=unknown):
				previous = self.listing(names, tuple(0 if index == unknown else identity
					for index, identity in enumerate(identities)))
				self.assertEqual({index: index for index in range(len(names)) if index != unknown},
					reconcile(previous, replace(previous)))

	def test_sentinel_scan_cancels_between_cross_boundary_zero_runs(self):
		from fman.impl.model.listing import Canceled
		from unittest.mock import Mock
		previous = self.listing(tuple('entry%d' % index for index in range(600)), (1, 1 << 120) * 300)
		check = Mock(side_effect=[None, Canceled()])
		with self.assertRaises(Canceled):
			reconcile(previous, replace(previous), check)
		self.assertEqual(2, check.call_count)

	def test_other_directory_or_volume_does_not_inherit_state(self):
		listing = self.listing()
		for changes in ({'location': 'file://C:/other'},
			{'scope': (124, listing.scope[1])}, {'scope': (123, bytes(16))}):
			self.assertEqual({}, reconcile(listing, replace(listing, **changes)))

	def test_reconciliation_can_cancel_exact_and_ambiguous_work(self):
		from fman.impl.model.listing import Canceled
		from unittest.mock import Mock
		previous = self.listing()
		for current, checkpoints in ((previous, 1), (self.listing(('renamed', 'other')), 2)):
			check = Mock(side_effect=[None] * (checkpoints - 1) + [Canceled()])
			with self.assertRaises(Canceled):
				reconcile(previous, current, check)
			self.assertEqual(checkpoints, check.call_count)

	def test_find_uses_provider_labels_but_keeps_entry_keys(self):
		from search_file_fuzzy.indexer import ListingSearch, index_listing
		listing = Listing.create('process://', ['internal~123~99'], labels=['Example.exe'])
		visible, highlights = ListingSearch()(listing, 'Example', lambda: None)
		self.assertEqual((0,), visible)
		self.assertTrue(highlights[0])
		entry = index_listing(listing).entries[0]
		self.assertEqual('process://internal~123~99', entry.url)
		self.assertEqual('Example.exe', entry.name)


class NativeListingTest(TestCase):
	def test_native_cancellation_checks_batches_and_each_followed_link(self):
		from core.fs.local.windows import listing as native
		from unittest.mock import Mock
		def batches(check):
			check()
			yield b'first'
			check()
			yield b'second'
		with patch.object(native, 'NativeDirectory') as factory, \
			patch.object(native, 'records', side_effect=[
				[('file%d' % index, 0, 0, 32, 0, bytes(16), 0) for index in range(100)],
				[('link', 0, 0, 0x410, 0xa0000003, bytes(16), 0)]]), \
			patch.object(native.os, 'stat', side_effect=PermissionError()):
			directory = factory.return_value.__enter__.return_value
			directory.scope.return_value = (1, bytes(16))
			directory.batches.side_effect = batches
			check = Mock()
			listing = native.scan('file://C:/fixture', 'C:\\fixture', check)
			self.assertEqual(101, len(listing.names))
			self.assertEqual(5, check.call_count)

	def test_modified_keys_preserve_datetime_order_and_unknown_values(self):
		from core import Modified
		from datetime import datetime
		values = tuple(value for value in (None, -1, 0, 1, 10**30, 1700000000000000000, None)
			for repeat in range(4))
		listing = Listing.create('file://C:/fixture', ['entry%d' % index for index in range(len(values))], mtimes_ns=values)
		for ascending in (True, False):
			expected = []
			for value in values:
				try:
					modified = datetime.min if value is None else datetime.fromtimestamp(value / 1_000_000_000)
				except (OSError, OverflowError, ValueError):
					modified = datetime.min
				expected.append((ascending, modified))
			with patch('core.datetime', wraps=datetime) as conversion:
				conversion.min = datetime.min
				self.assertEqual(tuple(expected), Modified().keys(listing, ascending))
				self.assertEqual(20, conversion.fromtimestamp.call_count)

	def test_unreadable_link_targets_keep_own_metadata_in_both_scanners(self):
		from core.fs.local import LocalFileSystem
		from core.fs.local.windows import listing as native
		from stat import S_IFDIR, FILE_ATTRIBUTE_DIRECTORY, FILE_ATTRIBUTE_REPARSE_POINT
		from unittest.mock import Mock
		attributes = FILE_ATTRIBUTE_DIRECTORY | FILE_ATTRIBUTE_REPARSE_POINT
		for error in (PermissionError('denied'), OSError('network unavailable'), FileNotFoundError('missing')):
			with self.subTest(error=type(error).__name__):
				with patch.object(native, 'NativeDirectory') as factory, \
					patch.object(native, 'records', return_value=[
						('link', 12, 34, attributes, 0xa0000003, bytes(16), 56),
						('neighbor', 7, 8, 32, 0, bytes(16), 9)]), \
					patch('core.fs.local.os.stat', side_effect=error):
					directory = factory.return_value.__enter__.return_value
					directory.scope.return_value = (1, bytes(16))
					directory.batches.return_value = [b'fixture']
					listing = native.scan('file://C:/fixture', 'C:\\fixture', Mock())
					self.assertEqual(('link', 'neighbor'), listing.names)
					self.assertEqual((True, False), listing.is_dir)
					self.assertEqual((12, 7), listing.sizes)
					self.assertEqual((34, 8), listing.mtimes_ns)
					factory.return_value.__exit__.assert_called_once()
				entry = Mock(path='C:\\fixture\\link')
				entry.name = 'link'
				entry.stat.return_value = Mock(st_mode=S_IFDIR, st_size=12, st_mtime_ns=34,
					st_file_attributes=attributes, st_reparse_tag=0xa0000003)
				with patch('core.fs.local.os.scandir') as scandir, \
					patch('core.fs.local.os.stat', side_effect=error):
					scandir.return_value.__enter__.return_value = [entry]
					listing = LocalFileSystem()._scan_entries('C:/fixture', 'C:\\fixture', Mock())
					self.assertEqual(('link',), listing.names)
					self.assertEqual((True,), listing.is_dir)
					self.assertEqual((12,), listing.sizes)
					self.assertEqual((34,), listing.mtimes_ns)
					self.assertEqual((attributes,), listing.attributes)

	def test_local_provider_uses_same_snapshot_when_native_scan_is_unavailable(self):
		from core.fs.local import LocalFileSystem
		from fman.url import as_url
		from unittest.mock import Mock, patch
		with TemporaryDirectory() as temporary:
			folder = Path(temporary).resolve()
			(folder / 'entry.txt').write_bytes(b'payload')
			(folder / 'directory').mkdir()
			with patch('core.fs.local.windows.listing.scan', return_value=None):
				listing = LocalFileSystem().scan(as_url(folder)[7:], Mock())
			self.assertEqual({'entry.txt', 'directory'}, set(listing.names))
			self.assertEqual(7, listing.sizes[listing.names.index('entry.txt')])
			self.assertTrue(listing.is_dir[listing.names.index('directory')])

	def test_process_and_archive_scans_capture_provider_data(self):
		from core.fs.zip import ZipFileSystem
		from process_pane import Processes, Pid
		from process_pane.processes import ProcessRecord
		from unittest.mock import Mock, patch
		from zipfile import ZipFile
		provider = Mock(snapshot=Mock(return_value=[ProcessRecord(123, 'Example.exe', 99)]))
		with patch('process_pane.get_provider', return_value=provider):
			listing = Processes().scan('', Mock())
		self.assertEqual(('Example.exe',), listing.display_names)
		self.assertEqual('123', Pid().text(listing, 0))
		self.assertEqual((123,), Pid().keys(listing, True))
		self.assertEqual((123).to_bytes(16, 'little'), listing.identity(0)[0])
		with TemporaryDirectory() as temporary:
			archive = Path(temporary) / 'test.zip'
			with ZipFile(archive, 'w') as output:
				output.writestr('implicit/file.txt', b'abc')
				output.writestr('file.txt', b'payload')
			filesystem = ZipFileSystem(suffixes={'.zip'})
			listing = filesystem.scan(archive.as_posix(), Mock())
			self.assertEqual({'implicit', 'file.txt'}, set(listing.names))
			self.assertEqual(7, listing.sizes[listing.names.index('file.txt')])
			self.assertTrue(listing.is_dir[listing.names.index('implicit')])
			inside = filesystem.scan(archive.as_posix() + '/implicit', Mock())
			self.assertEqual(('file.txt',), inside.names)
			self.assertEqual((3,), inside.sizes)

	def test_provider_labels_and_unknown_metadata_render_without_io(self):
		from core import Name, Size, Modified
		from core.fs.local.windows.drives import DrivesFileSystem, DriveName
		from fman.impl.plugins.builtin import NullFileSystem, NullColumn
		from unittest.mock import Mock, patch
		listing = Listing.create('process://', ['entry'], labels=['Example'])
		for column, expected in ((Name(), 'Example'), (Size(), ''), (Modified(), '')):
			self.assertEqual(expected, column.text(listing, 0))
			self.assertEqual(1, len(column.keys(listing, True)))
		with patch.object(DrivesFileSystem, '_get_drives', return_value=['C:']), \
			patch.object(DriveName, '_get_volume_name', return_value='System'):
			listing = DrivesFileSystem().scan('', Mock())
		self.assertEqual(('C: System', 'Network...'), listing.display_names)
		self.assertEqual('C: System', DriveName().text(listing, 0))
		empty = NullFileSystem().scan('', Mock())
		self.assertEqual((), empty.names)
		self.assertEqual((), NullColumn().keys(empty, True))

	def test_native_long_unicode_path_and_entry_attributes(self):
		from core.fs.local.windows.listing import scan
		from fman.url import as_url
		from win32file import SetFileAttributes
		with TemporaryDirectory() as temporary:
			folder = Path(temporary).resolve().joinpath(*(['long-directory-' * 6] * 3))
			folder.mkdir(parents=True)
			for name, attributes in (('hidden.txt', 2), ('system.txt', 4), ('.dot', 32), ('name\u0131\U0001f600.txt', 32)):
				path = folder / name
				path.write_bytes(b'payload')
				SetFileAttributes('\\\\?\\' + str(path), attributes)
			listing = scan(as_url(folder), str(folder), lambda: None)
			self.assertIsNotNone(listing)
			self.assertEqual(set(os.listdir(folder)), set(listing.names))
			for index, name in enumerate(listing.names):
				self.assertEqual(os.stat(folder / name).st_file_attributes, listing.attributes[index])

	def test_native_icon_pixels(self):
		from fman.impl.model.listing_icons import extract_icon
		pixels = extract_icon('example.txt', 32, True)
		self.assertIsNotNone(pixels)
		self.assertEqual(32 * 32 * 4, len(pixels))
		self.assertTrue(any(pixels))

	def test_name_keys_preserve_padding_and_unicode_digit_semantics(self):
		from core import Name
		from types import SimpleNamespace
		names = ('file999999', 'file1000000', 'file02', 'file2', '002a09b',
			'no-digits', 'FILE0000000', 'v\u0662\u0663', 'v\uff12', '9' * 80)
		listing = Listing.create('file://C:/fixture', names,
			is_dir=tuple(index % 2 == 0 for index in range(len(names))), labels=tuple(reversed(names)))
		labels = dict(zip(listing.names, listing.display_names))
		directories = dict(zip(listing.names, listing.is_dir))
		column = Name(SimpleNamespace(is_dir=directories.__getitem__, query=lambda name, method: labels[name]))
		for ascending in (True, False):
			keys = column.keys(listing, ascending)
			self.assertEqual(tuple(column.get_sort_value(name, ascending) for name in listing.names), keys)
			minor = dict(zip(listing.display_names, (key[1] for key in keys)))
			self.assertLess(minor['file999999'], minor['file1000000'])
			self.assertEqual(minor['file02'], minor['file2'])
			self.assertLess(minor['v\uff12'], minor['v\u0662\u0663'])

	def test_core_column_goldens_both_sort_directions(self):
		from core import LocalFileSystem, Name, Size, Modified
		from fman.url import as_url, splitscheme
		provider = LocalFileSystem()
		class Queries:
			def query(self, url, method):
				return getattr(provider, method)(splitscheme(url)[1])
			def is_dir(self, url):
				return self.query(url, 'is_dir')
		with TemporaryDirectory() as temporary:
			folder = Path(temporary).resolve()
			for name in ('file999999', 'file1000000', 'file02', 'file2', 'Zeta', 'alpha'):
				(folder / name).write_bytes(b'payload' * len(name))
			for name in ('directory02', 'Directory1'):
				(folder / name).mkdir()
			location = as_url(folder)
			listing = provider.scan(splitscheme(location)[1], lambda: None)
			for column in (Name(Queries()), Size(Queries()), Modified(Queries())):
				for ascending in (True, False):
					keys = column.keys(listing, ascending)
					for index, name in enumerate(listing.names):
						url = location + '/' + name
						with self.subTest(column=type(column).__name__, ascending=ascending, name=name):
							self.assertEqual(column.get_str(url), column.text(listing, index))
							self.assertEqual(column.get_sort_value(url, ascending), keys[index])

	def test_record_bounds_and_128_bit_identity(self):
		from core.fs.local.windows.listing import _RECORD, records
		name = 'example'.encode('utf-16-le')
		identity = (1 << 90).to_bytes(16, 'little')
		data = _RECORD.pack(0, 0, 0, 0, 0, 0, 4, 4, 32, len(name), 0, 0, identity) + name
		result = list(records(data))
		self.assertEqual('example', result[0][0])
		self.assertEqual(identity, result[0][5])
		for invalid in (data[:10], data[:-1], b'\x01\x00\x00\x00' + data[4:]):
			with self.assertRaises(ValueError):
				list(records(invalid))

	def test_native_ntfs_and_refs_parity(self):
		from core.fs.local.windows.listing import scan
		from fman.url import as_url
		roots = [None] + [drive + ':/' for drive in ('E', 'F') if Path(drive + ':/').is_dir()]
		for root in roots:
			with self.subTest(root=root), TemporaryDirectory(dir=root) as temporary:
				folder = Path(temporary).resolve()
				(folder / 'file10.txt').write_bytes(b'payload')
				(folder / 'folder').mkdir()
				os.link(folder / 'file10.txt', folder / 'hardlink.txt')
				listing = scan(as_url(folder), str(folder), lambda: None)
				self.assertIsNotNone(listing)
				self.assertEqual(set(os.listdir(folder)), set(listing.names))
				for index, name in enumerate(listing.names):
					metadata = os.stat(folder / name, follow_symlinks=False)
					self.assertEqual(metadata.st_ino, int.from_bytes(listing.identity(index)[0], 'little'))
					self.assertEqual(metadata.st_mtime_ns, listing.mtimes_ns[index])
					self.assertEqual(metadata.st_file_attributes, listing.attributes[index])
					if not listing.is_dir[index]:
						self.assertEqual(metadata.st_size, listing.sizes[index])
				before = listing
				(folder / 'file10.txt').rename(folder / 'renamed.txt')
				after = scan(as_url(folder), str(folder), lambda: None)
				mapping = reconcile(before, after)
				self.assertNotIn(before.names.index('file10.txt'), mapping)
				self.assertEqual(after.names.index('hardlink.txt'), mapping[before.names.index('hardlink.txt')])

	def test_cancel_and_failure_close_handle(self):
		from core.fs.local.windows import listing as native
		with patch.object(native, 'NativeDirectory') as factory:
			directory = factory.return_value.__enter__.return_value
			directory.scope.return_value = (1, bytes(16))
			directory.batches.side_effect = RuntimeError('canceled')
			with self.assertRaisesRegex(RuntimeError, 'canceled'):
				native.scan('file://C:/fixture', 'C:\\fixture', lambda: None)
			factory.return_value.__exit__.assert_called_once()


class SnapshotJobsTest(TestCase):
	def test_icon_start_failure_can_retry(self):
		from collections import OrderedDict
		from threading import Lock
		from types import SimpleNamespace
		from unittest.mock import Mock, patch
		from fman.impl.model.listing_icons import ListingIcons
		icons = SimpleNamespace(_folder=None, _file=None, _cache={}, _pending=OrderedDict(),
			_inflight=set(), _lock=Lock(), _closed=False, _running=False, key=Mock(return_value='.txt'), _run=Mock())
		listing = SimpleNamespace(location='file://C:/root', attributes=(0,), is_dir=(False,))
		with patch('fman.impl.model.listing_icons.Thread') as thread:
			thread.return_value.start.side_effect = [RuntimeError('start failed'), None]
			with self.assertRaises(RuntimeError):
				ListingIcons.icon(icons, listing, 0)
			self.assertFalse(icons._running)
			self.assertFalse(icons._pending)
			ListingIcons.icon(icons, listing, 0)
			self.assertEqual(2, thread.return_value.start.call_count)
	def test_status_entries_join_each_visible_url_once(self):
		from types import SimpleNamespace
		from unittest.mock import patch
		from fman.impl.model.listing import ListingModel
		from fman.url import join
		model = SimpleNamespace(_location='file://C:/root', _visible=(0, 1),
			_displayed=SimpleNamespace(names=('one', 'two'), is_dir=(False, True)))
		with patch('fman.impl.model.listing.join', wraps=join) as joined:
			entries = ListingModel.get_status_entries(model, {'file://C:/root/one'})
			self.assertEqual(2, joined.call_count)
		self.assertTrue(entries[0].is_selected)
		self.assertFalse(entries[1].is_selected)
	def test_refresh_expected_errors_use_fallback(self):
		from types import SimpleNamespace
		from unittest.mock import Mock, patch
		from fman.impl.model.listing import ListingModel
		model = SimpleNamespace(_shutdown=False, _scan_revision=1, _dirty=False,
			_navigation_request=None, _location='file://C:/root', location_disappeared=Mock())
		with patch('fman.impl.model.listing.sys.excepthook') as report:
			for error in (PermissionError(), FileNotFoundError(), NotADirectoryError()):
				ListingModel._receive(model, 'scan', 1, None, error)
			report.assert_not_called()
			self.assertEqual(3, model.location_disappeared.emit.call_count)
			ListingModel._receive(model, 'scan', 1, None, ValueError('unexpected'))
			report.assert_called_once()
	def test_start_failure_releases_capacity_and_retires_outside_lock(self):
		from fman.impl.model.listing import LatestJobs
		from unittest.mock import Mock, patch
		from threading import Event
		for capacity in (1, 2):
			for construction in (False, True):
				with self.subTest(capacity=capacity, construction=construction):
					jobs = LatestJobs(capacity)
					error = RuntimeError('start failed')
					def retired():
						self.assertTrue(jobs._lock.acquire(blocking=False))
						jobs._lock.release()
					callback = Mock(side_effect=retired)
					with patch('fman.impl.model.listing.Thread') as thread:
						if construction:
							thread.side_effect = error
						else:
							thread.return_value.start.side_effect = error
						with self.assertRaises(RuntimeError) as raised:
							jobs.submit(Mock(), Mock(), callback)
						self.assertIs(error, raised.exception)
					callback.assert_called_once()
					self.assertEqual(set(), jobs._active)
					finished = Event()
					jobs.submit(lambda check: 1, lambda *args: finished.set())
					self.assertTrue(finished.wait(5))
					jobs.close()
	def test_queued_start_failure_delivers_once_outside_lock(self):
		from fman.impl.model.listing import LatestJobs
		from unittest.mock import Mock, patch
		for construction in (False, True):
			with self.subTest(construction=construction):
				jobs = LatestJobs()
				error = RuntimeError('queued start failed')
				def delivered(*args):
					self.assertTrue(jobs._lock.acquire(blocking=False))
					jobs._lock.release()
				deliver = Mock(side_effect=delivered)
				canceled, work = Mock(), Mock()
				with patch('fman.impl.model.listing.Thread') as thread:
					jobs.submit(Mock(), Mock())
					active_args = thread.call_args.kwargs['args']
					jobs.submit(work, deliver, canceled)
					if construction:
						thread.side_effect = error
					else:
						thread.return_value.start.side_effect = error
					jobs._run(*active_args)
				work.assert_not_called()
				canceled.assert_not_called()
				deliver.assert_called_once_with(None, error)
				self.assertEqual(set(), jobs._active)
				self.assertIsNone(jobs._pending)
				jobs.close()
	def test_batch_hidden_filter_matches_scalar_and_composes_with_plugin_filters(self):
		from core import Name
		from core.commands import _hidden_file_filter
		from fman.impl.model.listing import project
		from unittest.mock import Mock
		listing = Listing.create('file:///', ['Volumes', 'visible', 'hidden'], attributes=[2, 0, 2])
		for platform, expected in (('Windows', (1,)), ('Mac', (1, 0))):
			with patch('core.commands.PLATFORM', platform):
				predicate = _hidden_file_filter.snapshot_filter()
			order = (2, 1, 0)
			self.assertEqual(expected, tuple(predicate.filter_indices(listing, order, Mock())))
			self.assertEqual(expected, tuple(index for index in order if predicate(listing, index)))
			result = project(listing, None, Name(), 0, True,
				(predicate, lambda snapshot, index: snapshot.names[index] != 'visible'), Mock(), order=order)
			self.assertEqual(tuple(index for index in expected if index != 1), result.visible)

	def test_batch_hidden_filter_checks_cancellation_between_chunks(self):
		from core.commands import _hidden_file_filter
		from fman.impl.model.listing import Canceled
		from unittest.mock import Mock
		listing = Listing.create('file://C:/fixture', ['entry%d' % index for index in range(600)])
		check = Mock(side_effect=[None, Canceled()])
		with self.assertRaises(Canceled):
			_hidden_file_filter.snapshot_filter().filter_indices(listing, tuple(range(600)), check)
		self.assertEqual(2, check.call_count)

	def test_projection_cancellation_is_bounded_by_visited_rows(self):
		from core import Name
		from fman.impl.model.listing import Canceled, project
		from unittest.mock import Mock
		listing = Listing.create('file://C:/fixture', ['entry%d' % index for index in range(600)])
		order = tuple(index for index in range(600) if index % 256)
		predicate = Mock(spec=['__call__'], return_value=True)
		check = Mock(side_effect=[None, None, Canceled()])
		with self.assertRaises(Canceled):
			project(listing, None, Name(), 0, True, (predicate,), check, order=order)
		self.assertEqual(256, predicate.call_count)

	def test_unfiltered_projection_reuses_order(self):
		from core import Name
		from fman.impl.model.listing import project
		listing = Listing.create('file://C:/fixture', ['first', 'second'])
		order = (1, 0)
		result = project(listing, None, Name(), 0, True, (), lambda: None, order=order)
		self.assertIs(order, result.visible)
		self.assertEqual({1: 0, 0: 1}, result.rows)

	def test_provider_watch_failure_allows_clean_retry(self):
		from fman.fs import FileSystem
		from unittest.mock import Mock
		provider = FileSystem()
		provider.watch = Mock(side_effect=[PermissionError('watch denied'), None])
		provider.unwatch = Mock()
		callback = Mock()
		with self.assertRaises(PermissionError):
			provider._add_file_changed_callback('folder', callback)
		self.assertEqual({}, provider._file_changed_callbacks)
		provider._add_file_changed_callback('folder', callback)
		self.assertEqual(2, provider.watch.call_count)
		self.assertEqual({'folder': [callback]}, provider._file_changed_callbacks)
		provider._remove_file_changed_callback('folder', callback)
		provider.unwatch.assert_called_once_with('folder')

	def test_failed_watch_registration_removes_partial_subscriptions(self):
		from fman.impl.model.file_watcher import FileWatcher
		from unittest.mock import Mock
		filesystem = Mock()
		filesystem.add_file_changed_callback.side_effect = PermissionError('watch denied')
		watcher = FileWatcher(filesystem, Mock(get_location=Mock(return_value='file://C:/folder')))
		with self.assertRaises(PermissionError):
			watcher.start()
		filesystem.file_added.remove_callback.assert_called_once_with(watcher._on_file_added)
		filesystem.file_removed.remove_callback.assert_called_once_with(watcher._on_file_removed)
		filesystem.remove_file_changed_callback.side_effect = FileNotFoundError()
		watcher.shutdown()
		self.assertEqual(2, filesystem.file_added.remove_callback.call_count)
		self.assertEqual(2, filesystem.file_removed.remove_callback.call_count)

	def test_fuzzy_construction_and_queries_honor_cancellation(self):
		from search_file_fuzzy.matcher import Matcher, SearchEntry
		from fman.impl.model.listing import Canceled
		def canceled():
			raise Canceled()
		entries = [SearchEntry(index, 'candidate', 'candidate') for index in range(1000)]
		with self.assertRaises(Canceled):
			Matcher(entries, check_canceled=canceled)
		for mode in ('fuzzy', 'regular'):
			matcher = Matcher(entries, mode)
			for query in ('candidate', '!absent', ''):
				with self.assertRaises(Canceled):
					matcher.matches(query, check_canceled=canceled)

	def test_fuzzy_projection_reuses_full_candidates_not_top_results(self):
		from core import Name
		from fman.impl.model.listing import project
		from search_file_fuzzy.indexer import ListingSearch
		listing = ListingTest().listing(('alpha', 'beta'), (1, 2))
		engine = ListingSearch(max_results=1)
		for query, expected in (('alpha', (0,)), ('beta', (1,)), ('!alpha', (1,)), ('', (0,))):
			result = project(listing, None, Name(), 0, True,
				(lambda snapshot, index: False,), lambda: None, search=(engine, query))
			self.assertEqual(expected, result.visible)
			self.assertEqual(set(expected), set(result.highlights))

	def test_pending_and_failed_cancellations_are_acknowledged_once(self):
		from fman.impl.model.listing import LatestJobs
		from threading import Event
		started, release, finished = Event(), Event(), Event()
		retired, delivered = [], []
		jobs = LatestJobs()
		def blocked(check):
			started.set()
			if not release.wait(2):
				raise TimeoutError('release')
			raise PermissionError('late native error')
		def active_retired():
			retired.append('active')
			finished.set()
		try:
			jobs.submit(blocked, lambda *args: delivered.append(args), active_retired)
			self.assertTrue(started.wait(2))
			jobs.submit(lambda check: None, None, lambda: retired.append('replaced'))
			jobs.submit(lambda check: None, None, lambda: retired.append('closed'))
			jobs.close()
			jobs.submit(lambda check: None, None, lambda: retired.append('rejected'))
			release.set()
			self.assertTrue(finished.wait(2))
			self.assertEqual(['replaced', 'closed', 'rejected', 'active'], retired)
			self.assertEqual([], delivered)
		finally:
			release.set()
			jobs.close()

	def test_fuzzy_snapshot_index_scope_metadata_and_limits(self):
		from search_file_fuzzy.indexer import index_listing
		listing = replace(ListingTest().listing(('visible', '.dot'), (1, 2)), attributes=(0, 2))
		result = index_listing(listing, include_hidden=False, collect_metadata=True)
		self.assertEqual(['visible'], [entry.name for entry in result.entries])
		self.assertEqual(1, result.entries[0].size_bytes)
		self.assertEqual(10, result.entries[0].modified_ns)
		self.assertFalse(result.truncated)
		self.assertEqual(2, len(index_listing(listing, include_hidden=True).entries))
		limited = index_listing(listing, max_entries=1)
		self.assertTrue(limited.truncated)
		self.assertEqual(1, len(limited.entries))
		self.assertIsNone(limited.entries[0].size_bytes)

	def test_canceled_scan_acknowledges_retirement(self):
		from fman.impl.model.listing import LatestJobs
		from threading import Event
		started, release, retired = Event(), Event(), Event()
		jobs = LatestJobs()
		def work(check):
			started.set()
			if not release.wait(2):
				raise TimeoutError('release')
		try:
			jobs.submit(work, lambda *args: self.fail('Stale result published'), retired.set)
			self.assertTrue(started.wait(2))
			jobs.cancel()
			release.set()
			self.assertTrue(retired.wait(2))
		finally:
			release.set()
			jobs.close()

	def test_latest_pending_is_bounded_and_stale_result_is_discarded(self):
		from fman.impl.model.listing import LatestJobs
		from threading import Event
		started, release, finished = Event(), Event(), Event()
		results = []
		jobs = LatestJobs()
		def blocked(check):
			started.set()
			if not release.wait(2):
				raise TimeoutError('release')
			return 'old'
		def deliver(result, error):
			results.append((result, error))
			finished.set()
		try:
			jobs.submit(blocked, deliver)
			self.assertTrue(started.wait(2))
			for value in range(100):
				jobs.submit(lambda check, value=value: value, deliver)
			release.set()
			self.assertTrue(finished.wait(2))
			self.assertEqual([(99, None)], results)
		finally:
			release.set()
			jobs.close()

	def test_projection_preserves_production_filter_and_directional_order(self):
		from core import Name
		from fman.impl.filter_pattern import compile_filter
		from fman.impl.model.listing import project
		listing = ListingTest().listing(('a', 'ab'), (1, 2))
		for query, expected in (('!a', ()), ('!ab', (0,)), ('[ab]', (0, 1)), ('', (0, 1))):
			matcher = compile_filter(query)
			result = project(listing, None, Name(), 0, True,
				(lambda snapshot, index: matcher.matches(snapshot.names[index]),), lambda: None)
			self.assertEqual(expected, result.visible)

	def test_query_reuses_full_order_without_rebuilding_sort_keys(self):
		from core import Name
		from fman.impl.model.listing import project
		from unittest.mock import Mock
		listing = ListingTest().listing(('a', 'ab'), (1, 2))
		first = project(listing, None, Name(), 0, True,
			(lambda snapshot, index: index == 0,), lambda: None)
		column = Mock(keys=Mock(side_effect=AssertionError('Unnecessary sort')))
		second = project(listing, listing, column, 0, True, (), lambda: None, order=first.order)
		self.assertEqual((0, 1), second.visible)
		self.assertIs(first.order, second.order)