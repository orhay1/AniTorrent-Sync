import httpx
import xml.etree.ElementTree as ET
from bs4 import BeautifulSoup

async def search_nyaa(query: str, allowed_groups=None, limit: int = 2):
    """
    Search Nyaa.si using its RSS feed and return a filtered list of torrents.
    Only includes results from allowed_groups if provided.
    """
    url = f"https://nyaa.si/?page=rss&q={query.replace(' ', '+')}"

    async with httpx.AsyncClient() as client:
        response = await client.get(url)
        response.raise_for_status()

    root = ET.fromstring(response.text)
    results = []

    for item in root.findall("./channel/item"):
        title = item.find("title").text
        torrent_page_url = item.find("guid").text  # This is the view page, not .torrent

        # ✅ Filter by allowed release groups
        if allowed_groups:
            if not any(title.startswith(f"[{group}]") for group in allowed_groups):
                continue

        results.append({
            "title": title,
            "link": torrent_page_url  # 👈 this is the correct one to extract magnet from
        })

        if len(results) >= limit:
            break
    # ✅ Sort results by group priority
    if allowed_groups:
        results.sort(key=lambda r: score_result(r["title"], allowed_groups))

    return results



def score_result(title: str, group_priority: list[str]) -> int:
    """
    Give a higher score to torrents from higher-priority groups.
    Lower score = better match (for sorting).
    """
    for index, group in enumerate(group_priority):
        if title.startswith(f"[{group}]"):
            return index  # Lower index = higher priority
    return len(group_priority)  # Lowest priority if group not found




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

    # Find <a> tags where href starts with magnet:? and text contains 'Magnet'
    for a in soup.find_all("a", href=True):
        href = a["href"]
        text = a.get_text(strip=True).lower()
        if href.startswith("magnet:?") and "magnet" in text:
            return href

    print("⚠️ Magnet link not found in HTML.")
    return None