from glob import glob
from os import makedirs, getpid, unlink, replace
from os.path import basename, dirname, exists, join
from threading import RLock

import json
import yaml

# Bundled defaults stay in plug-in folders; the user layer is UserSettings\AppSettings.yaml.
APP_SETTINGS = 'AppSettings.yaml'
SETTINGS_SUFFIX = '.yaml'

class Config:
	def __init__(self, app_settings_path=None, user_settings_dir=None):
		self._app_settings_path = app_settings_path
		self._user_settings_dir = user_settings_dir
		self._plugin_dirs = []
		self._cache = {}
		self._save_on_quit = set()
		self._preserve_on_reload = set()
		self._lock = RLock()
	def add_dir(self, dir_path):
		with self._lock:
			self._plugin_dirs.append(dir_path)
			self._reload_cache()
	def remove_dir(self, dir_path):
		with self._lock:
			self._plugin_dirs.remove(dir_path)
			self._reload_cache()
	def load_json(self, json_name, default=None, save_on_quit=False, *, preserve_on_reload=False):
		with self._lock:
			if json_name in self._cache:
				result = self._cache[json_name]
			else:
				result = load_json(self.locate(json_name))
				if result is None:
					result = default
				if result is not None:
					self._cache[json_name] = result
			if save_on_quit and result is not None:
				self._save_on_quit.add(json_name)
			if preserve_on_reload and result is not None:
				self._preserve_on_reload.add(json_name)
			return result
	def save_json(self, json_name, value=None):
		with self._lock:
			if value is None:
				value = self._cache[json_name]
			locations = self.locate(json_name)
			write_differential_json(value, locations[:-1], locations[-1])
			self._cache[json_name] = value
	def locate(self, file_name, in_dir=None):
		with self._lock:
			dirs_to_search = [in_dir] if in_dir else self._plugin_dirs
			result = [join(dir_, file_name) for dir_ in dirs_to_search]
			if in_dir is None and file_name == APP_SETTINGS and self._app_settings_path:
				result.append(self._app_settings_path)
			return result
	def create_user_settings(self, plugin_dir):
		"""Give each settings file plugin_dir ships a commented user copy, if missing."""
		if not self._user_settings_dir:
			return
		for defaults in sorted(glob(join(plugin_dir, '*' + SETTINGS_SUFFIX))):
			name = basename(defaults)
			target = self._app_settings_path if name == APP_SETTINGS else \
				join(self._user_settings_dir, name)
			if not target or exists(target):
				continue
			makedirs(dirname(target), exist_ok=True)
			try:
				with open(target, 'x', encoding='utf-8', newline='\n') as file:
					file.write(settings_template(defaults))
			except FileExistsError:
				pass
	def on_quit(self):
		with self._lock:
			for json_name in self._save_on_quit:
				try:
					self.save_json(json_name)
				except ValueError as error_computing_delta:
					# This can happen for a variety of reasons. One example:
					# When multiple instances of fman are open and another
					# instance has already written to the same json file, then
					# the delta computation may fail with a ValueError. Ignore
					# this so we can at least save the other files in
					# _save_on_quit:
					continue
				except OSError:
					# Not much we can do. Try the other JSONs at least:
					continue
	def _reload_cache(self):
		old_cache = self._cache
		self._cache = {
			name: value for name, value in old_cache.items()
			if name in self._preserve_on_reload
		}
		for json_name, old in old_cache.items():
			if json_name in self._preserve_on_reload:
				continue
			new = self.load_json(json_name)
			if isinstance(old, dict) and isinstance(new, dict):
				old.clear()
				old.update(new)
				new = old
			elif isinstance(old, list) and isinstance(new, list):
				old.clear()
				old.extend(new)
				new = old
			if new is not None:
				self._cache[json_name] = new
			elif json_name in self._save_on_quit:
				self._cache[json_name] = old

def read_json_file(path):
	try:
		with open(path, 'r', encoding='utf-8-sig') as source:
			return json.load(source)
	except UnicodeDecodeError:
		with open(path, 'r') as source:
			return json.load(source)

def is_settings_file(path):
	return str(path).lower().endswith(SETTINGS_SUFFIX)

_LIST_TEMPLATES = {
	'Key Bindings.yaml': (
		'# Key bindings: your additions and overrides; they take precedence over the bundled ones.\n'
		'# Each entry: {keys: [Shortcut], command: command_name, args: {name: value}}; args is optional.\n'
		'# "Show keyboard shortcuts" (F1) lists the active bindings; "Reload plugins" applies changes.\n'
		'# Examples (remove the leading "# " to use):\n'
		'# - {keys: [Ctrl+Alt+F], command: find_files}\n'
		'# - {keys: [Delete], command: none}  # Disables a bundled shortcut.\n'
	),
	'File Context Menu.yaml': (
		'# File context menu: your additions to the bundled menu.\n'
		'# Each entry: {command: command_name, caption: Text, args: {...}, id: section};\n'
		'# caption "-" is a separator. "Reload plugins" applies changes.\n'
		'# Example (remove the leading "# " to use):\n'
		"# - {caption: '-', id: clipboard}\n"
		'# - {command: copy_file_path, caption: Copy full path}\n'
	),
	'Folder Context Menu.yaml': (
		'# Folder (empty pane space) context menu: your additions to the bundled menu.\n'
		'# Each entry: {command: command_name, caption: Text, args: {...}, id: section};\n'
		'# caption "-" is a separator. "Reload plugins" applies changes.\n'
		'# Example (remove the leading "# " to use):\n'
		'# - {command: create_directory, caption: New folder}\n'
	),
}

def settings_template(defaults_path):
	"""User settings text: the defaults file with every option commented out."""
	name = basename(defaults_path)
	if name in _LIST_TEMPLATES:
		return _LIST_TEMPLATES[name]
	with open(defaults_path, encoding='utf-8-sig') as file:
		lines = file.read().splitlines()
	while lines and lines[0].startswith('#'):
		lines.pop(0)
	while lines and not lines[0].strip():
		lines.pop(0)
	header = [
		'# %s: your settings; they override the bundled defaults.' % name,
		'# Lines starting with "# " show the defaults. To change an option, remove "# " from',
		'# its line and from its indented lines, then edit the value. Restart to apply.',
		'',
	]
	body = [line if not line.strip() or line.lstrip().startswith('#') else '# ' + line
		for line in lines]
	return '\n'.join(header + body) + '\n'

def read_settings_file(path):
	"""Read a YAML settings file or a JSON file; a YAML file with only comments returns None."""
	if not is_settings_file(path):
		return read_json_file(path)
	with open(path, 'r', encoding='utf-8-sig') as source:
		text = source.read()
	try:
		return yaml.load(text, Loader=yaml.CSafeLoader)
	except yaml.YAMLError as error:
		raise ValueError(str(error)) from None

def load_json(paths):
	result = None
	for path in paths:
		try:
			next_value = read_settings_file(path)
		except FileNotFoundError:
			continue
		if next_value is None and is_settings_file(path):
			continue
		if result is None:
			result = type(next_value)(next_value)
			continue
		if type(next_value) != type(result):
			raise ValueError(
				'Cannot join types %s and %s.' %
				(type(next_value).__name__, type(result).__name__)
			)
		if isinstance(next_value, dict):
			result = _merge_dicts(result, next_value)
		elif isinstance(next_value, list):
			result = next_value + result
	return result

def write_differential_json(obj, paths, dest_path):
	difference = get_differential_json(obj, paths, dest_path)
	if difference is not None:
		# Some users complained about corrupted Visited Paths.json files.
		# Looking at the files, it appears that they were concurrently
		# overwritten. To avoid this, write to a temp file first, then use
		# atomic operation replace(...) to move to the destination:
		tmp_file = dest_path + '.tmp%d' % getpid()
		makedirs(dirname(tmp_file), exist_ok=True)
		try:
			if is_settings_file(dest_path):
				_write_settings(difference, dest_path, tmp_file)
			else:
				with open(tmp_file, 'w') as f:
					json.dump(difference, f, indent=2)
					f.write('\n')
			replace(tmp_file, dest_path)
		finally:
			try:
				unlink(tmp_file)
			except FileNotFoundError:
				pass

def _write_settings(value, dest_path, tmp_file):
	"""Write YAML, keeping the comments of keys and items that remain in the file."""
	from ruamel.yaml import YAML
	document = YAML()
	document.indent(mapping=2, sequence=4, offset=2)
	document.width = 4096
	try:
		with open(dest_path, 'r', encoding='utf-8-sig') as source:
			text = source.read()
	except FileNotFoundError:
		text = ''
	existing = document.load(text) if text.strip() else None
	with open(tmp_file, 'w', encoding='utf-8', newline='\n') as target:
		if existing is None and text.strip():
			target.write(text.rstrip('\n') + '\n') # A comment-only file keeps its comments
		document.dump(_merge_commented(existing, value), target)

def _merge_commented(old, new):
	if isinstance(old, dict) and isinstance(new, dict):
		for key in [key for key in old if key not in new]:
			del old[key]
		for key, value in new.items():
			old[key] = _merge_commented(old[key], value) if key in old else value
		return old
	if isinstance(old, list) and isinstance(new, list) and len(old) == len(new):
		for index, value in enumerate(new):
			old[index] = _merge_commented(old[index], value)
		return old
	return new

def get_differential_json(obj, paths, final_path):
	old_obj = load_json(paths + [final_path])
	if obj == old_obj:
		return None
	if old_obj is None:
		return obj
	else:
		if type(obj) != type(old_obj):
			raise ValueError(
				'Cannot overwrite value of type %s with different type %s.' %
				(type(old_obj).__name__, type(obj).__name__)
			)
		if isinstance(obj, dict):
			base = load_json(paths) or {}
			return _get_dict_delta(obj, base)
		elif isinstance(obj, list):
			changeable = load_json([final_path]) or []
			remainder = old_obj[len(changeable):]
			if remainder:
				if obj[-len(remainder):] != remainder:
					raise ValueError(
						"It's not possible to update list items in paths %r." %
						(paths,)
					)
				return obj[:-len(remainder)]
			else:
				return obj
		else:
			return obj

def _merge_dicts(base, override):
	result = dict(base)
	for key, value in override.items():
		if isinstance(value, dict) and isinstance(result.get(key), dict):
			result[key] = _merge_dicts(result[key], value)
		else:
			result[key] = value
	return result

def _get_dict_delta(obj, base):
	wrongly_deleted = set(base) - set(obj)
	if wrongly_deleted:
		raise ValueError(
			'Deleting keys %r is not supported.' % wrongly_deleted
		)
	result = {}
	for key, value in obj.items():
		base_value = base.get(key, object())
		if isinstance(base_value, dict) and isinstance(value, dict):
			delta = _get_dict_delta(value, base_value)
			if delta:
				result[key] = delta
		elif base_value != value:
			result[key] = value
	return result