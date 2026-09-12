from functools import cached_property
import sys


_application_context = None


def is_frozen():
	return bool(getattr(sys, 'frozen', False))


def get_application_context(development_class, frozen_class):
	global _application_context
	if _application_context is None:
		context_class = frozen_class if is_frozen() else development_class
		_application_context = context_class()
	return _application_context