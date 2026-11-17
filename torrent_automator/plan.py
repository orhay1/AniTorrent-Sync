"""
Data structures describing *what would be downloaded* before anything is sent
to qBittorrent. Both the CLI and the GUI build a DownloadPlan first, show it to
the user for confirmation, and only then execute the confirmed items.
"""
from __future__ import annotations

from dataclasses import dataclass, field

# ShowPlan.status values
STATUS_READY = "ready"                    # at least one release from an allowed group
STATUS_GROUPS_UNAVAILABLE = "groups_unavailable"  # releases exist, but not from the selected group(s)
STATUS_NO_NEW = "no_new"                  # nothing newer than AniList progress
STATUS_NO_RESULTS = "no_results"          # nyaa returned nothing usable
STATUS_NOT_WATCHING = "not_watching"      # show not on the AniList Watching list
STATUS_ERROR = "error"                    # search failed


@dataclass
class PlannedTorrent:
    show: str
    title: str
    link: str
    group: str = ""
    episode: str | None = None
    season: int | None = None
    # Whether the release comes from one of the selected/allowed groups.
    in_selected_groups: bool = True
    # Pre-ticked in the confirmation step (releases outside the selected
    # groups are listed but not pre-ticked).
    selected: bool = True
    # Every group that has a release for this same episode in the search results.
    available_groups: list[str] = field(default_factory=list)


@dataclass
class ShowPlan:
    show: str
    status: str = STATUS_NO_RESULTS
    message: str = ""
    matched_title: str | None = None
    progress: int | None = None
    total_episodes: int | None = None
    cover: str = ""
    color: str = ""
    # Every release group seen in the raw search results for this show.
    groups_found: list[str] = field(default_factory=list)
    items: list[PlannedTorrent] = field(default_factory=list)


@dataclass
class DownloadPlan:
    kind: str  # "batch" | "recent"
    quality: str = ""
    codec: str = ""
    group_mode: str = "any"  # "single" | "priority" | "any"
    groups: list[str] = field(default_factory=list)
    count: int | None = None
    episode_filter: str | None = None
    shows: list[ShowPlan] = field(default_factory=list)
    error: str = ""

    @property
    def items(self) -> list[PlannedTorrent]:
        return [it for sp in self.shows for it in sp.items]

    def selected_items(self) -> list[PlannedTorrent]:
        return [it for it in self.items if it.selected]


def unique(seq) -> list[str]:
    seen, out = set(), []
    for s in seq:
        if s and s.lower() not in seen:
            seen.add(s.lower())
            out.append(s)
    return out


def describe_groups(plan: DownloadPlan) -> str:
    if plan.group_mode == "single" and plan.groups:
        return f"Single group: {plan.groups[0]}"
    if plan.group_mode == "priority" and plan.groups:
        return "Priority: " + " > ".join(plan.groups)
    return "Any group"


def format_plan(plan: DownloadPlan) -> list[str]:
    """Human readable summary used by the CLI and the GUI log."""
    lines: list[str] = []
    title = "Batch automation" if plan.kind == "batch" else "Recent releases"
    lines.append(f"===== Download plan: {title} =====")
    lines.append(f"Quality: {plan.quality or 'Any'} | Codec: {plan.codec or 'Any'} | {describe_groups(plan)}")
    if plan.kind == "recent":
        extra = f"Count per show: {plan.count}"
        if plan.episode_filter:
            extra += f" | Episode: {plan.episode_filter}"
        lines.append(extra)
    for sp in plan.shows:
        head = f"- {sp.show}"
        if sp.progress is not None:
            total = sp.total_episodes if sp.total_episodes is not None else "?"
            head += f" (watched {sp.progress}/{total})"
        lines.append(head)
        if sp.message:
            lines.append(f"    {sp.message}")
        if sp.groups_found:
            lines.append(f"    Groups found: {', '.join(sp.groups_found)}")
        for it in sp.items:
            mark = "[x]" if it.selected else "[ ]"
            ep = f"Ep {it.episode}" if it.episode else "Ep ?"
            note = "" if it.in_selected_groups else "  (not in selected groups)"
            lines.append(f"    {mark} {ep}: {it.title}{note}")
    selected = plan.selected_items()
    lines.append(f"Total: {len(selected)} torrent(s) selected of {len(plan.items)} found")
    return lines
