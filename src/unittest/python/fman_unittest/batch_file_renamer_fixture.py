from contextlib import contextmanager
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
import sys


PLUGIN_ROOT = Path(__file__).resolve().parents[4] / 'plugins/BatchFileRenamer'


@contextmanager
def engine_module():
	name = '_batch_renamer_test_engine'
	previous = sys.modules.get(name)
	spec = spec_from_file_location(name, PLUGIN_ROOT / 'batch_file_renamer/engine.py')
	module = module_from_spec(spec)
	sys.modules[name] = module
	try:
		spec.loader.exec_module(module)
		yield module
	finally:
		if previous is None:
			sys.modules.pop(name, None)
		else:
			sys.modules[name] = previous


@contextmanager
def plugin_module():
	name = 'batch_file_renamer'
	previous = {key: value for key, value in sys.modules.items() if key == name or key.startswith(name + '.')}
	spec = spec_from_file_location(name, PLUGIN_ROOT / name / '__init__.py', submodule_search_locations=[str(PLUGIN_ROOT / name)])
	module = module_from_spec(spec)
	sys.modules[name] = module
	try:
		spec.loader.exec_module(module)
		yield module
	finally:
		for key in tuple(sys.modules):
			if key == name or key.startswith(name + '.'):
				sys.modules.pop(key)
		sys.modules.update(previous)