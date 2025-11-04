#!/usr/bin/env python3

"""
Torrent Automator CLI
Finds and enqueues torrent releases for configured shows and adds them to qBittorrent.
"""

import asyncio
import argparse
import logging
from pathlib import Path

from torrent_automator.config import load_config
from torrent_automator.core import process_shows
from torrent_automator.qbittorrent import QBitClient
from torrent_automator.report import print_summary


def parse_args():
    parser = argparse.ArgumentParser(
        description="Find and enqueue authorized torrents for your shows"
    )
    parser.add_argument(
        "--config",
        type=Path,
        required=True,
        help="Path to YAML/JSON config file"
    )
    parser.add_argument("--dry-run", action="store_true", help="Run without enqueuing torrents")
    parser.add_argument("--non-interactive", action="store_true", help="Auto-accept top match")
    parser.add_argument("--verbose", action="store_true", help="Enable verbose logging")
    parser.add_argument("--legal-only", action="store_true", help="Reject unclear licensing releases")
    return parser.parse_args()


def setup_logging(verbose: bool):
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="[%(asctime)s] %(levelname)s - %(message)s",
        handlers=[
            logging.FileHandler("torrent_automator.log"),
            logging.StreamHandler()
        ]
    )


async def main():
    args = parse_args()
    setup_logging(args.verbose)

    config = load_config(args.config)

    qb_client = QBitClient(
        host=config.qbittorrent.host,
        port=config.qbittorrent.port,
        username=config.qbittorrent.username,
        password=config.qbittorrent.password,
        use_https=config.qbittorrent.https
    )

    summary = await process_shows(
        config=config,
        qb_client=qb_client,
        dry_run=args.dry_run,
        interactive=not args.non_interactive,
        legal_only=args.legal_only
    )

    print_summary(summary)


if __name__ == "__main__":
    asyncio.run(main())
