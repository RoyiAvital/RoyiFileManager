from contextlib import redirect_stdout
from importlib.util import module_from_spec, spec_from_file_location
from io import StringIO
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[4]
SPEC = spec_from_file_location('release_notes', ROOT / '.github/scripts/release_notes.py')
release_notes = module_from_spec(SPEC)
SPEC.loader.exec_module(release_notes)


class ReleaseNotesTest(TestCase):
	def test_accepts_only_required_headings(self):
		text = '# Changelog\n\n## [Unreleased]\n\n## [0.9.0]\n'
		self.assertEqual(('', None), release_notes.extract_section(text, '0.9.0'))
		self.assertEqual('', release_notes.extract_unreleased(text))

	def test_extracts_dated_free_form_release(self):
		section = 'Release summary.\n\n### API Compatibility\n\nChanged contracts.\n\n### Added\n\n- Feature.'
		text = f'## [Unreleased]\n\n## [0.9.0] - 2026-09-22\n\n{section}\n\n## [0.8.1]\n\nOlder notes.'
		self.assertEqual((section, '2026-09-22'), release_notes.extract_section(text, '0.9.0'))

	def test_unreleased_entries_are_separate_from_release(self):
		text = '## [Unreleased]\n\nDraft notes.\n\n## [0.9.0]\n\nReleased notes.'
		self.assertEqual(('Released notes.', None), release_notes.extract_section(text, '0.9.0'))
		self.assertEqual('Draft notes.', release_notes.extract_unreleased(text))

	def test_requires_unreleased(self):
		text = '## [0.9.0]\n\nReleased notes.'
		with self.assertRaisesRegex(SystemExit, 'has no .*Unreleased'):
			release_notes.extract_section(text, '0.9.0')
		with self.assertRaisesRegex(SystemExit, 'has no .*Unreleased'):
			release_notes.extract_unreleased(text)

	def test_requires_unreleased_first(self):
		text = '## [0.9.0]\n\nReleased notes.\n\n## [Unreleased]\n'
		with self.assertRaisesRegex(SystemExit, 'must be the first'):
			release_notes.extract_section(text, '0.9.0')
		with self.assertRaisesRegex(SystemExit, 'must be the first'):
			release_notes.extract_unreleased(text)

	def test_requires_exact_version_heading(self):
		for heading in ('## [0.9.01]', '## [0x9x0]', '### [0.9.0]'):
			with self.subTest(heading=heading):
				with self.assertRaisesRegex(SystemExit, 'has no .*0.9.0'):
					release_notes.extract_section(f'## [Unreleased]\n\n{heading}\n\nNotes.', '0.9.0')

	def test_cli_accepts_optional_date(self):
		for suffix, expected in (
			('', 'Released notes.\n'),
			(' - 2026-09-22', 'Released 2026-09-22.\n\nReleased notes.\n')
		):
			with self.subTest(suffix=suffix):
				text = f'## [Unreleased]\n\nDraft notes.\n\n## [0.9.0]{suffix}\n\nReleased notes.'
				self.assertEqual(expected, self.run_cli(text))

	def test_dry_run_accepts_empty_and_populated_unreleased(self):
		for body in ('', 'Draft notes.'):
			with self.subTest(body=body):
				text = f'## [Unreleased]\n\n{body}\n\n## [0.8.1]\n\nOlder notes.'
				self.assertEqual(f'Dry run for 0.9.0.\n\n{body}\n', self.run_cli(text, '--dry-run'))

	def test_cli_writes_output_file(self):
		with TemporaryDirectory() as temporary:
			output = Path(temporary) / 'nested' / 'release-notes.md'
			text = '## [Unreleased]\n\n## [0.9.0]\n\nReleased notes.'
			self.assertEqual('', self.run_cli(text, '--output', str(output)))
			self.assertEqual('Released notes.\n', output.read_text(encoding='utf-8'))

	def run_cli(self, text, *arguments):
		with TemporaryDirectory() as temporary:
			changelog = Path(temporary) / 'CHANGELOG.md'
			changelog.write_text(text, encoding='utf-8')
			stdout = StringIO()
			with patch.object(release_notes, 'CHANGELOG', changelog), \
				patch('sys.argv', ['release_notes.py', '--version', '0.9.0', *arguments]), \
				redirect_stdout(stdout):
				release_notes.main()
			return stdout.getvalue()


class ReleaseProductNameTest(TestCase):
	def test_name_flows_from_validated_settings_to_publish_job(self):
		import yaml
		workflow = yaml.safe_load((ROOT / '.github/workflows/release.yml').read_text(encoding='utf-8'))
		build = workflow['jobs']['build']
		resolve = next(step for step in build['steps'] if step.get('id') == 'version')['run']
		self.assertIn('$appName = python src/main/python/fbs_runtime/build_settings.py', resolve)
		self.assertIn('if ($LASTEXITCODE -ne 0)', resolve)
		self.assertIn('"app-name=$appName" >> $env:GITHUB_OUTPUT', resolve)
		self.assertIn('"artifact-name=$appName-$version" >> $env:GITHUB_OUTPUT', resolve)
		self.assertEqual('${{ steps.version.outputs.app-name }}', build['outputs']['app-name'])
		publish = workflow['jobs']['publish']
		self.assertEqual('${{ needs.build.outputs.app-name }}', publish['env']['APP_NAME'])
		self.assertIn("'--title', \"$env:APP_NAME $env:RELEASE_VERSION\"", publish['steps'][-1]['run'])
