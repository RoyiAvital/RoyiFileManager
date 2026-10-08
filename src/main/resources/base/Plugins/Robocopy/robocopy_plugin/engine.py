from contextlib import closing
from dataclasses import dataclass
import ntpath
import os
from pathlib import Path
import stat
import subprocess
from tempfile import TemporaryDirectory

from . import windows


COMMAND_UNITS = 24000
NAME_SURROGATE = 0x20000000


@dataclass(frozen=True, slots=True)
class Settings:
	threads: int = 8
	retries: int = 1
	retry_wait_seconds: int = 1
	restartable: bool = False
	unbuffered: bool = False
	log_enabled: bool = False
	open_log_on_finish: bool = False
	log_retention_count: int = 20

	@classmethod
	def load(cls, value):
		if not isinstance(value, dict):
			raise ValueError('Robocopy.json must contain an object.')
		unknown = set(value) - set(cls.__dataclass_fields__)
		if unknown:
			raise ValueError('Unknown Robocopy setting: ' + ', '.join(sorted(unknown)))
		result = cls(**value)
		for name, minimum, maximum in (('threads', 1, 32), ('retries', 0, 10),
				('retry_wait_seconds', 0, 30), ('log_retention_count', 1, 100)):
			item = getattr(result, name)
			if type(item) is not int or not minimum <= item <= maximum:
				raise ValueError('%s must be an integer from %d to %d.' % (name, minimum, maximum))
		for name in ('restartable', 'unbuffered', 'log_enabled', 'open_log_on_finish'):
			if type(getattr(result, name)) is not bool:
				raise ValueError(name + ' must be boolean.')
		if result.open_log_on_finish and not result.log_enabled:
			raise ValueError('open_log_on_finish requires log_enabled.')
		return result

	def arguments(self):
		return ('/COPY:DAT', '/XJD', '/XJF', '/NP', '/UNICODE', '/FP', '/BYTES',
			'/MT:%d' % self.threads, '/R:%d' % self.retries, '/W:%d' % self.retry_wait_seconds) + \
			(('/Z',) if self.restartable else ()) + (('/J',) if self.unbuffered else ())


def absolute_path(value):
	if not isinstance(value, str) or not value or any(char in value for char in '\x00\r\n*?"'):
		raise ValueError('Enter an absolute Windows folder path without wildcards.')
	if value.startswith(('\\\\?\\', '\\\\.\\')):
		raise ValueError('Device and extended-namespace input paths are not supported.')
	drive, tail = ntpath.splitdrive(value)
	unc = drive.startswith(('\\\\', '//')) and len(drive.replace('/', '\\').split('\\')) == 4
	local = len(drive) == 2 and drive[0].isascii() and drive[0].isalpha() and drive[1] == ':'
	if not (unc or local) or not (tail.startswith(('\\', '/')) or unc and not tail):
		raise ValueError('Use an absolute drive or UNC path, not a relative path or URL.')
	if ':' in tail or unc and ':' in drive:
		raise ValueError('Alternate streams and credentials in paths are not supported.')
	for part in tail.replace('/', '\\').split('\\'):
		if part and part not in ('.', '..') and (ntpath.isreserved(part) or part.endswith((' ', '.'))):
			raise ValueError('Unsupported Windows path component: ' + part)
	result = ntpath.normpath(value)
	if len(result.encode('utf-16-le', 'strict')) // 2 > 32760:
		raise ValueError('Path is too long.')
	return result


def from_url(value):
	if not isinstance(value, str) or not value.startswith('file://'):
		raise ValueError('Robocopy supports filesystem locations only.')
	path = value[7:].replace('/', '\\')
	if len(path) == 2 and path[1] == ':':
		path += '\\'
	return absolute_path(path)


def key(path):
	return ntpath.normcase(ntpath.normpath(path))


def contains(parent, child):
	try:
		return ntpath.commonpath((key(parent), key(child))) == key(parent)
	except ValueError:
		return False


def related(first, second):
	return contains(first, second) or contains(second, first)


def canonical(path):
	return str(Path(path).resolve(strict=False))


def identity(info):
	if not info.st_dev or not info.st_ino:
		raise ValueError('Cannot establish filesystem identity for this location.')
	return info.st_dev, info.st_ino, getattr(info, 'st_birthtime_ns', info.st_ctime_ns)


def inspect_source(path):
	info = os.lstat(path)
	if stat.S_ISLNK(info.st_mode) or getattr(info, 'st_reparse_tag', 0) & NAME_SURROGATE:
		raise ValueError('Select actual files or folders, not symbolic links or junctions: ' + path)
	if not stat.S_ISREG(info.st_mode) and not stat.S_ISDIR(info.st_mode):
		raise ValueError('Unsupported source type: ' + path)
	return info


@dataclass(frozen=True, slots=True)
class Source:
	path: str
	name: str
	is_dir: bool
	identity: tuple


@dataclass(frozen=True, slots=True)
class Job:
	source: str
	destination: str
	entries: tuple
	filenames: tuple = ()

	def arguments(self, executable, settings, move=False, log=None):
		options = ('/NODCOPY',) if self.filenames else ('/E', '/DCOPY:DAT')
		if move:
			options += ('/MOV',) if self.filenames else ('/MOVE',)
		if log:
			options += ('/UNILOG+:' + log, '/TEE')
		return (executable, self.source, self.destination, *self.filenames, *settings.arguments(), *options)


@dataclass(frozen=True, slots=True)
class Plan:
	source: str
	destination: str
	source_identity: tuple
	jobs: tuple
	settings: Settings
	move: bool


def command_units(arguments):
	return len(subprocess.list2cmdline(arguments).encode('utf-16-le')) // 2 + 1


def build_jobs(source, destination, entries, executable, settings, move=False, log=None, limit=COMMAND_UNITS, check=lambda: None):
	files = tuple(entry for entry in entries if not entry.is_dir)
	result, batch = [], []
	base = Job(source, destination, (), ('placeholder',)).arguments(executable, settings, move, log)
	base_units = command_units(base) - len('placeholder') - 1
	units = base_units
	for entry in files:
		check()
		added = command_units((entry.name,))
		if base_units + added > limit:
			raise ValueError('A selected filename cannot fit in a Robocopy command: ' + entry.name)
		if batch and units + added > limit:
			result.append(Job(source, destination, tuple(batch), tuple(item.name for item in batch)))
			batch, units = [], base_units
		batch.append(entry)
		units += added
	if batch:
		result.append(Job(source, destination, tuple(batch), tuple(item.name for item in batch)))
	for entry in entries:
		check()
		if entry.is_dir:
			result.append(Job(entry.path, ntpath.join(destination, entry.name), (entry,)))
	for job in result:
		if command_units(job.arguments(executable, settings, move, log)) > limit:
			raise ValueError('Robocopy command exceeds its safe Windows argument limit.')
	return tuple(result)


def check_names(source, entries, check):
	wanted = {entry.name.upper().casefold() for entry in entries}
	if len(wanted) != len(entries):
		raise ValueError('Ambiguous selected names differ only by case.')
	found = set()
	with closing(windows.filenames(source, check)) as names:
		for name, alternate in names:
			folded = name.upper().casefold()
			if alternate and alternate.upper().casefold() in wanted and alternate.upper().casefold() != folded:
				raise ValueError('Select the long filename, not its 8.3 alias: ' + alternate)
			if folded in wanted:
				if folded in found:
					raise ValueError('Ambiguous case-insensitive filename match: ' + name)
				found.add(folded)
	if found != wanted:
		raise ValueError('A selected name is missing or is an 8.3 alias; select its long filename again.')


def prepare(source_url, selected, destination, executable, settings, move=False, log=None, check=lambda: None):
	source = from_url(source_url)
	destination = absolute_path(destination)
	check()
	parent = inspect_source(source)
	if not stat.S_ISDIR(parent.st_mode):
		raise ValueError('The source pane no longer shows a directory.')
	parent_identity = identity(parent)
	source_path, destination_path = canonical(source), canonical(destination)
	log_path = canonical(log) if log else None
	if log_path and related(log_path, destination_path):
		raise ValueError('The destination overlaps the transfer log; disable logging for this operation.')
	entries, seen = [], set()
	for url in selected:
		check()
		path = from_url(url)
		if key(ntpath.dirname(path)) != key(source):
			raise ValueError('The selection changed location; invoke Robocopy again.')
		if path in seen:
			continue
		seen.add(path)
		name = ntpath.basename(path)
		info = inspect_source(path)
		is_dir = stat.S_ISDIR(info.st_mode)
		if not is_dir and name.startswith('-'):
			raise ValueError('Robocopy treats names beginning with a hyphen as switches: ' + name)
		entries.append(Source(path, name, is_dir, identity(info)))
	if not entries:
		raise ValueError('No file is selected.')
	if any(not entry.is_dir for entry in entries) and windows.case_sensitive(source):
		raise ValueError('Exact loose-file selection in case-sensitive folders is not supported.')
	check_names(source, entries, check)
	check()
	ancestor = Path(destination)
	while True:
		check()
		try:
			info = ancestor.stat()
		except FileNotFoundError:
			if ancestor.parent == ancestor:
				raise
			ancestor = ancestor.parent
		else:
			if not stat.S_ISDIR(info.st_mode):
				raise NotADirectoryError(str(ancestor))
			ancestor_identity = identity(info)
			break
	destination_exists = key(str(ancestor)) == key(destination)
	if key(source_path) == key(destination_path) or destination_exists and ancestor_identity[:2] == parent_identity[:2]:
		raise ValueError('Cannot transfer entries onto themselves.')
	for entry in entries:
		check()
		target = ntpath.join(destination, entry.name)
		entry_path = ntpath.join(source_path, entry.name)
		if entry.is_dir:
			entry_path, target_path = canonical(entry.path), canonical(target)
			if contains(entry_path, target_path):
				raise ValueError('Cannot transfer a directory into its own subtree: ' + entry.name)
		if destination_exists:
			try:
				target_info = os.stat(target)
			except FileNotFoundError:
				pass
			else:
				if identity(target_info)[:2] == entry.identity[:2]:
					raise ValueError('Source and destination refer to the same entry: ' + entry.name)
		if log_path and (contains(entry_path, log_path) or entry.is_dir and related(log_path, target_path)):
			raise ValueError('The transfer overlaps its own log; disable logging for this operation.')
	jobs = build_jobs(source, destination, tuple(entries), executable, settings, move, log, check=check)
	return Plan(source, destination, parent_identity, jobs, settings, move)


def recheck(plan, job, check=lambda: None):
	check()
	if identity(inspect_source(plan.source)) != plan.source_identity:
		raise ValueError('The source folder changed; start a new transfer.')
	for entry in job.entries:
		check()
		info = inspect_source(entry.path)
		if identity(info) != entry.identity or stat.S_ISDIR(info.st_mode) != entry.is_dir:
			raise ValueError('A selected source was replaced: ' + entry.name)


def remaining(entries, check=lambda: None):
	present = unknown = 0
	examples = []
	for entry in entries:
		check()
		try:
			os.lstat(entry.path)
		except FileNotFoundError:
			continue
		except OSError:
			unknown += 1
		else:
			present += 1
		if len(examples) < 10:
			examples.append(entry.path)
	return present, unknown, tuple(examples)


def exit_description(code):
	if type(code) is not int or not 0 <= code < 8:
		return 'Failed (exit %s)' % code
	parts = ['Copied files' if code & 1 else 'No files copied']
	if code & 2:
		parts.append('extra destination entries')
	if code & 4:
		parts.append('mismatches reported')
	return '; '.join(parts)


def probe(executable, settings, check=lambda: None):
	with TemporaryDirectory(prefix='robocopy-options-') as temporary:
		root = Path(temporary)
		source, destination = root / 'source', root / 'destination'
		source.mkdir()
		destination.mkdir()
		log = str(root / 'probe.txt') if settings.log_enabled else None
		if log:
			Path(log).write_bytes(b'\xff\xfe')
		for filenames in (('probe.txt',), ()):
			job = Job(str(source), str(destination), (), filenames)
			code, output = windows.run((*job.arguments(executable, settings, True, log), '/L'), check=check, timeout=15)
			if not 0 <= code < 8:
				raise OSError('Robocopy does not accept the required options (exit %d): %s' % (code, output[-1500:]))
		if log:
			text = Path(log).read_text(encoding='utf-16')
			if '\ufeff' in text:
				raise OSError('Robocopy does not append compatible Unicode logs.')