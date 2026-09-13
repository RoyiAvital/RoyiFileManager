from fbs_runtime.application_context import cached_property
from pathlib import Path
import json
import sys


class ApplicationContext:
	@cached_property
	def build_settings(self):
		if getattr(sys, 'frozen', False):
			settings_path = Path(self.get_resource('build-settings/base.json'))
		else:
			settings_path = Path(__file__).resolve().parents[5] / \
				'src/build/settings/base.json'
		return json.loads(settings_path.read_text(encoding='utf-8'))

	def get_resource(self, relative_path):
		if getattr(sys, 'frozen', False):
			resource_root = Path(sys._MEIPASS) / 'resources'
		else:
			project_root = Path(__file__).resolve().parents[5]
			windows_resource = project_root / 'src' / 'main' / 'resources' / \
				'windows' / relative_path
			if windows_resource.exists():
				return str(windows_resource)
			icon = project_root / 'src' / 'main' / 'icons' / relative_path
			if icon.exists():
				return str(icon)
			resource_root = project_root / 'src' / 'main' / 'resources' / 'base'
		resource = resource_root / relative_path
		if not resource.exists():
			raise FileNotFoundError(str(resource))
		return str(resource)