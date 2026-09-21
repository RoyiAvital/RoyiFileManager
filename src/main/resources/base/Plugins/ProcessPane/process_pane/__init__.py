from fman import DirectoryPaneCommand, DirectoryPaneListener, Task, YES, NO, show_alert, show_status_message, submit_task
from fman.fs import FileSystem, Column, query
from .processes import ProcessError, Snapshot, get_provider


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

	def get_str(self, url):
		return str(self.get_sort_value(url))

	def get_sort_value(self, url, is_ascending=True):
		return query(url, 'process_record').pid


class ShowProcesses(DirectoryPaneCommand):
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
	def __call__(self):
		show_alert('Processes are not files. Use F8 to end one process, or refresh the list.')

	def is_visible(self):
		return False


def _is_process_url(url):
	return isinstance(url, str) and url.startswith(ROOT)