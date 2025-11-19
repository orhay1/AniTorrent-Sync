#!/usr/bin/env python3
import sys
from pathlib import Path
sys.path.append(str(Path(__file__).parent))

import argparse
import logging
import asyncio
import re
from difflib import SequenceMatcher
from typing import Callable

from torrent_automator.config import load_config
from torrent_automator.nyaa import search_nyaa, extract_magnet, score_result
from torrent_automator.qbittorrent import QBitClient
from torrent_automator.anilist import fetch_anilist_progress


# ------------------------------
# Parsing helpers
# ------------------------------

def extract_episode_number(title: str) -> str | None:
    clean = (
        title.replace("×", "x")
             .replace("–", "-")
             .replace("—", "-")
             .replace("_", " ")
    )
    patterns = [
        r"[Ss](\d{1,2})[Ee](\d{1,3}(?:v\d)?)",
        r"[Ss]eason\s*\d{1,2}\s*[- ]\s*(\d{1,3}(?:v\d)?)",
        r"[Ee]pisode\s*(\d{1,3}(?:v\d)?)",
        r"[- ](\d{1,3}(?:v\d)?)",
    ]
    for pat in patterns:
        m = re.search(pat, clean)
        if m:
            ep = m.group(2) if len(m.groups()) >= 2 else m.group(1)
            if ep in ("720", "1080", "2160"):
                continue
            return ep.zfill(2)
    return None


def extract_season_number(title: str) -> int | None:
    m = re.search(r"[Ss](\d{1,2})", title) or re.search(r"[Ss]eason\s*(\d{1,2})", title)
    return int(m.group(1)) if m else None


def normalize_show_name(name: str) -> str:
    s = name
    s = s.replace("×", "x").replace("–", "-").replace("—", "-")
    s = re.sub(r"[^\w\s-]", " ", s)
    s = re.sub(r"\s+", " ", s)
    s = s.strip().lower()
    s = re.sub(r"[^a-z0-9\s-]", "", s)
    s = re.sub(r"[-\s]+", " ", s)
    return s


def similarity(a: str, b: str) -> float:
    return SequenceMatcher(None, a, b).ratio()


# ------------------------------
# Nyaa search helpers
# ------------------------------

def _safe_query_tokens(show: str, quality: str, codec: str) -> list[str]:
    base = normalize_show_name(show)
    tokens = [f"{base} {quality} {codec}"]
    if " season " in f" {base} ":
        head, tail = base.split(" season ", 1)
        tokens.append(f"{base.replace(' season ', ' s ')} {quality} {codec}")
        if tail.strip().isdigit():
            n = tail.strip()
            tokens.append(f"{head.strip()} s {n} {quality} {codec}")
            tokens.append(f"{head.strip()} {n} {quality} {codec}")
    else:
        tokens.append(f"{base} {quality}")
    seen, out = set(), []
    for q in tokens:
        if q not in seen:
            seen.add(q)
            out.append(q)
    return out


async def search_with_variants(show: str, config: dict):
    queries = _safe_query_tokens(show, config["quality"], config["codec"])
    seen_titles = set()
    results = []
    for q in queries:
        r = await search_nyaa(q, allowed_groups=config.get("release_groups"))
        for item in r:
            t = item["title"]
            if t not in seen_titles:
                seen_titles.add(t)
                results.append(item)
    return results


# ------------------------------
# Deduplication by episode
# ------------------------------

def pick_best_per_episode(results: list[dict], groups: list[str], current_season: int) -> list[dict]:
    bucket: dict[tuple[int, int], dict] = {}

    for r in results:
        ep_s = extract_episode_number(r["title"])
        if not ep_s:
            continue
        try:
            ep = int(re.sub(r"v\d", "", ep_s))
        except Exception:
            continue

        sn = extract_season_number(r["title"]) or current_season  # ✅ force collapse
        key = (sn, ep)

        if key not in bucket:
            bucket[key] = r
        else:
            cur = bucket[key]
            if groups:
                cur_score = score_result(cur["title"], groups)
                new_score = score_result(r["title"], groups)
                if new_score < cur_score:
                    bucket[key] = r

    ordered = [bucket[k] for k in sorted(bucket.keys(), key=lambda k: (k[0], k[1]))]
    return ordered


# ------------------------------
# Main flow
# ------------------------------

LogFn = Callable[[str], None] | None

async def run_automation(config: dict, non_interactive: bool = False, log_cb: LogFn = None):
    def emit(message: str):
        if log_cb:
            log_cb(message)
        else:
            print(message)

    try:
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

        # AniList fetch
        anilist = {}
        if "anilist_username" in config:
            logging.info("🔗 Fetching AniList 'Watching' list...")
            anilist = await fetch_anilist_progress(config["anilist_username"])
            emit("📺 AniList Watching List:")
            for title, info in anilist.items():
                emit(f"  {title} → Ep {info['progress']}")

        for show in config["shows"]:
            norm_show = normalize_show_name(show)
            matched_title = None
            best = 0.0
            for ani_title in anilist:
                score = similarity(norm_show, ani_title)
                if score > best and score > 0.6:
                    matched_title = ani_title
                    best = score

            if not matched_title:
                emit(f"⏭️ '{show}' not found in AniList 'Watching', skipping.")
                continue

            prog = int(anilist[matched_title]["progress"])
            season_total = anilist[matched_title]["episodes"]
            current_season = extract_season_number(matched_title) or 1  # ✅ assume 1 if missing

            emit(f"\n📺 {matched_title}: Last watched episode {prog}")

            results = await search_with_variants(show, config)

            # Filter results
            filtered = []
            for r in results:
                ep_s = extract_episode_number(r["title"])
                if not ep_s:
                    continue
                try:
                    ep = int(re.sub(r"v\d", "", ep_s))
                except Exception:
                    continue

                sn = extract_season_number(r["title"]) or current_season
                if current_season and sn != current_season:
                    continue
                if season_total is not None and ep > season_total:
                    continue
                if ep > prog:
                    filtered.append(r)

            if not filtered:
                emit(f"⏭️ No new episodes for {show}")
                continue

            groups = config.get("release_groups", []) or []
            best_per_ep = pick_best_per_episode(filtered, groups, current_season)

            for r in best_per_ep:
                magnet = await extract_magnet(r["link"])
                if not magnet:
                    emit(f"⚠️ Magnet not found for {r['title']}")
                    continue

                # 🧠 Log which group was chosen
                grp = re.search(r"^\[(.*?)\]", r["title"])
                grp = grp.group(1) if grp else "Unknown"
                emit(f"✅ Chosen [{grp}] for episode {extract_episode_number(r['title'])}")

                if not non_interactive:
                    emit("\n🔹 Torrent:")
                    emit(f"Title : {r['title']}")
                    emit(f"Magnet: {magnet[:60]}...")
                    choice = input("Add this torrent to qBittorrent? [y/N]: ").strip().lower()
                    if choice not in ("y", "yes"):
                        emit("⏭️ Skipped by user.")
                        continue

                try:
                    qb.add_magnet(magnet)
                    emit(f"✅ Sent {r['title']} to qBittorrent")
                except Exception as e:
                    emit(f"❌ Failed to add {r['title']}: {e}")

    except Exception as e:
        logging.error(f"❌ Failed: {e}")


def main():
    parser = argparse.ArgumentParser(description="Torrent Automator Tool")
    parser.add_argument("--config", type=str, required=True)
    parser.add_argument("--non-interactive", action="store_true")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO)
    config = load_config(args.config)
    asyncio.run(run_automation(config, non_interactive=args.non_interactive))


if __name__ == "__main__":
    main()
