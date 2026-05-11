"""
Correlation + regression analysis on the as-of per-start dataset.

Deliverables:
    - Pearson/Spearman per metric vs FP
    - OLS / Ridge multivariate models
    - Out-of-sample test (train 2024, test 2025+2026)
    - Stability scores per metric (year-over-year)
    - Regression candidates (predicted - actual)
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

import numpy as np
import pandas as pd
from scipy import stats
from sklearn.linear_model import LinearRegression, Ridge
from sklearn.metrics import mean_squared_error, r2_score


ROOT = Path(__file__).resolve().parents[1]
PROC = ROOT / "data" / "processed"
OUT = ROOT / "output"
OUT.mkdir(parents=True, exist_ok=True)


FEATURE_COLS = [
    "k_pct_prior", "bb_pct_prior", "k_bb_pct_prior",
    "csw_pct_prior", "whiff_pct_prior",
    "hard_hit_pct_prior", "barrel_pct_prior",
    "gb_pct_prior", "fb_pct_prior",
    "xwoba_against_prior",
    "era_prior", "whip_prior",
    "xfip_prior", "siera_prior",
    "ip_per_start_prior", "hr_per_9_prior",
    "wins_prior",
    "is_home",
    # Phase 2 additions:
    "park_factor",
    "opp_xwoba_prior",
    "own_team_xwoba_prior",
    "days_of_rest",
    "prior_pitches",
]


def load_dataset(years: Iterable[int]) -> pd.DataFrame:
    frames = []
    for y in years:
        p = PROC / f"sp_dataset_{y}.parquet"
        if not p.exists():
            print(f"  missing: {p}")
            continue
        df = pd.read_parquet(p)
        df["season"] = y
        frames.append(df)
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()


# ----------------------------------------------------------- correlations

def univariate_correlations(df: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for col in FEATURE_COLS:
        if col not in df.columns:
            continue
        sub = df[[col, "fp"]].dropna()
        if len(sub) < 30:
            continue
        r_pear, p_pear = stats.pearsonr(sub[col], sub["fp"])
        r_spear, p_spear = stats.spearmanr(sub[col], sub["fp"])
        rows.append({
            "feature": col,
            "n": len(sub),
            "pearson_r": r_pear,
            "pearson_p": p_pear,
            "spearman_r": r_spear,
            "spearman_p": p_spear,
        })
    out = pd.DataFrame(rows).sort_values("pearson_r", key=abs, ascending=False)
    return out.reset_index(drop=True)


# ----------------------------------------------------------- regression

def fit_model(train: pd.DataFrame, features: list[str], model=None):
    sub = train[features + ["fp"]].dropna()
    X = sub[features].values
    y = sub["fp"].values
    if model is None:
        model = Ridge(alpha=1.0, random_state=0)
    model.fit(X, y)
    return model, features


def evaluate(model, features: list[str], df: pd.DataFrame) -> dict:
    sub = df[features + ["fp"]].dropna()
    if sub.empty:
        return {"n": 0, "rmse": np.nan, "r2": np.nan, "mae": np.nan}
    y_pred = model.predict(sub[features].values)
    y_true = sub["fp"].values
    return {
        "n": len(sub),
        "rmse": float(np.sqrt(mean_squared_error(y_true, y_pred))),
        "r2":   float(r2_score(y_true, y_pred)),
        "mae":  float(np.mean(np.abs(y_pred - y_true))),
    }


# --------------------------------------------------------- single + pair

def single_metric_models(train: pd.DataFrame, test: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for f in FEATURE_COLS:
        if f not in train.columns:
            continue
        model, feats = fit_model(train, [f])
        m = evaluate(model, feats, test)
        m["feature"] = f
        rows.append(m)
    return pd.DataFrame(rows).sort_values("r2", ascending=False).reset_index(drop=True)


def best_pair(train: pd.DataFrame, test: pd.DataFrame, top_k: int = 8) -> pd.DataFrame:
    # Pick top-k single features by train R^2 first to limit pair count
    singles = single_metric_models(train, train)  # in-sample
    candidates = singles.dropna(subset=["r2"]).head(top_k)["feature"].tolist()
    rows = []
    for i, a in enumerate(candidates):
        for b in candidates[i + 1:]:
            model, feats = fit_model(train, [a, b])
            m = evaluate(model, feats, test)
            m["features"] = f"{a} + {b}"
            rows.append(m)
    return pd.DataFrame(rows).sort_values("r2", ascending=False).reset_index(drop=True)


# ----------------------------------------------------------- stability

def stability(df_by_year: dict[int, pd.DataFrame]) -> pd.DataFrame:
    """For each feature, correlate 2024 season-end value vs 2025 season-end value
    over pitchers who appear in both years (≥20 starts each)."""
    if not all(y in df_by_year for y in (2024, 2025)):
        return pd.DataFrame()

    # Take each pitcher's LAST row in each season as the season-end value
    def season_end(df):
        s = df.sort_values("game_date")
        last = s.groupby("pitcher_id").tail(1)
        n_starts = df.groupby("pitcher_id").size().rename("n_starts")
        return last.merge(n_starts, on="pitcher_id")

    a = season_end(df_by_year[2024])
    b = season_end(df_by_year[2025])
    merged = a.merge(b, on="pitcher_id", suffixes=("_24", "_25"))
    merged = merged[(merged["n_starts_24"] >= 15) & (merged["n_starts_25"] >= 15)]

    rows = []
    for f in FEATURE_COLS:
        col24 = f"{f}_24"
        col25 = f"{f}_25"
        if col24 not in merged or col25 not in merged:
            continue
        sub = merged[[col24, col25]].dropna()
        if len(sub) < 20:
            continue
        r, p = stats.pearsonr(sub[col24], sub[col25])
        rows.append({"feature": f, "n_pitchers": len(sub), "yoy_pearson_r": r, "p": p})
    return pd.DataFrame(rows).sort_values("yoy_pearson_r", ascending=False).reset_index(drop=True)


# -------------------------------------------------- regression candidates

def regression_candidates(model, features: list[str], df_2026: pd.DataFrame) -> pd.DataFrame:
    sub = df_2026[features + ["fp", "pitcher_id", "pitcher_name", "game_date"]].dropna(subset=features)
    sub["fp_pred"] = model.predict(sub[features].values)
    per_pitcher = (
        sub.groupby(["pitcher_id", "pitcher_name"])
        .agg(n=("fp", "size"), fp_actual=("fp", "mean"), fp_pred=("fp_pred", "mean"))
        .reset_index()
    )
    per_pitcher["delta"] = per_pitcher["fp_actual"] - per_pitcher["fp_pred"]
    per_pitcher = per_pitcher.query("n >= 3").sort_values("delta")
    return per_pitcher


def main():
    df_24 = load_dataset([2024])
    df_25 = load_dataset([2025])
    df_26 = load_dataset([2026])

    # 1. correlations on combined 2024+2025
    combined = pd.concat([df_24, df_25], ignore_index=True)
    corr = univariate_correlations(combined)
    print("=== Univariate correlations (2024+2025) ===")
    print(corr.head(15).to_string(index=False))
    corr.to_csv(OUT / "univariate_corr.csv", index=False)

    # 2. single-metric out-of-sample
    print("\n=== Single-metric model: train 2024, test 2025 ===")
    single = single_metric_models(df_24, df_25)
    print(single.head(15).to_string(index=False))
    single.to_csv(OUT / "single_metric_oos.csv", index=False)

    # 3. best pair
    print("\n=== Best pairs (train 2024, test 2025) ===")
    pair = best_pair(df_24, df_25)
    print(pair.head(10).to_string(index=False))
    pair.to_csv(OUT / "pair_oos.csv", index=False)

    # 4. full multivariate
    full_feats = [f for f in FEATURE_COLS if f in df_24.columns]
    full_model, _ = fit_model(df_24, full_feats)
    full_metrics = evaluate(full_model, full_feats, df_25)
    print(f"\n=== Full multivariate (Ridge): {full_metrics}")

    # 5. stability
    stab = stability({2024: df_24, 2025: df_25})
    print("\n=== Stability (year-over-year r) ===")
    print(stab.to_string(index=False))
    stab.to_csv(OUT / "stability.csv", index=False)

    # 6. regression candidates 2026
    if len(df_26):
        cands = regression_candidates(full_model, full_feats, df_26)
        print("\n=== Top 'buy' candidates (underperforming peripherals) ===")
        print(cands.head(15).to_string(index=False))
        print("\n=== Top 'sell' candidates (overperforming peripherals) ===")
        print(cands.tail(15).iloc[::-1].to_string(index=False))
        cands.to_csv(OUT / "regression_candidates_2026.csv", index=False)


if __name__ == "__main__":
    main()
