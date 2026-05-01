"""
Pull per-start xwOBA from Baseball Savant.

Endpoint:
    /player-services/statcast-pitches-breakdown
        ?playerId=...&position=1&pitchBreakdown=pitches
        &timeFrame=game&updatePitches=false

Response is HTML containing a <script> with:
    window.serverVals.pitchDetails = [...per-pitch-type-per-game rows...]

We aggregate by game_date, weighted by PA, to get the per-start xwOBA
that matches what's displayed in Savant's player page Pitch Tracking
section under "All Pitches" + "Game" timeframe.
"""

import requests
import re
import json
from collections import defaultdict


PLAYER_SERVICES_URL = (
    "https://baseballsavant.mlb.com/player-services/statcast-pitches-breakdown"
)

REQUEST_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) Fantasy-Tracker/1.0"
}


def fetch_per_start_xwoba(player_id, season=2026, num_starts=5):
    """
    Pull per-start xwOBA for a single pitcher.

    Args:
        player_id: MLB player ID (e.g., "607192" for Glasnow)
        season: year to filter to (default 2026)
        num_starts: number of most-recent starts to return

    Returns: list of dicts, most recent first:
        [
            {"date": "2026-04-23", "pa": 25, "xwoba": 0.143, "woba": 0.064},
            ...
        ]
    """
    if not player_id:
        return []

    params = {
        "playerId": player_id,
        "position": 1,
        "pitchBreakdown": "pitches",
        "timeFrame": "game",
        "updatePitches": "false",
    }

    try:
        r = requests.get(PLAYER_SERVICES_URL, params=params,
                         headers=REQUEST_HEADERS, timeout=20)
        r.raise_for_status()
    except requests.RequestException:
        return []

    # The response is a <script> blob with pitchDetails array
    match = re.search(r"pitchDetails\s*=\s*(\[[\s\S]*?\])", r.text)
    if not match:
        return []

    try:
        rows = json.loads(match.group(1))
    except json.JSONDecodeError:
        return []

    # Aggregate per pitch-type per game → all-pitches per game
    games = defaultdict(lambda: {"pa": 0, "xwoba_w": 0.0, "woba_w": 0.0})
    season_str = str(season)

    for row in rows:
        date = row.get("game_date", "")
        if not date or not date.startswith(season_str):
            continue
        try:
            pa = int(row.get("pa") or 0)
            xwoba = float(row.get("xwoba") or 0)
            woba = float(row.get("woba") or 0)
        except (ValueError, TypeError):
            continue

        if pa <= 0:
            continue

        games[date]["pa"] += pa
        games[date]["xwoba_w"] += xwoba * pa
        games[date]["woba_w"] += woba * pa

    # Sort by date desc, take top N
    sorted_games = sorted(games.items(), key=lambda kv: kv[0], reverse=True)
    sorted_games = sorted_games[:num_starts]

    out = []
    for date, g in sorted_games:
        if g["pa"] > 0:
            out.append({
                "date": date,
                "pa": g["pa"],
                "xwoba": round(g["xwoba_w"] / g["pa"], 3),
                "woba": round(g["woba_w"] / g["pa"], 3),
            })
    return out


def compute_per_start_sd(per_start_list):
    """Population SD of xwOBA across the starts."""
    if not per_start_list or len(per_start_list) < 2:
        return None
    vals = [s["xwoba"] for s in per_start_list if s.get("xwoba") is not None]
    if len(vals) < 2:
        return None
    n = len(vals)
    mean = sum(vals) / n
    var = sum((v - mean) ** 2 for v in vals) / n
    return round(var ** 0.5, 3)


if __name__ == "__main__":
    print("Glasnow per-start xwOBA:")
    starts = fetch_per_start_xwoba("607192")
    for s in starts:
        print(f"  {s['date']}: xwOBA {s['xwoba']:.3f} ({s['pa']} PA)")
    print(f"  SD: {compute_per_start_sd(starts)}")
