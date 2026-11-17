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
from torrent_automator.nyaa import (
    fetch_nyaa_rss, extract_magnet, score_result, in_groups, release_group,
)
from torrent_automator.qbittorrent import QBitClient
from torrent_automator.anilist import fetch_anilist_progress
from torrent_automator.plan import (
    DownloadPlan, ShowPlan, PlannedTorrent, format_plan, unique,
    STATUS_READY, STATUS_GROUPS_UNAVAILABLE, STATUS_NO_NEW, STATUS_NO_RESULTS,
    STATUS_NOT_WATCHING, STATUS_ERROR,
)


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


def normalize_group_name(group: str) -> str:
    g = (group or "").strip()
    if g.lower() in ("any", "(any)"):
        return ""
    if g.startswith("[") and g.endswith("]"):
        g = g[1:-1].strip()
    return g


def similarity(a: str, b: str) -> float:
    return SequenceMatcher(None, a, b).ratio()


# ------------------------------
# Nyaa search helpers
# ------------------------------

def _safe_query_tokens(show: str, quality: str, codec: str) -> list[str]:
    base = normalize_show_name(show)
    def join_parts(*parts: str) -> str:
        return " ".join(p for p in parts if p).strip()

    tokens = [join_parts(base, quality, codec)]
    padded = f" {base} "
    if " season " in padded:
        # split the padded name so titles that start/end with "season" (e.g. "Aoashi 2nd Season") work
        head, tail = padded.split(" season ", 1)
        tokens.append(join_parts(padded.replace(" season ", " s ").strip(), quality, codec))
        if tail.strip().isdigit():
            n = tail.strip()
            tokens.append(join_parts(head.strip(), "s", n, quality, codec))
            tokens.append(join_parts(head.strip(), n, quality, codec))
    else:
        tokens.append(join_parts(base, quality))
    seen, out = set(), []
    for q in tokens:
        if q and q not in seen:
            seen.add(q)
            out.append(q)
    return out


def _recent_query(show: str, quality: str, codec: str) -> str:
    parts = [show]
    if quality:
        parts.append(quality)
    if codec:
        parts.append(codec)
    return " ".join(p.strip() for p in parts if p and p.strip())


async def search_with_variants_raw(show: str, config: dict) -> list[dict]:
    """Run every query variant for a show and return all unique results (any group)."""
    queries = _safe_query_tokens(show, config.get("quality") or "", config.get("codec") or "")
    seen_titles = set()
    results = []
    for q in queries:
        for item in await fetch_nyaa_rss(q):
            t = item["title"]
            if t not in seen_titles:
                seen_titles.add(t)
                results.append(item)
    return results


async def search_with_variants(show: str, config: dict):
    _, groups = effective_groups(config)
    return [r for r in await search_with_variants_raw(show, config) if in_groups(r["title"], groups)]


def effective_groups(config: dict) -> tuple[str, list[str]]:
    """
    Resolve which release groups the batch run should accept.
    Returns (mode, groups) with mode "single", "priority" or "any".
    A preferred_group (GUI "single group" mode) takes precedence over release_groups.
    """
    preferred = normalize_group_name(config.get("preferred_group") or "")
    if preferred:
        return "single", [preferred]
    groups = [normalize_group_name(g) for g in (config.get("release_groups") or [])]
    groups = [g for g in groups if g]
    if groups:
        return "priority", groups
    return "any", []


def _episode_int(ep_s: str | None) -> int | None:
    if not ep_s:
        return None
    try:
        return int(re.sub(r"v\d", "", ep_s))
    except Exception:
        return None


# ------------------------------
# Main flow: plan -> confirm -> execute
# ------------------------------

LogFn = Callable[[str], None] | None


def _emitter(log_cb: LogFn):
    def emit(message: str):
        if log_cb:
            log_cb(message)
        else:
            print(message)
    return emit


def match_anilist_title(show: str, anilist: dict) -> str | None:
    norm_show = normalize_show_name(show)
    matched_title = None
    best = 0.0
    for ani_title in anilist:
        score = similarity(norm_show, ani_title)
        if score > best and score > 0.6:
            matched_title = ani_title
            best = score
    return matched_title


async def build_batch_plan(config: dict, log_cb: LogFn = None, anilist: dict | None = None) -> DownloadPlan:
    """
    Work out which new episodes would be downloaded for the configured shows,
    without contacting qBittorrent. Nothing is downloaded here.
    """
    emit = _emitter(log_cb)
    group_mode, groups = effective_groups(config)
    plan = DownloadPlan(
        kind="batch",
        quality=config.get("quality") or "",
        codec=config.get("codec") or "",
        group_mode=group_mode,
        groups=groups,
    )

    if anilist is None:
        anilist = {}
        username = (config.get("anilist_username") or "").strip()
        if username:
            logging.info("🔗 Fetching AniList 'Watching' list...")
            anilist = await fetch_anilist_progress(username)
            emit("📺 AniList Watching List:")
            for title, info in anilist.items():
                emit(f"  {title} → Ep {info['progress']}")
        else:
            emit("⚠️ No AniList username set: batch automation needs your Watching list.")

    for show in config.get("shows") or []:
        sp = ShowPlan(show=show)
        plan.shows.append(sp)

        matched_title = match_anilist_title(show, anilist)
        if not matched_title:
            sp.status = STATUS_NOT_WATCHING
            sp.message = "Not found on your AniList Watching list, skipped."
            emit(f"⏭️ '{show}' not found in AniList 'Watching', skipping.")
            continue

        info = anilist[matched_title]
        prog = int(info.get("progress") or 0)
        season_total = info.get("episodes")
        current_season = extract_season_number(matched_title) or 1  # assume 1 if missing
        sp.matched_title = info.get("title") or matched_title
        sp.progress = prog
        sp.total_episodes = season_total
        sp.cover = info.get("cover") or ""
        sp.color = info.get("color") or ""

        emit(f"\n📺 {matched_title}: Last watched episode {prog}")

        try:
            raw = await search_with_variants_raw(show, config)
        except Exception as e:
            sp.status = STATUS_ERROR
            sp.message = f"Search failed: {e}"
            emit(f"❌ Search failed for {show}: {e}")
            continue
        sp.groups_found = unique(r["group"] for r in raw)

        # Bucket every newer episode (from any group) by (season, episode)
        buckets: dict[tuple[int, int], list[dict]] = {}
        ep_labels: dict[tuple[int, int], str] = {}
        for r in raw:
            ep_s = extract_episode_number(r["title"])
            ep = _episode_int(ep_s)
            if ep is None:
                continue
            sn = extract_season_number(r["title"]) or current_season
            if current_season and sn != current_season:
                continue
            if season_total is not None and ep > season_total:
                continue
            if ep <= prog:
                continue
            key = (sn, ep)
            buckets.setdefault(key, []).append(r)
            ep_labels.setdefault(key, ep_s)

        if not buckets:
            sp.status = STATUS_NO_NEW if raw else STATUS_NO_RESULTS
            sp.message = "No new episodes found." if raw else "No releases found on Nyaa."
            emit(f"⏭️ No new episodes for {show}")
            continue

        for key in sorted(buckets):
            candidates = buckets[key]
            allowed = [r for r in candidates if in_groups(r["title"], groups)]
            available = unique(r["group"] for r in candidates)
            if allowed:
                best = min(allowed, key=lambda r: score_result(r["title"], groups)) if groups else allowed[0]
                ok = True
            else:
                best = candidates[0]
                ok = False
            sp.items.append(PlannedTorrent(
                show=show,
                title=best["title"],
                link=best["link"],
                group=best.get("group") or release_group(best["title"]),
                episode=ep_labels[key],
                season=key[0],
                in_selected_groups=ok,
                selected=ok,
                available_groups=available,
            ))

        n_ok = sum(1 for it in sp.items if it.in_selected_groups)
        n_other = len(sp.items) - n_ok
        if n_ok:
            sp.status = STATUS_READY
            sp.message = f"{n_ok} new episode(s) ready."
        else:
            sp.status = STATUS_GROUPS_UNAVAILABLE
            sp.message = "New episodes exist, but not from your selected group(s)."
        if n_ok and n_other:
            sp.message += f" {n_other} more only available from other groups."

    return plan


async def build_recent_plan(
    config: dict,
    show: str | list[str] | None = None,
    group: str | None = None,
    count: int | None = None,
    log_cb: LogFn = None,
    quality: str | None = None,
    codec: str | None = None,
    episode: str | None = None,
) -> DownloadPlan:
    """Collect the latest releases for the selected shows. Nothing is downloaded here."""
    emit = _emitter(log_cb)

    show_list = _split_shows(show)
    if not show_list:
        show_list = _split_shows(config.get("recent_shows")) or _split_shows(config.get("recent_show"))

    group = normalize_group_name(group or config.get("recent_group") or config.get("preferred_group") or "")
    count = int(count or config.get("recent_count") or 5)

    recent_quality = (config.get("recent_quality") or "").strip()
    recent_codec = (config.get("recent_codec") or "").strip()
    if recent_quality == "__any__":
        quality = ""
    else:
        quality = (quality or recent_quality or config.get("quality") or "").strip()
    if recent_codec == "__any__":
        codec = ""
    else:
        codec = (codec or recent_codec or config.get("codec") or "").strip()
    episode_filter = _normalize_episode_input(episode or config.get("recent_episode"))

    plan = DownloadPlan(
        kind="recent",
        quality=quality,
        codec=codec,
        group_mode="single" if group else "any",
        groups=[group] if group else [],
        count=count,
        episode_filter=episode_filter,
    )

    if not show_list:
        plan.error = "Missing recent show(s). Set recent_shows in config or pass CLI args."
        emit(plan.error)
        return plan

    allowed_groups = [group] if group else None
    for show_name in show_list:
        sp = ShowPlan(show=show_name)
        plan.shows.append(sp)
        query = _recent_query(show_name, quality, codec)
        label = f"[{group}] " if group else ""
        emit(f"Fetching last {count} releases for {label}{show_name}...")
        try:
            raw = await fetch_nyaa_rss(query)
        except Exception as e:
            sp.status = STATUS_ERROR
            sp.message = f"Search failed: {e}"
            emit(f"Search failed for {show_name}: {e}")
            continue
        sp.groups_found = unique(r["group"] for r in raw)

        results = [r for r in raw if in_groups(r["title"], allowed_groups)][:count]
        if episode_filter:
            results = [r for r in results if extract_episode_number(r["title"]) == episode_filter]

        if not results:
            if group and sp.groups_found:
                sp.status = STATUS_GROUPS_UNAVAILABLE
                sp.message = f"No recent releases from [{group}]."
            else:
                sp.status = STATUS_NO_RESULTS
                sp.message = "No recent releases found."
            emit(f"No recent releases found for {show_name}.")
            continue

        sp.status = STATUS_READY
        sp.message = f"{len(results)} release(s) found."
        for r in results:
            ep_s = extract_episode_number(r["title"])
            same_ep = [x for x in raw if ep_s and extract_episode_number(x["title"]) == ep_s]
            sp.items.append(PlannedTorrent(
                show=show_name,
                title=r["title"],
                link=r["link"],
                group=r.get("group") or release_group(r["title"]),
                episode=ep_s,
                season=extract_season_number(r["title"]),
                in_selected_groups=True,
                selected=True,
                available_groups=unique(x["group"] for x in same_ep),
            ))

    return plan


def _make_qb(config: dict) -> QBitClient:
    qbc = config["qbittorrent"]
    return QBitClient(
        host=qbc["host"],
        port=qbc["port"],
        username=qbc["username"],
        password=qbc["password"],
        use_https=qbc.get("https", False),
    )


async def execute_plan_items(
    items: list[PlannedTorrent],
    config: dict,
    log_cb: LogFn = None,
    qb_client: QBitClient | None = None,
) -> dict:
    """Resolve magnets and send the confirmed items to qBittorrent."""
    emit = _emitter(log_cb)
    summary = {"sent": 0, "failed": 0}
    if not items:
        emit("Nothing to send.")
        return summary

    qb = qb_client
    try:
        if qb is None:
            qb = _make_qb(config)
        qb.login()
    except Exception as e:
        emit(f"❌ Could not connect to qBittorrent: {e}")
        summary["failed"] = len(items)
        return summary

    for it in items:
        magnet = await extract_magnet(it.link)
        if not magnet:
            emit(f"⚠️ Magnet not found for {it.title}")
            summary["failed"] += 1
            continue
        try:
            qb.add_magnet(magnet)
            emit(f"✅ Sent [{it.group or '?'}] {it.title} to qBittorrent")
            summary["sent"] += 1
        except Exception as e:
            emit(f"❌ Failed to add {it.title}: {e}")
            summary["failed"] += 1

    emit(f"Done: {summary['sent']} sent, {summary['failed']} failed.")
    return summary


def confirm_plan_cli(plan: DownloadPlan, input_fn: Callable[[str], str] | None = None) -> list[PlannedTorrent]:
    """Ask the user on the terminal which planned torrents to send."""
    input_fn = input_fn or input
    candidates = plan.selected_items()
    if not plan.items:
        return []
    if candidates:
        prompt = f"\nSend {len(candidates)} torrent(s) to qBittorrent? [y]es / [n]o / [s]elect individually: "
    else:
        prompt = "\nNo releases from your selected group(s). [s]elect individually / [n]o: "
    choice = input_fn(prompt).strip().lower()
    if choice in ("y", "yes"):
        return candidates
    if choice in ("s", "select"):
        chosen = []
        for it in plan.items:
            default = "Y/n" if it.selected else "y/N"
            ans = input_fn(f"  Ep {it.episode or '?'} [{it.group or '?'}] {it.title}  [{default}]: ").strip().lower()
            if ans in ("y", "yes") or (ans == "" and it.selected):
                chosen.append(it)
        return chosen
    return []


async def _confirm_and_execute(plan: DownloadPlan, config: dict, non_interactive: bool, emit) -> DownloadPlan:
    for line in format_plan(plan):
        emit(line)
    if not plan.items:
        emit("Nothing to download.")
        return plan
    chosen = plan.selected_items() if non_interactive else confirm_plan_cli(plan)
    if not chosen:
        emit("⏭️ Nothing confirmed, no torrents sent.")
        return plan
    await execute_plan_items(chosen, config, log_cb=emit)
    return plan


async def run_automation(config: dict, non_interactive: bool = False, log_cb: LogFn = None):
    emit = _emitter(log_cb)
    try:
        logging.info("✅ Config loaded successfully!")
        logging.info(f"Shows from config: {config.get('shows')}")
        plan = await build_batch_plan(config, log_cb=log_cb)
        return await _confirm_and_execute(plan, config, non_interactive, emit)
    except Exception as e:
        logging.error(f"❌ Failed: {e}")


def _split_shows(value) -> list[str]:
    if not value:
        return []
    if isinstance(value, (list, tuple)):
        out = []
        for v in value:
            out.extend(_split_shows(v))
        return out
    if isinstance(value, str):
        parts = [v.strip() for v in value.split(",")]
        return [p for p in parts if p]
    return []


def _normalize_episode_input(value: str | None) -> str | None:
    if not value:
        return None
    v = value.strip()
    if not v:
        return None
    if v.isdigit():
        return v.zfill(2)
    return v


async def run_recent_fetch(
    config: dict,
    show: str | list[str] | None = None,
    group: str | None = None,
    count: int | None = None,
    non_interactive: bool = False,
    log_cb: LogFn = None,
    quality: str | None = None,
    codec: str | None = None,
    episode: str | None = None,
):
    emit = _emitter(log_cb)
    try:
        plan = await build_recent_plan(
            config, show=show, group=group, count=count, log_cb=log_cb,
            quality=quality, codec=codec, episode=episode,
        )
        if plan.error:
            return plan
        return await _confirm_and_execute(plan, config, non_interactive, emit)
    except Exception as e:
        logging.error(f"Recent fetch failed: {e}")


def main():
    parser = argparse.ArgumentParser(description="Torrent Automator Tool")
    parser.add_argument("--config", type=str, required=True)
    parser.add_argument("--non-interactive", action="store_true")
    parser.add_argument("--recent", action="store_true", help="Fetch last N releases for a show and group")
    parser.add_argument("--recent-show", action="append", help="Show name for recent fetch (repeatable)")
    parser.add_argument("--recent-group", type=str, help="Release group name for recent fetch")
    parser.add_argument("--recent-count", type=int, help="Number of recent releases to fetch")
    parser.add_argument("--recent-quality", type=str, help="Quality override for recent fetch")
    parser.add_argument("--recent-codec", type=str, help="Codec override for recent fetch")
    parser.add_argument("--recent-episode", type=str, help="Episode number filter for recent fetch")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO)
    config = load_config(args.config)
    if args.recent:
        asyncio.run(run_recent_fetch(
            config=config,
            show=args.recent_show,
            group=args.recent_group,
            count=args.recent_count,
            non_interactive=args.non_interactive,
            quality=args.recent_quality,
            codec=args.recent_codec,
            episode=args.recent_episode,
        ))
    else:
        asyncio.run(run_automation(config, non_interactive=args.non_interactive))


if __name__ == "__main__":
    main()
