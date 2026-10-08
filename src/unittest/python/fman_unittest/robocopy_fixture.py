from contextlib import contextmanager
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
import shutil
import sys
from tempfile import TemporaryDirectory


PLUGIN_ROOT = Path(__file__).resolve().parents[4] / 'src/main/resources/base/Plugins/Robocopy'


@contextmanager
def plugin_module():
	name = 'robocopy_plugin'
	previous = {key: value for key, value in sys.modules.items() if key == name or key.startswith(name + '.')}
	with TemporaryDirectory(prefix='RobocopyPluginTest-') as temporary:
		root = Path(temporary) / 'Robocopy'
		shutil.copytree(PLUGIN_ROOT, root, ignore=shutil.ignore_patterns('__pycache__'))
		spec = spec_from_file_location(name, root / name / '__init__.py', submodule_search_locations=[str(root / name)])
		module = module_from_spec(spec)
		sys.modules[name] = module
		try:
			spec.loader.exec_module(module)
			yield module
		finally:
			for key in tuple(sys.modules):
				if key == name or key.startswith(name + '.'):
					sys.modules.pop(key, None)
			sys.modules.update(previous)