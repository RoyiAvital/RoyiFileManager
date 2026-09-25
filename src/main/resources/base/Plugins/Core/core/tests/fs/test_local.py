from collections import namedtuple
from fman import PLATFORM
from fman.url import join, as_url, splitscheme
from core import LocalFileSystem
from core.tests import SYMLINKS_SUPPORTED
from pathlib import Path
from stat import S_IWRITE
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest import TestCase, skipIf, skipUnless
from unittest.mock import Mock, patch

import os

class ListdirTest(TestCase):
	def setUp(self):
		self.fs = LocalFileSystem()
	def test_enumeration_does_not_stat_or_seed_cache(self):
		for platform, path in (('Windows', 'C:/folder'), ('Windows', '//host/share'), ('Linux', '/tmp')):
			with self.subTest(platform=platform), \
				patch('core.fs.local.PLATFORM', platform), \
				patch.object(self.fs, '_url_to_os_path', return_value=path), \
				patch.object(self.fs, '_isabs', return_value=True), \
				patch('core.fs.local.os.listdir', return_value=['entry']) as listdir, \
				patch('core.fs.local.os.scandir', side_effect=AssertionError), \
				patch('core.fs.local.os.stat', side_effect=AssertionError), \
				patch.object(self.fs.cache, 'put', side_effect=AssertionError):
				self.assertEqual(['entry'], self.fs.iterdir(path))
				listdir.assert_called_once_with(path)
	def test_enumeration_failure_propagates(self):
		error = PermissionError('enumeration failed')
		with patch('core.fs.local.os.listdir', side_effect=error):
			with self.assertRaises(PermissionError) as raised:
				self.fs.iterdir('//host/share')
		self.assertIs(error, raised.exception)

class WatchTest(TestCase):
	def test_windows_keeps_notifications_without_qt_dispatch(self):
		provider = LocalFileSystem()
		added, removed, changed = Mock(), Mock(), Mock()
		provider._file_added.add_callback(added)
		provider._file_removed.add_callback(removed)
		with patch('core.fs.local.PLATFORM', 'Windows'), \
			patch('fman.impl.util.qt.thread.Executor.instance', side_effect=AssertionError('No Qt dispatch')), \
			patch.object(provider, '_get_watcher', side_effect=AssertionError('No OS watcher')):
			provider._add_file_changed_callback('C:/probe', changed)
			provider.notify_file_changed('C:/probe')
			provider.notify_file_added('C:/probe/new')
			provider.notify_file_removed('C:/probe/old')
			provider._remove_file_changed_callback('C:/probe', changed)
			provider.notify_file_changed('C:/probe')
		changed.assert_called_once_with('file://C:/probe')
		added.assert_called_once_with('file://C:/probe/new')
		removed.assert_called_once_with('file://C:/probe/old')
		self.assertEqual({}, provider._file_changed_callbacks)
		self.assertIsNone(provider._watcher)

@skipUnless(PLATFORM == 'Windows', 'Windows enumeration attributes')
class NativeEntryAttributesTest(TestCase):
	def setUp(self):
		self.temporary = TemporaryDirectory()
		self.addCleanup(self.temporary.cleanup)
		self.root = Path(self.temporary.name)
		self.fs = LocalFileSystem()
		self.directory = _urlpath(self.root)
		(self.root / 'file').write_bytes(b'contents')
		(self.root / 'directory').mkdir()
	def test_stat_identity_and_metadata_unchanged_after_scan(self):
		path = _urlpath(self.root / 'file')
		before = self.fs.stat(path)
		names = self.fs.iterdir(self.directory)
		self.assertEqual(os.listdir(self.root), names)
		self.assertIs(before, self.fs.stat(path))
		for name in names:
			actual = self.fs.stat(_urlpath(self.root / name))
			self.assertIs(type(actual), os.stat_result)
			self.assertEqual(tuple(os.stat(self.root / name)), tuple(actual))
			self.assertNotEqual(0, actual.st_ino)
			self.assertNotEqual(0, actual.st_dev)
	def test_hidden_attribute_parity_and_refresh(self):
		from core.commands import _hidden_file_filter
		from PyQt5.QtCore import QFileInfo
		from win32file import SetFileAttributes
		for name, attributes in (('file', 2), ('directory', 2), ('.dot', 4)):
			path = self.root / name
			if not path.exists():
				path.touch()
			SetFileAttributes(str(path), attributes)
		listing = self.fs.scan(self.directory, lambda: None)
		for index, name in enumerate(listing.names):
			self.assertEqual(QFileInfo(str(self.root / name)).isHidden(), bool(listing.attributes[index] & 2))
		SetFileAttributes(str(self.root / 'file'), 128)
		self.assertTrue(listing.attributes[listing.names.index('file')] & 2)
		updated = self.fs.scan(self.directory, lambda: None)
		self.assertFalse(updated.attributes[updated.names.index('file')] & 2)
		self.assertTrue(_hidden_file_filter(as_url(self.root / 'file')))
	def test_hardlink_copy_move_delete_after_scan(self):
		from core.fs.local import MoveByCopying
		source = self.root / 'file'
		alias = self.root / 'alias'
		os.link(source, alias)
		self.fs.iterdir(self.directory)
		self.assertTrue(self.fs.samefile(_urlpath(source), _urlpath(alias)))
		copy = self.root / 'copy'
		self.fs.copy(as_url(source), as_url(copy))
		self.fs.iterdir(self.directory)
		destination = self.root / 'moved'
		tasks = list(self.fs.prepare_move(as_url(copy), as_url(destination)))
		self.assertEqual(1, len(tasks))
		self.assertNotIsInstance(tasks[0], MoveByCopying)
		tasks[0]()
		self.assertEqual(b'contents', destination.read_bytes())
		self.fs.delete(_urlpath(destination))
		self.assertFalse(destination.exists())
		self.assertEqual(b'contents', source.read_bytes())
	def test_cross_device_move_still_uses_copy(self):
		from core.fs.local import MoveByCopying
		self.fs.iterdir(self.directory)
		original = self.fs.stat(self.directory)
		self.fs.cache.put(self.directory, 'stat',
			SimpleNamespace(st_dev=original.st_dev + 1))
		tasks = list(self.fs.prepare_move(as_url(self.root / 'file'),
			as_url(self.root / 'destination')))
		self.assertEqual(1, len(tasks))
		self.assertIsInstance(tasks[0], MoveByCopying)
	def test_drive_root_keeps_qt_semantics(self):
		from core.commands import _hidden_file_filter
		from PyQt5.QtCore import QFileInfo
		for path in ('C:', 'C:/', _urlpath(self.root.anchor)):
			with self.subTest(path=path):
				with patch('core.commands.query', side_effect=lambda url, method:
					getattr(self.fs, method)(splitscheme(url)[1])):
					self.assertEqual(not QFileInfo(path).isHidden(),
						_hidden_file_filter('file://' + path))
	def test_c_drive_listing_matches_qt_read_only(self):
		from core.commands import _hidden_file_filter
		from PyQt5.QtCore import QFileInfo
		for directory in ('C:', 'C:/'):
			with self.subTest(directory=directory):
				names = self.fs.iterdir(directory)
				self.assertEqual(os.listdir('C:/'), names)
				with patch('core.commands.query', side_effect=lambda url, method:
					getattr(self.fs, method)(splitscheme(url)[1])):
					for name in names:
						path = 'C:/' + name
						self.assertEqual(not QFileInfo(path).isHidden(),
							_hidden_file_filter('file://' + path), name)
	def test_junction_to_hidden_directory_keeps_qt_and_target_stat(self):
		from core.commands import _hidden_file_filter
		from PyQt5.QtCore import QFileInfo
		from subprocess import run
		from win32file import SetFileAttributes
		target = self.root / 'directory'
		link = self.root / 'junction'
		SetFileAttributes(str(target), 2)
		result = run(['cmd', '/c', 'mklink', '/J', str(link), str(target)],
			capture_output=True, timeout=10)
		self.assertEqual(0, result.returncode, result.stderr)
		try:
			self.fs.iterdir(self.directory)
			self.assertTrue(self.fs.is_dir(_urlpath(link)))
			self.assertTrue(self.fs.samefile(_urlpath(target), _urlpath(link)))
			with patch('core.commands.query', side_effect=lambda url, method:
				getattr(self.fs, method)(splitscheme(url)[1])):
				self.assertEqual(not QFileInfo(str(link)).isHidden(),
					_hidden_file_filter(as_url(link)))
		finally:
			os.rmdir(link)
	@skipUnless(SYMLINKS_SUPPORTED, 'Symbolic links require Windows privilege')
	def test_visible_hidden_and_broken_symlinks_keep_qt(self):
		from core.commands import _hidden_file_filter
		from PyQt5.QtCore import QFileInfo
		from win32file import SetFileAttributes
		target = self.root / 'file'
		for name, destination in (('visible-link', target),
			('hidden-link', target), ('broken-link', self.root / 'missing')):
			(self.root / name).symlink_to(destination)
		SetFileAttributes(str(target), 2)
		SetFileAttributes(str(self.root / 'hidden-link'), 2)
		self.fs.iterdir(self.directory)
		for name in ('visible-link', 'hidden-link', 'broken-link'):
			path = self.root / name
			with patch('core.commands.query', side_effect=lambda url, method:
				getattr(self.fs, method)(splitscheme(url)[1])):
				self.assertEqual(not QFileInfo(str(path)).isHidden(),
					_hidden_file_filter(as_url(path)))
		self.assertEqual(len(b'contents'), self.fs.size_bytes(_urlpath(self.root / 'visible-link')))
		self.assertIs(type(self.fs.stat(_urlpath(self.root / 'broken-link'))), os.stat_result)

class LocalFileSystemTest(TestCase):
	@skipUnless(PLATFORM == 'Windows', 'Windows read-only replacement')
	def test_readonly_mode_failure_reports_published_data(self):
		with TemporaryDirectory() as directory:
			source, destination = Path(directory, 'source'), Path(directory, 'destination')
			source.write_bytes(b'new')
			destination.write_bytes(b'old')
			source.chmod(0o444)
			chmod = os.chmod
			def denied(path, mode, **kwargs):
				if os.fspath(path) == str(destination):
					raise PermissionError(13, 'Access is denied', str(destination))
				return chmod(path, mode, **kwargs)
			try:
				with patch('core.fs.local.os.chmod', side_effect=denied), patch.object(self._fs, 'notify_file_changed') as changed:
					with self.assertRaisesRegex(PermissionError, 'Copy published'):
						self._fs.copy(as_url(source), as_url(destination))
					changed.assert_called_once_with(_urlpath(destination))
				self.assertEqual(b'new', source.read_bytes())
				self.assertEqual(b'new', destination.read_bytes())
				self.assertEqual({'source', 'destination'}, {path.name for path in Path(directory).iterdir()})
			finally:
				source.chmod(S_IWRITE)
				destination.chmod(S_IWRITE)

	def test_copy_refuses_known_hardlinks_with_unknown_inode(self):
		from io import UnsupportedOperation
		with TemporaryDirectory() as directory:
			source, destination, alias = (Path(directory, name) for name in ('source', 'destination', 'alias'))
			source.write_bytes(b'new')
			destination.write_bytes(b'old')
			os.link(destination, alias)
			lstat = os.lstat
			def unidentified(*args, **kwargs):
				metadata = lstat(*args, **kwargs)
				fields = {name: getattr(metadata, name) for name in dir(metadata) if name.startswith('st_')}
				fields.update(st_ino=0, st_dev=0)
				return SimpleNamespace(**fields)
			with patch('core.fs.local.os.lstat', side_effect=unidentified):
				with self.assertRaises(UnsupportedOperation):
					self._fs.copy(as_url(source), as_url(destination))
			self.assertEqual(b'old', destination.read_bytes())
			self.assertEqual(b'old', alias.read_bytes())
			self.assertEqual(b'new', source.read_bytes())

	@skipUnless(PLATFORM == 'Windows', 'Windows copy metadata calls')
	def test_copy_avoids_extra_staging_metadata_calls(self):
		stat = os.stat
		for exists in (False, True):
			with self.subTest(exists=exists), TemporaryDirectory() as directory:
				source, destination = Path(directory, 'source'), Path(directory, 'destination')
				source.write_bytes(b'new')
				if exists:
					destination.write_bytes(b'old')
				def check_stat(path, **kwargs):
					self.assertFalse(Path(path).name.startswith(('.fc-', '.fb-')))
					return stat(path, **kwargs)
				with patch('core.fs.local.os.stat', side_effect=check_stat), \
					patch('win32api.GetFileAttributes', side_effect=AssertionError('Extra attributes read')), \
					patch('win32api.SetFileAttributes', side_effect=AssertionError('Extra attributes write')):
					self._fs.copy(as_url(source), as_url(destination))
				self.assertEqual(b'new', destination.read_bytes())
				self.assertEqual({'source', 'destination'}, {path.name for path in Path(directory).iterdir()})

	@skipUnless(PLATFORM == 'Windows', 'Windows legacy path limits')
	def test_staging_near_legacy_path_limit(self):
		from core.fs.local import mkstemp, mkdtemp
		with TemporaryDirectory() as directory:
			root = Path(directory).resolve()
			source = root / 'source'
			source.write_bytes(b'new')
			parent = root / ('a' * 80)
			parent /= 'b' * (257 - len(str(parent)) - 1)
			extended_parent = Path('\\\\?\\' + str(parent))
			extended_parent.mkdir(parents=True)
			destination = parent / 'd'
			self.assertEqual(259, len(str(destination)))
			def legacy_create(factory, limit, **kwargs):
				path = os.path.join(kwargs['dir'], kwargs['prefix'] + '12345678')
				if not path.startswith('\\\\?\\') and len(path) >= limit:
					raise OSError(36, 'Legacy path limit exceeded', path)
				return factory(**kwargs)
			for exists in (False, True):
				with self.subTest(exists=exists):
					if exists:
						destination.write_bytes(b'old')
					with patch('core.fs.local.mkstemp', side_effect=lambda **kwargs: legacy_create(mkstemp, 260, **kwargs)), \
						patch('core.fs.local.mkdtemp', side_effect=lambda **kwargs: legacy_create(mkdtemp, 248, **kwargs)):
						self._fs.copy(as_url(source), as_url(destination))
					self.assertEqual(b'new', destination.read_bytes())
					self.assertEqual({'d'}, {path.name for path in extended_parent.iterdir()})
				self.assertEqual(b'new', source.read_bytes())

	@skipUnless(PLATFORM == 'Windows', 'Windows staging path syntax')
	def test_staging_directory_preserves_unc_and_extended_paths(self):
		from core.fs.local import CopyFile
		for destination, expected in (
			('C:\\folder\\file', '\\\\?\\C:\\folder'),
			('\\\\server\\share\\folder\\file', '\\\\?\\UNC\\server\\share\\folder'),
			('\\\\?\\C:\\folder\\file', '\\\\?\\C:\\folder'),
			('\\\\?\\UNC\\server\\share\\folder\\file', '\\\\?\\UNC\\server\\share\\folder'),
		):
			with self.subTest(destination=destination):
				self.assertEqual(expected, CopyFile._staging_directory(destination))

	@skipUnless(PLATFORM == 'Windows', 'Windows overwrite publication')
	def test_copy_ignores_access_time_but_rejects_destination_changes(self):
		from core.fs.local import CopyFile
		for change in ('access', 'size', 'modified', 'identity', 'hardlink'):
			with self.subTest(change=change), TemporaryDirectory() as directory:
				source, destination = Path(directory, 'source'), Path(directory, 'destination')
				source.write_bytes(b'new')
				destination.write_bytes(b'old')
				task = CopyFile(self._fs, as_url(source), as_url(destination), 3)
				copy_bytes = task._copy_bytes
				def changed_destination(input_file, output_file):
					copy_bytes(input_file, output_file)
					before = destination.stat()
					if change == 'access':
						os.utime(destination, ns=(before.st_atime_ns + 1_000_000_000, before.st_mtime_ns))
					elif change == 'modified':
						os.utime(destination, ns=(before.st_atime_ns, before.st_mtime_ns + 1_000))
					elif change == 'identity':
						replacement = Path(directory, 'replacement')
						replacement.write_bytes(b'old')
						os.utime(replacement, ns=(before.st_atime_ns, before.st_mtime_ns))
						os.replace(replacement, destination)
					elif change == 'hardlink':
						os.link(destination, Path(directory, 'alias'))
					else:
						destination.write_bytes(b'changed')
				with patch.object(task, '_copy_bytes', side_effect=changed_destination):
					if change == 'access':
						task()
					else:
						with self.assertRaisesRegex(OSError, 'Destination changed'):
							task()
				self.assertEqual(b'new', source.read_bytes())
				self.assertEqual(b'new' if change == 'access' else b'changed' if change == 'size' else b'old', destination.read_bytes())
				self.assertFalse(list(Path(directory).glob('.f[cb]-*')))

	def test_symlink_overwrite_reports_explicit_refusal(self):
		from io import UnsupportedOperation
		with TemporaryDirectory() as directory:
			source, destination = Path(directory, 'source'), Path(directory, 'destination')
			source.write_bytes(b'source')
			destination.write_bytes(b'keep')
			with patch('core.fs.local.islink', return_value=True), \
				patch('core.fs.local.os.readlink', return_value='target'), \
				patch('core.fs.local.os.symlink', side_effect=FileExistsError('exists')) as create:
				with self.assertRaisesRegex(UnsupportedOperation, 'Symlink overwrite refused'):
					self._fs.copy(as_url(source), as_url(destination))
				create.assert_not_called()
			self.assertEqual(b'keep', destination.read_bytes())

	@skipUnless(PLATFORM == 'Windows', 'Windows overwrite publication')
	def test_copy_with_unknown_identity_uses_resolved_paths(self):
		from shutil import SameFileError
		for same_path in (False, True):
			for source_unknown in (False, True):
				for link_count in (0, 1):
					with self.subTest(same_path=same_path, source_unknown=source_unknown, link_count=link_count), TemporaryDirectory() as directory:
						source = Path(directory, 'source')
						destination = source if same_path else Path(directory, 'destination')
						source.write_bytes(b'new')
						if not same_path:
							destination.write_bytes(b'old')
						lstat, fstat = os.lstat, os.fstat
						def unknown(metadata):
							fields = {name: getattr(metadata, name) for name in dir(metadata) if name.startswith('st_')}
							fields.update(st_ino=0, st_dev=0, st_nlink=link_count)
							return SimpleNamespace(**fields)
						with patch('core.fs.local.os.lstat', side_effect=lambda *args, **kwargs: unknown(lstat(*args, **kwargs))), \
							patch('core.fs.local.os.fstat', side_effect=lambda descriptor: unknown(fstat(descriptor)) if source_unknown else fstat(descriptor)):
							if same_path:
								with self.assertRaises(SameFileError):
									self._fs.copy(as_url(source), as_url(destination))
							else:
								self._fs.copy(as_url(source), as_url(destination))
						self.assertEqual(b'new', source.read_bytes())
						self.assertEqual(b'new', destination.read_bytes())

	@skipUnless(PLATFORM == 'Windows', 'Windows read-only replacement')
	def test_readonly_source_copy_preserves_mode_and_contents(self):
		for exists in (False, True):
			with self.subTest(exists=exists), TemporaryDirectory() as directory:
				source, destination = Path(directory, 'source'), Path(directory, 'destination')
				source.write_bytes(b'new')
				os.utime(source, ns=(1_700_000_000_000_000_000, 1_700_000_000_000_000_000))
				if exists:
					destination.write_bytes(b'old')
				source.chmod(0o444)
				try:
					self._fs.copy(as_url(source), as_url(destination))
					self.assertEqual(b'new', source.read_bytes())
					self.assertEqual(b'new', destination.read_bytes())
					self.assertFalse(source.stat().st_mode & S_IWRITE)
					self.assertFalse(destination.stat().st_mode & S_IWRITE)
					self.assertEqual(source.stat().st_mtime_ns, destination.stat().st_mtime_ns)
					self.assertEqual({'source', 'destination'}, {path.name for path in Path(directory).iterdir()})
				finally:
					source.chmod(S_IWRITE)
					if destination.exists():
						destination.chmod(S_IWRITE)

	@skipUnless(PLATFORM == 'Windows', 'Windows partial replacement failures')
	def test_partial_windows_replace_retains_original_backup(self):
		import ctypes
		for competing in (False, True):
			with self.subTest(competing=competing), TemporaryDirectory() as directory:
				source, destination = Path(directory, 'source'), Path(directory, 'destination')
				source.write_bytes(b'new')
				destination.write_bytes(b'old')
				def partial_replace(old, temporary, backup, *args):
					os.replace(old, backup)
					if competing:
						Path(old).write_bytes(b'competing')
					ctypes.set_last_error(1177)
					return False
				with patch('ctypes.WinDLL') as library:
					library.return_value.ReplaceFileW.side_effect = partial_replace
					with self.assertRaises(OSError) as raised:
						self._fs.copy(as_url(source), as_url(destination))
				self.assertEqual(1177, raised.exception.winerror)
				self.assertEqual(b'new', source.read_bytes())
				self.assertEqual(b'competing' if competing else b'old', destination.read_bytes())
				backups = list(Path(directory).glob('.fb-*/o'))
				if competing:
					self.assertEqual(1, len(backups))
					self.assertEqual(b'old', backups[0].read_bytes())
					self.assertIn(str(backups[0]), raised.exception.strerror)
				else:
					self.assertFalse(backups)
	def test_copy_does_not_replace_competing_creator(self):
		from core.fs.local import CopyFile
		with TemporaryDirectory() as directory:
			source, destination = Path(directory, 'source'), Path(directory, 'destination')
			source.write_bytes(b'new')
			task = CopyFile(self._fs, as_url(source), as_url(destination), 3)
			copy_bytes = task._copy_bytes
			def competing_copy(input_file, output_file):
				copy_bytes(input_file, output_file)
				destination.write_bytes(b'competing creator')
			with patch.object(task, '_copy_bytes', side_effect=competing_copy):
				with self.assertRaises(FileExistsError):
					task()
			self.assertEqual(b'competing creator', destination.read_bytes())
			self.assertEqual({'source', 'destination'}, {path.name for path in Path(directory).iterdir()})
	@skipUnless(PLATFORM == 'Windows', 'Windows replacement metadata')
	def test_overwrite_preserves_destination_security_and_named_stream(self):
		from core.fs.local import CopyFile
		from win32security import GetFileSecurity, SetNamedSecurityInfo, SE_FILE_OBJECT, DACL_SECURITY_INFORMATION, PROTECTED_DACL_SECURITY_INFORMATION, SE_DACL_PROTECTED
		def security_entries(path):
			acl = GetFileSecurity(str(path), DACL_SECURITY_INFORMATION).GetSecurityDescriptorDacl()
			return tuple(acl.GetAce(index) for index in range(acl.GetAceCount()))
		with TemporaryDirectory() as directory:
			source, destination = Path(directory, 'source'), Path(directory, 'destination')
			source.write_bytes(b'new')
			destination.write_bytes(b'old')
			descriptor = GetFileSecurity(str(destination), DACL_SECURITY_INFORMATION)
			SetNamedSecurityInfo(str(destination), SE_FILE_OBJECT,
				DACL_SECURITY_INFORMATION | PROTECTED_DACL_SECURITY_INFORMATION,
				None, None, descriptor.GetSecurityDescriptorDacl(), None)
			self.assertTrue(GetFileSecurity(str(destination), DACL_SECURITY_INFORMATION).GetSecurityDescriptorControl()[0] & SE_DACL_PROTECTED)
			stream = Path(str(destination) + ':retained')
			stream.write_bytes(b'stream')
			security = security_entries(destination)
			copy_bytes = CopyFile._copy_bytes
			def protected_copy(task, input_file, output_file):
				temporary = next(Path(directory).glob('.fc-*'))
				self.assertEqual(security, security_entries(temporary))
				self.assertTrue(GetFileSecurity(str(temporary), DACL_SECURITY_INFORMATION).GetSecurityDescriptorControl()[0] & SE_DACL_PROTECTED)
				return copy_bytes(task, input_file, output_file)
			with patch.object(CopyFile, '_copy_bytes', protected_copy):
				self._fs.copy(as_url(source), as_url(destination))
			self.assertEqual(b'new', destination.read_bytes())
			self.assertEqual(b'stream', stream.read_bytes())
			self.assertEqual(security, security_entries(destination))
			self.assertTrue(GetFileSecurity(str(destination), DACL_SECURITY_INFORMATION).GetSecurityDescriptorControl()[0] & SE_DACL_PROTECTED)
	@skipUnless(PLATFORM == 'Windows', 'Windows junctions')
	def test_junction_move_fallback_refuses_and_rename_preserves_target(self):
		from io import UnsupportedOperation
		from subprocess import run
		with TemporaryDirectory() as directory:
			target, link, destination = (Path(directory, name) for name in ('target', 'link', 'destination'))
			target.mkdir()
			(target / 'keep').write_bytes(b'keep')
			result = run(['cmd', '/c', 'mklink', '/J', str(link), str(target)], capture_output=True, timeout=10)
			self.assertEqual(0, result.returncode, result.stderr)
			with self.assertRaises(UnsupportedOperation):
				list(self._fs._prepare_move(as_url(link), as_url(destination), use_rename=False))
			self.assertTrue(os.path.isjunction(link))
			self._fs.move(as_url(link), as_url(destination))
			self.assertTrue(os.path.isjunction(destination))
			self.assertEqual(b'keep', (target / 'keep').read_bytes())
	@skipUnless(SYMLINKS_SUPPORTED, 'Symbolic links require Windows privilege')
	def test_copy_refuses_dangling_destination_link(self):
		from io import UnsupportedOperation
		with TemporaryDirectory() as directory:
			source, destination, target = (Path(directory, name) for name in ('source', 'destination', 'missing'))
			source.write_bytes(b'keep')
			destination.symlink_to(target)
			with self.assertRaises(UnsupportedOperation):
				self._fs.copy(as_url(source), as_url(destination))
			self.assertTrue(destination.is_symlink())
			self.assertFalse(target.exists())
	def test_failed_copy_preserves_old_or_absent_destination(self):
		from core.fs.local import CopyFile
		from fman import Task
		for exists in (False, True):
			for failure in (OSError('disk full'), Task.Canceled()):
				with self.subTest(exists=exists, failure=type(failure)), TemporaryDirectory() as directory:
					source, destination = Path(directory, 'source'), Path(directory, 'destination')
					source.write_bytes(b'source')
					if exists:
						destination.write_bytes(b'old')
					with patch.object(CopyFile, '_copy_bytes', side_effect=failure):
						with self.assertRaises(type(failure)):
							self._fs.copy(as_url(source), as_url(destination))
					self.assertEqual(b'source', source.read_bytes())
					self.assertEqual(b'old' if exists else None, destination.read_bytes() if destination.exists() else None)
					self.assertEqual({'source', 'destination'} if exists else {'source'}, {path.name for path in Path(directory).iterdir()})
	def test_failed_copy_publication_retains_destination(self):
		from core.fs.local import CopyFile
		with TemporaryDirectory() as directory:
			source, destination = Path(directory, 'source'), Path(directory, 'destination')
			source.write_bytes(b'new')
			destination.write_bytes(b'old')
			with patch.object(CopyFile, '_publish', side_effect=PermissionError('locked')):
				with self.assertRaises(PermissionError):
					self._fs.copy(as_url(source), as_url(destination))
			self.assertEqual(b'old', destination.read_bytes())
	def test_copy_same_file_and_hardlink_preserves_bytes(self):
		from shutil import SameFileError
		for alias in (False, True):
			with self.subTest(alias=alias), TemporaryDirectory() as directory:
				source = Path(directory, 'source')
				source.write_bytes(b'keep this data')
				destination = Path(directory, 'alias') if alias else source
				if alias:
					os.link(source, destination)
				with self.assertRaises(SameFileError):
					self._fs.copy(as_url(source), as_url(destination))
				self.assertEqual(b'keep this data', source.read_bytes())
				self.assertEqual(b'keep this data', destination.read_bytes())
	def test_delete_failure_preserves_exception_and_notifications(self):
		for stat_failure in (False, True):
			with self.subTest(stat_failure=stat_failure), TemporaryDirectory() as directory:
				path = Path(directory, 'file')
				path.write_bytes(b'keep')
				error = PermissionError('locked')
				with patch.object(self._fs, 'stat', side_effect=OSError('stat') if stat_failure else None,
					return_value=path.stat()), patch.object(self._fs, 'notify_file_removed') as removed:
					with self.assertRaises(PermissionError) as raised:
						self._fs._do_delete(_urlpath(path), Mock(side_effect=error))
					self.assertIs(error, raised.exception)
					removed.assert_not_called()
				self.assertEqual(b'keep', path.read_bytes())
	@skipUnless(PLATFORM == 'Windows', 'Windows junctions')
	def test_delete_nested_and_dangling_junction_preserves_target(self):
		from subprocess import run
		with TemporaryDirectory() as directory:
			root = Path(directory)
			target = root / 'target'
			target.mkdir()
			(target / 'keep').write_bytes(b'keep')
			for dangling in (False, True):
				with self.subTest(dangling=dangling):
					parent = root / 'selected'
					parent.mkdir()
					link = parent / 'link'
					result = run(['cmd', '/c', 'mklink', '/J', str(link),
						str(root / 'missing' if dangling else target)], capture_output=True, timeout=10)
					self.assertEqual(0, result.returncode, result.stderr)
					self._fs.delete(_urlpath(parent))
					self.assertFalse(parent.exists())
					self.assertEqual(b'keep', (target / 'keep').read_bytes())
	@skipUnless(PLATFORM == 'Windows', 'Windows non-replacing directory rename')
	def test_directory_rename_conflict_emits_no_notifications(self):
		with TemporaryDirectory() as directory:
			source = Path(directory, 'source')
			destination = Path(directory, 'Destination')
			source.mkdir()
			destination.mkdir()
			with patch.object(self._fs, 'notify_file_added') as added, \
				patch.object(self._fs, 'notify_file_removed') as removed:
				with self.assertRaises(FileExistsError):
					self._fs._rename(as_url(source), as_url(Path(directory, 'destination')))
				added.assert_not_called()
				removed.assert_not_called()
			self.assertTrue(source.is_dir())
			self.assertTrue(destination.is_dir())
	def test_mkdir_root(self):
		with self.assertRaises(FileExistsError):
			self._fs.mkdir('C:' if PLATFORM == 'Windows' else '/')
	def test_iterdir_nonexistent(self):
		root = 'C:/' if PLATFORM == 'Windows' else '/'
		path = root + 'nonexistent'
		with self.assertRaises(FileNotFoundError):
			next(iter(self._fs.iterdir(path)))
	def test_empty_path_does_not_exist(self):
		self.assertFalse(self._fs.exists(''))
	def test_relative_paths(self):
		subdir_name = 'subdir'
		with TemporaryCwd() as tmp_dir:
			Path(tmp_dir, subdir_name).mkdir()
			self.assertFalse(self._fs.exists(subdir_name))
			with self.assertRaises(FileNotFoundError):
				list(self._fs.iterdir(subdir_name))
			with self.assertRaises(FileNotFoundError):
				self._fs.is_dir(subdir_name)
			with self.assertRaises(FileNotFoundError):
				self._fs.stat(subdir_name)
			with self.assertRaises(FileNotFoundError):
				self._fs.size_bytes(subdir_name)
			with self.assertRaises(FileNotFoundError):
				self._fs.modified_datetime(subdir_name)
			with self.assertRaises(ValueError):
				self._fs.touch('test.txt')
			with self.assertRaises(ValueError):
				self._fs.mkdir('other_dir')
			src_url = join(as_url(tmp_dir), subdir_name)
			dst_url = as_url('dir2')
			with self.assertRaises(ValueError):
				self._fs.move(src_url, dst_url)
			with self.assertRaises(ValueError):
				self._fs.prepare_move(src_url, dst_url)
			with self.assertRaises(ValueError):
				self._fs.copy(src_url, dst_url)
			with self.assertRaises(ValueError):
				self._fs.prepare_copy(src_url, dst_url)
			with self.assertRaises(FileNotFoundError):
				self._fs.move_to_trash(subdir_name)
			with self.assertRaises(FileNotFoundError):
				list(self._fs.prepare_trash(subdir_name))
			with self.assertRaises(FileNotFoundError):
				self._fs.delete(subdir_name)
			file_name = 'test.txt'
			Path(tmp_dir, file_name).touch()
			with self.assertRaises(FileNotFoundError):
				self._fs.delete(file_name)
			with self.assertRaises(FileNotFoundError):
				self._fs.resolve(subdir_name)
	@skipIf(PLATFORM != 'Windows', 'Skip Windows-only test')
	def test_isabs_windows(self):
		self.assertTrue(self._fs._isabs(r'\\host'))
		self.assertTrue(self._fs._isabs(r'\\host\share'))
		self.assertTrue(self._fs._isabs(r'\\host\share\subfolder'))
		self.assertFalse(self._fs._isabs('dir'))
		self.assertFalse(self._fs._isabs(r'dir\subdir'))
	@skipUnless(SYMLINKS_SUPPORTED, 'Symbolic links require Windows privilege')
	def test_stat_nonexistent_symlink(self):
		with TemporaryDirectory() as tmp_dir:
			path = Path(tmp_dir, 'symlink')
			path.symlink_to('nonexistent')
			self._fs.stat(_urlpath(path))
	def test_samefile(self):
		this = _urlpath(__file__)
		pardir = _urlpath(Path(__file__).parent)
		init = pardir + '/__init__.py'
		self.assertTrue(self._fs.samefile(this, this))
		self.assertTrue(self._fs.samefile(pardir, pardir))
		self.assertTrue(self._fs.samefile(init, init))
		self.assertFalse(self._fs.samefile(this, pardir))
		self.assertFalse(self._fs.samefile(this, init))
		self.assertFalse(self._fs.samefile(pardir, init))
	@skipIf(PLATFORM != 'Windows', 'Skip Windows-only test')
	def test_samefile_hardlink(self):
		with TemporaryDirectory() as tmp_dir:
			target = Path(tmp_dir, 'target')
			target.touch()
			link = Path(tmp_dir, 'link')
			os.link(target, link)
			self.assertTrue(self._fs.samefile(_urlpath(target), _urlpath(link)))
	def test_samefile_gdrive_file_stream(self):
		with TemporaryDirectory() as tmp_dir:
			a = Path(tmp_dir, 'a')
			a.mkdir()
			b = Path(tmp_dir, 'b')
			b.mkdir()
			a_path = _urlpath(a)
			b_path = _urlpath(b)
			self._fs.cache.put(a_path, 'stat', fake_statresult(0, 0))
			self._fs.cache.put(b_path, 'stat', fake_statresult(0, 0))
			self.assertFalse(self._fs.samefile(a_path, b_path))
	def test_delete_readonly_file(self):
		with TemporaryDirectory() as tmp_dir:
			path = Path(tmp_dir, 'file')
			path.touch()
			path.chmod(path.stat().st_mode ^ S_IWRITE)
			self._fs.delete(_urlpath(path))
	@skipUnless(SYMLINKS_SUPPORTED, 'Symbolic links require Windows privilege')
	def test_delete_symlink_to_directory(self):
		with TemporaryDirectory() as tmp_dir:
			a = Path(tmp_dir, 'a')
			a.mkdir()
			b = Path(tmp_dir, 'b')
			b.symlink_to(a)
			self._fs.delete(_urlpath(b))
			self.assertFalse(b.exists(), 'Failed to delete symlink to folder')
	def test_copy_file(self):
		self._test_transfer_file(self._fs.copy, deletes_src=False)
	def test_move_file(self):
		self._test_transfer_file(self._fs.move, deletes_src=True)
	def _test_transfer_file(self, transfer_fn, deletes_src):
		with TemporaryDirectory() as tmp_dir:
			src = Path(tmp_dir, 'src')
			f_contents = '1234'
			src.write_text(f_contents)
			dst = Path(tmp_dir, 'dst')
			transfer_fn(as_url(src), as_url(dst))
			self.assertTrue(dst.exists())
			self.assertEqual(f_contents, dst.read_text())
			if deletes_src:
				self.assertFalse(src.exists())
	def test_copy_directory(self):
		with TemporaryDirectory() as tmp_dir:
			src = Path(tmp_dir, 'src')
			src.mkdir()
			self._create_test_directory_structure(src)
			dst = Path(tmp_dir, 'dst')
			self._fs.copy(as_url(src), as_url(dst))
			self.assertEqual(
				self._jsonify_directory(src), self._jsonify_directory(dst)
			)
	def test_move_directory(self, use_rename=True):
		with TemporaryDirectory() as tmp_dir:
			src = Path(tmp_dir, 'src')
			src.mkdir()
			self._create_test_directory_structure(src)
			src_contents = self._jsonify_directory(src)
			dst = Path(tmp_dir, 'dst')
			for task in self._fs._prepare_move(
				as_url(src), as_url(dst), use_rename=use_rename
			):
				task()
			self.assertFalse(src.exists())
			self.assertEqual(src_contents, self._jsonify_directory(dst))
	def test_move_directory_without_rename(self):
		self.test_move_directory(use_rename=False)
	def _create_test_directory_structure(self, parent_dir):
		file_1 = parent_dir / 'file.txt'
		file_txt_contents = '12345'
		file_1.write_text(file_txt_contents)
		empty_dir = parent_dir / 'empty'
		empty_dir.mkdir()
		dir_ = parent_dir / 'dir'
		dir_.mkdir()
		file_2 = dir_ / 'file2.txt'
		file_2_contents = '6789'
		file_2.write_text(file_2_contents)
		subdir = dir_ / 'subdir'
		subdir.mkdir()
		file_3 = subdir / 'file_3.txt'
		file_3_contents = 'Hello!'
		file_3.write_text(file_3_contents)
		file_4 = subdir / 'file_4.txt'
		file_4_contents = 'Hello 2!'
		file_4.write_text(file_4_contents)
	def _jsonify_directory(self, dir_):
		result = {}
		for f in dir_.iterdir():
			result[f.name] = \
				self._jsonify_directory(f) if f.is_dir() else f.read_bytes()
		return result
	def test_prepare_move_fails_cleanly(self):
		"""
		Consider moving a file from src to dst. When src and dst are on the same
		drive (as indicated by stat().st_dev having the same value), then a
		simple os.rename(src, dst) suffices to "move" the file.

		On the other hand, if src and dst are not on the same device, then
		LocalFileSystem (LFS) needs to 1) copy src to dst and 2) delete src.

		This test checks that 2) is only performed if 1) was successful, and
		thus that no data loss occurs. It does this by forcing LFS to use the
		copy-move (and not the rename) implementation. Then, it makes 1) fail by
		making dst read-only.
		"""
		with TemporaryDirectory() as tmp_dir:
			src = Path(tmp_dir, 'src')
			# Need to give src some contents. Otherwise, the write to dst goes
			# through without raising a PermissionError.
			src.write_text('some_contents')
			src_url = as_url(src)
			dst_dir = Path(tmp_dir, 'dst_dir')
			dst_dir.mkdir()
			dst = dst_dir / 'dst'
			dst.touch()
			# Make dst read-only.
			dst.chmod(dst.stat().st_mode ^ S_IWRITE)
			try:
				permission_error_raised = False
				for task in self._fs._prepare_move(
					src_url, as_url(dst), use_rename=False
				):
					try:
						task()
					except PermissionError:
						permission_error_raised = True
				self.assertTrue(
					permission_error_raised,
					'PermissionError was not raised upon writing to read-only '
					'dst. This test may have to be updated to trigger this '
					'error in a different way.'
				)
				self.assertTrue(
					src.exists(),
					'LocalFileSystem deleted the source file even though '
					'copying it to the destination failed. This can lead to '
					'data loss!'
				)
			finally:
				# Make file writable again. Otherwise cleaning up the temporary
				# directory fails on Windows.
				dst.chmod(dst.stat().st_mode | S_IWRITE)
	def test_move_across_devices(self):
		with TemporaryDirectory() as tmp_dir:
			src_parent = Path(tmp_dir, 'src_parent')
			src_parent.mkdir()
			src = src_parent / 'src'
			src.mkdir()
			src_file = src / 'file.txt'
			src_file_contents = 'contents'
			src_file.write_text(src_file_contents)
			src_subdir = src / 'subdir'
			src_subdir.mkdir()
			src_subfile = src_subdir / 'subfile.txt'
			src_subfile_contents = '1234'
			src_subfile.write_text(src_subfile_contents)
			dst_parent = Path(tmp_dir, 'dst_parent')
			dst_parent.mkdir()
			dst = dst_parent / src.name
			# Pretend that src_parent and dst_parent are on different devices:
			self._fs.cache.put(
				_urlpath(dst_parent), 'stat', fake_statresult(object(), 1)
			)
			# We don't want to just call `self._fs.move(...)` here, for the
			# following reason: The bug which this test case prevents initially
			# occurred because `_prepare_move(...)` returned these tasks:
			#  1) Create `dst`
			#  2) Move `src_file` into `dst`
			#  3) Delete `src`
			# When returning 2), the implementation checks whether `src_file`
			# and `dst_file` are on the same device. But! At this point, `dst`
			# (and thus `dst_file`) do not yet exist. So this raised a
			# FileNotFoundError.
			# If we did just call `.move(...)`, then 2) would be computed
			# *after* `dst` was created in 1), thus not triggering the error.
			# Hence we use list(...) to force 2) to be computed before 1) runs:
			tasks = list(self._fs.prepare_move(as_url(src), as_url(dst)))
			for task in tasks:
				task()
			self.assertFalse(src.exists())
			self.assertTrue(dst.exists())
			dst_file_contents = (dst / src_file.name).read_text()
			self.assertEqual(src_file_contents, dst_file_contents)
			dst_subfile = dst / 'subdir' / 'subfile.txt'
			dst_subfile_contents = dst_subfile.read_text()
			self.assertEqual(src_subfile_contents, dst_subfile_contents)
	def setUp(self):
		super().setUp()
		self._fs = LocalFileSystem()

class TemporaryCwd:
	def __init__(self):
		self._cwd_before = None
		self._tmp_dir = None
	def __enter__(self):
		self._cwd_before = os.getcwd()
		self._tmp_dir = TemporaryDirectory()
		tmp_dir_path = self._tmp_dir.name
		os.chdir(tmp_dir_path)
		return tmp_dir_path
	def __exit__(self, *_):
		os.chdir(self._cwd_before)
		self._tmp_dir.cleanup()

fake_statresult = namedtuple('fake_statresult', ('st_dev', 'st_ino'))

def _urlpath(file_path):
	return splitscheme(as_url(file_path))[1]