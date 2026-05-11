"""Inspect Chase Dollander's 2026 data end to end."""
import json
import pandas as pd
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PROC = ROOT / "data" / "processed"
RAW = ROOT / "data" / "raw"

NAME = "Dollander"

# First — does he appear *anywhere* in the raw boxscore cache?
import os
import re
cache_dir = RAW / "boxscores" / "2026"
matches = []
if cache_dir.exists():
    for p in sorted(cache_dir.glob("*.json")):
        text = p.read_text()
        if NAME.lower() in text.lower():
            matches.append(p.name)
print(f"Raw boxscore files mentioning '{NAME}': {len(matches)}")
if matches:
    print(f"  First 5: {matches[:5]}")
    # Inspect one to find his pitcher line + spelling
    box = json.loads((cache_dir / matches[0]).read_text())
    for side in ("home", "away"):
        for p in box.get(f"{side}Pitchers", []):
            if NAME.lower() in str(p.get("name", "")).lower():
                print(f"  Sample line ({side}, {matches[0]}): {p}")
                break

# Try statcast pitch-level data — pitcher names aren't there but IDs are
import pybaseball as pyb
try:
    ids = pyb.playerid_lookup("dollander", "chase")
    print(f"\nplayerid_lookup result:")
    print(ids.to_string(index=False))
except Exception as e:
    print(f"playerid_lookup failed: {e}")

# Re-extract Dollander's lines from raw cache, ignoring all our filters
print("\n=== ALL Dollander box-line appearances in 2026 raw cache ===")
import re
from src.pull_box_scores import _ip_str_to_outs, _parse_decision
rows = []
for p in sorted(cache_dir.glob("*.json")):
    box = json.loads(p.read_text())
    for side in ("home", "away"):
        for pit in box.get(f"{side}Pitchers", []):
            if not isinstance(pit, dict):
                continue
            if pit.get("personId") == 801403:
                ip = pit.get("ip", "0.0")
                outs = _ip_str_to_outs(ip)
                dec = _parse_decision(pit.get("note", ""))
                # was he the starter? First non-header pitcher row.
                pitchers = box.get(f"{side}Pitchers", [])
                first = next((r for r in pitchers if isinstance(r, dict) and r.get("personId")), None)
                is_starter = (first and first.get("personId") == 801403)
                rows.append({
                    "game_pk": box.get("gameId"),
                    "side": side,
                    "is_starter": is_starter,
                    "ip": ip,
                    "outs": outs,
                    "h": pit.get("h"),
                    "er": pit.get("er"),
                    "bb": pit.get("bb"),
                    "k": pit.get("k"),
                    "hr": pit.get("hr"),
                    "note": pit.get("note"),
                })
df_all = pd.DataFrame(rows)
print(df_all.to_string(index=False))
print(f"\nTotal appearances: {len(df_all)}")
print(f"As starter: {df_all['is_starter'].sum()}")
print(f"As starter w/ >=4 IP: {((df_all['is_starter']) & (df_all['outs'] >= 12)).sum()}")


def show(title, df):
    print(f"\n=== {title} ({len(df)} rows) ===")
    if len(df):
        print(df.to_string(index=False))


# 1) Raw box lines
box = pd.read_parquet(PROC / "box_starts_2026.parquet")
d = box[box["pitcher_name"].str.contains(NAME, na=False)].sort_values("game_date")
show(
    f"Raw 2026 box-score lines for {NAME}",
    d[["game_date", "team", "opponent", "is_home", "ip", "h", "er", "bb", "k",
       "win", "loss", "qs", "cg", "sho"]],
)

# 2) FP per start using our scoring
from src.yahoo_scoring import PitcherWeights, pitcher_fp
w = PitcherWeights.from_file()
if len(d):
    d2 = d.copy()
    d2["fp"] = d2.apply(lambda r: pitcher_fp(r.to_dict(), w), axis=1)
    print(f"\n2026 FP per start (Yahoo scoring): mean={d2.fp.mean():.2f}  median={d2.fp.median():.2f}")
    print(d2[["game_date", "opponent", "ip", "er", "k", "bb", "win", "qs", "fp"]].to_string(index=False))

# 3) Analytical dataset (requires >=3 prior starts)
ds = pd.read_parquet(PROC / "sp_dataset_2026.parquet")
d3 = ds[ds["pitcher_name"].str.contains(NAME, na=False)].sort_values("game_date")
show(
    f"Analytical rows for {NAME} (requires >=3 prior starts)",
    d3[["game_date", "opponent", "n_starts_prior", "k_pct_prior", "bb_pct_prior",
        "k_bb_pct_prior", "era_prior", "xfip_prior", "siera_prior",
        "xwoba_against_prior", "whiff_pct_prior", "csw_pct_prior",
        "hard_hit_pct_prior", "barrel_pct_prior", "fp"]],
)

# 4) Projection rank
proj = pd.read_csv(ROOT / "output" / "2026_pitcher_projections.csv")
mask = proj["pitcher_name"].str.contains(NAME, na=False)
if mask.any():
    idx = proj.index[mask][0]
    rank = idx + 1
    print(f"\nProjection rank: #{rank} of {len(proj)} qualified SPs")
    row = proj.loc[idx]
    for k in ("pitcher_name", "team", "n_starts_prior", "fp_projection"):
        print(f"  {k} = {row[k]}")
else:
    print(f"\nNOT in projections CSV (likely <3 prior starts — needs at least 4 starts for the dataset)")
