import httpx
import xml.etree.ElementTree as ET
import re
from urllib.parse import quote_plus
from bs4 import BeautifulSoup

def release_group(title: str) -> str:
    """Return the release group from a title like "[ASW] Show - 01", or ""."""
    m = re.match(r"^\s*\[(.*?)\]", title or "")
    return m.group(1).strip() if m else ""


def in_groups(title: str, allowed_groups) -> bool:
    """True if the title's [group] prefix matches one of allowed_groups (or none given)."""
    if not allowed_groups:
        return True
    lowered = (title or "").lower()
    return any(lowered.startswith(f"[{g.lower()}]") for g in allowed_groups if g)


async def fetch_nyaa_rss(query: str) -> list[dict]:
    """
    Fetch the raw Nyaa.si RSS results for a query (no group filtering).
    Each result: {"title", "link", "group"}.
    """
    url = f"https://nyaa.si/?page=rss&q={quote_plus(query)}"

    async with httpx.AsyncClient() as client:
        response = await client.get(url)
        response.raise_for_status()

    root = ET.fromstring(response.text)
    results = []

    for item in root.findall("./channel/item"):
        title_el = item.find("title")
        guid_el = item.find("guid")
        if title_el is None or guid_el is None:
            continue

        title = title_el.text or ""
        results.append({
            "title": title,
            "link": guid_el.text or "",
            "group": release_group(title),
        })

    return results


async def search_nyaa(query: str, allowed_groups=None, limit: int = 15):
    """
    Search Nyaa.si using its RSS feed and return a filtered list of torrents.
    Only includes results from allowed_groups if provided (prefix match like "[ASW] ...").
    """
    results = [r for r in await fetch_nyaa_rss(query) if in_groups(r["title"], allowed_groups)]
    return results[:limit]


def score_result(title: str, group_priority: list[str]) -> int:
    """
    Lower score = higher priority. Unknown groups -> lowest priority.
    """
    low = title.lower()
    for index, group in enumerate(group_priority):
        if low.startswith(f"[{group.lower()}]"):
            return index
    return len(group_priority)


async def extract_magnet(link: str) -> str | None:
    """
    Given a Nyaa.si torrent page URL, extract the magnet link robustly.
    """
    async with httpx.AsyncClient() as client:
        try:
            response = await client.get(link)
            response.raise_for_status()
        except httpx.HTTPError as e:
            print(f"⚠️ Failed to load torrent page: {e}")
            return None

    soup = BeautifulSoup(response.text, "html.parser")

    for a in soup.find_all("a", href=True):
        href = a["href"]
        text = a.get_text(strip=True).lower()
        if href.startswith("magnet:?") and "magnet" in text:
            return href

    print("⚠️ Magnet link not found in HTML.")
    return None


async def fetch_nyaa_groups(query: str = "1080p", pages: int = 5, max_groups: int = 150) -> list[str]:
    """
    Scrape Nyaa search pages and extract distinct release group names from titles.
    """
    groups: list[str] = []
    seen = set()

    async with httpx.AsyncClient() as client:
        for page in range(1, max(1, pages) + 1):
            url = f"https://nyaa.si/?q={quote_plus(query)}&p={page}"
            response = await client.get(url)
            response.raise_for_status()

            soup = BeautifulSoup(response.text, "html.parser")
            for row in soup.select("table.torrent-list tbody tr"):
                title_link = row.select_one("td.col-2 a[href^='/view/']")
                if not title_link:
                    continue
                title = title_link.get_text(strip=True)
                m = re.match(r"^\[(.*?)\]", title)
                if not m:
                    continue
                group = m.group(1).strip()
                if group and group not in seen:
                    seen.add(group)
                    groups.append(group)
                    if len(groups) >= max_groups:
                        return groups

    return groups
