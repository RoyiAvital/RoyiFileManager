from core.fileoperations import CopyFiles, MoveFiles, ArchiveUpdateError
from core.tests import StubFS, SYMLINKS_SUPPORTED
from fman import YES, NO, OK, YES_TO_ALL, NO_TO_ALL, ABORT, Task
from fman.url import join, dirname, as_url, as_human_readable
from os.path import exists
from tempfile import TemporaryDirectory
from unittest import TestCase, skipIf, skipUnless
from unittest.mock import Mock, patch

import os
import os.path
import stat

class PreparationSafetyTest(TestCase):
	def test_move_to_missing_destination_prepares_without_mutation(self):
		from pathlib import Path
		from core.commands import Move
		from core.fs.local import LocalFileSystem
		from fman.impl.plugins.mother_fs import MotherFileSystem
		with TemporaryDirectory() as directory:
			root = Path(directory)
			source, destination = root / 'source', root / 'new' / 'nested'
			(source / 'folder').mkdir(parents=True)
			(source / 'file.txt').write_bytes(b'file')
			(source / 'folder' / 'child.txt').write_bytes(b'child')
			filesystem = MotherFileSystem(None)
			filesystem.add_child('file://', LocalFileSystem())
			files = [as_url(source / 'file.txt'), as_url(source / 'folder')]
			ui = Mock()
			ui.show_prompt.return_value = (str(destination), True)
			ui.show_alert.return_value = YES
			confirmed = Move._confirm_tree_operation(files, as_url(root), as_url(source), ui=ui, fs=filesystem)
			self.assertEqual((as_url(destination), None), confirmed)
			ui.show_alert.assert_called_once()
			self.assertFalse((root / 'new').exists())
			operation = MoveFiles(files, *confirmed, fs=filesystem)
			self.assertTrue(operation._gather_files())
			self.assertFalse((root / 'new').exists())
			self.assertEqual(b'file', (source / 'file.txt').read_bytes())
			self.assertEqual(b'child', (source / 'folder' / 'child.txt').read_bytes())
			for task in operation._tasks:
				task()
			self.assertEqual(b'file', (destination / 'file.txt').read_bytes())
			self.assertEqual(b'child', (destination / 'folder' / 'child.txt').read_bytes())
			self.assertEqual([], list(source.iterdir()))

	def test_cancel_move_to_missing_destination_creates_nothing(self):
		from pathlib import Path
		from core.fs.local import LocalFileSystem
		from fman.impl.plugins.mother_fs import MotherFileSystem
		with TemporaryDirectory() as directory:
			root = Path(directory)
			source, destination = root / 'file.txt', root / 'new' / 'nested'
			source.write_bytes(b'keep')
			filesystem = MotherFileSystem(None)
			filesystem.add_child('file://', LocalFileSystem())
			operation = MoveFiles([as_url(source)], as_url(destination), fs=filesystem)
			original = operation._gather_files
			def cancel_after_preparation():
				self.assertTrue(original())
				raise Task.Canceled()
			with patch.object(operation, '_gather_files', side_effect=cancel_after_preparation):
				with self.assertRaises(Task.Canceled):
					operation()
			self.assertEqual(b'keep', source.read_bytes())
			self.assertFalse((root / 'new').exists())
			self.assertEqual({}, operation._ancestor_identities)

	def test_file_selection_does_not_enumerate_its_parent(self):
		from pathlib import Path
		from core.fs.local import LocalFileSystem
		from core.fs.local.windows import listing as scanner
		from fman.impl.plugins.mother_fs import MotherFileSystem
		for operation_class in (CopyFiles, MoveFiles):
			for count in (1, 32):
				with self.subTest(operation=operation_class.__name__, count=count), TemporaryDirectory() as directory:
					root = Path(directory)
					source, destination = root / 'source', root / 'destination'
					source.mkdir()
					paths = [source / ('file%d.txt' % index) for index in range(count)]
					for path in paths:
						path.write_bytes(b'keep')
					filesystem = MotherFileSystem(None)
					filesystem.add_child('file://', LocalFileSystem())
					with patch.object(scanner, 'scan', side_effect=AssertionError('No bulk scan for selected files')):
						operation_class([as_url(path) for path in paths], as_url(destination), fs=filesystem)()
					self.assertEqual(count, len(list(destination.iterdir())))
					for path in paths:
						self.assertEqual(b'keep', (destination / path.name).read_bytes())
						self.assertEqual(operation_class is CopyFiles, path.exists())

	def test_direct_child_destinations_keep_absolute_and_relative_paths(self):
		operation = CopyFiles(['file://C:/source/first.txt'], 'file://C:/destination', fs=Mock())
		self.assertEqual('file://C:/destination/second.txt', operation._get_dest_url('file://C:/source/second.txt'))
		operation = CopyFiles(['file://C:/source/first.txt'], 'relative', fs=Mock())
		self.assertEqual('file://C:/source/relative/first.txt', operation._get_dest_url('file://C:/source/first.txt'))

	def test_directory_transfer_does_not_use_bulk_metadata(self):
		from pathlib import Path
		from core.fs.local import LocalFileSystem
		from core.fs.local.windows import listing as scanner
		from fman.impl.plugins.mother_fs import MotherFileSystem
		for operation_class in (CopyFiles, MoveFiles):
			for merge in (False, True):
				with self.subTest(operation=operation_class.__name__, merge=merge), TemporaryDirectory() as directory:
					root = Path(directory)
					source, destination = root / 'source', root / 'destination'
					(source / 'child').mkdir(parents=True)
					(source / 'child' / 'keep.txt').write_bytes(b'keep')
					if merge:
						(destination / source.name / 'child').mkdir(parents=True)
					filesystem = MotherFileSystem(None)
					filesystem.add_child('file://', LocalFileSystem())
					with patch.object(scanner, 'scan', side_effect=AssertionError('No bulk scan during traversal')):
						operation_class([as_url(source)], as_url(destination), fs=filesystem)()
					self.assertEqual(b'keep', (destination / source.name / 'child' / 'keep.txt').read_bytes())
					self.assertEqual(operation_class is CopyFiles, source.exists())

	def test_copy_reads_live_source_after_preparation(self):
		from pathlib import Path
		from core.fs.local import CopyFile
		with TemporaryDirectory() as directory:
			root = Path(directory)
			source, destination = root / 'file.txt', root / 'destination'
			source.write_bytes(b'before')
			operation = CopyFiles([as_url(source)], as_url(destination), fs=StubFS())
			original = CopyFile.__call__
			def copy(task):
				source.write_bytes(b'after preparation')
				return original(task)
			with patch.object(CopyFile, '__call__', copy):
				operation()
			self.assertEqual(b'after preparation', (destination / source.name).read_bytes())

	def test_directory_ancestry_is_resolved_once_per_destination(self):
		from pathlib import Path
		with TemporaryDirectory() as directory:
			root = Path(directory)
			destination = root / 'destination'
			files = []
			for index in range(8):
				path = root / ('folder%d' % index)
				path.mkdir()
				files.append(as_url(path))
			operation = CopyFiles(files, as_url(destination), fs=StubFS())
			original = Path.resolve
			with patch('core.fileoperations.Path.resolve', autospec=True, side_effect=original) as resolve, \
					patch('core.fileoperations.is_parent', side_effect=AssertionError('No repeated ancestor walk')):
				self.assertTrue(operation._gather_files())
				resolve.assert_called_once()
			self.assertFalse(destination.exists())

	def test_directory_ancestry_refuses_junction_aliases(self):
		from pathlib import Path
		from subprocess import run
		for operation_class in (CopyFiles, MoveFiles):
			for alias_source in (False, True):
				with self.subTest(operation=operation_class.__name__, alias_source=alias_source), TemporaryDirectory() as directory:
					root = Path(directory)
					source, link = root / 'source', root / 'link'
					(source / 'child').mkdir(parents=True)
					(source / 'keep').write_bytes(b'keep')
					process = run(['cmd', '/c', 'mklink', '/J', str(link), str(source)], capture_output=True, timeout=10)
					self.assertEqual(0, process.returncode, process.stderr)
					selected, destination = (link, source / 'child') if alias_source else (source, link / 'child')
					operation = operation_class([as_url(selected)], as_url(destination), fs=StubFS())
					with patch.object(operation, 'show_alert', return_value=OK) as alert:
						operation()
						alert.assert_called_once()
					self.assertEqual(b'keep', (source / 'keep').read_bytes())
					self.assertEqual([], list((source / 'child').iterdir()))
					self.assertEqual({}, operation._ancestor_identities)

	def test_unknown_identity_and_nonlocal_paths_keep_fallback(self):
		from pathlib import Path
		from types import SimpleNamespace
		operation = CopyFiles(['file://C:/source/item'], 'file://C:/destination', fs=Mock())
		with patch('core.fileoperations.os.lstat', return_value=SimpleNamespace(st_dev=0, st_ino=0)), \
				patch('core.fileoperations.is_parent', return_value=True) as fallback:
			self.assertTrue(operation._contains_destination('file://C:/source/item', 'file://C:/destination/item', False, False))
			fallback.assert_called_once()
		with patch('core.fileoperations.is_parent', return_value=True) as fallback:
			self.assertTrue(operation._contains_destination('zip://archive/item', 'file://C:/destination/item', False, False))
			fallback.assert_called_once()
		with patch('core.fileoperations.os.stat', return_value=SimpleNamespace(st_dev=1, st_ino=1)), \
				patch('core.fileoperations.Path.stat', return_value=SimpleNamespace(st_dev=0, st_ino=0)), \
				patch('core.fileoperations.Path.resolve', return_value=Path('C:/destination')), \
				patch('core.fileoperations.is_parent', return_value=True) as fallback:
			self.assertTrue(operation._contains_destination('file://C:/source', 'file://C:/destination/source', True, False))
			fallback.assert_called_once()

	def test_regular_files_do_not_walk_ancestors(self):
		from pathlib import Path
		with TemporaryDirectory() as directory:
			root = Path(directory)
			source, destination = root / 'source', root / 'destination'
			source.mkdir()
			files = []
			for index in range(32):
				path = source / ('file%d.txt' % index)
				path.write_bytes(b'payload')
				files.append(as_url(path))
			operation = CopyFiles(files, as_url(destination), fs=StubFS())
			with patch('core.fileoperations.is_parent', side_effect=AssertionError('No file ancestor walk')):
				self.assertTrue(operation._gather_files())
			self.assertFalse(destination.exists())
			self.assertEqual(33, len(operation._tasks))

	def test_self_alias_aborts_before_mutating_prepared_prefix(self):
		from pathlib import Path
		for operation_class in (CopyFiles, MoveFiles):
			with self.subTest(operation=operation_class.__name__), TemporaryDirectory() as directory:
				root = Path(directory)
				source, destination = root / 'source', root / 'destination'
				source.mkdir()
				destination.mkdir()
				(source / 'a.txt').write_bytes(b'first')
				(source / 'b.txt').write_bytes(b'second')
				os.link(source / 'b.txt', destination / 'b.txt')
				last = source / 'b.txt' if operation_class is CopyFiles else destination / 'b.txt'
				operation = operation_class([as_url(source / 'a.txt'), as_url(last)], as_url(destination), fs=StubFS())
				with patch.object(operation, 'show_alert', return_value=ABORT) as alert:
					operation()
					self.assertTrue(alert.called)
				self.assertFalse((destination / 'a.txt').exists())
				self.assertEqual(b'first', (source / 'a.txt').read_bytes())
				self.assertEqual(b'second', (source / 'b.txt').read_bytes())


class ArchiveTransferErrorTest(TestCase):
	def test_real_merged_hardlink_copy_retains_source(self):
		from pathlib import Path
		with TemporaryDirectory() as directory:
			root = Path(directory)
			source, destination = root / 'source' / 'folder', root / 'destination' / 'folder'
			source.mkdir(parents=True)
			destination.mkdir(parents=True)
			(source / 'keep').write_bytes(b'keep')
			os.link(source / 'keep', destination / 'keep')
			operation = CopyFiles([as_url(source)], as_url(destination.parent), fs=StubFS())
			with patch.object(operation, 'show_alert', return_value=YES):
				operation()
			self.assertEqual(b'keep', (source / 'keep').read_bytes())
			self.assertEqual(b'keep', (destination / 'keep').read_bytes())
	def test_real_nested_link_merge_refuses_before_mutation(self):
		from pathlib import Path
		from subprocess import run
		for operation_class in (CopyFiles, MoveFiles):
			for destination_link in (False, True):
				with self.subTest(operation=operation_class.__name__, destination_link=destination_link), TemporaryDirectory() as directory:
					root = Path(directory)
					source, destination, target = root / 'source' / 'folder', root / 'destination' / 'folder', root / 'target'
					for path in (source, destination, target):
						path.mkdir(parents=True)
					(target / 'keep').write_bytes(b'keep')
					linked, regular = (destination, source) if destination_link else (source, destination)
					(regular / 'nested').mkdir()
					(regular / 'nested' / 'original').write_bytes(b'original')
					result = run(['cmd', '/c', 'mklink', '/J', str(linked / 'nested'), str(target)], capture_output=True, timeout=10)
					self.assertEqual(0, result.returncode, result.stderr)
					operation = operation_class([as_url(source)], as_url(destination.parent), fs=StubFS())
					with patch.object(operation, 'show_alert', return_value=YES) as alert:
						operation()
						alert.assert_called_once()
					self.assertEqual(b'keep', (target / 'keep').read_bytes())
					self.assertEqual(b'original', (regular / 'nested' / 'original').read_bytes())
					self.assertTrue(os.path.isjunction(linked / 'nested'))
	def test_local_archive_move_refuses_before_gathering_or_mutation(self):
		filesystem = Mock()
		operation = MoveFiles(['file://C:/source'], 'zip://C:/archive.zip', fs=filesystem)
		with patch.object(operation, 'show_alert') as alert:
			operation()
			alert.assert_called_once()
		self.assertEqual([], filesystem.mock_calls)
	def test_merge_refuses_source_and_destination_links(self):
		for operation_class in (CopyFiles, MoveFiles):
			for linked in ('file://C:/source/folder', 'file://C:/destination/folder'):
				with self.subTest(operation=operation_class.__name__, linked=linked):
					filesystem = Mock()
					operation = operation_class(['file://C:/source/folder'], 'file://C:/destination', fs=filesystem)
					with patch('core.fileoperations.os.path.islink',
						side_effect=lambda path: path == as_human_readable(linked)):
						with self.assertRaises(OSError):
							operation._merge_directory('file://C:/source/folder')
					filesystem.iterdir.assert_not_called()
	def test_no_to_all_merge_checks_cancellation(self):
		filesystem = Mock()
		filesystem.iterdir.return_value = ['one', 'two']
		filesystem.is_dir.return_value = False
		filesystem.exists.return_value = True
		operation = CopyFiles(['stub://source/folder'], 'stub://destination', fs=filesystem)
		operation._override_all = False
		with patch.object(operation, 'check_canceled', side_effect=[None, Task.Canceled()]):
			with self.assertRaises(Task.Canceled):
				operation._merge_directory('stub://source/folder')
	def test_update_failure_stops_even_after_ignore_all(self):
		operation = MoveFiles(['zip://source.zip/item'], 'file:///destination')
		operation._ignore_exceptions = True
		later = Mock()
		operation._tasks = [Task('Update', fn=Mock(side_effect=ArchiveUpdateError(5, 'retained'))),
			Task('Later', fn=later)]
		with patch.object(operation, '_gather_files', return_value=True), \
			patch.object(operation, 'show_alert', return_value=OK) as alert:
			operation()
			alert.assert_called_once()
		later.assert_not_called()
	def test_continue_skips_failed_composite_not_just_extraction(self):
		operation = MoveFiles(['zip://source.zip/item'], 'file:///destination')
		deleted = Mock()
		later = Mock()
		class Composite(Task):
			def __call__(self):
				self.run(Task('Extract', fn=Mock(side_effect=OSError(5, 'failed'))))
				deleted()
		operation._tasks = [Composite('Move', size=200), Task('Later', fn=later)]
		with patch.object(operation, '_gather_files', return_value=True), \
			patch.object(operation, 'show_alert', return_value=YES) as alert:
			operation()
			alert.assert_called_once()
		deleted.assert_not_called()
		later.assert_called_once()

class FileTreeOperationAT:

	_NO_SUCH_FILE_MSG = 'the system cannot find the file specified'

	def __init__(self, operation, operation_descr_verb, methodName='runTest'):
		super().__init__(methodName=methodName)
		self.operation = operation
		self.operation_descr_verb = operation_descr_verb
	def test_single_file(self):
		self._single_file()
	def _single_file(self, dest_dir=None):
		if dest_dir is None:
			dest_dir = self.dest
		src_file = join(self.src, 'test.txt')
		self._touch(src_file, '1234')
		self._perform_on(src_file, dest_dir=dest_dir)
		self._expect_files({'test.txt'}, dest_dir)
		self._assert_file_contents_equal(join(dest_dir, 'test.txt'), '1234')
		return src_file
	def test_singe_file_dest_dir_does_not_exist(self):
		self._single_file(dest_dir=join(self.dest, 'subdir'))
	def test_empty_directory(self):
		self._empty_directory()
	def _empty_directory(self):
		empty_dir = join(self.src, 'test')
		self._mkdir(empty_dir)
		self._perform_on(empty_dir)
		self._expect_files({'test'})
		self._expect_files(set(), in_dir=join(self.dest, 'test'))
		return empty_dir
	def test_directory_several_files(self):
		self._directory_several_files()
	def _directory_several_files(self, dest_dir=None):
		if dest_dir is None:
			dest_dir = self.dest
		file_outside_dir = join(self.src, 'file1.txt')
		self._touch(file_outside_dir)
		dir_ = join(self.src, 'dir')
		self._mkdir(dir_)
		file_in_dir = join(dir_, 'file.txt')
		self._touch(file_in_dir)
		executable_in_dir = join(dir_, 'executable')
		self._touch(executable_in_dir, 'abc')
		self._perform_on(file_outside_dir, dir_, dest_dir=dest_dir)
		self._expect_files({'file1.txt', 'dir'}, dest_dir)
		self._expect_files({'executable', 'file.txt'}, join(dest_dir, 'dir'))
		executable_dst = join(dest_dir, 'dir', 'executable')
		self._assert_file_contents_equal(executable_dst, 'abc')
		return [file_outside_dir, dir_]
	def test_directory_several_files_dest_dir_does_not_exist(self):
		self._directory_several_files(dest_dir=join(self.dest, 'subdir'))
	def test_overwrite_files(self):
		self._overwrite_files()
	def _overwrite_files(
		self, answers=(YES, YES), expect_overrides=(True, True),
		files=('a.txt', 'b.txt'), perform_on_files=None
	):
		if perform_on_files is None:
			perform_on_files = files
		src_files = [join(self.src, *relpath.split('/')) for relpath in files]
		dest_files = [join(self.dest, *relpath.split('/')) for relpath in files]
		file_contents = lambda src_file_path: os.path.basename(src_file_path)
		for i, src_file_path in enumerate(src_files):
			self._makedirs(dirname(src_file_path), exist_ok=True)
			self._touch(src_file_path, file_contents(src_file_path))
			dest_file_path = dest_files[i]
			self._makedirs(dirname(dest_file_path), exist_ok=True)
			self._touch(dest_file_path)
		for i, answer in enumerate(answers):
			file_name = os.path.basename(files[i])
			self._expect_alert(
				('%s exists. Do you want to overwrite it?' % file_name,
				 YES | NO | YES_TO_ALL | NO_TO_ALL | ABORT, YES),
				answer=answer
			)
		self._perform_on(*[join(self.src, fname) for fname in perform_on_files])
		for i, expect_override in enumerate(expect_overrides):
			dest_file = dest_files[i]
			with self._open(dest_file, 'r') as f:
				contents = f.read()
			if expect_override:
				self.assertEqual(file_contents(src_files[i]), contents)
			else:
				self.assertEqual(
					'', contents,
					'File %s was overwritten, contrary to expectations.' %
					os.path.basename(dest_file)
				)
		return src_files
	def test_overwrite_files_no_yes(self):
		self._overwrite_files((NO, YES), (False, True))
	def test_overwrite_files_yes_all(self):
		self._overwrite_files((YES_TO_ALL,), (True, True))
	def test_overwrite_files_no_all(self):
		self._overwrite_files((NO_TO_ALL,), (False, False))
	def test_overwrite_files_yes_no_all(self):
		self._overwrite_files((YES, NO_TO_ALL), (True, False))
	def test_overwrite_files_abort(self):
		self._overwrite_files((ABORT,), (False, False))
	def test_overwrite_files_in_directory(self):
		self._overwrite_files(
			files=('dir/a.txt', 'b.txt'), perform_on_files=('dir', 'b.txt')
		)
	def test_overwrite_directory_abort(self):
		self._overwrite_files(
			(ABORT,), (False, False,), files=('dir/a/a.txt', 'dir/b/b.txt'),
			perform_on_files=('dir',)
		)
	def test_move_to_self(self):
		a, b = join(self.dest, 'a'), join(self.dest, 'b')
		c = join(self.external_dir, 'c')
		dir_ = join(self.dest, 'dir')
		self._makedirs(dir_)
		files = [a, b, c]
		for file_ in files:
			self._touch(file_)
		# Expect alert only once:
		self._expect_alert(
			('You cannot %s a file to itself.' % self.operation_descr_verb,),
			answer=OK
		)
		self._perform_on(dir_, *files)
	def test_move_dir_to_self(self):
		dir_ = join(self.src, 'dir')
		self._makedirs(dir_)
		self._expect_alert(
			('You cannot %s a file to itself.' % self.operation_descr_verb,),
			answer=OK
		)
		self._perform_on(dir_, dest_dir=self.src)
	def test_move_to_own_subdir(self):
		dir_ = join(self.src, 'dir')
		subdir = join(dir_, 'subdir')
		self._makedirs(subdir)
		self._expect_alert(
			('You cannot %s a file to itself.' % self.operation_descr_verb,),
			answer=OK
		)
		self._perform_on(dir_, dest_dir=subdir)
	def test_external_file(self):
		self._external_file()
	def _external_file(self):
		external_file = join(self.external_dir, 'test.txt')
		self._touch(external_file)
		self._perform_on(external_file)
		self._expect_files({'test.txt'})
		return external_file
	def test_nested_dir(self):
		self._nested_dir()
	def _nested_dir(self):
		parent_dir = join(self.src, 'parent_dir')
		nested_dir = join(parent_dir, 'nested_dir')
		text_file = join(nested_dir, 'file.txt')
		self._makedirs(nested_dir)
		self._touch(text_file)
		self._perform_on(parent_dir)
		self._expect_files({'parent_dir'})
		self._expect_files({'nested_dir'}, join(self.dest, 'parent_dir'))
		self._expect_files(
			{'file.txt'}, join(self.dest, 'parent_dir', 'nested_dir')
		)
		return parent_dir
	@skipUnless(SYMLINKS_SUPPORTED, 'Symbolic links require Windows privilege')
	def test_symlink(self):
		self._symlink_test()
	def _symlink_test(self):
		symlink_source = join(self.src, 'symlink_source')
		self._touch(symlink_source)
		symlink = join(self.src, 'symlink')
		self._symlink(symlink_source, symlink)
		self._perform_on(symlink)
		self._expect_files({'symlink'})
		symlink_dest = join(self.dest, 'symlink')
		self.assertTrue(self._islink(symlink_dest))
		symlink_dest_source = self._readlink(symlink_dest)
		self.assertTrue(self._fs.samefile(symlink_source, symlink_dest_source))
		return symlink
	def test_dest_name(self):
		self._dest_name()
	def _dest_name(self, src_equals_dest=False, preserves_files=True):
		src_dir = self.dest if src_equals_dest else self.src
		foo = join(src_dir, 'foo')
		self._touch(foo, '1234')
		self._perform_on(foo, dest_name='bar')
		expected_files = {'bar'}
		if preserves_files and src_equals_dest:
			expected_files.add('foo')
		self._expect_files(expected_files)
		self._assert_file_contents_equal(join(self.dest, 'bar'), '1234')
		return foo
	def test_dest_name_same_dir(self):
		self._dest_name(src_equals_dest=True)
	def test_error(self, answer_1=YES, answer_2=YES):
		nonexistent_file_1 = join(self.src, 'foo1.txt')
		nonexistent_file_2 = join(self.src, 'foo2.txt')
		existent_file = join(self.src, 'bar.txt')
		self._touch(existent_file)
		self._expect_alert(
			('Could not %s %s (%s). '
			 'Do you want to continue?' % (
				self.operation_descr_verb,
				as_human_readable(nonexistent_file_1), self._NO_SUCH_FILE_MSG
			 ),
			 YES | YES_TO_ALL | ABORT, YES),
			answer=answer_1
		)
		if not answer_1 & ABORT and not answer_1 & YES_TO_ALL:
			self._expect_alert(
				('Could not %s %s (%s). '
				 'Do you want to continue?' % (
					 self.operation_descr_verb,
					 as_human_readable(nonexistent_file_2),
					 self._NO_SUCH_FILE_MSG
				 ),
				 YES | YES_TO_ALL | ABORT, YES),
				answer=answer_2
			)
		self._perform_on(nonexistent_file_1, nonexistent_file_2, existent_file)
		if not answer_1 & ABORT and not answer_2 & ABORT:
			expected_files = {'bar.txt'}
		else:
			expected_files = set()
		self._expect_files(expected_files)
	def test_error_yes_to_all(self):
		self.test_error(answer_1=YES_TO_ALL)
	def test_error_abort(self):
		self.test_error(answer_1=ABORT)
	def test_error_only_one_file(self):
		nonexistent_file = join(self.src, 'foo.txt')
		file_path = as_human_readable(nonexistent_file)
		message = 'Could not %s %s (%s).' % \
		          (self.operation_descr_verb, file_path, self._NO_SUCH_FILE_MSG)
		self._expect_alert((message, OK, OK), answer=OK)
		self._perform_on(nonexistent_file)
	def test_relative_path_parent_dir(self):
		src_file = join(self.src, 'test.txt')
		self._touch(src_file, '1234')
		self._perform_on(src_file, dest_dir='..')
		dest_dir_abs = dirname(self.src)
		self._expect_files({'src', 'test.txt'}, dest_dir_abs)
		self._assert_file_contents_equal(join(dest_dir_abs, 'test.txt'), '1234')
	def test_relative_path_subdir(self):
		src_file = join(self.src, 'test.txt')
		self._touch(src_file, '1234')
		subdir = join(self.src, 'subdir')
		self._makedirs(subdir, exist_ok=True)
		self._perform_on(src_file, dest_dir='subdir')
		self._expect_files({'test.txt'}, subdir)
		self._assert_file_contents_equal(join(subdir, 'test.txt'), '1234')
	def test_drag_and_drop_file(self):
		src_file = join(self.src, 'test.txt')
		self._touch(src_file, '1234')
		self._perform_on(src_file)
		self._expect_files({'test.txt'})
		self._assert_file_contents_equal(join(self.dest, 'test.txt'), '1234')
	def test_copy_paste_directory(self):
		self._touch(join(self.src, 'dir', 'test.txt'))
		self._makedirs(join(self.dest, 'dir'))
		self._perform_on(join(self.src, 'dir'))
		self._expect_files({'test.txt'}, in_dir=join(self.dest, 'dir'))
	def test_overwrite_directory_file_in_subdir(self):
		self._touch(join(self.src, 'dir1', 'dir2', 'test.txt'))
		self._makedirs(join(self.dest, 'dir1', 'dir2'))
		self._perform_on(join(self.src, 'dir1'))
		self._expect_files({'test.txt'}, in_dir=join(self.dest, 'dir1', 'dir2'))
	def setUp(self):
		super().setUp()
		self._fs = StubFS()
		self._progress_dialog = MockProgressDialog(self)
		self._tmp_dir = TemporaryDirectory()
		self._root = as_url(self._tmp_dir.name)
		# We need intermediate 'src-parent' for test_relative_path_parent_dir:
		self.src = join(self._root, 'src-parent', 'src')
		self._makedirs(self.src)
		self.dest = join(self._root, 'dest')
		self._makedirs(self.dest)
		self.external_dir = join(self._root, 'external-dir')
		self._makedirs(self.external_dir)
		# Create a dummy file to test that not _all_ files are copied from src:
		self._touch(join(self.src, 'dummy'))
	def tearDown(self):
		self._tmp_dir.cleanup()
		super().tearDown()
	def _perform_on(self, *files, dest_dir=None, dest_name=None):
		if dest_dir is None:
			dest_dir = self.dest
		op = self.operation(files, dest_dir, dest_name, self._fs)
		op._dialog = self._progress_dialog
		op()
		self._progress_dialog.verify_expected_dialogs_were_shown()
	def _assert_file_contents_equal(self, url, expected_contents):
		with self._open(url, 'r') as f:
			self.assertEqual(expected_contents, f.read())
	def _touch(self, file_url, contents=None):
		self._makedirs(dirname(file_url), exist_ok=True)
		self._fs.touch(file_url)
		if contents is not None:
			with self._open(file_url, 'w') as f:
				f.write(contents)
	def _mkdir(self, dir_url):
		self._fs.mkdir(dir_url)
	def _makedirs(self, dir_url, exist_ok=False):
		self._fs.makedirs(dir_url, exist_ok=exist_ok)
	def _open(self, file_url, mode):
		return open(as_human_readable(file_url), mode)
	def _stat(self, file_url):
		return os.stat(as_human_readable(file_url))
	def _chmod(self, file_url, mode):
		return os.chmod(as_human_readable(file_url), mode)
	def _symlink(self, src_url, dst_url):
		os.symlink(as_human_readable(src_url), as_human_readable(dst_url))
	def _islink(self, file_url):
		return os.path.islink(as_human_readable(file_url))
	def _readlink(self, link_url):
		return as_url(os.readlink(as_human_readable(link_url)))
	def _expect_alert(self, args, answer):
		self._progress_dialog.expect_alert(args, answer)
	def _expect_files(self, files, in_dir=None):
		if in_dir is None:
			in_dir = self.dest
		self.assertEqual(files, set(self._fs.iterdir(in_dir)))

try:
	from os import geteuid
except ImportError:
	_is_root = False
else:
	_is_root = geteuid() == 0

class CopyFilesTest(FileTreeOperationAT, TestCase):
	def __init__(self, methodName='runTest'):
		super().__init__(CopyFiles, 'copy', methodName)
	@skipIf(_is_root, 'Skip this test when run by root')
	def test_overwrite_locked_file(self):
		# Would also like to have this as a test case in MoveFilesTest but the
		# call to chmod(0o444) which we use to lock the file doesn't prevent the
		# file from being overwritten by a move. Another solution would be to
		# chown the file as a different user, but then the test would require
		# root privileges. So keep it here only for now.
		dir_ = join(self.src, 'dir')
		self._fs.makedirs(dir_)
		src_file = join(dir_, 'foo.txt')
		self._touch(src_file, 'dstn')
		dest_dir = join(self.dest, 'dir')
		self._fs.makedirs(dest_dir)
		locked_dest_file = join(dest_dir, 'foo.txt')
		self._touch(locked_dest_file)
		self._chmod(locked_dest_file, 0o444)
		try:
			self._expect_alert(
				('foo.txt exists. Do you want to overwrite it?',
				 YES | NO | YES_TO_ALL | NO_TO_ALL | ABORT, YES), answer=YES
			)
			self._expect_alert(
				('Error copying foo.txt (permission denied).', OK, OK),
				answer=OK
			)
			self._perform_on(dir_)
		finally:
			# Make the file writeable again because on Windows, the temp dir
			# containing it can't be cleaned up otherwise.
			self._chmod(locked_dest_file, 0o777)

class MoveFilesTest(FileTreeOperationAT, TestCase):
	def __init__(self, methodName='runTest'):
		super().__init__(MoveFiles, 'move', methodName)
	def _single_file(self, dest_dir=None):
		src_file = super()._single_file(dest_dir)
		self.assertFalse(exists(src_file))
		return src_file
	def _empty_directory(self):
		empty_dir_src = super()._empty_directory()
		self.assertFalse(exists(empty_dir_src))
		return empty_dir_src
	def _directory_several_files(self, dest_dir=None):
		src_files = super()._directory_several_files(dest_dir=dest_dir)
		for file_ in src_files:
			self.assertFalse(exists(file_))
		return src_files
	def _overwrite_files(
		self, answers=(YES, YES), expect_overrides=(True, True),
		files=('a.txt', 'b.txt'), perform_on_files=None
	):
		src_files = super()._overwrite_files(
			answers, expect_overrides, files, perform_on_files
		)
		for i, file_ in enumerate(src_files):
			if expect_overrides[i]:
				self.assertFalse(exists(file_), file_)
		return src_files
	def test_rename_directory_case(self):
		container = join(self.dest, 'container')
		directory = join(container, 'a')
		self._makedirs(directory)
		self._perform_on(directory, dest_dir=container, dest_name='A')
		self._expect_files({'A'}, in_dir=container)
	def _external_file(self):
		external_file = super()._external_file()
		self.assertFalse(exists(external_file))
		return external_file
	def _nested_dir(self):
		parent_dir = super()._nested_dir()
		self.assertFalse(exists(parent_dir))
		return parent_dir
	def _symlink_test(self):
		symlink = super()._symlink_test()
		self.assertFalse(exists(symlink))
		return symlink
	def _dest_name(self, src_equals_dest=False, preserves_files=False):
		return super()._dest_name(src_equals_dest, preserves_files=False)
	def test_overwrite_dir_skip_file(self):
		src_dir = join(self.src, 'dir')
		self._makedirs(src_dir)
		src_file = join(src_dir, 'test.txt')
		self._touch(src_file, 'src contents')
		dest_dir = join(self.dest, 'dir')
		self._makedirs(dest_dir)
		dest_file = join(dest_dir, 'test.txt')
		self._touch(dest_file, 'dest contents')
		self._expect_alert(
			('test.txt exists. Do you want to overwrite it?',
			 YES | NO | YES_TO_ALL | NO_TO_ALL | ABORT, YES),
			answer=NO
		)
		self._perform_on(src_dir)
		self.assertTrue(
			self._fs.exists(src_file),
			"Source file was skipped and should not have been deleted."
		)
		self._assert_file_contents_equal(src_file, 'src contents')
		self._assert_file_contents_equal(dest_file, 'dest contents')
	def test_drag_and_drop_file(self):
		super().test_drag_and_drop_file()
		self.assertNotIn('test.txt', self._fs.iterdir(self.src))
	def test_overwrite_directory_file_in_subdir(self):
		super().test_overwrite_directory_file_in_subdir()
		self.assertNotIn('dir1', self._fs.iterdir(self.src))

class MockProgressDialog:
	def __init__(self, test_case):
		self._test_case = test_case
		self._progress = 0
		self._expected_alerts = []
	def expect_alert(self, args, answer):
		self._expected_alerts.append((args, answer))
	def verify_expected_dialogs_were_shown(self):
		self._test_case.assertEqual(
			[], self._expected_alerts, 'Did not receive all expected alerts.'
		)
	def show_alert(self, *args, **_):
		if not self._expected_alerts:
			self._test_case.fail('Unexpected alert: %r' % args[0])
			return
		expected_args, answer = self._expected_alerts.pop(0)
		self._test_case.assertEqual(expected_args, args, "Wrong alert")
		return answer
	def set_text(self, text):
		pass
	def was_canceled(self):
		return False
	def set_task_size(self, size):
		pass
	def get_progress(self):
		return self._progress
	def set_progress(self, progress):
		self._progress = progress