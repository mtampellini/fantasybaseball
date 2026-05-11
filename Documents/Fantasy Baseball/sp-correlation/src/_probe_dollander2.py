"""Inspect Dollander's reliever-flagged games to confirm pitcher ordering."""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
cd = ROOT / "data" / "raw" / "boxscores" / "2026"

# Look at three games where we previously flagged Dollander as not-starter.
# We'll find files containing 'Dollander' and dump the first 4 awayPitchers entries.
found = 0
for p in sorted(cd.glob("*.json")):
    text = p.read_text()
    if "Dollander" not in text:
        continue
    box = json.loads(text)
    for side in ("home", "away"):
        pitchers = box.get(f"{side}Pitchers", [])
        # is Dollander in there?
        has_dol = any(isinstance(pp, dict) and pp.get("personId") == 801403 for pp in pitchers)
        if not has_dol:
            continue
        first = next((pp for pp in pitchers if isinstance(pp, dict) and pp.get("personId")), None)
        if first and first.get("personId") == 801403:
            continue  # Dollander IS first; skip
        # Show this game
        gid = box.get("gameId", p.stem)
        print(f"\n=== Game {gid} ({side} pitchers) — Dollander not first ===")
        for i, pp in enumerate(pitchers[:6]):
            if not isinstance(pp, dict):
                continue
            print(f"  [{i}] pid={pp.get('personId')} name={pp.get('name'):20s} ip={pp.get('ip'):>5s}  k={pp.get('k'):>3s}  note={pp.get('note')}")
        found += 1
        if found >= 4:
            break
    if found >= 4:
        break
