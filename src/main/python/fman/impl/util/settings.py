from json import JSONDecodeError
from os import makedirs
from os.path import dirname
from tempfile import NamedTemporaryFile

import json
import os

class Settings:
	def __init__(self, json_path):
		self._json_path = json_path
		try:
			with open(self._json_path, 'r') as f:
				self._json_dict = json.load(f)
		except (FileNotFoundError, JSONDecodeError):
			self._json_dict = {}
		if not isinstance(self._json_dict, dict):
			self._json_dict = {}
	def get(self, key, default):
		return self._json_dict.get(key, default)
	def __setitem__(self, key, value):
		self._json_dict[key] = value
	def pop(self, key, default=None):
		return self._json_dict.pop(key, default)
	def setdefault(self, key, value):
		return self._json_dict.setdefault(key, value)
	def flush(self):
		serialized = json.dumps(self._json_dict)
		directory = dirname(self._json_path) or '.'
		makedirs(directory, exist_ok=True)
		self._check_destination()
		temporary = None
		try:
			with NamedTemporaryFile(mode='w', dir=directory, prefix='.fman-settings-',
				encoding='utf-8', delete=False) as output:
				temporary = output.name
				output.write(serialized)
			self._check_destination()
			os.replace(temporary, self._json_path)
		finally:
			if temporary is not None:
				try:
					os.unlink(temporary)
				except OSError:
					pass
	def _check_destination(self):
		if os.path.islink(self._json_path) or os.path.isjunction(self._json_path):
			raise OSError('Refusing to replace linked settings')
		try:
			metadata = os.lstat(self._json_path)
		except FileNotFoundError:
			return
		if metadata.st_nlink > 1:
			raise OSError('Refusing to replace linked settings')
	def __bool__(self):
		return bool(self._json_dict)