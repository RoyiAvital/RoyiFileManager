from fman.impl.util.qt import KeypadModifier, Key_Return, Key_Enter, \
	Key_Shift, Key_Control, Key_Meta, \
	Key_Alt, Key_AltGr, Key_CapsLock, Key_NumLock, Key_ScrollLock
from PyQt5.QtCore import Qt
from PyQt5.QtGui import QKeySequence

class QtKeyEvent:
	def __init__(self, key, modifiers):
		self.key = key
		self.modifiers = modifiers
	def matches(self, keys):
		modifiers = self.modifiers
		key, modifiers, keys = self._alias_return_and_enter(modifiers, keys)
		return QKeySequence(modifiers | key).matches(QKeySequence(keys)) \
			   == QKeySequence.ExactMatch
	def is_modifier_only(self):
		return self.key in (
			Key_Shift, Key_Control, Key_Meta, Key_Alt, Key_AltGr, Key_CapsLock,
			Key_NumLock, Key_ScrollLock
		)
	def __str__(self):
		result = ''
		if self.modifiers:
			result += QKeySequence(self.modifiers).toString()
		for key in [k for k in dir(Qt) if k.startswith('Key_')]:
			if self.key == getattr(Qt, key):
				result += key[len('Key_'):]
				break
		else:
			result += '0x%02x' % self.key
		return result
	def _alias_return_and_enter(self, modifiers, keys):
		# Qt has Key_Enter and Key_Return. The former is the Enter key on the
		# numpad. The latter is next to the characters. We want the user to
		# specify "Enter" for both:
		if self.key == Key_Enter:
			key = Key_Return
			modifiers &= ~KeypadModifier
		else:
			key = self.key
		return key, modifiers, self._replace(keys, {'Enter': 'Return'})
	def _replace(self, keys, replacements):
		return '+'.join(replacements.get(k, k) for k in keys.split('+'))
	def __hash__(self):
		return hash((int(self.key), int(self.modifiers)))
	def __eq__(self, other):
		if not isinstance(other, QtKeyEvent):
			return False
		return self.key == other.key and self.modifiers == other.modifiers
	def __ne__(self, other):
		return not self == other