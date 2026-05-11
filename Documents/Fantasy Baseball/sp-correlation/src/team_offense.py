"""
Build per-team, per-game cumulative offensive metric (xwOBA as a wRC+ proxy)
from pitch-level Statcast data we already pulled.

Output: data/processed/team_offense_{year}.parquet with columns:
    team, game_date,
    team_xwoba_prior   (season-to-date xwOBA entering that date)
    cum_pa             (PAs accumulated up to but not including that date)

We don't compute true wRC+ (would require park + league adjustments), but
cumulative team xwOBA carries the same ranking information for the
correlations we care about.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data" / "raw" / "statcast"
PROC = ROOT / "data" / "processed"


def _per_chunk_team_pa(chunk: pd.DataFrame) -> pd.DataFrame:
    """Reduce a pitch-level chunk to (game_date, batting_team) sums."""
    if chunk.empty:
        return pd.DataFrame(columns=["game_date", "batting_team", "xwoba_sum", "pa"])

    df = chunk.copy()
    # Determine batting team: top of inning → away team bats, bottom → home.
    df["batting_team"] = np.where(
        df["inning_topbot"] == "Top",
        df["away_team"],
        df["home_team"],
    )

    # Canonical per-PA xwOBA: estimated_woba_using_speedangle (batted balls),
    # fall back to woba_value for K/BB/HBP. Only PA-ending pitches count.
    est = pd.to_numeric(df["estimated_woba_using_speedangle"], errors="coerce").astype("float64")
    actual = pd.to_numeric(df["woba_value"], errors="coerce").astype("float64")
    df["xwoba_per_pa"] = est.fillna(actual)
    df["woba_denom"] = pd.to_numeric(df["woba_denom"], errors="coerce").fillna(0).astype("float64")
    df.loc[df["woba_denom"] != 1, "xwoba_per_pa"] = np.nan

    df["game_date"] = pd.to_datetime(df["game_date"]).dt.date.astype(str)

    grp = df.dropna(subset=["xwoba_per_pa"]).groupby(["game_date", "batting_team"])
    out = grp.agg(xwoba_sum=("xwoba_per_pa", "sum"), pa=("woba_denom", "sum")).reset_index()
    return out


def build_team_offense(year: int) -> pd.DataFrame:
    """Stream raw chunks for the year, build cumulative per-team xwOBA-as-of."""
    chunks_dir = RAW
    chunk_files = sorted(chunks_dir.glob(f"{year}-*.parquet"))
    if not chunk_files:
        print(f"  no chunks found for {year}", file=sys.stderr)
        return pd.DataFrame()

    per_day_parts = []
    for cf in chunk_files:
        chunk = pd.read_parquet(cf)
        per_day_parts.append(_per_chunk_team_pa(chunk))
    per_day = pd.concat(per_day_parts, ignore_index=True)

    # Multiple chunks may contribute to same (date, team) — re-aggregate.
    per_day = (
        per_day.groupby(["game_date", "batting_team"])
        .agg(xwoba_sum=("xwoba_sum", "sum"), pa=("pa", "sum"))
        .reset_index()
        .rename(columns={"batting_team": "team"})
    )
    per_day = per_day.sort_values(["team", "game_date"]).reset_index(drop=True)

    # Cumulative sums prior to current date (per team)
    grp = per_day.groupby("team", sort=False)
    cum_xwoba = grp["xwoba_sum"].cumsum()
    cum_pa = grp["pa"].cumsum()
    # Shift by 1 within group to get strictly prior
    cum_xwoba_prior = cum_xwoba.groupby(per_day["team"]).shift(1)
    cum_pa_prior = cum_pa.groupby(per_day["team"]).shift(1)
    per_day["team_xwoba_prior"] = cum_xwoba_prior / cum_pa_prior
    per_day["cum_pa_prior"] = cum_pa_prior.fillna(0)

    out = per_day[["team", "game_date", "team_xwoba_prior", "cum_pa_prior"]].copy()
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--year", type=int, required=True)
    args = ap.parse_args()

    df = build_team_offense(args.year)
    if df.empty:
        return 1
    out = PROC / f"team_offense_{args.year}.parquet"
    df.to_parquet(out, index=False)
    print(f"Wrote {out}  ({len(df)} team-day rows, {df['team'].nunique()} teams)")
    print(f"\nSample as-of values (latest 5 dates):")
    latest = df.sort_values("game_date").groupby("team").tail(1).sort_values("team_xwoba_prior", ascending=False)
    print(latest.head(15).to_string(index=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
