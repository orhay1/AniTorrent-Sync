
#### <p style="text-align:center;">A tool that fetches new episodes from Nyaa, matches them to the user’s AniList “Watching” list, and sends the prefered release to qBittorrent.</p>


## Features

- Fetches currently-watching shows from AniList (GraphQL API)
- Multi-query Nyaa search with group filtering and scoring
- Automatic selection of best release per episode
- Auto-enqueue to qBittorrent WebUI
- Configurable release groups, quality/codec, and AniList integration
- Modern GUI with logs, preferences, and group reordering



## Installation

	python -m venv venv
	venv\Scripts\activate
	python -m pip install -r requirements.txt

Requires Python 3.10+ and qBittorrent WebUI.

  

## Configuration

Change config.example.yaml to config.yaml and set:

 - anilist_username
 - quality / codec
 - qBittorrent WebUI credentials
 - show list (or use GUI to populate)
 - release group mode (single or priority)

  

### CLI Usage
  
	python main.py --config config.yaml

  
Options:
--non-interactive   --> Automatically sends best match to qBittorrent



### GUI Usage

	python gui.py

The GUI supports:

- Dark/Light theme.
- Fetching AniList shows.
- Selecting shows to add to config.
- Defining release groups and priority.
- Opening qBittorrent in WebUI.
- Running automation with real-time logs.

### To-Do

- Refine GUI layout and remove unused or redundant elements.
- Add support for fetching the last N releases for a selected group + show.
- Improve episode filtering to cover additional irregular naming edge cases.
- Create a standalone executable build for the GUI.