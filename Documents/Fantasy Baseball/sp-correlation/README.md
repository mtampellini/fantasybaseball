# SP Correlation — Yahoo league 41657

Find which pitcher metrics most predict Yahoo fantasy points per start in
"Il Nuovo Vesuvio" (league 41657), and rank pitchers going forward.

## Scoring (fetched 2026-05-11 from Yahoo)

| Stat | Value | | Stat | Value |
|---|---|---|---|---|
| W | +8 | | K | +2 |
| CG | +10 | | IP | +0.25 / IP |
| SHO | +4 | | ER | −2 |
| SV | +6 | | BB | −0.5 |
| QS | +3 | | | |

Notable absences (do not score): L, H, HBP, HLD, BS, HR. The format rewards
strikeouts and innings, mildly penalizes walks and earned runs, and ignores
losses + hits.

## Data scope

- Seasons: 2024 + 2025 (full) + 2026 YTD
- For 2024/2025: only starts on/after May 15
- For 2026: opening day onward (today is pre–May 15)
- Pitcher must have ≥5 starts in season
- Each start: ≥4 IP and listed as game starter (first pitcher to take the mound)
- Each feature row requires ≥3 prior starts in that season

## Pipeline

```
pull_box_scores.py      MLB StatsAPI → per-start box lines (W/L/IP/ER/H/BB/K + QS/CG/SHO flags)
pull_statcast.py        pybaseball.statcast → pitch-level → per-game agg (CSW%, whiff%, hard%, barrel%, GB/FB, xwOBA-PA)
as_of_features.py       joins both, computes season-to-date entering each start, applies filters
analysis.py             correlation + regression, stability, regression candidates
project_pitcher.py      single-pitcher and league-wide projection
refresh.py              weekly Monday refresh
```

## Quick start

```bash
pip install -r requirements.txt

# One-time: fetch league scoring (requires OAuth, falls back to home-dir oauth2.json)
python -m src.fetch_scoring

# Pull data (each year ~10 min box scores + ~30-45 min Statcast)
python -m src.pull_box_scores --year 2024
python -m src.pull_box_scores --year 2025
python -m src.pull_box_scores --year 2026
python -m src.pull_statcast    --year 2024
python -m src.pull_statcast    --year 2025
python -m src.pull_statcast    --year 2026

# Build as-of feature datasets
python -m src.as_of_features --year 2024
python -m src.as_of_features --year 2025
python -m src.as_of_features --year 2026

# Run analysis
python -m src.analysis

# Project all 2026 SPs
python -m src.project_pitcher --all

# Single pitcher
python -m src.project_pitcher "Skubal"

# Monday refresh (re-pulls 2026 only)
python -m src.refresh
```

## Outputs (in /output)

- `univariate_corr.csv` — Pearson/Spearman of each metric vs FP
- `single_metric_oos.csv` — train 2024, test 2025, ranked
- `pair_oos.csv` — best 2-metric combinations
- `stability.csv` — year-over-year metric stability
- `regression_candidates_2026.csv` — over/underperformers (buy/sell)
- `2026_pitcher_projections.csv` — ranked SP list for lineup/waiver
- `findings.md` — narrative summary of what works and what doesn't

## Caveats

- xFIP and SIERA are approximations using simplified formulas with year-level
  HR/FB and FIP constants. Good enough for relative ranking, not for matching
  FanGraphs to 3 decimals.
- Opponent wRC+ as-of is NOT in v1 (would require daily team-batting
  snapshots).
- 2026 has no May 15+ data yet (today is 2026-05-11); 2026 rows come from
  opening day and are used for projection only, not for train/validation.
- `CG` is inferred from box (pitcher's IP equals team total pitching IP and
  ≥8 IP). Roughly equivalent to MLB's CG definition but not strictly the
  same in every edge case.
