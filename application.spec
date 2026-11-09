from PyInstaller.utils.hooks import collect_all, copy_metadata
from PyInstaller.utils.win32 import versioninfo
from pathlib import Path
from runpy import run_path
import os
import re
import sys


root = Path(SPECPATH)
load_build_settings = run_path(
	str(root / 'src/main/python/fbs_runtime/build_settings.py')
)['load_build_settings']
build_settings_path = root / 'src/AppMeta.json'
build_settings = load_build_settings(build_settings_path)
app_name = build_settings['app_name']
app_version = build_settings.get('version')
identifier = r'(?:0|[1-9][0-9]*|[0-9]*[A-Za-z-][0-9A-Za-z-]*)'
version_match = re.fullmatch(
	r'([0-9]+(?:\.[0-9]+){2,3})(?:-%s(?:\.%s)*)?' % (identifier, identifier),
	app_version
) if isinstance(app_version, str) else None
if version_match is None or any(int(part) > 65535 for part in version_match.group(1).split('.')):
	raise ValueError(
		'%s: invalid version; use three or four integers from 0 to 65535, '
		'separated by dots, optionally followed by a SemVer prerelease suffix '
		'such as -rc.1.' % build_settings_path
	)
version_parts = tuple(map(int, version_match.group(1).split('.')))
version_parts += (0,) * (4 - len(version_parts))
version_info = versioninfo.VSVersionInfo(
	ffi=versioninfo.FixedFileInfo(
		filevers=version_parts, prodvers=version_parts,
		flags=0x2 if '-' in app_version else 0
	),
	kids=[
		versioninfo.StringFileInfo([versioninfo.StringTable('040904b0', [
			versioninfo.StringStruct('FileVersion', app_version),
			versioninfo.StringStruct('ProductVersion', app_version),
			versioninfo.StringStruct('ProductName', app_name),
			versioninfo.StringStruct('FileDescription', build_settings['description'])
		])]),
		versioninfo.VarFileInfo([versioninfo.VarStruct('Translation', [0x0409, 1200])])
	]
)

send2trash_datas, send2trash_binaries, send2trash_imports = \
	collect_all('send2trash')
pdfium_datas, pdfium_binaries, pdfium_imports = collect_all(
	'pypdfium2', filter_submodules=lambda name: '._cli' not in name and not name.endswith('.__main__'))
pdfium_raw_datas, pdfium_raw_binaries, pdfium_raw_imports = collect_all('pypdfium2_raw')
# Table View needs only the core engine; optional pandas/Spark/Polars integrations are not bundled.
duckdb_datas, duckdb_binaries, duckdb_imports = collect_all(
	'duckdb', filter_submodules=lambda name: not name.startswith(('duckdb.experimental', 'duckdb.query_graph')))
checksum_native_files = run_path(
	str(root / 'src/main/resources/base/Plugins/ChecksumFiles/package.py')
)['native_files']()
checksum_native_destination = 'resources/Plugins/ChecksumFiles/checksum_files/_vendor/blake3'

datas = [
	('src/main/resources/base', 'resources'),
	('plugins/BatchFileRenamer', 'resources/Plugins/BatchFileRenamer'),
	('plugins/FileAttributesEditor', 'resources/Plugins/FileAttributesEditor'),
	('src/AppMeta.json', 'resources/build-settings'),
	('src/main/resources/windows', 'resources'),
	('src/main/icons/Icon.ico', 'resources'),
	('src/main/resources/base/Plugins/Everything/bin/Everything.exe', 'resources/Plugins/Everything/bin'),
	('src/main/resources/base/Plugins/Everything/licenses/Everything.txt', 'resources/Plugins/Everything/licenses')
] + send2trash_datas + pdfium_datas + pdfium_raw_datas + duckdb_datas + copy_metadata('pypdfium2') + copy_metadata('Pygments') + [
	(str(path), checksum_native_destination) for path in checksum_native_files
	if path.suffix != '.pyd'
]
binaries = send2trash_binaries + pdfium_binaries + pdfium_raw_binaries + duckdb_binaries + [
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
	'adodbapi', 'ctypes.wintypes', 'random', 'string', 'uuid', 'win32com.shell.shell',
	'win32com.shell.shellcon', 'win32gui', 'win32wnet', 'win32process',
	'fman.ui', 'fman.impl.ui.quicklist', 'fman.impl.ui.panel',
	'fman.impl.ui.session', 'fman.impl.ui.output', 'fman.impl.navigation',
	'fman.impl.ui.table', 'fman.impl.ui.table_data', 'fman.impl.ui.facade',
	'fman.impl.quick_view',
	'fman.impl.quick_view_animation',
	'fman.impl.quick_view_pdf', 'fman.impl.quick_view_pdf_view', '_quick_view_pdf_worker',
	'fman.impl.quick_view_csv', '_quick_view_csv_worker',
	'PyQt5.QtSvg'
] + send2trash_imports + pdfium_imports + pdfium_raw_imports + duckdb_imports

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
	version=version_info,
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