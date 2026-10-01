from concurrent.futures import ThreadPoolExecutor
from threading import get_ident
from unittest import TestCase
from unittest.mock import Mock, call, patch

from core.fs.local.windows.drives import DriveName, DrivesFileSystem


class DrivesTest(TestCase):
	def test_snapshot_labels_errors_and_network_order(self):
		filesystem = DrivesFileSystem()
		with patch.object(filesystem, '_get_drives', return_value=['C:', 'D:', 'E:']), \
			patch.object(filesystem, '_get_volume_name', side_effect=['Windows', '', OSError('unavailable')]) as volume:
			listing = filesystem.scan('', Mock())
		self.assertEqual(('C:', 'D:', 'E:', 'Network...'), listing.names)
		self.assertEqual(('C: Windows', 'D:', 'E:', 'Network...'), listing.display_names)
		self.assertEqual((True,) * 4, listing.is_dir)
		self.assertEqual([call('C:\\'), call('D:\\'), call('E:\\')], volume.call_args_list)
		column = DriveName()
		self.assertEqual(listing.display_names, tuple(column.text(listing, index) for index in range(4)))
		for ascending, expected in ((True, (0, 1, 2, 3)), (False, (3, 2, 1, 0))):
			keys = column.keys(listing, ascending)
			self.assertEqual(expected, tuple(sorted(range(4), key=keys.__getitem__, reverse=not ascending)))

	def test_cancellation_precedes_each_lookup(self):
		filesystem = DrivesFileSystem()
		with patch.object(filesystem, '_get_drives', return_value=['C:', 'D:']), \
			patch.object(filesystem, '_get_volume_name', return_value='Disk') as volume:
			with self.assertRaisesRegex(RuntimeError, 'canceled'):
				filesystem.scan('', Mock(side_effect=[None, RuntimeError('canceled')]))
		volume.assert_called_once_with('C:\\')

	def test_lookup_runs_on_scan_worker_and_columns_do_no_io(self):
		filesystem = DrivesFileSystem()
		threads = []
		def label(path):
			threads.append(get_ident())
			return 'Disk'
		with patch.object(filesystem, '_get_drives', return_value=['C:']), \
			patch.object(filesystem, '_get_volume_name', side_effect=label) as volume:
			with ThreadPoolExecutor(max_workers=1) as worker:
				listing = worker.submit(filesystem.scan, '', Mock()).result(timeout=5)
			self.assertEqual(1, len(threads))
			self.assertNotEqual(get_ident(), threads[0])
			column = DriveName()
			self.assertEqual('C: Disk', column.text(listing, 0))
			column.keys(listing, True)
			column.keys(listing, False)
			volume.assert_called_once_with('C:\\')