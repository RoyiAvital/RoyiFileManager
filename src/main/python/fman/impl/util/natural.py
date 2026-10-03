from unicodedata import decimal

import re

_DIGITS = re.compile(r'(\d+)')


def natural_key(name):
	parts = _DIGITS.split(name.lower())
	for index in range(1, len(parts), 2):
		digits = parts[index]
		if not digits.isascii():
			digits = ''.join(str(decimal(character)) for character in digits)
		digits = digits.lstrip('0') or '0'
		if len(digits) <= 6:
			parts[index] = '0' + digits.zfill(6)
		else:
			length = str(len(digits))
			parts[index] = '1' + '1' * len(length) + '0' + length + digits
	return ''.join(parts)
