"""Quick probe: dump one boxscore's pitcher rows to verify field names."""
import statsapi, json

games = statsapi.schedule(date="2024-06-15", sportId=1)
games = [g for g in games if g.get("game_type") == "R" and g.get("status") == "Final"]
print(f"{len(games)} games on 2024-06-15")
g = games[0]
print(f"gamePk={g['game_id']}  {g['away_name']} @ {g['home_name']}")
box = statsapi.boxscore_data(gamePk=int(g["game_id"]))
print(f"top-level keys: {sorted(box.keys())}")
for side in ("home", "away"):
    pitchers = box.get(f"{side}Pitchers", [])
    print(f"\n--- {side} pitchers ({len(pitchers)}) ---")
    for i, p in enumerate(pitchers[:3]):
        print(f"[{i}] {p}")
    print(f"\n{side}PitchingTotals: {box.get(f'{side}PitchingTotals')}")
    print(f"{side}Info: {box.get(f'{side}Info')}")
