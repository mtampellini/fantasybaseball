"""
Render the "League Standings & Distributions" section for the daily report.

Three sub-sections:
  1. Most recent completed week — all 14 teams ranked, my row highlighted.
  2. Season distributions (Weeks 2..N) — three side-by-side tables for
     hitting consistency, pitching consistency, and total mean.
  3. My Position — three big stat boxes plus a one-paragraph summary.

This module is intentionally separate from render_report.py so the
existing renderer doesn't bloat. render_report.py imports and calls
render_section() to drop this in.
"""

from html import escape

from config import YAHOO_TEAM_ID


# Extra CSS just for this section. Folded into render_report.CSS at import time.
EXTRA_CSS = """
.weekly-grid {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 12px;
  margin-top: 8px;
}
.weekly-grid table { font-size: 11px; }
.weekly-grid h3 { margin-top: 0; }
.me-row { background: var(--good-bg); font-weight: 600; }
.me-row td { font-weight: 600; }
.in-progress-tag {
  display: inline-block;
  background: var(--orange);
  color: white;
  font-size: 9px;
  font-weight: 600;
  padding: 2px 6px;
  border-radius: 3px;
  margin-left: 8px;
  text-transform: uppercase;
  letter-spacing: 0.4px;
  vertical-align: middle;
}
table.sortable th { cursor: pointer; user-select: none; }
table.sortable th:hover { color: var(--blue); }
table.sortable th[data-sort-dir="asc"]::after  { content: " \\25B2"; color: var(--blue); }
table.sortable th[data-sort-dir="desc"]::after { content: " \\25BC"; color: var(--blue); }
.chart-grid {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 12px;
  margin-top: 16px;
}
.chart-box {
  background: var(--card);
  border: 1px solid var(--border);
  border-radius: 6px;
  padding: 12px;
}
.chart-box h4 {
  margin: 0 0 8px 0;
  font-size: 12px;
  font-weight: 500;
  color: var(--muted);
  text-transform: uppercase;
  letter-spacing: 0.4px;
}
.chart-line-other {
  stroke: var(--muted);
  stroke-width: 1;
  opacity: 0.35;
  fill: none;
}
.chart-line-other:hover {
  opacity: 0.9;
  stroke: var(--text);
  stroke-width: 1.5;
}
.chart-line-me {
  stroke: var(--blue);
  stroke-width: 2.5;
  fill: none;
}
.chart-dot-me {
  fill: var(--blue);
}
.chart-axis {
  stroke: var(--border);
}
.chart-tick {
  fill: var(--muted);
  font-size: 9px;
}
.chart-x-label {
  fill: var(--muted);
  font-size: 10px;
}
.stat-boxes {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 12px;
  margin: 8px 0 12px 0;
}
.stat-box {
  background: var(--card);
  border: 1px solid var(--border);
  border-radius: 6px;
  padding: 12px;
  text-align: center;
}
.stat-box .label {
  font-size: 10px;
  text-transform: uppercase;
  letter-spacing: 0.4px;
  color: var(--muted);
  margin-bottom: 4px;
}
.stat-box .rank {
  font-size: 28px;
  font-weight: 700;
  color: var(--blue);
  line-height: 1;
}
.stat-box .of {
  font-size: 14px;
  color: var(--muted);
}
.stat-box .detail {
  font-size: 11px;
  color: var(--muted);
  margin-top: 6px;
}
.summary-line {
  background: var(--highlight-bg);
  padding: 10px 12px;
  border-radius: 6px;
  font-size: 12px;
  margin: 8px 0 0 0;
}
.diff-pos { color: var(--green); font-weight: 600; }
.diff-neg { color: var(--red); font-weight: 600; }
"""


def _hit_sd_class(sd):
    if sd is None:
        return ""
    if sd < 40:
        return "good"
    if sd > 70:
        return "vbad"
    return ""


def _pitch_sd_class(sd):
    if sd is None:
        return ""
    if sd < 30:
        return "good"
    if sd > 50:
        return "vbad"
    return ""


def _is_me(team_id):
    try:
        return int(team_id) == int(YAHOO_TEAM_ID)
    except (ValueError, TypeError):
        return False


def _row_cls(team_id):
    return "me-row" if _is_me(team_id) else ""


def _render_week_table(week, results, in_progress=False):
    """Render one weekly results table — works for either completed or in-progress week."""
    sorted_results = sorted(results, key=lambda r: -r["total"])
    hit_order = sorted(results, key=lambda r: -r["hitting"])
    pitch_order = sorted(results, key=lambda r: -r["pitching"])
    hit_rank = {r["team_id"]: i + 1 for i, r in enumerate(hit_order)}
    pitch_rank = {r["team_id"]: i + 1 for i, r in enumerate(pitch_order)}

    n = len(results)
    avg_total = sum(r["total"] for r in results) / n if n else 0
    avg_hit = sum(r["hitting"] for r in results) / n if n else 0
    avg_pitch = sum(r["pitching"] for r in results) / n if n else 0

    rows = []
    for i, r in enumerate(sorted_results, start=1):
        cls = _row_cls(r["team_id"])
        cells = [
            f'<td class="r">{i}</td>',
            f'<td class="nm">{escape(r["team_name"])}</td>',
            f'<td class="r">{r["hitting"]:.2f}</td>',
            f'<td class="r dim">#{hit_rank[r["team_id"]]}</td>',
            f'<td class="r">{r["pitching"]:.2f}</td>',
            f'<td class="r dim">#{pitch_rank[r["team_id"]]}</td>',
            f'<td class="r"><strong>{r["total"]:.2f}</strong></td>',
        ]
        if _is_me(r["team_id"]):
            diff = r["total"] - avg_total
            cls_d = "diff-pos" if diff >= 0 else "diff-neg"
            cells.append(f'<td class="r {cls_d}">{diff:+.1f}</td>')
        else:
            cells.append('<td class="r dim">—</td>')
        rows.append(f'<tr class="{cls}">' + "".join(cells) + "</tr>")

    title_prefix = "Current Week — " if in_progress else "Most Recent Completed Week — "
    title_tag = '<span class="in-progress-tag">in progress</span>' if in_progress else ""
    label = "so far" if in_progress else "this week"

    return f"""
<h3>{title_prefix}Week {week}{title_tag}</h3>
<table class="sortable">
  <thead>
    <tr>
      <th class="r">Rank</th>
      <th>Team</th>
      <th class="r">Hitting</th>
      <th class="r">Hit#</th>
      <th class="r">Pitching</th>
      <th class="r">Pit#</th>
      <th class="r">Total</th>
      <th class="r">vs avg</th>
    </tr>
  </thead>
  <tbody>
{chr(10).join(rows)}
  </tbody>
</table>
<p class="note">League avg {label}: hit {avg_hit:.1f} / pitch {avg_pitch:.1f} / total {avg_total:.1f}. Tamp Slam highlighted. Click any column header to sort.</p>
"""


def _render_recent_week(week, results):
    """Backwards-compatible wrapper — completed week."""
    return _render_week_table(week, results, in_progress=False)


def _render_current_week(week, results):
    """In-progress week with same shape."""
    return _render_week_table(week, results, in_progress=True)


def _render_standings(standings):
    """Yahoo standings table: rank, team, record, PF, PA, waiver, moves, trades."""
    if not standings:
        return ""
    rows = []
    for s in standings:
        cls = _row_cls(s["team_id"])
        record = f'{s["wins"]}-{s["losses"]}' + (f'-{s["ties"]}' if s["ties"] else "")
        diff = s["points_for"] - s["points_against"]
        diff_cls = "diff-pos" if diff >= 0 else "diff-neg"
        cells = [
            f'<td class="r">{s["rank"]}</td>',
            f'<td class="nm">{escape(s["team_name"])}</td>',
            f'<td class="c">{record}</td>',
            f'<td class="r">{s["win_pct"]:.3f}</td>',
            f'<td class="c dim">{escape(str(s["games_back"]))}</td>',
            f'<td class="r"><strong>{s["points_for"]:.2f}</strong></td>',
            f'<td class="r dim">{s["points_against"]:.2f}</td>',
            f'<td class="r {diff_cls}">{diff:+.1f}</td>',
            f'<td class="r">{s["waiver_priority"]}</td>',
            f'<td class="r">{s["moves"]}</td>',
            f'<td class="r dim">{s["trades"]}</td>',
        ]
        rows.append(f'<tr class="{cls}">' + "".join(cells) + "</tr>")

    return f"""
<h3 style="margin-top: 24px;">Standings</h3>
<table class="sortable">
  <thead>
    <tr>
      <th class="r">Rank</th>
      <th>Team</th>
      <th class="c">Record</th>
      <th class="r">Win%</th>
      <th class="c">GB</th>
      <th class="r">PF</th>
      <th class="r">PA</th>
      <th class="r">PF-PA</th>
      <th class="r">Waiver</th>
      <th class="r">Moves</th>
      <th class="r">Trades</th>
    </tr>
  </thead>
  <tbody>
{chr(10).join(rows)}
  </tbody>
</table>
<p class="note">PF = points for. PA = points against. Click any column header to sort. Tamp Slam highlighted.</p>
"""


def _line_chart(title, weeks_data, value_key, exclude_weeks=(1,)):
    """Render one inline-SVG line chart of `value_key` per team across weeks.

    Excludes Week 1 (short opening week outlier) and any in-progress week.
    Tamp Slam line is bold blue; other 13 teams faint gray with hover tooltips.
    """
    teams = {}  # team_id -> {team_name, points: {week: value}}
    week_set = set()
    for w in weeks_data:
        wk = w["week"]
        if wk in exclude_weeks:
            continue
        if w.get("in_progress"):
            continue
        week_set.add(wk)
        for r in w["results"]:
            tid = r["team_id"]
            if tid is None:
                continue
            entry = teams.setdefault(tid, {"team_name": r["team_name"], "points": {}})
            entry["points"][wk] = r[value_key]
    weeks = sorted(week_set)
    if len(weeks) < 1 or not teams:
        return ""

    all_vals = [v for t in teams.values() for v in t["points"].values()]
    y_min, y_max = min(all_vals), max(all_vals)
    pad = max(1.0, (y_max - y_min) * 0.08)
    y_min -= pad
    y_max += pad
    if y_max - y_min < 1e-9:
        y_max = y_min + 1.0

    W, H = 340, 220
    ml, mr, mt, mb = 38, 12, 10, 28
    pw, ph = W - ml - mr, H - mt - mb

    def x(wk):
        if len(weeks) == 1:
            return ml + pw / 2
        return ml + (weeks.index(wk) / (len(weeks) - 1)) * pw

    def y(val):
        return mt + ph * (1 - (val - y_min) / (y_max - y_min))

    n_ticks = 5
    y_ticks_html = []
    for i in range(n_ticks):
        v = y_min + (y_max - y_min) * i / (n_ticks - 1)
        ty = y(v)
        y_ticks_html.append(
            f'<line class="chart-axis" x1="{ml - 3}" y1="{ty:.1f}" x2="{ml}" y2="{ty:.1f}" />'
            f'<text class="chart-tick" x="{ml - 5}" y="{ty + 3:.1f}" text-anchor="end">{v:.0f}</text>'
        )

    x_labels = "".join(
        f'<text class="chart-x-label" x="{x(wk):.1f}" y="{H - mb + 14}" text-anchor="middle">W{wk}</text>'
        for wk in weeks
    )

    me_id = None
    try:
        me_id = int(YAHOO_TEAM_ID)
    except (ValueError, TypeError):
        pass

    other_lines = []
    me_line = ""
    me_dots = ""
    for tid, t in teams.items():
        pts = []
        for wk in weeks:
            v = t["points"].get(wk)
            if v is None:
                continue
            pts.append(f"{x(wk):.1f},{y(v):.1f}")
        if not pts:
            continue
        is_me = (tid == me_id)
        polyline = (
            f'<polyline class="{"chart-line-me" if is_me else "chart-line-other"}" '
            f'points="{" ".join(pts)}">'
            f'<title>{escape(t["team_name"])}</title></polyline>'
        )
        if is_me:
            me_line = polyline
            for wk in weeks:
                v = t["points"].get(wk)
                if v is None:
                    continue
                me_dots += f'<circle class="chart-dot-me" cx="{x(wk):.1f}" cy="{y(v):.1f}" r="3" />'
        else:
            other_lines.append(polyline)

    return f"""
<div class="chart-box">
  <h4>{escape(title)}</h4>
  <svg viewBox="0 0 {W} {H}" width="100%" preserveAspectRatio="xMidYMid meet">
    <line class="chart-axis" x1="{ml}" y1="{mt}" x2="{ml}" y2="{H - mb}" />
    <line class="chart-axis" x1="{ml}" y1="{H - mb}" x2="{W - mr}" y2="{H - mb}" />
    {"".join(y_ticks_html)}
    {x_labels}
    {"".join(other_lines)}
    {me_line}
    {me_dots}
  </svg>
</div>
"""


def _render_weekly_charts(weeks_data):
    """Three side-by-side line charts: Total, Pitching, Hitting."""
    if not weeks_data:
        return ""
    total = _line_chart("Total Points", weeks_data, "total")
    pitch = _line_chart("Pitching Points", weeks_data, "pitching")
    hit = _line_chart("Hitting Points", weeks_data, "hitting")
    if not (total or pitch or hit):
        return ""
    return f"""
<h3 style="margin-top: 24px;">Weekly Trend (W2 → most recent)</h3>
<p class="note">Tamp Slam in blue; other teams in gray. Hover any line for the team name.</p>
<div class="chart-grid">
{total}
{pitch}
{hit}
</div>
"""


# Vanilla JS injected once per report. Looks up tables with class "sortable"
# and wires click-to-sort on headers. Numeric vs text auto-detected per column.
SORTABLE_JS = """
<script>
(function () {
  function parseCell(td) {
    var raw = (td.textContent || '').trim();
    var m = raw.match(/-?[0-9][0-9,]*\\.?[0-9]*/);
    if (m) {
      var num = parseFloat(m[0].replace(/,/g, ''));
      if (!isNaN(num)) return { num: num, str: raw };
    }
    return { num: null, str: raw };
  }
  function sortTable(table, colIdx, dir) {
    var tbody = table.tBodies[0];
    var rows = Array.prototype.slice.call(tbody.rows);
    rows.sort(function (a, b) {
      var x = parseCell(a.cells[colIdx]);
      var y = parseCell(b.cells[colIdx]);
      var cmp;
      if (x.num !== null && y.num !== null) cmp = x.num - y.num;
      else cmp = x.str.localeCompare(y.str);
      return dir === 'asc' ? cmp : -cmp;
    });
    rows.forEach(function (r) { tbody.appendChild(r); });
  }
  document.querySelectorAll('table.sortable').forEach(function (table) {
    var ths = table.tHead ? table.tHead.rows[0].cells : [];
    Array.prototype.forEach.call(ths, function (th, idx) {
      th.addEventListener('click', function () {
        var current = th.getAttribute('data-sort-dir');
        var next = current === 'asc' ? 'desc' : 'asc';
        Array.prototype.forEach.call(ths, function (h) { h.removeAttribute('data-sort-dir'); });
        th.setAttribute('data-sort-dir', next);
        sortTable(table, idx, next);
      });
    });
  });
})();
</script>
"""


def _render_distribution_table(teams, sort_key, sort_reverse, columns, title, sd_class_fn=None):
    """Generic 3-column distribution table (team, mean, SD) sorted by sort_key.

    columns is a list of (header, getter) pairs for the value cells.
    """
    sorted_teams = sorted(teams, key=lambda t: t[sort_key], reverse=sort_reverse)
    rows = []
    for i, t in enumerate(sorted_teams, start=1):
        cells = [f'<td class="r dim">{i}</td>',
                 f'<td class="nm">{escape(t["team_name"])}</td>']
        for header, getter in columns:
            v = getter(t)
            cls = ""
            if sd_class_fn and "sd" in header.lower():
                cls = sd_class_fn(v) or ""
            cells.append(f'<td class="r {cls}">{v:.1f}</td>')
        rows.append(f'<tr class="{_row_cls(t["team_id"])}">' + "".join(cells) + "</tr>")

    head_cells = '<th class="r">#</th><th>Team</th>' + "".join(
        f'<th class="r">{h}</th>' for h, _ in columns
    )
    return f"""
<div>
  <h3>{title}</h3>
  <table class="sortable">
    <thead><tr>{head_cells}</tr></thead>
    <tbody>
{chr(10).join(rows)}
    </tbody>
  </table>
</div>
"""


def _render_season_distributions(distributions):
    """Three side-by-side tables: hit consistency, pitch consistency, total mean."""
    teams = list(distributions["teams"].values())
    weeks_used = distributions["weeks_used"]

    hit_table = _render_distribution_table(
        teams,
        sort_key="hit_sd",
        sort_reverse=False,
        columns=[("Mean", lambda t: t["hit_mean"]), ("SD", lambda t: t["hit_sd"])],
        title="Hitting Consistency (low SD = consistent)",
        sd_class_fn=_hit_sd_class,
    )
    pitch_table = _render_distribution_table(
        teams,
        sort_key="pitch_sd",
        sort_reverse=False,
        columns=[("Mean", lambda t: t["pitch_mean"]), ("SD", lambda t: t["pitch_sd"])],
        title="Pitching Consistency (low SD = consistent)",
        sd_class_fn=_pitch_sd_class,
    )
    total_table = _render_distribution_table(
        teams,
        sort_key="total_mean",
        sort_reverse=True,
        columns=[("Mean", lambda t: t["total_mean"]), ("SD", lambda t: t["total_sd"])],
        title="Total Output (mean desc)",
    )

    weeks_label = ", ".join(f"W{w}" for w in weeks_used)
    return f"""
<h3 style="margin-top: 24px;">Season Distributions ({weeks_label})</h3>
<p class="note">Population SD (n, not n-1). Week 1 excluded as a known short-week outlier. Tamp Slam highlighted.</p>
<div class="weekly-grid">
{hit_table}
{pitch_table}
{total_table}
</div>
"""


def _render_my_position(my_summary):
    """Three stat boxes + a one-line summary for my team."""
    if not my_summary:
        return ""
    n = my_summary["n_teams"]
    h = my_summary["hit"]
    p = my_summary["pitch"]
    t = my_summary["total"]

    return f"""
<h3 style="margin-top: 24px;">My Position — {escape(my_summary["team_name"])}</h3>
<div class="stat-boxes">
  <div class="stat-box">
    <div class="label">Hitting Consistency Rank</div>
    <div><span class="rank">#{h["rank"]}</span><span class="of"> / {n}</span></div>
    <div class="detail">μ {h["mean"]:.1f} · SD {h["sd"]:.2f}</div>
  </div>
  <div class="stat-box">
    <div class="label">Pitching Consistency Rank</div>
    <div><span class="rank">#{p["rank"]}</span><span class="of"> / {n}</span></div>
    <div class="detail">μ {p["mean"]:.1f} · SD {p["sd"]:.2f}</div>
  </div>
  <div class="stat-box">
    <div class="label">Total Output Rank</div>
    <div><span class="rank">#{t["rank"]}</span><span class="of"> / {n}</span></div>
    <div class="detail">μ {t["mean"]:.1f}/wk</div>
  </div>
</div>
<p class="summary-line">
  You're <strong>#{h["rank"]}</strong> in hitting consistency (SD {h["sd"]:.2f}),
  <strong>#{p["rank"]}</strong> in pitching consistency (SD {p["sd"]:.2f}),
  and <strong>#{t["rank"]}</strong> in total mean output ({t["mean"]:.1f}/wk).
</p>
"""


def render_section(league_metrics):
    """
    Top-level entry point. Build the full <section>...</section> HTML.

    league_metrics expected shape:
        {
            "current": {"week": int, "results": [team_dict, ...]} | None,
            "most_recent": {"week": int, "results": [team_dict, ...]} | None,
            "distributions": <output of compute_team_distributions>,
            "my_summary": <output of get_my_team_summary>,
            "standings": <output of fetch_standings>,
        }
    """
    if not league_metrics:
        return ""
    parts = []
    stale = league_metrics.get("stale_from")
    if stale:
        parts.append(
            f'<p class="note" style="color:#c62828;">Live Yahoo pull failed this '
            f'morning — showing the last good data from <b>{stale}</b>.</p>'
        )
    standings = league_metrics.get("standings")
    if standings:
        parts.append(_render_standings(standings))
    cur = league_metrics.get("current")
    if cur:
        parts.append(_render_current_week(cur["week"], cur["results"]))
    mr = league_metrics.get("most_recent")
    if mr:
        parts.append(_render_recent_week(mr["week"], mr["results"]))
    dist = league_metrics.get("distributions")
    if dist and dist.get("weeks_used"):
        parts.append(_render_season_distributions(dist))
    my = league_metrics.get("my_summary")
    if my:
        parts.append(_render_my_position(my))
    weeks_data = league_metrics.get("weeks_data")
    if weeks_data:
        parts.append(_render_weekly_charts(weeks_data))
    inner = "\n".join(parts)
    return f"""
<section class="section">
  <h2>League Standings &amp; Distributions</h2>
  {inner}
</section>
"""
