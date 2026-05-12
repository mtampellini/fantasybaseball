"""
Build the per-hitter-game analysis dataset: one row per (batter, game_date)
with season-to-date metrics ENTERING that game (i.e., computed over all prior
games in that season only).

Mirror of as_of_features.py for the hitter side.

Inputs:
    data/processed/box_hitters_{year}.parquet   (from pull_box_scores --hitters)
    data/processed/bat_agg_{year}.parquet       (from pull_statcast --hitters)
    data/processed/team_offense_{year}.parquet  (optional, own-team xwOBA)

Output:
    data/processed/hitter_dataset_{year}.parquet

Each row carries:
  - Identity:  batter_id, batter_name, team, opponent, game_date, is_home
  - Target  :  fp (Yahoo fantasy points scored that game, no CYC/SLAM bonus)
  - As-of features (season-to-date entering the game):
      fp_per_g, pa_per_g, n_games_prior
      xwoba, xba_per_bbe, barrel_pct, hard_hit_pct, sweet_spot_pct,
      k_pct, bb_pct, gb_pct, fb_pct, ld_pct,
      iso, hr_per_pa, sb_per_g,
      park_factor, own_team_xwoba
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np
import pandas as pd

from src.yahoo_scoring import HitterWeights, hitter_fp
from src.park_factors import park_factor, TEAMNAME_TO_CODE


ROOT = Path(__file__).resolve().parents[1]
PROC = ROOT / "data" / "processed"


def _expanding_with_lag(df: pd.DataFrame, by: str, sort_cols: list[str]) -> pd.DataFrame:
    """Per-batter cumulative sums strictly prior to current row."""
    df = df.sort_values(sort_cols).reset_index(drop=True)
    num_cols = df.select_dtypes(include="number").columns.tolist()
    num_cols = [c for c in num_cols if c not in (by, "is_home", "game_pk")]
    grouped = df.groupby(by, sort=False)[num_cols]
    cum_inc = grouped.cumsum()
    cum = cum_inc.groupby(df[by]).shift(1).fillna(0).add_prefix("cum_")
    df["n_games_prior"] = grouped.cumcount()
    out = pd.concat([df, cum], axis=1)
    return out


def _safe_div(num, den):
    return np.where(den > 0, num / den, np.nan)


def build_year(year: int) -> pd.DataFrame:
    box_path = PROC / f"box_hitters_{year}.parquet"
    bat_path = PROC / f"bat_agg_{year}.parquet"

    box = pd.read_parquet(box_path)
    if bat_path.exists():
        bat = pd.read_parquet(bat_path)
    else:
        print(f"  WARN: bat_agg_{year}.parquet missing; running without Statcast metrics")
        bat = pd.DataFrame(columns=["game_pk", "batter_id"])

    # ---- target FP (no CYC/SLAM in model target, per design)
    w = HitterWeights.from_file()
    box["fp"] = box.apply(lambda r: hitter_fp(r.to_dict(), w, include_bonuses=False), axis=1)

    # ---- join Statcast per-game stats
    if not bat.empty:
        join_cols = [c for c in bat.columns if c not in ("game_date",)]
        # rename pa to avoid collision with box's pa column (box.pa is AB+BB approx;
        # bat.pa is true PA from woba_denom). Prefer the statcast version.
        box = box.drop(columns=["pa"]) if "pa" in box.columns else box
        box = box.merge(
            bat[join_cols],
            on=["game_pk", "batter_id"],
            how="left",
        )

    for c in ("pa", "bbe", "swings", "whiffs", "hard_hit", "barrels",
              "gb", "ld", "fb", "pu", "sweet", "ks", "bbs",
              "xwoba_sum", "xwoba_n", "xba_sum", "pitches"):
        if c not in box.columns:
            box[c] = 0
        box[c] = pd.to_numeric(box[c], errors="coerce").fillna(0)

    box["game_date"] = pd.to_datetime(box["game_date"]).dt.date.astype(str)

    # ---- cumulative-prior aggregates per batter
    cum = _expanding_with_lag(box, by="batter_id", sort_cols=["batter_id", "game_date"])

    o = pd.DataFrame()
    o["batter_id"] = cum["batter_id"]
    o["batter_name"] = cum["batter_name"]
    o["game_date"] = cum["game_date"]
    o["game_pk"] = cum["game_pk"]
    o["team"] = cum["team"]
    o["opponent"] = cum["opponent"]
    o["is_home"] = cum["is_home"]
    o["position"] = cum["position"]
    o["fp"] = cum["fp"]
    o["n_games_prior"] = cum["n_games_prior"]

    # Box-derived rate features
    ab = cum["cum_ab"]
    pa_box = cum["cum_ab"] + cum["cum_bb"]  # box-derived PA (no HBP/SF)
    pa = cum["cum_pa"].where(cum["cum_pa"] > 0, pa_box)  # prefer statcast PA
    bbe = cum["cum_bbe"]
    g = cum["n_games_prior"]

    o["fp_per_g_prior"] = _safe_div(cum["cum_fp"], g)
    o["pa_per_g_prior"] = _safe_div(pa, g)
    o["ab_per_g_prior"] = _safe_div(ab, g)

    # ISO = (2B + 2*3B + 3*HR) / AB
    o["iso_prior"] = _safe_div(
        cum["cum_2b"] + 2 * cum["cum_3b"] + 3 * cum["cum_hr"],
        ab,
    )
    o["hr_per_pa_prior"] = _safe_div(cum["cum_hr"], pa_box)
    o["sb_per_g_prior"] = _safe_div(cum["cum_sb"], g)
    o["bb_per_pa_prior"] = _safe_div(cum["cum_bb"], pa_box)
    o["k_per_pa_prior"] = _safe_div(cum["cum_k"], pa_box)

    # Statcast features (preferred — uses pitch-level data)
    o["xwoba_prior"] = _safe_div(cum["cum_xwoba_sum"], cum["cum_xwoba_n"])
    o["xba_per_bbe_prior"] = _safe_div(cum["cum_xba_sum"], bbe)
    o["barrel_pct_prior"] = _safe_div(cum["cum_barrels"], bbe)
    o["hard_hit_pct_prior"] = _safe_div(cum["cum_hard_hit"], bbe)
    o["sweet_spot_pct_prior"] = _safe_div(cum["cum_sweet"], bbe)
    o["gb_pct_prior"] = _safe_div(cum["cum_gb"], bbe)
    o["fb_pct_prior"] = _safe_div(cum["cum_fb"], bbe)
    o["ld_pct_prior"] = _safe_div(cum["cum_ld"], bbe)
    # Statcast-derived K/BB rates (denominator = PA-ending events)
    o["k_pct_prior"] = _safe_div(cum["cum_ks"], cum["cum_xwoba_n"])
    o["bb_pct_prior"] = _safe_div(cum["cum_bbs"], cum["cum_xwoba_n"])
    o["whiff_pct_prior"] = _safe_div(cum["cum_whiffs"], cum["cum_swings"])

    # ---- park factor (home park of this game)
    home_team = np.where(o["is_home"] == 1, o["team"], o["opponent"])
    o["park_factor"] = pd.Series(home_team).map(lambda t: park_factor(t)).values

    # ---- own-team offense (lineup quality affects R/RBI)
    to_path = PROC / f"team_offense_{year}.parquet"
    if to_path.exists():
        to = pd.read_parquet(to_path)
        o["_team_code"] = o["team"].map(TEAMNAME_TO_CODE).fillna(o["team"])
        o = o.merge(
            to.rename(columns={"team": "_team_code", "team_xwoba_prior": "own_team_xwoba_prior"})[
                ["_team_code", "game_date", "own_team_xwoba_prior"]
            ],
            on=["_team_code", "game_date"], how="left",
        )
        o = o.drop(columns=["_team_code"])
    else:
        print(f"  WARN: team_offense_{year}.parquet missing")
        o["own_team_xwoba_prior"] = np.nan

    # Filter: in-season analysis cutoff for training years; min prior games
    # for stable features. 2026 keeps all rows (we need the latest per-batter
    # for projection).
    MIN_PRIOR = 20
    if year == 2026:
        final = o[o["n_games_prior"] >= 5].copy()  # loose for projection coverage
    else:
        cutoff = f"{year}-05-15"
        final = o[(o["game_date"] >= cutoff) & (o["n_games_prior"] >= MIN_PRIOR)].copy()

    return final


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--year", type=int, required=True)
    args = ap.parse_args()

    df = build_year(args.year)
    out = PROC / f"hitter_dataset_{args.year}.parquet"
    df.to_parquet(out, index=False)
    print(f"Wrote {out}  ({len(df)} rows, {df['batter_id'].nunique()} batters)")
    print("\nfeature null %:")
    feat_cols = [c for c in df.columns if c.endswith("_prior")]
    print((df[feat_cols].isna().mean() * 100).round(1).sort_values(ascending=False).to_string())
    return 0


if __name__ == "__main__":
    sys.exit(main())
