#!/usr/bin/env python3
import sys
from pathlib import Path

# Add the current directory to the Python path
sys.path.append(str(Path(__file__).parent))


import argparse
import logging
from torrent_automator.config import load_config

import asyncio
from torrent_automator.nyaa import search_nyaa, extract_magnet


def main():
    parser = argparse.ArgumentParser(description="Torrent Automator Tool")
    parser.add_argument("--config", type=str, required=True, help="Path to config.yaml")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO)

    try:
        config = load_config(args.config)
        logging.info("✅ Config loaded successfully!")
        logging.info(f"Shows: {config['shows']}")
        
        logging.info("🔍 Searching for torrents...")
        for show in config["shows"]:
            query = f"{show} {config['quality']} {config['codec']}"
            results = asyncio.run(search_nyaa(query, allowed_groups=config.get("release_groups")))


            print(f"\nResults for '{query}':")
            for r in results:
                magnet = asyncio.run(extract_magnet(r["link"]))
                print(f"- {r['title']}")
                print(f"  Magnet: {magnet or '⚠️ Not found'}")
                
    except Exception as e:
        logging.error(f"❌ Failed to load config: {e}")
        return

if __name__ == "__main__":
    main()
