from core.fs.local.windows.network import NetworkFileSystem
from core.util import filenotfounderror
from ctypes import windll
from fman.fs import FileSystem, Column
from fman.url import as_url

import ctypes
import string

class DrivesFileSystem(FileSystem):

	scheme = 'drives://'

	NETWORK = 'Network...'

	def get_default_columns(self, path):
		return DriveName.__module__ + '.' + DriveName.__name__,
	def resolve(self, path):
		if not path:
			# Showing the list of all drives:
			return self.scheme
		if path in self._get_drives():
			return as_url(path + '\\')
		if path == self.NETWORK:
			return NetworkFileSystem.scheme
		raise filenotfounderror(path)
	def iterdir(self, path):
		if path:
			raise filenotfounderror(path)
		return self._get_drives() + [self.NETWORK]
	def is_dir(self, existing_path):
		if self.exists(existing_path):
			return True
		raise filenotfounderror(existing_path)
	def scan(self, path, check_canceled):
		from fman.listing import Listing
		names, labels = [], []
		for name in self.iterdir(path):
			check_canceled()
			names.append(name)
			labels.append(self._get_drive_label(name))
		return Listing.create(self.scheme + path, names, is_dir=(True,) * len(names), labels=labels)
	def _get_drive_label(self, name):
		if name == self.NETWORK:
			return name
		try:
			volume_name = self._get_volume_name(name + '\\')
		except OSError:
			return name
		return name + ' ' + volume_name if volume_name else name
	def _get_volume_name(self, volume_path):
		kernel32 = windll.kernel32
		buffer = ctypes.create_unicode_buffer(1024)
		if not kernel32.GetVolumeInformationW(
			ctypes.c_wchar_p(volume_path), buffer, ctypes.sizeof(buffer),
			None, None, None, None, 0
		):
			raise ctypes.WinError()
		return buffer.value
	def exists(self, path):
		return not path or path in self._get_drives() or path == self.NETWORK
	def _get_drives(self):
		result = []
		bitmask = windll.kernel32.GetLogicalDrives()
		for letter in string.ascii_uppercase:
			if bitmask & 1:
				result.append(letter + ':')
			bitmask >>= 1
		return result

class DriveName(Column):

	display_name = 'Name'
	def text(self, listing, index):
		return listing.display_names[index]
	def keys(self, listing, ascending):
		return tuple((name == DrivesFileSystem.NETWORK, label.lower())
			for name, label in zip(listing.names, listing.display_names))
