from functools import lru_cache
from pathlib import Path
import json
import re
import sys


def settings_path():
	if getattr(sys, 'frozen', False):
		return Path(sys._MEIPASS) / 'resources/build-settings/base.json'
	return Path(__file__).resolve().parents[4] / 'src/build/settings/base.json'


def load_build_settings(path):
	path = Path(path)
	try:
		settings = json.loads(path.read_text(encoding='utf-8'))
	except (OSError, UnicodeError, ValueError) as error:
		raise ValueError('%s: cannot read build settings: %s' % (path, error)) from error
	name = settings.get('app_name') if isinstance(settings, dict) else None
	reserved = {'CON', 'PRN', 'AUX', 'NUL'} | {
		'%s%d' % (prefix, number)
		for prefix in ('COM', 'LPT') for number in range(1, 10)
	}
	if not isinstance(name, str) or not re.fullmatch(
		'[A-Za-z][A-Za-z0-9_-]{0,63}', name
	) or name.upper() in reserved:
		raise ValueError(
			'%s: invalid app_name; use 1-64 ASCII letters, digits, underscores '
			'or hyphens, starting with a letter, excluding Windows device names.' % path
		)
	return settings


@lru_cache(maxsize=1)
def get_build_settings():
	return load_build_settings(settings_path())


if __name__ == '__main__':
	print(get_build_settings()['app_name'])