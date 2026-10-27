from core.quicksearch_matchers import contains_chars_after_separator, \
	display_positions
from unittest import TestCase

class DisplayPositionsTest(TestCase):
	def test_unchanged_when_lowercase_keeps_positions(self):
		for text in ('Copy', 'Caf\u00e9', '\u05e7\u05d1\u05e6\u05d9\u05dd', 'a\ud800b'):
			with self.subTest(text=text):
				self.assertEqual([1], display_positions(text, text.lower(), [1]))
		self.assertIsNone(display_positions('\u0130', '\u0130'.lower(), None))
	def test_expanding_lowercase_maps_back_to_the_source_character(self):
		text = '\u0130: Edit'
		self.assertEqual([0, 2, 3, 4, 5, 6],
			display_positions(text, text.lower(), [0, 3, 4, 5, 6, 7]))
		self.assertEqual([0], display_positions(text, text.lower(), [0, 1]))
	def test_non_bmp_characters_use_two_utf16_units(self):
		text = '\U0001f527 Tools: Edit'
		self.assertEqual([10, 11, 12, 13], display_positions(text, text.lower(), [9, 10, 11, 12]))
		self.assertEqual([0, 1], display_positions(text, text.lower(), [0]))

class ContainsCharsAfterSeparatorTest(TestCase):
	def test_simple(self):
		self.assertEqual(
			[0, 5], self.find_chars_after_space('copy paths', 'cp')
		)
	def test_chars_in_first_and_second_part(self):
		self.assertEqual(
			[0, 1, 2], self.find_chars_after_space('copy paths', 'cop')
		)
	def test_no_match(self):
		self.assertIsNone(self.find_chars_after_space('copy paths', 'cd'))
	def test_full_word_match(self):
		self.assertEqual(
			[0, 1, 2, 3, 5],
			self.find_chars_after_space('copy paths', 'copyp')
		)
	def test_prefix_match(self):
		self.assertEqual(
			[0, 1],
			self.find_chars_after_space('column count', 'co')
		)
	def setUp(self):
		super().setUp()
		self.find_chars_after_space = contains_chars_after_separator(' ')