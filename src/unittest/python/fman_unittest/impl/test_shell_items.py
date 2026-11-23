from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import patch
from zipfile import ZipFile

from fman.impl import shell_items
from fman.impl.shell_items import SHELL_IDLIST_MIME, ShellSelection, dropped_urls, shell_selection
from fman.url import as_url
from PyQt5.QtCore import QMimeData, QUrl

HANDLERS = {'.zip': 'zip://', '.7z': '7z://', '.tar': 'tar://'}


def explorer_idlist(folder_path, names=None):
	"""The "Shell IDList Array" bytes Explorer offers when copying items of a folder."""
	import pythoncom
	import win32clipboard
	from win32com.shell import shell, shellcon
	pythoncom.CoInitialize()
	desktop = shell.SHGetDesktopFolder()
	_, pidl, _ = desktop.ParseDisplayName(0, None, str(folder_path))
	folder = desktop.BindToObject(pidl, None, shell.IID_IShellFolder)
	children = [child for child in folder.EnumObjects(0, shellcon.SHCONTF_FOLDERS | shellcon.SHCONTF_NONFOLDERS)
		if names is None or folder.GetDisplayNameOf(child, shellcon.SHGDN_INFOLDER) in names]
	_, data = folder.GetUIObjectOf(0, children, pythoncom.IID_IDataObject, 0)
	format_ = win32clipboard.RegisterClipboardFormat('Shell IDList Array')
	return data.GetData((format_, None, pythoncom.DVASPECT_CONTENT, -1, pythoncom.TYMED_HGLOBAL)).data


def make_archive(directory, name='sample.zip'):
	archive = Path(directory).resolve() / name
	archive.parent.mkdir(parents=True, exist_ok=True)
	with ZipFile(archive, 'w') as zipped:
		zipped.writestr('report.txt', 'report\n')
		zipped.writestr('folder/inner.txt', 'inner\n')
	return archive


def shell_mime(raw):
	mime = QMimeData()
	mime.setData(SHELL_IDLIST_MIME, raw)
	return mime


class ShellItemsTest(TestCase):
	def setUp(self):
		patcher = patch.object(shell_items, '_cache', (None, None))
		patcher.start()
		self.addCleanup(patcher.stop)
		patcher = patch.object(shell_items, '_archive_handlers', return_value=HANDLERS)
		self.handlers = patcher.start()
		self.addCleanup(patcher.stop)

	def archive_url(self, archive, member, scheme='zip://'):
		return scheme + as_url(archive)[len('file://'):] + '/' + member

	def test_archive_items_map_to_archive_urls(self):
		with TemporaryDirectory() as directory:
			archive = make_archive(directory)
			mime = shell_mime(explorer_idlist(archive))
			expected = {self.archive_url(archive, 'report.txt'), self.archive_url(archive, 'folder')}
			self.assertEqual(expected, set(shell_selection(mime).urls))
			self.assertIsNone(shell_selection(mime).problem)
			urls, from_shell = dropped_urls(mime)
			self.assertEqual(expected, set(urls))
			self.assertTrue(from_shell)

	def test_shell_decides_the_archive_boundary_not_names(self):
		with TemporaryDirectory() as directory:
			# A real folder named like an archive above the archive, and a member
			# folder named like an archive inside it.
			archive = Path(directory).resolve() / 'real.zip' / 'container.zip'
			archive.parent.mkdir()
			with ZipFile(archive, 'w') as zipped:
				zipped.writestr('ordinary.zip/report.txt', 'report\n')
			folder = archive / 'ordinary.zip'
			selection = shell_selection(shell_mime(explorer_idlist(folder)))
			self.assertEqual((self.archive_url(archive, 'ordinary.zip/report.txt'),), selection.urls)
			self.assertIsNone(selection.problem)
			selection = shell_selection(shell_mime(explorer_idlist(archive)))
			self.assertEqual((self.archive_url(archive, 'ordinary.zip'),), selection.urls)

	def test_file_system_items_stay_file_urls_without_reading_settings(self):
		with TemporaryDirectory() as directory:
			root = Path(directory).resolve()
			(root / 'plain.txt').write_text('plain')
			(root / 'notes.zip').mkdir()
			selection = shell_selection(shell_mime(explorer_idlist(root)))
			self.assertEqual({as_url(root / 'plain.txt'), as_url(root / 'notes.zip')}, set(selection.urls))
			self.handlers.assert_not_called()

	def test_unsupported_selection_gives_a_problem_and_no_urls(self):
		with TemporaryDirectory() as directory:
			mime = shell_mime(explorer_idlist(make_archive(directory)))
			self.handlers.return_value = {'.7z': '7z://'}
			selection = shell_selection(mime)
			self.assertEqual((), selection.urls)
			self.assertIn('sample.zip', selection.problem)
			self.assertIn('archive_handlers', selection.problem)
			self.assertEqual(([], True), dropped_urls(mime))
		from win32com.shell import shell, shellcon
		this_pc = shell.SHGetSpecialFolderLocation(0, shellcon.CSIDL_DRIVES)
		for raw in (shell.CIDAAsString(([], [this_pc])), b'not an id list'):
			with self.subTest(raw=raw[:16]):
				selection = shell_selection(shell_mime(raw))
				self.assertEqual((), selection.urls)
				self.assertTrue(selection.problem)

	def test_file_urls_take_precedence_and_plain_data_is_not_shell(self):
		with TemporaryDirectory() as directory:
			archive = make_archive(directory)
			mime = shell_mime(explorer_idlist(archive))
			mime.setUrls([QUrl.fromLocalFile(str(archive)), QUrl()])
			self.assertEqual(([as_url(archive)], False), dropped_urls(mime))
		self.assertEqual(([], False), dropped_urls(QMimeData()))
		self.assertIsNone(shell_selection(QMimeData()))

	def test_repeated_drag_events_resolve_once(self):
		with TemporaryDirectory() as directory:
			mime = shell_mime(explorer_idlist(make_archive(directory)))
			with patch.object(shell_items, '_locate_all', wraps=shell_items._locate_all) as locate:
				first = shell_selection(mime)
				self.assertEqual(first, shell_selection(mime))
			locate.assert_called_once()

	def test_failures_are_retried_by_a_new_paste_or_drag_only(self):
		mime = shell_mime(b'probe')
		results = [((), 'Transient shell error'), ((('C:\\source.txt', ()),), None)]
		with patch.object(shell_items, '_locate_all', side_effect=results) as locate:
			self.assertEqual('Transient shell error', shell_selection(mime).problem)
			# Drag-move events reuse the failure; a new request retries.
			self.assertEqual('Transient shell error', shell_selection(mime).problem)
			shell_items.forget_failure()
			self.assertEqual(ShellSelection(('file://C:/source.txt',), None), shell_selection(mime))
			shell_items.forget_failure()
			self.assertEqual(('file://C:/source.txt',), shell_selection(mime).urls)
		self.assertEqual(2, locate.call_count)

	def test_empty_selection_has_no_urls_and_no_problem(self):
		from win32com.shell import shell
		selection = shell_selection(shell_mime(shell.CIDAAsString(([], []))))
		self.assertEqual(ShellSelection((), None), selection)

	def test_longest_suffix_selects_the_scheme(self):
		handlers = {'.gz': 'gz://', '.tar.gz': 'tar://', '.zip': 'zip://'}
		for name, expected in (('a.TAR.GZ', 'tar://'), ('a.gz', 'gz://'), ('A.ZIP', 'zip://'), ('a.rar', None)):
			with self.subTest(name=name):
				self.assertEqual(expected, shell_items.archive_scheme(name, handlers))

	def test_bundled_handlers_map_compressed_tars_to_ctar(self):
		handlers = bundled_handlers()
		for name, expected in (('x.tar.gz', 'ctar://'), ('X.TGZ', 'ctar://'), ('x.tar.bz2', 'ctar://'),
				('x.tbz2', 'ctar://'), ('x.tbz', 'ctar://'), ('x.tar.xz', 'ctar://'), ('x.txz', 'ctar://'),
				('x.tar.zst', 'ctar://'), ('x.tzst', 'ctar://'), ('x.tar', 'tar://'), ('x.gz', None)):
			with self.subTest(name=name):
				self.assertEqual(expected, shell_items.archive_scheme(name, handlers))

	def test_explorer_items_of_a_compressed_tar_copy_out_through_ctar(self):
		import tarfile
		from io import BytesIO
		from core import LocalFileSystem
		from core.fileoperations import CopyFiles
		from core.fs.zip import CompressedTarFileSystem, _MEMBER_LISTS
		from fman.impl.plugins.mother_fs import MotherFileSystem
		self.handlers.return_value = handlers = bundled_handlers()
		self.addCleanup(_MEMBER_LISTS.clear)
		with TemporaryDirectory() as directory:
			root = Path(directory).resolve()
			for name in ('x.tar.gz', 'x.tgz'):
				with self.subTest(name=name):
					archive = root / name
					with tarfile.open(archive, 'w:gz') as writer:
						info = tarfile.TarInfo('dir/a.txt')
						info.size = 7
						writer.addfile(info, BytesIO(b'payload'))
					try:
						raw = explorer_idlist(archive / 'dir')
					except Exception as error:
						self.skipTest('Explorer cannot open %s here: %s' % (name, error))
					shell_items._cache = (None, None)
					url = self.archive_url(archive, 'dir/a.txt', 'ctar://')
					self.assertEqual((url,), shell_selection(shell_mime(raw)).urls)
					filesystem = MotherFileSystem()
					filesystem.add_child('file://', LocalFileSystem())
					filesystem.add_child('ctar://', CompressedTarFileSystem(filesystem,
						{suffix for suffix, scheme in handlers.items() if scheme == 'ctar://'}))
					output = root / ('out-' + name)
					output.mkdir()
					operation = CopyFiles([url], as_url(output), fs=filesystem)
					with patch.object(operation, 'show_alert', side_effect=AssertionError('Unexpected alert')):
						operation()
					self.assertEqual(b'payload', (output / 'a.txt').read_bytes())


def bundled_handlers():
	import yaml
	settings = Path(__file__).resolve().parents[4] / 'main' / 'resources' / 'base' / 'Plugins' / 'Core' / 'AppSettings.yaml'
	return yaml.safe_load(settings.read_text(encoding='utf-8'))['archive_handlers']
