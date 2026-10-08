"""Independent Windows Robocopy plug-in."""

import os
import subprocess
from threading import Event
from time import monotonic

import fman
import fman.ui as ui


class RobocopyOwner(ui.UiController):
	pass


class CopyWithRobocopy(fman.DirectoryPaneCommand):
	aliases = ('Copy with robocopy',)

	def __call__(self):
		_invoke(self, False)


class MoveWithRobocopy(fman.DirectoryPaneCommand):
	aliases = ('Move with robocopy',)

	def __call__(self):
		_invoke(self, True)


def _destinations(query, opposite, title):
	if query:
		yield fman.QuicksearchItem(query, title='Use this path', description=query, hint=title)
	if opposite and opposite != query:
		yield fman.QuicksearchItem(opposite, title='Opposite pane', description=opposite, hint=title)


def _invoke(command, move):
	from . import engine
	owner = RobocopyOwner.require_owner()
	release = ui.settings_resource('Robocopy operation').try_claim()
	if release is None:
		fman.show_status_message('A Robocopy operation is already active.', timeout_secs=5)
		return
	closed = Event()
	unsubscribe = lambda: None
	operation = None
	try:
		if not owner.attach(closed.set):
			return
		unsubscribe = command.pane.on_closed(closed.set)
		source = command.pane.get_path()
		selected = tuple(command.get_chosen_files())
		engine.from_url(source)
		if not selected:
			raise ValueError('No file is selected.')
		panes = command.pane.window.get_panes()
		opposite = next((pane for pane in panes if pane != command.pane), None)
		try:
			default = engine.from_url(opposite.get_path()) if opposite else ''
		except ValueError:
			default = ''
		settings = engine.Settings.load(fman.load_json('Robocopy.json', default={}))
		title = 'Move with robocopy' if move else 'Copy with robocopy'
		if closed.is_set() or not owner.active:
			return
		choice = fman.show_quicksearch(lambda query: _destinations(query, default, title), query=default)
		if choice is None or closed.is_set() or not owner.active:
			return
		query, value = choice
		destination = query if value is None else value
		if not destination:
			return
		operation = _Transfer(title, source, selected, destination, settings, move, closed)
		fman.submit_task(operation)
		if operation.started and not closed.is_set() and owner.active:
			_refresh(command.pane.window, operation.plan)
		release()
		_present(operation, owner, closed)
	except (OSError, ValueError, RuntimeError) as error:
		if not closed.is_set() and owner.active:
			fman.show_alert('Robocopy: ' + str(error)[:2000])
	finally:
		try:
			unsubscribe()
		finally:
			owner.detach(closed.set)
			release()


def _present(operation, owner, closed):
	if operation is None or closed.is_set() or not owner.active:
		return
	if operation.log is not None and operation.settings.open_log_on_finish:
		try:
			os.startfile(str(operation.log.path))
		except OSError as error:
			operation.notes.append('Could not open the log: ' + str(error)[:300])
	if not closed.is_set() and owner.active:
		if operation.warning:
			fman.show_alert(operation.summary())
		else:
			fman.show_status_message(operation.status_text(), timeout_secs=8)


def _refresh(window, plan):
	from .engine import from_url, related
	try:
		panes = tuple(window.get_panes())
	except RuntimeError:
		return
	for pane in panes:
		try:
			path = from_url(pane.get_path())
			if related(path, plan.source) or related(path, plan.destination):
				pane.reload()
		except (RuntimeError, ValueError):
			continue


class _Transfer(fman.Task):
	def __init__(self, title, source, selected, destination, settings, move, closed):
		from .engine import exit_description
		super().__init__(title)
		self.describe_exit = exit_description
		self.source, self.selected, self.destination = source, selected, destination
		self.settings, self.move, self.closed = settings, move, closed
		self.plan = self.log = None
		self.current_job = None
		self.started = self.canceled = False
		self.codes, self.notes = [], []
		self.error = self.tail = ''
		self.present = self.unknown = self.checked_roots = 0
		self.examples = []
		self.started_at = monotonic()

	def check(self):
		self.check_canceled()
		if self.closed.is_set():
			raise self.Canceled()

	def activity(self, text):
		self.check()
		count = len(self.plan.jobs) if self.plan else 0
		elapsed = max(0, int(monotonic() - self.started_at))
		minutes, seconds = divmod(elapsed, 60)
		label = 'Moving' if self.move else 'Copying'
		if count > 1:
			label += ' | Job %d/%d (approximate)' % (len(self.codes) + 1, count)
		label += ' | %02d:%02d' % (minutes, seconds)
		if self.current_job is not None:
			if self.current_job.filenames:
				label += '\nFiles: %d selected' % len(self.current_job.filenames)
			else:
				name = self.current_job.entries[0].name
				if len(name) > 28:
					name = name[:14] + '...' + name[-11:]
				label += '\nFolder: ' + name
		self.set_text(label)

	def __call__(self):
		from . import engine, windows
		try:
			self.check()
			self.set_size(0)
			self.set_text('Preparing Robocopy...')
			executable = windows.executable()
			log_path = None
			if self.settings.log_enabled:
				from .logs import choose_path
				log_path = choose_path(fman.DATA_DIRECTORY)
			self.plan = engine.prepare(self.source, self.selected, self.destination, executable,
				self.settings, self.move, log_path, self.check)
			engine.probe(executable, self.settings, self.check)
			self.check()
			if log_path:
				from .logs import TransferLog
				self.log = TransferLog(log_path, '%s\r\nSource: %s\r\nDestination: %s' %
					(self.get_title(), self.plan.source, self.plan.destination))
			if len(self.plan.jobs) > 1:
				self.set_size(len(self.plan.jobs))
			for job in self.plan.jobs:
				engine.recheck(self.plan, job, self.check)
				self.current_job = job
				arguments = job.arguments(executable, self.settings, self.move, log_path)
				self.write_log('\r\nJob %d of %d\r\n%s' %
					(len(self.codes) + 1, len(self.plan.jobs), subprocess.list2cmdline(arguments)))
				self.activity('Starting...')
				self.started = True
				code, output = windows.run(arguments, check=self.check, activity=self.activity)
				self.codes.append(code)
				self.tail = output[-2000:]
				if not 0 <= code < 8:
					self.error = 'Robocopy reported a failure; later jobs were not started.'
				self.write_log('Exit %d: %s' % (code, engine.exit_description(code)))
				self.check()
				if self.move:
					present, unknown, examples = engine.remaining(job.entries, self.check)
					self.present += present
					self.unknown += unknown
					self.checked_roots += len(job.entries)
					self.examples.extend(examples[:max(0, 10 - len(self.examples))])
				if not 0 <= code < 8:
					break
				self.check()
				if len(self.plan.jobs) > 1:
					self.set_progress(len(self.codes))
		except self.Canceled:
			self.canceled = True
		except Exception as error:
			self.error = str(error)[:2000]
		finally:
			if self.log is not None:
				try:
					self.log.finish(self.summary())
				except OSError as error:
					self.notes.append('Log finalization failed; log may be incomplete: ' + str(error)[:300])
				try:
					self.log.prune(self.settings.log_retention_count)
				except OSError as error:
					self.notes.append('Log retention failed: ' + str(error)[:300])

	def write_log(self, text):
		if self.log is not None:
			try:
				self.log.append(text)
			except OSError as error:
				raise OSError('Log writing failed after %d finished jobs; completed transfers are retained: %s' %
					(len(self.codes), error)) from error

	@property
	def warning(self):
		return bool(self.canceled or self.error or self.notes or self.present or self.unknown or
			any(not 0 <= code < 8 or code & 4 for code in self.codes))

	def status_text(self):
		count = len(self.plan.jobs) if self.plan else 0
		text = 'Robocopy: %d/%d jobs finished' % (len(self.codes), count)
		if self.codes:
			flags = 0
			for code in self.codes:
				flags |= code
			text += ' | %s | Exit %d' % (self.describe_exit(flags), self.codes[-1])
		return text

	def summary(self):
		count = len(self.plan.jobs) if self.plan else 0
		state = 'Canceled' if self.canceled else ('Stopped' if self.error else 'Finished')
		lines = ['Robocopy %s: %d/%d jobs finished; %d remaining.' %
			(state.lower(), len(self.codes), count, count - len(self.codes))]
		if self.codes:
			flags = 0
			for code in self.codes:
				flags |= code
			result = 'Native failures reported' if any(not 0 <= code < 8 for code in self.codes) else self.describe_exit(flags)
			lines.append('%s. Last exit: %d. File counts/content verification unavailable.' % (result, self.codes[-1]))
		if self.move:
			roots = sum(len(job.entries) for job in self.plan.jobs) if self.plan else len(self.selected)
			lines.append('Selected roots checked: %d; absent: %d; remaining: %d; uncheckable: %d.' %
				(self.checked_roots, self.checked_roots - self.present - self.unknown, self.present, self.unknown))
			if roots > self.checked_roots:
				lines.append('Selected roots not checked: %d (reporting stopped or job not run).' % (roots - self.checked_roots))
			lines.extend(path[:200] for path in self.examples)
		if self.canceled:
			lines.append('Completed and partial changes are retained; no rollback was attempted.')
		if self.error:
			lines.append(self.error)
			if self.tail:
				lines.append(self.tail[-1000:])
		lines.extend(self.notes)
		if self.log is not None:
			lines.append('Log: ' + str(self.log.path))
		return '\n'.join(lines)[:5000]