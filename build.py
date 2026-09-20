import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
from tempfile import TemporaryDirectory
import time
from urllib.error import HTTPError
from urllib.request import urlopen
from zipfile import ZIP_DEFLATED, ZipFile


ROOT = Path(__file__).resolve().parent
TARGET_DIR = ROOT / 'target'
DIST_DIR = TARGET_DIR / 'RoyiFileManager'
SETTINGS_PATH = ROOT / 'src' / 'build' / 'settings' / 'base.json'
ENVIRONMENT_PATH = ROOT / 'environment.yml'
CONDA_LOCK_PATH = ROOT / 'conda-lock.yml'
SEVEN_ZIP_VERSION = '26.03'
SEVEN_ZIP_PATH = (
	ROOT / 'src' / 'main' / 'resources' / 'base' / 'Plugins' / 'Core' /
	'bin' / 'windows' / '7za.exe'
)
SEVEN_ZIP_RELEASE_URL = (
	f'https://github.com/ip7z/7zip/releases/download/{SEVEN_ZIP_VERSION}'
)
SEVEN_ZIP_ARCHIVE_URL = (
	f'{SEVEN_ZIP_RELEASE_URL}/7z{SEVEN_ZIP_VERSION.replace(".", "")}-extra.7z'
)
SEVEN_ZIP_EXTRACTOR_URL = f'{SEVEN_ZIP_RELEASE_URL}/7zr.exe'
SEVEN_ZIP_ARCHIVE_SHA256 = \
	'191894e6acb3647ffb69ce630479ff318523b2e2b9890aa7f05c1127c2e59b8f'
SEVEN_ZIP_EXTRACTOR_SHA256 = \
	'ad4c82fadcbdf93c03b4fc440f300509c7d60c5c2f4d183e35d9d70d6957037d'
SEVEN_ZIP_BINARY_SHA256 = \
	'edbee35370e14030e4c785cf88200f42dc651c1eb4217c1e3963c38a12f099b0'
DOWNLOAD_SETTLE_SECONDS = 0.25
DOWNLOAD_RETRY_DELAYS = (1, 2, 4)


def _require_windows():
	if sys.platform != 'win32':
		raise SystemExit('RoyiFileManager is supported on Windows only.')


def _sha256(path):
	digest = hashlib.sha256()
	try:
		with path.open('rb') as file:
			for chunk in iter(lambda: file.read(1024 * 1024), b''):
				digest.update(chunk)
	except OSError:
		return None
	return digest.hexdigest()


def _verify_sha256(path, expected, description):
	actual = _sha256(path)
	if actual != expected:
		raise SystemExit(
			f'{description} failed SHA-256 verification: expected {expected}, '
			f'got {actual or "an unreadable file"}.'
		)


def _download(url, destination, expected_sha256):
	for attempt in range(len(DOWNLOAD_RETRY_DELAYS) + 1):
		verified = False
		try:
			with urlopen(url, timeout=120) as response, \
					destination.open('wb') as output:
				shutil.copyfileobj(response, output)
				output.flush()
				os.fsync(output.fileno())
			time.sleep(DOWNLOAD_SETTLE_SECONDS)
			_verify_sha256(destination, expected_sha256, url)
			verified = True
			return
		except HTTPError as error:
			error.close()
			if error.code not in (408, 429, 500, 502, 503, 504) or \
					attempt == len(DOWNLOAD_RETRY_DELAYS):
				raise
			delay = DOWNLOAD_RETRY_DELAYS[attempt]
			print(f'HTTP {error.code} downloading {url}; retrying in {delay}s...')
		finally:
			if not verified:
				destination.unlink(missing_ok=True)
		time.sleep(delay)


def _ensure_7za(destination=SEVEN_ZIP_PATH):
	destination = Path(destination)
	if _sha256(destination) == SEVEN_ZIP_BINARY_SHA256:
		return
	print(f'Downloading 7-Zip {SEVEN_ZIP_VERSION} from GitHub...')
	with TemporaryDirectory() as temporary_directory:
		temporary_directory = Path(temporary_directory)
		extractor = temporary_directory / '7zr.exe'
		archive = temporary_directory / '7zip-extra.7z'
		extracted = temporary_directory / 'extracted'
		_download(
			SEVEN_ZIP_EXTRACTOR_URL, extractor, SEVEN_ZIP_EXTRACTOR_SHA256
		)
		_download(SEVEN_ZIP_ARCHIVE_URL, archive, SEVEN_ZIP_ARCHIVE_SHA256)
		subprocess.run(
			[
				str(extractor), 'x', str(archive), f'-o{extracted}', '-y'
			],
			check=True, stdout=subprocess.DEVNULL
		)
		downloaded_7za = extracted / 'x64' / '7za.exe'
		_verify_sha256(
			downloaded_7za, SEVEN_ZIP_BINARY_SHA256,
			'The extracted x64/7za.exe'
		)
		destination.parent.mkdir(parents=True, exist_ok=True)
		temporary_destination = destination.with_suffix('.exe.tmp')
		shutil.copy2(downloaded_7za, temporary_destination)
		temporary_destination.replace(destination)


def _environment():
	environment = os.environ.copy()
	native_bin = Path(sys.prefix) / 'Library' / 'bin'
	if native_bin.is_dir():
		environment['PATH'] = os.pathsep.join(
			[str(native_bin), environment.get('PATH', '')]
		)
	paths = [
		ROOT / 'src' / 'main' / 'python',
		ROOT / 'src' / 'unittest' / 'python',
		ROOT / 'src' / 'integrationtest' / 'python',
		ROOT / 'src' / 'main' / 'resources' / 'base' / 'Plugins' / 'Core',
		ROOT / 'src' / 'main' / 'resources' / 'base' / 'Plugins' /
		'SearchFileFuzzy',
		ROOT / 'src' / 'main' / 'resources' / 'base' / 'Plugins' /
		'Favorites',
		ROOT / 'src' / 'main' / 'resources' / 'base' / 'Plugins' /
		'CalculateFileHash',
		ROOT / 'src' / 'main' / 'resources' / 'base' / 'Plugins' /
		'SearchFiles',
		ROOT / 'src' / 'main' / 'resources' / 'base' / 'Plugins' /
		'ProcessPane'
	]
	existing = environment.get('PYTHONPATH')
	if existing:
		paths.append(Path(existing))
	environment['PYTHONPATH'] = os.pathsep.join(map(str, paths))
	return environment


def run():
	_require_windows()
	_ensure_7za()
	main_script = ROOT / 'src' / 'main' / 'python' / 'fman' / 'main.py'
	subprocess.run(
		[sys.executable, str(main_script)], check=True, env=_environment()
	)


def test():
	_require_windows()
	_ensure_7za()
	environment = _environment()
	environment.setdefault('QT_QPA_PLATFORM', 'offscreen')
	windows_fonts = Path(environment.get('WINDIR', r'C:\Windows')) / 'Fonts'
	if windows_fonts.is_dir():
		environment.setdefault('QT_QPA_FONTDIR', str(windows_fonts))
	test_directories = [
		ROOT / 'src' / 'unittest' / 'python',
		ROOT / 'src' / 'integrationtest' / 'python',
		ROOT / 'src' / 'main' / 'resources' / 'base' / 'Plugins' / 'Core'
	]
	for test_directory in test_directories:
		_run_test_directory(test_directory, environment)


def _run_test_directory(test_directory, environment, *, traceback_after=120, timeout=600):
	print('Running tests in %s (timeout: %s seconds)' % (test_directory, timeout), flush=True)
	runner = (
		'import faulthandler, sys, unittest; '
		'faulthandler.dump_traceback_later(%r, repeat=True); '
		'unittest.main(module=None, testRunner=unittest.TextTestRunner('
		'stream=sys.stdout, verbosity=2))'
	) % traceback_after
	return subprocess.run(
		[
			sys.executable, '-X', 'faulthandler', '-u', '-c', runner,
			'discover', '-s', str(test_directory), '-p', 'test*.py'
		],
		check=True, env=environment, timeout=timeout
	)


def clean():
	shutil.rmtree(TARGET_DIR, ignore_errors=True)
	for cache in ROOT.rglob('__pycache__'):
		shutil.rmtree(cache, ignore_errors=True)


def _ensure_conda_lock():
	if os.environ.get('CI', '').lower() == 'true':
		if CONDA_LOCK_PATH.is_file():
			return
		raise SystemExit(
			'CI requires the committed conda-lock.yml and will not generate it.'
		)
	if CONDA_LOCK_PATH.is_file() and \
		CONDA_LOCK_PATH.stat().st_mtime_ns >= \
		ENVIRONMENT_PATH.stat().st_mtime_ns:
		return
	conda_lock = shutil.which('conda-lock')
	if conda_lock is None:
		raise SystemExit(
			'conda-lock.yml is missing or outdated, but `conda-lock` is not '
			'available in the active environment.'
		)
	print('Generating conda-lock.yml for win-64...')
	subprocess.run(
		[
			conda_lock, 'lock', '-f', str(ENVIRONMENT_PATH), '-p', 'win-64'
		],
		check=True, cwd=ROOT
	)
	if not CONDA_LOCK_PATH.is_file():
		raise SystemExit('conda-lock did not create conda-lock.yml.')


def _copy_dependency_manifests():
	if not CONDA_LOCK_PATH.is_file():
		raise SystemExit(
			'Missing conda-lock.yml. Run '
			'`conda-lock lock -f environment.yml -p win-64` first.'
		)
	shutil.copy2(ENVIRONMENT_PATH, DIST_DIR)
	shutil.copy2(CONDA_LOCK_PATH, DIST_DIR)


def _remove_previous_freeze():
	if not DIST_DIR.exists():
		return
	try:
		shutil.rmtree(DIST_DIR)
	except PermissionError as error:
		raise SystemExit(
			f'Cannot replace {DIST_DIR}. Close RoyiFileManager and ensure no '
			'terminal has this directory as its current working directory, then '
			'run `python build.py freeze` again.'
		) from error


def freeze():
	_require_windows()
	_ensure_7za()
	_ensure_conda_lock()
	_remove_previous_freeze()
	subprocess.run(
		[
			sys.executable, '-m', 'PyInstaller', '--noconfirm', '--clean',
			'--distpath', str(TARGET_DIR),
			'--workpath', str(TARGET_DIR / 'build'),
			str(ROOT / 'RoyiFileManager.spec')
		],
		check=True, cwd=ROOT, env=_environment()
	)
	(DIST_DIR / 'UserSettings').mkdir(exist_ok=True)
	_copy_dependency_manifests()


def package():
	_require_windows()
	if not DIST_DIR.is_dir():
		raise SystemExit('Run `python build.py freeze` first.')
	_copy_dependency_manifests()
	version = json.loads(SETTINGS_PATH.read_text(encoding='utf-8'))['version']
	archive = TARGET_DIR / f'RoyiFileManager-{version}-windows-x86_64.zip'
	with ZipFile(archive, 'w', ZIP_DEFLATED) as zip_file:
		for path in sorted(DIST_DIR.rglob('*')):
			archive_path = Path(DIST_DIR.name) / path.relative_to(DIST_DIR)
			if path.is_dir():
				zip_file.writestr(archive_path.as_posix() + '/', '')
			else:
				zip_file.write(path, archive_path.as_posix())
	print(archive)


def publish():
	clean()
	freeze()
	package()


COMMANDS = {
	'clean': clean,
	'freeze': freeze,
	'package': package,
	'publish': publish,
	'release': publish,
	'run': run,
	'test': test
}


def main():
	parser = argparse.ArgumentParser(description='Build RoyiFileManager.')
	parser.add_argument('command', choices=sorted(COMMANDS))
	args = parser.parse_args()
	COMMANDS[args.command]()


if __name__ == '__main__':
	main()