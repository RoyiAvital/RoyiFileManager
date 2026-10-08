from datetime import datetime, timezone
import os
from pathlib import Path
import re
import stat
from uuid import uuid4

from .engine import NAME_SURROGATE


FINISHED = '\r\n[Robocopy transfer finished]\r\n'.encode('utf-16-le')
LOG_NAME = re.compile(r'\d{8}T\d{12}Z-[0-9a-f]{32}\.txt\Z')


def choose_path(data_directory):
	name = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ-') + uuid4().hex + '.txt'
	return str(Path(data_directory) / 'Local' / 'Robocopy' / 'Logs' / name)


def plain_info(path):
	info = os.lstat(path)
	if stat.S_ISLNK(info.st_mode) or getattr(info, 'st_reparse_tag', 0) & NAME_SURROGATE:
		raise OSError('Robocopy log paths must not be symbolic links or junctions.')
	return info


def safe_directory(directory):
	for parent in reversed((directory, *directory.parents)):
		try:
			info = plain_info(parent)
		except FileNotFoundError:
			continue
		if not stat.S_ISDIR(info.st_mode):
			raise NotADirectoryError(str(parent))


class TransferLog:
	def __init__(self, path, title):
		self.path = Path(path)
		safe_directory(self.path.parent)
		self.path.parent.mkdir(parents=True, exist_ok=True)
		safe_directory(self.path.parent)
		with self.path.open('xb') as output:
			output.write(b'\xff\xfe' + (title + '\r\n').encode('utf-16-le'))
			info = os.fstat(output.fileno())
			self.identity = info.st_dev, info.st_ino
		self.validate()

	def validate(self):
		safe_directory(self.path.parent)
		info = plain_info(self.path)
		if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or \
				(info.st_dev, info.st_ino) != self.identity or info.st_size < 2 or info.st_size % 2:
			raise OSError('The Robocopy log changed or contains incomplete Unicode output.')
		with self.path.open('rb') as source:
			if source.read(2) != b'\xff\xfe':
				raise OSError('The Robocopy log has an unexpected encoding.')

	def append(self, text):
		self.validate()
		with self.path.open('ab') as output:
			output.write((text + '\r\n').encode('utf-16-le', errors='replace'))

	def finish(self, summary):
		self.append(summary)
		with self.path.open('ab') as output:
			output.write(FINISHED)

	def prune(self, count):
		safe_directory(self.path.parent)
		completed = []
		with os.scandir(self.path.parent) as entries:
			for entry in entries:
				if not LOG_NAME.fullmatch(entry.name) or Path(entry.path) == self.path:
					continue
				try:
					info = os.lstat(entry.path)
					if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_size < len(FINISHED) or \
							getattr(info, 'st_file_attributes', 0) & 0x400:
						continue
					with open(entry.path, 'rb') as source:
						source.seek(-len(FINISHED), os.SEEK_END)
						if source.read() != FINISHED:
							continue
				except FileNotFoundError:
					continue
				completed.append(entry.name)
		for name in sorted(completed, reverse=True)[max(0, count - 1):]:
			path = self.path.parent / name
			info = os.lstat(path)
			if stat.S_ISREG(info.st_mode) and info.st_nlink == 1 and not getattr(info, 'st_file_attributes', 0) & 0x400:
				path.unlink()