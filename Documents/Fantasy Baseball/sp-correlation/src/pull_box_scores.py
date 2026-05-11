"""
Pull per-pitcher box-score lines for every regular-season MLB start in a
date range via MLB StatsAPI.

Output: parquet of one row per (gamePk, pitcher) for the starting pitcher
of each team only, with W/L/SV/QS flags and full box line.

Schedule + boxscore are cached to disk so re-runs are cheap.

Usage:
    python -m src.pull_box_scores --year 2024
    python -m src.pull_box_scores --start 2024-05-15 --end 2024-09-30
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
from pathlib import Path

import pandas as pd
import statsapi
from tqdm import tqdm


ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data" / "raw"
PROC = ROOT / "data" / "processed"
RAW.mkdir(parents=True, exist_ok=True)
PROC.mkdir(parents=True, exist_ok=True)


# ---------------------------------------------------------------- helpers

def _ip_str_to_float(ip_str: str) -> float:
    """'6.2' (6 IP + 2 outs) -> 6.6667. '7.0' -> 7.0. '' -> 0.0."""
    if not ip_str:
        return 0.0
    try:
        whole, _, frac = str(ip_str).partition(".")
        whole = int(whole or 0)
        frac = int(frac or 0)
        return whole + frac / 3.0
    except (TypeError, ValueError):
        return 0.0


def _ip_str_to_outs(ip_str: str) -> int:
    if not ip_str:
        return 0
    whole, _, frac = str(ip_str).partition(".")
    return int(whole or 0) * 3 + int(frac or 0)


_NOTE_RE = re.compile(r"\((?:BS|H)\s*[\d,]*\)|\(\d+\)|\s+")


def _parse_decision(note: str) -> dict:
    """
    Decision note from MLB StatsAPI box scores. Real format examples:
        '(W, 7-1)', '(L, 2-3)', '(S, 14)', '(H, 5)', '(BS, 2)', ''
    """
    out = {"win": 0, "loss": 0, "save": 0, "hold": 0, "blown_save": 0}
    if not note:
        return out
    n = note.strip().upper().lstrip("(").rstrip(")")
    head = re.split(r"[,\s]", n, 1)[0]
    if head == "W":
        out["win"] = 1
    elif head == "L":
        out["loss"] = 1
    elif head in ("S", "SV"):
        out["save"] = 1
    elif head in ("H", "HLD"):
        out["hold"] = 1
    elif head == "BS":
        out["blown_save"] = 1
    return out


# -------------------------------------------------------- schedule pull

def fetch_schedule(start_date: str, end_date: str) -> list[dict]:
    """Return list of regular-season Final games in [start_date, end_date]."""
    cache = RAW / f"schedule_{start_date}_{end_date}.json"
    if cache.exists():
        return json.loads(cache.read_text())
    games = statsapi.schedule(start_date=start_date, end_date=end_date, sportId=1)
    games = [g for g in games if g.get("game_type") == "R" and g.get("status") == "Final"]
    cache.write_text(json.dumps(games))
    return games


# --------------------------------------------------------- box score pull

def fetch_boxscore(game_pk: int, year: int) -> dict | None:
    """Cached boxscore_data fetch. Returns None on failure."""
    cache_dir = RAW / "boxscores" / str(year)
    cache_dir.mkdir(parents=True, exist_ok=True)
    cache = cache_dir / f"{game_pk}.json"
    if cache.exists():
        try:
            return json.loads(cache.read_text())
        except json.JSONDecodeError:
            cache.unlink(missing_ok=True)
    for attempt in range(3):
        try:
            box = statsapi.boxscore_data(gamePk=game_pk)
            cache.write_text(json.dumps(box))
            return box
        except Exception as e:
            if attempt == 2:
                print(f"  fail {game_pk}: {e}", file=sys.stderr)
                return None
            time.sleep(1.5 * (attempt + 1))
    return None


# --------------------------------------------------------- pitcher rows

def _team_starter_row(side: str, game: dict, box: dict) -> dict | None:
    """Extract the *effective* starting pitcher line for one team side.

    Rule: pitcher with the most IP on that team for that game AND >=4 IP.
    This captures traditional GS starters as well as bulk-relief pitchers
    used behind an opener (e.g., Dollander '26 Rockies, modern Brewers/Tigers
    bullpen days). Pure openers (<4 IP) and middle relievers are excluded.
    """
    pitchers = box.get(f"{side}Pitchers")
    if not pitchers:
        return None
    candidates = []
    for row in pitchers:
        if not isinstance(row, dict) or not row.get("personId"):
            continue
        outs = _ip_str_to_outs(row.get("ip", "0.0"))
        if outs >= 12:
            candidates.append((outs, row))
    if not candidates:
        return None
    # Highest IP wins; on a tie, earlier appearance wins (sort is stable + by -outs).
    candidates.sort(key=lambda t: -t[0])
    starter = candidates[0][1]

    ip_str = starter.get("ip") or "0.0"
    outs = _ip_str_to_outs(ip_str)
    ip = _ip_str_to_float(ip_str)
    er = int(starter.get("er") or 0)
    bb = int(starter.get("bb") or 0)
    k = int(starter.get("k") or 0)
    h = int(starter.get("h") or 0)
    r = int(starter.get("r") or 0)
    hr = int(starter.get("hr") or 0)
    p = int(starter.get("p") or 0)
    s = int(starter.get("s") or 0)
    pid = int(starter["personId"])
    name = starter.get("name") or starter.get("namefield")

    decision = _parse_decision(starter.get("note", ""))

    qs = 1 if (ip >= 6.0 and er <= 3) else 0

    is_home = side == "home"
    opp_side = "away" if is_home else "home"
    team_info = box.get(f"teamInfo", {}) or {}
    team_name = (team_info.get(side) or {}).get("teamName") or game.get(f"{side}_name")
    opp_name = (team_info.get(opp_side) or {}).get("teamName") or game.get(f"{opp_side}_name")

    # Complete game / shutout heuristic — pitcher faced all opposing innings.
    # Compute opposing team total IP from their batters' "totals". Fall back to 9.
    opp_pitchers = box.get(f"{opp_side}Pitchers", [])
    team_pitch_totals = box.get(f"{side}PitchingTotals", {}) or {}
    team_total_ip = _ip_str_to_float(team_pitch_totals.get("ip", "0.0"))
    cg = 1 if (outs >= 24 and abs(ip - team_total_ip) < 0.01) else 0
    sho = 1 if (cg and r == 0) else 0

    return {
        "game_pk": int(game["game_id"]),
        "game_date": game["game_date"],
        "pitcher_id": pid,
        "pitcher_name": name,
        "team": team_name,
        "opponent": opp_name,
        "is_home": int(is_home),
        "outs": outs,
        "ip": round(ip, 4),
        "h": h,
        "r": r,
        "er": er,
        "bb": bb,
        "k": k,
        "hr": hr,
        "pitches": p,
        "strikes": s,
        "win": decision["win"],
        "loss": decision["loss"],
        "save": decision["save"],
        "qs": qs,
        "cg": cg,
        "sho": sho,
    }


def pull_range(start_date: str, end_date: str, year: int) -> pd.DataFrame:
    """Pull all SP rows for the date range; returns DataFrame."""
    games = fetch_schedule(start_date, end_date)
    print(f"  {len(games)} regular-season Final games in {start_date}..{end_date}")
    rows: list[dict] = []
    for g in tqdm(games, desc=f"boxscores {year}"):
        box = fetch_boxscore(int(g["game_id"]), year)
        if not box:
            continue
        for side in ("home", "away"):
            r = _team_starter_row(side, g, box)
            if r:
                rows.append(r)
    df = pd.DataFrame(rows)
    return df


# ------------------------------------------------------------------- cli

def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--year", type=int)
    ap.add_argument("--start", help="YYYY-MM-DD (overrides --year)")
    ap.add_argument("--end", help="YYYY-MM-DD (overrides --year)")
    args = ap.parse_args()

    if args.start and args.end:
        start, end = args.start, args.end
        year = int(start[:4])
    elif args.year:
        year = args.year
        # Pull from opening-day region for every year. The May 15+ analytical
        # filter is applied later in as_of_features.py — but the feature
        # cumulative sums need full-season-to-date data to be accurate.
        start = f"{year}-03-15"
        end = time.strftime("%Y-%m-%d") if year == 2026 else f"{year}-09-30"
    else:
        ap.error("Provide --year or --start/--end")
        return 2

    print(f"\n=== Pulling box-score starts: {start} to {end} ===")
    df = pull_range(start, end, year)

    # Apply per-start filters
    df_pre = df.copy()
    df = df[df["outs"] >= 12].copy()  # 4+ IP minimum per appearance

    # Compute season-total starts per pitcher (within this date range), then keep ≥5
    starts_per = df.groupby("pitcher_id").size().rename("n_starts_season")
    df = df.merge(starts_per, left_on="pitcher_id", right_index=True)
    df = df[df["n_starts_season"] >= 5].copy()

    out = PROC / f"box_starts_{year}.parquet"
    df.to_parquet(out, index=False)
    print(f"\nWrote {out}")
    print(f"  Pre-filter rows : {len(df_pre)}")
    print(f"  After 4+ IP     : {(df_pre['outs'] >= 12).sum()}")
    print(f"  After 5+ starts : {len(df)}")
    print(f"  Unique SPs      : {df['pitcher_id'].nunique()}")
    print(f"  Date range      : {df['game_date'].min()} .. {df['game_date'].max()}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
