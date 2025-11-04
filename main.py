#!/usr/bin/env python3
import sys
from pathlib import Path

# Add the current directory to the Python path
sys.path.append(str(Path(__file__).parent))

import argparse
import logging
import asyncio

from torrent_automator.config import load_config
from torrent_automator.nyaa import search_nyaa, extract_magnet
from torrent_automator.qbittorrent import QBitClient

import re

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
        r"[ _-](\d{1,3}(?:v\d)?)"                    # fallback simple number
    ]

    for pat in patterns:
        match = re.search(pat, title)
        if match:
            return match.group(1).zfill(2)
    return None

def normalize_show_name(name: str) -> str:
    """
    Simplify show names for consistent comparison (case-insensitive).
    Removes brackets and extra spaces.
    """
    name = re.sub(r"\[.*?\]", "", name)  # remove [Group] tags
    name = re.sub(r"\s+", " ", name)     # normalize spaces
    return name.lower().strip()


def ask_user_to_accept(title: str, magnet: str) -> bool:
    """
    Ask the user whether to accept this torrent for download.
    """
    print("\n🔹 Torrent:")
    print(f"Title : {title}")
    print(f"Magnet: {magnet[:60]}...")  # Truncate for readability

    while True:
        choice = input("Add this torrent to qBittorrent? [y/N]: ").strip().lower()
        if choice in ("y", "yes"):
            return True
        elif choice in ("n", "no", ""):
            return False
        else:
            print("Please enter 'y' or 'n'.")


def main():
    # 🧾 Argument parsing
    parser = argparse.ArgumentParser(description="Torrent Automator Tool")
    parser.add_argument("--config", type=str, required=True, help="Path to config.yaml")
    parser.add_argument("--non-interactive", action="store_true", help="Auto-accept all matches")
    args = parser.parse_args()

    interactive = not args.non_interactive  # This sets interactive mode correctly

    # 🪵 Logging
    logging.basicConfig(level=logging.INFO)

    try:
        # 📂 Load config
        config = load_config(args.config)
        logging.info("✅ Config loaded successfully!")
        logging.info(f"Shows: {config['shows']}")

        # 🔐 Create and login to qBittorrent
        qb = QBitClient(
            host=config["qbittorrent"]["host"],
            port=config["qbittorrent"]["port"],
            username=config["qbittorrent"]["username"],
            password=config["qbittorrent"]["password"],
            use_https=config["qbittorrent"].get("https", False)
        )
        qb.login()
        
        processed_episodes = {}  # { show_name: set(["01", "02", ...]) }

        # 🔍 Search for torrents and process each one
        for show in config["shows"]:
            query = f"{show} {config['quality']} {config['codec']}"
            results = asyncio.run(search_nyaa(query, allowed_groups=config.get("release_groups")))

            print(f"\nResults for '{query}':")
            for r in results:
                magnet = asyncio.run(extract_magnet(r["link"]))
                if magnet:
                    r["magnet"] = magnet
                    
                    episode_num = extract_episode_number(r["title"])
                    show_key = normalize_show_name(show)

                    # Create tracking set for this show if missing
                    if show_key not in processed_episodes:
                        processed_episodes[show_key] = set()

                    # Skip if already downloaded/accepted
                    if episode_num and episode_num in processed_episodes[show_key]:
                        print(f"⏭️ Skipping duplicate episode {episode_num} for {show}")
                        continue

                    # Ask user to confirm if in interactive mode
                    if interactive:
                        if not ask_user_to_accept(r["title"], magnet):
                            print("⏭️ Skipped.")
                            continue

                    # Add magnet to qBittorrent
                    try:
                        qb.add_magnet(magnet)
                        print("✅ Sent to qBittorrent")
                        if episode_num:
                            processed_episodes[show_key].add(episode_num)
                    except Exception as e:
                        print(f"❌ Failed to add: {e}")
                        
                    print(f"🔍 Parsed episode: {episode_num}, show key: {show_key}")

                else:
                    print(f"- {r['title']}")
                    print("⚠️ Magnet not found")

    except Exception as e:
        logging.error(f"❌ Failed: {e}")
        return


if __name__ == "__main__":
    main()
