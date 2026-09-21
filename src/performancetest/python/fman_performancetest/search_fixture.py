import json
import os
from pathlib import Path
import random
import string


FORMAT = 'RoyiFileManager filter-find fixture v1'
FILTER_QUERIES = (
	'report', '^common', '.txt$', '!tmp', '[ab]*[0-9]$',
	'?*?*?*?*?*?*?*?Z', 'a*a*a*a*a*a*a*a*Z', '*' * 100,
	r'\[draft\]', 'report*2026*final', 'z' * 200, 'strasse',
)
FUZZY_QUERIES = (
	'rpt', 'report pdf', '^common !missing', "'report .pdf$ | .txt$ !tmp",
	'abababababababababababababababZ', "!'backup", "'annual\\ report",
	'strasse', 'caf\u00e9', '^missing$',
)
RECURSIVE_QUERIES = ('^branch_03', '^branch_02 .py$', *FUZZY_QUERIES)


def names(count, seed):
	randomizer = random.Random(seed)
	alphabet = string.ascii_letters + string.digits + '_-'
	for index in range(count):
		token = ''.join(randomizer.choices(alphabet, k=randomizer.randint(24, 72)))
		category = index % 8
		stem = (
			'common_' + 'a' * 72 + '_' + token[:24],
			'ab' * 42 + '_' + token[:24],
			'annual report 2026 final_' + token,
			'!tmp_[draft]_backup_' + token,
			'Stra\u00dfe_cafe\u0301_CAF\u00c9_' + token,
			'archive_000000000000001_99999999999999_' + token[:48],
			'project.src--release__' + token,
			token,
		)[category]
		extension = ('.txt', '.pdf', '.py', '.jpg')[(index // 8) % 4]
		yield '%s_%08d%s' % (stem, index, extension)


def relative_paths(flat_count, recursive_count, seed):
	for name in names(flat_count, seed):
		yield Path('flat') / name
	for index, name in enumerate(names(recursive_count, seed + 1)):
		folder = Path('recursive') / ('branch_%02d' % (index % 16))
		for depth in range(1 + index % 4):
			folder = folder / ('level_%02d' % depth)
		yield folder / name


def validate(directory, flat_count, recursive_count, seed):
	expected = {str(path) for path in relative_paths(flat_count, recursive_count, seed)}
	for root, directories, files in os.walk(directory):
		for child in directories:
			path = Path(root) / child
			if path.is_symlink() or path.is_junction():
				raise ValueError('Fixture contains a directory link: ' + str(path))
		for name in files:
			path = Path(root) / name
			if path == directory / 'fixture.json':
				continue
			relative = str(path.relative_to(directory))
			if relative not in expected or path.is_symlink() or path.stat().st_size:
				raise ValueError('Fixture contains an unexpected or modified file: ' + str(path))
			expected.remove(relative)
	if expected:
		raise ValueError('Fixture is incomplete: %d missing files' % len(expected))


def prepare(directory, flat_count=50_000, recursive_count=50_000, seed=1729):
	if flat_count < 1 or recursive_count < 1:
		raise ValueError('Both fixture counts must be positive')
	directory = Path(directory).resolve()
	configuration = dict(format=FORMAT, flat_count=flat_count,
		recursive_count=recursive_count, seed=seed)
	manifest = directory / 'fixture.json'
	if directory.exists():
		if manifest.is_file() and json.loads(manifest.read_text(encoding='utf-8')) == configuration:
			validate(directory, flat_count, recursive_count, seed)
			return configuration
		raise ValueError('Refusing to overwrite an existing or incomplete fixture: ' + str(directory))
	directory.mkdir(parents=True)
	flat, tree = directory / 'flat', directory / 'recursive'
	flat.mkdir()
	tree.mkdir()
	for relative in relative_paths(flat_count, recursive_count, seed):
		path = directory / relative
		path.parent.mkdir(parents=True, exist_ok=True)
		with path.open('xb'):
			pass
	manifest.write_text(json.dumps(configuration, indent=2) + '\n', encoding='utf-8')
	return configuration