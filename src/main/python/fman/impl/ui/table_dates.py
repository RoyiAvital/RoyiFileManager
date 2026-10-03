from datetime import date, datetime, timedelta
import re

NS = 1_000_000_000
INT64_MIN, INT64_MAX = -2 ** 63, 2 ** 63 - 1
_EPOCH = datetime(1970, 1, 1)
_ISO_DATE = re.compile(r'\d{4}-\d{2}-\d{2}')


def system_offset():
	from PyQt5.QtCore import QDateTime, QTimeZone, Qt
	zone = QTimeZone.systemTimeZone()
	if not zone.isValid():
		raise ValueError('The system time zone is unavailable.')
	return lambda seconds: zone.offsetFromUtc(QDateTime.fromSecsSinceEpoch(seconds, Qt.UTC))


class LocalDates:
	"""Formats UTC epoch nanoseconds and computes local day bounds for one zone."""

	def __init__(self, offset=None):
		self.offset = offset or system_offset()

	def local(self, nanoseconds):
		seconds = nanoseconds // NS
		offset = self.offset(seconds)
		return _EPOCH + timedelta(seconds=seconds + offset), offset

	def format(self, nanoseconds, date_only=False):
		moment, offset = self.local(nanoseconds)
		text = '%04d-%02d-%02d' % (moment.year, moment.month, moment.day)
		if date_only:
			return text
		if offset:
			sign = '+' if offset > 0 else '-'
			minutes = abs(offset) // 60
			zone = '%s%02d:%02d' % (sign, minutes // 60, minutes % 60)
		else:
			zone = 'Z'
		return text + 'T%02d:%02d:%02d' % (moment.hour, moment.minute, moment.second) + zone

	def day_start(self, day):
		naive = (datetime(day.year, day.month, day.day) - _EPOCH) // timedelta(seconds=1)
		offsets = {self.offset(naive + delta) for delta in (-86400, -43200, 0, 43200, 86400)}
		valid = [naive - offset for offset in offsets if self.offset(naive - offset) == offset]
		if valid:
			return min(valid) * NS
		# Midnight falls in a gap: use the first instant whose local time is on or after it.
		low, high = naive - max(offsets), naive - min(offsets)
		while low < high:
			middle = (low + high) // 2
			if middle + self.offset(middle) >= naive:
				high = middle
			else:
				low = middle + 1
		moment = _EPOCH + timedelta(seconds=low + self.offset(low))
		if moment.date() != day:
			raise ValueError('%s does not exist in the local time zone.' % day.isoformat())
		return low * NS

	def next_day_start(self, day):
		try:
			following = day + timedelta(days=1)
		except OverflowError:
			raise ValueError('The day after %s cannot be represented.' % day.isoformat()) from None
		return self.day_start(following)


def parse_date(value):
	value = value.strip()
	if not _ISO_DATE.fullmatch(value):
		raise ValueError('Enter a date as YYYY-MM-DD.')
	try:
		return date.fromisoformat(value)
	except ValueError:
		raise ValueError('%s is not a valid calendar date.' % value) from None
