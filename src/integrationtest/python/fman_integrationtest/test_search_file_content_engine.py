import json
import os
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory
from unittest import TestCase


class SearchFileContentEngineTest(TestCase):
	@classmethod
	def setUpClass(cls):
		cls.executable = Path(sys.prefix) / 'bin' / 'rg.exe'

	def setUp(self):
		self.temporary = TemporaryDirectory()
		self.addCleanup(self.temporary.cleanup)
		self.root = Path(self.temporary.name)

	def write(self, name, data=b'needle\n'):
		path = self.root / name
		path.parent.mkdir(parents=True, exist_ok=True)
		path.write_bytes(data)
		return path

	def search(self, paths=None, flags=()):
		command = [str(self.executable), '--no-config', '--no-ignore',
			'--no-follow', '--no-mmap', '--json', '--line-buffered',
			'--line-number', '--crlf', '--threads', '2', *flags,
			'-e', 'needle', '--', *map(str, paths or [self.root])]
		result = subprocess.run(command, capture_output=True, timeout=10)
		self.assertIn(result.returncode, (0, 1), result.stderr.decode('utf-8', 'replace'))
		return [record['data'] for record in map(json.loads, result.stdout.splitlines())
			if record['type'] == 'match']

	def test_installed_executable_searches(self):
		self.write('match.txt')
		self.assertEqual(1, len(self.search()))

	def test_positive_glob_descends_nonmatching_directories(self):
		self.write('nested/does-not-match-mask/hit.txt')
		self.write('ignored.bin')
		matches = self.search(flags=('--iglob', '*.txt'))
		self.assertEqual(1, len(matches))
		self.assertTrue(matches[0]['path']['text'].endswith('hit.txt'))
		self.assertEqual([], self.search(flags=('--iglob', '*.txt', '--max-depth', '1')))

	def test_exclusions_override_positive_masks(self):
		self.write('keep.txt')
		self.write('omit.txt')
		matches = self.search(flags=('--iglob', '*.txt', '--iglob', '!omit.txt'))
		self.assertEqual(['keep.txt'], [Path(item['path']['text']).name for item in matches])

	def test_nul_name_regex_records_map_duplicate_basenames(self):
		result = subprocess.run([str(self.executable), '--no-config', '--null-data',
			'--json', '--line-number', '--ignore-case', '-e', r'^report\.txt$', '-'],
			input=b'report.txt\x00other.md\x00REPORT.TXT\x00', capture_output=True, timeout=10)
		self.assertEqual(0, result.returncode, result.stderr)
		matches = [record['data'] for record in map(json.loads, result.stdout.splitlines())
			if record['type'] == 'match']
		self.assertEqual([1, 3], [item['line_number'] for item in matches])
		self.assertEqual(['report.txt\x00', 'REPORT.TXT\x00'],
			[item['lines']['text'] for item in matches])

	def test_hidden_and_oversized_directory_versus_explicit_operands(self):
		hidden = self.write('.hidden.txt')
		large = self.write('large.txt', b'needle' + b'x' * 100 + b'\n')
		self.assertEqual([], self.search(flags=('--max-filesize', '16')))
		hidden_matches = self.search([hidden], ('--max-depth', '0', '--max-filesize', '16'))
		large_matches = self.search([large], ('--max-depth', '0', '--max-filesize', '16'))
		print('Explicit operands bypass flags: hidden=%s, oversized=%s' %
			(bool(hidden_matches), bool(large_matches)))
		self.assertLessEqual(len(hidden_matches), 1)
		self.assertLessEqual(len(large_matches), 1)
		self.assertEqual(1, len(self.search(flags=('--iglob', '*.txt', '--max-filesize', '16'))))

	def test_explicit_directory_at_depth_zero_is_not_traversed(self):
		self.write('nested/hit.txt')
		self.assertEqual([], self.search([self.root / 'nested'], ('--max-depth', '0')))

	def test_utf16_bom_crlf_and_binary_inputs(self):
		self.write('utf16.txt', 'needle\r\n'.encode('utf-16'))
		self.write('binary.bin', b'\x00needle\x00')
		matches = self.search(flags=('--iglob', '*.txt'))
		self.assertEqual(1, len(matches))
		self.assertEqual('needle\r\n', matches[0]['lines']['text'])
		binary_result = subprocess.run([str(self.executable), '--no-config',
			'--json', '-e', 'needle', '--', str(self.root / 'binary.bin')],
			capture_output=True, timeout=10)
		self.assertIn(binary_result.returncode, (0, 1))
		records = [json.loads(line) for line in binary_result.stdout.splitlines()]
		end = next(record['data'] for record in records if record['type'] == 'end')
		self.assertEqual(0, end['binary_offset'])
		self.assertTrue(any(record['type'] == 'match' for record in records))

	def test_symlink_directory_is_not_followed(self):
		target = self.root / 'real'
		self.write('real/hit.txt')
		link = self.root / 'alias'
		try:
			os.symlink(target, link, target_is_directory=True)
		except OSError as error:
			self.skipTest('Directory symlink capability unavailable: %s' % error)
		self.assertEqual(1, len(self.search(flags=('--iglob', '*.txt'))))

	def test_waiting_child_can_be_killed_and_reaped(self):
		process = subprocess.Popen([str(self.executable), '--no-config',
			'--json', '-e', 'needle', '-'], stdin=subprocess.PIPE,
			stdout=subprocess.PIPE, stderr=subprocess.PIPE)
		try:
			self.assertIsNone(process.poll())
			process.kill()
			process.communicate(timeout=5)
			self.assertIsNotNone(process.returncode)
		finally:
			if process.poll() is None:
				process.kill()
				process.communicate(timeout=5)