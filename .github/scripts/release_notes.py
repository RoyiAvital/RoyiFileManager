"""
Extract the CHANGELOG.md section for one version and validate release
readiness. Used by .github/workflows/release.yml; runnable locally:

    python .github/scripts/release_notes.py --version 0.2.0
"""
import argparse
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CHANGELOG = ROOT / 'CHANGELOG.md'
API_STATEMENT = re.compile(r'^API compatibility:.*$', re.MULTILINE)


def _section_body(changelog_text, match):
	start = match.end()
	next_heading = re.compile(r'^## ', re.MULTILINE).search(changelog_text, start)
	end = next_heading.start() if next_heading else len(changelog_text)
	return changelog_text[start:end].strip()


def extract_section(changelog_text, version):
	heading = re.compile(
		r'^## \[' + re.escape(version) + r'\](?: - (\d{4}-\d{2}-\d{2}))?[ \t]*$',
		re.MULTILINE
	)
	match = heading.search(changelog_text)
	if match is None:
		raise SystemExit(
			f'CHANGELOG.md has no "## [{version}]" section. Move the '
			f'"## [Unreleased]" entries under "## [{version}] - YYYY-MM-DD" '
			'before tagging.'
		)
	if match.group(1) is None:
		raise SystemExit(f'"## [{version}]" is missing its release date.')
	section = _section_body(changelog_text, match)
	if not section:
		raise SystemExit(f'"## [{version}]" has no content.')
	if API_STATEMENT.search(section) is None:
		raise SystemExit(
			f'"## [{version}]" lacks the required "API compatibility:" statement.'
		)
	return section, match.group(1)


def extract_unreleased(changelog_text):
	match = re.search(r'^## \[Unreleased\][ \t]*$', changelog_text, re.MULTILINE)
	if match is None:
		raise SystemExit('CHANGELOG.md has no "## [Unreleased]" section.')
	section = _section_body(changelog_text, match)
	if API_STATEMENT.search(section) is None:
		raise SystemExit(
			'"## [Unreleased]" lacks the required "API compatibility:" '
			'statement.'
		)
	return section


def check_unreleased_is_empty(changelog_text):
	section = extract_unreleased(changelog_text)
	leftover = API_STATEMENT.sub('', section).strip()
	if leftover:
		raise SystemExit(
			'"## [Unreleased]" still contains entries. Move them into the '
			'version section before tagging a release.'
		)


def main():
	parser = argparse.ArgumentParser(description=__doc__)
	parser.add_argument('--version', required=True, help='e.g. 0.2.0')
	parser.add_argument(
		'--output', type=Path, help='write the notes here (default: stdout)'
	)
	parser.add_argument(
		'--dry-run', action='store_true',
		help='extract Unreleased without requiring a versioned release section'
	)
	args = parser.parse_args()
	text = CHANGELOG.read_text(encoding='utf-8')
	if args.dry_run:
		section = extract_unreleased(text)
		notes = f'Dry run for {args.version}.\n\n{section}\n'
	else:
		section, date = extract_section(text, args.version)
		check_unreleased_is_empty(text)
		notes = f'Released {date}.\n\n{section}\n'
	if args.output:
		args.output.parent.mkdir(parents=True, exist_ok=True)
		args.output.write_text(notes, encoding='utf-8')
	else:
		sys.stdout.write(notes)


if __name__ == '__main__':
	main()
