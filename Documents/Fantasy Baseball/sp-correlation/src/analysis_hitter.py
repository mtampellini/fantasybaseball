"""
Correlation + regression analysis on the as-of per-game hitter dataset.

Mirror of analysis.py for hitters. Target = Yahoo FP scored in the game
(no CYC/SLAM bonus — those are scored in actuals only).
"""

from __future__ import annotations

from pathlib import Path
from typing import Iterable

import numpy as np
import pandas as pd
from scipy import stats
from sklearn.linear_model import Ridge
from sklearn.metrics import mean_squared_error, r2_score


ROOT = Path(__file__).resolve().parents[1]
PROC = ROOT / "data" / "processed"
OUT = ROOT / "output"
OUT.mkdir(parents=True, exist_ok=True)


# Curated feature set — redundant pairs trimmed to reduce multicollinearity.
# Dropped: bb_per_pa_prior (vs bb_pct_prior), k_per_pa_prior (vs k_pct_prior),
#          ab_per_g_prior (vs pa_per_g_prior), xba_per_bbe_prior (vs xwoba),
#          gb_pct_prior + ld_pct_prior (vs fb_pct_prior), iso_prior (vs barrel/HR).
FEATURE_COLS = [
    "fp_per_g_prior",       # role + playing time + everything baseline
    "pa_per_g_prior",        # lineup spot / playing time
    "xwoba_prior",           # overall hitting skill
    "barrel_pct_prior",      # power
    "hard_hit_pct_prior",    # contact quality
    "sweet_spot_pct_prior",  # launch angle quality
    "hr_per_pa_prior",       # power realized
    "sb_per_g_prior",        # speed
    "bb_pct_prior",          # plate discipline
    "k_pct_prior",           # whiff propensity
    "fb_pct_prior",          # flyball tendency (with barrel%, isolates power profile)
    "is_home",
    "park_factor",
    "own_team_xwoba_prior",  # lineup context for R/RBI
]


def load_dataset(years: Iterable[int]) -> pd.DataFrame:
    frames = []
    for y in years:
        p = PROC / f"hitter_dataset_{y}.parquet"
        if not p.exists():
            print(f"  missing: {p}")
            continue
        df = pd.read_parquet(p)
        df["season"] = y
        frames.append(df)
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()


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
    return (
        pd.DataFrame(rows)
        .sort_values("pearson_r", key=abs, ascending=False)
        .reset_index(drop=True)
    )


def fit_model(train: pd.DataFrame, features: list[str], alpha: float = 1.0):
    sub = train[features + ["fp"]].dropna()
    X = sub[features].values
    y = sub["fp"].values
    model = Ridge(alpha=alpha, random_state=0)
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


def main():
    df_24 = load_dataset([2024])
    df_25 = load_dataset([2025])
    df_26 = load_dataset([2026])

    combined = pd.concat([df_24, df_25], ignore_index=True)
    print(f"Training pool: 2024+2025 = {len(combined):,} rows, "
          f"{combined['batter_id'].nunique()} batters")
    print(f"Mean FP/G: {combined['fp'].mean():.3f}  Std: {combined['fp'].std():.3f}")

    # 1. correlations
    corr = univariate_correlations(combined)
    print("\n=== Univariate correlations (2024+2025) ===")
    print(corr.head(15).to_string(index=False))
    corr.to_csv(OUT / "hitter_univariate_corr.csv", index=False)

    # 2. single-metric out-of-sample
    print("\n=== Single-metric model: train 2024, test 2025 ===")
    single = single_metric_models(df_24, df_25)
    print(single.head(15).to_string(index=False))
    single.to_csv(OUT / "hitter_single_metric_oos.csv", index=False)

    # 3. full multivariate
    full_feats = [f for f in FEATURE_COLS if f in df_24.columns]
    full_model, _ = fit_model(df_24, full_feats)
    full_metrics = evaluate(full_model, full_feats, df_25)
    print(f"\n=== Full multivariate (Ridge, train 2024, test 2025) ===")
    print(f"  n: {full_metrics['n']:,}  R²: {full_metrics['r2']:.4f}  "
          f"RMSE: {full_metrics['rmse']:.3f}  MAE: {full_metrics['mae']:.3f}")

    # 4. trained on 2024+2025 -> evaluate on 2026 (current season actuals)
    if len(df_26):
        combined_model, _ = fit_model(combined, full_feats)
        m26 = evaluate(combined_model, full_feats, df_26)
        print(f"\n=== Full multivariate (train 2024+2025, test 2026 so-far) ===")
        print(f"  n: {m26['n']:,}  R²: {m26['r2']:.4f}  "
              f"RMSE: {m26['rmse']:.3f}  MAE: {m26['mae']:.3f}")

    # 5. coefficient table for interpretation
    print(f"\n=== Ridge coefficients (train 2024+2025) ===")
    coefs = pd.DataFrame({
        "feature": full_feats,
        "coef": fit_model(combined, full_feats)[0].coef_,
    })
    print(coefs.reindex(coefs["coef"].abs().sort_values(ascending=False).index).to_string(index=False))

    # 6. Per-batter delta on 2026 (current season): who's hot vs cold
    if len(df_26):
        last = df_26.sort_values("game_date").groupby("batter_id").tail(1).copy()
        sub = last.dropna(subset=full_feats)
        sub["fp_g_pred"] = combined_model.predict(sub[full_feats].values)
        # Use per-batter actual FP/G from the 2026 row's fp_per_g_prior (prior-game cumulative)
        sub["delta"] = sub["fp_per_g_prior"] - sub["fp_g_pred"]
        sub = sub.query("n_games_prior >= 25").sort_values("delta")
        cands = sub[["batter_name", "team", "n_games_prior", "fp_per_g_prior", "fp_g_pred", "delta"]]
        print(f"\n=== Top 10 'buy' candidates (underperforming peripherals) ===")
        print(cands.head(10).to_string(index=False))
        print(f"\n=== Top 10 'sell' candidates (overperforming peripherals) ===")
        print(cands.tail(10).iloc[::-1].to_string(index=False))
        cands.to_csv(OUT / "hitter_regression_candidates_2026.csv", index=False)


if __name__ == "__main__":
    main()
