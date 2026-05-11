"""
Static park factor table. Numbers approximate FanGraphs / Statcast 3-year
run park factors. 100 = league-neutral, >100 = hitter-friendly, <100 = pitcher-friendly.

These are HOME-team-park factors. Apply via the game's home team.
"""

# Statcast tricode → run park factor (3-year avg). Sourced from
# https://baseballsavant.mlb.com/leaderboard/statcast-park-factors.
# Codes match what Savant/Statcast emits (AZ not ARI, SD not SDP, etc.).
PARK_FACTORS: dict[str, float] = {
    # Hitter-friendly
    "COL": 115,  # Coors
    "CIN": 108,  # Great American
    "BAL": 104,  # Camden
    "BOS": 104,  # Fenway
    "PHI": 103,  # Citizens Bank
    "TEX": 103,  # Globe Life
    "NYY": 104,  # Yankee Stadium (LHB-friendly)
    "KC":  102,  # Kauffman
    "TOR": 102,  # Rogers Centre
    "MIL": 101,  # American Family
    "ATL": 101,  # Truist
    "AZ":  102,  # Chase
    "CHC": 100,  # Wrigley (wind-dependent)
    "STL": 100,  # Busch
    "HOU": 99,   # Minute Maid
    "WSH": 99,   # Nationals Park
    "MIN": 99,   # Target
    "CWS": 98,   # Rate Field
    "TB":  98,   # Trop
    "LAA": 97,   # Angel
    # Pitcher-friendly
    "PIT": 96,   # PNC
    "DET": 96,   # Comerica
    "OAK": 96,   # Coliseum (pre-rebrand)
    "ATH": 96,   # Athletics post-Vegas/Sacramento move
    "MIA": 95,   # loanDepot
    "CLE": 95,   # Progressive
    "SEA": 95,   # T-Mobile
    "NYM": 95,   # Citi
    "SD":  94,   # Petco
    "SF":  94,   # Oracle
    "LAD": 99,   # Dodger Stadium
}

# MLB StatsAPI 'teamName' field → Statcast tricode
TEAMNAME_TO_CODE = {
    "Rockies": "COL", "Reds": "CIN", "Orioles": "BAL", "Red Sox": "BOS",
    "Phillies": "PHI", "Rangers": "TEX", "Yankees": "NYY", "Royals": "KC",
    "Blue Jays": "TOR", "Brewers": "MIL", "Braves": "ATL", "D-backs": "AZ",
    "Diamondbacks": "AZ", "Cubs": "CHC", "Cardinals": "STL", "Astros": "HOU",
    "Nationals": "WSH", "Twins": "MIN", "White Sox": "CWS", "Rays": "TB",
    "Angels": "LAA", "Pirates": "PIT", "Tigers": "DET", "Athletics": "ATH",
    "A's": "ATH", "Marlins": "MIA", "Guardians": "CLE", "Mariners": "SEA",
    "Mets": "NYM", "Padres": "SD", "Giants": "SF", "Dodgers": "LAD",
}


def park_factor(home_team: str) -> float:
    """Return park factor for a game's home team. 100 = neutral."""
    code = TEAMNAME_TO_CODE.get(home_team, None)
    if code is None:
        return 100.0
    return float(PARK_FACTORS.get(code, 100))
