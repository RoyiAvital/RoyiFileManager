import os
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory
from threading import Event, Thread
import traceback


def exercise(context, root, phase):
	from core.commands import CommandPalette, ReloadPlugins, SortByColumn, _recent_commands
	from fman.url import as_url
	from fman.impl.quicksearch import Quicksearch
	from fman.impl.util.qt.thread import run_in_main_thread
	from PyQt5.QtCore import QThread, QTimer
	from PyQt5.QtGui import QFont, QFontMetricsF
	gui = lambda function: run_in_main_thread(function)()
	commands = ('select_all', 'deselect', 'reload')
	expected = tuple(('pane', name) for name in reversed(commands))
	if phase == 'restore':
		expected = (('pane', 'select_all'), ('pane', 'reload'), ('pane', 'deselect'))
	code = 1
	try:
		ready = Event()
		def watch_startup():
			timer = QTimer(context.main_window)
			timer.setInterval(10)
			def check():
				panes = context.window.get_panes()
				if len(panes) == 2 and all(pane.get_path() == as_url(str(root))
					and pane.get_sort_column()[0] in pane.get_columns() for pane in panes):
					timer.stop()
					ready.set()
			timer.timeout.connect(check)
			timer.start()
			return timer
		timer = gui(watch_startup)
		try:
			assert ready.wait(15), 'Startup panes or columns did not settle'
		finally:
			gui(timer.stop)
			gui(timer.deleteLater)
		pane = context.window.get_panes()[0]
		palette = CommandPalette(pane)
		errors = []
		selection = [None]
		other_picker = [False]
		def inspect(dialog):
			def ready():
				try:
					assert isinstance(dialog, Quicksearch)
					assert QThread.currentThread() == context.app.thread()
					if other_picker[0]:
						assert dialog._curr_items
						assert all(not item.hint for item in dialog._curr_items)
					elif selection[0] is not None:
						index = next(index for index, item in enumerate(dialog._curr_items)
							if item.value.identity == ('pane', selection[0]))
						dialog._place_cursor_at_item(index)
						dialog._on_return_pressed()
						return
					else:
						assert tuple(item.value.identity for item in dialog._curr_items[:3]) == expected
						assert all('Recent' in item.hint for item in dialog._curr_items[:3])
						assert len({item.value.identity for item in dialog._curr_items}) == len(dialog._curr_items)
						css = context.theme.get_quicksearch_item_css()
						title_font = QFont(dialog._items.font())
						title_font.setPointSize(int(css['title']['font-size_pts']))
						hint_font = QFont(dialog._items.font())
						hint_font.setPointSize(int(css['hint']['font-size_pts']))
						available = dialog._items.viewport().width() - css['padding-left_px'] - css['padding-right_px']
						checked = 0
						for item in dialog._curr_items:
							title_width = QFontMetricsF(title_font).horizontalAdvance(item.title)
							hint = item.hint.removesuffix(' \u00b7 Recent')
							baseline = title_width + QFontMetricsF(hint_font).horizontalAdvance(hint)
							if baseline + 12 <= available:
								recent_hint = hint + ' \u00b7 Recent' if hint else 'Recent'
								width = title_width + QFontMetricsF(hint_font).horizontalAdvance(recent_hint)
								assert width + 12 <= available, 'New hint overlap: ' + item.title
								checked += 1
						output = Path('target/recent-commands-%s-%s.png' % (os.environ['QT_SCALE_FACTOR'], phase))
						output.parent.mkdir(parents=True, exist_ok=True)
						assert dialog.grab().save(str(output))
						dialog._query.setText('reload')
						assert dialog._curr_items[0].value.identity == ('pane', 'reload')
						assert 'Recent' in dialog._curr_items[0].hint
						assert all('Recent' not in item.hint for item in dialog._curr_items[1:])
						print('PASS: native palette, filtering and', checked, 'bundled hint widths', flush=True)
				except BaseException as error:
					errors.append(error)
				dialog.reject()
			QTimer.singleShot(0, ready)
		gui(lambda: context.main_window.before_dialog.connect(inspect))
		try:
			history_path = root / 'UserSettings/Plugins/User/Settings/Command Palette History (Windows).json'
			if phase == 'record':
				assert not history_path.exists()
				assert not _recent_commands()
				pane.run_command('select_all')
				assert not _recent_commands(), 'Non-palette command was recorded'
				for name in commands:
					selection[0] = name
					palette()
					if errors:
						raise errors[0]
				assert not history_path.exists(), 'History was written during the session'
			else:
				assert history_path.exists(), 'History was not saved on quit'
			assert _recent_commands() == expected
			if phase == 'reload':
				before = history_path.read_bytes()
				selection[0] = 'select_all'
				palette()
				if errors:
					raise errors[0]
				assert _recent_commands()[0] == ('pane', 'select_all')
				ReloadPlugins(context.window)()
				assert history_path.read_bytes() == before, 'Plug-in reload wrote history during the session'
				print('PASS: real plug-in reload, no history write; quitting without reopening palette', flush=True)
				code = 0
				return
			selection[0] = None
			palette()
			if errors:
				raise errors[0]
			other_picker[0] = True
			SortByColumn(pane)()
			if errors:
				raise errors[0]
			assert _recent_commands() == expected
			print('PASS:', phase, 'palette-only recording, shared history and other-picker isolation', flush=True)
		finally:
			gui(lambda: context.main_window.before_dialog.disconnect(inspect))
		code = 0
	except BaseException:
		traceback.print_exc()
	finally:
		gui(lambda: context.app.exit(code))


def main():
	if len(sys.argv) == 1:
		for scale in ('1', '1.5', '2'):
			with TemporaryDirectory(prefix='recent-commands-smoke-') as temporary:
				root = Path(temporary)
				(root / 'sample.txt').write_text('sample', encoding='utf-8')
				environment = dict(os.environ, QT_QPA_PLATFORM='windows', QT_SCALE_FACTOR=scale,
					ROYIFILEMANAGER_USER_SETTINGS=str(root / 'UserSettings'))
				for phase in ('record', 'reload', 'restore'):
					subprocess.run([sys.executable, '-X', 'faulthandler', '-m',
						'fman_integrationtest.recent_commands_smoke', phase], env=environment, check=True)
		return 0
	phase = sys.argv[1]
	root = Path(os.environ['ROYIFILEMANAGER_USER_SETTINGS']).parent
	from fman.impl.application_context import get_application_context
	from PyQt5.QtCore import QTimer
	context = get_application_context()
	_ = context.app
	context.session_manager.is_first_run = False
	sys.argv = [sys.argv[0], str(root), str(root)]
	QTimer.singleShot(0, lambda: Thread(target=exercise, args=(context, root, phase), daemon=True).start())
	return context.run()


if __name__ == '__main__':
	sys.exit(main())