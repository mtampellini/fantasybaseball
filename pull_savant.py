"""
Pull season-level Statcast data from Baseball Savant.

Uses the leaderboard CSV endpoint:
    /leaderboard/custom?...&csv=true

The HTML page is a JS-rendered SPA so we use the CSV export instead.
"""

import requests
import csv
import io

from utils import normalize_name, parse_float


SAVANT_BASE = "https://baseballsavant.mlb.com/leaderboard/custom"

REQUEST_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) Fantasy-Tracker/1.0"
}


def fetch_pitcher_leaderboard(year=2026, min_pa=1):
    """Pull every pitcher with min_pa+ PA. Returns dict keyed on normalized name."""
    params = {
        "year": year, "type": "pitcher", "min": min_pa,
        "selections": "k_percent,bb_percent,babip,woba,xwoba",
        "sort": "xwoba", "sortDir": "asc",
        "csv": "true",
    }
    r = requests.get(SAVANT_BASE, params=params, headers=REQUEST_HEADERS, timeout=30)
    r.raise_for_status()
    return _parse_pitcher_csv(r.text)


def fetch_hitter_leaderboard(year=2026, min_pa=10):
    """Pull every hitter with min_pa+ PA. Returns dict keyed on normalized name."""
    params = {
        "year": year, "type": "batter", "min": min_pa,
        "selections": "babip,xslg,woba,xwoba",
        "sort": "xwoba", "sortDir": "desc",
        "csv": "true",
    }
    r = requests.get(SAVANT_BASE, params=params, headers=REQUEST_HEADERS, timeout=30)
    r.raise_for_status()
    return _parse_hitter_csv(r.text)


def _display_name(raw_name):
    """Convert 'Last, First' to 'First Last'."""
    if "," in raw_name:
        parts = [p.strip() for p in raw_name.split(",")]
        if len(parts) == 2:
            return f"{parts[1]} {parts[0]}"
    return raw_name


def _parse_pitcher_csv(text):
    """CSV: "last_name, first_name", player_id, year, k_pct, bb_pct, babip, woba, xwoba"""
    out = {}
    text = text.lstrip("\ufeff")
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
        normalized = normalize_name(raw_name)
        kp = parse_float(row[3])
        bbp = parse_float(row[4])
        out[normalized] = {
            "name": _display_name(raw_name),
            "player_id": row[1].strip(),
            "k_pct": kp,
            "bb_pct": bbp,
            "k_bb_pct": (round(kp - bbp, 1) if kp is not None and bbp is not None else None),
            "babip": parse_float(row[5]),
            "woba": parse_float(row[6]),
            "xwoba": parse_float(row[7]),
        }
    return out


def _parse_hitter_csv(text):
    """CSV: "last_name, first_name", player_id, year, babip, xslg, woba, xwoba"""
    out = {}
    text = text.lstrip("\ufeff")
    reader = csv.reader(io.StringIO(text))
    headers = next(reader, None)
    if not headers:
        return out

    for row in reader:
        if len(row) < 7:
            continue
        raw_name = row[0].strip()
        if not raw_name:
            continue
        normalized = normalize_name(raw_name)
        woba = parse_float(row[5])
        xwoba = parse_float(row[6])
        gap = None
        if woba is not None and xwoba is not None:
            gap = round((woba - xwoba) * 1000)
        out[normalized] = {
            "name": _display_name(raw_name),
            "player_id": row[1].strip(),
            "babip": parse_float(row[3]),
            "xslg": parse_float(row[4]),
            "woba": woba,
            "xwoba": xwoba,
            "woba_xwoba_gap": gap,
        }
    return out


if __name__ == "__main__":
    print("Pulling pitchers...")
    p = fetch_pitcher_leaderboard()
    print(f"Got {len(p)} pitchers")
    if p:
        glasnow = p.get("tyler glasnow")
        if glasnow:
            print(f"  Glasnow: xwOBA {glasnow['xwoba']}, K-BB% {glasnow['k_bb_pct']}")

    print("\nPulling hitters...")
    h = fetch_hitter_leaderboard()
    print(f"Got {len(h)} hitters")
    if h:
        walker = h.get("jordan walker")
        if walker:
            print(f"  Walker: xwOBA {walker['xwoba']}, xSLG {walker['xslg']}")
