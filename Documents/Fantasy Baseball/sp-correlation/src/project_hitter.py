"""
Project each 2026 hitter's rest-of-season Yahoo FP using the Ridge model
trained on 2024+2025 trailing-5-week (WINDOW_DAYS) as-of features, so the
projection reflects current form rather than season-to-date averages.

Headline metric: fp_ros_projection = fp_g_projection × games_remaining_est
where games_remaining_est = (player_G / team_G) × (162 - team_G).

Usage:
    python -m src.project_hitter --all
    python -m src.project_hitter "Aaron Judge"
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import pandas as pd

from src.analysis_hitter import FEATURE_COLS, fit_model, load_dataset
from src.as_of_features_hitter import WINDOW_DAYS
from src.yahoo_scoring import HitterWeights, hitter_fp


ROOT = Path(__file__).resolve().parents[1]
PROC = ROOT / "data" / "processed"
OUT = ROOT / "output"
OUT.mkdir(parents=True, exist_ok=True)

SEASON_GAMES = 162


def _train_default_model():
    df = load_dataset([2024, 2025])
    if df.empty:
        raise RuntimeError("No training data — pull 2024/2025 first")
    feats = [f for f in FEATURE_COLS if f in df.columns]
    return fit_model(df, feats)


def _actual_fp_per_batter() -> pd.DataFrame:
    """Mean / count / sum of actual 2026 Yahoo FP per batter (with CYC bonus
    in actuals, but our 2026 data has zero cycles so far). Also computes the
    trailing-5-week (WINDOW_DAYS) actuals to match the model's form window."""
    box_path = PROC / "box_hitters_2026.parquet"
    if not box_path.exists():
        return pd.DataFrame(columns=[
            "batter_id", "avg_fp_actual", "games_played_2026",
            "fp_total_2026", "avg_fp_5wk", "games_5wk", "team",
        ])
    box = pd.read_parquet(box_path)
    w = HitterWeights.from_file()
    box["fp"] = box.apply(lambda r: hitter_fp(r.to_dict(), w, include_bonuses=True), axis=1)
    # latest team per batter (handles in-season trades)
    last_team = (
        box.sort_values("game_date")
        .groupby("batter_id")
        .tail(1)[["batter_id", "team", "position"]]
        .rename(columns={"team": "team_current", "position": "position_current"})
    )
    agg = box.groupby("batter_id").agg(
        avg_fp_actual=("fp", "mean"),
        games_played_2026=("fp", "size"),
        fp_total_2026=("fp", "sum"),
    ).reset_index()
    agg["avg_fp_actual"] = agg["avg_fp_actual"].round(2)

    # Trailing 5 weeks, anchored to the newest game in the data (not today,
    # so a stale box pull doesn't shrink everyone's window)
    dates = pd.to_datetime(box["game_date"])
    window_start = dates.max() - pd.Timedelta(days=WINDOW_DAYS - 1)
    recent = box[dates >= window_start]
    agg5 = recent.groupby("batter_id").agg(
        avg_fp_5wk=("fp", "mean"),
        games_5wk=("fp", "size"),
    ).reset_index()
    agg5["avg_fp_5wk"] = agg5["avg_fp_5wk"].round(2)

    agg = agg.merge(agg5, on="batter_id", how="left")
    agg = agg.merge(last_team, on="batter_id", how="left")
    return agg


def _team_games_played() -> pd.DataFrame:
    """Count unique game_pks per team so far in 2026."""
    box_path = PROC / "box_hitters_2026.parquet"
    if not box_path.exists():
        return pd.DataFrame(columns=["team", "team_games_played"])
    box = pd.read_parquet(box_path)
    tg = box.groupby("team")["game_pk"].nunique().rename("team_games_played").reset_index()
    return tg


def project_all(model, feats: list[str]) -> pd.DataFrame:
    df = load_dataset([2026])
    if df.empty:
        df = load_dataset([2025])
        print("WARN: no 2026 dataset; using 2025 last-row for projection")
    # Pick the latest row per batter that has all features non-null. This
    # avoids dropping stars whose final-game row has a stale team_offense
    # join (team_offense parquet is often a day behind the box pull).
    df_complete = df.dropna(subset=feats)
    last = df_complete.sort_values("game_date").groupby("batter_id").tail(1).copy()
    sub = last
    sub["fp_g_projection"] = model.predict(sub[feats].values).round(3)

    actuals = _actual_fp_per_batter()
    team_g = _team_games_played()

    out = sub.merge(actuals, on="batter_id", how="left")
    # Prefer the current team from actuals (handles trades after the
    # last as-of row). Fall back to the dataset's team.
    out["team"] = out["team_current"].fillna(out["team"])
    out["position"] = out["position_current"].fillna(out["position"])

    out = out.merge(team_g, on="team", how="left")
    out["team_games_played"] = out["team_games_played"].fillna(out["team_games_played"].median())

    # Games-remaining estimate: (player_G / team_G) × (162 − team_G)
    out["games_remaining_est"] = (
        (out["games_played_2026"].fillna(0) / out["team_games_played"]) *
        (SEASON_GAMES - out["team_games_played"])
    ).round(1)

    out["fp_ros_projection"] = (out["fp_g_projection"] * out["games_remaining_est"]).round(1)

    cols = [
        "batter_id", "batter_name", "team", "position",
        "games_played_2026", "team_games_played", "games_remaining_est",
        "fp_g_projection", "avg_fp_actual", "avg_fp_5wk", "games_5wk",
        "fp_total_2026",
        "fp_ros_projection",
        "n_games_prior",
    ] + feats
    out = out[[c for c in cols if c in out.columns]]
    out = out.sort_values("fp_g_projection", ascending=False).reset_index(drop=True)
    return out


def project_one(name: str, model, feats: list[str]) -> dict | None:
    df = load_dataset([2026])
    if df.empty:
        return None
    last = df.sort_values("game_date").groupby("batter_id").tail(1).copy()
    hit = last[last["batter_name"].str.lower().str.contains(name.lower(), na=False)]
    if hit.empty:
        return None
    row = hit.iloc[0]
    sub = row[feats].to_frame().T
    if sub.isna().any().any():
        return {"batter": row["batter_name"], "error": "missing features",
                "missing": sub.columns[sub.isna().iloc[0]].tolist()}
    pred = float(model.predict(sub.values)[0])
    return {
        "batter": row["batter_name"],
        "team": row["team"],
        "n_games_prior": int(row["n_games_prior"]),
        "fp_g_projection": round(pred, 3),
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("name", nargs="?")
    ap.add_argument("--all", action="store_true")
    args = ap.parse_args()

    model, feats = _train_default_model()

    if args.all:
        df = project_all(model, feats)
        out_path = OUT / "2026_hitter_projections.csv"
        df.to_csv(out_path, index=False)
        print(f"Wrote {out_path}  ({len(df)} hitters)")
        print("\nTop 30 by projected FP ROS:")
        show = ["batter_name", "team", "games_played_2026", "team_games_played",
                "games_remaining_est", "fp_g_projection", "avg_fp_actual",
                "fp_ros_projection"]
        print(df.head(30)[show].to_string(index=False))
        return 0

    if not args.name:
        ap.error("provide a hitter name or --all")
    result = project_one(args.name, model, feats)
    if result is None:
        print(f"no match for '{args.name}'", file=sys.stderr)
        return 1
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
