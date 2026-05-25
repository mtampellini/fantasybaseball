"""Project each pitcher's expected Yahoo FP per next start.

Forward-looking projection (current default): for each pitcher, compute
season-to-date cumulative skill features from ALL their 2026 starts, apply
Bayesian shrinkage against 2025 baseline, then predict with a Ridge model
trained on 2024+2025 starts (with team OAA as a feature).

Output columns match the legacy schema so render_sp_leaderboard.py keeps
working: pitcher_id, pitcher_name, team, n_starts_prior, fp_projection,
avg_fp_actual, n_starts_actual, plus per-feature columns and prediction
intervals.

Usage:
    python -m src.project_pitcher --all              # rank all 2026 SPs
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.linear_model import Ridge

from src.analysis import FEATURE_COLS, fit_model, load_dataset
from src.park_factors import park_factor, TEAMNAME_TO_CODE
from src.yahoo_scoring import PitcherWeights, pitcher_fp


ROOT = Path(__file__).resolve().parents[1]
PROC = ROOT / "data" / "processed"
OUT = ROOT / "output"

# Feature set: drop team-xwoba (unavailable in 2024/2025 training data) and
# add team_oaa as a defense feature.
FORWARD_FEATS = [f for f in FEATURE_COLS if f not in ("own_team_xwoba_prior", "opp_xwoba_prior")] + ["own_team_oaa"]

# Stabilization sample sizes for Bayesian shrinkage (Russell Carleton).
SHRINK = {
    "k_pct_prior":          ("bf",      70),
    "bb_pct_prior":         ("bf",     170),
    "whiff_pct_prior":      ("swings", 150),
    "csw_pct_prior":        ("pitches",250),
    "hard_hit_pct_prior":   ("bbe",     50),
    "barrel_pct_prior":     ("bbe",     50),
    "gb_pct_prior":         ("bbe",     80),
    "fb_pct_prior":         ("bbe",     80),
    "xwoba_against_prior":  ("bf",     200),
}

# Specific (pitcher-name-substring, game_date) pairs to drop from a pitcher's
# 2026 cumulatives. Use for known atypical outings (e.g., IL-return rust).
STARTS_TO_EXCLUDE = [
    ("Strider", "2026-05-03"),   # rust outing on IL return
]

# Minimum 2026 starts to project for. Was 5; now 2 so recently-returned-from-IL
# pitchers (e.g., Strider) still rank with appropriately wide intervals.
MIN_STARTS_2026 = 2


# ----------------------------------------------------------- team defense
def _load_team_oaa(year: int) -> dict[str, float]:
    p = PROC / f"team_defense_{year}.parquet"
    if not p.exists():
        return {}
    df = pd.read_parquet(p)
    df = df[df.team_savant != "---"]
    return dict(zip(df.team_savant, df.oaa_total))


def _load_2026_oaa_prorated() -> dict[str, float]:
    """2026 OAA is partial-season; prorate to full-season equivalent so the
    feature's magnitude matches the full-season OAA the model was trained on."""
    raw = _load_team_oaa(2026)
    if not raw:
        return {}
    box = pd.read_parquet(PROC / "box_starts_2026.parquet")
    games_per_team = box.groupby("team").game_pk.nunique().mean()
    multiplier = 162.0 / games_per_team if games_per_team else 3.42
    return {t: v * multiplier for t, v in raw.items()}


# ----------------------------------------------------------- training
def _train_default_model():
    """Train Ridge on 2024 + 2025 with team OAA feature attached.

    Returns (model, feature_columns).
    """
    df = load_dataset([2024, 2025])
    if df.empty:
        raise RuntimeError("No training data — pull 2024/2025 first")
    oaa_24 = _load_team_oaa(2024)
    oaa_25 = _load_team_oaa(2025)
    df = df.copy()
    df["own_team_oaa"] = df["team"].map({**oaa_25, **oaa_24}).fillna(0)
    if "season" in df.columns and 2024 in df.season.unique():
        df.loc[df.season == 2024, "own_team_oaa"] = df.loc[df.season == 2024, "team"].map(oaa_24).fillna(0)
    feats = [f for f in FORWARD_FEATS if f in df.columns]
    df_drop = df.dropna(subset=feats)
    return fit_model(df_drop, feats)


def _actual_fp_per_pitcher() -> pd.DataFrame:
    box_path = PROC / "box_starts_2026.parquet"
    if not box_path.exists():
        return pd.DataFrame(columns=["pitcher_id", "avg_fp_actual", "n_starts_actual"])
    box = pd.read_parquet(box_path)
    box = _apply_exclusions(box)
    w = PitcherWeights.from_file()
    box["fp"] = box.apply(lambda r: pitcher_fp(r.to_dict(), w), axis=1)
    agg = box.groupby("pitcher_id").agg(
        avg_fp_actual=("fp", "mean"),
        n_starts_actual=("fp", "size"),
    ).reset_index()
    agg["avg_fp_actual"] = agg["avg_fp_actual"].round(2)
    return agg


# ----------------------------------------------------------- forward features
def _apply_exclusions(box: pd.DataFrame) -> pd.DataFrame:
    """Drop pitcher-date pairs listed in STARTS_TO_EXCLUDE."""
    if not STARTS_TO_EXCLUDE:
        return box
    box = box.copy()
    for name_sub, gd in STARTS_TO_EXCLUDE:
        mask = box["pitcher_name"].str.contains(name_sub, case=False, na=False) & (box["game_date"] == gd)
        if mask.any():
            box = box[~mask]
    return box


def _build_forward_features() -> pd.DataFrame:
    """One row per pitcher with season-to-date cumulative rates from ALL their
    2026 starts. Returns a frame with FORWARD_FEATS columns set."""
    box = pd.read_parquet(PROC / "box_starts_2026.parquet")
    pitch = pd.read_parquet(PROC / "pitch_agg_2026.parquet")

    box = _apply_exclusions(box)
    excluded_gpks = set()
    for name_sub, gd in STARTS_TO_EXCLUDE:
        raw_box = pd.read_parquet(PROC / "box_starts_2026.parquet")
        mask = raw_box["pitcher_name"].str.contains(name_sub, case=False, na=False) & (raw_box["game_date"] == gd)
        excluded_gpks.update(raw_box[mask].game_pk.tolist())
    if excluded_gpks:
        pitch = pitch[~pitch.game_pk.isin(excluded_gpks)]

    box = box.drop(columns=[c for c in ("pitches", "strikes") if c in box.columns])
    join_cols = [c for c in pitch.columns if c not in ("game_date",)]
    combined = box.merge(pitch[join_cols], on=["game_pk", "pitcher_id"], how="left")
    for c in ("pitches", "swings", "whiffs", "cstrikes", "bbe", "hard_hit", "barrels",
             "gb", "ld", "fb", "pu", "xwoba_sum", "xwoba_n"):
        if c not in combined.columns:
            combined[c] = 0
        combined[c] = pd.to_numeric(combined[c], errors="coerce").fillna(0)
    combined["bf_est"] = combined["outs"] + combined["h"] + combined["bb"]

    agg = combined.groupby(["pitcher_id", "pitcher_name", "team"]).agg(
        n_starts_prior=("game_pk", "size"),
        outs=("outs", "sum"),
        h=("h", "sum"), bb=("bb", "sum"), k=("k", "sum"), hr=("hr", "sum"),
        er=("er", "sum"), wins=("win", "sum"), losses=("loss", "sum"),
        pitches=("pitches", "sum"), swings=("swings", "sum"),
        whiffs=("whiffs", "sum"), cstrikes=("cstrikes", "sum"),
        bbe=("bbe", "sum"), hard_hit=("hard_hit", "sum"), barrels=("barrels", "sum"),
        gb=("gb", "sum"), fb=("fb", "sum"), xwoba_sum=("xwoba_sum", "sum"),
        xwoba_n=("xwoba_n", "sum"), bf=("bf_est", "sum"),
        last_date=("game_date", "max"),
    ).reset_index()
    agg = agg[agg.n_starts_prior >= MIN_STARTS_2026].copy()

    ip = agg["outs"] / 3.0
    agg["ip_per_start_prior"] = ip / agg["n_starts_prior"]
    agg["era_prior"] = np.where(ip > 0, agg["er"] * 9.0 / ip, np.nan)
    agg["whip_prior"] = np.where(ip > 0, (agg["h"] + agg["bb"]) / ip, np.nan)
    agg["k_pct_prior"] = np.where(agg["bf"] > 0, agg["k"] / agg["bf"], np.nan)
    agg["bb_pct_prior"] = np.where(agg["bf"] > 0, agg["bb"] / agg["bf"], np.nan)
    agg["k_bb_pct_prior"] = agg["k_pct_prior"] - agg["bb_pct_prior"]
    agg["hr_per_9_prior"] = np.where(ip > 0, agg["hr"] * 9.0 / ip, np.nan)
    agg["wins_prior"] = agg["wins"]
    agg["csw_pct_prior"] = np.where(agg["pitches"] > 0, (agg["cstrikes"] + agg["whiffs"]) / agg["pitches"], np.nan)
    agg["whiff_pct_prior"] = np.where(agg["swings"] > 0, agg["whiffs"] / agg["swings"], np.nan)
    agg["hard_hit_pct_prior"] = np.where(agg["bbe"] > 0, agg["hard_hit"] / agg["bbe"], np.nan)
    agg["barrel_pct_prior"] = np.where(agg["bbe"] > 0, agg["barrels"] / agg["bbe"], np.nan)
    agg["gb_pct_prior"] = np.where(agg["bbe"] > 0, agg["gb"] / agg["bbe"], np.nan)
    agg["fb_pct_prior"] = np.where(agg["bbe"] > 0, agg["fb"] / agg["bbe"], np.nan)
    agg["xwoba_against_prior"] = np.where(agg["xwoba_n"] > 0, agg["xwoba_sum"] / agg["xwoba_n"], np.nan)
    agg["xfip_prior"] = (
        13 * 0.118 * agg["fb"] + 3 * agg["bb"] - 2 * agg["k"]
    ) / ip.replace(0, np.nan) + 3.14
    k_pa = agg["k_pct_prior"].fillna(0)
    bb_pa = agg["bb_pct_prior"].fillna(0)
    gb_pa = np.where(agg["bf"] > 0, agg["gb"] / agg["bf"], 0)
    agg["siera_prior"] = (
        6.145 - 16.986 * k_pa + 11.434 * bb_pa - 1.858 * gb_pa
        + 7.653 * (k_pa ** 2) - 6.664 * (gb_pa ** 2)
        + 10.130 * k_pa * bb_pa - 5.195 * k_pa * gb_pa
    )

    # Neutral game-context (no specific matchup baked in).
    agg["is_home"] = 0.5
    agg["park_factor"] = 100.0
    agg["days_of_rest"] = 5.0
    agg["prior_pitches"] = (agg["pitches"] / agg["n_starts_prior"]).fillna(85)
    agg["own_team_oaa"] = agg["team"].map(_load_2026_oaa_prorated()).fillna(0)

    # Synthetic "game_date" column for legacy schema compatibility = pitcher's last start
    agg["game_date"] = agg["last_date"]
    return agg


def _apply_shrinkage(features: pd.DataFrame) -> pd.DataFrame:
    """Bayesian shrinkage: blend each rate stat with the pitcher's 2025 baseline
    (or league mean fallback), weighted by 2026 sample size."""
    df_25 = load_dataset([2025])
    if df_25.empty:
        return features
    last_25 = df_25.sort_values("game_date").groupby("pitcher_id").tail(1)
    prior = {
        r["pitcher_id"]: {f: r[f] for f in SHRINK.keys() if pd.notna(r.get(f))}
        for _, r in last_25.iterrows()
    }
    df_24 = load_dataset([2024])
    league_means = {f: df_24[f].mean() if not df_24.empty and f in df_24.columns else 0
                    for f in SHRINK.keys()}

    def shrink(obs, prior_val, n, k):
        if pd.isna(obs):
            return prior_val
        if pd.isna(prior_val):
            return obs
        return (n * obs + k * prior_val) / (n + k)

    out = features.copy()
    for feat, (denom_col, k) in SHRINK.items():
        new_vals = []
        for _, r in out.iterrows():
            p = prior.get(r["pitcher_id"], {}).get(feat, league_means[feat])
            n = r.get(denom_col, 0) or 0
            new_vals.append(shrink(r[feat], p, n, k))
        out[feat] = new_vals
    out["k_bb_pct_prior"] = out["k_pct_prior"] - out["bb_pct_prior"]
    return out


# ----------------------------------------------------------- projection
def project_all(model, feats: list[str], with_intervals: bool = True,
                n_boot: int = 200) -> pd.DataFrame:
    """Forward-looking projection for all 2026 SPs.

    Builds season-to-date features (excluding atypical outings configured in
    STARTS_TO_EXCLUDE), applies 2025-baseline shrinkage, predicts with the
    trained model, and optionally adds bootstrap-based 80% intervals.
    """
    features = _build_forward_features()
    features = _apply_shrinkage(features)
    sub = features.dropna(subset=feats).copy()
    if sub.empty:
        return sub

    sub["fp_projection"] = model.predict(sub[feats].values)

    if with_intervals:
        rng = np.random.default_rng(42)
        train = load_dataset([2024, 2025])
        oaa_24 = _load_team_oaa(2024); oaa_25 = _load_team_oaa(2025)
        train = train.copy()
        train["own_team_oaa"] = train["team"].map({**oaa_25, **oaa_24}).fillna(0)
        if "season" in train.columns:
            train.loc[train.season == 2024, "own_team_oaa"] = train.loc[train.season == 2024, "team"].map(oaa_24).fillna(0)
        train = train.dropna(subset=feats)
        X_tr, y_tr = train[feats].values, train.fp.values
        X_pr = sub[feats].values
        boot = np.zeros((n_boot, len(sub)))
        for i in range(n_boot):
            idx = rng.choice(len(X_tr), size=len(X_tr), replace=True)
            m = Ridge(alpha=1.0).fit(X_tr[idx], y_tr[idx])
            boot[i] = m.predict(X_pr)
        sub["model_se"] = boot.std(axis=0)
        df_25 = load_dataset([2025])
        last_25_ids = set(df_25.pitcher_id.unique()) if not df_25.empty else set()
        has_prior = sub["pitcher_id"].isin(last_25_ids).astype(int)
        PRIOR_STARTS_EQUIV = 12
        sub["effective_n"] = sub["n_starts_prior"] + PRIOR_STARTS_EQUIV * has_prior
        sub["sample_se"] = 10.0 / np.sqrt(sub["effective_n"].clip(lower=2))
        sub["total_se"] = np.sqrt(sub["model_se"]**2 + sub["sample_se"]**2)
        sub["lo80"] = sub["fp_projection"] - 1.28 * sub["total_se"]
        sub["hi80"] = sub["fp_projection"] + 1.28 * sub["total_se"]

    # Attach actuals
    actual = _actual_fp_per_pitcher()
    sub = sub.merge(actual, on="pitcher_id", how="left")

    base_cols = ["pitcher_id", "pitcher_name", "team", "game_date",
                 "n_starts_prior", "fp_projection",
                 "avg_fp_actual", "n_starts_actual"] + feats
    if with_intervals:
        base_cols += ["model_se", "sample_se", "total_se", "lo80", "hi80"]
    out = sub[base_cols].sort_values("fp_projection", ascending=False).reset_index(drop=True)
    return out


def project_one(name: str, model, feats: list[str]) -> dict | None:
    """Project a specific pitcher by name (substring, case-insensitive)."""
    out = project_all(model, feats, with_intervals=False)
    hit = out[out["pitcher_name"].str.lower().str.contains(name.lower(), na=False)]
    if hit.empty:
        return None
    row = hit.iloc[0]
    return {
        "pitcher": row["pitcher_name"],
        "team": row["team"],
        "n_starts_prior": int(row["n_starts_prior"]),
        "fp_projection": round(float(row["fp_projection"]), 2),
        "avg_fp_actual": (
            round(float(row["avg_fp_actual"]), 2)
            if pd.notna(row.get("avg_fp_actual")) else None
        ),
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
        print("\nTop 30 by projected FP/start:")
        print(df.head(30)[["pitcher_name", "team", "n_starts_prior",
                           "fp_projection", "avg_fp_actual"]].to_string(index=False))
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
