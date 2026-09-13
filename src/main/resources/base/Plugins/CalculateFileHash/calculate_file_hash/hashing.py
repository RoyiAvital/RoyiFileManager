from typing import NamedTuple

import hashlib
import os
import zlib


ALGORITHMS = (
	('sha256', 'SHA-256'), ('sha1', 'SHA-1 (legacy)'), ('md5', 'MD5 (legacy)'),
	('sha384', 'SHA-384'), ('sha512', 'SHA-512'),
	('sha3_256', 'SHA3-256'), ('sha3_512', 'SHA3-512'),
	('blake2b', 'BLAKE2b'), ('blake2s', 'BLAKE2s'), ('crc32', 'CRC32 (non-cryptographic)'),
)
DEFAULT_FALLBACK_ORDER = ('sha256', 'sha512', 'sha384', 'sha3_256', 'sha3_512', 'blake2b', 'blake2s')
DEFAULTS = {'default_algorithm': 'sha256', 'remember_last_algorithm': False, 'auto_copy': False, 'chunk_size_mib': 4}


def available_algorithms():
	available = []
	for identifier, label in ALGORITHMS:
		try:
			if identifier != 'crc32':
				hashlib.new(identifier)
		except ValueError:
			continue
		available.append((identifier, label))
	return tuple(available)


AVAILABLE_ALGORITHMS = available_algorithms()


def settings_snapshot(values):
	settings = dict(DEFAULTS)
	if isinstance(values, dict):
		settings.update(values)
	chunk_size = settings['chunk_size_mib']
	settings['chunk_size_mib'] = max(1, min(chunk_size, 64)) if type(chunk_size) is int else 4
	for key in ('remember_last_algorithm', 'auto_copy'):
		settings[key] = settings[key] is True
	return settings


def default_algorithm(configured, algorithms=AVAILABLE_ALGORITHMS):
	names = tuple(identifier for identifier, label in algorithms)
	if isinstance(configured, str) and configured in names:
		return configured
	for identifier in DEFAULT_FALLBACK_ORDER:
		if identifier in names:
			return identifier
	raise ValueError('No supported strong hash algorithm is available. Choose an algorithm explicitly.')


class HashResult(NamedTuple):
	digest: str
	bytes_read: int
	changed: bool


def _identity(info):
	return info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns


def compute_hash(path, algorithm, report, check_canceled, chunk_size=4 * 1024 * 1024):
	if type(chunk_size) is not int or chunk_size <= 0:
		raise ValueError('Chunk size must be a positive integer.')
	if algorithm not in tuple(identifier for identifier, label in AVAILABLE_ALGORITHMS):
		raise ValueError('Unsupported hash algorithm: %s' % algorithm)
	check_canceled()
	digest = None if algorithm == 'crc32' else hashlib.new(algorithm)
	checksum = 0
	bytes_read = 0
	with open(path, 'rb') as source:
		before = os.fstat(source.fileno())
		report(0)
		while True:
			check_canceled()
			chunk = source.read(chunk_size)
			if not chunk:
				break
			if digest is None:
				checksum = zlib.crc32(chunk, checksum)
			else:
				digest.update(chunk)
			bytes_read += len(chunk)
			report(bytes_read)
		check_canceled()
		after = os.fstat(source.fileno())
	current = os.stat(path)
	check_canceled()
	changed = _identity(before) != _identity(after) or _identity(before) != _identity(current) or bytes_read != before.st_size
	value = '%08X' % (checksum & 0xffffffff) if digest is None else digest.hexdigest()
	return HashResult(value, bytes_read, changed)