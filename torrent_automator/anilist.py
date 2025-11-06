import aiohttp

async def fetch_anilist_progress(username: str) -> dict:
    """
    Fetch only the user's 'Watching' anime list from AniList.
    Returns {title_lowercase: last_watched_episode}.
    """
    print("📦 Running AniList 'Watching' fetch (aiohttp)")

    query = """
    query ($username: String) {
      MediaListCollection(userName: $username, type: ANIME, status_in: [CURRENT]) {
        lists {
          entries {
            media {
              title { romaji }
              episodes
            }
            progress
          }
        }
      }
    }
    """

    url = "https://graphql.anilist.co"
    progress = {}

    async with aiohttp.ClientSession() as session:
        try:
            async with session.post(url, json={"query": query, "variables": {"username": username}}) as resp:
                if resp.status != 200:
                    print(f"❌ AniList request failed ({resp.status})")
                    return {}
                data = await resp.json()
        except Exception as e:
            print(f"❌ Failed to connect to AniList: {e}")
            return {}

    lists = data.get("data", {}).get("MediaListCollection", {}).get("lists", [])
    for list_group in lists:
        for entry in list_group.get("entries", []):
            title = entry["media"]["title"]["romaji"].lower()
            progress[title] = entry["progress"]
    return progress
