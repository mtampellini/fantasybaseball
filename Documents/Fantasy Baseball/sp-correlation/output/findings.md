# SP Correlation Findings — Yahoo league 41657

**Generated** 2026-05-11 · **Training data** 2024 + 2025 analytical rows on/after May 15 (full-season cumulatives from opening day) · **Test/projection** 2025 OOS + 2026 YTD

---

## Bottom line

For predicting your Yahoo fantasy points per start, three things matter:

1. **K% is the single best predictor.** No other metric is close.
2. **SIERA and xFIP beat ERA** at predicting next-start FP — and they're 2× more stable year-over-year.
3. **Wins entering the start are noise** for projection. Year-over-year stability is 0.30 — barely better than random. Ignore them when ranking.

Single-game FP variance is high (RMSE ≈ 10 FP, full-model R² = 0.06), so don't expect to predict any one start tightly. Where the signal IS strong is in **ranking pitchers by skill**: aggregate over 5+ starts and the K%/SIERA leaders separate cleanly from the field.

---

## 1. Univariate correlations (2024+2025, n=5,604 starts)

Strongest predictors of FP scored in a start (using metrics entering that start):

| Rank | Feature              | Pearson r |
|------|----------------------|-----------|
| 1    | **K%**               | **+0.240** |
| 2    | K-BB%                | +0.228 |
| 3    | xFIP                 | −0.222 |
| 4    | Whiff%               | +0.216 |
| 5    | SIERA                | −0.209 |
| 6    | CSW%                 | +0.204 |
| 7    | xwOBA against        | −0.190 |
| 8    | WHIP                 | −0.153 |
| 9    | IP / start           | +0.144 |
| 10   | **ERA**              | **−0.127** |
| 11   | Wins                 | +0.114 |
| 12   | HR/9                 | −0.089 |
| 13   | Hard-hit %           | −0.083 |
| 14   | Barrel %             | −0.064 |
| 15   | is_home              | +0.061 |

**Takeaway:** Strikeout-driven metrics dominate. ERA — the most-quoted pitcher stat — is the WEAKEST of the meaningful peripherals at predicting next start FP. xFIP and SIERA (estimators that strip out luck) outperform ERA by 2×.

---

## 2. Out-of-sample test — train 2024, predict 2025

| Model | R² | RMSE | MAE |
|---|---|---|---|
| Best single (K%) | 0.061 | 9.96 | 8.15 |
| Best pair (xFIP + Whiff%) | 0.064 | 9.95 | 8.12 |
| **Full multivariate (Ridge)** | **0.078** | **9.87** | **8.03** |

The full multivariate model adds only marginal value over K% alone. For practical purposes you can think of "K% + a tiebreaker among SIERA/xFIP/xwOBA" and not lose much.

---

## 3. Stability (year-over-year r, 2024 → 2025, n=56 SPs with ≥15 starts both years)

How well does each metric predict itself the following season? This matters most for projection.

| Rank | Metric              | YoY r | Verdict |
|------|---------------------|-------|---------|
| 1    | **GB%**             | **0.79** | very sticky |
| 2    | Whiff%              | 0.74 | very sticky |
| 3    | SIERA               | 0.72 | sticky |
| 4    | K%                  | 0.71 | sticky |
| 5    | xFIP                | 0.69 | sticky |
| 6    | K-BB%               | 0.69 | sticky |
| 7    | FB%                 | 0.63 | moderate |
| 8    | xwOBA against       | 0.62 | moderate |
| 9    | CSW%                | 0.59 | moderate |
| 10   | BB%                 | 0.58 | moderate |
| 11   | Hard-hit %          | 0.52 | weak |
| 12   | WHIP                | 0.47 | weak |
| 13   | Barrel %            | 0.46 | weak |
| 14   | HR/9                | 0.44 | weak |
| 15   | **ERA**             | **0.32** | unstable |
| 16   | Wins                | 0.23 | noise |
| 17   | IP/start            | 0.20 | noise |

**ERA is twice as volatile as SIERA year-over-year.** If you're projecting forward, use SIERA/xFIP, not ERA.

---

## 4. Combined score (predictive power × stability)

A metric is useful for ranking when it (a) correlates with FP and (b) carries that signal forward. Multiplying same-year predictive r by next-year stability r gives a combined utility:

| Metric         | Predictive |r| | Stability r | Utility |
|----------------|----------------|-------------|---------|
| **K%**         | 0.240          | 0.710       | **0.170** |
| K-BB%          | 0.228          | 0.689       | 0.157 |
| **Whiff%**     | 0.216          | 0.740       | **0.160** |
| **xFIP**       | 0.222          | 0.690       | **0.153** |
| **SIERA**      | 0.209          | 0.724       | **0.151** |
| xwOBA against  | 0.190          | 0.622       | 0.118 |
| CSW%           | 0.204          | 0.594       | 0.121 |
| ERA            | 0.127          | 0.324       | 0.041 |
| Wins entering  | 0.114          | 0.229       | 0.026 |

**K%, Whiff%, xFIP, and SIERA are the core.** All near-tied on utility. xwOBA against is a tier below but adds independent contact-quality signal.

---

## 5. Non-linearity check

Quintile-bucketed mean FP/start (see notebook chart 5) shows the relationships are mostly monotonic — a high-K% pitcher's bucket beats the next-lower bucket consistently. There's no obvious threshold effect (e.g., "K-BB% above 20% is special"); the relationship is roughly linear across the full range, which is why the simple linear/Ridge model captures most of what's there.

---

## 6. Regression candidates — 2026 YTD (≥3 starts)

Pitchers whose 2026 results are far from what their peripherals predict. Smaller samples → noisier; weighting toward longer track records is sensible.

### BUY (actual << projected — likely to improve)

| Pitcher | n | Actual FP | Projected FP | Delta |
|---|---|---|---|---|
| MacKenzie Gore | 4 | 2.1 | 12.5 | **−10.4** |
| Sandy Alcantara | 6 | 2.2 | 12.1 | −9.9 |
| Adrian Houser | 4 | −2.2 | 7.4 | −9.6 |
| Kyle Freeland | 3 | −0.1 | 9.3 | −9.4 |
| Simeon Woods Richardson | 5 | −4.4 | 4.8 | −9.2 |
| Luis Castillo | 3 | −0.1 | 7.2 | −7.3 |
| Jack Leiter | 4 | 6.8 | 13.5 | −6.8 |
| **Kevin Gausman** | 5 | 7.4 | 14.1 | −6.7 |
| **Aaron Nola** | 5 | 5.5 | 11.8 | −6.2 |
| **Jesús Luzardo** | 4 | 13.3 | 19.0 | −5.7 |

Gausman, Nola, Luzardo are the recognizable names — their K%/xFIP say "good", their ER totals say "bad". History suggests the peripherals win.

### SELL (actual >> projected — likely to drop)

| Pitcher | n | Actual FP | Projected FP | Delta |
|---|---|---|---|---|
| Chris Martin | 5 | 21.4 | 8.7 | +12.7 |
| **Chris Sale** | 5 | 24.4 | 12.6 | +11.7 |
| Will Warren | 4 | 20.1 | 10.5 | +9.6 |
| Kyle Harrison | 3 | 21.0 | 12.7 | +8.3 |
| **Paul Skenes** | 4 | 19.5 | 11.4 | +8.1 |
| Shota Imanaga | 5 | 19.9 | 12.6 | +7.2 |
| **Tyler Glasnow** | 3 | 22.2 | 15.1 | +7.1 |
| **Shohei Ohtani** | 3 | 18.1 | 11.8 | +6.3 |

Caveat: small samples — these deltas could be the peripherals catching up (positive regression), not the actual FP dropping. Skenes and Ohtani in particular have such small 2026 samples that the model is using mostly K% from a few starts. Track these over the next 2-3 starts before acting.

---

## 7. Top 30 projected SPs for 2026 going forward

Ranked by projected FP/start using their current 2026 metrics. Full list in `output/2026_pitcher_projections.csv` (128 pitchers).

1. Jacob Misiorowski — 17.57
2. Dylan Cease — 16.53
3. Tyler Glasnow — 16.44
4. Jesús Luzardo — 15.35
5. Cristopher Sánchez — 14.58
6. Gavin Williams — 14.53
7. Landen Roupp — 14.41
8. Jack Leiter — 13.93
9. Chase Burns — 13.90
10. Nolan McLean — 13.88
11. Will Warren — 13.83 *(see SELL caveat)*
12. Emmet Sheehan — 13.76
13. Kyle Harrison — 13.69
14. Shota Imanaga — 13.58
15. Ryan Weathers — 13.48
16. Jacob deGrom — 13.47
17. Chris Sale — 13.44
18. Reid Detmers — 12.99
19. Shohei Ohtani — 12.96
20. Brady Bubic — 12.95
21. Cam Schlittler — 12.84
22. José Soriano — 12.79
23. Garrett Crochet — 12.79
24. Tarik Skubal — 12.79
25. Braxton Ashcraft — 12.76
26. Will Warren — 12.70
27. Chris Martin — 12.57
28. Mike Soroka — 12.44
29. Max Meyer — 12.39
30. Michael King — 12.11

**Important caveat:** Pitchers with very few 2026 starts (e.g., Skubal at 6) are projected purely from their 2026 sample — career performance is not blended in. For an elite arm with a slow start (Skubal, Crochet, Yamamoto-types), expect their projection to climb as their 2026 K% normalizes. A v2 should add a Bayesian shrinkage toward career rates for SPs with n < ~10 starts.

---

## How to use this for your league

1. **Waivers:** Sort `2026_pitcher_projections.csv` by `fp_projection` desc. Anyone in the top 60 who is on FA = waiver target.
2. **Lineup decisions:** When choosing between two start options, prefer the higher K% / lower xFIP. Don't trust last-week ERA as a tiebreaker — it's noise.
3. **Trade targets:** The BUY list above. Pitchers with elite-tier K% and xFIP whose ERA / FP totals don't yet reflect it are bargains.
4. **Trade away:** The SELL list. Sale and Glasnow are especially interesting — well-known names with hot starts, but the peripherals say it can't fully sustain.

---

## Files

- `output/univariate_corr.csv` — full correlation table
- `output/single_metric_oos.csv` — single-feature OOS comparison
- `output/pair_oos.csv` — best 2-feature pairs
- `output/stability.csv` — year-over-year stability per metric
- `output/regression_candidates_2026.csv` — full buy/sell list
- `output/2026_pitcher_projections.csv` — ranked SP projections

## Caveats / known limits

- Single-start FP has a high noise floor (luck of decision W, BABIP, defense, weather, lineup). R² of 0.06 is normal for this type of model — the model ranks, it doesn't pinpoint.
- xFIP and SIERA are formula approximations using year-level HR/FB constants, not FanGraphs-exact values. Relative ranking is correct; absolute values may differ by ±0.10–0.25 from FanGraphs.
- xwOBA against is computed canonically (Savant methodology): per-PA value = `estimated_woba_using_speedangle` for batted balls, actual `woba_value` for K/BB/HBP outcomes; denominator restricted to PAs with `woba_denom == 1` (excludes IBB, SH). Matches what Savant's leaderboard publishes for that pitcher as of that date.
- Opponent wRC+ as-of is NOT in v1.
- 2026 sample for individual SPs ranges 3–8 starts. Use weight accordingly.
- CG/SHO detection is heuristic (pitcher's IP == team total IP and ≥8 IP). Edge cases (rain-shortened, 7-inning doubleheaders pre-2024) may misfire.
