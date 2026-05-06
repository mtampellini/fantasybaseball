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
        "selections": "xba,babip,xslg,woba,xwoba",
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


def _build_col_index(headers, required):
    """
    Map header name -> column index. Raises if any required column is missing,
    so a Savant schema change fails loudly instead of silently producing junk
    (the CSV's column order is not contractually stable).
    """
    norm = {h.strip().lower().lstrip("\ufeff"): i for i, h in enumerate(headers)}
    missing = [c for c in required if c not in norm]
    if missing:
        raise RuntimeError(
            f"Savant CSV missing expected columns {missing}; got headers={headers}"
        )
    return norm


def _cell(row, col_idx, name):
    i = col_idx[name]
    return row[i] if i < len(row) else ""


def _parse_pitcher_csv(text):
    """CSV: "last_name, first_name", player_id, year, k_percent, bb_percent, babip, woba, xwoba"""
    out = {}
    text = text.lstrip("\ufeff")
    reader = csv.reader(io.StringIO(text))
    headers = next(reader, None)
    if not headers:
        return out

    name_col = "last_name, first_name"
    required = [name_col, "player_id", "k_percent", "bb_percent", "babip", "woba", "xwoba"]
    col_idx = _build_col_index(headers, required)

    for row in reader:
        raw_name = _cell(row, col_idx, name_col).strip()
        if not raw_name:
            continue
        normalized = normalize_name(raw_name)
        kp = parse_float(_cell(row, col_idx, "k_percent"))
        bbp = parse_float(_cell(row, col_idx, "bb_percent"))
        out[normalized] = {
            "name": _display_name(raw_name),
            "player_id": _cell(row, col_idx, "player_id").strip(),
            "k_pct": kp,
            "bb_pct": bbp,
            "k_bb_pct": (round(kp - bbp, 1) if kp is not None and bbp is not None else None),
            "babip": parse_float(_cell(row, col_idx, "babip")),
            "woba": parse_float(_cell(row, col_idx, "woba")),
            "xwoba": parse_float(_cell(row, col_idx, "xwoba")),
        }
    return out


def _parse_hitter_csv(text):
    """CSV: "last_name, first_name", player_id, year, xba, babip, xslg, woba, xwoba"""
    out = {}
    text = text.lstrip("\ufeff")
    reader = csv.reader(io.StringIO(text))
    headers = next(reader, None)
    if not headers:
        return out

    name_col = "last_name, first_name"
    required = [name_col, "player_id", "xba", "babip", "xslg", "woba", "xwoba"]
    col_idx = _build_col_index(headers, required)

    for row in reader:
        raw_name = _cell(row, col_idx, name_col).strip()
        if not raw_name:
            continue
        normalized = normalize_name(raw_name)
        xba = parse_float(_cell(row, col_idx, "xba"))
        xslg = parse_float(_cell(row, col_idx, "xslg"))
        xiso = round(xslg - xba, 3) if (xslg is not None and xba is not None) else None
        woba = parse_float(_cell(row, col_idx, "woba"))
        xwoba = parse_float(_cell(row, col_idx, "xwoba"))
        gap = None
        if woba is not None and xwoba is not None:
            gap = round((woba - xwoba) * 1000)
        out[normalized] = {
            "name": _display_name(raw_name),
            "player_id": _cell(row, col_idx, "player_id").strip(),
            "xba": xba,
            "babip": parse_float(_cell(row, col_idx, "babip")),
            "xslg": xslg,
            "xiso": xiso,
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
