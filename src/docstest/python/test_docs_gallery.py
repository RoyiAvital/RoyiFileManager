"""Documentation gallery captures. Run by `python build.py test-docs` (Pages workflow), not by `build.py test`."""
import importlib.util
from contextlib import contextmanager
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory
from textwrap import dedent
from unittest import TestCase
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[3]
SCRIPT = ROOT / 'src' / 'misc' / 'generate_docs_screenshots.py'
SPEC = importlib.util.spec_from_file_location('generate_docs_screenshots', SCRIPT)
screenshots = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(screenshots)


@contextmanager
def resolved_temporary_directory():
	# CI temp can be an 8.3 alias (RUNNER~1); the app shows resolved long paths.
	with TemporaryDirectory() as directory:
		yield str(Path(directory).resolve(strict=True))


class DocsGalleryTest(TestCase):
	def test_selection_capture_shows_previews_and_preserves_sample_files(self):
		script = '''
import os, sys
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0, sys.argv[1])
import generate_docs_screenshots as screenshots
from core import commands
from fman.impl.application_context import get_application_context
from fman.impl.widgets import MainWindow
from PyQt5.QtGui import QScreen

screenshots.WORK_DIR = Path(os.environ['ROYIFILEMANAGER_USER_SETTINGS']).parent.parent
context = get_application_context()
captured = []
original = MainWindow.grab
def grab(window):
	pane = context.window.get_panes()[0]
	assert pane._widget._location_bar.text() == 'Selection sample'
	assert pane._widget._model.rowCount() == 10
	bar = pane._widget._filter_bar
	if len(captured) < 2:
		assert bar.isVisible() and bar._selection_label.isVisible()
		assert bar._selection_session['selecting'] == (len(captured) == 0)
		assert len(pane.get_selected_files()) == (1 if not captured else 4)
		assert len(pane._widget._file_view._delegate.preview_rows) == (4 if not captured else 2)
	else:
		assert bar._selection_session is None
		assert {Path(url).name for url in pane.get_selected_files()} == {'README.md', 'archive.tar.gz', 'backup.gz'}
	captured.append(True)
	return original(window)
args = screenshots._parse_args(['--_source-child', '--_capture', 'selection', '--output-dir', sys.argv[2]])
with patch.object(MainWindow, 'grab', grab), patch.object(QScreen, 'grabWindow',
		side_effect=AssertionError('Desktop capture forbidden')), patch.object(commands, 'submit_task',
		side_effect=AssertionError('Selection capture must not transfer files')):
	assert screenshots._capture_source_child(args) == 0
assert len(captured) == 3
sample = screenshots.WORK_DIR / 'source-selection/sample'
assert {path.name for path in sample.iterdir()} == {*screenshots.SELECTION_NAMES, 'Projects'}
for name in screenshots.SELECTION_NAMES:
	assert (sample / name).read_text(encoding='utf-8') == 'Documentation sample: ' + name + '\\n'
for output in screenshots._source_outputs(args.output_dir, 'selection'):
	screenshots._validate_image(output)
'''
		with resolved_temporary_directory() as directory, patch.object(screenshots, 'WORK_DIR', Path(directory)):
			settings = screenshots._prepare_settings('source-selection', initialize=False)
			environment = screenshots._source_environment(settings)
			environment['QT_QPA_PLATFORM'] = 'windows'
			result = subprocess.run([sys.executable, '-B', '-X', 'faulthandler', '-c', dedent(script),
				str(SCRIPT.parent), str(settings.parent / 'output')], cwd=ROOT, env=environment,
				capture_output=True, text=True, timeout=45)
			self.assertEqual(0, result.returncode, result.stdout + result.stderr)

	def test_duplicate_and_free_space_captures_are_real_and_isolated(self):
		script = '''
import os, sys
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0, sys.argv[1])
import generate_docs_screenshots as screenshots
from core import commands
from fman.impl.application_context import get_application_context
from fman.impl.widgets import MainWindow, Prompt
from PyQt5.QtGui import QScreen

screenshots.WORK_DIR = Path(os.environ['ROYIFILEMANAGER_USER_SETTINGS']).parent.parent
context = get_application_context()
capture = sys.argv[3]
captured = []
original_window, original_prompt = MainWindow.grab, Prompt.grab
def grab_window(window):
	pane = context.window.get_panes()[0]
	if capture == 'duplicate-file':
		assert pane._widget._location_bar.text() == 'Duplication sample'
	else:
		assert pane.get_path() == 'file://C:/Windows/Web'
		status = window._single_pane_status
		assert status.isVisible() and status._free_space.isVisible()
		assert status._free_space.text().startswith('Free: ') and ' of ' in status._free_space.text()
	captured.append('window')
	return original_window(window)
def grab_prompt(dialog):
	assert dialog.textValue() == 'report Copy 2.txt'
	assert 'report.txt' in dialog.labelText()
	captured.append('prompt')
	return original_prompt(dialog)
args = screenshots._parse_args(['--_source-child', '--_capture', capture, '--output-dir', sys.argv[2]])
with patch.object(MainWindow, 'grab', grab_window), patch.object(Prompt, 'grab', grab_prompt), \\
		patch.object(QScreen, 'grabWindow', side_effect=AssertionError('Desktop capture forbidden')), \\
		patch.object(commands, 'submit_task', side_effect=AssertionError('Capture must not copy files')) as transfer:
	assert screenshots._capture_source_child(args) == 0
	transfer.assert_not_called()
assert captured == (['window', 'prompt'] if capture == 'duplicate-file' else ['window'])
if capture == 'duplicate-file':
	sample = screenshots.WORK_DIR / 'source-duplicate-file/sample'
	assert {path.name for path in sample.iterdir()} == {'report.txt', 'report Copy 1.txt'}
	for path in sample.iterdir():
		assert path.read_text(encoding='utf-8') == 'Documentation sample: ' + path.name + '\\n'
screenshots._validate_image(screenshots._source_outputs(args.output_dir, args._capture)[0])
'''
		for capture in ('duplicate-file', 'free-space'):
			with self.subTest(capture=capture), resolved_temporary_directory() as directory, \
					patch.object(screenshots, 'WORK_DIR', Path(directory)):
				settings = screenshots._prepare_settings('source-' + capture, initialize=False)
				environment = screenshots._source_environment(settings)
				environment['QT_QPA_PLATFORM'] = 'windows'
				result = subprocess.run([sys.executable, '-B', '-X', 'faulthandler', '-c', dedent(script),
					str(SCRIPT.parent), str(settings.parent / 'output'), capture], cwd=ROOT, env=environment,
					capture_output=True, text=True, timeout=45)
				self.assertEqual(0, result.returncode, result.stdout + result.stderr)

	def test_robocopy_capture_selects_folder_and_cancels_without_transfer(self):
		script = '''
import sys
from unittest.mock import patch
sys.path.insert(0, sys.argv[1])
import generate_docs_screenshots as screenshots
import fman
from fman.impl.application_context import get_application_context
from fman.impl.quicksearch import Quicksearch
from PyQt5.QtGui import QScreen

context = get_application_context()
captured = []
original = Quicksearch.grab
def grab(dialog):
    assert dialog._query.text() == 'C:\\\\Backups\\\\Wallpapers'
    assert dialog._curr_items[0].value == dialog._query.text()
    assert dialog._curr_items[0].hint == 'Copy with robocopy'
    assert context.window.get_panes()[0].get_selected_files() == ['file://C:/Windows/Web/Wallpaper']
    captured.append(True)
    return original(dialog)
args = screenshots._parse_args([
    '--_source-child', '--_capture', 'robocopy', '--output-dir', sys.argv[2]
])
with patch.object(Quicksearch, 'grab', grab), patch.object(QScreen, 'grabWindow',
        side_effect=AssertionError('Desktop capture is forbidden')), patch.object(fman, 'submit_task',
        side_effect=AssertionError('Screenshot must not start a transfer')) as transfer:
    assert screenshots._capture_source_child(args) == 0
    transfer.assert_not_called()
assert captured == [True], 'Destination picker was not captured'
screenshots._validate_image(screenshots._source_outputs(args.output_dir, 'robocopy')[0])
'''
		with resolved_temporary_directory() as directory, patch.object(screenshots, 'WORK_DIR', Path(directory)):
			settings = screenshots._prepare_settings('robocopy')
			environment = screenshots._source_environment(settings)
			environment['QT_QPA_PLATFORM'] = 'windows'
			result = subprocess.run([sys.executable, '-B', '-X', 'faulthandler', '-c', dedent(script),
				str(SCRIPT.parent), str(settings.parent / 'output')], cwd=ROOT, env=environment,
				capture_output=True, text=True, timeout=45)
			self.assertEqual(0, result.returncode, result.stdout + result.stderr)

	def test_quick_board_capture_shows_arguments_without_desktop_grab(self):
		script = '''
import sys
from unittest.mock import patch
sys.path.insert(0, sys.argv[1])
import generate_docs_screenshots as screenshots
from fman.impl.application_context import get_application_context
from fman.impl.ui.quick_board import QuickBoardWindow
from PyQt5.QtCore import Qt
from PyQt5.QtGui import QScreen

context = get_application_context()
closed, captured = [], []
context.main_window.closed.connect(lambda: closed.append(True))
original = QuickBoardWindow.grab
def grab(window):
    assert window.input.text() == 'Archive_'
    assert window.windowTitle() == 'Compose a file-name prefix'
    assert window.summary.content == '3 captured names; preview only'
    assert tuple(row.cells for row in window.table.model.rows) == (
        ('report.txt', 'Archive_report.txt'), ('notes.md', 'Archive_notes.md'),
        ('photo.jpg', 'Archive_photo.jpg'))
    assert window.summary.isVisible() and window.input.isVisible()
    assert window.summary.text() == window.summary.content
	assert window.header.isVisible() and window.header.content == window.windowTitle()
	assert window.windowFlags() & Qt.FramelessWindowHint
	assert window.status.content == '3 / 3 rows'
    image = original(window)
	assert image.height() == round(window.height() * image.devicePixelRatio()), 'Wrong widget bounds'
    captured.append(True)
    return image
args = screenshots._parse_args([
    '--_source-child', '--_capture', 'quick-board', '--output-dir', sys.argv[2]
])
with patch.object(QuickBoardWindow, 'grab', grab), patch.object(QScreen, 'grabWindow',
	side_effect=AssertionError('Desktop capture is forbidden')):
    assert screenshots._capture_source_child(args) == 0
assert captured == [True] and closed == [True], 'Capture or normal cleanup was skipped'
screenshots._validate_image(screenshots._source_outputs(args.output_dir, 'quick-board')[0])
'''
		with resolved_temporary_directory() as directory, patch.object(screenshots, 'WORK_DIR', Path(directory)):
			settings = screenshots._prepare_settings('quick-board')
			environment = screenshots._source_environment(settings)
			environment['QT_QPA_PLATFORM'] = 'windows'
			result = subprocess.run([sys.executable, '-B', '-X', 'faulthandler', '-c', dedent(script.expandtabs(4)),
				str(SCRIPT.parent), str(settings.parent / 'output')], cwd=ROOT, env=environment,
				capture_output=True, text=True, timeout=45)
			self.assertEqual(0, result.returncode, result.stdout + result.stderr)

	def test_batch_renamer_capture_previews_samples_without_renaming(self):
		script = '''
import os, re, sys
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0, sys.argv[1])
import generate_docs_screenshots as screenshots
import fman.fs
from fman.impl.ui.quick_board import QuickBoardWindow
from fman.impl.widgets import MainWindow
from PyQt5.QtGui import QScreen

screenshots.WORK_DIR = Path(os.environ['ROYIFILEMANAGER_USER_SETTINGS']).parent.parent
closed, captured = [], []
original_grab, original_close = QuickBoardWindow.grab, MainWindow.closeEvent
def grab(window):
	assert window.windowTitle() == 'Batch File Renamer'
	assert (window.width(), window.height()) == (900, 600)
	assert window.input.text() == screenshots.BATCH_RENAMER_TEMPLATE
	assert '{c}' in window.summary.content and '{d}' in window.summary.content
	assert window.summary.text() == window.summary.content
	rows = window.table.model.rows
	assert tuple(row.cells[2] for row in rows) == screenshots.BATCH_RENAMER_NAMES
	for index, row in enumerate(rows):
		assert re.fullmatch(r'Archive_%03d_[a-zA-Z][0-9][.]txt' % (index + 1), row.cells[4])
	captured.append(True)
	return original_grab(window)
def close(window, event):
	closed.append(True)
	return original_close(window, event)
args = screenshots._parse_args([
	'--_source-child', '--_capture', 'batch-renamer', '--output-dir', sys.argv[2]
])
with patch.object(QuickBoardWindow, 'grab', grab), patch.object(MainWindow, 'closeEvent', close), \\
		patch.object(QScreen, 'grabWindow', side_effect=AssertionError('Desktop capture forbidden')), \\
		patch.object(fman.fs, 'rename_no_replace', side_effect=AssertionError('Screenshot must not rename')) as rename:
	assert screenshots._capture_source_child(args) == 0
	rename.assert_not_called()
assert captured == [True] and closed == [True], 'Capture or normal shutdown missing'
sample = screenshots.WORK_DIR / 'source-batch-renamer/sample'
assert sorted(path.name for path in sample.iterdir()) == sorted(screenshots.BATCH_RENAMER_NAMES)
for path in sample.iterdir():
	assert path.read_text(encoding='utf-8') == 'Documentation sample: ' + path.name + '\\n'
screenshots._validate_image(screenshots._source_outputs(args.output_dir, 'batch-renamer')[0])
'''
		with resolved_temporary_directory() as directory, patch.object(screenshots, 'WORK_DIR', Path(directory)):
			settings = screenshots._prepare_settings('source-batch-renamer', initialize=False)
			environment = screenshots._source_environment(settings)
			environment['QT_QPA_PLATFORM'] = 'windows'
			result = subprocess.run([sys.executable, '-B', '-X', 'faulthandler', '-c', dedent(script.expandtabs(4)),
				str(SCRIPT.parent), str(settings.parent / 'output')], cwd=ROOT, env=environment,
				capture_output=True, text=True, timeout=45)
			self.assertEqual(0, result.returncode, result.stdout + result.stderr)

	def test_edit_attributes_capture_shows_states_without_writing(self):
		script = '''
import os, sys
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0, sys.argv[1])
import generate_docs_screenshots as screenshots
from fman.impl.ui.quick_check_list import QuickCheckListWindow
from PyQt5.QtGui import QScreen

screenshots.WORK_DIR = Path(os.environ['ROYIFILEMANAGER_USER_SETTINGS']).parent.parent
captured = []
original = QuickCheckListWindow.grab
def grab(window):
	assert window.windowTitle() == 'Attributes: 3 items (1 folder)'
	assert window.list.summary.content == 'Attributes sample'
	assert window.list.count.text() == '1 changed'
	assert 'Shift+Enter: Apply recursively' in window.list.status.content
	captured.append(True)
	return original(window)
args = screenshots._parse_args([
	'--_source-child', '--_capture', 'edit-attributes', '--output-dir', sys.argv[2]
])
sample = screenshots.WORK_DIR / 'source-edit-attributes/sample'
with patch.object(QuickCheckListWindow, 'grab', grab), \\
		patch.object(QScreen, 'grabWindow', side_effect=AssertionError('Desktop capture forbidden')):
	assert screenshots._capture_source_child(args) == 0
assert captured == [True], 'Edit attributes was not captured'
for name, attributes in screenshots.EDIT_ATTRIBUTES_SAMPLE.items():
	assert os.lstat(sample / name).st_file_attributes & 0x2021 == attributes & 0x2021, name
screenshots._validate_image(screenshots._source_outputs(args.output_dir, 'edit-attributes')[0])
'''
		with resolved_temporary_directory() as directory, patch.object(screenshots, 'WORK_DIR', Path(directory)):
			settings = screenshots._prepare_settings('source-edit-attributes', initialize=False)
			environment = screenshots._source_environment(settings)
			environment['QT_QPA_PLATFORM'] = 'windows'
			result = subprocess.run([sys.executable, '-B', '-X', 'faulthandler', '-c', dedent(script.expandtabs(4)),
				str(SCRIPT.parent), str(settings.parent / 'output')], cwd=ROOT, env=environment,
				capture_output=True, text=True, timeout=45)
			self.assertEqual(0, result.returncode, result.stdout + result.stderr)

	def test_text_capture_generates_its_own_python_sample(self):
		with resolved_temporary_directory() as temporary_directory, \
				patch.object(screenshots, 'WORK_DIR', Path(temporary_directory)), \
				patch.object(screenshots, '_public_paths', return_value=(
					Path('C:\\'), Path('C:\\Windows')
				)):
			left, right = screenshots._source_capture_paths('quick-view-text')
			self.assertEqual(Path(temporary_directory) / 'source-quick-view-text/sample', left)
			self.assertEqual(Path('C:\\Windows'), right)
			source = (left / 'file_summary.py').read_text(encoding='utf-8')
			self.assertEqual(screenshots.PYTHON_SAMPLE, source)
			self.assertNotIn('\t', source)
			compile(source, 'file_summary.py', 'exec')
