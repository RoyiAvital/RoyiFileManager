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

	def test_name_only_modes_eligibility_recursion_and_limits(self):
		from search_file_content.engine import Options, Runner
		self.write('report.txt', b'')
		self.write('skip.txt', b'')
		self.write('nested/report.txt', b'\x00binary')
		self.write('.report.txt', b'')
		self.write('.hidden/report.txt', b'')
		self.write('report-large.txt', b'x' * 11)
		if os.name == 'nt':
			import ctypes
			for path in (self.write('attribute-report.txt', b''), self.write('attribute/report.txt', b'').parent):
				original = os.stat(path).st_file_attributes
				self.assertTrue(ctypes.windll.kernel32.SetFileAttributesW(str(path), original | 2))
				self.addCleanup(ctypes.windll.kernel32.SetFileAttributesW, str(path), original)
		for mode, pattern in (('glob', '*.txt;!skip*'), ('literal', 'report'), ('regex', 'report.*\\.txt$')):
			for recursive in (False, True):
				with self.subTest(mode=mode, recursive=recursive):
					result = Runner(Options(str(self.root), '', pattern, name_mode=mode,
						recursive=recursive, max_file_bytes=10, max_file_lines=1)).run()
					self.assertEqual('Complete', result.status, result.reason)
					expected = {'report.txt', os.path.join('nested', 'report.txt')} if recursive else {'report.txt'}
					self.assertEqual(expected, {hit.relative_path for hit in result.rows})
		for index in range(5):
			self.write('report%d.txt' % index, b'')
		for mode, pattern in (('glob', '*.txt'), ('literal', 'report'), ('regex', '^report')):
			runner = Runner(Options(str(self.root), '', pattern, name_mode=mode, max_rows=3))
			result = runner.run()
			self.assertEqual('Limited', result.status, result.reason)
			self.assertEqual(3, len(result.rows))
			self.assertEqual(set(), runner.children)

	def test_name_only_preflight_processes_and_invalid_regex(self):
		from search_file_content.engine import Options, Runner
		from unittest.mock import patch
		for mode, pattern in (('glob', '*.txt'), ('literal', 'report'), ('regex', '^report')):
			for content in ('', 'needle'):
				with self.subTest(mode=mode, content=content):
					runner = Runner(Options(str(self.root), content, pattern, name_mode=mode))
					with patch('search_file_content.engine.subprocess.Popen', wraps=subprocess.Popen) as popen:
						runner.preflight()
					self.assertEqual(int(bool(content)) + int(mode != 'glob'), popen.call_count)
		with patch('search_file_content.engine.subprocess.Popen', wraps=subprocess.Popen) as popen:
			result = Runner(Options(str(self.root), '', '[', name_mode='regex')).run()
			self.assertEqual('Error', result.status)
			self.assertFalse(result.validated)
			self.assertEqual(1, popen.call_count)
			self.assertNotIn('--files', popen.call_args.args[0])
		with patch('search_file_content.engine.subprocess.Popen') as popen:
			with self.assertRaises(ValueError):
				Options(str(self.root), '')
			popen.assert_not_called()

	def test_name_only_live_progress_and_stop_while_enumerating(self):
		from search_file_content.engine import Options, Runner
		from threading import Event, Thread
		from unittest.mock import patch
		for index in range(129):
			self.write('report%d.txt' % index, b'')
		command = [sys.executable, '-c',
			"import os, sys; from threading import Event; "
			"sys.stdout.buffer.write(b''.join(os.fsencode(os.path.join(sys.argv[1], 'report%d.txt' % index)) + b'\\x00' for index in range(129))); "
			"sys.stdout.flush(); Event().wait()", str(self.root)]
		for mode, pattern in (('glob', '*.txt'), ('literal', 'report'), ('regex', '^report')):
			with self.subTest(mode=mode):
				runner = Runner(Options(str(self.root), '', pattern, name_mode=mode))
				progress, finished = Event(), Event()
				results = []
				original_publish = runner.publish
				def publish(phase='Searching'):
					original_publish(phase)
					if runner.progress.files:
						progress.set()
				def run():
					try:
						results.append(runner.run())
					finally:
						finished.set()
				with patch.object(runner, 'file_args', return_value=command), \
						patch.object(runner, 'publish', side_effect=publish), \
						patch('search_file_content.engine.subprocess.Popen', wraps=subprocess.Popen):
					worker = Thread(target=run, daemon=True)
					worker.start()
					try:
						self.assertTrue(progress.wait(5), 'No progress during blocked enumeration')
						self.assertFalse(finished.is_set())
						self.assertGreater(runner.progress.files, 0)
						children = tuple(runner.children)
					finally:
						runner.stop()
						worker.join(5)
						self.assertFalse(worker.is_alive())
					self.assertEqual('Stopped', results[0].status)
					self.assertTrue(results[0].rows)
					self.assertEqual(set(), runner.children)
					self.assertTrue(all(child.process.poll() is not None for child in children))

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