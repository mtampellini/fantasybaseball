"""
Weekly Monday refresh: pull new 2026 starts since last run, rebuild as-of
features, re-fit model, regenerate 2026_pitcher_projections.csv.

Run:
    python -m src.refresh
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

import pandas as pd

from src.pull_box_scores import pull_range as box_pull, _ip_str_to_outs as _outs
from src.pull_statcast import pull_range as statcast_pull, aggregate_per_game
from src.as_of_features import build_year
from src.project_pitcher import _train_default_model, project_all


ROOT = Path(__file__).resolve().parents[1]
PROC = ROOT / "data" / "processed"
OUT = ROOT / "output"


def refresh():
    year = 2026
    today = time.strftime("%Y-%m-%d")
    print(f"[1/4] Pulling 2026 box scores 2026-03-15 .. {today}")
    box = box_pull("2026-03-15", today, year)
    box = box[box["outs"] >= 12].copy()
    starts_per = box.groupby("pitcher_id").size().rename("n_starts_season")
    box = box.merge(starts_per, left_on="pitcher_id", right_index=True)
    box = box[box["n_starts_season"] >= 5].copy()
    box.to_parquet(PROC / "box_starts_2026.parquet", index=False)
    print(f"      {len(box)} rows, {box['pitcher_id'].nunique()} SPs")

    print(f"[2/4] Pulling 2026 pitch-level Statcast (this can take 20–30 min)")
    pitches = statcast_pull(pd.to_datetime("2026-03-15").date(), pd.to_datetime(today).date())
    agg = aggregate_per_game(pitches)
    agg.to_parquet(PROC / "pitch_agg_2026.parquet", index=False)
    print(f"      {len(agg)} pitcher-game rows")

    print(f"[3/4] Rebuilding 2026 as-of feature dataset")
    df = build_year(2026)
    df.to_parquet(PROC / "sp_dataset_2026.parquet", index=False)
    print(f"      {len(df)} rows after May-15+/>=3 prior starts filter (or season-start for 2026)")

    print(f"[4/4] Re-training model + projecting all 2026 SPs")
    model, feats = _train_default_model()
    proj = project_all(model, feats)
    proj.to_csv(OUT / "2026_pitcher_projections.csv", index=False)
    print(f"      wrote {OUT / '2026_pitcher_projections.csv'}")
    print("\nDone. Top 15 by projected FP/start:")
    print(proj.head(15)[["pitcher_name", "team", "n_starts_prior", "fp_projection"]].to_string(index=False))
    return 0


if __name__ == "__main__":
    sys.exit(refresh())
