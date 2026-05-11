"""
Fetch every team's roster in league 41657 via Yahoo API and dump to
data/rosters.json so league_compare.py can do the team-vs-team analysis.

Usage:
    python -m src.fetch_all_rosters
"""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

import requests
from yahoo_oauth import OAuth2
import yahoo_fantasy_api as yfa


ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "data" / "rosters.json"

LEAGUE_ID = "41657"
DEFAULT_OAUTH = r"C:\Users\mtamp\Documents\Fantasy Baseball\fantasybaseball\oauth2.json"
REDIRECT_URI = "https://oauth.pstmn.io/v1/callback"
TOKEN_URL = "https://api.login.yahoo.com/oauth2/get_token"

# League team mapping (from C:\Users\mtamp\config.py)
LEAGUE_TEAMS = {
    1: "Pine Barrens", 2: "Balcony Tears", 3: "Chicks Dig",
    4: "Diamond Dogs", 5: "Rayhood", 6: "KING JULIAN",
    7: "LB Jefes", 8: "Mama's Juiced", 9: "Soto Shuffle",
    10: "South Park Cows", 11: "Tamp Slam", 12: "SS Express",
    13: "Wally Cats", 14: "Short Porchers",
}


def _refresh(oauth_file: Path) -> None:
    creds = json.loads(oauth_file.read_text())
    if "refresh_token" not in creds or time.time() - creds.get("token_time", 0) < 3300:
        return
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
    resp.raise_for_status()
    data = resp.json()
    creds["access_token"] = data["access_token"]
    creds["token_time"] = time.time()
    if data.get("refresh_token"):
        creds["refresh_token"] = data["refresh_token"]
    creds["token_type"] = data.get("token_type", "bearer")
    oauth_file.write_text(json.dumps(creds, indent=2))


def main() -> int:
    oauth_path = Path(os.environ.get("YAHOO_OAUTH_FILE", DEFAULT_OAUTH))
    if not oauth_path.exists():
        print(f"ERROR: oauth file not found at {oauth_path}", file=sys.stderr)
        return 2
    _refresh(oauth_path)
    sess = OAuth2(None, None, from_file=str(oauth_path))
    gm = yfa.Game(sess, "mlb")
    league_key = f"{gm.game_id()}.l.{LEAGUE_ID}"
    league = gm.to_league(league_key)

    out = {"league_id": LEAGUE_ID, "fetched_at": time.strftime("%Y-%m-%dT%H:%M:%S"), "teams": {}}
    for tid, tname in LEAGUE_TEAMS.items():
        team_key = f"{league_key}.t.{tid}"
        print(f"  fetching team {tid} {tname}...", file=sys.stderr)
        try:
            roster = league.to_team(team_key).roster()
        except Exception as e:
            print(f"    fail: {e}", file=sys.stderr)
            continue
        # Normalize: just keep name + positions + selected_pos + status
        slim = []
        for p in roster:
            slim.append({
                "name": p.get("name"),
                "player_id": p.get("player_id"),
                "eligible_positions": p.get("eligible_positions", []),
                "selected_position": p.get("selected_position"),
                "status": p.get("status", ""),
            })
        out["teams"][str(tid)] = {"name": tname, "players": slim}

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(out, indent=2))
    print(f"Wrote {OUT}")
    # Quick summary
    for tid in LEAGUE_TEAMS:
        team = out["teams"].get(str(tid))
        if not team:
            continue
        sps = [
            p["name"]
            for p in team["players"]
            if "SP" in (p.get("eligible_positions") or [])
        ]
        print(f"  {tid:>2}  {team['name']:25s}  {len(sps)} SPs")
    return 0


if __name__ == "__main__":
    sys.exit(main())
