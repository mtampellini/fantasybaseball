"""
One-off: pull stat_categories + stat_modifiers from Yahoo for league 41657
and dump to data/scoring.json so the rest of the project doesn't need OAuth.

Usage:
    python -m src.fetch_scoring

Assumes oauth2.json exists. Defaults to the home-dir repo's copy at
C:\\Users\\mtamp\\Documents\\Fantasy Baseball\\fantasybaseball\\oauth2.json
unless YAHOO_OAUTH_FILE env var is set.
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


LEAGUE_ID = "41657"
DEFAULT_OAUTH = r"C:\Users\mtamp\Documents\Fantasy Baseball\fantasybaseball\oauth2.json"
OUT_PATH = Path(__file__).resolve().parents[1] / "data" / "scoring.json"
REDIRECT_URI = "https://oauth.pstmn.io/v1/callback"
TOKEN_URL = "https://api.login.yahoo.com/oauth2/get_token"


def _refresh(oauth_file: Path) -> None:
    creds = json.loads(oauth_file.read_text())
    if "refresh_token" not in creds:
        return
    age = time.time() - creds.get("token_time", 0)
    if age < 3300:
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


def _find_first(node, key):
    if isinstance(node, dict):
        if key in node:
            return node[key]
        for v in node.values():
            r = _find_first(v, key)
            if r is not None:
                return r
    elif isinstance(node, list):
        for v in node:
            r = _find_first(v, key)
            if r is not None:
                return r
    return None


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
    raw = league.yhandler.get_settings_raw(league.league_id)

    cats = _find_first(raw, "stat_categories")
    mods = _find_first(raw, "stat_modifiers")
    if cats is None or mods is None:
        print("ERROR: could not locate stat_categories / stat_modifiers in response", file=sys.stderr)
        return 3

    # Build: stat_id -> {name, display_name, position_type, value}
    by_id: dict[int, dict] = {}
    for c in cats["stats"]:
        s = c["stat"]
        sid = int(s["stat_id"])
        by_id[sid] = {
            "stat_id": sid,
            "name": s.get("name"),
            "display_name": s.get("display_name"),
            "position_type": s.get("position_type"),
            "abbr": s.get("abbr"),
            "value": None,
        }
    for m in mods["stats"]:
        s = m["stat"]
        sid = int(s["stat_id"])
        try:
            v = float(s["value"])
        except (ValueError, TypeError):
            continue
        if sid in by_id:
            by_id[sid]["value"] = v
        else:
            by_id[sid] = {"stat_id": sid, "value": v, "position_type": None}

    out = {
        "league_id": LEAGUE_ID,
        "fetched_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "stats": [by_id[k] for k in sorted(by_id)],
        "pitching": [
            by_id[k] for k in sorted(by_id) if by_id[k].get("position_type") == "P"
        ],
        "batting": [
            by_id[k] for k in sorted(by_id) if by_id[k].get("position_type") == "B"
        ],
    }

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(json.dumps(out, indent=2))
    print(f"Wrote {OUT_PATH}")

    print("\nPITCHING SCORING:")
    for s in out["pitching"]:
        v = s.get("value")
        print(f"  {s.get('abbr') or s.get('name') or s['stat_id']:>10} = {v}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
