# Favorites

Favorites keeps a curated list of directory locations.

## Commands

- `Ctrl+B`: Show favorites.
- `Add Current Folder to Favorites`: Add or promote the active location.
- `Remove from Favorites`: Remove the active location or choose one.
- `Rename Favorite`: Choose a favorite and change its display name.

Favorites are saved under `UserSettings` and support every location scheme
understood by the active pane.

Re-adding a favorite moves it to the top without changing its display name.
Selecting a missing or inaccessible location reports the problem without
navigating. For UNC locations, the selected-item availability check can wait
for the network before navigation begins.

Custom key bindings can prefill the search query:

```json
{ "keys": ["Ctrl+Alt+B"], "command": "show_favorites", "args": {"query": "pro"} }
```

## Settings

The bundled defaults are stored in `Favorites.json`:

```json
{
	"favorites": [],
	"max_favorites": 200
}
```

Create
`UserSettings/Plugins/User/Settings/Favorites (Windows).json` to override the
defaults. `max_favorites` limits the saved list; adding beyond the limit asks
before replacing the oldest favorite.