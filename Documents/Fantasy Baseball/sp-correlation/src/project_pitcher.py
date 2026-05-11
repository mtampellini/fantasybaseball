"""
Project a single pitcher's expected Yahoo FP per start given their current
season metrics, using a fitted model.

Usage:
    python -m src.project_pitcher "Tarik Skubal"
    python -m src.project_pitcher --all              # rank all 2026 SPs
"""

from __future__ import annotations

import argparse
import json
import pickle
import sys
from pathlib import Path

import numpy as np
import pandas as pd

from src.analysis import FEATURE_COLS, fit_model, load_dataset


ROOT = Path(__file__).resolve().parents[1]
PROC = ROOT / "data" / "processed"
OUT = ROOT / "output"


def _train_default_model():
    """Train Ridge on 2024 + 2025 if available. Returns (model, features)."""
    df = load_dataset([2024, 2025])
    if df.empty:
        raise RuntimeError("No training data — pull 2024/2025 first")
    feats = [f for f in FEATURE_COLS if f in df.columns]
    return fit_model(df, feats)


def _actual_fp_per_pitcher() -> pd.DataFrame:
    """Compute mean / count of actual Yahoo FP per pitcher across all 2026 starts
    (including the early-season ones excluded from the as-of dataset)."""
    from pathlib import Path
    from src.yahoo_scoring import PitcherWeights, pitcher_fp

    box_path = Path(__file__).resolve().parents[1] / "data" / "processed" / "box_starts_2026.parquet"
    if not box_path.exists():
        return pd.DataFrame(columns=["pitcher_id", "avg_fp_actual", "n_starts_actual"])
    box = pd.read_parquet(box_path)
    w = PitcherWeights.from_file()
    box["fp"] = box.apply(lambda r: pitcher_fp(r.to_dict(), w), axis=1)
    agg = box.groupby("pitcher_id").agg(
        avg_fp_actual=("fp", "mean"),
        n_starts_actual=("fp", "size"),
    ).reset_index()
    agg["avg_fp_actual"] = agg["avg_fp_actual"].round(2)
    return agg


def project_all(model, feats: list[str]) -> pd.DataFrame:
    """Project each 2026 pitcher's FP/start using their most-recent as-of row."""
    df = load_dataset([2026])
    if df.empty:
        # fall back to last 2025 row if 2026 not yet pulled
        df = load_dataset([2025])
    last = df.sort_values("game_date").groupby("pitcher_id").tail(1).copy()
    sub = last.dropna(subset=feats)
    sub["fp_projection"] = model.predict(sub[feats].values)

    # Attach actual mean FP scored in 2026 (from the raw box data — includes
    # the pitcher's first 3 starts that were excluded from the as-of dataset)
    actual = _actual_fp_per_pitcher()
    sub = sub.merge(actual, on="pitcher_id", how="left")

    cols = ["pitcher_id", "pitcher_name", "team", "game_date",
            "n_starts_prior", "fp_projection",
            "avg_fp_actual", "n_starts_actual"] + feats
    out = sub[cols].sort_values("fp_projection", ascending=False).reset_index(drop=True)
    return out


def project_one(name: str, model, feats: list[str]) -> dict | None:
    """Project a specific pitcher by (substring, case-insensitive) name."""
    df = load_dataset([2026])
    if df.empty:
        df = load_dataset([2025])
    last = df.sort_values("game_date").groupby("pitcher_id").tail(1).copy()
    hit = last[last["pitcher_name"].str.lower().str.contains(name.lower(), na=False)]
    if hit.empty:
        return None
    row = hit.iloc[0]
    sub = row[feats].to_frame().T
    if sub.isna().any().any():
        return {"pitcher": row["pitcher_name"], "error": "missing features", "missing": sub.columns[sub.isna().iloc[0]].tolist()}
    pred = float(model.predict(sub.values)[0])
    return {
        "pitcher": row["pitcher_name"],
        "team": row["team"],
        "n_starts_prior": int(row["n_starts_prior"]),
        "as_of_date": row["game_date"],
        "fp_projection": round(pred, 2),
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("name", nargs="?", help="pitcher name (substring match)")
    ap.add_argument("--all", action="store_true", help="rank all 2026 SPs")
    args = ap.parse_args()

    model, feats = _train_default_model()

    if args.all:
        df = project_all(model, feats)
        out_path = OUT / "2026_pitcher_projections.csv"
        df.to_csv(out_path, index=False)
        print(f"Wrote {out_path}  ({len(df)} pitchers)")
        print(f"\nTop 30 by projected FP/start:")
        print(df.head(30)[["pitcher_name", "team", "n_starts_prior", "fp_projection"]].to_string(index=False))
        return 0

    if not args.name:
        ap.error("provide a pitcher name or --all")

    result = project_one(args.name, model, feats)
    if result is None:
        print(f"no match for '{args.name}'", file=sys.stderr)
        return 1
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
