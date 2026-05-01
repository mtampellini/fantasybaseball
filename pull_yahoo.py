"""
Pull Yahoo Fantasy Baseball data: my roster, free agent wire, matchup info.

Uses the `yahoo_fantasy_api` library which wraps Yahoo's Fantasy Sports API.
Authentication is OAuth2 with a refresh token stored in oauth2.json.

ONE-TIME SETUP (run setup_oauth.py once):
  1. Register an app at developer.yahoo.com (callback URL: oob)
  2. Save Client ID + Secret in oauth2.json
  3. First run will open browser for manual OAuth consent
  4. Token refreshes automatically thereafter

Useful resources:
  https://github.com/spilchen/yahoo_fantasy_api
"""

import os
import json
import time
from pathlib import Path

import requests
from yahoo_oauth import OAuth2
import yahoo_fantasy_api as yfa

from config import YAHOO_LEAGUE_ID, YAHOO_TEAM_ID, FA_PITCHER_COUNT, FA_HITTER_COUNT


OAUTH_FILE = os.environ.get("YAHOO_OAUTH_FILE", "oauth2.json")
# Must match the Redirect URI registered with the Yahoo Developer App.
REDIRECT_URI = "https://oauth.pstmn.io/v1/callback"
TOKEN_URL = "https://api.login.yahoo.com/oauth2/get_token"


def _maybe_refresh_token():
    """
    Refresh the access token if older than ~55 minutes.

    The yahoo_oauth library hardcodes `redirect_uri=oob` in its refresh call,
    which Yahoo rejects when the app is registered with a different URI. So
    we do the refresh ourselves with the correct redirect_uri and overwrite
    oauth2.json before yahoo_oauth ever sees it.
    """
    path = Path(OAUTH_FILE)
    creds = json.loads(path.read_text())
    if "refresh_token" not in creds:
        return  # nothing to refresh with; will fall through to bootstrap
    age = time.time() - creds.get("token_time", 0)
    if age < 3300:
        return  # token still has > 5 min of life
    print(f"  Refreshing Yahoo access token (current is {age:.0f}s old)")
    resp = requests.post(
        TOKEN_URL,
        data={
            "grant_type": "refresh_token",
            "refresh_token": creds["refresh_token"],
            "redirect_uri": REDIRECT_URI,
        },
        auth=(creds["consumer_key"], creds["consumer_secret"]),
        headers={"Accept": "application/json"},
        timeout=30,
    )
    if resp.status_code != 200:
        raise RuntimeError(f"Yahoo refresh failed {resp.status_code}: {resp.text}")
    data = resp.json()
    creds["access_token"] = data["access_token"]
    creds["token_time"] = time.time()
    if data.get("refresh_token"):
        creds["refresh_token"] = data["refresh_token"]
    creds["token_type"] = data.get("token_type", "bearer")
    path.write_text(json.dumps(creds, indent=2))


def get_session():
    """Get an authenticated OAuth2 session, refreshing token if needed."""
    _maybe_refresh_token()
    return OAuth2(None, None, from_file=OAUTH_FILE)


def get_league(sess=None):
    """Get the League object for our league."""
    if sess is None:
        sess = get_session()
    gm = yfa.Game(sess, "mlb")
    league_key = f"{gm.game_id()}.l.{YAHOO_LEAGUE_ID}"
    return gm.to_league(league_key)


def fetch_my_roster():
    """
    Pull current roster.

    Returns: list of dicts:
        [
            {
                "name": "Cal Raleigh",
                "player_id": 12345,
                "selected_position": "C",
                "eligible_positions": ["C"],
                "status": "",  # "DTD", "IL10", "IL60", "NA", or ""
                "position_type": "B",  # B for batter, P for pitcher
            },
            ...
        ]
    """
    league = get_league()
    team = league.to_team(f"{league.league_id}.t.{YAHOO_TEAM_ID}")
    roster_raw = team.roster()
    out = []
    for r in roster_raw:
        out.append({
            "name": r.get("name"),
            "player_id": r.get("player_id"),
            "team": r.get("editorial_team_abbr") or "",
            "selected_position": r.get("selected_position"),
            "eligible_positions": r.get("eligible_positions", []),
            "status": r.get("status", ""),
            "position_type": r.get("position_type"),
        })
    return out


def fetch_free_agents(position, count=30):
    """
    Pull free agents for a position group, sorted by season fantasy points desc.

    Args:
        position: "B" for all batters, "P" for all pitchers,
                  or specific like "SP", "RP", "1B", "OF", etc.
        count: how many to return

    Returns: list of dicts with:
        {
            "name": "Kyle Harrison",
            "player_id": 12345,
            "team": "MIL",
            "eligible_positions": ["SP", "RP"],
            "status": "",
            "percent_owned": 35,
            "fantasy_points": 68.92,
        }
    """
    league = get_league()
    fas = league.free_agents(position)

    # Sort by fantasy points desc if available, else AR
    def sort_key(p):
        return -(p.get("fantasy_points") or p.get("percent_owned") or 0)

    fas_sorted = sorted(fas, key=sort_key)
    out = []
    for fa in fas_sorted[:count * 2]:  # pull extra to filter then trim
        out.append({
            "name": fa.get("name"),
            "player_id": fa.get("player_id"),
            "team": fa.get("editorial_team_abbr") or fa.get("team"),
            "eligible_positions": fa.get("eligible_positions", []),
            "status": fa.get("status", ""),
            "percent_owned": fa.get("percent_owned"),
            "fantasy_points": fa.get("fantasy_points"),
        })
        if len(out) >= count:
            break
    return out


def fetch_last_month_fp(player_ids):
    """
    Fetch fantasy points over the last 30 days for given player IDs.

    Yahoo's `lastmonth` stat type returns the trailing 30-day window. The
    points league exposes a `total_points` field directly.

    A single invalid player_id in a batch causes Yahoo to reject the whole
    batch, so on chunk failure we fall back to per-player calls and skip
    only the bad IDs.

    Returns: { player_id: float, ... }  (missing players silently dropped)
    """
    if not player_ids:
        return {}
    league = get_league()
    out = {}

    def absorb(rows):
        for r in rows:
            pid = r.get("player_id")
            tp = r.get("total_points")
            if pid is not None and tp is not None:
                out[pid] = float(tp)

    ids = list(player_ids)
    for i in range(0, len(ids), 25):
        chunk = ids[i:i + 25]
        try:
            absorb(league.player_stats(chunk, "lastmonth"))
        except Exception:
            # Batch failed — retry one at a time so good IDs still resolve
            for pid in chunk:
                try:
                    absorb(league.player_stats([pid], "lastmonth"))
                except Exception:
                    continue
    return out


def fetch_current_matchup():
    """
    Get this week's matchup info.

    Returns:
        {
            "week": 6,
            "my_score": {"hit": 0, "pitch": 0, "total": 0},
            "opp_team_id": 5,
            "opp_team_name": "Rayhood",
            "opp_score": {"hit": 0, "pitch": 0, "total": 0},
        }
    """
    league = get_league()
    week = league.current_week()
    matchup = league.matchups(week=week)

    # The matchup data structure varies; we just want our team's matchup
    # and basic counterparty info. The lib gives us a nested dict.
    # Walk it to find our team_id.
    return {
        "week": week,
        "raw": matchup,  # Keep raw for now; refine after first live pull
    }


if __name__ == "__main__":
    print("Pulling roster...")
    roster = fetch_my_roster()
    for p in roster:
        print(f"  {p['selected_position']:>4} | {p['name']} ({p['status'] or 'OK'})")

    print(f"\nPulling top {FA_PITCHER_COUNT} FA pitchers...")
    fa_p = fetch_free_agents("P", FA_PITCHER_COUNT)
    for p in fa_p[:10]:
        print(f"  {p['name']} ({p['team']}) - {p['fantasy_points']} FP")

    print(f"\nPulling top {FA_HITTER_COUNT} FA hitters...")
    fa_h = fetch_free_agents("B", FA_HITTER_COUNT)
    for p in fa_h[:10]:
        print(f"  {p['name']} ({p['team']}) - {p['fantasy_points']} FP")
