"""
Pull per-week, per-team hitting/pitching/total point totals from Yahoo.

Approach
--------
1. Read the league's stat_categories + stat_modifiers once. This gives us:
     stat_id -> position_type ('B' or 'P')
     stat_id -> point modifier (e.g. HR = 4.0 points)

2. For each week, call league.matchups(week). The response includes
   team_stats (raw stat values per team) and team_points.total
   (authoritative weekly total). We compute hit_points by summing
   B-type stats * modifiers, then derive pitch_points = total - hit
   to avoid IP-as-thirds rounding drift on the pitching side.

3. Cache each week to data/weekly/{week}.json. Past weeks are immutable;
   the current week is re-fetched every run.

Output of fetch_week_results(week):
    [
        {
            "team_id": 11,
            "team_name": "Tamp Slam",
            "hitting": 271.0,
            "pitching": 189.59,
            "total": 460.59,
            "week": 5,
        },
        ...  # 14 entries
    ]
"""

import json
from pathlib import Path

from pull_yahoo import get_league


CACHE_DIR = Path(__file__).parent / "data" / "weekly"


def _build_scoring_maps(league):
    """
    Returns (stat_pos, stat_val) where:
        stat_pos[stat_id] = 'B' or 'P'
        stat_val[stat_id] = float point modifier
    """
    raw = league.yhandler.get_settings_raw(league.league_id)

    def find_first(obj, key):
        if isinstance(obj, dict):
            for k, v in obj.items():
                if k == key:
                    return v
                r = find_first(v, key)
                if r is not None:
                    return r
        elif isinstance(obj, list):
            for v in obj:
                r = find_first(v, key)
                if r is not None:
                    return r
        return None

    cats = find_first(raw, "stat_categories")
    mods = find_first(raw, "stat_modifiers")

    stat_pos = {}
    for c in cats["stats"]:
        s = c["stat"]
        stat_pos[int(s["stat_id"])] = s["position_type"]

    stat_val = {}
    for m in mods["stats"]:
        s = m["stat"]
        try:
            stat_val[int(s["stat_id"])] = float(s["value"])
        except (ValueError, TypeError):
            continue

    return stat_pos, stat_val


def _extract_team_meta(team_data):
    """team_data[0] is a list of dicts with team_key, team_id, name, etc."""
    team_key = None
    team_id = None
    team_name = None
    for piece in team_data[0]:
        if not isinstance(piece, dict):
            continue
        if "team_key" in piece:
            team_key = piece["team_key"]
        if "team_id" in piece:
            try:
                team_id = int(piece["team_id"])
            except (ValueError, TypeError):
                team_id = piece["team_id"]
        if "name" in piece:
            team_name = piece["name"]
    return team_key, team_id, team_name


def _team_results_from_matchup(team_data, stat_pos, stat_val, week):
    """Extract one team's results from a matchup teams entry."""
    team_key, team_id, team_name = _extract_team_meta(team_data)
    stats = team_data[1].get("team_stats", {}).get("stats", [])
    points = team_data[1].get("team_points", {})
    total_str = points.get("total")
    try:
        total = float(total_str) if total_str is not None else None
    except (ValueError, TypeError):
        total = None

    hit_pts = 0.0
    for s in stats:
        sid = int(s["stat"]["stat_id"])
        try:
            val = float(s["stat"]["value"])
        except (ValueError, TypeError):
            continue
        mod = stat_val.get(sid)
        pos = stat_pos.get(sid)
        if mod is None or pos is None:
            continue
        if pos == "B":
            hit_pts += val * mod

    if total is None:
        # Fallback: no API total, sum pitching stats directly
        pitch_pts = 0.0
        for s in stats:
            sid = int(s["stat"]["stat_id"])
            try:
                val = float(s["stat"]["value"])
            except (ValueError, TypeError):
                continue
            mod = stat_val.get(sid)
            pos = stat_pos.get(sid)
            if mod is None or pos is None or pos != "P":
                continue
            pitch_pts += val * mod
        total = round(hit_pts + pitch_pts, 2)
    else:
        pitch_pts = round(total - hit_pts, 2)

    return {
        "team_id": team_id,
        "team_name": team_name,
        "hitting": round(hit_pts, 2),
        "pitching": pitch_pts,
        "total": round(total, 2),
        "week": week,
    }


def _fetch_from_api(league, week, stat_pos, stat_val):
    """Pull all 7 matchups in `week`, return 14 team result dicts."""
    m = league.matchups(week=week)
    matchups = m["fantasy_content"]["league"][1]["scoreboard"]["0"]["matchups"]
    count = int(matchups.get("count", 0))
    out = []
    for i in range(count):
        mu = matchups[str(i)]["matchup"]
        teams = mu["0"]["teams"]
        for j in ("0", "1"):
            out.append(_team_results_from_matchup(teams[j]["team"], stat_pos, stat_val, week))
    return out


def fetch_week_results(week, force=False, league=None, scoring=None):
    """
    Get all 14 teams' results for one week.

    Reads from data/weekly/{week}.json if available (and not forced).
    Otherwise pulls from Yahoo and caches.
    """
    cache_path = CACHE_DIR / f"{week}.json"
    if cache_path.exists() and not force:
        return json.loads(cache_path.read_text())

    if league is None:
        league = get_league()
    if scoring is None:
        stat_pos, stat_val = _build_scoring_maps(league)
    else:
        stat_pos, stat_val = scoring

    results = _fetch_from_api(league, week, stat_pos, stat_val)
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    cache_path.write_text(json.dumps(results, indent=2))
    return results


def get_completed_weeks(league=None):
    """
    Return the list of week numbers that are fully completed.

    Yahoo's `current_week` is the in-progress week, so completed weeks
    are 1..current_week - 1.
    """
    if league is None:
        league = get_league()
    cw = league.current_week()
    if cw <= 1:
        return []
    return list(range(1, int(cw)))


def fetch_all_weeks(through_week=None, league=None):
    """
    Pull every completed week (using cache where possible) plus the
    current week (always re-fetched). Returns a list of week dicts.

    Each entry: {"week": int, "results": [team_dict, ...]}
    """
    if league is None:
        league = get_league()
    scoring = _build_scoring_maps(league)
    completed = get_completed_weeks(league)
    current = league.current_week()
    weeks = list(completed)
    if through_week is not None:
        weeks = [w for w in weeks if w <= through_week]
    # Yahoo continues posting stat corrections for ~1-2 days after a week ends,
    # so the most recently completed week (current_week - 1) gets re-fetched
    # too. Earlier weeks are immutable and read from cache.
    prior_week = int(current) - 1
    out = []
    for w in weeks:
        force = (w == prior_week)
        out.append({"week": w, "results": fetch_week_results(w, force=force, league=league, scoring=scoring)})
    # Always re-fetch current week (in progress) so partial standings refresh
    if (through_week is None or current <= through_week) and current >= 1:
        out.append({
            "week": int(current),
            "results": fetch_week_results(int(current), force=True, league=league, scoring=scoring),
            "in_progress": True,
        })
    return out


def fetch_standings(league=None):
    """
    Pull league standings + per-team metadata (waiver, moves).

    Returns: list of dicts, sorted by Yahoo's rank ascending:
        {
            "team_id": int,
            "team_name": str,
            "rank": int,
            "wins": int, "losses": int, "ties": int, "win_pct": float,
            "games_back": str,  # "-" for leader, otherwise float as str
            "points_for": float,
            "points_against": float,
            "waiver_priority": int,
            "moves": int,
            "trades": int,
        }
    """
    if league is None:
        league = get_league()
    standings = league.standings()
    teams = league.teams()  # team_key -> team meta

    out = []
    for s in standings:
        tk = s.get("team_key")
        meta = teams.get(tk, {}) if isinstance(teams, dict) else {}
        try:
            team_id = int(tk.rsplit(".", 1)[-1])
        except (ValueError, AttributeError):
            team_id = None
        ot = s.get("outcome_totals", {})

        def _to_int(v, default=0):
            try:
                return int(v)
            except (ValueError, TypeError):
                return default

        def _to_float(v, default=0.0):
            try:
                return float(v)
            except (ValueError, TypeError):
                return default

        out.append({
            "team_id": team_id,
            "team_name": s.get("name"),
            "rank": _to_int(s.get("rank")),
            "wins": _to_int(ot.get("wins")),
            "losses": _to_int(ot.get("losses")),
            "ties": _to_int(ot.get("ties")),
            "win_pct": _to_float(ot.get("percentage")),
            "games_back": s.get("games_back", "-"),
            "points_for": _to_float(s.get("points_for")),
            "points_against": _to_float(s.get("points_against")),
            "waiver_priority": _to_int(meta.get("waiver_priority")),
            "moves": _to_int(meta.get("number_of_moves")),
            "trades": _to_int(meta.get("number_of_trades")),
        })
    out.sort(key=lambda r: r["rank"])
    return out


if __name__ == "__main__":
    league = get_league()
    print(f"Current week: {league.current_week()}")
    print(f"Completed weeks: {get_completed_weeks(league)}")
    print()
    print("Week 5 results:")
    for r in fetch_week_results(5, force=True, league=league):
        print(f"  t.{r['team_id']:>2} {r['team_name']:<18} "
              f"hit={r['hitting']:>6.2f}  pitch={r['pitching']:>6.2f}  total={r['total']:>7.2f}")
