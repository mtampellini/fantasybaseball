"""
Pull pitch-level Statcast data in weekly chunks via pybaseball.statcast.

Output: data/raw/statcast/{YYYY-MM-DD}.parquet (one per chunk start date).
A consolidated per-game aggregate is written to data/processed/pitch_agg_{year}.parquet.

Usage:
    python -m src.pull_statcast --year 2024
    python -m src.pull_statcast --start 2024-05-15 --end 2024-09-30
"""

from __future__ import annotations

import argparse
import sys
import time
from datetime import date, datetime, timedelta
from pathlib import Path

import numpy as np
import pandas as pd
from tqdm import tqdm

# pybaseball is noisy; suppress its progress bars / cache warnings
import pybaseball as pyb
pyb.cache.enable()


ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data" / "raw" / "statcast"
PROC = ROOT / "data" / "processed"
RAW.mkdir(parents=True, exist_ok=True)
PROC.mkdir(parents=True, exist_ok=True)


# Which pitch-level columns we keep. Statcast returns ~90 columns; we only need
# the ones used for per-game aggregations.
KEEP_COLS = [
    "game_pk", "game_date", "pitcher", "batter", "pitch_type",
    "description", "events", "type",
    "launch_speed", "launch_angle", "launch_speed_angle",
    "estimated_woba_using_speedangle", "estimated_ba_using_speedangle",
    "woba_value", "woba_denom", "babip_value",
    "balls", "strikes", "outs_when_up", "inning", "inning_topbot",
    "home_team", "away_team", "p_throws", "stand",
]


def _chunks(start: date, end: date, days: int = 7):
    cur = start
    while cur <= end:
        nxt = min(cur + timedelta(days=days - 1), end)
        yield cur, nxt
        cur = nxt + timedelta(days=1)


def fetch_chunk(start: date, end: date) -> pd.DataFrame:
    """Fetch one weekly chunk; cached to parquet.

    A cache file is only trusted if it was written after the chunk's end
    date — a chunk cached mid-week holds partial data and must be refetched.
    """
    cache = RAW / f"{start.isoformat()}.parquet"
    if cache.exists():
        cached_on = datetime.fromtimestamp(cache.stat().st_mtime).date()
        if cached_on > end:
            return pd.read_parquet(cache)
    df = pyb.statcast(start_dt=start.isoformat(), end_dt=end.isoformat(), verbose=False)
    keep = [c for c in KEEP_COLS if c in df.columns]
    df = df[keep].copy()
    df.to_parquet(cache, index=False)
    return df


def pull_range(start: date, end: date) -> pd.DataFrame:
    """Pull weekly chunks across [start, end], concat."""
    parts = []
    chunks = list(_chunks(start, end, days=7))
    for cstart, cend in tqdm(chunks, desc="statcast weeks"):
        try:
            parts.append(fetch_chunk(cstart, cend))
        except Exception as e:
            print(f"  WARN: chunk {cstart} failed: {e}", file=sys.stderr)
            continue
    if not parts:
        return pd.DataFrame()
    return pd.concat(parts, ignore_index=True)


# ------------------------------------------------------ per-game aggregator

_SWING_DESC = {
    "foul", "foul_tip", "foul_bunt", "missed_bunt",
    "hit_into_play", "hit_into_play_no_out", "hit_into_play_score",
    "swinging_strike", "swinging_strike_blocked",
}
_WHIFF_DESC = {"swinging_strike", "swinging_strike_blocked"}
_CSTRIKE_DESC = {"called_strike"}


def aggregate_per_game(pitches: pd.DataFrame) -> pd.DataFrame:
    """Aggregate pitch-level to per (pitcher, game) rows."""
    if pitches.empty:
        return pd.DataFrame()

    df = pitches.copy()
    df["is_swing"] = df["description"].isin(_SWING_DESC)
    df["is_whiff"] = df["description"].isin(_WHIFF_DESC)
    df["is_cstrike"] = df["description"].isin(_CSTRIKE_DESC)
    df["is_bbe"] = df["events"].notna() & df["launch_speed"].notna()
    df["is_hard"] = df["is_bbe"] & (df["launch_speed"] >= 95)
    df["is_barrel"] = df["launch_speed_angle"] == 6

    # Canonical per-PA xwOBA against (Savant methodology):
    #   - PA-ending pitches with woba_denom == 1 are the denominator
    #   - Numerator value per PA:
    #       * batted ball  → estimated_woba_using_speedangle (model from EV/LA)
    #       * K / BB / HBP → woba_value (actual outcome; K=0, BB≈.696, HBP≈.726)
    df["woba_denom"] = pd.to_numeric(df["woba_denom"], errors="coerce")
    est = pd.to_numeric(df["estimated_woba_using_speedangle"], errors="coerce")
    actual = pd.to_numeric(df["woba_value"], errors="coerce")
    # Fall back to actual when estimated is null (K/BB/HBP rows). Restrict to PA rows.
    df["xwoba_per_pa"] = est.where(est.notna(), actual)
    df.loc[df["woba_denom"] != 1, "xwoba_per_pa"] = np.nan

    # GB / FB / LD classification from launch_angle (Statcast convention):
    # GB <10, LD 10-25, FB 25-50, PU >50
    la = pd.to_numeric(df["launch_angle"], errors="coerce")
    df["is_gb"] = df["is_bbe"] & (la < 10)
    df["is_ld"] = df["is_bbe"] & (la >= 10) & (la < 25)
    df["is_fb"] = df["is_bbe"] & (la >= 25) & (la < 50)
    df["is_pu"] = df["is_bbe"] & (la >= 50)

    grp = df.groupby(["game_pk", "game_date", "pitcher"], dropna=False)
    out = grp.agg(
        pitches=("description", "size"),
        swings=("is_swing", "sum"),
        whiffs=("is_whiff", "sum"),
        cstrikes=("is_cstrike", "sum"),
        bbe=("is_bbe", "sum"),
        hard_hit=("is_hard", "sum"),
        barrels=("is_barrel", "sum"),
        gb=("is_gb", "sum"),
        ld=("is_ld", "sum"),
        fb=("is_fb", "sum"),
        pu=("is_pu", "sum"),
        xwoba_sum=("xwoba_per_pa", "sum"),
        xwoba_n=("woba_denom", "sum"),
    ).reset_index()

    out = out.rename(columns={"pitcher": "pitcher_id"})
    out["game_pk"] = out["game_pk"].astype("Int64")
    out["pitcher_id"] = out["pitcher_id"].astype("Int64")
    out["game_date"] = pd.to_datetime(out["game_date"]).dt.date.astype(str)

    out["csw_rate"] = (out["cstrikes"] + out["whiffs"]) / out["pitches"].replace(0, np.nan)
    out["whiff_rate"] = out["whiffs"] / out["swings"].replace(0, np.nan)
    out["hard_hit_rate"] = out["hard_hit"] / out["bbe"].replace(0, np.nan)
    out["barrel_rate"] = out["barrels"] / out["bbe"].replace(0, np.nan)
    out["gb_rate"] = out["gb"] / out["bbe"].replace(0, np.nan)
    out["fb_rate"] = out["fb"] / out["bbe"].replace(0, np.nan)
    out["xwoba_per_pa"] = out["xwoba_sum"] / out["xwoba_n"].replace(0, np.nan)
    return out


def aggregate_per_game_batter(pitches: pd.DataFrame) -> pd.DataFrame:
    """Aggregate pitch-level to per (batter, game) rows.

    Mirrors aggregate_per_game() but groups by batter instead of pitcher.
    K/BB rates are computed off PA (woba_denom==1) for consistency with how
    Yahoo scoring buckets events.
    """
    if pitches.empty:
        return pd.DataFrame()

    df = pitches.copy()
    df["is_swing"] = df["description"].isin(_SWING_DESC)
    df["is_whiff"] = df["description"].isin(_WHIFF_DESC)
    df["is_cstrike"] = df["description"].isin(_CSTRIKE_DESC)
    df["is_bbe"] = df["events"].notna() & df["launch_speed"].notna()
    df["is_hard"] = df["is_bbe"] & (df["launch_speed"] >= 95)
    df["is_barrel"] = df["launch_speed_angle"] == 6

    # PA-ending events and outcome flags (batter perspective)
    df["woba_denom"] = pd.to_numeric(df["woba_denom"], errors="coerce")
    df["is_pa"] = df["woba_denom"] == 1
    df["is_k"] = df["is_pa"] & df["events"].isin(["strikeout", "strikeout_double_play"])
    df["is_bb"] = df["is_pa"] & (df["events"] == "walk")

    est = pd.to_numeric(df["estimated_woba_using_speedangle"], errors="coerce")
    actual = pd.to_numeric(df["woba_value"], errors="coerce")
    df["xwoba_per_pa"] = est.where(est.notna(), actual)
    df.loc[~df["is_pa"], "xwoba_per_pa"] = np.nan

    # xBA on BBE
    df["xba_bbe"] = pd.to_numeric(df["estimated_ba_using_speedangle"], errors="coerce")
    df.loc[~df["is_bbe"], "xba_bbe"] = np.nan

    # Launch-angle buckets (same as pitcher side, but recorded as batter metrics)
    la = pd.to_numeric(df["launch_angle"], errors="coerce")
    df["is_gb"] = df["is_bbe"] & (la < 10)
    df["is_ld"] = df["is_bbe"] & (la >= 10) & (la < 25)
    df["is_fb"] = df["is_bbe"] & (la >= 25) & (la < 50)
    df["is_pu"] = df["is_bbe"] & (la >= 50)
    df["is_sweet_spot"] = df["is_bbe"] & (la >= 8) & (la <= 32)

    grp = df.groupby(["game_pk", "game_date", "batter"], dropna=False)
    out = grp.agg(
        pitches=("description", "size"),
        pa=("is_pa", "sum"),
        swings=("is_swing", "sum"),
        whiffs=("is_whiff", "sum"),
        cstrikes=("is_cstrike", "sum"),
        bbe=("is_bbe", "sum"),
        hard_hit=("is_hard", "sum"),
        barrels=("is_barrel", "sum"),
        gb=("is_gb", "sum"),
        ld=("is_ld", "sum"),
        fb=("is_fb", "sum"),
        pu=("is_pu", "sum"),
        sweet=("is_sweet_spot", "sum"),
        ks=("is_k", "sum"),
        bbs=("is_bb", "sum"),
        xwoba_sum=("xwoba_per_pa", "sum"),
        xwoba_n=("woba_denom", "sum"),
        xba_sum=("xba_bbe", "sum"),
    ).reset_index()

    out = out.rename(columns={"batter": "batter_id"})
    out["game_pk"] = out["game_pk"].astype("Int64")
    out["batter_id"] = out["batter_id"].astype("Int64")
    out["game_date"] = pd.to_datetime(out["game_date"]).dt.date.astype(str)

    # Rate columns
    out["whiff_rate"] = out["whiffs"] / out["swings"].replace(0, np.nan)
    out["hard_hit_rate"] = out["hard_hit"] / out["bbe"].replace(0, np.nan)
    out["barrel_rate"] = out["barrels"] / out["bbe"].replace(0, np.nan)
    out["sweet_spot_rate"] = out["sweet"] / out["bbe"].replace(0, np.nan)
    out["gb_rate"] = out["gb"] / out["bbe"].replace(0, np.nan)
    out["fb_rate"] = out["fb"] / out["bbe"].replace(0, np.nan)
    out["ld_rate"] = out["ld"] / out["bbe"].replace(0, np.nan)
    out["k_rate"] = out["ks"] / out["pa"].replace(0, np.nan)
    out["bb_rate"] = out["bbs"] / out["pa"].replace(0, np.nan)
    out["xwoba_per_pa"] = out["xwoba_sum"] / out["xwoba_n"].replace(0, np.nan)
    out["xba_per_bbe"] = out["xba_sum"] / out["bbe"].replace(0, np.nan)
    return out


# ---------------------------------------------------------------- cli

def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--year", type=int)
    ap.add_argument("--start", help="YYYY-MM-DD")
    ap.add_argument("--end", help="YYYY-MM-DD")
    ap.add_argument("--hitters", action="store_true",
                    help="Aggregate to per-(batter,game) instead of per-(pitcher,game)")
    args = ap.parse_args()

    if args.start and args.end:
        s = datetime.fromisoformat(args.start).date()
        e = datetime.fromisoformat(args.end).date()
        year = s.year
    elif args.year:
        year = args.year
        s = date(year, 3, 15)
        e = date(year, 9, 30) if year < 2026 else date.today()
    else:
        ap.error("Provide --year or --start/--end")
        return 2

    print(f"\n=== Pulling Statcast pitch-level: {s} to {e} ===")
    pitches = pull_range(s, e)
    print(f"  {len(pitches):,} pitches pulled")

    if args.hitters:
        agg = aggregate_per_game_batter(pitches)
        out = PROC / f"bat_agg_{year}.parquet"
        agg.to_parquet(out, index=False)
        print(f"\nWrote {out}")
        print(f"  Batter-game rows: {len(agg)}")
        print(f"  Unique batters  : {agg['batter_id'].nunique()}")
        return 0

    agg = aggregate_per_game(pitches)
    out = PROC / f"pitch_agg_{year}.parquet"
    agg.to_parquet(out, index=False)
    print(f"\nWrote {out}")
    print(f"  Pitcher-game rows: {len(agg)}")
    print(f"  Unique pitchers  : {agg['pitcher_id'].nunique()}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
