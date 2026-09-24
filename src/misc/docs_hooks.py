from pathlib import Path
from runpy import run_path


ROOT = Path(__file__).resolve().parents[2]
load_build_settings = run_path(
	str(ROOT / 'src/main/python/fbs_runtime/build_settings.py')
)['load_build_settings']


def on_config(config):
	root = Path(config.config_file_path).resolve().parent
	settings = load_build_settings(root / 'src/build/settings/base.json')
	name = settings['app_name']
	config.site_name = name
	config.copyright = '%s is based on fman 1.7.5.' % name
	config.extra['app_name'] = name
	return config


def on_page_markdown(markdown, *, config, **kwargs):
	return markdown.replace('{{ app_name }}', config.extra['app_name'])