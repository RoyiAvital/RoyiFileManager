from copy import deepcopy
from favorites import AddCurrentFolderToFavorites, RemoveFromFavorites, \
	RenameFavorite, ShowFavorites, get_favorite_items
from favorites.store import AddResult, DEFAULT_MAX_FAVORITES, Favorite, \
	FavoritesStore
from fman import YES
from fman.impl.plugins.plugin import _get_command_name
from threading import Thread
from unittest import TestCase
from unittest.mock import Mock, patch

import favorites


class FavoritesStoreTest(TestCase):
	def test_adds_new_favorite_at_top_with_default_name(self):
		store = FavoritesStore.load({'favorites': [
			{'name': 'Old', 'url': 'file:///C:/Old'}
		]}, windows=True)

		store.add('file:///D:/Projects/')

		self.assertEqual(
			(
				Favorite('Projects', 'file:///D:/Projects'),
				Favorite('Old', 'file:///C:/Old')
			),
			store.favorites
		)

	def test_existing_favorite_moves_to_top_without_changing_name(self):
		store = FavoritesStore.load({'favorites': [
			{'name': 'Keep this name', 'url': 'file:///D:/Projects'},
			{'name': 'Other', 'url': 'file:///C:/Other'}
		]}, windows=True)

		result = store.add('file:///d:/projects/', 'Ignored replacement')

		self.assertEqual(2, len(store.favorites))
		self.assertEqual('Keep this name', store.favorites[0].name)
		self.assertEqual(store.favorites[0], result.favorite)
		self.assertIsNone(result.evicted)

	def test_non_file_identity_remains_case_sensitive(self):
		store = FavoritesStore(windows=True)
		store.add('example://Folder', 'Upper')
		store.add('example://folder', 'Lower')

		self.assertEqual(2, len(store.favorites))

	def test_drive_root_uses_human_readable_name(self):
		store = FavoritesStore(windows=True)

		store.add('file:///C:/')

		self.assertEqual('C:\\', store.favorites[0].name)

	def test_remove_and_rename_preserve_remaining_order(self):
		store = FavoritesStore.load({'favorites': [
			{'name': 'A', 'url': 'file:///C:/A'},
			{'name': 'B', 'url': 'file:///C:/B'},
			{'name': 'C', 'url': 'file:///C:/C'}
		]}, windows=True)

		self.assertTrue(store.rename('file:///c:/b', 'Renamed'))
		self.assertEqual('A', store.favorites[0].name)
		self.assertEqual('Renamed', store.favorites[1].name)
		self.assertEqual('C', store.favorites[2].name)
		self.assertEqual('A', store.remove('file:///c:/a').name)
		self.assertEqual(['Renamed', 'C'], [f.name for f in store.favorites])

	def test_invalid_entries_and_settings_fall_back(self):
		store = FavoritesStore.load({
			'favorites': [
				{'name': 'Valid', 'url': 'file:///C:/Valid'},
				{'name': '', 'url': 'file:///C:/Blank'},
				{'name': 'Missing URL'},
				'not a mapping'
			],
			'max_favorites': True
		}, windows=True)

		self.assertEqual((Favorite('Valid', 'file:///C:/Valid'),), store.favorites)
		self.assertEqual(DEFAULT_MAX_FAVORITES, store.max_favorites)
		self.assertEqual(4, store.invalid_count)

	def test_limit_discards_entries_below_cap_and_evicts_bottom(self):
		store = FavoritesStore.load({
			'favorites': [
				{'name': 'A', 'url': 'file:///C:/A'},
				{'name': 'B', 'url': 'file:///C:/B'},
				{'name': 'C', 'url': 'file:///C:/C'}
			],
			'max_favorites': 2
		}, windows=True)

		self.assertEqual(['A', 'B'], [f.name for f in store.favorites])
		self.assertEqual(1, store.invalid_count)
		self.assertTrue(store.would_evict('file:///C:/D'))
		self.assertEqual(
			AddResult(
				Favorite('D', 'file:///C:/D'),
				Favorite('B', 'file:///C:/B')
			),
			store.add('file:///C:/D')
		)
		self.assertEqual(['D', 'A'], [f.name for f in store.favorites])

	def test_to_json_returns_independent_round_trip_data(self):
		store = FavoritesStore(windows=True)
		store.add('file:///C:/A', 'A')

		data = store.to_json()
		data['favorites'][0]['name'] = 'Changed'

		self.assertEqual('A', store.favorites[0].name)
		self.assertEqual(
			store.to_json(), FavoritesStore.load(store.to_json(), windows=True).to_json()
		)


class FavoriteItemsTest(TestCase):
	def setUp(self):
		self.favorites = (
			Favorite('Projects', 'file:///D:/Work'),
			Favorite('Archive', 'file:///D:/Projects/Archive')
		)

	def test_empty_query_preserves_order(self):
		self.assertEqual(
			['Projects', 'Archive'],
			[item.title for item in get_favorite_items(self.favorites, '')]
		)

	def test_name_match_ranks_before_path_match(self):
		items = get_favorite_items(self.favorites, 'pro')

		self.assertEqual(['Projects', 'Archive'], [item.title for item in items])
		self.assertEqual([0, 1, 2], items[0].highlight)
		self.assertEqual([], items[1].highlight)

	def test_mixed_case_path_query_is_case_insensitive(self):
		items = get_favorite_items(self.favorites, 'D:\\Pro')

		self.assertEqual(['Archive'], [item.title for item in items])
		self.assertEqual([], items[0].highlight)


class FavoriteCommandTest(TestCase):
	def setUp(self):
		super().setUp()
		favorites._invalid_entries_reported = False

	def test_command_names_are_registered_from_class_names(self):
		self.assertEqual({
			'add_current_folder_to_favorites', 'show_favorites',
			'remove_from_favorites', 'rename_favorite'
		}, {
			_get_command_name(command) for command in (
				AddCurrentFolderToFavorites, ShowFavorites,
				RemoveFromFavorites, RenameFavorite
			)
		})

	@patch('favorites.show_status_message')
	@patch('favorites.save_json')
	def test_add_refuses_null_location(
		self, save_json_mock, show_status_message_mock
	):
		pane = Mock()
		pane.get_path.return_value = 'null://'

		AddCurrentFolderToFavorites(pane)()

		save_json_mock.assert_not_called()
		show_status_message_mock.assert_called_once()

	@patch('favorites.show_status_message')
	@patch('favorites.save_json')
	@patch('favorites.load_json', return_value={
		'favorites': [], 'max_favorites': 200
	})
	def test_add_current_folder_saves_favorite(
		self, load_json_mock, save_json_mock, show_status_message_mock
	):
		pane = Mock()
		pane.get_path.return_value = 'file:///D:/Projects'

		AddCurrentFolderToFavorites(pane)()

		self.assertEqual(
			'file:///D:/Projects',
			save_json_mock.call_args.args[1]['favorites'][0]['url']
		)
		show_status_message_mock.assert_called_once_with(
			'Added Projects to favorites.', timeout_secs=3
		)

	@patch('favorites.exists', return_value=True)
	@patch('favorites.show_quicksearch')
	@patch('favorites.load_json')
	def test_show_opens_selected_existing_favorite(
		self, load_json_mock, show_quicksearch_mock, exists_mock
	):
		url = 'file:///D:/Projects'
		load_json_mock.return_value = {
			'favorites': [{'name': 'Projects', 'url': url}]
		}
		show_quicksearch_mock.side_effect = lambda get_items, *args: (
			'', list(get_items(''))[0].value
		)
		pane = Mock()

		ShowFavorites(pane)()

		pane.run_command.assert_called_once_with(
			'open_directory', {'url': url}
		)

	@patch('favorites.show_alert')
	@patch('favorites.exists', return_value=False)
	@patch('favorites.show_quicksearch')
	@patch('favorites.load_json')
	def test_show_reports_missing_favorite_without_navigation(
		self, load_json_mock, show_quicksearch_mock, exists_mock,
		show_alert_mock
	):
		url = 'file:///D:/Missing'
		load_json_mock.return_value = {
			'favorites': [{'name': 'Missing', 'url': url}]
		}
		show_quicksearch_mock.side_effect = lambda get_items, *args: (
			'', list(get_items(''))[0].value
		)
		pane = Mock()

		ShowFavorites(pane)()

		show_alert_mock.assert_called_once()
		pane.run_command.assert_not_called()

	@patch('favorites.show_alert')
	@patch('favorites.exists', side_effect=OSError('Unavailable'))
	@patch('favorites.show_quicksearch')
	@patch('favorites.load_json')
	def test_show_reports_access_error_without_navigation(
		self, load_json_mock, show_quicksearch_mock, exists_mock,
		show_alert_mock
	):
		url = 'file:///D:/Unavailable'
		load_json_mock.return_value = {
			'favorites': [{'name': 'Unavailable', 'url': url}]
		}
		show_quicksearch_mock.side_effect = lambda get_items, *args: (
			'', list(get_items(''))[0].value
		)
		pane = Mock()

		ShowFavorites(pane)()

		self.assertIn('Unavailable', show_alert_mock.call_args.args[0])
		pane.run_command.assert_not_called()

	@patch('favorites.exists', side_effect=NotImplementedError())
	@patch('favorites.show_quicksearch')
	@patch('favorites.load_json')
	def test_show_defers_unsupported_existence_check_to_open_directory(
		self, load_json_mock, show_quicksearch_mock, exists_mock
	):
		url = 'example://Projects'
		load_json_mock.return_value = {
			'favorites': [{'name': 'Projects', 'url': url}]
		}
		show_quicksearch_mock.side_effect = lambda get_items, *args: (
			'', list(get_items(''))[0].value
		)
		pane = Mock()

		ShowFavorites(pane)()

		pane.run_command.assert_called_once_with(
			'open_directory', {'url': url}
		)

	@patch('favorites.show_status_message')
	@patch('favorites.show_alert', return_value=YES)
	@patch('favorites.save_json')
	@patch('favorites.load_json', return_value={
		'favorites': [{'name': 'Old', 'url': 'file:///C:/Old'}],
		'max_favorites': 1
	})
	def test_add_at_limit_confirms_and_evicts_oldest(
		self, load_json_mock, save_json_mock, show_alert_mock,
		show_status_message_mock
	):
		pane = Mock()
		pane.get_path.return_value = 'file:///C:/New'

		AddCurrentFolderToFavorites(pane)()

		show_alert_mock.assert_called_once()
		self.assertEqual(
			[{'name': 'New', 'url': 'file:///C:/New'}],
			save_json_mock.call_args.args[1]['favorites']
		)

	@patch('favorites.show_status_message')
	@patch('favorites.show_alert', return_value=YES)
	@patch('favorites.save_json')
	@patch('favorites.load_json')
	def test_remove_current_favorite_after_confirmation(
		self, load_json_mock, save_json_mock, show_alert_mock,
		show_status_message_mock
	):
		url = 'file:///C:/Current'
		load_json_mock.return_value = {
			'favorites': [{'name': 'Current', 'url': url}]
		}
		pane = Mock()
		pane.get_path.return_value = url

		RemoveFromFavorites(pane)()

		show_alert_mock.assert_called_once()
		self.assertEqual([], save_json_mock.call_args.args[1]['favorites'])

	@patch('favorites.show_status_message')
	@patch('favorites.show_alert', return_value=YES)
	@patch('favorites.show_quicksearch')
	@patch('favorites.save_json')
	@patch('favorites.load_json')
	def test_remove_chosen_favorite_when_current_is_not_favorite(
		self, load_json_mock, save_json_mock, show_quicksearch_mock,
		show_alert_mock, show_status_message_mock
	):
		url = 'file:///C:/Saved'
		load_json_mock.return_value = {
			'favorites': [{'name': 'Saved', 'url': url}]
		}
		show_quicksearch_mock.return_value = '', url
		pane = Mock()
		pane.get_path.return_value = 'file:///C:/Other'

		RemoveFromFavorites(pane)()

		self.assertEqual([], save_json_mock.call_args.args[1]['favorites'])

	@patch('favorites.show_prompt', return_value=('   ', True))
	@patch('favorites.show_quicksearch')
	@patch('favorites.save_json')
	@patch('favorites.load_json')
	def test_rename_ignores_blank_name(
		self, load_json_mock, save_json_mock, show_quicksearch_mock,
		show_prompt_mock
	):
		url = 'file:///C:/Current'
		load_json_mock.return_value = {
			'favorites': [{'name': 'Current', 'url': url}]
		}
		show_quicksearch_mock.return_value = '', url

		RenameFavorite(Mock())()

		save_json_mock.assert_not_called()

	@patch('favorites.show_prompt', return_value=('Changed', False))
	@patch('favorites.show_quicksearch')
	@patch('favorites.save_json')
	@patch('favorites.load_json')
	def test_rename_cancel_makes_no_change(
		self, load_json_mock, save_json_mock, show_quicksearch_mock,
		show_prompt_mock
	):
		url = 'file:///C:/Current'
		load_json_mock.return_value = {
			'favorites': [{'name': 'Current', 'url': url}]
		}
		show_quicksearch_mock.return_value = '', url

		RenameFavorite(Mock())()

		save_json_mock.assert_not_called()

	@patch('favorites.show_status_message')
	def test_invalid_entries_are_reported_once_per_session(
		self, show_status_message_mock
	):
		favorites._report_invalid_entries(2)
		favorites._report_invalid_entries(2)

		show_status_message_mock.assert_called_once_with(
			'Ignored 2 invalid or excess favorite entries.', timeout_secs=4
		)

	@patch('favorites.show_status_message')
	def test_concurrent_adds_preserve_both_updates(self, show_status_message_mock):
		state = {'favorites': [], 'max_favorites': 200}

		def load(*args, **kwargs):
			return deepcopy(state)

		def save(name, value):
			state.clear()
			state.update(deepcopy(value))

		left_pane = Mock()
		left_pane.get_path.return_value = 'file:///C:/Left'
		right_pane = Mock()
		right_pane.get_path.return_value = 'file:///C:/Right'
		with patch('favorites.load_json', side_effect=load), \
				patch('favorites.save_json', side_effect=save):
			threads = [
				Thread(target=AddCurrentFolderToFavorites(pane))
				for pane in (left_pane, right_pane)
			]
			for thread in threads:
				thread.start()
			for thread in threads:
				thread.join()

		self.assertEqual(
			{'file:///C:/Left', 'file:///C:/Right'},
			{favorite['url'] for favorite in state['favorites']}
		)

	@patch('favorites.show_status_message')
	def test_add_during_remove_confirmation_preserves_both_updates(
		self, show_status_message_mock
	):
		remove_url = 'file:///C:/Remove'
		keep_url = 'file:///C:/Keep'
		add_url = 'file:///C:/Added'
		state = {
			'favorites': [
				{'name': 'Remove', 'url': remove_url},
				{'name': 'Keep', 'url': keep_url}
			],
			'max_favorites': 200
		}

		def load(*args, **kwargs):
			return deepcopy(state)

		def save(name, value):
			state.clear()
			state.update(deepcopy(value))

		add_pane = Mock()
		add_pane.get_path.return_value = add_url

		def confirm(*args):
			thread = Thread(target=AddCurrentFolderToFavorites(add_pane))
			thread.start()
			thread.join()
			return YES

		remove_pane = Mock()
		remove_pane.get_path.return_value = remove_url
		with patch('favorites.load_json', side_effect=load), \
				patch('favorites.save_json', side_effect=save), \
				patch('favorites.show_alert', side_effect=confirm):
			RemoveFromFavorites(remove_pane)()

		self.assertEqual(
			{add_url, keep_url},
			{favorite['url'] for favorite in state['favorites']}
		)