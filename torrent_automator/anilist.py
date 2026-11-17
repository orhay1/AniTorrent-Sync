import aiohttp

ANILIST_URL = "https://graphql.anilist.co"

# Fields shared by the Watching list query and the browse/search query.
MEDIA_FIELDS = """
    id
    title { romaji english }
    episodes
    format
    status
    seasonYear
    averageScore
    siteUrl
    coverImage { large medium color }
"""


def _media_info(media: dict) -> dict:
    """Flatten an AniList media object into the dict shape used across the app."""
    media = media or {}
    title = media.get("title") or {}
    cover = media.get("coverImage") or {}
    episodes = media.get("episodes")
    try:
        episodes = int(episodes) if episodes is not None else None
    except Exception:
        episodes = None
    return {
        "id": media.get("id"),
        "title": title.get("romaji") or "",
        "title_english": title.get("english") or "",
        "episodes": episodes,
        "format": media.get("format") or "",
        "status": media.get("status") or "",
        "season_year": media.get("seasonYear"),
        "score": media.get("averageScore"),
        "site_url": media.get("siteUrl") or "",
        "cover": cover.get("large") or cover.get("medium") or "",
        "color": cover.get("color") or "",
    }


async def _post(query: str, variables: dict) -> dict:
    async with aiohttp.ClientSession() as session:
        async with session.post(ANILIST_URL, json={"query": query, "variables": variables}) as resp:
            if resp.status != 200:
                raise RuntimeError(f"AniList request failed ({resp.status})")
            return await resp.json()


async def fetch_anilist_progress(username: str) -> dict:
    """
    Fetch only the user's 'Watching' anime list from AniList.
    Returns a mapping:
      {
        title_lowercase: {
          "progress": last_watched_episode (int),
          "episodes": season_total_episodes (int | None),
          "title": original romaji title,
          "cover": cover image URL, "color": cover accent color,
          "id", "title_english", "format", "status", "season_year", "score", "site_url"
        }
      }
    """
    print("📦 Running AniList 'Watching' fetch (aiohttp)")

    query = """
    query ($username: String) {
      MediaListCollection(userName: $username, type: ANIME, status_in: [CURRENT]) {
        lists {
          entries {
            media { %s }
            progress
          }
        }
      }
    }
    """ % MEDIA_FIELDS

    out: dict[str, dict] = {}
    try:
        data = await _post(query, {"username": username})
    except Exception as e:
        print(f"❌ Failed to fetch AniList: {e}")
        return {}

    lists = ((data.get("data") or {}).get("MediaListCollection") or {}).get("lists") or []
    for list_group in lists:
        for entry in list_group.get("entries", []):
            info = _media_info(entry.get("media"))
            if not info["title"]:
                continue
            info["progress"] = int(entry.get("progress") or 0)
            out[info["title"].lower()] = info
    return out


async def search_anilist(search: str | None = None, page: int = 1, per_page: int = 30) -> list[dict]:
    """
    Browse AniList anime. With a search string, results are sorted by match;
    without one, currently airing shows are returned sorted by trending.
    Each result has the same shape as the values of fetch_anilist_progress
    (minus "progress").
    """
    search = (search or "").strip() or None
    query = """
    query ($search: String, $page: Int, $perPage: Int, $sort: [MediaSort], $status: MediaStatus) {
      Page(page: $page, perPage: $perPage) {
        media(search: $search, type: ANIME, sort: $sort, status: $status, isAdult: false) { %s }
      }
    }
    """ % MEDIA_FIELDS
    variables = {
        "search": search,
        "page": page,
        "perPage": per_page,
        "sort": ["SEARCH_MATCH", "POPULARITY_DESC"] if search else ["TRENDING_DESC", "POPULARITY_DESC"],
        "status": None if search else "RELEASING",
    }
    data = await _post(query, variables)
    if data.get("errors"):
        raise RuntimeError(data["errors"][0].get("message", "AniList error"))
    media = ((data.get("data") or {}).get("Page") or {}).get("media") or []
    return [_media_info(m) for m in media if m]
