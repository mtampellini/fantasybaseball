"""
Historical Statcast pulls for trade-target scoring.

Two cached datasets:
  data/savant_2025_hitters.json   -- 2025 final season (immutable)
  data/savant_career_hitters.json -- weighted career BABIP across 2020-2025

Both use the same CSV leaderboard endpoint as pull_savant.py.
Multi-year aggregation: pass year=2020,2021,...,2025 (comma-separated)
which returns one row per (player, year). We weight BABIP by AB to
collapse to a single career row per player.
"""

import csv
import io
import json
import time
from pathlib import Path

import requests

from utils import normalize_name, parse_float, parse_int
from pull_savant import SAVANT_BASE, REQUEST_HEADERS, _display_name


DATA_DIR = Path(__file__).parent / "data"
HITTERS_2025_CACHE = DATA_DIR / "savant_2025_hitters.json"
CAREER_CACHE = DATA_DIR / "savant_career_hitters.json"

CAREER_YEARS = "2020,2021,2022,2023,2024,2025"
CAREER_REFRESH_DAYS = 30
HISTORICAL_MIN_PA = 50  # broad — filtering is downstream


def fetch_hitter_leaderboard_year(year, min_pa=HISTORICAL_MIN_PA):
    """Pull one season of hitter Statcast with PA included."""
    params = {
        "year": year, "type": "batter", "min": min_pa,
        "selections": "pa,ab,babip,woba,xwoba",
        "sort": "xwoba", "sortDir": "desc",
        "csv": "true",
    }
    r = requests.get(SAVANT_BASE, params=params, headers=REQUEST_HEADERS, timeout=30)
    r.raise_for_status()
    return _parse_hitter_csv_with_pa(r.text)


def _parse_hitter_csv_with_pa(text):
    """CSV: "last_name, first_name", player_id, year, pa, ab, babip, woba, xwoba"""
    out = {}
    text = text.lstrip("﻿")
    reader = csv.reader(io.StringIO(text))
    headers = next(reader, None)
    if not headers:
        return out

    for row in reader:
        if len(row) < 8:
            continue
        raw_name = row[0].strip()
        if not raw_name:
            continue
        norm = normalize_name(raw_name)
        out[norm] = {
            "name": _display_name(raw_name),
            "player_id": row[1].strip(),
            "year": parse_int(row[2]),
            "pa": parse_int(row[3]),
            "ab": parse_int(row[4]),
            "babip": parse_float(row[5]),
            "woba": parse_float(row[6]),
            "xwoba": parse_float(row[7]),
        }
    return out


def fetch_hitter_career_stats(years=CAREER_YEARS, min_pa=HISTORICAL_MIN_PA):
    """Pull multi-year hitter data and aggregate per player.

    Returns dict keyed on normalized name with weighted (by AB) career BABIP.
    """
    params = {
        "year": years, "type": "batter", "min": min_pa,
        "selections": "pa,ab,babip,woba,xwoba",
        "sort": "xwoba", "sortDir": "desc",
        "csv": "true",
    }
    r = requests.get(SAVANT_BASE, params=params, headers=REQUEST_HEADERS, timeout=60)
    r.raise_for_status()

    text = r.text.lstrip("﻿")
    reader = csv.reader(io.StringIO(text))
    headers = next(reader, None)
    if not headers:
        return {}

    by_player = {}  # norm -> aggregator
    for row in reader:
        if len(row) < 8:
            continue
        raw_name = row[0].strip()
        if not raw_name:
            continue
        norm = normalize_name(raw_name)
        rec = {
            "year": parse_int(row[2]),
            "pa": parse_int(row[3]) or 0,
            "ab": parse_int(row[4]) or 0,
            "babip": parse_float(row[5]),
        }
        by_player.setdefault(norm, {
            "name": _display_name(raw_name),
            "player_id": row[1].strip(),
            "_rows": [],
        })
        by_player[norm]["_rows"].append(rec)

    out = {}
    for norm, info in by_player.items():
        rows = info.pop("_rows")
        total_ab = sum(r["ab"] for r in rows if r["babip"] is not None)
        total_pa = sum(r["pa"] for r in rows if r["babip"] is not None)
        if total_ab > 0:
            weighted = sum(r["babip"] * r["ab"] for r in rows if r["babip"] is not None)
            career_babip = round(weighted / total_ab, 3)
        else:
            career_babip = None
        years_played = sorted({r["year"] for r in rows if r["year"]})
        out[norm] = {
            **info,
            "career_babip": career_babip,
            "career_pa": total_pa,
            "career_ab": total_ab,
            "years_in_sample": years_played,
        }
    return out


def load_or_fetch_2025_hitters(force=False):
    """Load cached 2025 data, or fetch + cache. 2025 is immutable so no refresh."""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    if HITTERS_2025_CACHE.exists() and not force:
        with HITTERS_2025_CACHE.open() as f:
            return json.load(f)
    print("  Fetching 2025 hitter leaderboard from Savant...")
    data = fetch_hitter_leaderboard_year(2025)
    with HITTERS_2025_CACHE.open("w") as f:
        json.dump(data, f, indent=2)
    print(f"  Cached {len(data)} hitters to {HITTERS_2025_CACHE.name}")
    return data


def load_or_fetch_career_hitters(force=False, refresh_days=CAREER_REFRESH_DAYS):
    """Load cached career data; refresh if older than refresh_days."""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    if CAREER_CACHE.exists() and not force:
        age_days = (time.time() - CAREER_CACHE.stat().st_mtime) / 86400
        if age_days < refresh_days:
            with CAREER_CACHE.open() as f:
                return json.load(f)
        print(f"  Career cache is {age_days:.0f}d old, refreshing...")
    print(f"  Fetching career hitter stats ({CAREER_YEARS}) from Savant...")
    data = fetch_hitter_career_stats()
    with CAREER_CACHE.open("w") as f:
        json.dump(data, f, indent=2)
    print(f"  Cached {len(data)} career hitter records to {CAREER_CACHE.name}")
    return data


if __name__ == "__main__":
    print("Loading 2025 hitters...")
    h2025 = load_or_fetch_2025_hitters()
    print(f"  {len(h2025)} players")

    print("\nLoading career hitters...")
    career = load_or_fetch_career_hitters()
    print(f"  {len(career)} players")
    for name in ("juan soto", "freddie freeman", "luis arraez"):
        rec = career.get(name)
        if rec:
            print(f"  {rec['name']}: career BABIP {rec['career_babip']}, "
                  f"PA {rec['career_pa']}, years {rec['years_in_sample']}")
