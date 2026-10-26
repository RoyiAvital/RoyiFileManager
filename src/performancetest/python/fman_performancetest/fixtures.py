"""Content-verified synthetic fixtures independent of private datasets."""

from datetime import datetime, timezone
import csv
import hashlib
import io
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
TEXT_ASSETS = {
	'preview-sample.py': b'def summarize(values):\n    total = sum(values)\n    return total\n',
	'preview-sample.md': b'# Preview Report\n\n**Status:** Ready\n\n- First item\n- Second item\n\n[Project](https://example.invalid/)\n',
}
CSV_NAME = 'orders.csv'
CSV_HEADER = ('order_id', 'order_date', 'order_time', 'customer', 'email', 'phone', 'city', 'country', 'region',
	'postal_code', 'product', 'category', 'sku', 'quantity', 'unit_price', 'discount', 'tax', 'total', 'currency',
	'status', 'priority', 'channel', 'warehouse', 'carrier', 'tracking', 'weight_kg', 'latitude', 'longitude',
	'rating', 'flags', 'note', 'padding')
# Every record is padded to this many UTF-8 bytes, so the record count follows from the file size.
CSV_RECORD_BYTES = 512
CSV_NAMES = ('Avery Stone', 'Noa Levi', 'Jo\u00e3o Silva', 'Mira Patel', 'Liam Chen', 'Sara M\u00fcller',
	'Omar Haddad', 'In\u00e8s Moreau', 'Kenji Sato', 'Elena Rossi', 'Zo\u00eb Brennan', 'Bj\u00f6rk Sigur\u00f0ard\u00f3ttir')
CSV_CITIES = (('Z\u00fcrich', 'Switzerland', 'Europe'), ('Tel Aviv', 'Israel', 'Middle East'),
	('S\u00e3o Paulo', 'Brazil', 'South America'), ('Krak\u00f3w', 'Poland', 'Europe'), ('Osaka', 'Japan', 'Asia'),
	('Montr\u00e9al', 'Canada', 'North America'), ('Reykjav\u00edk', 'Iceland', 'Europe'), ('Lyon', 'France', 'Europe'))
CSV_PRODUCTS = (('Desk lamp', 'Lighting'), ('Monitor, 27"', 'Displays'), ('Keyboard', 'Input'), ('USB-C hub', 'Accessories'),
	('Office chair', 'Furniture'), ('Webcam', 'Video'), ('Standing desk', 'Furniture'), ('Headset', 'Audio'))


def csv_fields(seed, index):
	"""Fields of record `index` without padding; mixes numbers, dates, Unicode, quotes, commas and line breaks."""
	token = hashlib.sha256(('%d:%d' % (seed, index)).encode('ascii')).hexdigest()
	city, country, region = CSV_CITIES[index % len(CSV_CITIES)]
	product, category = CSV_PRODUCTS[(index // 3) % len(CSV_PRODUCTS)]
	quantity, price = 1 + index % 20, int(token[:6], 16) % 100000 / 100
	discount = index % 30 / 2
	total = quantity * price * (1 - discount / 100)
	note = 'Leave at door, ring twice' if index % 7 else 'Fragile "glass"\nCall on arrival' if index % 49 == 0 else ''
	return (str(index + 1), '%04d-%02d-%02d' % (2020 + index % 6, 1 + index % 12, 1 + index % 28),
		'%02d:%02d:%02d' % (index % 24, index * 7 % 60, index * 13 % 60), CSV_NAMES[index % len(CSV_NAMES)],
		'customer%d@example.invalid' % (index % 50000), '+1-555-%04d' % (index % 10000), city, country, region,
		token[6:11].upper(), product, category, 'SKU-' + token[11:19].upper(), str(quantity), '%.2f' % price,
		'%.1f' % discount, '%.2f' % (total * .17), '%.2f' % total, ('USD', 'EUR', 'ILS', 'JPY')[index % 4],
		('new', 'paid', 'shipped', 'delivered', 'returned')[index % 5], ('low', 'normal', 'high')[index % 3],
		('web', 'store', 'phone')[index % 3], 'WH-%02d' % (index % 12), ('DHL', 'UPS', 'FedEx', 'Post')[index % 4],
		token[19:35], '%.3f' % (int(token[35:39], 16) / 1000), '%.5f' % (int(token[39:45], 16) / 93206.75 - 90),
		'%.5f' % (int(token[45:51], 16) / 46603.375 - 180), str(1 + index % 5), ('', 'gift', 'express', 'gift express')[index % 4],
		note)


def csv_records(specification):
	return (specification['bytes'] - len(_csv_line(CSV_HEADER))) // CSV_RECORD_BYTES


def _csv_line(fields):
	stream = io.StringIO(newline='')
	csv.writer(stream, lineterminator='\r\n').writerow(fields)
	return stream.getvalue().encode('utf-8')


def csv_table(specification):
	header = _csv_line(CSV_HEADER)
	count, remainder = divmod(specification['bytes'] - len(header), CSV_RECORD_BYTES)
	chunks = [header]
	for index in range(count):
		fields = csv_fields(specification['seed'], index)
		padding = CSV_RECORD_BYTES - len(_csv_line(fields + ('',))) + (remainder if index == count - 1 else 0)
		if padding < 1:
			raise ValueError('CSV record exceeds its fixed size')
		chunks.append(_csv_line(fields + ('x' * padding,)))
	data = b''.join(chunks)
	if len(data) != specification['bytes']:
		raise AssertionError('Incorrect CSV fixture size')
	return data


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
	if specification['kind'] == 'csv':
		yield CSV_NAME, csv_table(specification)
		return
	if specification['kind'] == 'copy':
		for index in range(specification['files']):
			seed = ('%d:%d' % (specification['seed'], index)).encode('ascii')
			name = 'file_%06d.bin' % index
			if specification.get('layout', 'flat') == 'tree':
				levels = '/'.join('level_%02d' % level for level in range(1 + (index // 10) % 6))
				name = 'branch_%02d/bucket_%02d/%s/%s' % (index % 10, (index // 60) % 5, levels, name)
			yield name, hashlib.shake_256(seed).digest(specification['bytes_per_file'])
		return
	preview_assets = ASSETS + (tuple(TEXT_ASSETS) if specification['revision'] == 2 else ())
	for index in range(specification['files']):
		if index < len(preview_assets) and specification['kind'] == 'flat':
			name = preview_assets[index]
			yield name, TEXT_ASSETS[name] if name in TEXT_ASSETS else image_assets[name]
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
	if specification['kind'] == 'csv':
		if (specification['revision'] != 1 or specification['files'] != 1 or specification.get('columns') != len(CSV_HEADER) or
				type(specification.get('bytes')) is not int or not 1024 * 1024 <= specification['bytes'] <= 2 ** 31):
			raise ValueError('Invalid CSV fixture specification')
	elif specification['revision'] not in (1, 2) or specification['kind'] not in ('flat', 'recursive', 'copy') or specification['files'] < 8:
		raise ValueError('Invalid fixture specification')
	if specification['kind'] == 'copy' and (specification['revision'] != 1 or
			type(specification.get('bytes_per_file')) is not int or not 1 <= specification['bytes_per_file'] <= 1024 * 1024 or
			specification.get('layout', 'flat') not in ('flat', 'tree')):
		raise ValueError('Invalid copy fixture payload')
	if specification['revision'] == 2 and specification['kind'] != 'flat':
		raise ValueError('Text preview fixtures require flat folders')
	image_assets = {} if specification['kind'] in ('copy', 'csv') else assets() if image_assets is None else image_assets
	root = Path(base).resolve() / identity
	directory, manifest = root / 'data', root / 'manifest.json'
	expected = {name: dict(size=len(data), sha256=hashlib.sha256(data).hexdigest())
		for name, data in entries(specification, image_assets)}
	generator = {'copy': 'shake256-copy-v1', 'csv': 'csv-orders-v1'}.get(specification['kind'],
		'sha256-names-rgb-bands-v%d' % specification['revision'])
	definition = dict(generator=generator, specification=specification,
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