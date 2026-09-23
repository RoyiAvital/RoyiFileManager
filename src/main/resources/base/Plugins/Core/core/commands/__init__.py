from collections.abc import Mapping
from core.commands.util import get_program_files, get_program_files_x86, \
	is_hidden
from core.fileoperations import CopyFiles, MoveFiles
from core.github import find_repos, GitHubRepo
from core.os_ import open_terminal_in_directory, open_native_file_manager, \
	get_popen_kwargs_for_opening
from core.util import strformat_dict_values, listdir_absolute, is_parent
from core.quicksearch_matchers import contains_chars, \
	contains_chars_after_separator
from core.quick_view import switch_quick_view as _switch_quick_view
from fman import *
from fman.fs import exists, touch, mkdir, is_dir, delete, samefile, copy, \
	iterdir, resolve, prepare_copy, prepare_move, prepare_delete, \
	FileSystem, prepare_trash, query, makedirs, notify_file_added
from fman.impl.util import get_user
from fman.url import splitscheme, as_url, join, basename, as_human_readable, \
	dirname, relpath, normalize
from html import escape
from io import UnsupportedOperation
from itertools import chain
from os import strerror
from os.path import basename, pardir
from pathlib import PurePath
from PyQt5.QtCore import QUrl
from PyQt5.QtGui import QDesktopServices
from subprocess import Popen, DEVNULL, PIPE
from tempfile import TemporaryDirectory
from urllib.error import URLError

import errno
import fman.fs
import json
import os
import os.path
import re
import sys

from .goto import *

class About(ApplicationCommand):
	def __call__(self):
		from fman.impl.application_context import get_application_context
		version = get_application_context().build_settings['version']
		show_alert(
			'Version: %s<br>API Version: 0.0.0<br>'
			'Project: <a href="https://github.com/RoyiAvital/RoyiFileManager">'
			'https://github.com/RoyiAvital/RoyiFileManager</a><br>'
			'Documentation: <a href="https://royiavital.github.io/RoyiFileManager">'
			'https://royiavital.github.io/RoyiFileManager</a>'
			% escape(version)
		)

class Help(ApplicationCommand):

	aliases = ('Help', 'Show keyboard shortcuts', 'Show key bindings')

	def __call__(self):
		from fman.impl.application_context import get_application_context
		get_application_context().show_shortcuts()

class MoveCursorDown(DirectoryPaneCommand):
	def __call__(self, toggle_selection=False):
		self.pane.move_cursor_down(toggle_selection)

class MoveCursorUp(DirectoryPaneCommand):
	def __call__(self, toggle_selection=False):
		self.pane.move_cursor_up(toggle_selection)

class MoveCursorHome(DirectoryPaneCommand):
	def __call__(self, toggle_selection=False):
		self.pane.move_cursor_home(toggle_selection)

class MoveCursorEnd(DirectoryPaneCommand):
	def __call__(self, toggle_selection=False):
		self.pane.move_cursor_end(toggle_selection)

class MoveCursorPageUp(DirectoryPaneCommand):
	def __call__(self, toggle_selection=False):
		self.pane.move_cursor_page_up(toggle_selection)

class MoveCursorPageDown(DirectoryPaneCommand):
	def __call__(self, toggle_selection=False):
		self.pane.move_cursor_page_down(toggle_selection)

class ToggleSelection(DirectoryPaneCommand):
	def __call__(self):
		file_under_cursor = self.pane.get_file_under_cursor()
		if file_under_cursor:
			self.pane.toggle_selection(file_under_cursor)

class MoveToTrash(DirectoryPaneCommand):

	aliases = ('Delete', 'Move to trash', 'Move to recycle bin')

	def __call__(self, urls=None):
		if urls is None:
			urls = self.get_chosen_files()
		if not urls:
			show_alert('No file is selected!')
			return
		description = _describe(urls, 'these %d files')
		trash = 'Recycle Bin' if PLATFORM == 'Windows' else 'Trash'
		msg = "Do you really want to move %s to the %s?" % (description, trash)
		if show_alert(msg, YES | NO, YES) & YES:
			submit_task(_Delete(urls, prepare_trash, prepare_delete))
	def is_visible(self):
		return bool(self.pane.get_file_under_cursor())

class DeletePermanently(DirectoryPaneCommand):
	def __call__(self, urls=None):
		if urls is None:
			urls = self.get_chosen_files()
		if not urls:
			show_alert('No file is selected!')
			return
		description = _describe(urls, 'these %d items')
		message = \
			"Do you really want to PERMANENTLY delete %s? This action cannot " \
			"be undone!" % description
		if show_alert(message, YES | NO, YES) & YES:
			submit_task(_Delete(urls, prepare_delete))

class _Delete(Task):
	def __init__(self, urls, prepare_fn, fallback=None):
		super().__init__('Deleting ' + _describe(urls))
		self._urls = urls
		self._num_urls_prepared = 0
		self._prepare_fn = prepare_fn
		self._fallback = fallback
		self._tasks = []
	def __call__(self):
		try:
			self._gather_tasks()
		except (UnsupportedOperation, NotImplementedError):
			failing_url = self._urls[self._num_urls_prepared]
			self.show_alert(
				'Deleting files in %s is not supported.'
				% splitscheme(failing_url)[0]
			)
			return
		ignore_errors = False
		for i, task in enumerate(self._tasks):
			self.check_canceled()
			try:
				self.run(task)
			except FileNotFoundError:
				# Perhaps the file has already been deleted.
				pass
			except OSError as e:
				if ignore_errors:
					continue
				text = task.get_title()
				message = 'Error ' + text[0].lower() + text[1:]
				reason = e.strerror or ''
				if not reason and e.errno is not None:
					reason = strerror(e.errno)
				if reason:
					message += ': ' + reason
				message += '.'
				is_last = i == len(self._tasks) - 1
				if is_last:
					self.show_alert(message)
				else:
					message += ' Do you want to continue?'
					choice = show_alert(message, YES | NO | YES_TO_ALL)
					if choice & NO:
						break
					if choice & YES_TO_ALL:
						ignore_errors = True
	def _gather_tasks(self):
		for url in self._urls:
			try:
				self._prepare(url, self._prepare_fn)
			except (NotImplementedError, UnsupportedOperation):
				if self._fallback is None:
					raise
				self._prepare(url, self._fallback)
			self._num_urls_prepared += 1
		self.set_size(sum(t.get_size() for t in self._tasks))
	def _prepare(self, url, prepare_fn):
		url_tasks = []
		for task in prepare_fn(url):
			self.check_canceled()
			url_tasks.append(task)
			if task.get_size():
				num = len(self._tasks) + len(url_tasks)
				self.set_text('Preparing to delete {:,} files.'.format(num))
		self._tasks.extend(url_tasks)

def _describe(files, template='%d files'):
	if len(files) == 1:
		return basename(files[0])
	return template % len(files)

class GoUp(DirectoryPaneCommand):

	aliases = ('Go up', 'Go to parent directory')

	def __call__(self):
		go_up(self.pane)

def go_up(pane):
	path_before = pane.get_path()
	def callback():
		path_now = pane.get_path()
		# Only move the cursor if we actually changed directories; For
		# instance, we don't want to move the cursor if the user presses
		# Backspace while at drives:// and the cursor is already at
		# drives://C:
		if path_now != path_before:
			# Consider: The user is in zip:///Temp.zip and invokes GoUp.
			# This takes us to file:///. We want to place the cursor at
			# file:///Temp.zip. "Switch" schemes to make this happen:
			cursor_dest = splitscheme(path_now)[0] + \
						  splitscheme(path_before)[1]
			try:
				pane.place_cursor_at(cursor_dest)
			except ValueError as dest_doesnt_exist:
				pane.move_cursor_home()
	parent_dir = dirname(path_before)
	try:
		pane.set_path(parent_dir, callback)
	except FileNotFoundError:
		# This for instance happens when the user pressed backspace when at
		# file:/// on Unix.
		pass

class Open(DirectoryPaneCommand):
	def __call__(self, url=None):
		if url is None:
			url = self.pane.get_file_under_cursor()
		if url:
			try:
				url_is_dir = is_dir(url)
			except OSError as e:
				show_alert(
					'Could not read from %s (%s)' % (as_human_readable(url), e)
				)
				return
			# Use `run_command` to delegate the actual opening. This makes it
			# possible for plugins to modify the default open behaviour by
			# implementing DirectoryPaneListener#on_command(...).
			if url_is_dir:
				if PLATFORM == 'Mac' and url.endswith('.app'):
					dialogs = load_json('Core Dialogs.json', default={})
					if not dialogs.get('open_app_hint_shown', False):
						show_alert(
							'Quick tip: Apps in macOS are directories. When '
							'you press '
							'<span style="color: white;">Enter</span>, '
							'RoyiFileManager therefore browses them. If you want to '
							'launch the app instead, press '
							'<span style="color: white;">Cmd+Enter</span>.'
						)
						dialogs['open_app_hint_shown'] = True
						save_json('Core Dialogs.json')
						return
				self.pane.run_command('open_directory', {'url': url})
			else:
				self.pane.run_command('open_file', {'url': url})
		else:
			show_alert('No file is selected!')

class OpenListener(DirectoryPaneListener):
	def on_doubleclicked(self, file_url):
		self.pane.run_command('open', {'url': file_url})

class OpenDirectory(DirectoryPaneCommand):
	def __call__(self, url):
		from fman.impl.navigation import current_request
		request = current_request()
		try:
			url_is_dir = is_dir(url)
		except OSError as e:
			if request:
				request.fail(e)
				return
			show_alert(
				'Could not read from %s (%s)' % (as_human_readable(url), e)
			)
			return
		if url_is_dir:
			try:
				self.pane.set_path(url, onerror=None)
			except PermissionError as error:
				if request:
					request.fail(error)
					return
				show_alert(
					'Access to "%s" was denied.' % as_human_readable(url)
				)
		else:
			def callback():
				try:
					self.pane.place_cursor_at(url)
				except ValueError as file_disappeared:
					if request:
						raise
			self.pane.set_path(dirname(url), callback=callback, onerror=None)
	def is_visible(self):
		return False

class OpenFile(DirectoryPaneCommand):
	def __call__(self, url):
		_open_files([url], self.pane)
	def is_visible(self):
		return False

def _open_files(urls, pane):
	local_file_paths = []
	for url in urls:
		# On Windows, CMD can handle mapped drives Z:\ but not UNC paths
		# //192.168.0.2. If the former maps to the latter, then CMD fails to
		# run .bat files in that location. So only resolve if absolutely
		# necessary, i.e. when not a file:// URL:
		if not _is_file_url(url):
			try:
				url = resolve(url)
			except FileNotFoundError:
				# No sense to try to open a file that does not exist.
				continue
			except OSError as e:
				# Not all OSErrors need prevent us from opening the file.
				# So only skip this file if it does not exist:
				if e.errno == errno.ENOENT:
					continue
		scheme = splitscheme(url)[0]
		if scheme != 'file://':
			show_alert(
				'Opening files from %s is not supported. If you are a plugin '
				'developer, you can implement this with '
				'DirectoryPaneListener#on_command(...).' % scheme
			)
			return
		# Use as_human_readable(...) instead of the result from splitscheme(...)
		# above to get backslashes on Windows:
		local_file_paths.append(as_human_readable(url))
	_open_local_files(local_file_paths, pane)

def _is_file_url(url):
	return splitscheme(url)[0] == 'file://'

def _open_local_files(paths, pane):
	if PLATFORM == 'Windows':
		_open_local_files_win(paths, pane)
	elif PLATFORM == 'Mac':
		_open_local_files_mac(paths)
	else:
		assert PLATFORM == 'Linux'
		_open_local_files_linux(paths)

def _open_local_files_win(paths, pane):
	# Whichever implementation is used here, it should support:
	#  * C:\picture.jpg
	#  * C:\notepad.exe
	#  * C:\a & b.txt
	#  * C:\batch.bat should print the current dir:
	#        echo %cd%
	#        pause
	#  * \\server\share\picture.jpg
	#  * D:\Book.pdf
	#  * \\cryptomator-vault\app.exe
	for path in paths:
		if path.endswith('.lnk'):
			import win32com.client
			shell = win32com.client.Dispatch("WScript.Shell")
			shortcut = shell.CreateShortCut(path)
			target_url = as_url(shortcut.TargetPath)
			if is_dir(target_url):
				pane.set_path(target_url)
				return
		try:
			from win32api import ShellExecute
			from win32con import SW_SHOWNORMAL
			cwd = os.path.dirname(path)
			ShellExecute(0, None, path, None, cwd, SW_SHOWNORMAL)
		except OSError:
			# This for instance happens when the file is an .exe that requires
			# Admin privileges, but the user cancels the UAC "do you want to run
			# this file?" dialog.
			pass

def _open_local_files_mac(paths):
	non_executables = []
	for path in paths:
		try:
			_run_executable(path)
		except (OSError, ValueError):
			non_executables.append(path)
	if non_executables:
		try:
			Popen(['open'] + non_executables, **_quiet)
		except OSError:
			pass

def _open_local_files_linux(paths):
	for path in paths:
		try:
			_run_executable(path)
		except (OSError, ValueError):
			try:
				Popen(['xdg-open', path], **_quiet)
			except Exception as e:
				raise e from None

def _run_executable(path):
	Popen([path], cwd=os.path.dirname(path), **_quiet)

_quiet = {'stdout': DEVNULL, 'stderr': DEVNULL}

class OpenSelectedFiles(DirectoryPaneCommand):
	def __call__(self):
		file_under_cursor = self.pane.get_file_under_cursor()
		selected_files = self.pane.get_selected_files()
		if file_under_cursor in selected_files:
			_open_files(selected_files, self.pane)
		else:
			_open_files([file_under_cursor], self.pane)
	def is_visible(self):
		return bool(self.get_chosen_files())

class OpenWithEditor(DirectoryPaneCommand):

	aliases = ('Edit',)
	role = 'editor'

	def __call__(self, url=None):
		from core.text_editor import open_file
		if url is None:
			url = self.pane.get_file_under_cursor()
		open_file(url, self.role)

class ViewFile(OpenWithEditor):
	aliases = ('View',)
	role = 'viewer'

class SetTextEditor(DirectoryPaneCommand):
	aliases = ('Set text editor',)
	role = 'editor'

	def __call__(self):
		from core.text_editor import configure
		configure(self.role)

class SetTextViewer(SetTextEditor):
	aliases = ('Set text viewer',)
	role = 'viewer'

class SetFileComparator(DirectoryPaneCommand):
	aliases = ('Set file comparator',)
	role = 'file'

	def __call__(self):
		from core.comparator import configure
		configure(self.role)

class SetFolderComparator(SetFileComparator):
	aliases = ('Set folder comparator',)
	role = 'folder'

class CompareFiles(DirectoryPaneCommand):
	aliases = ('Compare files',)
	role = 'file'

	def __call__(self):
		from core.comparator import compare
		compare(self.pane, self.role)

class CompareFolders(CompareFiles):
	aliases = ('Compare folders',)
	role = 'folder'

def _show_app_open_dialog(caption):
	return show_file_open_dialog(
		caption, _get_applications_directory(),
		_PLATFORM_APPLICATIONS_FILTER[PLATFORM]
	)

_PLATFORM_APPLICATIONS_FILTER = {
	'Mac': 'Applications (*.app)',
	'Windows': 'Applications (*.exe)',
	'Linux': 'Applications (*)'
}

def _get_applications_directory():
	if PLATFORM == 'Mac':
		return '/Applications'
	elif PLATFORM == 'Windows':
		result = get_program_files()
		if not os.path.exists(result):
			result = get_program_files_x86()
		if not os.path.exists(result):
			result = PurePath(sys.executable).anchor
		return result
	elif PLATFORM == 'Linux':
		return '/usr/bin'
	raise NotImplementedError(PLATFORM)

def _prompt_for_file(pane, caption):
	file_under_cursor = pane.get_file_under_cursor()
	default_name = ''
	if file_under_cursor:
		try:
			file_is_dir = is_dir(file_under_cursor)
		except OSError:
			file_is_dir = False
		if not file_is_dir:
			default_name = basename(file_under_cursor)
	selection_end = _find_extension_start(default_name)
	file_name, ok = show_prompt(
		caption, default_name, selection_end=selection_end
	)
	if ok and file_name:
		return join(pane.get_path(), file_name)

def _touch_file_if_missing(file_url, unsupported_message):
	"""Return True if created, False if present, or None after an alert."""
	if exists(file_url):
		return False
	try:
		touch(file_url)
	except PermissionError:
		show_alert(
			"You do not have enough permissions to create %s."
			% as_human_readable(file_url)
		)
		return None
	except NotImplementedError:
		show_alert(unsupported_message)
		return None
	except OSError as error:
		show_alert(
			'Could not create %s: %s' % (
				as_human_readable(file_url), error.strerror or str(error)
			)
		)
		return None
	return True

def _place_cursor_at(pane, file_url):
	try:
		pane.place_cursor_at(file_url)
	except ValueError:
		# This can happen when the file is hidden. Eg .bashrc on Linux.
		pass

class NewEmptyFile(DirectoryPaneCommand):

	aliases = ('New file', 'Create file', 'New empty file', 'Create empty file', 'Touch')

	def __call__(self):
		file_url = _prompt_for_file(self.pane, 'Enter file name to create:')
		if file_url is None:
			return
		if _touch_file_if_missing(
			file_url, 'Sorry, creating a file is not supported here.'
		):
			_place_cursor_at(self.pane, file_url)
	def is_visible(self):
		scheme = splitscheme(self.pane.get_path())[0]
		return _fs_implements(scheme, 'touch')

class CreateAndEditFile(OpenWithEditor):

	aliases = ('Edit new file', 'Create and edit file')

	def __call__(self, url=None):
		file_to_edit = _prompt_for_file(
			self.pane, 'Enter file name to create/edit:'
		)
		if file_to_edit is None:
			return
		creation_result = _touch_file_if_missing(
			file_to_edit,
			'Sorry, creating a file for editing is not supported here.'
		)
		if creation_result is None:
			return
		_place_cursor_at(self.pane, file_to_edit)
		super().__call__(file_to_edit)

def _find_extension_start(file_name, start=0):
	for dual_extension in ('.pkg.tar.xz', '.tar.xz', '.tar.gz'):
		if file_name.endswith(dual_extension):
			return len(file_name) - len(dual_extension)
	try:
		return file_name.rindex('.', start)
	except ValueError as not_found:
		return None

class _TreeCommand(DirectoryPaneCommand):
	def __call__(self, files=None, dest_dir=None):
		if files is None:
			files = self.get_chosen_files()
			src_dir = self.pane.get_path()
		else:
			# This for instance happens in Drag and Drop operations.
			src_dir = None
		if dest_dir is None:
			dest_dir = _get_opposite_pane(self.pane).get_path()
		proceed = self._confirm_tree_operation(files, dest_dir, src_dir)
		if proceed:
			dest_dir, dest_name = proceed
			makedirs(dest_dir, exist_ok=True)
			self._call(files, dest_dir, dest_name)
	def _call(self, files, dest_dir, dest_name=None):
		raise NotImplementedError()
	@classmethod
	def _confirm_tree_operation(
		cls, files, dest_dir, src_dir, ui=fman, fs=fman.fs
	):
		if not files:
			ui.show_alert('No file is selected!')
			return
		selection_start = 0
		selection_end = None # Select everything
		if len(files) == 1:
			file_, = files
			dest_name = basename(file_)
			files_descr = '"%s"' % dest_name
			try:
				exists_and_is_dir = fs.is_dir(file_)
			except FileNotFoundError:
				exists_and_is_dir = False
			except OSError as e:
				ui.show_alert(
					'Could not read from %s (%s)' %
					(as_human_readable(file_), e)
				)
				return
			if exists_and_is_dir:
				"""
				There is only one reasonable course of action when the file to
				be copied is a dir: Suggest the parent directory and copy the
				dir into it as a folder. The alternative would be to suggest the
				destination directory and copy the dir's *contents*. But this 
				brings a host of problems: Say we copy folder src/ to (inside) 
				dst/ once, and then a second time. Then src/dst is suggested. It
				already exists. This leads to the remaining logic in this class
				copying to src/dst/dst instead of overwriting the previously 
				copied files.
				
				Another problem with the alternative approach would be that the
				user may copy a folder with a lot of files, and manually type in
				an existing destination directory. If we copied the folder's 
				contents, then the user may end up with thousands of files 
				scattered all over the existing directory when he intended for 
				them to be contained in a separate, single directory.
				
				Finally, the alternative approach might not be able to preserve
				the directory's permissions when an existing destination folder
				is supplied.
				"""
				suggested_dst = as_human_readable(dest_dir)
			else:
				dest_url = join(dest_dir, dest_name)
				suggested_dst, selection_start, selection_end = \
					get_dest_suggestion(dest_url)
		else:
			files_descr = '%d files' % len(files)
			suggested_dst = as_human_readable(dest_dir)
		message = '%s %s to' % (cls._verb().capitalize(), files_descr)
		dest, ok = ui.show_prompt(
			message, suggested_dst, selection_start, selection_end
		)
		if dest and ok:
			dest_url = _from_human_readable(dest, dest_dir, src_dir)
			if fs.exists(dest_url):
				try:
					dest_is_dir = fs.is_dir(dest_url)
				except OSError as e:
					ui.show_alert('Could not read from %s (%s)' % (dest, e))
					return
				if dest_is_dir:
					if len(files) == 1 and fs.samefile(dest_url, files[0]):
						# This happens when renaming a/ -> A/ on
						# case-insensitive file systems.
						return _split(dest_url)
					for file_ in files:
						if is_parent(file_, dest_url, fs):
							ui.show_alert(
								'You cannot %s a file to itself!' % cls._verb()
							)
							return
					return dest_url, None
				else:
					if len(files) == 1:
						return _split(dest_url)
					else:
						ui.show_alert(
							'You cannot %s multiple files to a single file!' %
							cls._verb()
						)
			else:
				if len(files) == 1:
					return _split(dest_url)
				else:
					choice = ui.show_alert(
						'%s does not exist. Do you want to create it '
						'as a directory and %s the files there?' %
						(as_human_readable(dest_url), cls._verb()),
						YES | NO, YES
					)
					if choice & YES:
						return dest_url, None
	@classmethod
	def _verb(cls):
		return cls.__name__.lower()
	def is_visible(self):
		return bool(self.pane.get_file_under_cursor())

def get_dest_suggestion(dst_url):
	scheme = splitscheme(dst_url)[0]
	if scheme == 'file://':
		sep = os.sep
		suggested_dst = as_human_readable(dst_url)
		offset = 0
	else:
		sep = '/'
		suggested_dst = dst_url
		offset = len(scheme)
	try:
		last_sep = suggested_dst.rindex(sep, offset)
	except ValueError as no_sep:
		selection_start = offset
	else:
		selection_start = last_sep + 1
	selection_end = _find_extension_start(suggested_dst, selection_start)
	return suggested_dst, selection_start, selection_end

def _get_opposite_pane(pane):
	panes = pane.window.get_panes()
	return panes[(panes.index(pane) + 1) % len(panes)]

def _from_human_readable(path_or_url, dest_dir, src_dir):
	try:
		splitscheme(path_or_url)
	except ValueError as no_scheme:
		dest_scheme, dest_dir_path = splitscheme(dest_dir)
		if src_dir:
			# Treat dest as relative to src_dir:
			src_scheme, src_path = splitscheme(src_dir)
			dest_path = PurePath(src_path, path_or_url).as_posix()
		else:
			dest_path = PurePath(dest_dir_path, path_or_url).as_posix()
		path_or_url = dest_scheme + dest_path
	return path_or_url

def _split(url):
	scheme, tail = splitscheme(url)
	head, tail = re.match('(/*)(.*?)$', tail).groups()
	if '/' in tail:
		h2, tail = tail.rsplit('/', 1)
		head += h2
	return scheme + head, tail

class Copy(_TreeCommand):
	def _call(self, files, dest_dir, dest_name=None):
		submit_task(CopyFiles(files, dest_dir, dest_name))

class Move(_TreeCommand):
	def _call(self, files, dest_dir, dest_name=None):
		submit_task(MoveFiles(files, dest_dir, dest_name))

class DragAndDropListener(DirectoryPaneListener):
	def on_files_dropped(self, file_urls, dest_dir, is_copy_not_move):
		command = self._get_command(file_urls, dest_dir, is_copy_not_move)
		self.pane.run_command(
			command, {'files': file_urls, 'dest_dir': dest_dir}
		)
	def _get_command(self, file_urls, dest_dir, is_copy_not_move):
		schemes = set(splitscheme(url)[0] for url in file_urls)
		src_scheme = next(iter(schemes)) if len(schemes) == 1 else ''
		dest_scheme = splitscheme(dest_dir)[0]
		if src_scheme != dest_scheme:
			# The default value for `is_copy_not_move` is False. But consider
			# the case where the user drags a file from a Zip archive to the
			# local file system. In this case, `is_copy_not_move` might indicate
			# "move" simply because it's the default. But most likely, the user
			# simply wants to extract the file and not also remove it from the
			# Zip file. Respect this:
			is_copy_not_move = True
		return 'copy' if is_copy_not_move else 'move'

class Symlink(_TreeCommand):

	aliases = ('Symlink', 'Create symbolic link')

	def is_visible(self):
		if not super().is_visible():
			return False
		return _is_file_url(self.pane.get_path()) and \
			   _is_file_url(_get_opposite_pane(self.pane).get_path())

	def __call__(self):
		src_url = self.pane.get_path()
		if not _is_file_url(src_url):
			self._refuse()
			return
		dest_url = _get_opposite_pane(self.pane).get_path()
		if not _is_file_url(dest_url):
			self._refuse()
			return
		super().__call__()

	def _call(self, files, dest_dir, dest_name=None):
		ignore_exists = False
		for i, f_url in enumerate(files):
			dest_url = join(dest_dir, dest_name or basename(f_url))
			if not _is_file_url(f_url) or not _is_file_url(dest_url):
				self._refuse()
				return
			f_path = as_human_readable(f_url)
			dest_path = as_human_readable(dest_url)
			try:
				os.symlink(f_path, dest_path, is_dir(f_url))
			except FileExistsError:
				if ignore_exists:
					continue
				has_more = i < len(files) - 1
				if has_more:
					answer = show_alert(
						"%s exists and cannot be symlinked. Continue?"
						% basename(f_url),
						YES | NO | YES_TO_ALL, YES
					)
					if answer & YES_TO_ALL:
						ignore_exists = True
					elif answer & NO:
						break
				else:
					show_alert(
						"%s exists and cannot be symlinked." % basename(f_url)
					)
			else:
				notify_file_added(dest_url)

	def _refuse(self):
		show_alert('Sorry, can only create symlinks between local files.')

class Rename(DirectoryPaneCommand):
	def __call__(self):
		file_under_cursor = self.pane.get_file_under_cursor()
		if file_under_cursor:
			try:
				file_is_dir = is_dir(file_under_cursor)
			except OSError as e:
				show_alert(
					'Could not read from %s (%s)' %
					(as_human_readable(file_under_cursor), e)
				)
				return
			if file_is_dir:
				selection_end = None
			else:
				file_name = basename(file_under_cursor)
				selection_end = _find_extension_start(file_name)
			self.pane.edit_name(file_under_cursor, selection_end=selection_end)
		else:
			show_alert('No file is selected!')
	def is_visible(self):
		return bool(self.pane.get_file_under_cursor())

class RenameListener(DirectoryPaneListener):
	def on_name_edited(self, file_url, new_name):
		old_name = basename(file_url)
		if not new_name or new_name == old_name:
			return
		is_relative = \
			os.sep in new_name or new_name in (pardir, '.') \
			or (PLATFORM == 'Windows' and '/' in new_name)
		if is_relative:
			show_alert(
				'Relative paths are not supported. Please use Move (F6) '
				'instead.'
			)
			return
		new_url = join(dirname(file_url), new_name)
		if exists(new_url):
			# Don't show dialog when "Foo" was simply renamed to "foo":
			if not samefile(new_url, file_url):
				show_alert(new_name + ' already exists!')
				return
		submit_task(_Rename(self.pane, file_url, new_url))

class _Rename(Task):
	def __init__(self, pane, src_url, dst_url):
		self._pane = pane
		self._src_url = src_url
		self._dst_url = dst_url
		super().__init__('Renaming ' + basename(src_url))
	def __call__(self):
		self.set_text('Preparing...')
		tasks = list(prepare_move(self._src_url, self._dst_url))
		self.set_size(sum(t.get_size() for t in tasks))
		try:
			for task in tasks:
				self.check_canceled()
				self.run(task)
		except OSError as e:
			if isinstance(e, PermissionError):
				message = 'Access was denied trying to rename %s to %s.'
			else:
				message = 'Could not rename %s to %s.'
			old_name = basename(self._src_url)
			new_name = basename(self._dst_url)
			self.show_alert(message % (old_name, new_name))
		else:
			try:
				self._pane.place_cursor_at(self._dst_url)
			except ValueError as file_disappeared:
				pass

class CreateDirectory(DirectoryPaneCommand):

	aliases = (
		'New folder', 'Create folder', 'New directory', 'Create directory'
	)

	def __call__(self):
		file_under_cursor = self.pane.get_file_under_cursor()
		if file_under_cursor:
			default = basename(file_under_cursor).split('.', 1)[0]
		else:
			default = ''
		name, ok = show_prompt("New folder (directory)", default)
		if ok and name:
			# Support recursive creation of directories:
			if PLATFORM == 'Windows':
				name = name.replace('\\', '/')
			base_url = self.pane.get_path()
			dir_url = join(base_url, name)
			try:
				makedirs(dir_url)
			except FileExistsError:
				show_alert("A file with this name already exists!")
			# Use normalize(...) instead of resolve(...) to avoid the following
			# problem: Say c/ is a symlink to a/b/. We're inside c/ and create
			# d. Then # resolve(c/d) would give a/b/d and the relative path
			# further down # would be ../a/b/d. We could not place the cursor at
			# that. If on # the other hand, we use normalize(...), then we
			# compute the relpath from c -> c/d, which does work.
			effective_url = normalize(dir_url)
			select = relpath(effective_url, base_url).split('/')[0]
			if select != '..':
				try:
					self.pane.place_cursor_at(join(base_url, select))
				except ValueError as dir_disappeared:
					pass
	def is_visible(self):
		fs = splitscheme(self.pane.get_path())[0]
		return _fs_implements(fs, 'mkdir')

def _fs_implements(scheme, method_name):
	# Using query(...) in this way is quite hacky, but works:
	method = query(scheme + method_name, '__getattr__')
	return method.__func__ is not getattr(FileSystem, method_name)

class OpenTerminal(DirectoryPaneCommand):

	aliases = (
		'Terminal', 'Shell', 'Open terminal', 'Open shell'
	)

	def __call__(self):
		scheme, path = splitscheme(self.pane.get_path())
		if scheme != 'file://':
			show_alert(
				"Can currently open the terminal only in local directories."
			)
			return
		open_terminal_in_directory(path)

class OpenNativeFileManager(DirectoryPaneCommand):
	def __call__(self):
		url = self.pane.get_path()
		scheme = splitscheme(url)[0]
		if scheme != 'file://':
			if PLATFORM == 'Mac':
				native_fm = 'Finder'
			elif PLATFORM == 'Windows':
				native_fm = 'Explorer'
			else:
				native_fm = 'your native file manager'
			show_alert("Cannot open %s in %s" % (native_fm, scheme))
			return
		open_native_file_manager(as_human_readable(url))

class CopyPathsToClipboard(DirectoryPaneCommand):
	def __call__(self):
		to_copy = self.get_chosen_files() or [self.pane.get_path()]
		files = '\n'.join(to_copy)
		clipboard.clear()
		clipboard.set_text('\n'.join(map(as_human_readable, to_copy)))
		_report_clipboard_action('Copied', to_copy, ' to the clipboard', 'path')

def _report_clipboard_action(verb, files, suffix='', ftype='file'):
	num = len(files)
	first_file = as_human_readable(files[0])
	if num == 1:
		message = '%s %s%s' % (verb, first_file, suffix)
	else:
		plural = 's' if num > 2 else ''
		message = '%s %s and %d other %s%s%s' % \
				  (verb, first_file, num - 1, ftype, plural, suffix)
	show_status_message(message, timeout_secs=3)

class CopyToClipboard(DirectoryPaneCommand):
	def __call__(self):
		files = self.get_chosen_files()
		if files:
			clipboard.copy_files(files)
			_report_clipboard_action('Copying', files)
		else:
			show_alert('No file is selected!')
	def is_visible(self):
		return bool(self.pane.get_file_under_cursor())

class Cut(DirectoryPaneCommand):
	def __call__(self):
		if PLATFORM == 'Mac':
			show_alert(
				"Sorry, macOS doesn't support cutting files. Please press "
				"⌘-C (copy) followed by ⌘-⌥-V (move)."
			)
			return
		files = self.get_chosen_files()
		if files:
			clipboard.cut_files(files)
			_report_clipboard_action('Cutting', files)
		else:
			show_alert('No file is selected!')
	def is_visible(self):
		return bool(self.pane.get_file_under_cursor())

class Paste(DirectoryPaneCommand):
	def __call__(self):
		files = clipboard.get_files()
		if not files:
			return
		if clipboard.files_were_cut():
			self.pane.run_command('paste_cut')
		else:
			dest = self.pane.get_path()
			self.pane.run_command('copy', {'files': files, 'dest_dir': dest})
	def is_visible(self):
		return bool(clipboard.get_files())

class PasteCut(DirectoryPaneCommand):
	def __call__(self):
		files = clipboard.get_files()
		if not any(map(exists, files)):
			# This can happen when the paste-cut has already been performed.
			return
		dest_dir = self.pane.get_path()
		self.pane.run_command('move', {
			'files': files,
			'dest_dir': dest_dir
		})

class SelectAll(DirectoryPaneCommand):
	def __call__(self):
		self.pane.select_all()

class Deselect(DirectoryPaneCommand):
	def __call__(self):
		self.pane.clear_selection()

class InvertSelection(DirectoryPaneCommand):
	def __call__(self, *args, **kwargs):
		url = self.pane.get_path()
		all_files = (join(url, fname) for fname in iterdir(url))
		to_deselect = set(self.pane.get_selected_files())
		to_select = (f for f in all_files if f not in to_deselect)
		self.pane.deselect(to_deselect)
		self.pane.select(to_select)

class ToggleHiddenFiles(DirectoryPaneCommand):

	aliases = ('Toggle hidden files', 'Show / hide hidden files')

	def __call__(self):
		_toggle_hidden_files(self.pane, not _is_showing_hidden_files(self.pane))

class InitHiddenFilesFilter(DirectoryPaneListener):
	def __init__(self, *args, **kwargs):
		super().__init__(*args, **kwargs)
		# We need to do this somewhere when fman starts. We can't do it in the
		# __init__ of ToggleHiddenFiles, because fman instantiates commands
		# lazily.
		if not _is_showing_hidden_files(self.pane):
			_toggle_hidden_files(self.pane, False)
		else:
			self.pane._set_hidden_files_shown(True)

def _is_showing_hidden_files(pane):
	return _get_pane_info(pane)['show_hidden_files']

def _toggle_hidden_files(pane, value):
	if value:
		pane._remove_filter(_hidden_file_filter)
	else:
		pane._add_filter(_hidden_file_filter)
	_get_pane_info(pane)['show_hidden_files'] = value
	# Consider a scenario where the user:
	#  1. shows hidden files, then
	#  2. reloads plugins.
	# The second step reloads the settings. This reverts 'Panes.json' to the
	# version that was last saved. If we only relied on the save_on_quit
	# functionality of load_json(...), then the last saved version would be the
	# one when fman was last closed. But this does not reflect the fact that we
	# are now showing hidden files. So we flush Panes.json immediately to disk:
	save_json('Panes.json')
	pane._set_hidden_files_shown(value)
	# When we toggle hidden files again, this avoids an error caused by
	# `_remove_filter` being called for a non-active filter.

def _get_pane_info(pane):
	settings = load_json('Panes.json', default=[])
	default = {'show_hidden_files': False}
	pane_index = pane.window.get_panes().index(pane)
	for _ in range(pane_index - len(settings) + 1):
		settings.append(default.copy())
	return settings[pane_index]

def _hidden_file_filter(url):
	if PLATFORM == 'Mac' and url == 'file:///Volumes':
		return True
	scheme, path = splitscheme(url)
	if scheme != 'file://':
		return True
	return not is_hidden(path)

def _snapshot_hidden_file_filter():
	mac = PLATFORM == 'Mac'
	def predicate(listing, index):
		return not listing.attributes[index] & 2 or (
			mac and listing.location == 'file:///' and listing.names[index] == 'Volumes')
	def filter_indices(listing, order, check):
		attributes = listing.attributes
		visible = []
		for start in range(0, len(order), 256):
			check()
			batch = order[start:start + 256]
			if mac and listing.location == 'file:///':
				visible.extend(index for index in batch if predicate(listing, index))
			else:
				visible.extend([index for index in batch if not attributes[index] & 2])
		return visible
	predicate.filter_indices = filter_indices
	return predicate

_hidden_file_filter.snapshot_filter = _snapshot_hidden_file_filter

class _OpenInPaneCommand(DirectoryPaneCommand):
	def __call__(self):
		panes = self.pane.window.get_panes()
		num_panes = len(panes)
		if num_panes < 2:
			raise NotImplementedError()
		this_pane = panes.index(self.pane)
		source_pane = panes[self.get_source_pane(this_pane, num_panes)]
		if source_pane is self.pane:
			to_open = source_pane.get_file_under_cursor() or \
					  source_pane.get_path()
		else:
			# This for instance happens when the right pane is active and the
			# user asks to "open in the right pane". The source pane in this
			# case is the left pane. The cursor in the left pane is not visible
			# (because the right pane is active) - but it still exists and might
			# be over a directory! If we opened the directory under the cursor,
			# we would thus open a subdirectory of the left pane. That's not
			# what we want. We want to open the directory of the left pane:
			to_open = source_pane.get_path()
		dest_pane = panes[self.get_destination_pane(this_pane, num_panes)]
		dest_pane.run_command('open_directory', {'url': to_open})
	def get_source_pane(self, this_pane, num_panes):
		raise NotImplementedError()
	def get_destination_pane(self, this_pane, num_panes):
		raise NotImplementedError()

class OpenInRightPane(_OpenInPaneCommand):
	def get_source_pane(self, this_pane, num_panes):
		if this_pane == num_panes - 1:
			return this_pane - 1
		return this_pane
	def get_destination_pane(self, this_pane, num_panes):
		return min(this_pane + 1, num_panes - 1)

class OpenInLeftPane(_OpenInPaneCommand):
	def get_source_pane(self, this_pane, num_panes):
		if this_pane > 0:
			return this_pane
		return 1
	def get_destination_pane(self, this_pane, num_panes):
		return max(this_pane - 1, 0)

class ShowVolumes(DirectoryPaneCommand):

	aliases = ('Show volumes', 'Show drives')

	def __call__(self, pane_index=None):
		if pane_index is None:
			pane = self.pane
		else:
			pane = self.pane.window.get_panes()[pane_index]
		def callback():
			pane.focus()
			pane.move_cursor_home()
		pane.set_path(_get_volumes_url(), callback=callback)

def _get_volumes_url():
	if PLATFORM == 'Mac':
		return 'file:///Volumes'
	elif PLATFORM == 'Windows':
		return 'drives://'
	elif PLATFORM == 'Linux':
		if os.path.isdir('/media'):
			contents = os.listdir('/media')
			user_name = get_user()
			if contents == [user_name]:
				return as_url(os.path.join('/media', user_name))
			else:
				return 'file:///media'
		else:
			return 'file:///mnt'
	else:
		raise NotImplementedError(PLATFORM)

_RECENT_COMMANDS_LIMIT = 3
_COMMAND_PALETTE_HISTORY = 'Command Palette History.json'

def _recent_commands(registered=None, executed=None):
	from fman.ui import settings_resource
	resource = settings_resource(_COMMAND_PALETTE_HISTORY)
	with resource.lock:
		try:
			document = load_json(_COMMAND_PALETTE_HISTORY, default={'recent': []})
			if isinstance(document, dict):
				document = load_json(
					_COMMAND_PALETTE_HISTORY, save_on_quit=True, preserve_on_reload=True
				)
		except (OSError, ValueError, TypeError):
			document = None
		if not isinstance(document, dict):
			if not hasattr(resource, '_command_palette_fallback'):
				resource._command_palette_fallback = {'recent': []}
			document = resource._command_palette_fallback
		entries = document.get('recent', [])
		entries = entries[:256] if isinstance(entries, list) else []
		if executed is not None:
			entries.insert(0, {'kind': executed[0], 'name': executed[1]})
		recent = []
		for entry in entries:
			if not isinstance(entry, dict):
				continue
			kind, name = entry.get('kind'), entry.get('name')
			if kind not in ('pane', 'application') or not isinstance(name, str):
				continue
			if not name.strip() or name != name.strip() or len(name) > 256:
				continue
			identity = kind, name
			if identity in recent or registered is not None and identity not in registered:
				continue
			recent.append(identity)
			if len(recent) == _RECENT_COMMANDS_LIMIT:
				break
		document['recent'] = [{'kind': kind, 'name': name} for kind, name in recent]
		return tuple(recent)

class CommandPalette(DirectoryPaneCommand):

	_MATCHERS = (contains_chars_after_separator(' '), contains_chars)

	def __init__(self, *args, **kwargs):
		super().__init__(*args, **kwargs)
		self._last_query = ''
		self._last_cmd_name = ''
		self._last_cmd_kind = 'pane'
		self._recent = ()
	def __call__(self):
		registered = {('pane', name) for name in self.pane.get_commands()}
		registered.update(('application', name) for name in get_application_commands())
		self._recent = _recent_commands(registered=registered)
		if self._last_cmd_name:
			initial_suggestions = [
				quicksearch_item.value.identity
				for quicksearch_item in self._suggest_commands(self._last_query)
			]
			try:
				initial_item = initial_suggestions.index((self._last_cmd_kind, self._last_cmd_name))
			except ValueError:
				initial_item = 0
		else:
			initial_item = 0
		result = show_quicksearch(
			self._suggest_commands, query=self._last_query, item=initial_item
		)
		if result:
			query, command = result
			if command:
				self._last_query = query
				self._last_cmd_name = command.name
				self._last_cmd_kind = command.kind
				_recent_commands(executed=command.identity)
				command()
		else:
			self._last_query = self._last_cmd_name = ''
			self._last_cmd_kind = 'pane'
	def _suggest_commands(self, query):
		result = [[] for _ in self._MATCHERS]
		key_bindings = load_json('Key Bindings.json')
		for cmd_name, aliases, command in self._get_all_commands():
			for alias in aliases:
				this_alias_matched = False
				for i, matcher in enumerate(self._MATCHERS):
					highlight = matcher(alias.lower(), query.lower())
					if highlight is not None:
						shortcuts = \
							_get_shortcuts_for_command(key_bindings, cmd_name)
						if PLATFORM == 'Mac':
							shortcuts = map(_insert_mac_key_symbols, shortcuts)
						hint = ', '.join(shortcuts)
						item = QuicksearchItem(command, alias, highlight, hint)
						result[i].append(item)
						this_alias_matched = True
						break
				if this_alias_matched:
					# Don't check the other aliases:
					break
		for results in result:
			results.sort(key=lambda item: (len(item.title), item.title))
		ranked = list(chain.from_iterable(result))
		if not self._recent:
			return ranked
		by_identity = {item.value.identity: item for item in ranked}
		recent_items = []
		for identity in self._recent:
			item = by_identity.pop(identity, None)
			if item is not None:
				hint = item.hint + ' \u00b7 Recent' if item.hint else 'Recent'
				recent_items.append(QuicksearchItem(item.value, item.title, item.highlight, hint))
		return recent_items + [item for item in ranked if item.value.identity in by_identity]
	def _get_all_commands(self):
		result = []
		for cmd_name in self.pane.get_commands():
			if not self.pane.is_command_visible(cmd_name):
				continue
			aliases = self.pane.get_command_aliases(cmd_name)
			command = CommandPaletteItem(self.pane.run_command, cmd_name)
			result.append((cmd_name, aliases, command))
		for cmd_name in get_application_commands():
			aliases = get_application_command_aliases(cmd_name)
			command = CommandPaletteItem(run_application_command, cmd_name, 'application')
			result.append((cmd_name, aliases, command))
		return result

def _get_shortcuts_for_command(key_bindings, command):
	shortcuts_occupied_by_other_commands = set()
	for binding in key_bindings:
		try:
			binding_cmd = binding['command']
		except (KeyError, TypeError):
			# Malformed Key Bindings.json
			continue
		try:
			shortcut = binding['keys'][0]
		except (KeyError, IndexError, TypeError):
			# Malformed Key Bindings.json
			continue
		if not isinstance(shortcut, str):
			# Malformed Key Bindings.json
			continue
		if binding_cmd == command:
			if shortcut not in shortcuts_occupied_by_other_commands:
				yield shortcut
		shortcuts_occupied_by_other_commands.add(shortcut)

def _insert_mac_key_symbols(shortcut):
	keys = shortcut.split('+')
	return ''.join(_KEY_SYMBOLS_MAC.get(key, key) for key in keys)

_KEY_SYMBOLS_MAC = {
	'Cmd': '⌘', 'Alt': '⌥', 'Ctrl': '⌃', 'Shift': '⇧', 'Backspace': '⌫',
	'Up': '↑', 'Down': '↓', 'Left': '←', 'Right': '→', 'Enter': '↩'
}

class CommandPaletteItem:
	def __init__(self, run_fn, cmd_name, kind='pane'):
		self._run_fn = run_fn
		self.name = cmd_name
		self.kind = kind
	@property
	def identity(self):
		return self.kind, self.name
	def __call__(self):
		self._run_fn(self.name)

class Quit(ApplicationCommand):

	aliases = ('Quit', 'Exit')

	def __call__(self):
		sys.exit(0)

class ZenOfFman(ApplicationCommand):
	aliases = ('Zen of RoyiFileManager',)
	def __call__(self):
		show_alert(
			"The Zen of RoyiFileManager\n\n"
			"Looks matter\n"
			"Speed counts\n"
			"Extending must be easy\n"
			"Customisability is important\n"
			"But not at the expense of speed\n"
			"I/O is better asynchronous\n"
			"Updates should be transparent and continuous\n"
			"Don't reinvent the wheel"
		)

class OpenDataDirectory(DirectoryPaneCommand):
	def __call__(self):
		self.pane.set_path(as_url(DATA_DIRECTORY))

class GoBack(DirectoryPaneCommand):
	def __call__(self):
		HistoryListener.INSTANCES[self.pane].go_back()

class GoForward(DirectoryPaneCommand):
	def __call__(self):
		HistoryListener.INSTANCES[self.pane].go_forward()

class HistoryListener(DirectoryPaneListener):

	INSTANCES = {}

	def __init__(self, *args, **kwargs):
		super().__init__(*args, **kwargs)
		self._history = History()
		self.INSTANCES[self.pane] = self
	def go_back(self):
		try:
			path = self._history.go_back()
		except ValueError:
			return
		self._navigate_to(path)
	def go_forward(self):
		try:
			path = self._history.go_forward()
		except ValueError:
			return
		self._navigate_to(path)
	def _navigate_to(self, path):
		if path == dirname(self.pane.get_path()):
			# Place the cursor at the current directory after going up:
			go_up(self.pane)
		else:
			self.pane.set_path(path)
	def on_path_changed(self):
		self._history.path_changed(self.pane.get_path())

class History:
	def __init__(self):
		self._paths = []
		self._curr_path = -1
		self._ignore_next_path_change = False
	def go_back(self):
		if self._curr_path <= 0:
			raise ValueError()
		self._curr_path -= 1
		self._ignore_next_path_change = True
		return self._paths[self._curr_path]
	def go_forward(self):
		if self._curr_path >= len(self._paths) - 1:
			raise ValueError()
		self._curr_path += 1
		self._ignore_next_path_change = True
		return self._paths[self._curr_path]
	def path_changed(self, path):
		if path == 'null://':
			return
		if self._ignore_next_path_change:
			self._ignore_next_path_change = False
			return
		self._curr_path += 1
		del self._paths[self._curr_path:]
		self._paths.append(path)

class InstallPlugin(ApplicationCommand):
	def __init__(self, *args, **kwargs):
		super().__init__(*args, **kwargs)
		self._plugin_repos = None
	def __call__(self, github_repo=None):
		if github_repo:
			with StatusMessage('Fetching GitHub repo %s...' % github_repo):
				repo = GitHubRepo.fetch(github_repo)
		else:
			if self._plugin_repos is None:
				with StatusMessage('Fetching available plugins...'):
					try:
						self._plugin_repos = \
							find_repos(topics=['fman', 'plugin'])
					except URLError as e:
						show_alert(
							'Could not fetch available plugins: %s.' % e.reason
						)
						return
			result = show_quicksearch(self._get_matching_repos)
			repo = result[1] if result else None
		if repo:
			with StatusMessage('Downloading %s...' % repo.name):
				try:
					ref = repo.get_latest_release()
				except LookupError as no_release_yet:
					ref = repo.get_latest_commit()
				zipball_contents = repo.download_zipball(ref)
			plugin_dir = self._install_plugin(repo.name, zipball_contents)
			# Save some data in case we want to update the plugin later:
			self._record_plugin_installation(plugin_dir, repo.url, ref)
			success = self._load_installed_plugin(plugin_dir)
			if success:
				show_alert('Plugin %r was successfully installed.' % repo.name)
	def _get_matching_repos(self, query):
		installed_plugins = set(
			os.path.basename(plugin_dir)
			for plugin_dir in _get_thirdparty_plugins()
		)
		for repo in self._plugin_repos:
			if repo.name in installed_plugins:
				continue
			match = contains_chars(repo.name.lower(), query.lower())
			if match or not query:
				hint = '%d ★' % repo.num_stars if repo.num_stars else ''
				yield QuicksearchItem(
					repo, repo.name, match, hint=hint,
					description=repo.description
				)
	def _install_plugin(self, name, zipball_contents):
		os.makedirs(_THIRDPARTY_PLUGINS_DIR, exist_ok=True)
		dest_dir = os.path.join(_THIRDPARTY_PLUGINS_DIR, name)
		dest_dir_url = as_url(dest_dir)
		if exists(dest_dir_url):
			raise ValueError('Plugin %s seems to already be installed.' % name)
		# We purposely don't use Python's ZipFile here because it does not
		# preserve the executable bit of extracted files. This would present a
		# problem for plugins shipping with their own binaries.
		with TemporaryDirectory() as tmp_dir:
			zip_path = os.path.join(tmp_dir, 'plugin.zip')
			with open(zip_path, 'wb') as f:
				f.write(zipball_contents)
			zip_url = as_url(zip_path, 'zip://')
			dir_in_zip, = iterdir(zip_url)
			copy(join(zip_url, dir_in_zip), dest_dir_url)
		return dest_dir
	def _load_installed_plugin(self, plugin_dir):
		# Unload plugins later than the given plugin in the load order, load
		# the plugin, then load the unloaded plugins again. This inserts the
		# given plugin in the correct place in the load order.
		plugins = _get_plugins()
		plugin_index = plugins.index(plugin_dir)
		to_unload = plugins[plugin_index + 1:]
		with PreservePanePaths(self.window):
			for plugin in reversed(to_unload):
				try:
					unload_plugin(plugin)
				except ValueError as was_not_loaded:
					pass
			result = load_plugin(plugin_dir)
			for plugin in to_unload:
				load_plugin(plugin)
		return result
	def _record_plugin_installation(self, plugin_dir, repo_url, ref):
		plugin_json = os.path.join(plugin_dir, 'Plugin.json')
		if os.path.exists(plugin_json):
			with open(plugin_json, 'r') as f:
				data = json.load(f)
		else:
			data = {}
		data['url'] = repo_url
		data['ref'] = ref
		with open(plugin_json, 'w') as f:
			json.dump(data, f)

_THIRDPARTY_PLUGINS_DIR = os.path.join(DATA_DIRECTORY, 'Plugins', 'Third-party')

def _get_thirdparty_plugins():
	return _list_plugins(_THIRDPARTY_PLUGINS_DIR)

def _list_plugins(dir_path):
	try:
		return list(filter(os.path.isdir, listdir_absolute(dir_path)))
	except FileNotFoundError:
		return []

class RemovePlugin(ApplicationCommand):

	aliases = ('Remove plugin', 'Uninstall plugin')

	def __init__(self, *args, **kwargs):
		super().__init__(*args, **kwargs)
		self._installed_plugins = None
	def __call__(self):
		self._installed_plugins = _get_thirdparty_plugins()
		if not self._installed_plugins:
			show_alert("You don't seem to have any plugins installed.")
		else:
			result = show_quicksearch(self._get_matching_plugins)
			if result:
				plugin_dir = result[1]
				if plugin_dir:
					try:
						unload_plugin(plugin_dir)
					except ValueError as plugin_was_not_loaded:
						pass
					delete(as_url(plugin_dir))
					show_alert(
						'Plugin %r was successfully removed.'
						% os.path.basename(plugin_dir)
					)
	def _get_matching_plugins(self, query):
		for plugin_dir in self._installed_plugins:
			plugin_name = os.path.basename(plugin_dir)
			match = contains_chars(plugin_name.lower(), query.lower())
			if match or not query:
				yield QuicksearchItem(plugin_dir, plugin_name, highlight=match)

class ReloadPlugins(ApplicationCommand):
	def __call__(self):
		plugins = _get_plugins()
		with PreservePanePaths(self.window):
			for plugin in reversed(plugins):
				try:
					unload_plugin(plugin)
				except ValueError as plugin_had_not_been_loaded:
					pass
			for plugin in plugins:
				load_plugin(plugin)
		num_plugins = len(plugins)
		plural = 's' if num_plugins > 1 else ''
		show_status_message(
			'Reloaded %d plugin%s.' % (num_plugins, plural), timeout_secs=2
		)

class PreservePanePaths:
	# When a pane is currently displaying a location with a file system that
	# is "reloaded", its location gets lost. So save the locations and
	# restore them later.
	def __init__(self, window):
		self._window = window
		self._paths_before = []
	def __enter__(self):
		self._paths_before = \
			[pane.get_path() for pane in (self._window.get_panes())]
		return self
	def __exit__(self, exc_type, exc_val, exc_tb):
		for pane, path in zip(self._window.get_panes(), self._paths_before):
			pane.set_path(path)

def _get_plugins():
	return _get_thirdparty_plugins() + _get_user_plugins()

def _get_user_plugins():
	result = []
	settings_plugin = ''
	user_plugins_dir = os.path.join(DATA_DIRECTORY, 'Plugins', 'User')
	for plugin_dir in _list_plugins(user_plugins_dir):
		if os.path.basename(plugin_dir) == 'Settings':
			settings_plugin = plugin_dir
		else:
			result.append(plugin_dir)
	# According to the fman docs, the Settings plugin is loaded last:
	if settings_plugin:
		result.append(settings_plugin)
	return result

class ListPlugins(DirectoryPaneCommand):
	def __call__(self):
		result = show_quicksearch(self._get_matching_plugins)
		if result:
			plugin_dir = result[1]
			if plugin_dir:
				self.pane.set_path(as_url(plugin_dir), onerror=None)
	def _get_matching_plugins(self, query):
		result = []
		for plugin_dir in _get_thirdparty_plugins():
			plugin_name = os.path.basename(plugin_dir)
			match = contains_chars(plugin_name.lower(), query.lower())
			if match or not query:
				plugin_json = os.path.join(plugin_dir, 'Plugin.json')
				try:
					with open(plugin_json, 'r') as f:
						ref = json.load(f).get('ref', '')
				except OSError:
					ref = ''
				is_sha = len(ref) == 40
				if is_sha:
					ref = ref[:8]
				result.append(QuicksearchItem(
					plugin_dir, plugin_name, highlight=match, hint=ref
				))
		for plugin_dir in _get_user_plugins():
			plugin_name = os.path.basename(plugin_dir)
			match = contains_chars(plugin_name.lower(), query.lower())
			if match or not query:
				result.append(
					QuicksearchItem(plugin_dir, plugin_name, highlight=match)
				)
		return sorted(result, key=lambda qsi: qsi.title)

class StatusMessage:
	def __init__(self, message):
		self._message = message
	def __enter__(self):
		show_status_message(self._message)
	def __exit__(self, *_):
		clear_status_message()

if PLATFORM == 'Mac':
	class GetInfo(DirectoryPaneCommand):
		def __call__(self):
			files = self.get_chosen_files() or [self.pane.get_path()]
			self._run_applescript(
				'on run args\n'
				'	tell app "Finder"\n'
				'		activate\n'
				'		repeat with f in args\n'
				'			open information window of '
							'(posix file (contents of f) as alias)\n'
				'		end\n'
				'	end\n'
				'end\n',
				_get_local_filepaths(files)
			)
		def _run_applescript(self, script, args=None):
			if args is None:
				args = []
			process = Popen(
				['osascript', '-'] + args, stdin=PIPE,
				stdout=DEVNULL, stderr=DEVNULL
			)
			process.communicate(script.encode('ascii'))
elif PLATFORM == 'Windows':
	try:
		from .explorer_properties import ShowExplorerProperties
	except ImportError as e:
		# If we simply refer to `e` below, we get a NameError. This is likely
		# because the captured exception of `except` statements goes out of
		# scope as soon as the except block exits. So introduce a separate
		# variable that does not go out of scope:
		error = e
		class ShowExplorerProperties(DirectoryPaneCommand):
			def __call__(self):
				show_alert(
					'Sorry, the module for displaying file properties %r could '
					'not be loaded. Include your Windows version and architecture '
					'when reporting this problem.'
					% error.name
				)

def _get_local_filepaths(urls):
	result = []
	for url in urls:
		scheme, path = splitscheme(url)
		if scheme == 'file://':
			result.append(path)
	return result

class UnpackArchive(DirectoryPaneCommand):
	aliases = ('Unpack archive',)
	def __call__(self):
		directory = self.pane.get_path()
		chosen = self.get_chosen_files()
		if len(chosen) != 1:
			show_alert('Choose exactly one archive to unpack.')
			return
		source = chosen[0]
		try:
			if splitscheme(directory)[0] != 'file://' or splitscheme(source)[0] != 'file://':
				raise ValueError('Unpack requires a local archive in the current folder.')
			if not samefile(dirname(source), directory) or is_dir(source):
				raise ValueError('Choose an archive file directly inside the current folder.')
			settings = load_json('Core Settings.json', default={})
			handlers = settings.get('archive_handlers') if isinstance(settings, Mapping) else None
			name, scheme = _unpack_archive_name(basename(source), handlers)
			destination = join(directory, name)
			if os.path.lexists(as_human_readable(destination)):
				show_alert('Destination already exists: ' + name)
				return
			task = _UnpackArchive(source, scheme + splitscheme(source)[1], destination)
			try:
				submit_task(task)
			except OSError as error:
				show_alert(_unpack_error_text(error, destination))
				return
		except (OSError, ValueError) as error:
			show_alert(str(error))
			return
		if task.succeeded:
			show_status_message('Unpacked ' + name, timeout_secs=5)
			try:
				if self.pane.get_path() == directory:
					self.pane.place_cursor_at(destination)
			except (OSError, RuntimeError, ValueError):
				pass

def _unpack_archive_name(file_name, handlers):
	if not isinstance(handlers, Mapping) or any(
		not isinstance(suffix, str) or not suffix.startswith('.') or len(suffix) < 2 or
		suffix != suffix.lower() or not isinstance(scheme, str) or
		not scheme.endswith('://') or len(scheme) <= 3
		for suffix, scheme in handlers.items()
	):
		raise ValueError('Invalid archive_handlers in Core Settings.json.')
	match = _get_archive_handler(file_name, handlers)
	if match is None:
		raise ValueError('This archive format is not supported.')
	suffix, scheme = match
	name = file_name[:-len(suffix)]
	if name in ('', '.', '..'):
		raise ValueError('The archive name does not produce a valid folder name.')
	return name, scheme

class _UnpackArchive(Task):
	def __init__(self, source, archive, destination):
		super().__init__('Unpacking ' + basename(source), size=0)
		self._source = source
		self._archive = archive
		self._destination = destination
		self.succeeded = False
	def __call__(self):
		from core.fs.zip import Extract
		self.check_canceled()
		children = list(prepare_copy(self._archive, self._destination))
		if len(children) != 1 or type(children[0]) is not Extract:
			raise UnsupportedOperation('This archive handler does not support safe Unpack.')
		children[0].require_new_directory(
			as_human_readable(self._source), as_human_readable(self._destination)
		)
		self.set_size(sum(child.get_size() for child in children))
		for child in children:
			self.check_canceled()
			self.run(child)
		self.succeeded = True

def _unpack_error_text(error, destination):
	path = as_human_readable(destination)
	if isinstance(error, (FileExistsError, PermissionError)) and error.filename2 and \
		os.path.normcase(os.path.normpath(error.filename2)) == os.path.normcase(os.path.normpath(path)):
		try:
			if os.path.lexists(path):
				return 'Destination already exists: ' + basename(destination)
		except OSError:
			pass
	return str(error)

class Pack(DirectoryPaneCommand):

	aliases = 'Pack to archive (.zip, .7z, .tar)', 'Compress...'

	def __call__(self):
		files = self.get_chosen_files()
		if not files:
			show_alert('No file is selected!')
			return
		if len(files) == 1:
			dest_name = PurePath(basename(files[0])).stem + '.zip'
		else:
			dest_name = basename(self.pane.get_path()) + '.zip'
		dest_dir = _get_opposite_pane(self.pane).get_path()
		dest_url = join(dest_dir, dest_name)
		suggested_dst, selection_start, selection_end = \
			get_dest_suggestion(dest_url)
		dest, ok = show_prompt(
			'Pack %s to (.zip, .7z, .tar):' % _describe(files), suggested_dst,
			selection_start, selection_end
		)
		if dest and ok:
			dest = _from_human_readable(dest, dest_dir, self.pane.get_path())
			scheme = _get_handler_for_archive(basename(dest))
			if not scheme:
				show_alert('Sorry, but this archive format is not supported.')
				return
			dest_rewritten = scheme + splitscheme(dest)[1]
			try:
				# Create empty archive:
				mkdir(dest_rewritten)
			except FileExistsError:
				answer = show_alert(
					'%s already exists. Do you want to add/update the selected '
					'files?' % basename(dest_rewritten), YES | NO, YES
				)
				if not answer & YES:
					return
			submit_task(_Pack(files, dest_rewritten))
	def is_visible(self):
		return bool(self.pane.get_file_under_cursor())

class _Pack(Task):
	def __init__(self, files, archive_url):
		super().__init__('Packing ' + _describe(files), size=len(files) * 100)
		self._files = files
		self._archive = archive_url
	def __call__(self):
		for f in self._files:
			for task in prepare_copy(f, join(self._archive, basename(f))):
				self.check_canceled()
				self.run(task)

def _get_handler_for_archive(file_name):
	match = _get_archive_handler(file_name)
	return match[1] if match else None

def _get_archive_handler(file_name, handlers=None):
	if handlers is None:
		settings = load_json('Core Settings.json', default={})
		handlers = settings.get('archive_handlers', {})
	archive_types = sorted(
		handlers.items(),
		key=lambda tpl: -len(tpl[0])
	)
	for suffix, scheme in archive_types:
		if file_name.lower().endswith(suffix):
			return suffix, scheme

class ArchiveOpenListener(DirectoryPaneListener):
	def on_command(self, command_name, args):
		if command_name in ('open_file', 'open_directory'):
			url = args['url']
			try:
				scheme, path = splitscheme(url)
			except (KeyError, ValueError):
				return None
			if scheme == 'file://':
				new_scheme = _get_handler_for_archive(basename(path))
				if new_scheme:
					try:
						if is_dir(url):
							return None
					except OSError:
						return None
					new_args = dict(args)
					new_args['url'] = new_scheme + path
					return 'open_directory', new_args

class Reload(DirectoryPaneCommand):

	aliases = ('Reload', 'Refresh')

	def __call__(self):
		self.pane.reload()

class SwitchPanes(DirectoryPaneCommand):
	def __call__(self, pane_index=None):
		if _switch_quick_view(self.pane, pane_index):
			return
		if pane_index is None:
			pane = _get_opposite_pane(self.pane)
		else:
			pane = self.pane.window.get_panes()[pane_index]
		pane.focus()

class SyncPaneLocation(DirectoryPaneCommand):
	aliases = ('Sync pane location',)

	def __call__(self):
		if not self.is_visible():
			show_status_message('No other pane to sync.', timeout_secs=3)
			return
		path = self.pane.get_path()
		if path == 'null://':
			show_status_message('No location to sync.', timeout_secs=3)
			return
		opposite_pane = _get_opposite_pane(self.pane)
		if opposite_pane.get_path() != path:
			opposite_pane.set_path(path)

	def is_visible(self):
		return len(self.pane.window.get_panes()) > 1

class SortByColumn(DirectoryPaneCommand):

	_MATCHERS = (contains_chars_after_separator(' '), contains_chars)

	def __call__(self, column_index=None):
		columns = self.pane.get_columns()
		if column_index is None:
			curr_sort_col = self.pane.get_sort_column()[0]
			curr_sort_col_index = columns.index(curr_sort_col)
			result = show_quicksearch(
				lambda q: self._get_items(columns, q), item=curr_sort_col_index
			)
			if result:
				column_index = columns.index(result[1])
		if column_index is not None:
			column = columns[column_index]
			sort_column, sort_column_is_ascending = self.pane.get_sort_column()
			if column == sort_column:
				ascending = not sort_column_is_ascending
			else:
				ascending = True
			self.pane.set_sort_column(column, ascending)
	def _get_items(self, columns, query):
		result = [[] for _ in self._MATCHERS]
		for col_qual_name in columns:
			col_name = col_qual_name.rsplit('.', 1)[1]
			for i, matcher in enumerate(self._MATCHERS):
				highlight = matcher(col_name.lower(), query.lower())
				if highlight is not None:
					item = QuicksearchItem(col_qual_name, col_name, highlight)
					result[i].append(item)
					break
		return chain.from_iterable(result)

class RememberSortSettings(DirectoryPaneListener):
	def before_location_change(self, url, sort_column='', ascending=True):
		self._remember_curr_sort_column()
		try:
			# Consider: We're at zip:///foo.zip and go up. This moves us to
			# zip:/// - which resolves to file:///. The sort settings will have
			# been saved for this latter URL. So we have to resolve(...) to go
			# from the former to the latter:
			url_resolved = resolve(url)
		except OSError:
			url_resolved = url
		settings = load_json('Sort Settings.json', default={})
		try:
			data = settings[url_resolved]
		except KeyError:
			return
		remembered_col, remembered_asc = data['column'], data['is_ascending']
		# Note that we return `url` here, not `url_resolved`. This is eg.
		# because we don't want to rewrite C:\Windows\System32 -> ...\SysWOW64.
		return url, remembered_col, remembered_asc
	def _remember_curr_sort_column(self):
		column, is_ascending = self.pane.get_sort_column()
		url = self.pane.get_path()
		settings = load_json('Sort Settings.json', default={})
		default = (self.pane.get_columns()[0], True)
		if (column, is_ascending) == default:
			settings.pop(url, None)
		else:
			settings[url] = {
				'column': column,
				'is_ascending': is_ascending
			}
		save_json('Sort Settings.json')

class Minimize(ApplicationCommand):
	def __call__(self):
		self.window.minimize()

class ResetWindowGeometry(ApplicationCommand):
	aliases = ('Reset window geometry',)
	def __call__(self):
		from fman.impl.application_context import get_application_context
		get_application_context().session_manager.reset_window_geometry(
			self.window
		)

class LocationBarListener(DirectoryPaneListener):
	def on_location_bar_clicked(self):
		url = self.pane.get_path()
		if _is_file_url(url):
			path = as_human_readable(url)
			self.pane.run_command('go_to', {'query': path})
			ctrl = 'Cmd' if PLATFORM == 'Mac' else 'Ctrl'
			show_status_message(
				'Hint: You can also press %s+P to open GoTo. If you merely '
				'want to copy the current path, close GoTo, then press '
				'Backspace followed by F11.' % ctrl, timeout_secs=15
			)

class OpenWith(DirectoryPaneCommand):

	aliases = 'Open with...',

	_OTHER = 'Other...'

	def __call__(self, app=None):
		files, error_msg = self._get_chosen_files()
		if error_msg:
			show_alert(error_msg)
			return
		is_first_execution = not _load_apps()
		if is_first_execution:
			app = _add_app()
			if app:
				_open_files_with_app(files, app)
		else:
			if app is None:
				ShowAppsForOpening(files).show()
			else:
				_open_files_with_app(files, app)
	def _get_chosen_files(self):
		urls = self.get_chosen_files()
		if not urls:
			return [], 'No file is selected!'
		files = []
		for url in urls:
			try:
				url_resolved = resolve(url)
			except OSError:
				pass
			else:
				scheme, path = splitscheme(url_resolved)
				if scheme != 'file://':
					return \
						[], 'Sorry, opening %s files is not supported.' % scheme
				files.append(as_human_readable(url_resolved))
		return files, ''
	def is_visible(self):
		pane = self.pane
		return _is_file_url(pane.get_path()) and pane.get_file_under_cursor()

def _open_files_with_app(files, app):
	associations = _load_file_associations()
	for file_path in files:
		file_name = os.path.basename(file_path)
		try:
			extension = file_name[file_name.rindex('.'):]
		except ValueError:
			extension = ''
		ext_assocs = associations.setdefault(extension, {})
		ext_assocs[app] = ext_assocs.get(app, 0) + 1
	_save_file_associations()
	apps = _load_apps()
	try:
		app_path = apps[app]
	except KeyError:
		# We don't expect this to happen. But JSON files are always susceptible
		# by becoming corrupted, eg. when the user edits them.
		show_alert('Could not find the configuration for %s.' % app)
		return
	Popen(**get_popen_kwargs_for_opening(files, with_=app_path))

def _load_file_associations():
	return load_json('File Associations.json', {})

def _save_file_associations():
	save_json('File Associations.json')

def _load_apps():
	return load_json('Apps.json', {})

def _save_apps():
	save_json('Apps.json')

def _add_app():
	app_path = _show_app_open_dialog('Pick an application')
	if not app_path:
		return
	app_name = os.path.basename(app_path).split('.')[0].capitalize()
	app_name, ok = show_prompt(
		'Please enter a name for the application:', app_name
	)
	if not ok or not app_name:
		return
	apps = _load_apps()
	apps[app_name] = app_path
	_save_apps()
	return app_name

def _remove_app(app):
	apps = _load_apps()
	try:
		del apps[app]
	except KeyError:
		# We don't expect this to happen. But JSON files are always susceptible
		# by becoming corrupted, eg. when the user edits them.
		pass
	_save_apps()
	associations = _load_file_associations()
	for suffix, apps in list(associations.items()):
		apps.pop(app, None)
		if not apps:
			del associations[suffix]
	_save_file_associations()

class QuicksearchScreen:

	_MATCHERS = (contains_chars_after_separator(' '), contains_chars)

	def show(self):
		options = list(self.get_options())
		choice = show_quicksearch(lambda q: self._filter_options(options, q))
		if choice:
			option = choice[1]
			self.on_selected(option)
		else:
			self.on_cancelled()
	def get_options(self):
		raise NotImplementedError()
	def on_selected(self, option):
		raise NotImplementedError()
	def on_cancelled(self):
		pass
	def _filter_options(self, options, query):
		already_yielded = set()
		for matcher in self._MATCHERS:
			for option in options:
				match = matcher(option.lower(), query.lower())
				if match or not query:
					if option not in already_yielded:
						yield QuicksearchItem(option, highlight=match)
						already_yielded.add(option)

class ShowAppsForOpening(QuicksearchScreen):

	_CONFIGURE = 'Configure...'

	def __init__(self, files):
		super().__init__()
		self._files = files
	def get_options(self):
		file_associations = sorted(
			_load_file_associations().items(),
			key=lambda tpl: len(tpl[0]), reverse=True
		)
		already_yielded = set()
		for file_path in self._files:
			fname = os.path.basename(file_path)
			for suffix, associations in file_associations:
				if fname.endswith(suffix) and (suffix or '.' not in fname):
					for app, count in sorted(
						associations.items(), key=lambda tpl: tpl[1],
						reverse=True
					):
						if app not in already_yielded:
							yield app
							already_yielded.add(app)
		for app in sorted(_load_apps()):
			if app not in already_yielded:
				yield app
		yield self._CONFIGURE
	def on_selected(self, option):
		if option == self._CONFIGURE:
			Configure(self._files).show()
		else:
			_open_files_with_app(self._files, option)

class Configure(QuicksearchScreen):

	_ADD_APP = 'Add app...'
	_EDIT_APP = 'Edit app...'
	_REMOVE_APP = 'Remove app...'

	def __init__(self, files):
		super().__init__()
		self._files = files
	def get_options(self):
		yield self._ADD_APP
		yield self._EDIT_APP
		yield self._REMOVE_APP
	def on_selected(self, option):
		if option == self._ADD_APP:
			app = _add_app()
			if app:
				_open_files_with_app(self._files, app)
		elif option == self._EDIT_APP:
			EditApp(self._files).show()
		elif option == self._REMOVE_APP:
			RemoveApp(self._files).show()
	def on_cancelled(self):
		ShowAppsForOpening(self._files).show()

class EditApp(QuicksearchScreen):
	def __init__(self, files):
		super().__init__()
		self._files = files
	def get_options(self):
		yield from sorted(_load_apps())
	def on_selected(self, app):
		new_name, ok = \
			show_prompt('Enter the new name for the application:', app)
		if not ok or not new_name:
			Configure(self._files).show()
			return
		apps = _load_apps()
		app_path = apps[app]
		new_path = show_file_open_dialog(
			"Pick an executable", app_path,
			_PLATFORM_APPLICATIONS_FILTER[PLATFORM]
		)
		if not new_path:
			Configure(self._files).show()
			return
		del apps[app]
		apps[new_name] = new_path
		_save_apps()
		associations = _load_file_associations()
		for suffix, app_counts_for_suffix in associations.items():
			try:
				app_counts_for_suffix[new_name] = app_counts_for_suffix.pop(app)
			except KeyError:
				pass
		_save_file_associations()
		show_alert('%s was updated.' % new_name)
	def on_cancelled(self):
		Configure(self._files).show()

class RemoveApp(QuicksearchScreen):
	def __init__(self, files):
		super().__init__()
		self._files = files
	def get_options(self):
		yield from sorted(_load_apps())
	def on_selected(self, app):
		apps = _load_apps()
		del apps[app]
		_save_apps()
		associations = _load_file_associations()
		for suffix, apps in list(associations.items()):
			apps.pop(app, None)
			if not apps:
				del associations[suffix]
		_save_file_associations()
		show_alert('%s was removed from your favorite apps.' % app)
	def on_cancelled(self):
		Configure(self._files).show()

class CompareDirectories(DirectoryPaneCommand):
	def __call__(self):
		this = self.pane
		panes = this.window.get_panes()
		this_index = panes.index(this)
		other_index = (this_index + 1) % len(panes)
		left = panes[min(this_index, other_index)]
		right = panes[max(this_index, other_index)]
		res_left = self._select_nonexistent_in_other(left, right)
		res_right = self._select_nonexistent_in_other(right, left)
		if res_left == res_right == 0:
			message = 'The directories contain the same file <em>names</em>.' \
			          '<br/>(Did not compare contents, Size or Modified.)'
		else:
			msg_parts = []
			def report(count, l, r):
				if count:
					msg_parts.append(
						'The %s pane contains %d file%s not present on the %s.'
						% (l, count, '' if count == 1 else 's', r)
					)
			report(res_left, 'left', 'right')
			report(res_right, 'right', 'left')
			message = '<br/>'.join(msg_parts)
		show_alert(message)
	def _select_nonexistent_in_other(self, this, other):
		this.clear_selection()
		other_files = set(iterdir(other.get_path()))
		url = this.get_path()
		nonexistent = set(f for f in iterdir(url) if f not in other_files)
		this.select(join(url, f) for f in nonexistent)
		return len(nonexistent)

class none(DirectoryPaneCommand):
	"""
	Assign key bindings to this command to effectively deactivate them.
	This is a DirectoryPaneCommand because ApplicationCommand currently does not
	support is_visible().
	"""
	def __call__(self):
		pass
	def is_visible(self):
		return False

if PLATFORM == 'Mac':
	class QuickLook(DirectoryPaneCommand):

		aliases = ('Quick Look', 'Preview')

		def __call__(self):
			files = self.get_chosen_files()
			if not files:
				show_alert('No file is selected!')
				return
			if any(not _is_file_url(f) for f in files):
				show_alert('Sorry, can only preview normal files.')
				return
			args = ['qlmanage', '-p']
			args.extend(map(as_human_readable, files))
			Popen(args, stdout=DEVNULL, stderr=DEVNULL)

if PLATFORM == 'Windows':
	class GoToRootOfCurrentDrive(DirectoryPaneCommand):
		def __call__(self):
			url = self.pane.get_path()
			scheme = splitscheme(url)[0]
			if scheme == 'file://':
				dest = as_url(PurePath(as_human_readable(url)).anchor)
			else:
				dest = scheme
			try:
				self.pane.set_path(dest)
			except FileNotFoundError:
				pass