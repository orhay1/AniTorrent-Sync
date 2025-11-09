#!/usr/bin/env python3
import sys
from pathlib import Path

# Add the current directory to the Python path
sys.path.append(str(Path(__file__).parent))

import argparse
import logging
import asyncio
import re
from difflib import SequenceMatcher  # 🟩 added

from torrent_automator.config import load_config
from torrent_automator.nyaa import search_nyaa, extract_magnet
from torrent_automator.qbittorrent import QBitClient
from torrent_automator.anilist import fetch_anilist_progress


def extract_episode_number(title: str) -> str | None:
    """
    Extract episode number from a torrent title.
    Handles patterns like:
    - S03E07
    - - 07
    - Ep 07
    - Episode 07v2
    Returns the episode as a string (e.g. "07" or "07v2").
    """
    patterns = [
        r"[ _-][Ee][Pp]?\s?(\d{1,3}(?:v\d)?)",      # Ep 03, E03, - 03, etc.
        r"[Ss]\d{1,2}[Ee](\d{1,3}(?:v\d)?)",         # S03E07 or S1E2
        r"(?:Episode\s*)(\d{1,3}(?:v\d)?)",          # Episode 03
        r"[ _-](\d{1,3}(?:v\d)?)"                    # fallback simple number
    ]

    for pat in patterns:
        match = re.search(pat, title)
        if match:
            ep = match.group(1)
            # 🟩 skip 720, 1080, 2160 numbers
            if ep in ("720", "1080", "2160"):
                continue
            return ep.zfill(2)
    return None


def normalize_show_name(name: str) -> str:
    """Simplify show names for consistent comparison (case-insensitive)."""
    name = re.sub(r"\[.*?\]", "", name)
    name = re.sub(r"\(.*?\)", "", name)  # 🟩 remove parentheses too
    name = re.sub(r"[^a-zA-Z0-9\s]", "", name)  # 🟩 strip symbols
    name = re.sub(r"\s+", " ", name)
    return name.lower().strip()


def similarity(a: str, b: str) -> float:  # 🟩 added fuzzy matching helper
    return SequenceMatcher(None, a, b).ratio()


def ask_user_to_accept(title: str, magnet: str) -> bool:
    """Ask the user whether to accept this torrent for download."""
    print("\n🔹 Torrent:")
    print(f"Title : {title}")
    print(f"Magnet: {magnet[:60]}...")
    while True:
        choice = input("Add this torrent to qBittorrent? [y/N]: ").strip().lower()
        if choice in ("y", "yes"):
            return True
        elif choice in ("n", "no", ""):
            return False
        else:
            print("Please enter 'y' or 'n'.")


# 🟩 fully async main to avoid repeated asyncio.run()
async def main_async(args):
    logging.basicConfig(level=logging.INFO)

    try:
        config = load_config(args.config)
        logging.info("✅ Config loaded successfully!")
        logging.info(f"Shows from config: {config['shows']}")

        qb = QBitClient(
            host=config["qbittorrent"]["host"],
            port=config["qbittorrent"]["port"],
            username=config["qbittorrent"]["username"],
            password=config["qbittorrent"]["password"],
            use_https=config["qbittorrent"].get("https", False)
        )
        qb.login()

        # 📡 AniList fetch
        anilist_progress = {}
        if "anilist_username" in config:
            logging.info("🔗 Fetching AniList 'Watching' list...")
            anilist_progress = await fetch_anilist_progress(config["anilist_username"])
            print("📺 AniList Watching List:")
            for title, ep in anilist_progress.items():
                print(f"  {title} → Ep {ep}")

        for show in config["shows"]:
            norm_show = normalize_show_name(show)
            matched_title = None
            best_score = 0.0
            for ani_title in anilist_progress:
                score = similarity(norm_show, ani_title)
                if score > best_score and score > 0.6:  # 🟩 fuzzy threshold
                    matched_title = ani_title
                    best_score = score

            if not matched_title:
                print(f"⏭️ '{show}' not found in AniList 'Watching', skipping.")
                continue

            last_seen = anilist_progress[matched_title]
            print(f"\n📺 {matched_title}: Last watched episode {last_seen}")

            query = f"{show} {config['quality']} {config['codec']}"
            results = await search_nyaa(query, allowed_groups=config.get("release_groups"))

            # Filter unwatched episodes
            filtered_results = []
            for r in results:
                ep_num = extract_episode_number(r["title"])
                try:
                    if ep_num and int(re.sub(r'v\d', '', ep_num)) > last_seen:
                        filtered_results.append(r)
                except ValueError:
                    pass

            if not filtered_results:
                print(f"⏭️ No new episodes for {show}")
                continue

            print(f"🔍 Found {len(filtered_results)} new episode(s) for {show}")

            # 🟩 Only add one (highest-priority) result
            r = filtered_results[0]
            magnet = await extract_magnet(r["link"])
            if not magnet:
                print(f"⚠️ Magnet not found for {r['title']}")
                continue

            if not args.non_interactive:
                if not ask_user_to_accept(r["title"], magnet):
                    print("⏭️ Skipped by user.")
                    continue

            try:
                qb.add_magnet(magnet)
                print(f"✅ Sent {r['title']} to qBittorrent")
            except Exception as e:
                print(f"❌ Failed to add {r['title']}: {e}")

    except Exception as e:
        logging.error(f"❌ Failed: {e}")
        return


def main():
    parser = argparse.ArgumentParser(description="Torrent Automator Tool")
    parser.add_argument("--config", type=str, required=True, help="Path to config.yaml")
    parser.add_argument("--non-interactive", action="store_true", help="Auto-accept all matches")
    args = parser.parse_args()
    asyncio.run(main_async(args))


if __name__ == "__main__":
    main()
