from fman.impl.filter_pattern import compile_filter, MAX_FILTER_LENGTH
from itertools import product
from random import Random
from unittest import TestCase

import re
import warnings


class FilterPatternTest(TestCase):
	def test_legacy_matching(self):
		names = ['', 'Annual Report.pdf', 'rep 2024', 'a.b', 'a+b', '(x)', 'ABC']
		names.extend(''.join(chars) for size in range(4) for chars in product('ab ', repeat=size))
		queries = ['', 'rep', 'rep*pdf', 'a*b*c', 'a.b', 'a+b', '(x)', 'rep 2024']
		queries.extend(''.join(chars) for size in range(4) for chars in product('ab* ', repeat=size))
		for query in queries:
			old = re.compile('.*'.join(map(re.escape, query.split('*'))), re.I)
			matcher = compile_filter(query)
			for name in names:
				self.assertEqual(bool(old.search(name)), matcher.matches(name), (query, name))

	def test_globs_anchors_negation_and_escapes(self):
		cases = [
			('r?p', ['rep', 'RAP'], ['rp', 'reep']),
			('[abc]', ['b', 'Cat'], ['xyz']),
			('[a-z]', ['R'], ['123']),
			('[!x]', ['y'], ['xxx']),
			('[]a]', [']', 'a'], ['b']),
			('[*]', ['*'], ['abc']),
			('[a*]', ['a', '*'], ['b']),
			('[[]', ['['], ['b']),
			('[draft', ['[draft]'], ['draft']),
			('^rep', ['Report.pdf'], ['Annual Report.pdf']),
			('.py$', ['foo.py'], ['foo.pyc']),
			('^a*z$', ['abz', 'az'], ['xabz', 'abzy']),
			('^rep*$', ['report', 'rep'], ['Annualrep']),
			('^*rep$', ['Annualrep', 'rep'], ['report']),
			('^**rep**$', ['Annualreport', 'rep'], ['abc']),
			('^*$', ['', 'anything'], []),
			('!*', [], ['', 'anything']),
			('!^*$', [], ['anything']),
			('^', ['^x'], ['x']),
			('$', ['$RECYCLE.BIN'], ['name']),
			('^$', ['a^$b'], ['ab']),
			('$RE', ['$RECYCLE.BIN'], ['RECYCLE.BIN']),
			('a^b', ['a^b'], ['ab']),
			('!tmp', ['report'], ['backup.tmp']),
			('!^tmp', ['a.tmp'], ['tmpfile']),
			('!', ['!important'], ['important']),
			('!^$', ['!^$'], ['anything']),
			('a!b', ['a!b'], ['ab']),
			(r'share\$', ['share$', 'share$x'], ['share']),
			(r'\^x', ['^x'], ['x']),
			(r'\!x', ['!x'], ['x']),
			(r'\*', ['*'], ['anything']),
			(r'\?', ['?'], ['anything']),
			(r'\[a]', ['[a]'], ['a']),
			('[$]', ['$'], ['a']),
			('abc\\', ['abc'], ['abd']),
			(r'\\', ['\\'], ['abc']),
			(r'[\]]', [']'], ['a']),
			(r'[a\-c]', ['a', '-', 'c'], ['b']),
			('[z-a]', ['[z-a]'], ['z', 'a']),
			('rep 2024', ['rep 2024'], ['2024 rep']),
		]
		for query, accepted, rejected in cases:
			with self.subTest(query=query):
				matcher = compile_filter(query)
				for name in accepted:
					self.assertTrue(matcher.matches(name), name)
				for name in rejected:
					self.assertFalse(matcher.matches(name), name)

	def test_character_class_hyphen_positions(self):
		cases = [
			('[-]', '-', 'abc'),
			('[-ac]', '-ac', 'bd'),
			('[ac-]', 'ac-', 'bd'),
			('[a-c]', 'abcB', '-d'),
			('[-a-c]', '-abc', 'd'),
			('[a-c-]', 'abc-', 'd'),
			(r'[a\-c]', 'a-c', 'bd'),
			('[--]', '-', 'abc'),
			('[a--c]', 'a-c', 'bd'),
			('[!-ac]', 'bd', '-ac'),
			('[!ac-]', 'bd', 'ac-'),
			('[!a-c-]', 'de', 'abc-'),
			(r'[!a\-c]', 'bd', 'a-c'),
		]
		for query, accepted, rejected in cases:
			with self.subTest(query=query), warnings.catch_warnings():
				warnings.simplefilter('error', FutureWarning)
				matcher = compile_filter(query)
				for name in accepted:
					self.assertTrue(matcher.matches(name), name)
				for name in rejected:
					self.assertFalse(matcher.matches(name), name)
				self.assertFalse(matcher.matches(''))

	def test_every_prefix_and_random_input_is_safe(self):
		random = Random(123)
		queries = [r'!^a*[!x-z]\?$']
		queries.extend(''.join(random.choices('ab!?[]^$*\\-&', k=30)) for count in range(200))
		for query in queries:
			for length in range(len(query) + 1):
				with warnings.catch_warnings():
					warnings.simplefilter('error', FutureWarning)
					matcher = compile_filter(query[:length])
				self.assertIsInstance(matcher.matches('a' * 255), bool)
		self.assertTrue(compile_filter('a' * (MAX_FILTER_LENGTH + 10)).matches('a' * MAX_FILTER_LENGTH))

	def test_adversarial_matching_results(self):
		queries = ['?*?*?*?*?*?*?*?Z', 'a*a*a*a*a*a*a*a*Z', '*' * 100]
		for query in queries:
			matcher = compile_filter(query)
			for length in (0, 1, 32, 255):
				self.assertEqual(query == '*' * 100, matcher.matches('a' * length))