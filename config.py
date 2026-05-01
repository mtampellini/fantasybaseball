"""Configuration for Tamp Slam fantasy tracker."""

# League settings
YAHOO_LEAGUE_ID = "41657"
YAHOO_TEAM_ID = "11"
TEAM_NAME = "Tamp Slam"
LEAGUE_NAME = "Il Nuovo Vesuvio"

# Number of FAs to pull
FA_PITCHER_COUNT = 30
FA_HITTER_COUNT = 30

# Per-start xwOBA depth
PER_START_DEPTH = 5

# Players to exclude from FA SP wire (relievers w/ SP eligibility, injured, etc)
SP_EXCLUDE = {
    "antonio senzatela", "tobias myers", "tyler alexander",
    "jeff hoffman", "tyler wells", "sean newcomb", "cody ponce",
}

# League team mapping
LEAGUE_TEAMS = {
    1: "Pine Barrens", 2: "Balcony Tears", 3: "Chicks Dig",
    4: "Diamond Dogs", 5: "Rayhood", 6: "KING JULIAN",
    7: "LB Jefes", 8: "Mama's Juiced", 9: "Soto Shuffle",
    10: "South Park Cows", 11: "Tamp Slam", 12: "SS Express",
    13: "Wally Cats", 14: "Short Porchers",
}
