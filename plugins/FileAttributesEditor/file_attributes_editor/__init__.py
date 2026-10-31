import os

import fman
import fman.fs as fs
import fman.ui as ui
from fman.url import as_url, splitscheme


def supported_host():
	return callable(getattr(ui, 'show_quick_check_list', None))


class EditAttributes(fman.DirectoryPaneCommand):
	category = 'File'
	aliases = ('Edit attributes',)

	def is_visible(self):
		return self.pane.get_path().startswith('file://') and bool(self.get_chosen_files())

	def __call__(self):
		if not supported_host():
			fman.show_alert('Edit attributes requires QuickCheckList. Update the application.')
			return
		chosen = self.get_chosen_files()
		if not chosen:
			# Reachable through key bindings and direct calls even though the command is hidden.
			fman.show_status_message('Edit attributes: no files selected.', timeout_secs=5)
			return
		from . import engine
		try:
			capture = _Capture(_local_paths(chosen))
			fman.submit_task(capture)
			if capture.entries is None:
				fman.show_status_message('Edit attributes cancelled.', timeout_secs=5)
				return
			entries = capture.entries
			folders = sum(entry.is_dir for entry in entries)
			keys = 'Enter: Apply \u00b7 Shift+Enter: Apply recursively \u00b7 Esc: Cancel' if folders \
				else 'Enter: Apply \u00b7 Esc: Cancel'
			changed, approval = ui.show_quick_check_list(
				items=tuple(ui.CheckListItem(start.id, start.title, start.state, start.hint,
					start.description, start.enabled) for start in engine.starting_states(entries)),
				states='checkbox3', title=_title(entries, folders),
				summary=os.path.dirname(entries[0].path), status=keys, alternate=bool(folders))
		except (OSError, ValueError) as error:
			fman.show_alert('Edit attributes: ' + str(error))
			return
		if approval is None:
			return
		if not changed:
			fman.show_status_message('No attributes changed.', timeout_secs=5)
			return
		add, remove = engine.masks(changed)
		operation = _Apply(entries, add, remove, approval == 'alternate')
		fman.submit_task(operation)
		report = operation.report
		fman.show_status_message('%sAttributes: %d changed, %d unchanged, %d skipped, %d failed.' % (
			'Cancelled. ' if report.cancelled else '', report.changed, report.unchanged,
			report.skipped, report.failed), timeout_secs=10)
		if report.failures:
			not_listed = report.failed - len(report.failures)
			ui.show_quick_table(columns=(ui.QuickTableColumn('Path'), ui.QuickTableColumn('Error')),
				rows=tuple(ui.QuickTableRow(failure) for failure in report.failures),
				title='Edit attributes failures', summary='%d failed%s' % (
					report.failed, '; %d not listed' % not_listed if not_listed else ''))


def _local_paths(urls):
	paths = []
	for url in urls:
		scheme, path = splitscheme(url)
		if scheme != 'file://':
			raise ValueError('Only local files are supported: ' + url)
		paths.append(os.path.normpath(path))
	return paths


def _title(entries, folders):
	if len(entries) == 1:
		return 'Attributes: ' + (os.path.basename(entries[0].path) or entries[0].path)
	suffix = ' (%d folder%s)' % (folders, '' if folders == 1 else 's') if folders else ''
	return 'Attributes: %d items%s' % (len(entries), suffix)


def _notify(folder):
	fs.notify_file_changed(as_url(folder))


class _Capture(fman.Task):
	def __init__(self, paths):
		super().__init__('Reading attributes', size=len(paths))
		self.paths, self.entries = paths, None

	def __call__(self):
		from .engine import capture
		self.entries = capture(self.paths, check=self.check_canceled)


class _Apply(fman.Task):
	def __init__(self, entries, add, remove, recursive):
		super().__init__('Editing attributes', size=len(entries))
		self.entries, self.add, self.remove, self.recursive = entries, add, remove, recursive
		self.done = 0
		from .engine import Report
		self.report = Report()

	def __call__(self):
		from .engine import Operations, apply
		operations = Operations(notify=_notify, check=self.check_canceled,
			progress=self.set_text, step=self._step)
		try:
			apply(self.entries, self.add, self.remove, self.recursive, operations, self.report)
		except fman.Task.Canceled:
			self.report.cancelled = True
			raise

	def _step(self):
		self.done += 1
		self.set_progress(self.done)
