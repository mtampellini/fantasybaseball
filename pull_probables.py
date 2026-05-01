"""
Pull probable starting pitchers from Fangraphs Probables Grid.

Source: https://www.fangraphs.com/roster-resource/probables-grid

The page is a Next.js app that ships its data in a __NEXT_DATA__ script tag.
We don't need to run JS — just parse the JSON blob server-side.

Fangraphs returns ~16 days of probables (roughly 2 fantasy weeks).
"""

import requests
import re
import json
from datetime import datetime, timedelta, date
from collections import defaultdict

from utils import normalize_name


FANGRAPHS_URL = "https://www.fangraphs.com/roster-resource/probables-grid"

REQUEST_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) Fantasy-Tracker/1.0",
    "Accept": "text/html,application/xhtml+xml",
}


def fetch_probables_grid():
    """
    Pull all probables for the next ~16 days.

    Returns: list of dicts, one per scheduled game:
        {
            "team": "LAD",
            "team_id": 22,
            "opponent": "HOU",
            "opponent_id": 21,
            "date": "2026-05-06",
            "is_home": False,
            "pitcher_name": "Tyler Glasnow",
            "pitcher_id": "607192",
            "throws": "R",
            "doubleheader": 0,
            "notes": None,
        }
    """
    r = requests.get(FANGRAPHS_URL, headers=REQUEST_HEADERS, timeout=30)
    r.raise_for_status()

    match = re.search(
        r'<script id="__NEXT_DATA__"[^>]*>([\s\S]*?)</script>',
        r.text,
    )
    if not match:
        raise RuntimeError("Fangraphs page format changed - no __NEXT_DATA__ found")

    next_data = json.loads(match.group(1))
    queries = (next_data.get("props", {})
               .get("pageProps", {})
               .get("dehydratedState", {})
               .get("queries", []))

    grid_data = None
    for q in queries:
        if q.get("queryKey") == ["roster-resource/probables-grid/data"]:
            grid_data = q.get("state", {}).get("data")
            break

    if not grid_data:
        raise RuntimeError("Probables grid data missing from dehydrated state")

    # grid_data may be a list (server response) or dict (cached values)
    entries = grid_data.values() if isinstance(grid_data, dict) else grid_data

    games = []
    for entry in entries:
        games.append({
            "team": entry.get("AbbName"),
            "team_id": entry.get("TeamId"),
            "opponent": entry.get("OpponentAbbName"),
            "opponent_id": entry.get("OpponentId"),
            "date": (entry.get("GameDate") or "")[:10],
            "is_home": bool(entry.get("isHome")),
            "pitcher_name": entry.get("teamSPPlayerName"),
            "pitcher_id": str(entry.get("teamSPPlayerId")) if entry.get("teamSPPlayerId") else None,
            "throws": entry.get("Throws"),
            "doubleheader": entry.get("dh", 0),
            "notes": entry.get("notes"),
        })
    return games


def starts_by_pitcher(games):
    """
    Reorganize raw games list into a dict keyed by normalized pitcher name.

    Returns: {normalized_name: [game_dict, ...]} sorted by date asc.
    """
    by_pitcher = defaultdict(list)
    for g in games:
        if not g.get("pitcher_name"):
            continue
        norm = normalize_name(g["pitcher_name"])
        by_pitcher[norm].append(g)
    # Sort each pitcher's starts by date
    for norm in by_pitcher:
        by_pitcher[norm].sort(key=lambda x: x["date"])
    return dict(by_pitcher)


def count_team_games_in_window(games, start_date, end_date):
    """
    Count scheduled MLB games per team in the given date window.

    Each entry in `games` is one team's perspective of a single contest
    (team's SP + opponent), so a 1-vs-1 game produces 2 entries — one
    keyed under each team. We count entries by `team` field, which gives
    us exactly one count per team per game (doubleheaders correctly
    produce 2 entries per team).

    Returns: {team_abbr: int}
    """
    if isinstance(start_date, datetime):
        start_date = start_date.date()
    if isinstance(end_date, datetime):
        end_date = end_date.date()
    counts = defaultdict(int)
    for g in games:
        d = g.get("date")
        if not d:
            continue
        try:
            gd = datetime.strptime(d, "%Y-%m-%d").date()
        except ValueError:
            continue
        if start_date <= gd <= end_date:
            t = g.get("team")
            if t:
                counts[t] += 1
    return dict(counts)


def filter_to_date_range(games, start_date, end_date):
    """Filter a list of games to a date range (inclusive)."""
    if isinstance(start_date, datetime):
        start_date = start_date.date()
    if isinstance(end_date, datetime):
        end_date = end_date.date()

    out = []
    for g in games:
        if not g.get("date"):
            continue
        try:
            gd = datetime.strptime(g["date"], "%Y-%m-%d").date()
        except ValueError:
            continue
        if start_date <= gd <= end_date:
            out.append(g)
    return out


def get_fantasy_week_bounds(today=None):
    """
    Get this week's and next week's start/end dates.
    Yahoo fantasy weeks run Monday → Sunday.

    Returns: (this_week_start, this_week_end, next_week_start, next_week_end)
    All as date objects.
    """
    if today is None:
        today = date.today()
    elif isinstance(today, datetime):
        today = today.date()

    # Days since Monday (0=Mon, 6=Sun)
    days_since_monday = today.weekday()
    this_start = today - timedelta(days=days_since_monday)
    this_end = this_start + timedelta(days=6)
    next_start = this_end + timedelta(days=1)
    next_end = next_start + timedelta(days=6)
    return this_start, this_end, next_start, next_end


if __name__ == "__main__":
    games = fetch_probables_grid()
    print(f"Pulled {len(games)} probable starts")

    by_pitcher = starts_by_pitcher(games)
    print(f"\n{len(by_pitcher)} unique pitchers")

    print("\nGlasnow starts:")
    for g in by_pitcher.get("tyler glasnow", []):
        loc = "vs" if g["is_home"] else "@"
        print(f"  {g['date']} {loc} {g['opponent']}")

    ts, te, ns, ne = get_fantasy_week_bounds()
    print(f"\nThis week: {ts} → {te}")
    print(f"Next week: {ns} → {ne}")
