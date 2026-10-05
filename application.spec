from PyInstaller.utils.hooks import collect_all, copy_metadata
from pathlib import Path
from runpy import run_path
import os
import sys


root = Path(SPECPATH)
load_build_settings = run_path(
	str(root / 'src/main/python/fbs_runtime/build_settings.py')
)['load_build_settings']
app_name = load_build_settings(root / 'src/build/settings/base.json')['app_name']

winpty_datas, winpty_binaries, winpty_imports = collect_all('winpty')
send2trash_datas, send2trash_binaries, send2trash_imports = \
	collect_all('send2trash')
pdfium_datas, pdfium_binaries, pdfium_imports = collect_all(
	'pypdfium2', filter_submodules=lambda name: '._cli' not in name and not name.endswith('.__main__'))
pdfium_raw_datas, pdfium_raw_binaries, pdfium_raw_imports = collect_all('pypdfium2_raw')
checksum_native_files = run_path(
	str(root / 'src/main/resources/base/Plugins/ChecksumFiles/package.py')
)['native_files']()
checksum_native_destination = 'resources/Plugins/ChecksumFiles/checksum_files/_vendor/blake3'

datas = [
	('src/main/resources/base', 'resources'),
	('src/build/settings/base.json', 'resources/build-settings'),
	('src/main/resources/windows', 'resources'),
	('src/main/icons/Icon.ico', 'resources'),
	('src/main/resources/base/Plugins/Everything/bin/Everything.exe', 'resources/Plugins/Everything/bin'),
	('src/main/resources/base/Plugins/Everything/licenses/Everything.txt', 'resources/Plugins/Everything/licenses')
] + winpty_datas + send2trash_datas + pdfium_datas + pdfium_raw_datas + copy_metadata('pypdfium2') + copy_metadata('Pygments') + [
	(str(path), checksum_native_destination) for path in checksum_native_files
	if path.suffix != '.pyd'
]
binaries = winpty_binaries + send2trash_binaries + pdfium_binaries + pdfium_raw_binaries + [
	(str(Path(sys.prefix) / 'bin' / 'rg.exe'), 'resources/Plugins/SearchFiles/bin'),
	(str(Path(sys.prefix) / 'bin' / 'fd.exe'), 'resources/Plugins/FindFiles/bin'),
	# Native directory parser (Done/FSParser.md): verified by build.py against
	# src/main/c/fsparser.sha256; as a binary so PyInstaller bundles python3.dll (abi3).
	(str(root / 'src/main/c/_fsparser.pyd'), 'resources/Plugins/Core/core/fs/local/windows')
] + [
	(str(path), checksum_native_destination) for path in checksum_native_files
	if path.suffix == '.pyd'
]
hidden_imports = [
	'adodbapi', 'ctypes.wintypes', 'uuid', 'win32com.shell.shell',
	'win32com.shell.shellcon', 'win32gui', 'win32wnet', 'win32process',
	'fman.ui', 'fman.impl.ui.quicklist', 'fman.impl.ui.panel',
	'fman.impl.ui.session', 'fman.impl.ui.output', 'fman.impl.navigation',
	'fman.impl.ui.table', 'fman.impl.ui.table_data', 'fman.impl.ui.facade',
	'fman.impl.quick_view',
	'fman.impl.quick_view_pdf', 'fman.impl.quick_view_pdf_view', '_quick_view_pdf_worker',
	'PyQt5.QtSvg'
] + winpty_imports + send2trash_imports + pdfium_imports + pdfium_raw_imports

a = Analysis(
	['src/main/python/fman/main.py'],
	pathex=['src/main/python'],
	binaries=binaries,
	datas=datas,
	hiddenimports=hidden_imports,
	excludes=['boto3', 'botocore', 's3transfer', 'PIL', 'numpy']
)
pyz = PYZ(a.pure)
exe = EXE(
	pyz,
	a.scripts,
	[],
	exclude_binaries=True,
	name=app_name,
	console=os.environ.get('ROYIFILEMANAGER_BUILD_CONSOLE') == '1',
	icon='src/main/icons/Icon.ico'
)
coll = COLLECT(
	exe,
	a.binaries,
	a.datas,
	strip=False,
	upx=True,
	name=app_name
)