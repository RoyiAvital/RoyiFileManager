import re
from threading import Event

import fman
import fman.fs as fs
import fman.ui as ui
from fman.url import as_url


def supported_host():
	version = str(fman.APP_VERSION)
	if re.fullmatch(r'[0-9]+\.[0-9]+\.[0-9]+', version) is None:
		return False
	return (tuple(map(int, version.split('.'))) >= (0, 14, 0) and
		callable(getattr(fs, 'rename_no_replace', None)) and callable(getattr(ui, 'show_quick_board', None)))


class BatchFileRenamer(fman.DirectoryPaneCommand):
	aliases = ('Batch File Renamer',)

	def is_visible(self):
		return self.pane.get_path().startswith('file://') and bool(self.get_chosen_files())

	def __call__(self):
		if not supported_host():
			fman.show_alert('Batch File Renamer requires mapped QuickBoard and rename_no_replace. '
				'The released 0.14.0 host does not include them; update the application.')
			return
		from . import engine
		parent_url = self.pane.get_path()
		changed = Event()
		def location_changed():
			if self.pane.get_path() != parent_url:
				changed.set()
		unsubscribe_path = self.pane.on_path_changed(location_changed)
		unsubscribe_close = self.pane.on_closed(changed.set)
		try:
			capture_task = _Capture(self.get_chosen_files())
			fman.submit_task(capture_task)
			captured = capture_task.result
			if captured is None:
				return
			text, accepted, mapping = ui.show_quick_board(columns=engine.COLUMNS,
				get_rows=lambda text, mapping: engine.preview(captured, text, mapping, with_status=True),
				text=engine.DEFAULT_TEMPLATE, title='Batch File Renamer',
				summary='%d candidates; visible rows only | {(index + 1):03d} | {file_index} | {file_date:%%Y%%m%%d}' % len(captured.sources))
			if not accepted:
				return
			entries = engine.plan(captured, text, mapping)
			if any(entry.problem for entry in entries if entry.index is not None):
				fman.show_alert('The visible preview contains invalid names. Nothing was renamed. Run Batch File Renamer again to revise the scope or template.')
				return
			if not any(entry.index is not None and entry.target != entry.source.name for entry in entries):
				fman.show_status_message('No files need renaming.')
				return
			operation = _Rename(captured, entries)
			fman.submit_task(operation)
			if operation.report is None:
				return
			if operation.confirmed and not changed.is_set():
				_restore_selection(self.pane, parent_url, operation.confirmed)
			renamed = len(operation.confirmed)
			excluded = sum(entry.index is None for entry in entries)
			pages = (len(operation.report) + 9999) // 10000
			for page in range(pages):
				kept = ui.show_quick_table(columns=(ui.QuickTableColumn('Original Name'),
					ui.QuickTableColumn('Current Name'), ui.QuickTableColumn('Result')),
					rows=tuple(ui.QuickTableRow((engine.display_name(old), engine.display_name(current),
						engine.display_name(outcome, 256))) for old, current, outcome in operation.report[page * 10000:(page + 1) * 10000]),
					title='Batch File Renamer Results', summary='%d renamed; %d excluded by filter%s' %
						(renamed, excluded, '; page %d/%d' % (page + 1, pages) if pages > 1 else ''))
				if kept is None:
					break
		except (OSError, ValueError) as error:
			fman.show_alert('Batch File Renamer: ' + str(error))
		finally:
			unsubscribe_path()
			unsubscribe_close()


class _Capture(fman.Task):
	def __init__(self, urls):
		super().__init__('Preparing Batch File Renamer')
		self.urls, self.result = tuple(urls), None

	def __call__(self):
		from .engine import capture
		self.result = capture(self.urls, self.check_canceled)


class _Rename(fman.Task):
	def __init__(self, captured, entries):
		super().__init__('Batch File Renamer', sum(entry.index is not None for entry in entries))
		self.captured, self.entries = captured, entries
		self.report, self.confirmed = None, ()

	def __call__(self):
		from .engine import execute, preflight
		self.set_text('Checking visible targets...')
		preflight(self.captured, self.entries, self.check_canceled)
		self.set_text('Renaming visible files...')
		self.report, self.confirmed = execute(self.captured, self.entries, fs.rename_no_replace,
			self.check_canceled, self.set_progress)


def _restore_selection(pane, parent_url, urls):
	def loaded():
		try:
			if pane.get_path() == parent_url:
				pane.clear_selection()
				pane.select(urls)
				for url in urls:
					try:
						pane.place_cursor_at(url)
					except ValueError:
						continue
					break
		except (RuntimeError, ValueError):
			pass
	if pane.get_path() == parent_url:
		pane.reload(on_done=loaded)