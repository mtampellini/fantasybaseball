"""
Data-quality report for the box-score per-start dataset.

Usage:
    python -m src.validate_boxes --year 2024
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import pandas as pd

from src.yahoo_scoring import PitcherWeights, pitcher_fp


ROOT = Path(__file__).resolve().parents[1]
PROC = ROOT / "data" / "processed"


def report(year: int) -> int:
    path = PROC / f"box_starts_{year}.parquet"
    if not path.exists():
        print(f"ERROR: {path} not found. Run pull_box_scores first.", file=sys.stderr)
        return 2

    df = pd.read_parquet(path)
    w = PitcherWeights.from_file()
    df["fp"] = df.apply(lambda r: pitcher_fp(r.to_dict(), w), axis=1)

    print(f"\n=== Data-quality report: box_starts_{year}.parquet ===")
    print(f"Rows               : {len(df)}")
    print(f"Unique SPs         : {df['pitcher_id'].nunique()}")
    print(f"Date range         : {df['game_date'].min()} .. {df['game_date'].max()}")
    print(f"Teams represented  : {df['team'].nunique()}")
    print(f"Mean IP / start    : {df['ip'].mean():.2f}")
    print(f"Mean K / start     : {df['k'].mean():.2f}")
    print(f"Mean ER / start    : {df['er'].mean():.2f}")
    print(f"QS rate            : {df['qs'].mean():.1%}")
    print(f"W rate             : {df['win'].mean():.1%}")
    print(f"CG count           : {df['cg'].sum()}")
    print(f"SHO count          : {df['sho'].sum()}")

    print(f"\nFP distribution:")
    print(f"  mean   = {df['fp'].mean():.2f}")
    print(f"  median = {df['fp'].median():.2f}")
    print(f"  std    = {df['fp'].std():.2f}")
    print(f"  min    = {df['fp'].min():.2f}")
    print(f"  max    = {df['fp'].max():.2f}")
    print(f"  p90    = {df['fp'].quantile(0.9):.2f}")
    print(f"  p10    = {df['fp'].quantile(0.1):.2f}")

    print(f"\nStarts per pitcher (post May 15, >=4 IP):")
    starts_per = df.groupby("pitcher_id").size()
    print(starts_per.describe().round(1).to_string())

    top = (
        df.groupby(["pitcher_id", "pitcher_name"])
        .agg(n=("fp", "size"), fp_mean=("fp", "mean"), k_mean=("k", "mean"),
             ip_mean=("ip", "mean"), er_mean=("er", "mean"))
        .sort_values("fp_mean", ascending=False)
        .head(15)
        .round(2)
    )
    print("\nTop 15 SPs by mean FP/start:")
    print(top.to_string())

    bot = (
        df.groupby(["pitcher_id", "pitcher_name"])
        .agg(n=("fp", "size"), fp_mean=("fp", "mean"))
        .query("n >= 10")
        .sort_values("fp_mean")
        .head(10)
        .round(2)
    )
    print("\nBottom 10 SPs by mean FP/start (n>=10):")
    print(bot.to_string())

    # Sanity check: any rows with weird IP?
    weird = df[(df["ip"] < 4) | (df["ip"] > 9)]
    if len(weird):
        print(f"\n!! {len(weird)} rows with IP outside [4,9] (post-filter):")
        print(weird[["pitcher_name", "game_date", "ip", "outs"]].head(10).to_string())

    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--year", type=int, required=True)
    args = ap.parse_args()
    return report(args.year)


if __name__ == "__main__":
    sys.exit(main())
