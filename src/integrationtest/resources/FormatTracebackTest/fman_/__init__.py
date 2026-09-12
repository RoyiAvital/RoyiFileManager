def run_plugins():
	from plugin.module import run_plugin
	try:
		raise Exception()
	except Exception:
		run_plugin()

def raise_error():
	raise ValueError()