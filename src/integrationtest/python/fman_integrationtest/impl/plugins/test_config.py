from fman import PLATFORM
from fman.impl.plugins.config import load_json, write_differential_json, Config
from fman_integrationtest import get_resource
from os.path import join, exists
from shutil import rmtree, copy
from tempfile import mkdtemp
from unittest import TestCase
from unittest.mock import patch

import json

class ConfigTest(TestCase):
	def test_add_dir(self):
		self._config.add_dir(self._dir_1)
		self.assertEqual([1], self._config.load_json('Test.json'))
	def test_add_dir_updates_existing(self):
		self._config.add_dir(self._dir_1)
		value = self._config.load_json('Test.json')
		self.assertEqual([1], value)
		self._config.add_dir(self._dir_2)
		self.assertIs(value, self._config.load_json('Test.json'))
		self.assertEqual([2, 1], value)
	def test_nested_settings_reload_save_and_restart(self):
		name = 'Archives.json'
		base = {'archive_handlers': {'.zip': 'zip://', '.tar': 'tar://'}}
		override = {'archive_handlers': {'.crx': 'crx://', '.tar': 'tar2://'}}
		write_differential_json(base, [], join(self._dir_1, name))
		write_differential_json(override, [], join(self._dir_2, name))
		self._config.add_dir(self._dir_1)
		value = self._config.load_json(name)
		self._config.add_dir(self._dir_2)
		self.assertIs(value, self._config.load_json(name))
		self.assertEqual({'.zip': 'zip://', '.tar': 'tar2://', '.crx': 'crx://'},
			value['archive_handlers'])
		self._config.remove_dir(self._dir_2)
		self.assertIs(value, self._config.load_json(name))
		self.assertEqual(base, value)
		self._config.add_dir(self._dir_2)
		user_dir = mkdtemp()
		self.addCleanup(rmtree, user_dir)
		self._config.add_dir(user_dir)
		value['archive_handlers']['.crx'] = 'custom://'
		self._config.save_json(name)
		with open(self._config.locate(name)[-1], 'r') as file:
			self.assertEqual({'archive_handlers': {'.crx': 'custom://'}}, json.load(file))
		restarted = Config(PLATFORM)
		for directory in (self._dir_1, self._dir_2, user_dir):
			restarted.add_dir(directory)
		self.assertEqual(value, restarted.load_json(name))
	def test_remove_add_dir(self):
		self._config.add_dir(self._dir_1)
		self.assertEqual([1], self._config.load_json('Test.json'))
		self._config.remove_dir(self._dir_1)
		self.assertIsNone(self._config.load_json('Test.json'))
		self._config.add_dir(self._dir_2)
		self.assertEqual([2], self._config.load_json('Test.json'))
	def test_save_on_quit_nonexistent(self):
		value = self._config.load_json(
			'Nonexistent.json', default=[], save_on_quit=True
		)
		value.append(3)
		self._config.add_dir(self._dir_1)
		self._config.on_quit()
		config = Config(PLATFORM)
		config.add_dir(self._dir_1)
		self.assertEqual(value, config.load_json('Nonexistent.json'))
	def test_preserve_on_reload_leaves_ordinary_settings_unchanged(self):
		self._config.add_dir(self._dir_1)
		self._config.save_json('History.json', {'recent': ['copy']})
		history = self._config.load_json('History.json', save_on_quit=True, preserve_on_reload=True)
		ordinary = self._config.load_json('Test.json', save_on_quit=True)
		history['recent'].insert(0, 'paste')
		ordinary.append(99)
		self._config.add_dir(self._dir_2)
		self.assertIs(history, self._config.load_json('History.json'))
		self.assertEqual({'recent': ['paste', 'copy']}, history)
		self.assertIs(ordinary, self._config.load_json('Test.json'))
		self.assertEqual([2, 1], ordinary)
		self._config.remove_dir(self._dir_2)
		self.assertEqual([1], ordinary)
		self.assertEqual({'recent': ['paste', 'copy']}, history)
	def test_default_dict_reload_still_restores_disk_contents(self):
		self._config.add_dir(self._dir_1)
		self._config.save_json('History.json', {'recent': ['copy']})
		history = self._config.load_json('History.json', save_on_quit=True)
		history['recent'].insert(0, 'paste')
		self._config.add_dir(self._dir_2)
		self.assertIs(history, self._config.load_json('History.json'))
		self.assertEqual({'recent': ['copy']}, history)
	def test_retained_value_has_no_reload_io_or_implicit_write(self):
		self._config.add_dir(self._dir_1)
		self._config.save_json('History.json', {'recent': ['copy']})
		history = self._config.load_json('History.json', preserve_on_reload=True)
		history['recent'].insert(0, 'paste')
		with patch('fman.impl.plugins.config.load_json', side_effect=AssertionError('Reload I/O')):
			self._config.remove_dir(self._dir_1)
			self._config.add_dir(self._dir_1)
		self.assertIs(history, self._config.load_json('History.json'))
		self._config.on_quit()
		restarted = Config(PLATFORM)
		restarted.add_dir(self._dir_1)
		self.assertEqual({'recent': ['copy']}, restarted.load_json('History.json'))
	def test_retained_value_saves_latest_state_after_directory_reload(self):
		self._config.add_dir(self._dir_1)
		self._config.save_json('History.json', {'recent': ['copy']})
		history = self._config.load_json('History.json', save_on_quit=True, preserve_on_reload=True)
		history['recent'].insert(0, 'paste')
		self._config.remove_dir(self._dir_1)
		self._config.add_dir(self._dir_1)
		self._config.on_quit()
		restarted = Config(PLATFORM)
		restarted.add_dir(self._dir_1)
		self.assertEqual(history, restarted.load_json('History.json'))
	def test_explicit_save_replaces_retained_value(self):
		self._config.add_dir(self._dir_1)
		self._config.load_json('History.json', default={}, preserve_on_reload=True)
		replacement = {'recent': ['new']}
		self._config.save_json('History.json', replacement)
		self._config.add_dir(self._dir_2)
		self.assertIs(replacement, self._config.load_json('History.json'))
	def test_missing_value_does_not_prevent_future_load(self):
		self.assertIsNone(self._config.load_json('Test.json', preserve_on_reload=True))
		self._config.add_dir(self._dir_1)
		self.assertEqual([1], self._config.load_json('Test.json'))
	def test_failed_load_is_not_retained(self):
		with patch('fman.impl.plugins.config.load_json', side_effect=ValueError):
			with self.assertRaises(ValueError):
				self._config.load_json('Test.json', preserve_on_reload=True)
		self._config.add_dir(self._dir_1)
		value = self._config.load_json('Test.json')
		self._config.add_dir(self._dir_2)
		self.assertEqual([2, 1], value)
	def test_retained_history_survives_another_settings_reload_failure(self):
		self._config.add_dir(self._dir_1)
		self._config.load_json('Test.json')
		history = self._config.load_json('History.json', default={'recent': ['copy']},
			save_on_quit=True, preserve_on_reload=True)
		history['recent'].insert(0, 'paste')
		with patch('fman.impl.plugins.config.load_json', side_effect=ValueError('Invalid other settings')):
			with self.assertRaises(ValueError):
				self._config.add_dir(self._dir_2)
			self.assertIs(history, self._config.load_json('History.json'))
		self._config.on_quit()
		restarted = Config(PLATFORM)
		restarted.add_dir(self._dir_2)
		self.assertEqual({'recent': ['paste', 'copy']}, restarted.load_json('History.json'))
	def test_retention_supports_lists_and_scalars(self):
		for value in ([1, 2], 'text', 0, False):
			with self.subTest(value=value):
				config = Config(PLATFORM)
				config.load_json('History.json', default=value, preserve_on_reload=True)
				config.add_dir(self._dir_1)
				config.remove_dir(self._dir_1)
				self.assertIs(value, config.load_json('History.json'))
	def test_public_api_forwards_retention_and_preserves_positional_calls(self):
		from fman import load_json as public_load_json
		from fman.impl.plugins import PluginSupport
		support = PluginSupport(None, None, None, None, self._config)
		with patch('fman._get_plugin_support', return_value=support):
			self._config.add_dir(self._dir_1)
			ordinary = public_load_json('Test.json', None, True)
			history = public_load_json('History.json', {'recent': []}, True, preserve_on_reload=True)
			history['recent'].append('copy')
			self._config.add_dir(self._dir_2)
			self.assertEqual([2, 1], ordinary)
			self.assertIs(history, public_load_json('History.json'))
			self.assertEqual({'recent': ['copy']}, history)
	def setUp(self):
		super().setUp()
		self._dir_1 = mkdtemp()
		copy(get_resource('ConfigTest/1/Test.json'), self._dir_1)
		self._dir_2 = mkdtemp()
		copy(get_resource('ConfigTest/2/Test.json'), self._dir_2)
		self._config = Config(PLATFORM)
	def tearDown(self):
		rmtree(self._dir_1)
		rmtree(self._dir_2)
		super().tearDown()

class LoadJsonTest(TestCase):
	def test_nonexistent_file(self):
		self.assertIsNone(load_json(['non-existent']))
	def test_dict(self):
		d = {'a': 1, 'b': 1}
		json_path = self._save_to_json(d)
		self.assertEqual(d, load_json([json_path]))
	def test_dict_multiple_files(self):
		d1 = {'a': 1, 'b': 1}
		d2 = {'b': 2, 'c': 2}
		json1 = self._save_to_json(d1)
		json2 = self._save_to_json(d2)
		self.assertEqual({'a': 1, 'b': 2, 'c': 2}, load_json([json1, json2]))
	def test_nested_dict_multiple_files(self):
		base = {'archive_handlers': {'.zip': 'zip://', '.tar': 'tar://'}}
		override = {'archive_handlers': {'.crx': 'crx://', '.tar': 'tar2://'}}
		paths = [self._save_to_json(base), self._save_to_json(override)]
		self.assertEqual(
			{'archive_handlers': {
				'.zip': 'zip://', '.tar': 'tar2://', '.crx': 'crx://'
			}},
			load_json(paths)
		)
	def test_nested_list_multiple_files(self):
		base = {'editor': {'args': ['vim', '{file}']}}
		override = {'editor': {'args': ['emacs', '{file}']}}
		paths = [self._save_to_json(base), self._save_to_json(override)]
		self.assertEqual(override, load_json(paths))
	def test_deep_nested_dict_multiple_files(self):
		values = (
			{'tools': {'editor': {'path': 'vim', 'args': ['old']}}},
			{'tools': {'editor': {'path': 'emacs'}}},
			{'tools': {'editor': {'args': [], 'enabled': False}}}
		)
		paths = [self._save_to_json(value) for value in values]
		self.assertEqual(
			{'tools': {'editor': {'path': 'emacs', 'args': [], 'enabled': False}}},
			load_json(paths)
		)
	def test_list(self):
		l = [1, 2]
		json_path = self._save_to_json(l)
		self.assertEqual(l, load_json([json_path]))
	def test_list_multiple_files(self):
		l1 = [1, 2]
		l2 = [3]
		json1 = self._save_to_json(l1)
		json2 = self._save_to_json(l2)
		self.assertEqual(l2 + l1, load_json([json1, json2]))
	def test_string(self):
		string = 'test'
		json_path = self._save_to_json(string)
		self.assertEqual(string, load_json([json_path]))
	def test_string_multiple_files(self):
		s1 = 'test1'
		s2 = 'test2'
		json1 = self._save_to_json(s1)
		json2 = self._save_to_json(s2)
		self.assertEqual(s2, load_json([json2, json1]))
	def test_multiple_files_first_does_not_exist(self):
		value = {'a': 1}
		json_path = self._save_to_json(value)
		self.assertEqual(value, load_json(['non-existent', json_path]))
	def setUp(self):
		self.temp_dir = mkdtemp()
		self.num_files = 0
	def tearDown(self):
		rmtree(self.temp_dir)
	def _save_to_json(self, value):
		json_path = join(self.temp_dir, '%d.json' % self.num_files)
		with open(json_path, 'w') as f:
			json.dump(value, f)
		self.num_files += 1
		return json_path

class WriteDifferentialJsonTest(TestCase):
	def test_dict(self):
		self._check_write({'a': 1})
	def test_list(self):
		self._check_write([1, 2])
	def test_string(self):
		self._check_write("hello!")
	def test_int(self):
		self._check_write(3)
	def test_bool(self):
		self._check_write(True)
	def test_float(self):
		self._check_write(4.5)
	def test_overwrite_dict_value(self):
		d = {'a': 1, 'b': 1}
		with open(self._json_file(), 'w') as f:
			json.dump(d, f)
		d['b'] = 2
		d['c'] = 3
		self._check_write(d)
	def test_dict_incremental_update(self):
		d = {'a': 1, 'b': 1}
		with open(self._json_file(0), 'w') as f:
			json.dump(d, f)
		d['b'] = 2
		d['c'] = 3
		write_differential_json(d, [self._json_file(0)], self._json_file(1))
		with open(self._json_file(1), 'r') as f:
			self.assertEqual({'b': 2, 'c': 3}, json.load(f))
	def test_extend_list(self):
		write_differential_json([1, 2], [], self._json_file())
		self._check_write([1, 2, 3])
	def test_update_list(self):
		json1 = self._json_file(0)
		json2 = self._json_file(1)
		with open(json1, 'w') as f:
			json.dump([2, 3], f)
		with open(json2, 'w') as f:
			json.dump([1], f)
		write_differential_json([0, 1, 2, 3], [json1], json2)
		with open(json2, 'r') as f:
			self.assertEqual([0, 1], json.load(f))
	def test_type_change_raises(self):
		write_differential_json(1, [], self._json_file())
		with self.assertRaises(ValueError):
			write_differential_json({'x': 1}, [], self._json_file())
	def test_update_unmodifiable_list_parts_raises(self):
		json1 = self._json_file(0)
		json2 = self._json_file(1)
		with open(json1, 'w') as f:
			json.dump([1], f)
		with open(json2, 'w') as f:
			json.dump([2], f)
		with self.assertRaises(ValueError):
			write_differential_json(json1, [], json2)
	def test_no_change(self):
		json1 = self._json_file(0)
		l = [0, 1]
		with open(json1, 'w') as f:
			json.dump(l, f)
		json2 = self._json_file(1)
		write_differential_json(l, [json1], json2)
		self.assertFalse(exists(json2))
	def test_delete_dict_key_same_file_ok(self):
		json1 = self._json_file(0)
		json2 = self._json_file(1)
		write_differential_json({'a': 1}, [], json1)
		write_differential_json({'a': 1, 'b': 2}, [json1], json2)
		write_differential_json({'a': 1}, [json1], json2)
	def test_delete_dict_key_different_file_raises(self):
		json1 = self._json_file(0)
		json2 = self._json_file(1)
		write_differential_json({'a': 1}, [], json1)
		write_differential_json({'a': 1, 'b': 2}, [json1], json2)
		with self.assertRaises(ValueError):
			write_differential_json({'b': 2}, [json1], json2)
	def test_nested_dict_incremental_update(self):
		base_path = self._json_file(0)
		override_path = self._json_file(1)
		write_differential_json({'a': {'x': 1, 'y': 1}}, [], base_path)
		updated = {'a': {'x': 1, 'y': 2, 'z': 3}}
		write_differential_json(updated, [base_path], override_path)
		with open(override_path, 'r') as file:
			self.assertEqual({'a': {'y': 2, 'z': 3}}, json.load(file))
		self.assertEqual(updated, load_json([base_path, override_path]))
	def test_delete_nested_dict_key_same_file_ok(self):
		base_path = self._json_file(0)
		override_path = self._json_file(1)
		base = {'a': {'x': 1}}
		write_differential_json(base, [], base_path)
		write_differential_json({'a': {'x': 1, 'y': 2}}, [base_path], override_path)
		write_differential_json(base, [base_path], override_path)
		self.assertEqual(base, load_json([base_path, override_path]))
	def test_delete_nested_dict_key_different_file_raises(self):
		base_path = self._json_file(0)
		override_path = self._json_file(1)
		write_differential_json({'a': {'x': 1}}, [], base_path)
		write_differential_json({'a': {'x': 1, 'y': 2}}, [base_path], override_path)
		with self.assertRaises(ValueError):
			write_differential_json({'a': {'y': 2}}, [base_path], override_path)
		self.assertEqual({'a': {'x': 1, 'y': 2}}, load_json([base_path, override_path]))
	def test_nested_value_type_changes_round_trip(self):
		for base_value, updated_value in (
			({'key': 1}, None), ({'key': 1}, []), ({'key': 1}, False),
			(None, {'key': 1}), ([], {'key': 1}), (False, {'key': 1}),
			(['old'], ['new']), ({}, {'new': {}})
		):
			with self.subTest(base=base_value, updated=updated_value):
				base_path = self._json_file(0)
				override_path = self._json_file(1)
				base = {'settings': {'value': base_value, 'unchanged': True}}
				updated = {'settings': {'value': updated_value, 'unchanged': True}}
				write_differential_json(base, [], base_path)
				write_differential_json(updated, [base_path], override_path)
				with open(override_path, 'r') as file:
					self.assertEqual({'settings': {'value': updated_value}}, json.load(file))
				self.assertEqual(updated, load_json([base_path, override_path]))
	def setUp(self):
		self.temp_dir = mkdtemp()
	def tearDown(self):
		rmtree(self.temp_dir)
	def _check_write(self, obj):
		write_differential_json(obj, [], self._json_file())
		self.assertEqual(obj, load_json([self._json_file()]))
	def _json_file(self, i=0):
		return join(self.temp_dir, '%d.json' % i)