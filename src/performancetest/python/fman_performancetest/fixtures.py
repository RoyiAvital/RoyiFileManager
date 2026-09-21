"""Content-verified synthetic fixtures independent of private datasets."""

from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import struct
import sys
import zlib

from fman_performancetest.records import digest


EPOCH_NS = 1704067200 * 1_000_000_000
ASSETS = ('preview-small.png', 'preview-large.png', 'preview-small.jpg',
	'preview-small.bmp', 'preview-invalid.png', 'preview-unsupported.txt')


def png(width, height):
	def chunk(kind, data):
		return struct.pack('!I', len(data)) + kind + data + struct.pack('!I', zlib.crc32(kind + data))
	rows = bytearray()
	for row in range(height):
		rows.append(0)
		for column in range(width):
			rows.extend((30 + (column // 32 % 2) * 20, 160 + (row // 32 % 2) * 30, 60))
	header = struct.pack('!IIBBBBB', width, height, 8, 2, 0, 0, 0)
	return b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', header) + chunk(b'IDAT', zlib.compress(rows, 6)) + chunk(b'IEND', b'')


def assets():
	from PyQt5.QtCore import QBuffer, QIODevice
	from PyQt5.QtGui import QImage
	result = {ASSETS[0]: png(1280, 960), ASSETS[1]: png(4096, 3072),
		ASSETS[4]: b'Not a PNG\n', ASSETS[5]: b'Unsupported preview\n'}
	image = QImage.fromData(result[ASSETS[0]], 'PNG')
	for name, format_ in ((ASSETS[2], 'JPG'), (ASSETS[3], 'BMP')):
		buffer = QBuffer()
		buffer.open(QIODevice.WriteOnly)
		if not image.save(buffer, format_, 90):
			raise RuntimeError('Image encoder unavailable: ' + format_)
		result[name] = bytes(buffer.data())
	return result


def entries(specification, image_assets):
	for index in range(specification['files']):
		if index < len(ASSETS) and specification['kind'] == 'flat':
			name = ASSETS[index]
			yield name, image_assets[name]
			continue
		token = hashlib.sha256(('%d:%d' % (specification['seed'], index)).encode('ascii')).hexdigest()
		stem = ('common_' + 'a' * 72, 'ab' * 42, 'annual report 2026 final',
			'!tmp_[draft]_backup', 'Stra\u00dfe_cafe\u0301_CAF\u00c9',
			'archive_000000000000001_99999999999999', 'project.src--release__', token[:32])[index % 8]
		name = '%s_%s_%08d%s' % (stem, token[:24], index, ('.txt', '.pdf', '.py', '.jpg')[(index // 8) % 4])
		if specification['kind'] == 'recursive':
			levels = '/'.join('level_%02d' % level for level in range(1 + index % 4))
			name = 'branch_%02d/%s/%s' % (index % 16, levels, name)
		yield name, b''


def set_metadata(path):
	os.utime(path, ns=(EPOCH_NS, EPOCH_NS))
	if sys.platform == 'win32':
		from ntsecuritycon import FILE_WRITE_ATTRIBUTES
		import win32con
		import win32file
		flags = win32con.FILE_FLAG_BACKUP_SEMANTICS if path.is_dir() else 0
		handle = win32file.CreateFile(str(path), FILE_WRITE_ATTRIBUTES,
			win32con.FILE_SHARE_READ | win32con.FILE_SHARE_WRITE | win32con.FILE_SHARE_DELETE,
			None, win32con.OPEN_EXISTING, flags, None)
		try:
			stamp = datetime(2024, 1, 1, tzinfo=timezone.utc)
			win32file.SetFileTime(handle, stamp, stamp, stamp)
		finally:
			handle.Close()
		win32file.SetFileAttributes(str(path), win32con.FILE_ATTRIBUTE_NORMAL if path.is_dir() else win32con.FILE_ATTRIBUTE_ARCHIVE)


def verify(directory, expected):
	remaining = set(expected)
	expected_directories = {Path('.')}
	for relative in expected:
		expected_directories.update(Path(relative).parents)
	for root, directories, files in os.walk(directory, followlinks=False):
		folder = Path(root)
		if folder.relative_to(directory) not in expected_directories:
			raise ValueError('Unexpected fixture directory')
		info = folder.stat()
		if info.st_mtime_ns != EPOCH_NS:
			raise ValueError('Modified fixture directory timestamp')
		if sys.platform == 'win32' and (info.st_file_attributes != 16 or info.st_birthtime_ns != EPOCH_NS):
			raise ValueError('Modified fixture directory metadata')
		for name in directories:
			path = folder / name
			if path.is_symlink() or path.is_junction():
				raise ValueError('Fixture directory links are forbidden')
		for name in files:
			path = folder / name
			relative = path.relative_to(directory).as_posix()
			if relative not in remaining or path.is_symlink():
				raise ValueError('Unexpected fixture file: ' + relative)
			info = path.stat()
			row = expected[relative]
			if info.st_size != row['size'] or info.st_mtime_ns != EPOCH_NS or hashlib.sha256(path.read_bytes()).hexdigest() != row['sha256']:
				raise ValueError('Modified fixture file: ' + relative)
			if sys.platform == 'win32' and (info.st_file_attributes != 32 or info.st_birthtime_ns != EPOCH_NS):
				raise ValueError('Modified fixture metadata: ' + relative)
			remaining.remove(relative)
	if remaining:
		raise ValueError('Missing fixture files: %d' % len(remaining))


def prepare(base, identity, specification, image_assets=None):
	if not identity or Path(identity).name != identity or identity in ('.', '..'):
		raise ValueError('Invalid fixture ID')
	if specification['revision'] != 1 or specification['kind'] not in ('flat', 'recursive') or specification['files'] < 8:
		raise ValueError('Invalid fixture specification')
	image_assets = assets() if image_assets is None else image_assets
	root = Path(base).resolve() / identity
	directory, manifest = root / 'data', root / 'manifest.json'
	expected = {name: dict(size=len(data), sha256=hashlib.sha256(data).hexdigest())
		for name, data in entries(specification, image_assets)}
	definition = dict(generator='sha256-names-rgb-bands-v1', specification=specification,
		mtime_ns=EPOCH_NS, creation_ns=EPOCH_NS, file_attributes=32, entries=expected)
	fingerprint = digest(definition)
	if root.exists():
		if root.is_symlink() or root.is_junction() or directory.is_symlink() or directory.is_junction() or not manifest.is_file():
			raise ValueError('Unowned or incomplete fixture: ' + identity)
		if json.loads(manifest.read_text(encoding='utf-8')) != definition:
			raise ValueError('Fixture specification or generated bytes changed: ' + identity)
	else:
		directory.mkdir(parents=True)
		for name, data in entries(specification, image_assets):
			path = directory / name
			path.parent.mkdir(parents=True, exist_ok=True)
			with path.open('xb') as output:
				output.write(data)
			set_metadata(path)
		for folder, directories, files in os.walk(directory, topdown=False):
			set_metadata(Path(folder))
		manifest.write_text(json.dumps(definition, sort_keys=True, ensure_ascii=True) + '\n', encoding='utf-8')
	verify(directory, expected)
	return dict(id=identity, sha256=fingerprint, specification=specification, directory=str(directory))