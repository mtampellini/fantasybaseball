"""
Render the Top 50 SP Projections section for the Tamp Slam daily report.

Pulls from the sibling sp-correlation project's outputs:
    Documents/Fantasy Baseball/sp-correlation/output/2026_pitcher_projections.csv
    Documents/Fantasy Baseball/sp-correlation/data/rosters.json

Rostered SPs are highlighted (own team = green, FA = yellow). Rostered SPs
below rank 50 are appended.
"""

from __future__ import annotations

import json
import unicodedata
from html import escape
from pathlib import Path

import csv


# Compute path relative to this file so it works on both local Windows
# (C:\Users\mtamp\) and the GitHub Actions Linux runner.
SPCORR_DIR = Path(__file__).resolve().parent / "Documents" / "Fantasy Baseball" / "sp-correlation"
PROJ_CSV = SPCORR_DIR / "output" / "2026_pitcher_projections.csv"
ROSTERS_JSON = SPCORR_DIR / "data" / "rosters.json"
MY_TEAM_ID = 11


SP_LEADERBOARD_CSS = """
.sp-mine td { background: #c8e6c9 !important; }
.sp-fa td { background: #fff9c4 !important; }
.sp-mine td:nth-child(2), .sp-fa td:nth-child(2) { font-weight: 700; }
.sp-rank { text-align: right; font-variant-numeric: tabular-nums; }
.sp-proj { text-align: right; font-weight: 600; font-variant-numeric: tabular-nums; }
.sp-legend { font-size: 12px; color: var(--muted); margin-top: 8px; }
.sp-legend .swatch { display: inline-block; width: 12px; height: 12px;
  margin: 0 4px 0 12px; vertical-align: middle; border: 1px solid #ccc; }
"""


def _norm_last(name: str) -> str:
    s = str(name).split(",", 1)[0].strip().lower()
    return "".join(c for c in unicodedata.normalize("NFKD", s) if not unicodedata.combining(c))


def _last_of_full(full: str) -> str:
    return _norm_last(full.rsplit(" ", 1)[-1])


def _load_projections() -> list[dict]:
    if not PROJ_CSV.exists():
        return []
    rows = []
    with PROJ_CSV.open(encoding="utf-8") as f:
        for i, r in enumerate(csv.DictReader(f), start=1):
            avg_actual = r.get("avg_fp_actual", "")
            n_actual = r.get("n_starts_actual", "")
            rows.append({
                "rank": i,
                "pitcher_name": r["pitcher_name"],
                "team": r["team"],
                "n_starts_prior": int(float(r.get("n_starts_prior", 0))),
                "fp_projection": float(r["fp_projection"]),
                "avg_fp_actual": float(avg_actual) if avg_actual not in ("", "nan") else None,
                "n_starts_actual": int(float(n_actual)) if n_actual not in ("", "nan") else None,
                "last_norm": _norm_last(r["pitcher_name"]),
            })
    return rows


def _load_role_map() -> tuple[dict[str, str], list[str]]:
    """Return ({last_norm: 'mine'|'fa'}, [unmatched_my_sp_names])."""
    if not ROSTERS_JSON.exists():
        return {}, []
    data = json.loads(ROSTERS_JSON.read_text(encoding="utf-8"))["teams"]
    my_names, fa_names = [], []
    for tid, info in data.items():
        for p in info["players"]:
            if "SP" not in (p.get("eligible_positions") or []):
                continue
            if int(tid) == MY_TEAM_ID:
                my_names.append(p["name"])
    # FA SPs come from the daily-report's own snapshot, not rosters.json.
    return my_names, fa_names


def render_sp_leaderboard_section(my_pitchers: list[dict], fa_pitchers: list[dict]) -> str:
    """Build the HTML for the Top 50 SP section.

    my_pitchers / fa_pitchers come from the daily report's own snapshot (already
    in scope when render_report calls us) — that's our source of truth for
    'is this an FA right now?' since the sp-correlation rosters.json may be a
    few hours stale relative to the daily Yahoo pull.
    """
    proj = _load_projections()
    if not proj:
        return (
            "<p class='dim'>SP projection data not found. "
            f"Run <code>python -m src.refresh</code> in <code>{escape(str(SPCORR_DIR))}</code> "
            "to generate it.</p>"
        )

    # Build role maps from the live daily-report snapshot data
    my_last = {_last_of_full(p["name"]) for p in (my_pitchers or [])
               if "SP" in (p.get("eligible_positions") or [])}
    fa_last = {_last_of_full(p["name"]) for p in (fa_pitchers or [])
               if "SP" in (p.get("eligible_positions") or [])}

    def role(row):
        if row["last_norm"] in my_last:
            return "mine"
        if row["last_norm"] in fa_last:
            return "fa"
        return "other"

    for r in proj:
        r["role"] = role(r)

    top50 = proj[:50]
    # Include any rostered (mine) SPs below 50
    extras = [r for r in proj[50:] if r["role"] == "mine"]
    rows = top50 + extras

    # Build the table
    body = []
    for r in rows:
        cls = ""
        label = ""
        if r["role"] == "mine":
            cls = "sp-mine"
            label = "★ MINE"
        elif r["role"] == "fa":
            cls = "sp-fa"
            label = "FA"
        avg = (
            f'{r["avg_fp_actual"]:.2f}' if r["avg_fp_actual"] is not None
            else '<span class="dim">—</span>'
        )
        n_act = r["n_starts_actual"] if r["n_starts_actual"] is not None else "—"
        body.append(
            f'<tr class="{cls}">'
            f'<td class="sp-rank">{r["rank"]}</td>'
            f'<td>{escape(r["pitcher_name"])}</td>'
            f'<td>{escape(r["team"])}</td>'
            f'<td class="sp-rank">{r["n_starts_prior"]}</td>'
            f'<td class="sp-proj">{r["fp_projection"]:.2f}</td>'
            f'<td class="sp-rank">{avg}</td>'
            f'<td class="sp-rank">{n_act}</td>'
            f'<td>{label}</td>'
            f'</tr>'
        )

    # Count rostered SPs not in projection dataset (for footnote)
    proj_lasts = {r["last_norm"] for r in proj}
    not_in_dataset = []
    for p in (my_pitchers or []):
        if "SP" not in (p.get("eligible_positions") or []):
            continue
        if _last_of_full(p["name"]) not in proj_lasts:
            stat = p.get("status", "")
            tag = f" [{stat}]" if stat else ""
            not_in_dataset.append(f"{escape(p['name'])}{tag}")
    not_in_html = ""
    if not_in_dataset:
        not_in_html = (
            f"<p class='dim sp-legend' style='margin-top:10px;'>"
            f"<b>My rostered SPs not in projection dataset</b> "
            f"(need ≥4 starts in 2026 or on IL): {', '.join(not_in_dataset)}</p>"
        )

    legend = (
        "<p class='sp-legend'>"
        "<span class='swatch' style='background:#c8e6c9;'></span> my roster"
        "<span class='swatch' style='background:#fff9c4;'></span> free agent"
        "<span class='swatch' style='background:transparent;'></span> rostered by another team"
        "</p>"
    )

    return (
        "<p class='dim'>Ranked by projected Yahoo FP per start using the Ridge model trained on 2024+2025 May-15+ data. "
        f"Source: <code>sp-correlation/output/2026_pitcher_projections.csv</code>. "
        f"Shows top 50 plus {len(extras)} rostered SP{'s' if len(extras) != 1 else ''} below rank 50.</p>"
        "<table class='sortable'>"
        "<thead><tr><th>Rank</th><th>Pitcher</th><th>Team</th>"
        "<th>N starts<br><small>(as-of)</small></th>"
        "<th>Proj FP/start</th>"
        "<th>Actual avg FP/start</th>"
        "<th>N starts<br><small>(actual)</small></th>"
        "<th>Role</th></tr></thead>"
        f"<tbody>{''.join(body)}</tbody></table>"
        f"{legend}{not_in_html}"
    )
