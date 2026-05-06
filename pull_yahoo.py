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
    Pull available players (free agents + waivers) for a position group,
    sorted by season fantasy points desc, falling back to ownership.

    Yahoo splits availability into two buckets: `free_agents` (no claim
    pending) and `waivers` (a claim is pending). A hot recent call-up
    can sit on waivers for days and never appear in `free_agents` —
    so we merge both lists to keep them eligible candidates.

    Returns: list of dicts with:
        {
            "name": "Kyle Harrison",
            "player_id": 12345,
            "team": "MIL",
            "eligible_positions": ["SP", "RP"],
            "status": "",
            "percent_owned": 35,
            "fantasy_points": 68.92,
            "on_waivers": False,
        }
    """
    league = get_league()
    fas = league.free_agents(position)
    waivers = league.waivers()
    # Filter waivers to the requested position group
    if position == "B":
        waivers = [w for w in waivers if w.get("position_type") == "B"]
    elif position == "P":
        waivers = [w for w in waivers if w.get("position_type") == "P"]
    else:
        waivers = [w for w in waivers if position in (w.get("eligible_positions") or [])]

    seen = set()
    combined = []
    for f in fas:
        pid = f.get("player_id")
        if pid in seen:
            continue
        seen.add(pid)
        combined.append((f, False))
    for w in waivers:
        pid = w.get("player_id")
        if pid in seen:
            continue
        seen.add(pid)
        combined.append((w, True))

    def sort_key(item):
        p = item[0]
        return -(p.get("fantasy_points") or p.get("percent_owned") or 0)

    combined.sort(key=sort_key)
    out = []
    for fa, is_waiver in combined[:count * 2]:
        out.append({
            "name": fa.get("name"),
            "player_id": fa.get("player_id"),
            "team": fa.get("editorial_team_abbr") or fa.get("team"),
            "eligible_positions": fa.get("eligible_positions", []),
            "status": fa.get("status", ""),
            "percent_owned": fa.get("percent_owned"),
            "fantasy_points": fa.get("fantasy_points"),
            "on_waivers": is_waiver,
        })
        if len(out) >= count:
            break
    return out


def fetch_yahoo_stats(player_ids, range_type="lastmonth"):
    """
    Fetch raw stats for `range_type` ('lastweek', 'lastmonth', etc.).

    A single invalid player_id in a batch causes Yahoo to reject the whole
    batch, so on chunk failure we fall back to per-player calls and skip
    only the bad IDs.

    Returns: {player_id: stats_dict_from_yahoo}
    """
    if not player_ids:
        return {}
    league = get_league()
    out = {}

    def absorb(rows):
        for r in rows:
            pid = r.get("player_id")
            if pid is None:
                continue
            out[pid] = r

    ids = list(player_ids)
    chunk_fail = 0
    pid_fail = 0
    first_err = None
    for i in range(0, len(ids), 25):
        chunk = ids[i:i + 25]
        try:
            absorb(league.player_stats(chunk, range_type))
        except Exception as e:
            chunk_fail += 1
            if first_err is None:
                first_err = f"{type(e).__name__}: {e}"
            for pid in chunk:
                try:
                    absorb(league.player_stats([pid], range_type))
                except Exception:
                    pid_fail += 1
                    continue
    if chunk_fail or pid_fail:
        print(f"  WARN: yahoo player_stats({range_type}) had {chunk_fail} chunk failures, "
              f"{pid_fail} per-player failures (first error: {first_err})")
    return out


def fetch_last_month_fp(player_ids):
    """Returns {player_id: total_points} from Yahoo's lastmonth stat type."""
    raw = fetch_yahoo_stats(player_ids, "lastmonth")
    out = {}
    for pid, s in raw.items():
        tp = s.get("total_points")
        if tp is None:
            continue
        try:
            out[pid] = float(tp)
        except (ValueError, TypeError):
            continue
    return out


def parse_pa_from_yahoo_stats(s):
    """Extract estimated PA from a Yahoo player_stats response.

    Yahoo's stats endpoint exposes H/AB ('21/104') and BB. PA = AB + BB
    (HBP/SF aren't included in this scope, so we under-count by ~3-5%).
    """
    h_ab = s.get("H/AB", "")
    ab = 0
    if isinstance(h_ab, str) and "/" in h_ab:
        try:
            ab = int(h_ab.split("/")[1])
        except (ValueError, IndexError):
            ab = 0
    bb = 0
    for key in ("BB", "Walks"):
        if key in s:
            try:
                bb = int(float(s[key]))
            except (ValueError, TypeError):
                bb = 0
            break
    return ab + bb


def fetch_last_week_stats(player_ids):
    """
    Returns {player_id: {"fp_1w": float, "ab": int, "bb": int, "pa": int}}.
    Used both as a recency signal and to filter hitters by recent plate
    appearances. `pa` = ab + bb (HBP/SF aren't exposed in this endpoint).
    """
    raw = fetch_yahoo_stats(player_ids, "lastweek")
    out = {}
    for pid, s in raw.items():
        try:
            tp = float(s.get("total_points") or 0)
        except (ValueError, TypeError):
            tp = 0.0
        h_ab = s.get("H/AB", "")
        ab = 0
        if isinstance(h_ab, str) and "/" in h_ab:
            try:
                ab = int(h_ab.split("/")[1])
            except (ValueError, IndexError):
                ab = 0
        bb = 0
        for key in ("BB", "Walks"):
            if key in s:
                try:
                    bb = int(float(s[key]))
                except (ValueError, TypeError):
                    bb = 0
                break
        out[pid] = {"fp_1w": tp, "ab": ab, "bb": bb, "pa": ab + bb}
    return out


def fetch_all_rostered_hitters():
    """
    Iterate every team in the league and return rostered hitters with
    owner info attached. Used to build a full-league xFP leaderboard
    (taken_players() exists but doesn't expose ownership).

    Returns: list of dicts:
        {
            name, player_id, team, eligible_positions, status,
            position_type='B', percent_owned,
            owner_team_id, owner_team_name,
        }
    """
    league = get_league()
    teams_dict = league.teams()  # team_key -> meta dict
    out = []
    for team_key, team_meta in teams_dict.items():
        if not isinstance(team_meta, dict):
            continue
        team_name = team_meta.get("name", "")
        try:
            owner_team_id = int(team_key.rsplit(".", 1)[-1])
        except (ValueError, AttributeError):
            owner_team_id = None
        try:
            roster = league.to_team(team_key).roster()
        except Exception as e:
            print(f"  WARN: roster pull failed for {team_name}: {e}")
            continue
        for r in roster:
            if r.get("position_type") != "B":
                continue
            out.append({
                "name": r.get("name"),
                "player_id": r.get("player_id"),
                "team": r.get("editorial_team_abbr") or "",
                "eligible_positions": r.get("eligible_positions", []),
                "status": r.get("status", ""),
                "position_type": "B",
                "owner_team_id": owner_team_id,
                "owner_team_name": team_name,
            })
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
