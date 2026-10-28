from os import listdir, strerror
from os.path import join, dirname, realpath, relpath, \
	pardir, splitdrive

import errno
import os

def listdir_absolute(dir_path):
	return [join(dir_path, file_name) for file_name in listdir(dir_path)]

def is_below_dir(file_path, directory):
	if splitdrive(file_path)[0].lower() != splitdrive(directory)[0].lower():
		return False
	rel = relpath(realpath(dirname(file_path)), realpath(directory))
	return not (rel == pardir or rel.startswith(pardir + os.sep))

class Event:
	def __init__(self):
		self._callbacks = []
	def add_callback(self, callback):
		self._callbacks.append(callback)
	def remove_callback(self, callback):
		self._callbacks.remove(callback)
	def trigger(self, *args):
		for callback in self._callbacks:
			callback(*args)

# Copied from core.util:
def filenotfounderror(path):
	# The correct way of instantiating FileNotFoundError in a way that respects
	# the parent class (OSError)'s arguments:
	return FileNotFoundError(errno.ENOENT, strerror(errno.ENOENT), path)