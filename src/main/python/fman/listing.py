from collections import Counter
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Listing:
	location: str
	names: tuple
	is_dir: tuple
	sizes: tuple
	mtimes_ns: tuple
	attributes: tuple
	created_ns: tuple
	identities: bytes
	scope: tuple
	labels: object = None
	extra: tuple = ()

	@classmethod
	def create(cls, location, names, *, is_dir=None, sizes=None, mtimes_ns=None,
		attributes=None, created_ns=None, identities=None, scope=None, labels=None, extra=()):
		names = tuple(names)
		count = len(names)
		zeros = (0,) * count
		return cls(location, names, (False,) * count if is_dir is None else is_dir,
			(None,) * count if sizes is None else sizes,
			(None,) * count if mtimes_ns is None else mtimes_ns,
			zeros if attributes is None else attributes,
			zeros if created_ns is None else created_ns,
			bytes(16 * count) if identities is None else identities,
			(0, bytes(16)) if scope is None else scope, labels, extra)

	@property
	def display_names(self):
		return self.names if self.labels is None else self.labels

	def column(self, name):
		for key, values in self.extra:
			if key == name:
				return values
		raise KeyError(name)

	def __post_init__(self):
		for field in ('names', 'is_dir', 'sizes', 'mtimes_ns', 'attributes', 'created_ns'):
			object.__setattr__(self, field, tuple(getattr(self, field)))
		count = len(self.names)
		if any(len(getattr(self, field)) != count for field in
			('is_dir', 'sizes', 'mtimes_ns', 'attributes', 'created_ns')):
			raise ValueError('Listing column lengths differ')
		if any(type(name) is not str or not name or name in ('.', '..') or
			'/' in name or '\\' in name or '\x00' in name for name in self.names):
			raise ValueError('Invalid directory entry name')
		if len(set(self.names)) != count:
			raise ValueError('Duplicate directory entry name')
		if any(type(value) is not bool for value in self.is_dir):
			raise ValueError('Invalid directory flag')
		for field in ('sizes', 'mtimes_ns', 'attributes', 'created_ns'):
			if any(type(value) is not int and not (value is None and field in ('sizes', 'mtimes_ns'))
				for value in getattr(self, field)):
				raise ValueError('Invalid numeric listing column: ' + field)
		if any(value is not None and value < 0 for value in self.sizes):
			raise ValueError('Negative file size')
		if type(self.identities) is not bytes or len(self.identities) != count * 16:
			raise ValueError('Expected packed 128-bit identities')
		if type(self.scope) is not tuple or len(self.scope) != 2 or \
			type(self.scope[0]) is not int or type(self.scope[1]) is not bytes or \
			len(self.scope[1]) != 16:
			raise ValueError('Invalid directory identity scope')
		if self.labels is not None:
			object.__setattr__(self, 'labels', tuple(self.labels))
			if len(self.labels) != count or any(type(value) is not str for value in self.labels):
				raise ValueError('Invalid display labels')
		object.__setattr__(self, 'extra', tuple((key, tuple(values)) for key, values in self.extra))
		keys = set()
		for key, values in self.extra:
			if type(key) is not str or not key or key in keys or len(values) != count or \
				any(value is not None and type(value) not in (str, int, float, bool, bytes) for value in values):
				raise ValueError('Invalid provider column')
			keys.add(key)

	def identity(self, index):
		return self.identities[index * 16:(index + 1) * 16], self.created_ns[index]


def reconcile(previous, current, check_canceled=lambda: None) -> dict | None:
	"""Return safe old-to-new indices, or None if every entry keeps its index."""
	if previous.location != current.location or previous.scope != current.scope:
		return {}
	same_names = previous.names == current.names
	if same_names and previous.identities == current.identities and previous.created_ns == current.created_ns:
		unknown = bytes(16)
		offset = 0
		while True:
			check_canceled()
			offset = previous.identities.find(unknown, offset)
			if offset < 0:
				return None
			if offset % 16 == 0:
				break
			offset += 16 - offset % 16
		result = {}
		for start in range(0, len(previous.names), 256):
			check_canceled()
			result.update((index, index) for index in range(start, min(start + 256, len(previous.names)))
				if previous.identities[index * 16:(index + 1) * 16] != unknown)
		return result
	exact = {} if same_names else {name: index for index, name in enumerate(current.names)}
	result = {}
	pending = []
	for index, name in enumerate(previous.names):
		if index % 256 == 0:
			check_canceled()
		identity, created = previous.identity(index)
		if not any(identity):
			continue
		target = index if same_names else exact.get(name)
		if target is not None and current.identity(target) == (identity, created):
			result[index] = target
		else:
			pending.append((index, identity, created))
	if not pending:
		return result
	needed = {identity for index, identity, created in pending}
	old_counts = Counter()
	for index in range(len(previous.names)):
		if index % 256 == 0:
			check_canceled()
		identity = previous.identities[index * 16:(index + 1) * 16]
		if identity in needed:
			old_counts[identity] += 1
	unique = {}
	for index in range(len(current.names)):
		if index % 256 == 0:
			check_canceled()
		identity = current.identities[index * 16:(index + 1) * 16]
		if identity in needed:
			unique[identity] = None if identity in unique else index
	for offset, (index, identity, created) in enumerate(pending):
		if offset % 256 == 0:
			check_canceled()
		target = unique.get(identity) if old_counts[identity] == 1 else None
		if target is not None and current.identity(target) == (identity, created):
			result[index] = target
	return result