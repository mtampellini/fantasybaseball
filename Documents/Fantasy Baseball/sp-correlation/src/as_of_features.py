"""
Build the per-start analysis dataset: one row per (pitcher, game_date) with
season-to-date metrics ENTERING that start (i.e., computed over all prior
starts in that season only).

Inputs:
    data/processed/box_starts_{year}.parquet    (from pull_box_scores)
    data/processed/pitch_agg_{year}.parquet     (from pull_statcast)
    data/raw/opp_wrc_{year}.csv                 (team-level wRC+ as-of, optional)

Output:
    data/processed/sp_dataset_{year}.parquet

Each row carries:
  - Identity:  pitcher_id, pitcher_name, team, opponent, game_date, is_home
  - Target  :  fp (Yahoo fantasy points scored that game)
  - As-of features (season-to-date entering the start):
      k_pct, bb_pct, k_bb_pct,
      whiff_pct, csw_pct, hard_hit_pct, barrel_pct,
      gb_pct, fb_pct,
      xwoba_against,
      era, whip, fip_approx, xfip_approx, siera_approx,
      ip_per_start, n_starts_prior,
      wins, losses,
      hr_per_9
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np
import pandas as pd

from src.yahoo_scoring import PitcherWeights, pitcher_fp
from src.park_factors import park_factor, TEAMNAME_TO_CODE


ROOT = Path(__file__).resolve().parents[1]
PROC = ROOT / "data" / "processed"

# League-year constants (approximate, for xFIP). Source: FanGraphs leaderboards.
# HR/FB% league rates and xFIP/SIERA constants by year.
HR_FB_RATE = {2024: 0.118, 2025: 0.116, 2026: 0.118}     # placeholder updates
XFIP_CONST = {2024: 3.13, 2025: 3.16, 2026: 3.14}


def _expanding_with_lag(df: pd.DataFrame, by: str, sort_cols: list[str]) -> pd.DataFrame:
    """For each pitcher, return cumulative sums *strictly prior* to the current
    row (excluding current row). The shift must be done WITHIN each pitcher's
    group — a global .shift() would leak pitcher A's last cumulative value into
    pitcher B's first row."""
    df = df.sort_values(sort_cols).reset_index(drop=True)
    num_cols = df.select_dtypes(include="number").columns.tolist()
    num_cols = [c for c in num_cols if c not in (by, "is_home", "game_pk")]
    grouped = df.groupby(by, sort=False)[num_cols]
    # cumulative INCLUDING current row, then shift by 1 WITHIN each pitcher
    cum_inc = grouped.cumsum()
    cum = cum_inc.groupby(df[by]).shift(1).fillna(0).add_prefix("cum_")
    df["n_starts_prior"] = grouped.cumcount()
    out = pd.concat([df, cum], axis=1)
    return out


def _safe_div(num, den):
    return np.where(den > 0, num / den, np.nan)


def build_year(year: int) -> pd.DataFrame:
    """Build the as-of per-start dataset for one season."""
    box_path = PROC / f"box_starts_{year}.parquet"
    pitch_path = PROC / f"pitch_agg_{year}.parquet"

    box = pd.read_parquet(box_path)
    if pitch_path.exists():
        pitch = pd.read_parquet(pitch_path)
    else:
        print(f"  WARN: pitch_agg_{year}.parquet missing; running without Statcast metrics")
        pitch = pd.DataFrame(columns=["game_pk", "pitcher_id"])

    # ---- target FP for each start
    w = PitcherWeights.from_file()
    box["fp"] = box.apply(lambda r: pitcher_fp(r.to_dict(), w), axis=1)

    # ---- join pitch-level per-game stats
    # box already has 'pitches'/'strikes' from the box line; drop them so
    # pitch_agg's counts (computed from pitch-level data) win.
    if not pitch.empty:
        box = box.drop(columns=[c for c in ("pitches", "strikes") if c in box.columns])
        join_cols = [c for c in pitch.columns if c not in ("game_date",)]
        box = box.merge(
            pitch[join_cols],
            on=["game_pk", "pitcher_id"],
            how="left",
        )
    # Some pitches columns may now be missing for the pitcher (e.g., if statcast
    # had gaps). Fill with 0 / NaN so downstream cumulative sums behave.
    for c in ("pitches", "swings", "whiffs", "cstrikes", "bbe",
              "hard_hit", "barrels", "gb", "ld", "fb", "pu",
              "xwoba_sum", "xwoba_n"):
        if c not in box.columns:
            box[c] = 0
        box[c] = pd.to_numeric(box[c], errors="coerce").fillna(0)

    # Derived per-start helpers needed for cum sums
    box["bf_est"] = box["outs"] + box["h"] + box["bb"]   # batters faced estimate

    # Sort by pitcher then date
    box["game_date"] = pd.to_datetime(box["game_date"]).dt.date.astype(str)

    # ---- days of rest + prior pitch count (computed BEFORE cumulative, both
    #      are simple within-pitcher lagged features)
    box = box.sort_values(["pitcher_id", "game_date"]).reset_index(drop=True)
    box["prev_date"] = box.groupby("pitcher_id")["game_date"].shift(1)
    box["days_of_rest"] = (
        pd.to_datetime(box["game_date"]) - pd.to_datetime(box["prev_date"])
    ).dt.days
    # Cap absurd values (long IL stints) at 30 so they don't blow up the model
    box["days_of_rest"] = box["days_of_rest"].clip(upper=30).fillna(5)
    box["prior_pitches"] = box.groupby("pitcher_id")["pitches"].shift(1).fillna(0)

    # ---- cumulative-prior aggregates per pitcher
    cum = _expanding_with_lag(box, by="pitcher_id", sort_cols=["pitcher_id", "game_date"])

    # Build features
    o = pd.DataFrame()
    o["pitcher_id"] = cum["pitcher_id"]
    o["pitcher_name"] = cum["pitcher_name"]
    o["game_date"] = cum["game_date"]
    o["game_pk"] = cum["game_pk"]
    o["team"] = cum["team"]
    o["opponent"] = cum["opponent"]
    o["is_home"] = cum["is_home"]
    o["fp"] = cum["fp"]
    o["n_starts_prior"] = cum["n_starts_prior"]

    # Rate stats using cumulative-prior columns
    bf = cum["cum_bf_est"]
    ip = cum["cum_outs"] / 3.0

    o["ip_per_start_prior"] = _safe_div(cum["cum_outs"] / 3.0, cum["n_starts_prior"])
    o["era_prior"] = _safe_div(cum["cum_er"] * 9.0, ip)
    o["whip_prior"] = _safe_div(cum["cum_h"] + cum["cum_bb"], ip)
    o["k_pct_prior"] = _safe_div(cum["cum_k"], bf)
    o["bb_pct_prior"] = _safe_div(cum["cum_bb"], bf)
    o["k_bb_pct_prior"] = o["k_pct_prior"] - o["bb_pct_prior"]
    o["hr_per_9_prior"] = _safe_div(cum["cum_hr"] * 9.0, ip)
    o["wins_prior"] = cum["cum_win"]
    o["losses_prior"] = cum["cum_loss"]

    # Statcast rates (denominators from pitch-level cumulatives)
    pitches_cum = cum["cum_pitches"]
    swings_cum = cum["cum_swings"]
    bbe_cum = cum["cum_bbe"]
    o["csw_pct_prior"] = _safe_div(cum["cum_cstrikes"] + cum["cum_whiffs"], pitches_cum)
    o["whiff_pct_prior"] = _safe_div(cum["cum_whiffs"], swings_cum)
    o["hard_hit_pct_prior"] = _safe_div(cum["cum_hard_hit"], bbe_cum)
    o["barrel_pct_prior"] = _safe_div(cum["cum_barrels"], bbe_cum)
    o["gb_pct_prior"] = _safe_div(cum["cum_gb"], bbe_cum)
    o["fb_pct_prior"] = _safe_div(cum["cum_fb"], bbe_cum)
    o["xwoba_against_prior"] = _safe_div(cum["cum_xwoba_sum"], cum["cum_xwoba_n"])

    # xFIP / SIERA approximations
    yr_hrfb = HR_FB_RATE.get(year, 0.117)
    yr_const = XFIP_CONST.get(year, 3.14)
    fb_cum = cum["cum_fb"]
    # xFIP: ((13*lgHRFB*FB) + (3*(BB+HBP)) - (2*K)) / IP + const
    o["xfip_prior"] = (
        (13 * yr_hrfb * fb_cum + 3 * cum["cum_bb"] - 2 * cum["cum_k"]) / ip.replace(0, np.nan)
    ) + yr_const

    # SIERA approximation (Baseball Prospectus 2010 paper formula).
    k_pa = o["k_pct_prior"].fillna(0)
    bb_pa = o["bb_pct_prior"].fillna(0)
    gb_pa = _safe_div(cum["cum_gb"], bf)
    gb_pa = pd.Series(gb_pa).fillna(0)
    o["siera_prior"] = (
        6.145
        - 16.986 * k_pa
        + 11.434 * bb_pa
        - 1.858 * gb_pa
        + 7.653 * (k_pa ** 2)
        - 6.664 * (gb_pa ** 2)
        + 10.130 * k_pa * bb_pa
        - 5.195 * k_pa * gb_pa
    )

    # ---- attach days_of_rest and prior_pitches (already on `cum`)
    o["days_of_rest"] = cum["days_of_rest"]
    o["prior_pitches"] = cum["prior_pitches"]

    # ---- park factor (based on game's home team)
    home_team = np.where(o["is_home"] == 1, o["team"], o["opponent"])
    o["park_factor"] = pd.Series(home_team).map(lambda t: park_factor(t)).values

    # ---- team offense (own team + opponent) wRC+ proxy
    to_path = PROC / f"team_offense_{year}.parquet"
    if to_path.exists():
        to = pd.read_parquet(to_path)
        # Map our team-name strings to the tricodes used in team_offense
        o["_team_code"] = o["team"].map(TEAMNAME_TO_CODE).fillna(o["team"])
        o["_opp_code"] = o["opponent"].map(TEAMNAME_TO_CODE).fillna(o["opponent"])

        # Join own-team offense
        o = o.merge(
            to.rename(columns={"team": "_team_code", "team_xwoba_prior": "own_team_xwoba_prior"})[
                ["_team_code", "game_date", "own_team_xwoba_prior"]
            ],
            on=["_team_code", "game_date"], how="left",
        )
        # Join opponent offense
        o = o.merge(
            to.rename(columns={"team": "_opp_code", "team_xwoba_prior": "opp_xwoba_prior"})[
                ["_opp_code", "game_date", "opp_xwoba_prior"]
            ],
            on=["_opp_code", "game_date"], how="left",
        )
        o = o.drop(columns=["_team_code", "_opp_code"])
    else:
        print(f"  WARN: team_offense_{year}.parquet missing; running without team-offense features")
        o["own_team_xwoba_prior"] = np.nan
        o["opp_xwoba_prior"] = np.nan

    # Filter: ≥3 prior starts always; May 15+ cutoff applies to 2024/2025 only.
    # 2026 is current and we need its rows for projections regardless of date.
    if year == 2026:
        final = o[o["n_starts_prior"] >= 3].copy()
    else:
        cutoff = f"{year}-05-15"
        final = o[(o["game_date"] >= cutoff) & (o["n_starts_prior"] >= 3)].copy()

    return final


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--year", type=int, required=True)
    args = ap.parse_args()

    df = build_year(args.year)
    out = PROC / f"sp_dataset_{args.year}.parquet"
    df.to_parquet(out, index=False)
    print(f"Wrote {out}  ({len(df)} rows, {df['pitcher_id'].nunique()} SPs)")
    print("\nfeature null %:")
    feat_cols = [c for c in df.columns if c.endswith("_prior")]
    print((df[feat_cols].isna().mean() * 100).round(1).sort_values(ascending=False).to_string())
    return 0


if __name__ == "__main__":
    sys.exit(main())
