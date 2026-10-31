from fman import DirectoryPaneCommand, DirectoryPaneListener, Task, YES, NO, show_alert, show_status_message, submit_task
from fman.fs import FileSystem, Column, query
from fman.ui import QuickTableColumn, QuickTableRow, show_quick_table
from fman.url import splitscheme
from .processes import ProcessError, Snapshot, WindowsApi, get_provider

import os


ROOT = 'process://'


class Processes(FileSystem):
	scheme = ROOT

	def __init__(self):
		super().__init__()
		self.snapshot = Snapshot()

	def get_default_columns(self, path):
		return 'core.Name', 'process_pane.Pid'

	def iterdir(self, path):
		if path:
			raise NotADirectoryError('Process Pane has no child directories.')
		return self.snapshot.refresh(get_provider().snapshot)

	def process_record(self, path):
		return self.snapshot.get(path)

	def scan(self, path, check_canceled):
		from fman.listing import Listing
		if path:
			raise NotADirectoryError('Process Pane has no child directories.')
		def enumerate_records():
			for record in get_provider().snapshot():
				check_canceled()
				yield record
		entries = self.snapshot.capture(enumerate_records)
		return Listing.create(ROOT, (path for path, record in entries),
			labels=(record.name for path, record in entries),
			created_ns=(record.created or 0 for path, record in entries),
			identities=b''.join(record.pid.to_bytes(16, 'little') if record.created is not None
				else bytes(16) for path, record in entries),
			extra=(('pid', tuple(record.pid for path, record in entries)),))

	def name(self, path):
		return self.process_record(path).name if path else 'Processes'

	def is_dir(self, path):
		if path:
			self.process_record(path)
		return not path

	def resolve(self, path):
		self.is_dir(path)
		return ROOT + path


class Pid(Column):
	display_name = 'PID'

	def text(self, listing, index):
		return str(listing.column('pid')[index])

	def keys(self, listing, ascending):
		return listing.column('pid')




class ShowProcesses(DirectoryPaneCommand):
	category = 'Tools'
	aliases = ("Show OS' processes",)

	def __call__(self):
		try:
			get_provider()
		except ProcessError as error:
			show_alert(str(error))
			return
		if self.pane.get_path() == ROOT:
			self.pane.reload()
		else:
			self.pane.set_path(ROOT)


class EndProcess(DirectoryPaneCommand):
	category = 'Tools'
	def is_visible(self):
		return self.pane.get_path() == ROOT and bool(self.get_chosen_files())

	def __call__(self, urls=None):
		if self.pane.get_path() != ROOT:
			return
		urls = self.get_chosen_files() if urls is None else urls
		if not isinstance(urls, (list, tuple)) or len(urls) != 1:
			show_alert('Choose exactly one process to end.')
			return
		url = urls[0]
		if not _is_process_url(url) or url == ROOT:
			show_alert('Choose a process from the process list.')
			return
		try:
			record = query(url, 'process_record')
			provider = get_provider()
		except (OSError, ProcessError) as error:
			show_alert(str(error))
			return
		answer = show_alert(
			'End process "%s" (PID %d)?\n\nForce termination may lose unsaved data. Child processes will not be ended.'
			% (record.name, record.pid), YES | NO, NO
		)
		if answer != YES:
			return
		task = _EndProcess(provider, record)
		submit_task(task)
		if task.error:
			show_alert(task.error)
		elif task.requested:
			show_status_message('Termination requested for %s (PID %d).' % (record.name, record.pid), timeout_secs=5)
		if (task.error or task.requested) and self.pane.get_path() == ROOT:
			self.pane.reload()


class _EndProcess(Task):
	def __init__(self, provider, record):
		super().__init__('End Process', size=1)
		self.provider = provider
		self.record = record
		self.error = None
		self.requested = False

	def __call__(self):
		try:
			self.provider.end(self.record, self.check_canceled)
		except ProcessError as error:
			self.error = str(error)
		else:
			self.requested = True
		self.set_progress(1)


class ProcessPaneListener(DirectoryPaneListener):
	def on_command(self, command_name, args):
		in_process_pane = self.pane.get_path() == ROOT
		if in_process_pane and command_name in ('move_to_trash', 'delete_permanently'):
			return 'end_process', args
		if command_name in ('copy', 'move'):
			files = args.get('files') or []
			dest = args.get('dest_dir')
			if dest is None:
				panes = self.pane.window.get_panes()
				dest = panes[(panes.index(self.pane) + 1) % len(panes)].get_path()
			if in_process_pane or _is_process_url(dest) or any(_is_process_url(url) for url in files):
				return 'process_operation_unsupported', {}
		if in_process_pane and command_name in ('open', 'open_file', 'rename', 'new_empty_file', 'create_and_edit_file'):
			return 'process_operation_unsupported', {}


class ProcessOperationUnsupported(DirectoryPaneCommand):
	category = 'Tools'
	def __call__(self):
		show_alert('Processes are not files. Use F8 to end one process, or refresh the list.')

	def is_visible(self):
		return False


class FindLockingProcesses(DirectoryPaneCommand):
	category = 'File'
	aliases = ('Find blocking processes',)

	def is_visible(self):
		return self.pane.get_path().startswith('file://') and len(self.get_chosen_files()) == 1

	def __call__(self):
		chosen = self.get_chosen_files()
		scheme, path = splitscheme(chosen[0]) if len(chosen) == 1 else ('', '')
		if scheme != 'file://':
			show_status_message('Find blocking processes: choose one local file or folder.', timeout_secs=5)
			return
		path = os.path.normpath(path)
		name = os.path.basename(path) or path
		task = _FindLockingProcesses(path)
		submit_task(task)
		if task.error:
			show_alert('Could not check "%s": %s' % (name, task.error))
			return
		usage = task.usage
		if usage is None:
			show_status_message('Find blocking processes cancelled.', timeout_secs=5)
			return
		if not usage.items:
			show_alert('No process is using "%s".%s' % (name, ''.join('\n\n' + note for note in _notes(usage))))
			return
		show_quick_table(columns=_COLUMNS, rows=task.rows, pane=self.pane,
			title='Processes using ' + name, summary=_summary(usage), truncated=task.truncated)


_COLUMNS = (QuickTableColumn('Process'), QuickTableColumn('PID', 'numeric', format=str),
	QuickTableColumn('Item', 'entry_path'), QuickTableColumn('Program', 'file_path'))
_MAX_ROWS = 10_000
_MAX_RESULT_BYTES = 8 * 1024 * 1024


class _FindLockingProcesses(Task):
	def __init__(self, path):
		super().__init__('Finding blocking processes')
		self.path = path
		self.usage = self.error = None
		self.processes = {}
		self.rows = ()
		self.truncated = False

	def __call__(self):
		from .locks import describe, find
		try:
			self.check_canceled()
			usage = find(self.path, self.check_canceled, self.set_text)
			ids = {pid for path, pids in usage.items for pid in pids}
			self.check_canceled()
			self.processes = describe(ids, WindowsApi(), self.check_canceled) if ids else {}
			self.set_text('Preparing process results...')
			self.rows, self.truncated = _rows(usage, self.processes, self.path, self.check_canceled)
			self.check_canceled()
		except (OSError, ProcessError, ValueError) as error:
			self.error = getattr(error, 'strerror', None) or str(error)
		else:
			self.usage = usage


def _rows(usage, processes, root, check=lambda: None):
	parent = os.path.dirname(root)
	def shown(path):
		return path if parent == root else os.path.relpath(path, parent)
	rows = []
	size = 0
	truncated = usage.limited
	for path, pids in usage.items:
		for pid in pids:
			check()
			if len(rows) >= _MAX_ROWS:
				truncated = True
				break
			name, program = processes[pid]
			item = shown(path)
			row_bytes = sum(len(value.encode('utf-8')) for value in (name, item, program, path, program)) + 32
			if size + row_bytes > _MAX_RESULT_BYTES:
				truncated = True
				break
			rows.append(QuickTableRow((name, pid, item, program), targets=(None, None, path, program or None)))
			size += row_bytes
		else:
			continue
		break
	rows.sort(key=lambda row: (row.cells[0].casefold(), row.cells[1], row.cells[2].casefold()))
	check()
	return rows, truncated


def _summary(usage):
	count = len({pid for path, pids in usage.items for pid in pids})
	parts = ['%d process%s' % (count, '' if count == 1 else 'es')]
	if usage.checked > 1:
		parts.append('{:,} items checked'.format(usage.checked))
	if usage.failed:
		parts.append('{:,} could not be checked'.format(usage.failed))
	if not usage.complete:
		parts.append('stopped at {:,} items'.format(usage.checked))
	if usage.limited:
		parts.append('results limited')
	parts.append('Users may not block rename or delete')
	return ' \u00b7 '.join(parts)


def _notes(usage):
	if usage.failed:
		yield '{:,} items or folders could not be checked.'.format(usage.failed)
	if not usage.complete:
		yield 'Stopped after {:,} items; the rest of the folder was not checked.'.format(usage.checked)
	if usage.limited:
		yield 'Some open-file users were omitted because the result limit was reached.'


def _is_process_url(url):
	return isinstance(url, str) and url.startswith(ROOT)