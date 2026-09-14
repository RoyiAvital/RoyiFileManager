import hashlib
import importlib.util
from io import BytesIO
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import patch

import build


ROOT = Path(__file__).resolve().parents[4]
RELEASE_NOTES_PATH = ROOT / '.github' / 'scripts' / 'release_notes.py'
WORKFLOW_PATH = ROOT / '.github' / 'workflows' / 'release.yml'
SPEC = importlib.util.spec_from_file_location('release_notes', RELEASE_NOTES_PATH)
release_notes = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(release_notes)


class RipgrepPackagingTest(TestCase):
	def test_spec_includes_conda_executable_and_notices_directly(self):
		from types import SimpleNamespace
		from unittest.mock import Mock
		from PyInstaller.utils.hooks import conda_support
		specification = ROOT / 'RoyiFileManager.spec'
		code = compile(specification.read_text(encoding='utf-8'), str(specification), 'exec')
		namespace = {name: Mock() for name in ('Analysis', 'PYZ', 'EXE', 'COLLECT')}
		package = SimpleNamespace(raw={'link': {'source': 'C:\\cache\\ripgrep'}})
		with patch('PyInstaller.utils.hooks.collect_all', return_value=([], [], [])), \
				patch.object(conda_support, 'distribution', return_value=package), \
				patch('sys.prefix', 'C:\\conda'):
			exec(code, namespace)
		inputs = namespace['Analysis'].call_args.kwargs
		self.assertIn(('C:\\conda\\bin\\rg.exe', 'resources/Plugins/SearchFileContent/bin'), inputs['binaries'])
		self.assertIn(('C:\\cache\\ripgrep\\info\\licenses', 'resources/Plugins/SearchFileContent/licenses'), inputs['datas'])
		self.assertFalse(hasattr(build, '_ripgrep_payload'))

	def test_build_adds_search_plugin_pythonpath(self):
		self.assertIn('SearchFileContent', build._environment()['PYTHONPATH'])


class SevenZipVerificationTest(TestCase):
	def test_versioned_urls_and_hashes_are_pinned(self):
		self.assertEqual('26.03', build.SEVEN_ZIP_VERSION)
		self.assertEqual(
			'https://github.com/ip7z/7zip/releases/download/26.03/7zr.exe',
			build.SEVEN_ZIP_EXTRACTOR_URL
		)
		self.assertEqual(64, len(build.SEVEN_ZIP_EXTRACTOR_SHA256))
		self.assertEqual(64, len(build.SEVEN_ZIP_ARCHIVE_SHA256))
		self.assertEqual(64, len(build.SEVEN_ZIP_BINARY_SHA256))

	def test_download_verifies_content(self):
		content = b'verified download'
		expected = hashlib.sha256(content).hexdigest()
		with TemporaryDirectory() as directory:
			destination = Path(directory) / 'download.bin'
			with patch('build.urlopen', return_value=BytesIO(content)), \
					patch('build.time.sleep') as sleep:
				build._download('https://example.invalid/file', destination, expected)
			sleep.assert_called_once_with(build.DOWNLOAD_SETTLE_SECONDS)
			self.assertEqual(content, destination.read_bytes())

	def test_download_removes_hash_mismatch(self):
		with TemporaryDirectory() as directory:
			destination = Path(directory) / 'download.bin'
			with patch('build.urlopen', return_value=BytesIO(b'untrusted')):
				with self.assertRaises(SystemExit):
					build._download(
						'https://example.invalid/file', destination, '0' * 64
					)
			self.assertFalse(destination.exists())

	def test_ensure_7za_replaces_stale_binary(self):
		payload = b'pinned 7za payload'
		expected = hashlib.sha256(payload).hexdigest()

		def extract(command, **kwargs):
			extracted = Path(command[3][2:]) / 'x64'
			extracted.mkdir(parents=True)
			(extracted / '7za.exe').write_bytes(payload)

		with TemporaryDirectory() as directory:
			destination = Path(directory) / '7za.exe'
			destination.write_bytes(b'stale')
			with patch.object(build, 'SEVEN_ZIP_BINARY_SHA256', expected), \
					patch('build._download'), patch('build.subprocess.run', extract):
				build._ensure_7za(destination)
			self.assertEqual(payload, destination.read_bytes())


class CondaLockTest(TestCase):
	def test_ci_uses_existing_lock_regardless_of_mtime(self):
		with TemporaryDirectory() as directory:
			directory = Path(directory)
			environment = directory / 'environment.yml'
			lock = directory / 'conda-lock.yml'
			lock.write_text('committed lock', encoding='utf-8')
			environment.write_text('newer environment', encoding='utf-8')
			with patch.object(build, 'ENVIRONMENT_PATH', environment), \
					patch.object(build, 'CONDA_LOCK_PATH', lock), \
					patch.dict('os.environ', {'CI': 'true'}), \
					patch('build.shutil.which') as which:
				build._ensure_conda_lock()
			which.assert_not_called()
			self.assertEqual('committed lock', lock.read_text(encoding='utf-8'))

	def test_ci_fails_when_committed_lock_is_missing(self):
		with TemporaryDirectory() as directory:
			directory = Path(directory)
			environment = directory / 'environment.yml'
			environment.write_text('environment', encoding='utf-8')
			with patch.object(build, 'ENVIRONMENT_PATH', environment), \
					patch.object(build, 'CONDA_LOCK_PATH', directory / 'missing.yml'), \
					patch.dict('os.environ', {'CI': 'true'}):
				with self.assertRaisesRegex(SystemExit, 'committed conda-lock.yml'):
					build._ensure_conda_lock()


class ReleaseNotesTest(TestCase):
	def test_extract_versioned_section(self):
		text = (
			'## [Unreleased]\n\nAPI compatibility: Preserved.\n\n'
			'## [1.2.3] - 2026-09-13\n\n'
			'API compatibility: Preserved.\n\n### Fixed\n\n- Release fix.\n'
		)
		section, date = release_notes.extract_section(text, '1.2.3')
		self.assertEqual('2026-09-13', date)
		self.assertIn('- Release fix.', section)

	def test_empty_unreleased_accepts_only_api_statement(self):
		text = (
			'## [Unreleased]\n\nAPI compatibility: Preserved.\n\n'
			'## [1.0.0] - 2026-09-13\n\nAPI compatibility: Preserved.\n'
		)
		release_notes.check_unreleased_is_empty(text)

	def test_unreleased_heading_or_prose_blocks_release(self):
		for content in ('### Changed', 'Unbulleted release work.', '- Release work.'):
			with self.subTest(content=content):
				text = (
					'## [Unreleased]\n\nAPI compatibility: Preserved.\n\n'
					f'{content}\n\n## [1.0.0] - 2026-09-13\n'
				)
				with self.assertRaises(SystemExit):
					release_notes.check_unreleased_is_empty(text)

	def test_dry_run_extracts_unreleased_content(self):
		text = (
			'## [Unreleased]\n\nAPI compatibility: Preserved.\n\n- Pending.\n\n'
			'## [1.0.0] - 2026-09-13\n\nAPI compatibility: Preserved.\n'
		)
		self.assertIn('- Pending.', release_notes.extract_unreleased(text))


class ReleaseWorkflowTest(TestCase):
	def test_workflow_enforces_release_invariants(self):
		workflow = WORKFLOW_PATH.read_text(encoding='utf-8')
		for expected in (
			'permissions:\n  contents: read',
			'lfs: true',
			'Verify Git LFS assets',
			'Icon.ico is not a materialized ICO file',
			'git fetch --force origin',
			'git cat-file -t',
			'contents: write',
			'gh release view',
			"'release', 'create'",
			"'--verify-tag'",
			'Package command failed with exit code $LASTEXITCODE.',
			'RELEASE_VERSION: ${{ needs.build.outputs.version }}',
			'if: github.ref_type == \'tag\'',
			'actions/checkout@d23441a48e516b6c34aea4fa41551a30e30af803',
			'actions/upload-artifact@330a01c490aca151604b8cf639adc76d48f6c5d4',
			'actions/download-artifact@018cc2cf5baa6db3ef3c5f8a56943fffe632ef53'
		):
			self.assertIn(expected, workflow)
		self.assertNotIn('softprops/action-gh-release', workflow)
		self.assertNotRegex(workflow, r'uses: [^\n]+@v\d')