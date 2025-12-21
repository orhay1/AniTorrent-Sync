# Torrent Automator

A tool that fetches new episodes from Nyaa, matches them to the user's AniList *Watching* list, and sends the preferred release to qBittorrent.

## Features

- Fetch currently-watching shows from AniList (GraphQL API)
- Perform multi-query Nyaa searches with group filtering and scoring
- Automatically select the best release per episode
- Auto-enqueue torrents to the qBittorrent WebUI
- Configure release groups, quality/codec, and AniList integration
- Fetch recent releases for one or more shows (optional episode filter)
- Built-in popular release group list
- Use the modern GUI to view logs, tweak preferences, and reorder groups

## Installation

```bash
python -m venv venv
venv\Scripts\activate
python -m pip install -r requirements.txt
```

Requires Python 3.10+ and the qBittorrent WebUI.

## Configuration

Copy `config.example.yaml` to `config.yaml`, then configure:

- `anilist_username`
- `quality` / `codec`
- qBittorrent WebUI credentials
- Show list (or populate via the GUI)
- Release group mode (`single` or `priority`)

## CLI Usage

Activate the virtual environment, open a terminal in the project root, then run:

```bash
python main.py --config config.yaml
```

You can also use the helper script:

```bash
runCLI.bat
```

Options:

- `--non-interactive` – automatically send the best match to qBittorrent

## GUI Usage

Activate the virtual environment, open a terminal in the project root, then run:

```bash
python gui.py
```

or launch the helper script:

```bash
runGUI.bat
```

The GUI supports:

- Dark/Light theme
- Fetching AniList shows
- Selecting shows to add to the config
- Defining release groups and priority
- Batch automation with real-time logs
- Recent releases tab (multi-show, group, count, quality/codec override, optional episode)
- Load popular release groups into the picker
- Save/reload config from the menu
- Open qBittorrent (WebUI or app)

## To-Do

- Refine the GUI layout and remove unused or redundant elements
- Improve episode filtering to cover additional irregular naming edge cases
- Create a standalone executable build for the GUI
