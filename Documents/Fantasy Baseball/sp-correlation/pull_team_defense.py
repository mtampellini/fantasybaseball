"""Pull team-level Statcast OAA (Outs Above Average) for 2024-2026.

Uses the Savant fielder OAA leaderboard CSV endpoint, aggregates to team.
Output: data/processed/team_defense_{year}.parquet with columns:
    team_savant, oaa_total, frp_total, n_fielders
"""
import sys
sys.stdout.reconfigure(encoding="utf-8")
from io import StringIO
from pathlib import Path

import pandas as pd
import requests

PROC = Path("data/processed")
PROC.mkdir(parents=True, exist_ok=True)

URL = "https://baseballsavant.mlb.com/leaderboard/outs_above_average"


def fetch(year: int) -> pd.DataFrame:
    params = {"type": "Fielder", "year": year, "min": "0", "team": "", "csv": "true"}
    r = requests.get(URL, params=params, timeout=60)
    r.raise_for_status()
    df = pd.read_csv(StringIO(r.text))
    return df


for year in (2024, 2025, 2026):
    print(f"\n=== {year} ===")
    df = fetch(year)
    print(f"  raw rows: {len(df)}, cols: {list(df.columns)}")
    # Aggregate to team
    team = df.groupby("display_team_name").agg(
        oaa_total=("outs_above_average", "sum"),
        frp_total=("fielding_runs_prevented", "sum"),
        n_fielders=("player_id", "size"),
    ).reset_index().rename(columns={"display_team_name": "team_savant"})
    team = team.sort_values("oaa_total", ascending=False)
    out = PROC / f"team_defense_{year}.parquet"
    team.to_parquet(out, index=False)
    print(f"  wrote {out}  ({len(team)} teams)")
    print(f"  top 5 OAA: {', '.join(f'{r.team_savant} ({r.oaa_total:+d})' for _,r in team.head(5).iterrows())}")
    print(f"  bot 5 OAA: {', '.join(f'{r.team_savant} ({r.oaa_total:+d})' for _,r in team.tail(5).iterrows())}")
