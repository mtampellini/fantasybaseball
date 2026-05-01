"""
Compute per-team season distributions (mean + SD) over a window of weeks.

Uses population SD (divide by n) so values are directly comparable across
teams with the same number of weeks. Excludes Week 1 by default — the
short opening week where the team that drafted 14th had only ~3 games is
a known statistical outlier we've already validated against in prior
strategy work.
"""

from config import YAHOO_TEAM_ID, TEAM_NAME


def _pop_sd(values):
    """Population standard deviation."""
    n = len(values)
    if n < 1:
        return 0.0
    mean = sum(values) / n
    return (sum((v - mean) ** 2 for v in values) / n) ** 0.5


def _rank(value, sorted_values, ascending=True):
    """Return 1-based rank of `value` in sorted_values."""
    ordered = sorted(sorted_values, reverse=not ascending)
    for i, v in enumerate(ordered, start=1):
        if v == value:
            return i
    return None


def compute_team_distributions(weeks_data, exclude_weeks=(1,), exclude_in_progress=True):
    """
    Roll up per-team mean/SD across weeks.

    Args:
        weeks_data: list of {"week": int, "results": [team_dict, ...], "in_progress": bool?}
        exclude_weeks: iterable of week numbers to drop (default Week 1)
        exclude_in_progress: drop weeks marked in_progress so the
            current incomplete week doesn't dilute distributions

    Returns:
        {
            "weeks_used": [2, 3, 4, 5],
            "teams": {
                team_id: {
                    "team_id": int,
                    "team_name": str,
                    "weekly": [{"week": int, "hit": float, "pitch": float, "total": float}, ...],
                    "hit_mean": float, "hit_sd": float, "hit_rank": int,
                    "pitch_mean": float, "pitch_sd": float, "pitch_rank": int,
                    "total_mean": float, "total_sd": float, "total_rank": int,
                },
                ...
            }
        }

        Hit/pitch ranks are by SD ascending (most consistent = rank 1).
        Total rank is by mean descending (highest scoring = rank 1).
    """
    exclude = set(exclude_weeks)

    used_weeks = []
    by_team = {}  # team_id -> list of weekly dicts

    for w in weeks_data:
        wk = w["week"]
        if wk in exclude:
            continue
        if exclude_in_progress and w.get("in_progress"):
            continue
        used_weeks.append(wk)
        for r in w["results"]:
            tid = r["team_id"]
            entry = by_team.setdefault(tid, {
                "team_id": tid,
                "team_name": r["team_name"],
                "weekly": [],
            })
            entry["weekly"].append({
                "week": wk,
                "hit": r["hitting"],
                "pitch": r["pitching"],
                "total": r["total"],
            })

    used_weeks.sort()

    # Per-team mean + SD
    for tid, t in by_team.items():
        hits = [w["hit"] for w in t["weekly"]]
        pitches = [w["pitch"] for w in t["weekly"]]
        totals = [w["total"] for w in t["weekly"]]
        n = len(hits) or 1
        t["hit_mean"] = round(sum(hits) / n, 2)
        t["hit_sd"] = round(_pop_sd(hits), 2)
        t["pitch_mean"] = round(sum(pitches) / n, 2)
        t["pitch_sd"] = round(_pop_sd(pitches), 2)
        t["total_mean"] = round(sum(totals) / n, 2)
        t["total_sd"] = round(_pop_sd(totals), 2)

    # Cross-team ranks
    all_hit_sd = [t["hit_sd"] for t in by_team.values()]
    all_pitch_sd = [t["pitch_sd"] for t in by_team.values()]
    all_total_mean = [t["total_mean"] for t in by_team.values()]

    for t in by_team.values():
        t["hit_rank"] = _rank(t["hit_sd"], all_hit_sd, ascending=True)
        t["pitch_rank"] = _rank(t["pitch_sd"], all_pitch_sd, ascending=True)
        t["total_rank"] = _rank(t["total_mean"], all_total_mean, ascending=False)

    return {"weeks_used": used_weeks, "teams": by_team}


def get_my_team_summary(distributions):
    """
    Pull just my team's slice plus league context (means, SD ranges).
    """
    my_id = int(YAHOO_TEAM_ID)
    teams = distributions["teams"]
    me = teams.get(my_id)
    if not me:
        return None

    # League context: how many teams + ranges
    n = len(teams)
    return {
        "team_id": my_id,
        "team_name": me["team_name"],
        "weeks_used": distributions["weeks_used"],
        "n_teams": n,
        "hit": {
            "mean": me["hit_mean"],
            "sd": me["hit_sd"],
            "rank": me["hit_rank"],
        },
        "pitch": {
            "mean": me["pitch_mean"],
            "sd": me["pitch_sd"],
            "rank": me["pitch_rank"],
        },
        "total": {
            "mean": me["total_mean"],
            "sd": me["total_sd"],
            "rank": me["total_rank"],
        },
    }


def get_most_recent_completed_week(weeks_data, exclude_in_progress=True):
    """Return the highest-numbered week that's fully completed (not in progress)."""
    candidates = [
        w for w in weeks_data
        if not (exclude_in_progress and w.get("in_progress"))
    ]
    if not candidates:
        return None
    return max(candidates, key=lambda w: w["week"])


if __name__ == "__main__":
    # Validation: should reproduce the W2-W5 leaders the user gave
    from pull_weekly_results import fetch_all_weeks
    data = fetch_all_weeks()
    dist = compute_team_distributions(data, exclude_weeks=[1])
    print(f"Weeks used: {dist['weeks_used']}\n")
    print(f"{'Team':<22} {'hit_mean':>9} {'hit_sd':>7} {'rank':>5}  "
          f"{'pitch_mean':>10} {'pitch_sd':>9} {'rank':>5}  "
          f"{'total_mean':>10} {'rank':>5}")
    teams_sorted = sorted(dist["teams"].values(), key=lambda t: t["hit_rank"])
    for t in teams_sorted:
        print(f"{t['team_name'][:22]:<22} "
              f"{t['hit_mean']:>9.2f} {t['hit_sd']:>7.2f} {t['hit_rank']:>5}  "
              f"{t['pitch_mean']:>10.2f} {t['pitch_sd']:>9.2f} {t['pitch_rank']:>5}  "
              f"{t['total_mean']:>10.2f} {t['total_rank']:>5}")
    print()
    me = get_my_team_summary(dist)
    print(f"My team ({me['team_name']}): "
          f"hit rank #{me['hit']['rank']}/14 (SD {me['hit']['sd']}), "
          f"pitch rank #{me['pitch']['rank']}/14 (SD {me['pitch']['sd']}), "
          f"total rank #{me['total']['rank']}/14 (mean {me['total']['mean']})")
