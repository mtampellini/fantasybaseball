"""
Matchup-aware xFP projection for hitters.

For a given fantasy week (Mon-Sun), walk each scheduled game and combine:
  - Hitter true-talent xwOBA (from Savant)
  - Opposing SP xwOBA-allowed (log5 odds-ratio with league average)
  - Park factor (hitter team's park at home, opponent's park on road)
  - PA rate per game (uses last-7-day PA when available, season fallback)
  - SB rate per PA (season rate)

xFP/game = adj_xwoba * XFP_PER_XWOBA * pa_per_g + sb_per_g * SB_PTS

This replaces the naive `xfp_per_wk * (games_nw / typical_week_games)`
calc that was matchup-blind and used `pa_season / weeks_played` (which
broke for recently-promoted players whose calendar-week rate
under-represented their actual playing role).
"""

from collections import defaultdict
from datetime import datetime, date as date_cls

from utils import normalize_name


XFP_PER_XWOBA = 3.5
SB_PTS = 2.0
LEAGUE_AVG_XWOBA = 0.320
TYPICAL_GAMES_PER_WEEK = 6.0

# Park factors for hitter wOBA: home-team key used when hitter is at home;
# opp-team key used when hitter is on the road. Values are rough multipliers
# from public PF references (FanGraphs, Statcast). 1.00 = neutral.
PARK_MULT = {
    "COL": 1.12,   # Coors
    "CIN": 1.06,   # GABP
    "TEX": 1.05,   # Globe Life
    "BOS": 1.04,   # Fenway
    "ARI": 1.03, "AZ": 1.03,
    "NYY": 1.03,
    "PHI": 1.03,
    "BAL": 1.02, "TOR": 1.02, "CHC": 1.02,
    "HOU": 1.01,
    "ATL": 1.00, "STL": 1.00, "WSH": 1.00, "WSN": 1.00,
    "MIN": 0.99, "CLE": 0.99, "CWS": 0.99, "CHW": 0.99,
    "NYM": 0.98, "KC": 0.98, "KCR": 0.98, "LAA": 0.98, "MIL": 0.98,
    "TB": 0.97, "TBR": 0.97, "LAD": 0.97, "DET": 0.97,
    "PIT": 0.96,
    "OAK": 0.95, "ATH": 0.95,
    "MIA": 0.94,
    "SEA": 0.93, "SF": 0.93, "SFG": 0.93,
    "SD": 0.92, "SDP": 0.92,
}

# Team abbreviation normalization: Fangraphs uses some 3-letter codes
# different from Yahoo / Savant. Map everything to the Yahoo style.
ABBR_NORM = {
    "WSN": "WSH", "CHW": "CWS", "KCR": "KC", "SDP": "SD",
    "SFG": "SF", "TBR": "TB",
}


def _norm_team(abbr):
    if not abbr:
        return abbr
    return ABBR_NORM.get(abbr, abbr)


def _parse_date(s):
    if isinstance(s, date_cls):
        return s
    if isinstance(s, datetime):
        return s.date()
    try:
        return datetime.strptime(s, "%Y-%m-%d").date()
    except (ValueError, TypeError):
        return None


def log5_xwoba(hitter_xwoba, pitcher_xwoba_allowed, league=LEAGUE_AVG_XWOBA):
    """Combine hitter + pitcher xwOBA via log5 odds-ratio."""
    if hitter_xwoba is None or pitcher_xwoba_allowed is None:
        return hitter_xwoba
    return league * (hitter_xwoba / league) * (pitcher_xwoba_allowed / league)


def _build_pitcher_xwoba_lookup(pitcher_index):
    """
    Build {pitcher_id: xwoba, normalized_name: xwoba} lookups from a Savant
    pitcher leaderboard dict (already keyed by normalized name).
    """
    by_id = {}
    by_name = {}
    for nm, rec in pitcher_index.items():
        pid = rec.get("player_id")
        xw = rec.get("xwoba")
        if xw is None:
            continue
        if pid:
            by_id[str(pid)] = xw
        by_name[nm] = xw
    return by_id, by_name


def _team_schedule_in_window(probables, start, end):
    """
    Group probables by team for games in [start, end], attaching the OPPOSING
    team's SP to each entry.

    The Fangraphs grid emits each contest twice — once per team's perspective —
    and the `pitcher_*` fields on each entry are that team's OWN starter, not
    the opponent's. For hitter matchup math we need the OPPOSING SP, so we
    build a (date, team) -> SP-info lookup and attach the opposing entry's
    SP under `opp_pitcher_*` keys.
    """
    own_sp = {}  # (date, team) -> {name, id, throws}
    in_window = []
    for g in probables:
        gd = _parse_date(g.get("date"))
        if gd is None or not (start <= gd <= end):
            continue
        team = _norm_team(g.get("team"))
        if not team:
            continue
        own_sp[(gd, team)] = {
            "name": g.get("pitcher_name"),
            "id": g.get("pitcher_id"),
            "throws": g.get("throws"),
        }
        in_window.append((gd, team, g))

    sched = defaultdict(list)
    for gd, team, g in in_window:
        opp = _norm_team(g.get("opponent"))
        opp_sp_rec = own_sp.get((gd, opp)) if opp else None
        entry = dict(g)
        entry["opp_pitcher_name"] = opp_sp_rec["name"] if opp_sp_rec else None
        entry["opp_pitcher_id"] = opp_sp_rec["id"] if opp_sp_rec else None
        entry["opp_throws"] = opp_sp_rec["throws"] if opp_sp_rec else None
        sched[team].append(entry)
    return sched


def _pa_per_game(h):
    """
    Best estimate of PA-per-game for a hitter.

    Priority:
      1. recent_pa_per_wk (trailing ~2-week PA pace from daily_report's
         compute_recent_playing_time) -- the most stable read of current role,
         including recently-promoted everyday starters.
      2. pa_1w (Yahoo last-7-days PA) -- single-week recency signal.
      3. pa_season / weeks_played (season-average) as a final fallback.

    Players with pa_1w < 10 and no recent_pa_per_wk are routed through the
    season fallback, since a 5-PA week is too noisy to extrapolate.
    """
    recent = h.get("recent_pa_per_wk")
    if recent:
        return recent / TYPICAL_GAMES_PER_WEEK
    pa_1w = h.get("pa_1w") or 0
    if pa_1w >= 10:
        return pa_1w / TYPICAL_GAMES_PER_WEEK
    pa_per_wk = h.get("pa_per_wk") or 0
    if pa_per_wk:
        return pa_per_wk / TYPICAL_GAMES_PER_WEEK
    return 0.0


def _sb_per_pa(h):
    sb = h.get("sb_season") or 0
    pa = h.get("pa_season") or 0
    return (sb / pa) if pa else 0.0


def _project_window(hitter, schedule, pitcher_by_id, pitcher_by_name):
    """
    Project xFP for one hitter over one date-window schedule.

    Returns: (total_xfp, games_count, base_xfp_neutral_matchup)
        base_xfp = same calc but without log5/park (lets caller report a delta)
    """
    xwoba = hitter.get("xwoba")
    if xwoba is None or not schedule:
        return None, 0, None

    pa_per_g = _pa_per_game(hitter)
    if pa_per_g <= 0:
        return None, 0, None

    sb_per_pa = _sb_per_pa(hitter)
    hit_team = _norm_team(hitter.get("team"))

    total = 0.0
    base = 0.0
    for g in schedule:
        # Opposing SP xwOBA (the pitcher this hitter actually faces).
        # `opp_pitcher_*` is attached by _team_schedule_in_window; falling
        # back to the entry's own `pitcher_*` is WRONG — that's the hitter's
        # teammate. Leave matchup neutral if the opposing SP isn't in the
        # Savant index.
        pid = g.get("opp_pitcher_id")
        sp_xwoba = pitcher_by_id.get(str(pid)) if pid else None
        if sp_xwoba is None and g.get("opp_pitcher_name"):
            sp_xwoba = pitcher_by_name.get(normalize_name(g["opp_pitcher_name"]))

        matchup_xwoba = log5_xwoba(xwoba, sp_xwoba) if sp_xwoba is not None else xwoba

        # Park factor: home -> own park; road -> opp park.
        opp_team = _norm_team(g.get("opponent"))
        if g.get("is_home"):
            park = PARK_MULT.get(hit_team, 1.0)
        else:
            park = PARK_MULT.get(opp_team, 1.0)
        adj_xwoba = matchup_xwoba * park

        xfp_hit = adj_xwoba * XFP_PER_XWOBA * pa_per_g
        xfp_sb = sb_per_pa * pa_per_g * SB_PTS
        total += xfp_hit + xfp_sb

        # Neutral baseline (no log5, no park) for delta reporting
        base_hit = xwoba * XFP_PER_XWOBA * pa_per_g
        base += base_hit + xfp_sb

    return total, len(schedule), base


def enrich_matchup_xfp(hitter_list, probables, pitcher_index,
                       tw_start, tw_end, nw_start, nw_end):
    """
    Add matchup + park adjusted projections to each hitter dict in place.

    Adds keys:
      xfp_this_week        - matchup-adjusted xFP for [tw_start, tw_end]
      xfp_next_week        - matchup-adjusted xFP for [nw_start, nw_end]
                             (overwrites the naive games-ratio value)
      xfp_this_week_base   - neutral baseline (same PA/G but no log5/park)
      xfp_next_week_base   - neutral baseline next week
      games_this_week      - # games scheduled this week
      games_next_week      - # games scheduled next week (overwrites prior)
      xfp_matchup_delta_tw - this_week_adj - this_week_base (signed)
      xfp_matchup_delta_nw - next_week_adj - next_week_base (signed)
    """
    pitcher_by_id, pitcher_by_name = _build_pitcher_xwoba_lookup(pitcher_index)
    tw_sched = _team_schedule_in_window(probables, tw_start, tw_end)
    nw_sched = _team_schedule_in_window(probables, nw_start, nw_end)

    for h in hitter_list:
        team = _norm_team(h.get("team"))

        tw_games = tw_sched.get(team, [])
        tw_total, tw_g, tw_base = _project_window(h, tw_games, pitcher_by_id, pitcher_by_name)
        h["games_this_week"] = tw_g
        h["xfp_this_week"] = round(tw_total, 1) if tw_total is not None else None
        h["xfp_this_week_base"] = round(tw_base, 1) if tw_base is not None else None
        h["xfp_matchup_delta_tw"] = (
            round(tw_total - tw_base, 1) if (tw_total is not None and tw_base is not None) else None
        )

        nw_games = nw_sched.get(team, [])
        nw_total, nw_g, nw_base = _project_window(h, nw_games, pitcher_by_id, pitcher_by_name)
        h["games_next_week"] = nw_g
        h["xfp_next_week"] = round(nw_total, 1) if nw_total is not None else None
        h["xfp_next_week_base"] = round(nw_base, 1) if nw_base is not None else None
        h["xfp_matchup_delta_nw"] = (
            round(nw_total - nw_base, 1) if (nw_total is not None and nw_base is not None) else None
        )
