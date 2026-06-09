"""
Render the Top 100 Hitter ROS Projections section for the Tamp Slam daily report.

Pulls from the sibling sp-correlation project's outputs:
    Documents/Fantasy Baseball/sp-correlation/output/2026_hitter_projections.csv

Headline metric: fp_g_projection from the Ridge model fed trailing-5-week
form features (not season-to-date), with actuals shown over the same 5-week
window. Rostered hitters highlighted (own team = green, FA = yellow).
Rostered hitters below rank 100 are appended.
"""

from __future__ import annotations

import csv
import unicodedata
from html import escape
from pathlib import Path


SPCORR_DIR = Path(__file__).resolve().parent / "Documents" / "Fantasy Baseball" / "sp-correlation"
PROJ_CSV = SPCORR_DIR / "output" / "2026_hitter_projections.csv"


HITTER_LEADERBOARD_CSS = """
.h-mine td { background: #c8e6c9 !important; }
.h-fa td { background: #fff9c4 !important; }
.h-mine td:nth-child(2), .h-fa td:nth-child(2) { font-weight: 700; }
.h-rank { text-align: right; font-variant-numeric: tabular-nums; }
.h-ros { text-align: right; font-weight: 700; font-variant-numeric: tabular-nums; }
.h-num { text-align: right; font-variant-numeric: tabular-nums; }
.h-delta-up { color: #1976d2; font-weight: 600; }   /* hot — actual > proj */
.h-delta-dn { color: #c62828; font-weight: 600; }   /* cold — actual < proj */
.h-legend { font-size: 12px; color: var(--muted); margin-top: 8px; }
.h-legend .swatch { display: inline-block; width: 12px; height: 12px;
  margin: 0 4px 0 12px; vertical-align: middle; border: 1px solid #ccc; }
"""


_SUFFIXES = {"jr", "sr", "ii", "iii", "iv"}


def _norm(s: str) -> str:
    """ASCII-fold + lowercase + collapse whitespace + strip punctuation."""
    s = "".join(c for c in unicodedata.normalize("NFKD", str(s)) if not unicodedata.combining(c))
    s = s.lower().replace(".", "").replace(",", "")
    return " ".join(s.split())


def _strip_suffix(full: str) -> str:
    parts = _norm(full).split()
    while parts and parts[-1] in _SUFFIXES:
        parts.pop()
    return " ".join(parts)


def _norm_full(name: str) -> str:
    """Suffix-stripped, ASCII-folded full name. Primary match key."""
    return _strip_suffix(name)


def _norm_last(name: str) -> str:
    """Last-name fallback key."""
    parts = _strip_suffix(name).split()
    return parts[-1] if parts else ""


def _to_float(s):
    try:
        return float(s)
    except (TypeError, ValueError):
        return None


def _to_int(s):
    try:
        return int(float(s))
    except (TypeError, ValueError):
        return None


def load_proj_fp_g_index() -> dict[str, float]:
    """Return {normalized_full_name: fp_g_projection} for fast lookup from
    other render sections (e.g., FA hitters table). Falls back to last-name
    when full-name doesn't collide. Returns {} if the CSV is missing."""
    if not PROJ_CSV.exists():
        return {}
    full_index: dict[str, float] = {}
    last_counts: dict[str, int] = {}
    last_index: dict[str, float] = {}
    with PROJ_CSV.open(encoding="utf-8") as f:
        for r in csv.DictReader(f):
            try:
                v = float(r["fp_g_projection"])
            except (KeyError, TypeError, ValueError):
                continue
            full = _norm_full(r["batter_name"])
            last = _norm_last(r["batter_name"])
            full_index[full] = v
            last_counts[last] = last_counts.get(last, 0) + 1
            last_index.setdefault(last, v)  # first occurrence; only used when unique
    # Drop last-name entries that have collisions
    last_unique = {k: v for k, v in last_index.items() if last_counts.get(k, 0) == 1}

    class _Lookup(dict):
        def __init__(self, full, last):
            super().__init__(full)
            self._last = last
        def for_player(self, name: str) -> float | None:
            v = self.get(_norm_full(name))
            if v is not None:
                return v
            return self._last.get(_norm_last(name))

    return _Lookup(full_index, last_unique)


def _load_projections() -> list[dict]:
    if not PROJ_CSV.exists():
        return []
    rows = []
    with PROJ_CSV.open(encoding="utf-8") as f:
        for i, r in enumerate(csv.DictReader(f), start=1):
            rows.append({
                "rank": i,
                "batter_name": r["batter_name"],
                "team": r["team"],
                "position": r.get("position", ""),
                "games_played_2026": _to_int(r.get("games_played_2026")),
                "team_games_played": _to_int(r.get("team_games_played")),
                "games_remaining_est": _to_float(r.get("games_remaining_est")),
                "fp_g_projection": _to_float(r["fp_g_projection"]),
                "avg_fp_actual": _to_float(r.get("avg_fp_actual")),
                "avg_fp_5wk": _to_float(r.get("avg_fp_5wk")),
                "games_5wk": _to_int(r.get("games_5wk")),
                "fp_ros_projection": _to_float(r["fp_ros_projection"]),
                "name_norm": _norm_full(r["batter_name"]),
                "last_norm": _norm_last(r["batter_name"]),
            })
    return rows


def render_hitter_leaderboard_section(my_hitters: list[dict], fa_hitters: list[dict]) -> str:
    """Build the HTML for the Top 100 Hitter ROS section."""
    proj = _load_projections()
    if not proj:
        return (
            "<p class='dim'>Hitter projection data not found. "
            f"Run <code>python -m src.project_hitter --all</code> in "
            f"<code>{escape(str(SPCORR_DIR))}</code> to generate it.</p>"
        )

    # Role maps from daily-report snapshot. Match by full normalized name only
    # — last-name fallback is unsafe because a player rostered on another team
    # and an FA may share a last name (e.g., Julio Rodríguez rostered,
    # Jesus Rodriguez on the FA wire). Mis-labeling a rostered star as FA is
    # worse than failing to color-code a player whose name spelling drifted.
    my_full = {_norm_full(p["name"]) for p in (my_hitters or [])}
    fa_full = {_norm_full(p["name"]) for p in (fa_hitters or [])}

    def role(row):
        if row["name_norm"] in my_full:
            return "mine"
        if row["name_norm"] in fa_full:
            return "fa"
        return "other"

    for r in proj:
        r["role"] = role(r)

    top100 = proj[:100]
    extras = [r for r in proj[100:] if r["role"] == "mine"]
    rows = top100 + extras

    body = []
    for r in rows:
        cls = ""
        label = ""
        if r["role"] == "mine":
            cls = "h-mine"
            label = "★ MINE"
        elif r["role"] == "fa":
            cls = "h-fa"
            label = "FA"

        actual = r["avg_fp_5wk"]
        proj_g = r["fp_g_projection"]
        if actual is not None and proj_g is not None:
            actual_s = f'{actual:.2f}'
            delta = actual - proj_g
            sign = "+" if delta >= 0 else "-"
            d_class = "h-delta-up" if delta >= 0 else "h-delta-dn"
            delta_html = f'<span class="{d_class}">{sign}{abs(delta):.2f}</span>'
        else:
            actual_s = '<span class="dim">—</span>'
            delta_html = '<span class="dim">—</span>'

        g_played = r["games_5wk"] if r["games_5wk"] is not None else "—"
        proj_g_s = f'{proj_g:.2f}' if proj_g is not None else "—"

        body.append(
            f'<tr class="{cls}">'
            f'<td class="h-rank">{r["rank"]}</td>'
            f'<td>{escape(r["batter_name"])}</td>'
            f'<td>{escape(r["team"])}</td>'
            f'<td>{escape(r["position"])}</td>'
            f'<td class="h-num">{g_played}</td>'
            f'<td class="h-ros">{proj_g_s}</td>'
            f'<td class="h-num">{actual_s}</td>'
            f'<td class="h-num">{delta_html}</td>'
            f'<td>{label}</td>'
            f'</tr>'
        )

    # Footnote: rostered hitters missing from projection dataset (insufficient games)
    proj_full = {r["name_norm"] for r in proj}
    not_in_dataset = []
    for p in (my_hitters or []):
        if _norm_full(p["name"]) not in proj_full:
            stat = p.get("status", "")
            tag = f" [{stat}]" if stat else ""
            not_in_dataset.append(f"{escape(p['name'])}{tag}")
    not_in_html = ""
    if not_in_dataset:
        not_in_html = (
            f"<p class='dim h-legend' style='margin-top:10px;'>"
            f"<b>My rostered hitters not in projection dataset</b> "
            f"(need ≥5 games in the last 5 weeks or on IL): {', '.join(not_in_dataset)}</p>"
        )

    legend = (
        "<p class='h-legend'>"
        "<span class='swatch' style='background:#c8e6c9;'></span> my roster"
        "<span class='swatch' style='background:#fff9c4;'></span> free agent"
        "<span class='swatch' style='background:transparent;'></span> rostered by another team"
        "</p>"
    )

    return (
        "<p class='dim'>Ranked by projected Yahoo FP per game from "
        "<b>trailing-5-week form</b> — both the model features and the actuals "
        "below cover only the last 35 days, so hot/cold streaks and role changes "
        "show up instead of being diluted by April. Model: Ridge trained on "
        "2024+2025 trailing-5-week Statcast skill features. "
        f"Source: <code>sp-correlation/output/2026_hitter_projections.csv</code>. "
        f"Shows top 100 plus {len(extras)} rostered hitter{'s' if len(extras) != 1 else ''} below rank 100.</p>"
        "<p class='h-legend'>Click any column header to sort. "
        "<span class='h-delta-up'>Δ blue</span> = hot (actual &gt; projected, possible sell). "
        "<span class='h-delta-dn'>Δ red</span> = cold (actual &lt; projected, possible buy).</p>"
        "<table class='sortable'>"
        "<thead><tr><th>Rank</th><th>Hitter</th><th>Team</th><th>Pos</th>"
        "<th>G (5wk)</th>"
        "<th>Proj FP/G</th>"
        "<th>FP/G (5wk)</th>"
        "<th>Δ (5wk − Proj)</th>"
        "<th>Owned</th></tr></thead>"
        f"<tbody>{''.join(body)}</tbody></table>"
        f"{legend}{not_in_html}"
    )
