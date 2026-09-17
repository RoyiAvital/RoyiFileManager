from dataclasses import dataclass
from threading import Lock, Thread
from time import monotonic

from fman import DirectoryPaneCommand, load_json, save_json, show_status_message
from fman.ui import Action, Choice, Label, TableRow, TextField, Toggle, UiController, settings_resource, show_panel, show_table
from fman.url import as_human_readable, as_url
from search_file_content.engine import Options, Runner


SETTINGS_NAME = 'SearchFileContent.json'
DEFAULTS = {'name_mode': 'glob', 'content_mode': 'literal', 'recursive': True,
	'encoding': 'auto', 'max_rows': 10000, 'max_text_bytes': 16 * 1024 * 1024,
	'max_file_lines': 200, 'max_file_bytes': 50 * 1024 * 1024}
MODE_OPTIONS = (('literal', 'icons/text.svg', 'Literal text, case-insensitive'),
	('glob', 'icons/asterisk.svg', 'Glob: * any text, ? one character, [ab] a set'),
	('regex', 'icons/regex.svg', 'Regular expression (ripgrep syntax), case-insensitive'))


def settings_snapshot(values):
	if not isinstance(values, dict):
		return dict(DEFAULTS)
	result = dict(DEFAULTS)
	for name, default in DEFAULTS.items():
		value = values.get(name, default)
		if name in ('name_mode', 'content_mode'):
			fallback = 'regex' if values.get(name.replace('_mode', '_regex')) is True else default
			value = values.get(name, fallback)
			if value not in ('literal', 'glob', 'regex'):
				value = fallback
		if type(value) is type(default):
			if type(default) is int and not 1 <= value <= default:
				continue
			if name == 'encoding' and value not in ('auto', 'windows-1252'):
				continue
			result[name] = value
	return result


class SearchUI(UiController):
	pass


@dataclass(frozen=True, slots=True)
class Location:
	url: str
	path: str
	line: int
	column: int
	spans: tuple


class SearchSession:
	def __init__(self, owner, pane, root, settings):
		self.owner, self.pane, self.root = owner, pane, root
		panes = pane.window.get_panes()
		pane_side = 'left' if not panes or pane is panes[0] else 'right'
		self.unsubscribe_path = None
		self.settings = settings
		self.runner = None
		self.names_only = False
		self.table = None
		self.generation = 0
		self.save_lock = Lock()
		self.pending_settings = None
		self.saving = False
		self.panel = show_panel(owner=owner, pane=pane, rows=(
			(TextField('name', 'File Name Pattern', tooltip='Text within the name, globs matching the whole name (*.cmd;!*.bak), or a regular expression', max_width=480),
				Choice('name_mode', 'File name mode', MODE_OPTIONS, settings['name_mode'])),
			(TextField('content', 'Content Pattern', tooltip='Text within the line, a glob matched anywhere in the line (Comm*der), or a regular expression; leave empty to list files by name', max_width=480),
				Choice('content_mode', 'Content mode', MODE_OPTIONS, settings['content_mode'])),
			(Label('root', self.root_text(), 'icons/panel-' + pane_side + '.svg', pane_side.title() + ' pane'),
				Toggle('recursive', 'icons/folder-tree.svg', 'Recursive', settings['recursive'], 'Search subfolders'),
				Action('search', '', 'icons/search.svg', 'Search'),
				Action('stop', '', 'icons/square.svg', 'Stop'))),
			on_change=self.changed, on_action=self.action, on_closed=self.dispose)
		self.unsubscribe_path = pane.on_path_changed(self.refresh_root)
		if not owner.attach(self.dispose):
			self.dispose()
		else:
			self.refresh_root()

	def root_text(self):
		return self.root or 'Local folder required'

	def refresh_root(self):
		if not self.owner.active or not self.panel.is_open or self.runner is not None or self.table is not None and self.table.is_open:
			return
		path = self.pane.get_path()
		self.root = as_human_readable(path) if isinstance(path, str) and path.startswith('file://') else None
		self.panel.update(values={'root': self.root_text()}, enabled={'search': self.root is not None})

	def changed(self, values):
		updated = dict(self.settings)
		for name in ('name_mode', 'content_mode', 'recursive'):
			updated[name] = values[name]
		if updated == self.settings:
			return
		self.settings = updated
		with self.save_lock:
			self.pending_settings = tuple(updated.items())
			if self.saving:
				return
			self.saving = True
		Thread(target=self.save_preferences, name='content-search-settings', daemon=True).start()

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
					updated.pop('name_regex', None)
					updated.pop('content_regex', None)
					updated.update(values)
					save_json(SETTINGS_NAME, updated)
					notification = resource.committed(tuple(updated.items()))
				resource.publish(notification)
			except (OSError, ValueError) as error:
				try:
					self.panel.set_activity_status('Could not save search preferences: ' + str(error))
				except RuntimeError:
					pass

	def action(self, name, values):
		if name == 'stop':
			if self.runner is not None:
				self.panel.set_activity_status('Stopping')
				self.runner.stop()
			return
		if name != 'search' or self.runner is not None or self.table is not None and self.table.is_open:
			return
		self.refresh_root()
		if self.root is None:
			self.panel.set_activity_status('Content search requires a local folder.')
			return
		try:
			options = Options(self.root, values['content'], values['name'],
				**{key: values.get(key, value) for key, value in self.settings.items()})
		except ValueError as error:
			self.panel.set_activity_status(str(error))
			return
		self.generation += 1
		generation = self.generation
		runner = Runner(options, self.panel.cancelled)
		self.runner = runner
		self.names_only = options.names_only
		self.panel.update(enabled={key: False for key in ('name', 'content', 'name_mode', 'content_mode', 'recursive', 'search')})
		self.panel.set_activity_status('Validating', get_text=lambda: self.progress_text(runner))
		if not runner.start(lambda result: self.completed(generation, result)):
			self.runner = None
			self.enable_form()
			self.panel.set_activity_status('Another content search is still running or stopping.')

	def progress_text(self, runner):
		progress = runner.progress
		if runner.options.names_only:
			return '%s: %d files, %.1f s' % (progress.phase, progress.files, monotonic() - runner.started)
		return '%s: %d matching lines, %d files, %.1f s' % (
			progress.phase, progress.lines, progress.files, monotonic() - runner.started)

	def enable_form(self):
		self.panel.update(enabled={key: True for key in ('name', 'content', 'name_mode', 'content_mode', 'recursive', 'search')})
		self.refresh_root()

	def results_closed(self, generation):
		if generation == self.generation and self.owner.active and self.panel.is_open:
			self.table = None
			self.enable_form()

	def completed(self, generation, result):
		if generation != self.generation or not self.owner.active or self.panel.cancelled.is_set():
			return
		progress = result.progress
		if self.names_only:
			summary = '%s: %d files, %.1f s' % (result.status, len(result.rows), progress.elapsed)
		else:
			summary = '%s: %d matching lines, %d files, %.1f s' % (
				result.status, len(result.rows), progress.files, progress.elapsed)
		if result.reason:
			summary += ' - ' + result.reason
		try:
			self.panel.set_activity_status(summary)
			if result.validated and self.table is not None and self.table.is_open:
				self.table.close()
			if result.rows:
				rows = tuple(TableRow('%d:%d' % (generation, index), (hit.relative_path, hit.snippet),
					Location(as_url(hit.path), hit.path, hit.line, hit.column, hit.spans), ((), hit.spans))
					for index, hit in enumerate(result.rows))
				self.table = show_table(owner=self.owner, panel=self.panel, get_rows=lambda: rows,
					num_columns=2, columns_header=('File Path', 'Snippet'), title='Search File Content',
					file_path_column=0, base_path=self.root, modal=True,
					summary=self.root + ' | ' + summary,
					on_closed=lambda: self.results_closed(generation),
					get_details=lambda row, column: '%s | %d:%d' % (row.value.path, row.value.line, row.value.column)
						if row.value.line else row.value.path)
			self.runner = None
			if self.table is None or not self.table.is_open:
				self.enable_form()
		except (RuntimeError, ValueError):
			if self.panel.is_open:
				self.runner = None
				self.enable_form()
				self.panel.set_activity_status('Could not show search results.')

	def dispose(self):
		self.generation += 1
		self.owner.detach(self.dispose)
		unsubscribe, self.unsubscribe_path = self.unsubscribe_path, None
		if unsubscribe is not None:
			unsubscribe()
		if self.runner is not None:
			self.runner.stop()
		self.table = None


class SearchFileContent(DirectoryPaneCommand):
	aliases = ('Search File Content', 'Find text in files')

	def is_visible(self):
		path = self.pane.get_path()
		return isinstance(path, str) and path.startswith('file://')

	def __call__(self):
		owner = SearchUI.require_owner()
		path = self.pane.get_path()
		if not isinstance(path, str) or not path.startswith('file://'):
			show_status_message('Content search requires a local folder.', timeout_secs=3)
			return
		try:
			with settings_resource(SETTINGS_NAME).lock:
				settings = settings_snapshot(load_json(SETTINGS_NAME, default={}))
		except (OSError, ValueError) as error:
			show_status_message('Could not load search preferences: ' + str(error), timeout_secs=3)
			settings = dict(DEFAULTS)
		if owner.active:
			SearchSession(owner, self.pane, as_human_readable(path), settings)