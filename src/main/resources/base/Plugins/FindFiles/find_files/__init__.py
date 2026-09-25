from threading import Lock, Thread
from time import monotonic

from fman import DirectoryPaneCommand, load_json, save_json, show_status_message
from fman.impl.status_bar import format_size
from fman.impl.util.qt.thread import run_in_main_thread
from fman.ui import Action, Choice, DateField, IntegerField, Label, Select, Separator, TableRow, TextField, Toggle, UiController, settings_resource, show_panel, show_table
from fman.url import as_human_readable
from find_files.engine import Options, Runner, TYPES, UNITS, arguments, count_text


SETTINGS_NAME = 'FindFiles.json'
DEFAULTS = {'pattern_mode': 'glob', 'case_mode': 'smart', 'type': 'f', 'full_path': False,
	'recursive': True, 'hidden': False, 'honor_gitignore': True, 'follow_symlinks': False,
	'min_size_unit': 'b', 'max_size_unit': 'b'}
MODE_OPTIONS = (('literal', 'icons/text.svg', 'Literal substring'),
	('glob', 'icons/asterisk.svg', 'Glob: * any text, ? one character, [ab] a set'),
	('regex', 'icons/regex.svg', 'Regular expression (fd syntax)'))
CASE_OPTIONS = (('sensitive', 'Sensitive'), ('insensitive', 'Insensitive'), ('smart', 'Smart'))
UNIT_TOOLTIP = 'Bytes = 1; Kilo Bytes = 1,000; Mega Bytes = 1,000,000; Giga Bytes = 1,000,000,000 bytes'


def settings_snapshot(values):
	result = dict(DEFAULTS)
	if not isinstance(values, dict):
		return result
	choices = {'pattern_mode': tuple(option[0] for option in MODE_OPTIONS),
		'case_mode': tuple(option[0] for option in CASE_OPTIONS), 'type': tuple(option[0] for option in TYPES),
		'min_size_unit': tuple(option[0] for option in UNITS), 'max_size_unit': tuple(option[0] for option in UNITS)}
	for key, default in DEFAULTS.items():
		value = values.get(key, default)
		if type(value) is type(default) and (key not in choices or value in choices[key]):
			result[key] = value
	return result


def options_from_values(root, values):
	return Options(root, **{key: value for key, value in values.items() if key in Options.__dataclass_fields__ and key != 'root'})


class FindUI(UiController):
	pass


class FindSession:
	@run_in_main_thread
	def __init__(self, owner, pane, root, settings):
		self.owner, self.pane, self.root = owner, pane, root
		self.settings = settings
		self.runner = self.table = None
		self.generation = 0
		self.unsubscribe_path = None
		self.save_lock = Lock()
		self.pending_settings = None
		self.saving = False
		panes = pane.window.get_panes()
		side = 'left' if not panes or pane is panes[0] else 'right'
		self.panel = show_panel(owner=owner, pane=pane, rows=(
			(TextField('pattern', 'Name Pattern', max_width=480),
				Choice('pattern_mode', 'Pattern mode', MODE_OPTIONS, settings['pattern_mode']),
				Select('case_mode', 'Case', CASE_OPTIONS, settings['case_mode']),
				Toggle('full_path', 'icons/file-search.svg', 'Full path', settings['full_path'], 'Match the absolute path'),
				Separator('name_filters'),
				TextField('extensions', 'Extensions', tooltip='Semicolon-separated extensions, such as txt;tar.gz', max_width=120),
				TextField('exclude', 'Exclude', tooltip=r'Semicolon-separated exclusion globs; \; matches a literal semicolon', max_width=240),
				Separator('type_filter'),
				Select('type', 'Type', TYPES, settings['type'], 'Entry type to find: files, folders, links or special filesystem entries')),
			(Label('modified_label', 'Modification Date'), DateField('start_date', 'Start', tooltip='Include this local calendar day and later'),
				DateField('end_date', 'End', tooltip='Include this local calendar day and earlier'),
				Separator('size_filters'),
				Label('size_label', 'File Size'), IntegerField('min_size', 'Min', tooltip='Minimum size, inclusive'),
				Select('min_size_unit', '', UNITS, settings['min_size_unit'], UNIT_TOOLTIP),
				IntegerField('max_size', 'Max', tooltip='Maximum size, inclusive'), Select('max_size_unit', '', UNITS, settings['max_size_unit'], UNIT_TOOLTIP),
				Separator('limits'),
				IntegerField('max_results', 'Max Results', minimum=1,
					tooltip='Blank counts all matches; the table retains at most 10,000 rows / 16 MiB')),
			(Label('root', root, 'icons/panel-' + side + '.svg', side.title() + ' pane'),
				Toggle('recursive', 'icons/folder-tree.svg', 'Recursive', settings['recursive'], 'Search subfolders'),
				Toggle('hidden', 'icons/eye.svg', 'Hidden', settings['hidden'], 'Include hidden entries'),
				Toggle('honor_gitignore', 'icons/git-branch.svg', 'Honor .gitignore', settings['honor_gitignore'], 'Honor .gitignore, including outside Git worktrees; .fdignore and .ignore are always honored'),
				Toggle('follow_symlinks', 'icons/link.svg', 'Follow symbolic links', settings['follow_symlinks'], 'Follow links, including targets outside the root'),
				Separator('actions'),
				Action('search', '', 'icons/search.svg', 'Search'), Action('stop', '', 'icons/square.svg', 'Stop'))),
			on_change=self.changed, on_action=self.action, on_closed=self.dispose)
		self.editable = tuple(key for key in self.panel.snapshot() if key not in ('root', 'modified_label', 'size_label'))
		self.unsubscribe_path = pane.on_path_changed(self.refresh_root)
		if owner.attach(self.dispose):
			self.refresh_root()
		else:
			self.dispose()

	@run_in_main_thread
	def refresh_root(self):
		if not self.owner.active or not self.panel.is_open:
			return
		url = self.pane.get_path()
		root = as_human_readable(url) if isinstance(url, str) and url.startswith('file://') else None
		if root != self.root:
			self.generation += 1
			if self.runner is not None:
				self.runner.stop()
				self.runner = None
			if self.table is not None and self.table.is_open:
				self.table.close()
			self.table = None
			self.root = root
			self.panel.set_activity_status()
		self.panel.update(values={'root': self.root or 'Local folder required'})
		self.enable_form()

	def changed(self, values):
		self.enable_form()
		updated = {key: values[key] for key in DEFAULTS}
		if updated == self.settings:
			return
		self.settings = updated
		with self.save_lock:
			self.pending_settings = tuple(updated.items())
			if self.saving:
				return
			self.saving = True
		try:
			Thread(target=self.save_preferences, name='find-files-settings', daemon=True).start()
		except BaseException:
			with self.save_lock:
				self.saving = False
			raise

	def save_preferences(self):
		resource = settings_resource(SETTINGS_NAME)
		while True:
			with self.save_lock:
				values, self.pending_settings = self.pending_settings, None
				if values is None or not self.owner.active or self.panel.cancelled.is_set():
					self.saving = False
					return
			try:
				with resource.lock:
					if not self.owner.active or self.panel.cancelled.is_set():
						continue
					loaded = load_json(SETTINGS_NAME, default={})
					updated = dict(loaded) if isinstance(loaded, dict) else {}
					updated.update(values)
					save_json(SETTINGS_NAME, updated)
					notification = resource.committed(tuple(updated.items()))
				resource.publish(notification)
			except (OSError, ValueError) as error:
				try:
					self.panel.set_activity_status('Could not save Find Files preferences: ' + str(error))
				except RuntimeError:
					pass

	def enable_form(self):
		busy = self.runner is not None or self.table is not None and self.table.is_open
		values = self.panel.snapshot()
		enabled = {key: not busy for key in self.editable}
		enabled.update(search=not busy and self.root is not None, stop=True)
		if not busy:
			enabled['min_size_unit'] = values['min_size'] is not None
			enabled['max_size_unit'] = values['max_size'] is not None
			try:
				if self.root is not None:
					arguments(options_from_values(self.root, values))
			except ValueError as error:
				enabled['search'] = False
				self.panel.set_activity_status(str(error))
			else:
				self.panel.set_activity_status()
		self.panel.update(enabled=enabled)

	def action(self, name, values):
		if name == 'stop':
			if self.runner is not None:
				self.runner.stop()
				self.panel.set_activity_status('Stopping')
			return
		if name != 'search' or self.runner is not None or self.table is not None and self.table.is_open:
			return
		self.refresh_root()
		try:
			options = options_from_values(self.root, values)
			arguments(options)
		except (TypeError, ValueError) as error:
			self.panel.set_activity_status(str(error))
			return
		self.generation += 1
		generation = self.generation
		runner = self.runner = Runner(options, self.panel.cancelled)
		self.enable_form()
		self.panel.set_activity_status(get_text=lambda: '%s: %s entries, %.1f s' % (
			runner.progress.phase, format(runner.progress.matches, ','), monotonic() - runner.started))
		if not runner.start(lambda result: self.completed(generation, result)):
			self.runner = None
			self.enable_form()
			self.panel.set_activity_status('Another Find Files search is still running or stopping.')

	@run_in_main_thread
	def completed(self, generation, result):
		if generation != self.generation or not self.owner.active or not self.panel.is_open:
			return
		self.runner = None
		summary = count_text(len(result.rows), result)
		if result.reason:
			summary += ' - ' + result.reason
		try:
			if result.rows:
				rows = tuple(TableRow(str(index), (hit.relative_path, '' if hit.size is None else format_size(hit.size), hit.modified), hit.path)
					for index, hit in enumerate(result.rows))
				self.table = show_table(owner=self.owner, panel=self.panel, get_rows=lambda: rows,
					num_columns=3, columns_header=('Path', 'Size', 'Modified'), title='Find files',
					entry_path_column=0, base_path=self.root, modal=True, summary=self.root + ' | ' + summary,
					get_count_text=lambda shown, retained: count_text(shown, result),
					get_details=lambda row, column: row.value,
					on_closed=lambda: self.results_closed(generation, summary))
			self.enable_form()
			self.panel.set_activity_status(summary)
		except (RuntimeError, ValueError) as error:
			if self.panel.is_open:
				self.enable_form()
				self.panel.set_activity_status('Could not show Find Files results: ' + str(error))

	def results_closed(self, generation, summary):
		if generation == self.generation and self.owner.active and self.panel.is_open:
			self.table = None
			self.enable_form()
			self.panel.set_activity_status(summary)

	@run_in_main_thread
	def dispose(self):
		self.generation += 1
		self.owner.detach(self.dispose)
		unsubscribe, self.unsubscribe_path = self.unsubscribe_path, None
		if unsubscribe is not None:
			unsubscribe()
		if self.runner is not None:
			self.runner.stop()
		self.table = None


class FindFiles(DirectoryPaneCommand):
	aliases = ('Find files with fd', 'Find files')

	def is_visible(self):
		path = self.pane.get_path()
		return isinstance(path, str) and path.startswith('file://')

	def __call__(self):
		owner = FindUI.require_owner()
		path = self.pane.get_path()
		if not isinstance(path, str) or not path.startswith('file://'):
			show_status_message('Find Files requires a local folder.', timeout_secs=3)
			return
		try:
			with settings_resource(SETTINGS_NAME).lock:
				settings = settings_snapshot(load_json(SETTINGS_NAME, default={}))
		except (OSError, ValueError) as error:
			show_status_message('Could not load Find Files preferences: ' + str(error), timeout_secs=3)
			settings = dict(DEFAULTS)
		if owner.active:
			FindSession(owner, self.pane, as_human_readable(path), settings)