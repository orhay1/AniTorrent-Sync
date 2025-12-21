import httpx
import xml.etree.ElementTree as ET
import re
from urllib.parse import quote_plus
from bs4 import BeautifulSoup

async def search_nyaa(query: str, allowed_groups=None, limit: int = 15):
    """
    Search Nyaa.si using its RSS feed and return a filtered list of torrents.
    Only includes results from allowed_groups if provided (prefix match like "[ASW] ...").
    """
    url = f"https://nyaa.si/?page=rss&q={query.replace(' ', '+')}"

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
        torrent_page_url = guid_el.text or ""

        # Filter by allowed release groups (if given)
        if allowed_groups:
            lowered = title.lower()
            # accept if any priority group matches title prefix like: [group]
            if not any(lowered.startswith(f"[{g.lower()}]") for g in allowed_groups):
                continue

        results.append({
            "title": title,
            "link": torrent_page_url
        })

        if len(results) >= limit:
            break

    return results


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
