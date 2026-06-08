"""
Pull TRUE per-week Statcast metrics (xwOBA, wOBA, BABIP) for a single hitter
over a date range, broken out week-by-week.

Unlike the cumulative season figures in the daily snapshots, this queries
Baseball Savant's pitch-level search endpoint with explicit date bounds, so
each fantasy week (Mon-Sun) is computed from only that week's batted balls /
plate appearances -- the real Statcast weekly split, not a differenced
approximation.

Endpoint (CSV export of the Statcast search):
    https://baseballsavant.mlb.com/statcast_search/csv
      ?player_type=batter&batters_lookup[]=<MLBAM_ID>
      &game_date_gt=YYYY-MM-DD&game_date_lt=YYYY-MM-DD
      &type=details&all=true ...

Each row is one pitch; the columns we need:
    estimated_woba_using_speedangle  -> xwOBA numerator (per PA-ending event)
    woba_value / woba_denom          -> wOBA
    events, type, bb_type            -> to identify BIP for BABIP

Usage:
    # Default: Rafael Devers, last 4 completed fantasy weeks
    python pull_weekly_statcast.py

    # Any player by MLBAM id, custom week count
    python pull_weekly_statcast.py --player-id 592450 --weeks 6

    # Explicit date range (single bucket)
    python pull_weekly_statcast.py --player-id 646240 --start 2026-05-11 --end 2026-06-07

Note: requires outbound access to baseballsavant.mlb.com. In a sandboxed
environment whose network allowlist excludes MLB hosts this will 403; run it
on a machine (or session) with network access.
"""

import argparse
import csv
import io
import sys
from collections import defaultdict
from datetime import date, datetime, timedelta

import requests


STATCAST_CSV = "https://baseballsavant.mlb.com/statcast_search/csv"

REQUEST_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) Fantasy-Tracker/1.0"
}

# A handful of known MLBAM ids so you can pass a name instead of digits.
KNOWN_IDS = {
    "rafael devers": 646240,
    "george springer": 543807,
    "kyle schwarber": 656941,
    "jordan walker": 691023,
}

# Events that count as a plate appearance (wOBA denominator basis). Savant's
# woba_denom column already encodes this, so we lean on it when present.
BIP_EVENTS = {
    "single", "double", "triple", "home_run", "field_out", "force_out",
    "grounded_into_double_play", "double_play", "field_error", "fielders_choice",
    "fielders_choice_out", "sac_fly", "sac_fly_double_play", "triple_play",
}
HIT_EVENTS = {"single", "double", "triple", "home_run"}


def _monday_of(d):
    return d - timedelta(days=d.weekday())


def last_completed_weeks(n, today=None):
    """Return [(label, start_monday, end_sunday), ...] for the n most recent
    fully-completed fantasy weeks (Mon-Sun) ending before this week."""
    today = today or date.today()
    this_monday = _monday_of(today)
    out = []
    for i in range(n, 0, -1):
        start = this_monday - timedelta(days=7 * i)
        end = start + timedelta(days=6)
        out.append((f"{start.isoformat()}..{end.isoformat()}", start, end))
    return out


def fetch_statcast_rows(player_id, start, end):
    """Fetch raw pitch-level rows for one batter in [start, end] inclusive."""
    params = {
        "player_type": "batter",
        "batters_lookup[]": str(player_id),
        "game_date_gt": start.isoformat(),
        "game_date_lt": end.isoformat(),
        "type": "details",
        "all": "true",
        "min_pitches": "0",
        "min_results": "0",
        "group_by": "name",
        "sort_col": "pitches",
        "player_event_sort": "api_p_release_speed",
        "sort_order": "desc",
    }
    r = requests.get(STATCAST_CSV, params=params, headers=REQUEST_HEADERS, timeout=45)
    r.raise_for_status()
    text = r.text.lstrip("﻿")
    reader = csv.DictReader(io.StringIO(text))
    return list(reader)


def _f(row, key):
    v = row.get(key, "")
    if v in ("", "null", None):
        return None
    try:
        return float(v)
    except (ValueError, TypeError):
        return None


def aggregate_week(rows):
    """Compute xwOBA, wOBA, BABIP, PA, BIP from a week's pitch rows.

    We only look at PA-ending pitches: those carry woba_value/woba_denom and
    (for contact) estimated_woba_using_speedangle.
    """
    pa = 0
    woba_num = 0.0
    woba_den = 0.0
    xwoba_num = 0.0
    xwoba_den = 0  # PAs with an xwOBA value (Savant assigns one to every PA,
                   # including Ks/BBs which get a fixed value)
    hits = 0
    ab = 0
    bip = 0
    sf = 0
    so = 0
    for row in rows:
        events = (row.get("events") or "").strip()
        if not events:
            continue  # not a PA-ending pitch
        pa += 1

        wv = _f(row, "woba_value")
        wd = _f(row, "woba_denom")
        if wv is not None and wd is not None:
            woba_num += wv
            woba_den += wd

        xw = _f(row, "estimated_woba_using_speedangle")
        if xw is not None:
            xwoba_num += xw
            xwoba_den += 1
        else:
            # Ks / BBs / HBP have no batted-ball xwOBA; Savant still folds them
            # into the player's xwOBA using the event's generic woba_value.
            if wv is not None:
                xwoba_num += wv
                xwoba_den += 1

        # BABIP components: (H - HR) / (AB - K - HR + SF)
        if events in HIT_EVENTS:
            hits += 1
        if events in BIP_EVENTS:
            bip += 1
        if events == "sac_fly" or events == "sac_fly_double_play":
            sf += 1
        if events == "strikeout" or events == "strikeout_double_play":
            so += 1
        # AB = PA minus walks, HBP, sacrifices, catcher interference
        if events not in ("walk", "hit_by_pitch", "sac_fly", "sac_bunt",
                          "sac_fly_double_play", "catcher_interf", "intent_walk"):
            ab += 1

    hr = sum(1 for r in rows if (r.get("events") or "").strip() == "home_run")
    babip_den = ab - so - hr + sf
    babip = ((hits - hr) / babip_den) if babip_den > 0 else None

    return {
        "pa": pa,
        "xwoba": round(xwoba_num / xwoba_den, 3) if xwoba_den else None,
        "woba": round(woba_num / woba_den, 3) if woba_den else None,
        "babip": round(babip, 3) if babip is not None else None,
        "bip": bip,
    }


def main():
    ap = argparse.ArgumentParser(description="Per-week Statcast splits for a hitter")
    ap.add_argument("--player", help="Player name (uses known-id table)")
    ap.add_argument("--player-id", type=int, help="MLBAM id (overrides --player)")
    ap.add_argument("--weeks", type=int, default=4,
                    help="Number of recent completed fantasy weeks (default 4)")
    ap.add_argument("--start", help="Explicit start date YYYY-MM-DD (single bucket)")
    ap.add_argument("--end", help="Explicit end date YYYY-MM-DD (single bucket)")
    ap.add_argument("--today", help="Override 'today' as YYYY-MM-DD (for backtests)")
    args = ap.parse_args()

    pid = args.player_id
    if pid is None:
        name = (args.player or "rafael devers").lower()
        pid = KNOWN_IDS.get(name)
        if pid is None:
            print(f"Unknown player '{name}'. Pass --player-id <MLBAM id>.", file=sys.stderr)
            return 2

    today = (datetime.strptime(args.today, "%Y-%m-%d").date()
             if args.today else date.today())

    if args.start and args.end:
        s = datetime.strptime(args.start, "%Y-%m-%d").date()
        e = datetime.strptime(args.end, "%Y-%m-%d").date()
        buckets = [(f"{s.isoformat()}..{e.isoformat()}", s, e)]
    else:
        buckets = last_completed_weeks(args.weeks, today=today)

    print(f"Statcast weekly splits — player_id={pid}\n")
    print(f"{'window':>24} {'PA':>4} {'xwOBA':>6} {'wOBA':>6} {'BABIP':>6} {'gap':>5}")
    for label, start, end in buckets:
        try:
            rows = fetch_statcast_rows(pid, start, end)
        except requests.RequestException as ex:
            print(f"{label:>24}  ERROR: {ex}", file=sys.stderr)
            continue
        agg = aggregate_week(rows)
        gap = None
        if agg["woba"] is not None and agg["xwoba"] is not None:
            gap = round((agg["woba"] - agg["xwoba"]) * 1000)
        print(f"{label:>24} {agg['pa']:>4} "
              f"{agg['xwoba']!s:>6} {agg['woba']!s:>6} {agg['babip']!s:>6} "
              f"{('+' + str(gap)) if (gap is not None and gap >= 0) else str(gap):>5}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
