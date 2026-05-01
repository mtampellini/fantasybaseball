"""
Render the daily HTML report.

Sections in order (per Mike's spec):
    1. Header with team info, current week, last update
    2. My Hitters (lineup + Statcast)
    3. My Pitchers (rotation + Statcast + per-start xwOBA)
    4. Free Agent Hitters (top 30, Statcast)
    5. Free Agent Pitchers (top 30, Statcast + per-start)
    6. Probable Pitchers (this week + next week, mine + relevant FAs)
"""

from datetime import datetime
from html import escape

from render_weekly_section import (
    render_section as render_weekly_section,
    EXTRA_CSS as WEEKLY_CSS,
    SORTABLE_JS,
)


CSS = """
:root {
  --bg: #fafafa;
  --card: #ffffff;
  --text: #1a1a1a;
  --muted: #666;
  --border: #e0e0e0;
  --green: #1d9e75;
  --green-dark: #0f6e56;
  --red: #e24b4a;
  --red-dark: #a32d2d;
  --orange: #d85a30;
  --blue: #185fa5;
  --highlight-bg: #f0f7fc;
  --good-bg: #e1f5ee;
  --bad-bg: #fcebeb;
  --warn-bg: #fff3f0;
}
* { box-sizing: border-box; }
body {
  margin: 0; padding: 24px;
  font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
  background: var(--bg); color: var(--text);
  font-size: 13px; line-height: 1.5;
  max-width: 1400px; margin: 0 auto;
}
h1 { font-size: 24px; margin: 0 0 4px 0; }
h2 {
  font-size: 18px; margin: 32px 0 12px 0;
  padding-bottom: 6px; border-bottom: 2px solid var(--text);
}
h3 { font-size: 14px; margin: 16px 0 8px 0; color: var(--muted); font-weight: 500; }
.meta { color: var(--muted); font-size: 12px; margin: 0 0 16px 0; }
.section { background: var(--card); border-radius: 8px; padding: 20px; margin-bottom: 20px;
  border: 1px solid var(--border); }
table { width: 100%; border-collapse: collapse; font-size: 12px; }
th { text-align: left; font-weight: 500; padding: 6px 8px;
  border-bottom: 2px solid var(--text); font-size: 10px;
  text-transform: uppercase; letter-spacing: 0.4px; color: var(--muted);
  white-space: nowrap; }
td { padding: 6px 8px; border-bottom: 1px solid var(--border); }
.r { text-align: right; font-family: SFMono-Regular, Menlo, Consolas, monospace; font-size: 11.5px; }
.c { text-align: center; }
.nm { font-weight: 500; }
.nm a { color: inherit; text-decoration: none; border-bottom: 1px dotted var(--muted); }
.nm a:hover { color: var(--blue); }
.elite { color: var(--green-dark); font-weight: 600; }
.good { color: var(--green); }
.bad { color: var(--orange); }
.vbad { color: var(--red); font-weight: 500; }
.IL { background: var(--warn-bg); }
.injured { color: var(--red); font-size: 10px; font-weight: 500; }
.dropped { background: var(--bad-bg); }
.regress { background: var(--warn-bg); }
.poor-xwoba { background: var(--bad-bg); }
.hot { background: var(--good-bg); }
.two-start { background: var(--good-bg); }
.tag {
  display: inline-block; padding: 2px 6px; border-radius: 3px;
  font-size: 9px; font-weight: 600; text-transform: uppercase;
  letter-spacing: 0.3px; margin-left: 4px;
}
.tag-il { background: var(--red); color: white; }
.tag-dtd { background: var(--orange); color: white; }
.tag-na { background: #888; color: white; }
.tag-waiver { background: var(--blue); color: white; }
.dim { color: var(--muted); }
.per-start { font-family: SFMono-Regular, Menlo, monospace; font-size: 10.5px; }
.dot { color: var(--muted); margin: 0 4px; }
.note { color: var(--muted); font-size: 10px; margin-top: 4px; }
"""


def _fmt(val, places=3):
    if val is None or val == "":
        return '<span class="dim">—</span>'
    if isinstance(val, float):
        if places == 3:
            return f"{val:.3f}"
        if places == 1:
            return f"{val:.1f}"
        return f"{val:.{places}f}"
    return str(val)


def _xwoba_class(val):
    """Color class for an xwOBA value (pitcher; lower is better)."""
    if val is None:
        return ""
    if val < 0.260:
        return "elite"
    if val < 0.290:
        return "good"
    if val > 0.330:
        return "vbad"
    if val > 0.310:
        return "bad"
    return ""


def _hitter_xwoba_class(val):
    """For hitters, higher is better."""
    if val is None:
        return ""
    if val > 0.380:
        return "elite"
    if val > 0.350:
        return "good"
    if val < 0.280:
        return "vbad"
    if val < 0.300:
        return "bad"
    return ""


def _kbb_class(val):
    if val is None:
        return ""
    if val > 22:
        return "elite"
    if val > 18:
        return "good"
    if val < 12:
        return "vbad"
    return ""


def _bb_class(val):
    if val is None:
        return ""
    if val < 6:
        return "good"
    if val > 11:
        return "vbad"
    if val > 9:
        return "bad"
    return ""


def _status_tag(status):
    if not status:
        return ""
    s = status.upper()
    if "IL" in s or s == "NA":
        return f'<span class="tag tag-il">{escape(s)}</span>'
    if "DTD" in s:
        return f'<span class="tag tag-dtd">{escape(s)}</span>'
    return f'<span class="tag tag-na">{escape(s)}</span>'


def _row_class(player, kind=None):
    """Highlight class for whole row based on status + xwoba threshold."""
    classes = []
    s = (player.get("status") or "").upper()
    if "IL" in s or s == "NA":
        classes.append("IL")
    xw = player.get("xwoba")
    if xw is not None and kind:
        if kind == "B" and xw < 0.300:
            classes.append("poor-xwoba")
        elif kind == "P" and xw > 0.300:
            classes.append("poor-xwoba")
    return " ".join(classes)


def _player_link(player):
    pid = player.get("mlbam_id")
    name = escape(player.get("name") or "")
    waiver_tag = ' <span class="tag tag-waiver">W</span>' if player.get("on_waivers") else ""
    if pid:
        url = f"https://baseballsavant.mlb.com/savant-player/{pid}"
        return f'<a href="{url}" target="_blank">{name}</a>{waiver_tag}'
    return name + waiver_tag


def render_hitter_row(p, show_slot=True):
    cells = []
    if show_slot:
        cells.append(f'<td class="c">{escape(p.get("selected_position") or "")}</td>')
    name_html = _player_link(p) + _status_tag(p.get("status"))
    cells.append(f'<td class="nm">{name_html}</td>')
    cells.append(f'<td class="c">{escape(p.get("team") or "")}</td>')
    cells.append(f'<td class="r">{_fmt(p.get("avg_fp_4w"), 1)}</td>')
    cells.append(f'<td class="r">{_fmt(p.get("babip"))}</td>')
    cells.append(f'<td class="r">{_fmt(p.get("woba"))}</td>')
    xwc = _hitter_xwoba_class(p.get("xwoba"))
    cells.append(f'<td class="r {xwc}">{_fmt(p.get("xwoba"))}</td>')
    cells.append(f'<td class="r">{_fmt(p.get("xslg"))}</td>')
    gap = p.get("woba_xwoba_gap")
    gap_class = "vbad" if gap is not None and gap > 80 else ("good" if gap is not None and gap < -50 else "")
    gap_str = f"{gap:+d}" if gap is not None else "—"
    cells.append(f'<td class="r {gap_class}">{gap_str}</td>')
    return f'<tr class="{_row_class(p, "B")}">' + "".join(cells) + "</tr>"


def render_pitcher_row(p, show_slot=True):
    cells = []
    if show_slot:
        cells.append(f'<td class="c">{escape(p.get("selected_position") or "")}</td>')
    name_html = _player_link(p) + _status_tag(p.get("status"))
    cells.append(f'<td class="nm">{name_html}</td>')
    cells.append(f'<td class="c">{escape(p.get("team") or "")}</td>')
    cells.append(f'<td class="r">{_fmt(p.get("avg_fp_4w"), 1)}</td>')
    cells.append(f'<td class="r">{_fmt(p.get("k_pct"), 1)}</td>')
    bbc = _bb_class(p.get("bb_pct"))
    cells.append(f'<td class="r {bbc}">{_fmt(p.get("bb_pct"), 1)}</td>')
    kbbc = _kbb_class(p.get("k_bb_pct"))
    cells.append(f'<td class="r {kbbc}">{_fmt(p.get("k_bb_pct"), 1)}</td>')
    cells.append(f'<td class="r">{_fmt(p.get("babip"))}</td>')
    cells.append(f'<td class="r">{_fmt(p.get("woba"))}</td>')
    xwc = _xwoba_class(p.get("xwoba"))
    cells.append(f'<td class="r {xwc}">{_fmt(p.get("xwoba"))}</td>')
    sd = p.get("per_start_sd")
    cells.append(f'<td class="r">{_fmt(sd)}</td>')
    # Per-start summary
    starts = p.get("per_start") or []
    if starts:
        pcs_html = '<span class="per-start">' + ' <span class="dot">·</span> '.join(
            f'{_xwoba_inline_class(s["xwoba"])}{s["xwoba"]:.3f}</span>'
            for s in starts
        ) + '</span>'
    else:
        pcs_html = '<span class="dim">—</span>'
    cells.append(f'<td>{pcs_html}</td>')
    return f'<tr class="{_row_class(p, "P")}">' + "".join(cells) + "</tr>"


def _xwoba_inline_class(val):
    """Inline span class for per-start values."""
    if val is None:
        return '<span>'
    cls = _xwoba_class(val)
    return f'<span class="{cls}">' if cls else '<span>'


def render_my_hitters_table(hitters):
    rows = "\n".join(render_hitter_row(h) for h in hitters)
    return f"""
<table>
  <thead>
    <tr>
      <th>Slot</th>
      <th>Hitter</th>
      <th>Team</th>
      <th class="r">Avg_FP_L4_Weeks</th>
      <th class="r">BABIP</th>
      <th class="r">wOBA</th>
      <th class="r">xwOBA</th>
      <th class="r">xSLG</th>
      <th class="r">Gap</th>
    </tr>
  </thead>
  <tbody>
{rows}
  </tbody>
</table>
<p class="note">Avg_FP_L4_Weeks = (last-month FP total) / 4, i.e. weekly average over the last 4 weeks. Row highlighted red when xwOBA &lt; .300. Gap = wOBA − xwOBA in points. Positive = lucky outcomes (regression incoming). Negative = unlucky (positive regression candidate).</p>
"""


def render_my_pitchers_table(pitchers):
    pitchers = sorted(pitchers, key=lambda p: (p.get("xwoba") is None, p.get("xwoba") or 1))
    rows = "\n".join(render_pitcher_row(p) for p in pitchers)
    return f"""
<table>
  <thead>
    <tr>
      <th>Slot</th>
      <th>Pitcher</th>
      <th>Team</th>
      <th class="r">Avg_FP_L4_Weeks</th>
      <th class="r">K%</th>
      <th class="r">BB%</th>
      <th class="r">K-BB%</th>
      <th class="r">BABIP</th>
      <th class="r">wOBA</th>
      <th class="r">xwOBA</th>
      <th class="r">SD</th>
      <th>Per-start xwOBA (recent → older)</th>
    </tr>
  </thead>
  <tbody>
{rows}
  </tbody>
</table>
<p class="note">Avg_FP_L4_Weeks = (last-month FP total) / 4, i.e. weekly average over the last 4 weeks. Row highlighted red when xwOBA &gt; .300. SD = standard deviation of per-start xwOBA over last 5 starts. K-BB% color: green ≥ 18, red ≤ 12.</p>
"""


def render_fa_hitters_table(hitters):
    hitters = sorted(hitters, key=lambda h: (h.get("xwoba") is None, -(h.get("xwoba") or 0)))
    rows = []
    for h in hitters:
        cells = []
        cells.append(f'<td class="nm">{_player_link(h)}{_status_tag(h.get("status"))}</td>')
        cells.append(f'<td class="c">{escape(h.get("team") or "")}</td>')
        positions = ", ".join(h.get("eligible_positions") or [])
        cells.append(f'<td class="dim">{escape(positions)}</td>')
        ros = h.get("percent_owned")
        cells.append(f'<td class="r">{int(ros) if ros is not None else "—"}%</td>')
        cells.append(f'<td class="r">{_fmt(h.get("fantasy_points"), 1)}</td>')
        cells.append(f'<td class="r">{_fmt(h.get("avg_fp_4w"), 1)}</td>')
        cells.append(f'<td class="r">{_fmt(h.get("avg_fp_2w_est"), 1)}</td>')
        cells.append(f'<td class="r">{_fmt(h.get("babip"))}</td>')
        cells.append(f'<td class="r">{_fmt(h.get("woba"))}</td>')
        xwc = _hitter_xwoba_class(h.get("xwoba"))
        cells.append(f'<td class="r {xwc}">{_fmt(h.get("xwoba"))}</td>')
        cells.append(f'<td class="r">{_fmt(h.get("xslg"))}</td>')
        gap = h.get("woba_xwoba_gap")
        gap_class = "vbad" if gap is not None and gap > 80 else ("good" if gap is not None and gap < -50 else "")
        gap_str = f"{gap:+d}" if gap is not None else "—"
        cells.append(f'<td class="r {gap_class}">{gap_str}</td>')
        rows.append(f'<tr class="{_row_class(h, "B")}">' + "".join(cells) + "</tr>")
    rows_html = "\n".join(rows)
    return f"""
<table class="sortable">
  <thead>
    <tr>
      <th>Hitter</th>
      <th>Team</th>
      <th>Eligible</th>
      <th class="r">%Ros</th>
      <th class="r">FP</th>
      <th class="r">Avg_FP_L4W</th>
      <th class="r">Avg_FP_L2W</th>
      <th class="r">BABIP</th>
      <th class="r">wOBA</th>
      <th class="r">xwOBA</th>
      <th class="r">xSLG</th>
      <th class="r">Gap</th>
    </tr>
  </thead>
  <tbody>
{rows_html}
  </tbody>
</table>
<p class="note">Pool: top 100 by Yahoo ownership/season FP (incl. waivers), filtered to those with ≥15 PA over the last 2 weeks (1-week data extrapolated), then re-ranked by hybrid (L4W/wk + L1W) and trimmed to 50. Avg_FP_L2W est uses Yahoo's lastweek (7d) since 14d isn't exposed. Display sorted by xwOBA desc. Row highlighted red when xwOBA &lt; .300. <strong>W</strong> badge = waiver claim required.</p>
"""


def render_fa_pitchers_table(pitchers):
    pitchers = sorted(pitchers, key=lambda p: (p.get("xwoba") is None, p.get("xwoba") or 1))
    rows = []
    for p in pitchers:
        cells = []
        cells.append(f'<td class="nm">{_player_link(p)}{_status_tag(p.get("status"))}</td>')
        cells.append(f'<td class="c">{escape(p.get("team") or "")}</td>')
        positions = ", ".join(p.get("eligible_positions") or [])
        cells.append(f'<td class="dim">{escape(positions)}</td>')
        ros = p.get("percent_owned")
        cells.append(f'<td class="r">{int(ros) if ros is not None else "—"}%</td>')
        cells.append(f'<td class="r">{_fmt(p.get("fantasy_points"), 1)}</td>')
        cells.append(f'<td class="r">{_fmt(p.get("avg_fp_4w"), 1)}</td>')
        cells.append(f'<td class="r">{_fmt(p.get("avg_fp_2w_est"), 1)}</td>')
        cells.append(f'<td class="r">{_fmt(p.get("k_pct"), 1)}</td>')
        bbc = _bb_class(p.get("bb_pct"))
        cells.append(f'<td class="r {bbc}">{_fmt(p.get("bb_pct"), 1)}</td>')
        kbbc = _kbb_class(p.get("k_bb_pct"))
        cells.append(f'<td class="r {kbbc}">{_fmt(p.get("k_bb_pct"), 1)}</td>')
        xwc = _xwoba_class(p.get("xwoba"))
        cells.append(f'<td class="r {xwc}">{_fmt(p.get("xwoba"))}</td>')
        cells.append(f'<td class="r">{_fmt(p.get("per_start_sd"))}</td>')
        starts = p.get("per_start") or []
        if starts:
            pcs_html = ' <span class="dot">·</span> '.join(
                f'{_xwoba_inline_class(s["xwoba"])}{s["xwoba"]:.3f}</span>'
                for s in starts
            )
        else:
            pcs_html = '<span class="dim">—</span>'
        cells.append(f'<td class="per-start">{pcs_html}</td>')
        rows.append(f'<tr class="{_row_class(p, "P")}">' + "".join(cells) + "</tr>")
    rows_html = "\n".join(rows)
    return f"""
<table class="sortable">
  <thead>
    <tr>
      <th>Pitcher</th>
      <th>Team</th>
      <th>Eligible</th>
      <th class="r">%Ros</th>
      <th class="r">FP</th>
      <th class="r">Avg_FP_L4W</th>
      <th class="r">Avg_FP_L2W</th>
      <th class="r">K%</th>
      <th class="r">BB%</th>
      <th class="r">K-BB%</th>
      <th class="r">xwOBA</th>
      <th class="r">SD</th>
      <th>Per-start xwOBA</th>
    </tr>
  </thead>
  <tbody>
{rows_html}
  </tbody>
</table>
<p class="note">Pool: top 100 by Yahoo ownership/season FP (incl. waivers), then pure RPs without xwOBA &lt; .300 dropped, then re-ranked by hybrid (L4W/wk + L1W) and trimmed to 50. Avg_FP_L2W est uses Yahoo's lastweek (7d) since 14d isn't exposed. Display sorted by xwOBA ascending. Row highlighted red when xwOBA &gt; .300. <strong>W</strong> badge = waiver claim required.</p>
"""


def render_probables_section(my_pitchers, fa_pitchers):
    """Two tables: my rotation upcoming starts, then FA upcoming starts."""

    def render_starts(starts):
        if not starts:
            return '<span class="dim">—</span>'
        return ' <span class="dot">·</span> '.join(
            f'{s["date"][5:]} {"vs" if s["is_home"] else "@"} {escape(s["opponent"] or "")}'
            for s in starts
        )

    def pitcher_starts_row(p):
        tw = sorted(p.get("this_week_starts") or [], key=lambda s: s["date"])
        nw = sorted(p.get("next_week_starts") or [], key=lambda s: s["date"])
        total = len(tw) + len(nw)
        tw_cls = "two-start" if len(tw) >= 2 else ""
        nw_cls = "two-start" if len(nw) >= 2 else ""
        return f"""
<tr>
  <td class="nm">{_player_link(p)}</td>
  <td class="{tw_cls}">{render_starts(tw)}</td>
  <td class="{nw_cls}">{render_starts(nw)}</td>
  <td class="r">{total}</td>
</tr>"""

    # Sort: max-of-either-week desc (so 2-start weeks float up), then total desc
    def starts_sort_key(p):
        tw = len(p.get("this_week_starts") or [])
        nw = len(p.get("next_week_starts") or [])
        return (-max(tw, nw), -(tw + nw))

    my_with_starts = sorted(
        [p for p in my_pitchers if p.get("this_week_starts") or p.get("next_week_starts")],
        key=starts_sort_key,
    )
    my_rows = "\n".join(pitcher_starts_row(p) for p in my_with_starts)
    if not my_rows:
        my_rows = '<tr><td colspan="4" class="dim">No probable starts found</td></tr>'

    fa_with_starts = sorted(
        [p for p in fa_pitchers if p.get("this_week_starts") or p.get("next_week_starts")],
        key=starts_sort_key,
    )
    fa_rows = "\n".join(pitcher_starts_row(p) for p in fa_with_starts)
    if not fa_rows:
        fa_rows = '<tr><td colspan="4" class="dim">No probable starts found</td></tr>'

    return f"""
<h3>My Rotation</h3>
<table>
  <thead>
    <tr><th>Pitcher</th><th>This Week</th><th>Next Week</th><th class="r">Total</th></tr>
  </thead>
  <tbody>
{my_rows}
  </tbody>
</table>

<h3 style="margin-top: 20px;">Free Agent Pitchers</h3>
<p class="note">Cells with 2 starts highlighted green. Sorted to surface 2-start weeks (this or next), then by total. Dates Mon -> Sun within each week.</p>
<table>
  <thead>
    <tr><th>Pitcher</th><th>This Week</th><th>Next Week</th><th class="r">Total</th></tr>
  </thead>
  <tbody>
{fa_rows}
  </tbody>
</table>
"""


def render_html(snapshot):
    """Build the full HTML document."""
    today = snapshot.get("date", datetime.now().strftime("%Y-%m-%d"))
    last_update = snapshot.get("generated_at", "")
    week = snapshot.get("week", "—")
    record = snapshot.get("record", "")

    my_hitters = snapshot.get("my_hitters", [])
    my_pitchers = snapshot.get("my_pitchers", [])
    fa_hitters = snapshot.get("fa_hitters", [])
    fa_pitchers = snapshot.get("fa_pitchers", [])
    league_metrics = snapshot.get("league_metrics")

    weekly_section_html = render_weekly_section(league_metrics) if league_metrics else ""

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Tamp Slam Daily Report — {today}</title>
<style>{CSS}{WEEKLY_CSS}</style>
</head>
<body>

<header>
  <h1>Tamp Slam Daily Report</h1>
  <p class="meta">{today} · Week {week} · Record {record} · Updated {last_update}</p>
</header>

<section class="section">
  <h2>My Hitters</h2>
  {render_my_hitters_table(my_hitters)}
</section>

<section class="section">
  <h2>My Pitchers</h2>
  {render_my_pitchers_table(my_pitchers)}
</section>

{weekly_section_html}

<section class="section">
  <h2>Free Agent Hitters (Top {len(fa_hitters)})</h2>
  {render_fa_hitters_table(fa_hitters)}
</section>

<section class="section">
  <h2>Free Agent Pitchers (Top {len(fa_pitchers)})</h2>
  {render_fa_pitchers_table(fa_pitchers)}
</section>

<section class="section">
  <h2>Probable Pitchers</h2>
  {render_probables_section(my_pitchers, fa_pitchers)}
</section>

<footer style="margin-top: 40px; color: var(--muted); font-size: 11px; text-align: center;">
  Generated by mtampellini/fantasybaseball · Data: Yahoo Fantasy, Baseball Savant, Fangraphs RosterResource
</footer>

{SORTABLE_JS}
</body>
</html>"""
