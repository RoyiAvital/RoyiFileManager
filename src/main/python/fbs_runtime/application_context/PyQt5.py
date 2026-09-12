from pathlib import Path
import sys


class ApplicationContext:
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