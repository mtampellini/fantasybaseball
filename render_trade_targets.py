"""
Render the Trade Targets HTML section.

Reuses formatting helpers from render_report so the section blends in.
Top 5 candidates are highlighted with a background tint.
"""

from html import escape


# Extra CSS appended onto the main CSS block in render_report.
TRADE_TARGETS_CSS = """
.tt-top1, .tt-top2, .tt-top3, .tt-top4, .tt-top5 { background: var(--highlight-bg); }
.tt-top1 td:nth-child(2), .tt-top2 td:nth-child(2),
.tt-top3 td:nth-child(2), .tt-top4 td:nth-child(2),
.tt-top5 td:nth-child(2) { font-weight: 700; }
.tt-score { font-weight: 600; }
"""


def _player_link_for_target(t):
    pid = t.get("mlbam_id")
    name = escape(t.get("name") or "")
    if pid:
        url = f"https://baseballsavant.mlb.com/savant-player/{pid}"
        return f'<a href="{url}" target="_blank">{name}</a>'
    return name


def _signed(val, places=3):
    if val is None:
        return '<span class="dim">—</span>'
    sign = "+" if val >= 0 else "−"
    if places == 1:
        return f"{sign}{abs(val):.1f}"
    return f"{sign}{abs(val):.{places}f}"


def _gap_class(gap_points):
    """Color for xwOBA-wOBA gap. Positive gap = unlucky = good for trade target."""
    if gap_points is None:
        return ""
    if gap_points >= 60:
        return "elite"
    if gap_points >= 30:
        return "good"
    return ""


def _row_class(rank):
    if rank <= 5:
        return f"tt-top{rank}"
    return ""


def render_trade_targets_section(targets):
    # Lazy-import helpers to avoid a circular import with render_report.
    from render_report import _fmt, _hitter_xwoba_class

    if not targets:
        return """
<p class="dim">No trade-target candidates met the qualification thresholds today.</p>
"""

    rows = []
    for rank, t in enumerate(targets, 1):
        d = t.get("drivers") or {}
        name_html = _player_link_for_target(t)

        positions = ", ".join(t.get("eligible_positions") or [])
        if positions:
            name_html += f' <span class="dim" style="font-size:10px;">({escape(positions)})</span>'

        woba_2026 = d.get("woba_2026")
        xwoba_2026 = d.get("xwoba_2026")
        babip_2026 = d.get("babip_2026")
        gap_pts = d.get("gap_points")

        babip_baseline = d.get("babip_baseline")
        babip_baseline_src = d.get("babip_baseline_source")
        babip_delta = d.get("babip_delta")

        woba_2025 = d.get("woba_2025")
        yoy_delta = d.get("yoy_delta")

        xwc = _hitter_xwoba_class(xwoba_2026)
        gapc = _gap_class(gap_pts)

        cells = [
            f'<td class="r dim">{rank}</td>',
            f'<td class="nm">{name_html}</td>',
            f'<td class="c">{escape(t.get("team") or "—")}</td>',
            f'<td>{escape(t.get("owner_team_name") or "")}</td>',
            f'<td class="r">{_fmt(woba_2026)}</td>',
            f'<td class="r {xwc}">{_fmt(xwoba_2026)}</td>',
            f'<td class="r {gapc}">{_signed(gap_pts, 1) if gap_pts is not None else "—"}</td>',
            f'<td class="r">{_fmt(babip_2026)}</td>',
            (f'<td class="r">{_fmt(babip_baseline)}'
             f'<span class="dim" style="font-size:9px;"> ({escape(babip_baseline_src or "")})</span></td>'),
            f'<td class="r">{_signed(babip_delta) if babip_delta is not None else "—"}</td>',
            f'<td class="r">{_fmt(woba_2025)}</td>',
            f'<td class="r">{_signed(yoy_delta) if yoy_delta is not None else "—"}</td>',
            f'<td class="r tt-score">{t.get("score"):.1f}</td>',
        ]
        rows.append(f'<tr class="{_row_class(rank)}">' + "".join(cells) + "</tr>")

    rows_html = "\n".join(rows)
    return f"""
<table>
  <thead>
    <tr>
      <th class="r">#</th>
      <th>Hitter</th>
      <th>MLB</th>
      <th>Owner</th>
      <th class="r">'26 wOBA</th>
      <th class="r">'26 xwOBA</th>
      <th class="r">Gap</th>
      <th class="r">'26 BABIP</th>
      <th class="r">Career BABIP</th>
      <th class="r">BABIP Δ</th>
      <th class="r">'25 wOBA</th>
      <th class="r">YoY Δ</th>
      <th class="r">Score</th>
    </tr>
  </thead>
  <tbody>
{rows_html}
  </tbody>
</table>
<p class="note">
  <strong>Trade-target scoring:</strong> 2.0 × max(0, xwOBA − wOBA) × 1000 + 1.0 × max(0, careerBABIP − BABIP) × 100 + 1.0 × min(40, max(0, '25 wOBA − '26 wOBA)) × 100.
  Positive Gap = wOBA below xwOBA (unlucky). Positive BABIP Δ = 2026 BABIP below baseline. Positive YoY Δ = 2026 wOBA below 2025.
  Top 5 rows highlighted. Filters: ≥ 50 PA in 2026, ≥ 200 PA in 2025 (for YoY signal); excludes catchers, IL/NA, my team.
</p>
"""
