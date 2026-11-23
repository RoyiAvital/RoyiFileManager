"""End-to-end check: paste and drop items from Explorer's archive view into a pane.

Uses Explorer's own data object for a ZIP and a .tar.gz (no file paths, only
shell IDs), the real OLE clipboard, and the real application. Run:
	python -m fman_integrationtest.explorer_archive_smoke
Note: this replaces the current clipboard contents.
"""
import hashlib
from io import BytesIO
import os
from pathlib import Path
import subprocess
import sys
import tarfile
from tempfile import TemporaryDirectory
from threading import Event, Thread
import traceback
from zipfile import ZipFile


def exercise(context, root):
	from fman.impl.util.qt.thread import run_in_main_thread
	from fman.url import as_url
	from PyQt5.QtCore import QMimeData, QPoint, Qt, QTimer
	from PyQt5.QtGui import QDropEvent
	from PyQt5.QtTest import QTest
	from PyQt5.QtWidgets import QApplication
	gui = lambda function: run_in_main_thread(function)()
	def wait_for(predicate, message, seconds=20):
		ready = Event()
		def start():
			timer = QTimer(context.main_window)
			timer.setInterval(20)
			def check():
				if predicate():
					timer.stop()
					timer.deleteLater()
					ready.set()
			timer.timeout.connect(check)
			timer.start()
			check()
		gui(start)
		assert ready.wait(seconds), message
	# A real folder named like an archive holds the archive (Sol's ambiguity cases).
	archive = root / 'real.zip' / 'sample.zip'
	before = hashlib.sha256(archive.read_bytes()).hexdigest()
	tarred = root / 'sample.tar.gz'
	tarred_before = hashlib.sha256(tarred.read_bytes()).hexdigest()
	code = 1
	try:
		wait_for(lambda: len(context.window.get_panes()) == 2, 'Panes did not load')
		left, right = context.window.get_panes()
		dialogs = []
		def answer(dialog):
			# Accept the usual "Copy N files to" prompt as the user would; refuse anything else.
			dialogs.append((type(dialog).__name__, getattr(dialog, 'labelText', lambda: '')()))
			QTimer.singleShot(0, dialog.accept if type(dialog).__name__ == 'Prompt' else dialog.reject)
		gui(lambda: context.main_window.before_dialog.connect(answer))

		import pythoncom
		from fman_unittest.impl.test_shell_items import explorer_idlist
		from win32com.shell import shell, shellcon
		def explorer_copy():
			desktop = shell.SHGetDesktopFolder()
			_, pidl, _ = desktop.ParseDisplayName(0, None, str(archive))
			folder = desktop.BindToObject(pidl, None, shell.IID_IShellFolder)
			children = list(folder.EnumObjects(0, shellcon.SHCONTF_FOLDERS | shellcon.SHCONTF_NONFOLDERS))
			_, data = folder.GetUIObjectOf(0, children, pythoncom.IID_IDataObject, 0)
			pythoncom.OleSetClipboard(data)
			pythoncom.OleFlushClipboard()
		gui(explorer_copy)
		paste_target = root / 'paste'
		left.focus()
		wait_for(left._widget.hasFocus, 'Left pane did not take focus')
		gui(lambda: QTest.keyClick(left._widget._file_view, Qt.Key_V, Qt.ControlModifier))
		wait_for(lambda: all((paste_target / name).is_file() for name in ('report.txt', 'folder/inner.txt', 'ordinary.zip/note.txt')),
			'Ctrl+V did not extract the Explorer items: dialogs=%r' % dialogs)
		assert (paste_target / 'report.txt').read_text(encoding='utf-8') == 'report\n'
		assert (paste_target / 'folder' / 'inner.txt').read_text(encoding='utf-8') == 'inner\n'
		assert (paste_target / 'ordinary.zip' / 'note.txt').read_text(encoding='utf-8') == 'note\n'
		print('PASS: Ctrl+V extracted report.txt, folder/ and the archive-named folder ordinary.zip/', flush=True)

		drop_target = root / 'drop'
		def drop(raw):
			from fman.impl.shell_items import SHELL_IDLIST_MIME
			from PyQt5.QtGui import QDragEnterEvent, QDragMoveEvent
			viewport = right._widget._file_view.viewport()
			mime = QMimeData()
			mime.setData(SHELL_IDLIST_MIME, raw)
			# Below the last row: drop into the pane's folder. Shift (move) must still copy.
			point = QPoint(viewport.width() // 2, viewport.height() - 2)
			actions = Qt.CopyAction | Qt.MoveAction
			for event_type in (QDragEnterEvent, QDragMoveEvent):
				QApplication.sendEvent(viewport, event_type(point, actions, mime, Qt.LeftButton, Qt.ShiftModifier))
			event = QDropEvent(point, actions, mime, Qt.LeftButton, Qt.ShiftModifier)
			QApplication.sendEvent(viewport, event)
			return event.dropAction(), event.isAccepted()
		raw = explorer_idlist(archive, names={'report'})
		action, accepted = gui(lambda: drop(raw))
		assert action == Qt.CopyAction and accepted, (action, accepted)
		wait_for(lambda: (drop_target / 'report.txt').is_file(), 'Shift+drop did not extract: dialogs=%r' % dialogs)
		assert (drop_target / 'report.txt').read_text(encoding='utf-8') == 'report\n'
		print('PASS: Shift+drop copied report.txt from Explorer\'s ZIP view', flush=True)

		# A compressed tar with './' names, as tar and shutil.make_archive write them.
		expected_prompts = ['Copy 3 files to', 'Copy "report.txt" to']
		try:
			raw = explorer_idlist(tarred, names={'notes'})
		except Exception as error:
			print('SKIP: Explorer cannot open .tar.gz here: %s' % error, flush=True)
		else:
			action, accepted = gui(lambda: drop(raw))
			assert action == Qt.CopyAction and accepted, (action, accepted)
			wait_for(lambda: (drop_target / 'notes' / 'tarred.txt').is_file(),
				'Drop from the .tar.gz did not extract: dialogs=%r' % dialogs)
			assert (drop_target / 'notes' / 'tarred.txt').read_text(encoding='utf-8') == 'tarred\n'
			expected_prompts.append('Copy "notes" to')
			print('PASS: Shift+drop copied notes/ from Explorer\'s view of a .tar.gz', flush=True)

		assert hashlib.sha256(archive.read_bytes()).hexdigest() == before, 'The archive changed'
		assert hashlib.sha256(tarred.read_bytes()).hexdigest() == tarred_before, 'The .tar.gz changed'
		assert [name for name, text in dialogs] == ['Prompt'] * len(expected_prompts), dialogs
		assert [text for name, text in dialogs] == expected_prompts, dialogs
		print('PASS: archives unchanged; only the usual copy prompts: %r' % [text for name, text in dialogs], flush=True)
		code = 0
	except BaseException:
		traceback.print_exc()
	finally:
		def stop_models():
			for pane in context.window.get_panes():
				pane._widget._model.shutdown()
		try:
			gui(stop_models)
		finally:
			gui(lambda: context.app.exit(code))


def run_application(root):
	os.environ['ROYIFILEMANAGER_USER_SETTINGS'] = str(root / 'UserSettings')
	from fman.impl.application_context import get_application_context
	from PyQt5.QtCore import QTimer
	context = get_application_context()
	_ = context.app
	context.session_manager.is_first_run = False
	sys.argv = [sys.argv[0], str(root / 'paste'), str(root / 'drop')]
	QTimer.singleShot(0, lambda: Thread(target=exercise, args=(context, root), daemon=True).start())
	return context.run()


def main():
	if len(sys.argv) > 1:
		return run_application(Path(sys.argv[1]))
	with TemporaryDirectory(prefix='explorer-archive-smoke-') as temporary:
		root = Path(temporary).resolve(strict=True)
		for name in ('paste', 'drop'):
			(root / name).mkdir()
		(root / 'real.zip').mkdir()
		with ZipFile(root / 'real.zip' / 'sample.zip', 'w') as zipped:
			zipped.writestr('report.txt', 'report\n')
			zipped.writestr('folder/inner.txt', 'inner\n')
			zipped.writestr('ordinary.zip/note.txt', 'note\n')
		with tarfile.open(root / 'sample.tar.gz', 'w:gz') as tarred:
			for name, contents in (('.', None), ('./notes', None), ('./notes/tarred.txt', b'tarred\n')):
				info = tarfile.TarInfo(name)
				if contents is None:
					info.type = tarfile.DIRTYPE
					tarred.addfile(info)
				else:
					info.size = len(contents)
					tarred.addfile(info, BytesIO(contents))
		return subprocess.run([sys.executable, '-m', 'fman_integrationtest.explorer_archive_smoke', str(root)],
			timeout=120).returncode


if __name__ == '__main__':
	sys.exit(main())
