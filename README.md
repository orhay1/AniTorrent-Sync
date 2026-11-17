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
- AniList cover art when browsing your Watching list, searching AniList, and picking shows
- Review step before anything is downloaded: see every release, the group it comes from, and which other groups have it

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

Before sending anything, the CLI prints the download plan (quality, codec, selected groups, and per show the chosen release and the groups available) and asks once: `y` to send all pre-selected releases, `s` to pick individually, `n` to cancel.

Options:

- `--non-interactive` – skip the confirmation and automatically send the pre-selected releases to qBittorrent

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
- Fetching AniList shows, shown as a cover grid with watch progress, grouped into **Behind** (aired episodes you haven't watched), **Finished airing** (season is out, not finished by you) and **Up to date** (with a countdown to the next episode)
- A download basket: click a cover to add the show (click again to remove it), then **Download basket** finds the new episodes for just those shows (the basket is the `shows` list in `config.yaml`, so the CLI uses it too)
- Browsing AniList (trending airing shows or search) to add any show
- A review dialog before downloading, listing each episode, the chosen group, other available groups, and shows that were skipped and why
- Defining release groups and priority
- Batch automation with real-time logs
- Recent releases tab (multi-show, group, count, quality/codec override, optional episode)
- Load popular release groups into the picker
- Save/reload config from the menu
- Open qBittorrent (WebUI or app)

## Tests

```bash
python -m unittest discover -s tests
```

## To-Do

- Refine the GUI layout and remove unused or redundant elements
- Improve episode filtering to cover additional irregular naming edge cases
- Create a standalone executable build for the GUI
