"""
Enrichment: merge Yahoo player rosters with Savant Statcast.

Yahoo players have names like "Cal Raleigh" or "George Springer".
Savant data is keyed on normalized name ("cal raleigh", "george springer").
"""

from utils import normalize_name


def enrich_player(player, savant_index):
    """
    Add Savant stats fields onto a Yahoo player dict.
    Modifies in place AND returns the dict.

    If no Savant match, fields are set to None.
    """
    norm = normalize_name(player.get("name", ""))
    stats = savant_index.get(norm)

    if not stats:
        # Try last-name-only fallback for short names like "M. Garcia"
        last_name = norm.split()[-1] if norm else ""
        first_initial = norm.split()[0][0] if norm else ""
        for k, v in savant_index.items():
            if k.endswith(" " + last_name) and k.startswith(first_initial):
                stats = v
                break

    if stats:
        # Copy stat fields. Savant's `player_id` is the MLBAM ID — store
        # it under `mlbam_id` so we don't clobber Yahoo's `player_id`,
        # which we still need for Yahoo stats lookups.
        for key in ("k_pct", "bb_pct", "k_bb_pct", "babip", "woba", "xwoba",
                    "xslg", "woba_xwoba_gap"):
            if key in stats:
                player[key] = stats[key]
        if "player_id" in stats:
            player["mlbam_id"] = stats["player_id"]
        player["savant_matched"] = True
    else:
        player["savant_matched"] = False
        for key in ("k_pct", "bb_pct", "k_bb_pct", "babip", "woba", "xwoba",
                    "xslg", "woba_xwoba_gap"):
            player.setdefault(key, None)

    return player


def enrich_list(players, savant_index):
    """Enrich a list of players. Returns the same list (modified in place)."""
    for p in players:
        enrich_player(p, savant_index)
    return players


def attach_per_start(players, per_start_fetcher):
    """
    For each player with an mlbam_id, fetch per-start xwOBA and attach.

    Args:
        players: list of player dicts (must have mlbam_id from Savant enrich)
        per_start_fetcher: callable taking mlbam_id, returns list of starts

    Modifies players in place. Adds "per_start" and "per_start_sd" fields.
    """
    from pull_per_start import compute_per_start_sd

    for p in players:
        pid = p.get("mlbam_id")
        if not pid:
            p["per_start"] = []
            p["per_start_sd"] = None
            continue
        try:
            starts = per_start_fetcher(pid)
        except Exception:
            starts = []
        p["per_start"] = starts
        p["per_start_sd"] = compute_per_start_sd(starts)
    return players


def attach_probable_starts(pitchers, probables_by_pitcher,
                          this_week_start, this_week_end,
                          next_week_start, next_week_end):
    """
    For each pitcher, attach the probable starts in this week and next week.

    Modifies pitchers in place. Adds:
        "this_week_starts": [game_dict, ...]
        "next_week_starts": [game_dict, ...]
        "this_week_count": int
        "next_week_count": int
    """
    from pull_probables import filter_to_date_range

    for p in pitchers:
        norm = normalize_name(p.get("name", ""))
        all_starts = probables_by_pitcher.get(norm, [])
        tw = filter_to_date_range(all_starts, this_week_start, this_week_end)
        nw = filter_to_date_range(all_starts, next_week_start, next_week_end)
        p["this_week_starts"] = tw
        p["next_week_starts"] = nw
        p["this_week_count"] = len(tw)
        p["next_week_count"] = len(nw)
    return pitchers
