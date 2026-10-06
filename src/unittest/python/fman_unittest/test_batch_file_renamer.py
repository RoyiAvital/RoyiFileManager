from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import Mock, patch

from fman.url import as_url
from fman_unittest.batch_file_renamer_fixture import engine_module


class BatchFileRenamerTest(TestCase):
	def setUp(self):
		context = engine_module()
		self.engine = context.__enter__()
		self.addCleanup(context.__exit__, None, None, None)
		temporary = TemporaryDirectory()
		self.addCleanup(temporary.cleanup)
		self.root = Path(temporary.name).resolve()
		for name in ('IMG_2.txt', 'IMG_10.txt', 'IMG_1.txt', 'occupied.txt'):
			(self.root / name).write_bytes(name.encode())
		self.captured = self.engine.capture((as_url(self.root / 'IMG_10.txt'), as_url(self.root / 'IMG_2.txt')))

	def test_link_classification_allows_cloud_placeholders_and_sparse_files(self):
		import stat
		from types import SimpleNamespace
		for tag in (0, 0x9000001a, 0x9000101a, 0x80000015):
			for mode in (stat.S_IFREG, stat.S_IFDIR):
				with self.subTest(tag=tag, mode=mode):
					metadata = SimpleNamespace(st_mode=mode, st_nlink=1, st_reparse_tag=tag,
						st_file_attributes=stat.FILE_ATTRIBUTE_REPARSE_POINT | stat.FILE_ATTRIBUTE_SPARSE_FILE)
					self.assertFalse(self.engine.is_link(metadata))
		for mode, tag, links in ((stat.S_IFLNK, 0, 1), (stat.S_IFREG, 0xa000000c, 1),
				(stat.S_IFDIR, 0xa0000003, 1), (stat.S_IFREG, 0, 2)):
			with self.subTest(mode=mode, tag=tag, links=links):
				self.assertTrue(self.engine.is_link(SimpleNamespace(st_mode=mode, st_nlink=links, st_reparse_tag=tag)))

	def test_link_selection_is_rejected_before_quick_board(self):
		from fman_unittest.batch_file_renamer_fixture import plugin_module
		from types import SimpleNamespace
		import stat
		(self.root / 'alias.txt').hardlink_to(self.root / 'IMG_2.txt')
		original_stat = self.engine.os.lstat
		selected_path = self.captured.sources[0].path
		with plugin_module() as plugin:
			pane = Mock()
			pane.get_path.return_value = as_url(self.root)
			pane.get_selected_files.return_value = [source.url for source in self.captured.sources]
			for tag in (0, stat.IO_REPARSE_TAG_SYMLINK, stat.IO_REPARSE_TAG_MOUNT_POINT):
				def metadata(path):
					if str(path) == selected_path and tag:
						return SimpleNamespace(st_mode=stat.S_IFDIR, st_nlink=1, st_reparse_tag=tag)
					return original_stat(path)
				with self.subTest(tag=tag), patch('os.lstat', side_effect=metadata), \
						patch('fman.APP_VERSION', '0.14.0'), patch('fman.submit_task', side_effect=lambda task: task()), \
						patch('fman.ui.show_quick_board') as board, patch('fman.show_alert') as alert, \
						patch('fman.fs.rename_no_replace') as rename:
					plugin.BatchFileRenamer(pane)()
					board.assert_not_called()
					rename.assert_not_called()
					alert.assert_called_once()
					self.assertIn('Select actual files, not links or junctions', alert.call_args.args[0])

	def test_capture_and_preflight_allow_cloud_files_and_parent(self):
		from contextlib import contextmanager
		from types import SimpleNamespace
		import stat
		original_stat, original_scan = self.engine.os.lstat, self.engine.os.scandir
		for tag in (0, 0x9000001a, 0x9000101a, 0x80000015):
			def cloud(metadata):
				values = {name: getattr(metadata, name) for name in dir(metadata) if name.startswith('st_')}
				values.update(st_reparse_tag=tag,
					st_file_attributes=metadata.st_file_attributes | stat.FILE_ATTRIBUTE_SPARSE_FILE |
					(stat.FILE_ATTRIBUTE_REPARSE_POINT if tag else 0))
				return SimpleNamespace(**values)
			@contextmanager
			def scan(path):
				with original_scan(path) as entries:
					yield tuple(SimpleNamespace(name=entry.name,
						stat=Mock(return_value=cloud(entry.stat(follow_symlinks=False)))) for entry in entries)
			with self.subTest(tag=tag), patch('os.lstat', side_effect=lambda path: cloud(original_stat(path))), \
					patch('os.scandir', side_effect=scan), patch('builtins.open', side_effect=AssertionError('Content read')):
				captured = self.engine.capture(tuple(source.url for source in self.captured.sources))
				self.assertEqual(self.captured.sources, captured.sources)
				self.engine.preflight(captured, self.engine.plan(captured, 'free{index}{ext}', (0, 1)))

	def test_unselected_hard_link_names_count_toward_folder_index(self):
		original = self.root / 'A.txt'
		original.write_bytes(b'not selected')
		(self.root / 'A2.txt').hardlink_to(original)
		captured = self.engine.capture(tuple(source.url for source in self.captured.sources))
		self.assertEqual((3, 4), tuple(source.file_index for source in captured.sources))

	def test_natural_indices_and_mapping(self):
		self.assertEqual(('IMG_2.txt', 'IMG_10.txt'), tuple(source.name for source in self.captured.sources))
		self.assertEqual((1, 2), tuple(source.file_index for source in self.captured.sources))
		rows = self.engine.preview(self.captured, '{(index + 5):03d}_{file_index}{ext}', (1, 0))
		self.assertEqual('006_1.txt', rows[0].cells[4])
		self.assertEqual('005_2.txt', rows[1].cells[4])
		self.assertEqual('', self.engine.preview(self.captured, '{name}{ext}', (None, 0))[0].cells[4])
		self.assertEqual('', self.engine.preview(self.captured, '{name}{ext}', None)[0].cells[5])

	def test_syntax_and_identity(self):
		rows = self.engine.preview(self.captured, '{name}{ext}', (0, 1))
		self.assertTrue(all(row.cells[5] == '\u2713 Unchanged' for row in rows))
		for template in ('{index + 0}', '{index - 1}', '{name.upper()}', '{index:999999d}',
				'{index:{name}}', '{file_date:%Q}', '{name!r}', '{index + index}', '{((index + 1))}'):
			with self.subTest(template=template), self.assertRaises(ValueError):
				self.engine.parse(template)
		self.assertIn('_', self.engine.plan(self.captured, '{current_date}_{file_date:%Y%m%d}{ext}', (0, None))[0].display)

	def test_filtered_sources_remain_occupied_and_excluded_targets_do_not_collide(self):
		entries = self.engine.plan(self.captured, 'IMG_10.txt', (0, None))
		self.assertEqual('Target exists', entries[0].problem)
		entries = self.engine.plan(self.captured, 'free.txt', (0, None))
		self.assertIsNone(entries[0].problem)
		entries = self.engine.plan(self.captured, 'free.txt', (0, 1))
		self.assertTrue(all(entry.problem == 'Duplicate target' for entry in entries))

	def test_invalid_names_remain_complete_and_status_explains_block(self):
		rows = self.engine.preview(self.captured, 'x' * 4000 + '{name}{ext}', (0, 1))
		for row in rows:
			self.assertTrue(row.cells[4].startswith('x' * 4000))
			self.assertLessEqual(len(row.cells[5].encode('utf-8')), 64)
			self.assertIn('Name too long', row.cells[5])
		with self.assertRaises(ValueError):
			self.engine.preflight(self.captured, self.engine.plan(self.captured, 'x' * 4000, (0, 1)))
		rows, status = self.engine.preview(self.captured, 'occupied.txt', (0, None), with_status=True)
		self.assertEqual('Rename blocked: 1 invalid or conflicting names.', status)
		self.assertIsNone(self.engine.preview(self.captured, '{name}{ext}', None, with_status=True)[1])

	def test_fresh_preflight_refuses_late_target_or_changed_source(self):
		entries = self.engine.plan(self.captured, 'free{index}{ext}', (0, 1))
		(self.root / 'free1.txt').write_bytes(b'late')
		with self.assertRaises(FileExistsError):
			self.engine.preflight(self.captured, entries)
		(self.root / 'free1.txt').unlink()
		(self.root / 'IMG_2.txt').write_bytes(b'changed')
		with self.assertRaises(ValueError):
			self.engine.preflight(self.captured, entries)

	def test_preflight_checks_short_name_aliases(self):
		from win32api import GetShortPathName
		long_path = self.root / 'long_filename_for_alias_collision.txt'
		long_path.write_bytes(b'keep')
		short_name = Path(GetShortPathName(str(long_path))).name
		if short_name.casefold() == long_path.name.casefold():
			self.skipTest('8.3 short names are disabled on this volume')
		captured = self.engine.capture(tuple(source.url for source in self.captured.sources))
		entries = self.engine.plan(captured, short_name, (0, None))
		self.assertIsNone(entries[0].problem)
		with self.assertRaises(FileExistsError):
			self.engine.preflight(captured, entries)
		self.assertEqual(b'keep', long_path.read_bytes())

	def test_cancel_preserves_completed_prefix_and_excluded_rows(self):
		from fman import Task
		from fman.fs import RenameResult
		entries = self.engine.plan(self.captured, 'free{index}{ext}', (0, 1))
		calls = []
		def rename(source, target):
			calls.append((source, target))
			return RenameResult(source, target, True)
		def check():
			if calls:
				raise Task.Canceled()
		report, confirmed = self.engine.execute(self.captured, entries, rename, check)
		self.assertEqual('Renamed', report[0][2])
		self.assertEqual('Unattempted', report[1][2])
		self.assertEqual(1, len(confirmed))
		entries = self.engine.plan(self.captured, 'free{index}{ext}', (None, 0))
		report, confirmed = self.engine.execute(self.captured, entries, rename)
		self.assertEqual('Excluded by filter', report[0][2])

	def test_execution_uses_public_outcomes_and_stops_after_warning(self):
		from fman.fs import RenameResult
		entries = self.engine.plan(self.captured, 'free{index}{ext}', (1, 0))
		self.engine.preflight(self.captured, entries)
		rename = Mock(side_effect=lambda source, target: RenameResult(source, target, True, ('refresh failed',)))
		report, confirmed = self.engine.execute(self.captured, entries, rename)
		rename.assert_called_once()
		self.assertEqual('Unattempted', report[0][2])
		self.assertIn('Renamed; refresh warning', report[1][2])
		self.assertEqual((as_url(self.root / 'free0.txt'),), confirmed)

	def test_unformattable_notification_error_preserves_real_batch_commit(self):
		from core.fs.local import LocalFileSystem
		from fman.fs import rename_no_replace
		from fman.impl.plugins.mother_fs import MotherFileSystem
		import os
		class NotificationError(Exception):
			def __str__(self):
				raise RuntimeError('Notification error formatting failed')
		mother = MotherFileSystem(None)
		mother.add_child('file://', LocalFileSystem())
		removed, added = Mock(), Mock()
		mother.file_removed.add_callback(Mock(side_effect=NotificationError()))
		mother.file_removed.add_callback(removed)
		mother.file_added.add_callback(added)
		entries = self.engine.plan(self.captured, 'free{index}{ext}', (0, 1))
		self.engine.preflight(self.captured, entries)
		target = as_url(self.root / 'free0.txt')
		with patch('fman.fs._get_mother_fs', return_value=mother), \
				patch('core.fs.local.os.rename', wraps=os.rename) as native:
			report, confirmed = self.engine.execute(self.captured, entries, rename_no_replace)
			native.assert_called_once()
		self.assertEqual((target,), confirmed)
		self.assertEqual(('IMG_2.txt', 'free0.txt',
			'Renamed; refresh warning: Notification failed (details unavailable).'), report[0])
		self.assertEqual(('IMG_10.txt', 'IMG_10.txt', 'Unattempted'), report[1])
		removed.assert_called_once_with(entries[0].source.url)
		added.assert_called_once_with(target)
		self.assertFalse((self.root / 'IMG_2.txt').exists())
		self.assertEqual(b'IMG_2.txt', (self.root / 'free0.txt').read_bytes())
		self.assertEqual(b'IMG_10.txt', (self.root / 'IMG_10.txt').read_bytes())
		self.assertFalse((self.root / 'free1.txt').exists())

	def test_execution_preserves_completed_prefix_after_exception(self):
		from fman.fs import RenameResult
		captured = self.engine.capture(tuple(as_url(self.root / name) for name in ('IMG_1.txt', 'IMG_2.txt', 'IMG_10.txt')))
		entries = self.engine.plan(captured, 'free{index}{ext}', (0, 1, 2))
		target = as_url(self.root / 'free0.txt')
		for failure in (TypeError('Invalid provider result'), PermissionError('Access denied')):
			with self.subTest(failure=failure):
				rename = Mock(side_effect=(RenameResult(entries[0].source.url, target, True), failure))
				report, confirmed = self.engine.execute(captured, entries, rename)
				self.assertEqual(2, rename.call_count)
				self.assertEqual((target,), confirmed)
				self.assertEqual(('IMG_1.txt', 'free0.txt', 'Renamed'), report[0])
				self.assertEqual(('IMG_2.txt', 'IMG_2.txt', 'Failed: ' + str(failure)), report[1])
				self.assertEqual(('IMG_10.txt', 'IMG_10.txt', 'Unattempted'), report[2])

	def test_progress_exception_keeps_confirmed_rename(self):
		from fman.fs import RenameResult
		entries = self.engine.plan(self.captured, 'free{index}{ext}', (0, 1))
		target = as_url(self.root / 'free0.txt')
		rename = Mock(return_value=RenameResult(entries[0].source.url, target, True))
		progress = Mock(side_effect=TypeError('Progress reporting failed'))
		report, confirmed = self.engine.execute(self.captured, entries, rename, progress=progress)
		rename.assert_called_once()
		self.assertEqual((target,), confirmed)
		self.assertEqual(('IMG_2.txt', 'free0.txt', 'Renamed; reporting warning: Progress reporting failed'), report[0])
		self.assertEqual('Unattempted', report[1][2])

	def test_preview_performs_no_filesystem_reads(self):
		with patch.object(self.engine.os, 'scandir', side_effect=AssertionError), patch.object(self.engine.os, 'lstat', side_effect=AssertionError):
			self.engine.preview(self.captured, '{name}_{index}{ext}', (0, None))

	def test_complete_preview_limit_refuses_oversized_candidate_set(self):
		from dataclasses import replace
		from fman.impl.ui.table_data import TableSchema
		sources = tuple(replace(self.captured.sources[0], name='%05d' % index + '\u754c' * 250,
			file_index=2**63 - 1 - index) for index in range(10000))
		captured = replace(self.captured, sources=sources, occupied=frozenset(source.name.casefold() for source in sources))
		schema = TableSchema(self.engine.COLUMNS)
		rows = self.engine.preview(captured, '{name}{ext}', tuple(range(10000)))
		self.assertEqual(10000, len(schema.snapshot(rows)))
		with self.assertRaisesRegex(ValueError, '16 MiB'):
			self.engine.preview(captured, 'x' * 512 + '{name}{name}{name}', tuple(range(10000)))

	def test_missing_api_alert_does_not_promise_released_version_support(self):
		from fman_unittest.batch_file_renamer_fixture import plugin_module
		with plugin_module() as plugin:
			pane = Mock()
			with patch('fman.APP_VERSION', '0.14.0'), patch('fman.fs.rename_no_replace', None), \
					patch('fman.show_alert') as alert, patch('fman.submit_task') as submit, \
					patch('fman.ui.show_quick_board') as board:
				plugin.BatchFileRenamer(pane)()
				alert.assert_called_once()
				self.assertIn('released 0.14.0 host does not include', alert.call_args.args[0])
				submit.assert_not_called()
				board.assert_not_called()
				pane.get_path.assert_not_called()

	def test_public_command_stops_on_invalid_acceptance_without_reopening(self):
		from fman_unittest.batch_file_renamer_fixture import plugin_module
		with plugin_module() as plugin:
			pane = Mock()
			pane.get_path.return_value = as_url(self.root)
			pane.get_selected_files.return_value = [source.url for source in self.captured.sources]
			pane.on_closed.return_value = lambda: None
			pane.on_path_changed.return_value = lambda: None
			with patch('fman.APP_VERSION', '0.14.0'), patch('fman.submit_task', side_effect=lambda task: task()), \
					patch('fman.ui.show_quick_board', return_value=('occupied.txt', True, (0, None))) as board, \
					patch('fman.show_alert') as alert, patch('fman.fs.rename_no_replace') as rename:
				plugin.BatchFileRenamer(pane)()
				board.assert_called_once()
				alert.assert_called_once()
				rename.assert_not_called()

	def test_selection_restore_does_not_change_a_navigated_pane(self):
		from fman_unittest.batch_file_renamer_fixture import plugin_module
		with plugin_module() as plugin:
			pane = Mock()
			parent = as_url(self.root)
			urls = (as_url(self.root / 'renamed.txt'),)
			pane.get_path.return_value = parent
			plugin._restore_selection(pane, parent, urls)
			loaded = pane.reload.call_args.kwargs['on_done']
			pane.get_path.return_value = as_url(self.root / 'elsewhere')
			loaded()
			pane.clear_selection.assert_not_called()
			pane.select.assert_not_called()
			pane.place_cursor_at.assert_not_called()
			pane.reload.reset_mock()
			plugin._restore_selection(pane, parent, urls)
			pane.reload.assert_not_called()

	def test_source_uses_only_public_host_imports_and_mutations(self):
		import ast
		from fman_unittest.batch_file_renamer_fixture import PLUGIN_ROOT
		for path in (PLUGIN_ROOT / 'batch_file_renamer').glob('*.py'):
			tree = ast.parse(path.read_text(encoding='utf-8'))
			for node in ast.walk(tree):
				if isinstance(node, ast.Import):
					modules = [alias.name for alias in node.names]
				elif isinstance(node, ast.ImportFrom):
					modules = [node.module or '']
				else:
					modules = []
				self.assertFalse(any(module.startswith(('fman.impl', 'core', 'PyQt')) for module in modules), str(path))
				if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and isinstance(node.func.value, ast.Name):
					self.assertNotIn((node.func.value.id, node.func.attr), (('os', 'rename'), ('os', 'replace'), ('os', 'remove')))