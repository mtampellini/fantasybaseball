#!/usr/bin/env python
"""
Draft board generator for Il Nuovo Vesuvio (14-team H2H points).

WHAT THIS DOES
    Ranks hitters (and, more crudely, pitchers) for next season's draft using
    the only things that were shown to carry year-over-year signal:

        base      last season's fantasy points per game   (best single
                  predictor, R^2 ~ 0.38 in a 3-year backtest)
        adjust    contact quality - HardHit% / ExitVelo / Barrel% - which
                  repeat at r ~ 0.68-0.71, vs wOBA which repeats at 0.27
        volume    expected games, from prior games (r ~ 0.44 - a soft nudge,
                  NOT an injury filter)

    Deliberately NOT used: xwOBA (only 0.37 stable - it blends the repeatable
    inputs with BABIP noise), age (r = -0.07 with availability).

HOW TO RUN
    # after the MLB regular season ends, to build next year's board:
    python draft_board.py --season 2026

    # outputs, written next to this script:
    #   draft_board_<season+1>_hitters.csv
    #   draft_board_<season+1>_pitchers.csv
    #   draft_board_<season+1>.md      <- the one to read on draft day

HOW TO USE IT ON DRAFT DAY
    Take the best available player in the highest tier you can reach. Inside a
    tier the ordering is meaningless (rank correlation with actual outcome was
    0.13), so do not agonise - take the one you like and move on.

    Structure that worked in 2026 and should be kept:
        rounds 1-8    hitters
        rounds 9-12   starting pitchers with real innings
        rounds 13+    churn fodder; consider 2 closers
"""
from __future__ import annotations

import argparse
import json
import sys
import time
import unicodedata
import urllib.request
import warnings
from pathlib import Path

import numpy as np
import pandas as pd
from numpy.linalg import lstsq

warnings.filterwarnings('ignore')

# league scoring -------------------------------------------------------------
HIT = dict(R=1.5, H=1.0, S=1.0, D=2.0, T=3.0, HR=4.0, RBI=2.0, SB=2.0, BB=1.0)
PIT = dict(IP=.25, W=8, CG=10, SHO=4, SV=6, ER=-2, BB=-.5, K=2, QS=3)
FEAT = ['FPpG', 'brl_percent', 'ev95percent', 'avg_hit_speed', 'Kpct', 'BBpct', 'SB', 'HR']
MIN_PA = 200          # to be rankable
MIN_PA_TARGET = 100   # to be a training target


def _get(url: str, tries: int = 4):
    for i in range(tries):
        try:
            with urllib.request.urlopen(url, timeout=90) as r:
                return json.load(r)
        except Exception:
            if i == tries - 1:
                raise
            time.sleep(2 * (i + 1))


def norm(s: str) -> str:
    s = unicodedata.normalize('NFKD', s or '').encode('ascii', 'ignore').decode()
    return ''.join(c for c in s.lower() if c.isalpha() or c == ' ').strip()


# ---------------------------------------------------------------- sources ---
_TEAMS: dict[int, str] = {}


def team_abbr(year: int) -> dict:
    if not _TEAMS:
        js = _get(f'https://statsapi.mlb.com/api/v1/teams?sportId=1&season={year}')
        _TEAMS.update({t['id']: t['abbreviation'] for t in js.get('teams', [])})
    return _TEAMS


def season_hitting(year: int) -> pd.DataFrame:
    """counting stats -> league fantasy points, from MLB StatsAPI"""
    tm = team_abbr(year)
    rows, off = [], 0
    while True:
        js = _get(f'https://statsapi.mlb.com/api/v1/stats?stats=season&group=hitting'
                  f'&season={year}&gameType=R&playerPool=All&limit=500&offset={off}')
        sp = [s for b in js.get('stats', []) for s in b.get('splits', [])]
        if not sp:
            break
        for s in sp:
            st, p = s['stat'], s.get('player', {})
            h = st.get('hits', 0)
            d2, d3, hr = st.get('doubles', 0), st.get('triples', 0), st.get('homeRuns', 0)
            fp = (HIT['R'] * st.get('runs', 0) + HIT['H'] * h
                  + HIT['S'] * (h - d2 - d3 - hr) + HIT['D'] * d2 + HIT['T'] * d3
                  + HIT['HR'] * hr + HIT['RBI'] * st.get('rbi', 0)
                  + HIT['SB'] * st.get('stolenBases', 0)
                  + HIT['BB'] * st.get('baseOnBalls', 0))
            rows.append(dict(pid=p.get('id'), name=p.get('fullName'),
                             team=tm.get((s.get('team') or {}).get('id'), ''),
                             pos=(s.get('position') or {}).get('abbreviation', ''),
                             G=st.get('gamesPlayed', 0), PA=st.get('plateAppearances', 0),
                             FP=fp, K=st.get('strikeOuts', 0),
                             BB=st.get('baseOnBalls', 0),
                             SB=st.get('stolenBases', 0), HR=hr))
        off += 500
        if off > 4000:
            break
    d = pd.DataFrame(rows).drop_duplicates('pid')
    d['FPpG'] = d['FP'] / d['G'].replace(0, np.nan)
    d['Kpct'] = 100 * d['K'] / d['PA'].replace(0, np.nan)
    d['BBpct'] = 100 * d['BB'] / d['PA'].replace(0, np.nan)
    return d


def season_pitching(year: int) -> pd.DataFrame:
    tm = team_abbr(year)
    rows, off = [], 0
    while True:
        js = _get(f'https://statsapi.mlb.com/api/v1/stats?stats=season&group=pitching'
                  f'&season={year}&gameType=R&playerPool=All&limit=500&offset={off}')
        sp = [s for b in js.get('stats', []) for s in b.get('splits', [])]
        if not sp:
            break
        for s in sp:
            st, p = s['stat'], s.get('player', {})
            ipr = float(st.get('inningsPitched', 0) or 0)
            ip = int(ipr) + (ipr - int(ipr)) * 10 / 3
            if ip < 10:
                continue
            gs = st.get('gamesStarted', 0)
            era = st.get('earnedRuns', 0) * 9 / ip if ip else 9.0
            # QS is not in this feed; same estimator applied to everyone
            qs = gs * float(np.clip(0.72 - 0.11 * (era - 3.6), 0, 0.72))
            fp = (PIT['IP'] * ip + PIT['W'] * st.get('wins', 0)
                  + PIT['CG'] * st.get('completeGames', 0)
                  + PIT['SHO'] * st.get('shutouts', 0) + PIT['SV'] * st.get('saves', 0)
                  + PIT['ER'] * st.get('earnedRuns', 0)
                  + PIT['BB'] * st.get('baseOnBalls', 0)
                  + PIT['K'] * st.get('strikeOuts', 0) + PIT['QS'] * qs)
            rows.append(dict(pid=p.get('id'), name=p.get('fullName'),
                             team=tm.get((s.get('team') or {}).get('id'), ''),
                             IP=ip, GS=gs, SV=st.get('saves', 0),
                             K=st.get('strikeOuts', 0), ERA=era, FP=fp))
        off += 500
        if off > 4000:
            break
    return pd.DataFrame(rows).drop_duplicates('pid')


def savant(year: int) -> pd.DataFrame:
    from pybaseball import statcast_batter_expected_stats, statcast_batter_exitvelo_barrels
    e = statcast_batter_expected_stats(year, minPA=100)[['player_id', 'woba', 'est_woba']]
    b = statcast_batter_exitvelo_barrels(year, minBBE=30)[
        ['player_id', 'avg_hit_speed', 'brl_percent', 'ev95percent',
         'anglesweetspotpercent']]
    return e.merge(b, on='player_id', how='left')


def load(year: int) -> pd.DataFrame:
    h = season_hitting(year)
    try:
        s = savant(year)
        h = h.merge(s, left_on='pid', right_on='player_id', how='left')
    except Exception as ex:
        print(f'  ! Savant {year} unavailable ({ex}); contact-quality columns blank')
        for c in ['avg_hit_speed', 'brl_percent', 'ev95percent']:
            h[c] = np.nan
    return h


# ------------------------------------------------------------------ model ---
def _fit(df, ycol, cols):
    X = np.column_stack([np.ones(len(df))] + [df[c].values for c in cols])
    return lstsq(X, df[ycol].values, rcond=None)[0]


def _apply(beta, df, cols):
    X = np.column_stack([np.ones(len(df))] + [df[c].values for c in cols])
    return X @ beta


def build_board(season: int, back: int = 3):
    """season = the season that just finished. Board is for season+1."""
    years = list(range(season - back, season + 1))
    print(f'loading {years} ...')
    H = {}
    for y in years:
        H[y] = load(y)
        print(f'  {y}: {len(H[y])} hitters')

    train = []
    for a, b in zip(years, years[1:]):
        L = H[a][['pid'] + FEAT + ['G', 'PA']]
        R = H[b][['pid', 'FPpG', 'G', 'PA']].rename(
            columns={'FPpG': 'Y_fpg', 'G': 'Y_G', 'PA': 'Y_PA'})
        j = L.merge(R, on='pid').dropna()
        train.append(j[(j.PA >= MIN_PA) & (j.Y_PA >= MIN_PA_TARGET)])
    tr = pd.concat(train)
    print(f'training rows: {len(tr)} (pairs {years[0]}->{years[1]} .. '
          f'{years[-2]}->{years[-1]})')

    b_rate = _fit(tr, 'Y_fpg', FEAT)
    b_game = _fit(tr, 'Y_G', ['G'])
    p = _apply(b_rate, tr, FEAT)
    r2 = 1 - ((tr.Y_fpg - p) ** 2).sum() / ((tr.Y_fpg - tr.Y_fpg.mean()) ** 2).sum()
    print(f'in-sample R^2 on FP/G: {r2:.3f}   (expect ~0.44 out of sample)')

    cur = H[season].dropna(subset=FEAT).query(f'PA >= {MIN_PA}').copy()
    cur['proj_fpg'] = _apply(b_rate, cur, FEAT)
    cur['proj_G'] = np.clip(_apply(b_game, cur, ['G']), 40, 150)
    cur['PROJ'] = (cur['proj_fpg'] * cur['proj_G']).round(0)
    cur['gap_vs_contact'] = (cur['woba'] - cur['est_woba']).round(3)
    out = cur[['name', 'team', 'pos', 'G', 'PA', 'FPpG', 'brl_percent', 'ev95percent',
               'avg_hit_speed', 'SB', 'HR', 'proj_fpg', 'proj_G', 'PROJ',
               'gap_vs_contact']].sort_values('PROJ', ascending=False)
    out.insert(0, 'rank', range(1, len(out) + 1))
    out['tier'] = pd.cut(out['rank'], [0, 12, 30, 60, 100, 160, 10 ** 6],
                         labels=['T1 (rds 1-2)', 'T2 (rds 2-4)', 'T3 (rds 4-7)',
                                 'T4 (rds 7-10)', 'T5 (rds 10-14)', 'T6 (churn)'])

    P = season_pitching(season)
    P = P[(P.IP >= 60)].copy()
    P['PROJ'] = P['FP'].round(0)
    P = P.sort_values('PROJ', ascending=False)
    P.insert(0, 'rank', range(1, len(P) + 1))
    P['role'] = np.where(P['SV'] >= 10, 'CLOSER', np.where(P['GS'] >= 10, 'SP', 'RP'))
    return out, P[['rank', 'name', 'team', 'role', 'IP', 'GS', 'SV', 'K', 'ERA', 'PROJ']]


def write_md(hit, pit, season, path: Path):
    y = season + 1
    L = [f'# {y} Draft Board', '',
         f'*Built from {season} data. Hitter model trained on the prior '
         f'{3} season-pairs.*', '',
         '## How to use this', '',
         '- Take the best available player **in the highest tier you can reach**.',
         '- **Inside a tier the order is meaningless** (rank correlation with actual',
         '  outcome measured at 0.13). Do not agonise.',
         '- Ceiling on any projection here is about **R^2 0.44** - more than half of',
         '  next season is genuinely unforecastable.',
         '- `gap_vs_contact` = wOBA minus xwOBA. **Positive = results outran contact',
         '  quality, expect regression down. Negative = buy-low.**', '',
         '## Structure that worked in 2026 (keep it)', '',
         '| Rounds | Take |', '|---|---|',
         '| 1-8 | Hitters |',
         '| 9-12 | Starting pitchers with real innings |',
         '| 13+ | Churn fodder; consider 2 closers |', '',
         '## Hitters', '']
    for t in hit['tier'].cat.categories:
        d = hit[hit['tier'] == t]
        if not len(d):
            continue
        L += [f'### {t}', '',
              '| # | Player | Tm | Pos | Proj | FP/G | G | Barrel% | HardHit% | SB | gap |',
              '|---|---|---|---|---|---|---|---|---|---|---|']
        for r in d.head(60).itertuples():
            L.append(f'| {r.rank} | {r.name} | {r.team} | {r.pos} | **{r.PROJ:.0f}** | '
                     f'{r.FPpG:.2f} | {r.G} | {r.brl_percent:.1f} | {r.ev95percent:.1f} | '
                     f'{r.SB} | {r.gap_vs_contact:+.3f} |')
        L.append('')
    L += ['## Pitchers', '',
          '*Ranked on prior-year fantasy points only. This ranking is weak - late',
          'pitching was noise for every method tested. Use it for rounds 9-12, and',
          'churn the rest in-season where your real edge is.*', '',
          '| # | Player | Tm | Role | Proj | IP | GS | SV | K | ERA |',
          '|---|---|---|---|---|---|---|---|---|---|']
    for r in pit.head(80).itertuples():
        L.append(f'| {r.rank} | {r.name} | {r.team} | {r.role} | **{r.PROJ:.0f}** | '
                 f'{r.IP:.0f} | {r.GS} | {r.SV} | {r.K} | {r.ERA:.2f} |')
    path.write_text('\n'.join(L), encoding='utf-8')


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--season', type=int, required=True,
                    help='the season that just FINISHED (board is for season+1)')
    ap.add_argument('--back', type=int, default=3, help='training seasons to use')
    a = ap.parse_args()
    here = Path(__file__).parent
    hit, pit = build_board(a.season, a.back)
    y = a.season + 1
    hit.to_csv(here / f'draft_board_{y}_hitters.csv', index=False)
    pit.to_csv(here / f'draft_board_{y}_pitchers.csv', index=False)
    write_md(hit, pit, a.season, here / f'draft_board_{y}.md')
    print(f'\nwrote draft_board_{y}.md  ({len(hit)} hitters, {len(pit)} pitchers)')
    print('\ntop 15 hitters:')
    print(hit.head(15)[['rank', 'name', 'team', 'pos', 'PROJ', 'FPpG',
                        'gap_vs_contact']].to_string(index=False))


if __name__ == '__main__':
    sys.exit(main())
