"""
Main entry point. Run daily.

  python daily_report.py

Outputs:
  data/snapshots/YYYY-MM-DD.json   - raw data snapshot
  index.html                        - latest report (GitHub Pages serves this from root)
  reports/YYYY-MM-DD.html           - archived daily report
"""

import json
import sys
from datetime import datetime
from pathlib import Path

from config import (
    YAHOO_TEAM_ID, FA_PITCHER_COUNT, FA_HITTER_COUNT, PER_START_DEPTH
)
from pull_yahoo import (
    fetch_my_roster, fetch_free_agents, fetch_current_matchup,
    fetch_last_month_fp, fetch_last_week_stats, fetch_yahoo_stats,
    fetch_all_rostered_hitters,
    parse_pa_from_yahoo_stats, get_league,
)
from pull_savant import fetch_pitcher_leaderboard, fetch_hitter_leaderboard
from pull_savant_historical import (
    load_or_fetch_2025_hitters, load_or_fetch_career_hitters,
)
from pull_per_start import fetch_per_start_xwoba
from pull_probables import (
    fetch_probables_grid, starts_by_pitcher, get_fantasy_week_bounds,
    count_team_games_in_window,
)
from enrich import enrich_list, attach_per_start, attach_probable_starts
from pull_weekly_results import fetch_all_weeks, fetch_standings
from compute_league_metrics import (
    compute_team_distributions, get_my_team_summary, get_most_recent_completed_week,
)
from compute_trade_targets import rank_trade_targets, print_top_targets
from render_report import render_html


REPO_ROOT = Path(__file__).parent
DATA_DIR = REPO_ROOT / "data"
SNAPSHOT_DIR = DATA_DIR / "snapshots"
REPORT_DIR = REPO_ROOT / "reports"


def split_roster(roster):
    """Separate roster into hitters and pitchers based on position_type."""
    hitters = [p for p in roster if p.get("position_type") == "B"]
    pitchers = [p for p in roster if p.get("position_type") == "P"]
    return hitters, pitchers


def fetch_per_start_for_list(pitchers, depth=5):
    """Fetch per-start xwOBA for a list of pitchers (uses player_id from Savant)."""
    fetcher = lambda pid: fetch_per_start_xwoba(pid, num_starts=depth)
    return attach_per_start(pitchers, fetcher)


def main():
    today = datetime.now().strftime("%Y-%m-%d")
    print(f"=== Tamp Slam Daily Report: {today} ===\n")

    # Step 1: Yahoo data
    print("[1/8] Pulling Yahoo roster + FA wire...")
    roster = fetch_my_roster()
    my_hitters, my_pitchers = split_roster(roster)
    print(f"  Roster: {len(my_hitters)} hitters, {len(my_pitchers)} pitchers")

    # FA candidate pool: pull 2x the displayed count, then filter+rerank later
    fa_pool_size = FA_PITCHER_COUNT * 2
    fa_pitchers = fetch_free_agents("P", fa_pool_size)
    fa_hitters = fetch_free_agents("B", FA_HITTER_COUNT * 2)
    print(f"  FA pool: {len(fa_pitchers)} pitchers, {len(fa_hitters)} hitters")

    # Step 1b: All rostered hitters across the league (for full-league
    # ROS leaderboard at the bottom of the report)
    print("\nPulling rostered hitters across all 14 teams...")
    rostered_hitters_other = fetch_all_rostered_hitters()
    my_hitter_ids = {h["player_id"] for h in my_hitters}
    rostered_hitters_other = [
        h for h in rostered_hitters_other if h.get("player_id") not in my_hitter_ids
    ]
    print(f"  Got {len(rostered_hitters_other)} rostered hitters on other teams")

    # Step 2: Savant season leaderboards
    print("\n[2/8] Pulling Savant season Statcast...")
    pitcher_index = fetch_pitcher_leaderboard()
    hitter_index = fetch_hitter_leaderboard()
    print(f"  Pitchers indexed: {len(pitcher_index)}")
    print(f"  Hitters indexed: {len(hitter_index)}")

    # Step 3: Enrich rosters with Statcast
    print("\n[3/8] Enriching rosters with Statcast data...")
    enrich_list(my_hitters, hitter_index)
    enrich_list(my_pitchers, pitcher_index)
    enrich_list(fa_hitters, hitter_index)
    enrich_list(fa_pitchers, pitcher_index)
    enrich_list(rostered_hitters_other, hitter_index)

    matched_h = sum(1 for p in my_hitters if p.get("savant_matched"))
    matched_p = sum(1 for p in my_pitchers if p.get("savant_matched"))
    matched_other = sum(1 for p in rostered_hitters_other if p.get("savant_matched"))
    print(f"  Matched: {matched_h}/{len(my_hitters)} hitters, "
          f"{matched_p}/{len(my_pitchers)} pitchers, "
          f"{matched_other}/{len(rostered_hitters_other)} rostered-other hitters")

    # Step 4: Per-start xwOBA for my pitchers + top FA pitchers
    print(f"\n[4/8] Pulling per-start xwOBA for {len(my_pitchers)} my pitchers + top FA SPs...")
    fetch_per_start_for_list(my_pitchers, PER_START_DEPTH)
    # Limit FA per-start fetches to top 15 to keep runtime under control
    fa_top = fa_pitchers[:15]
    fetch_per_start_for_list(fa_top, PER_START_DEPTH)
    # The remaining FA pitchers get empty per_start
    for p in fa_pitchers[15:]:
        p["per_start"] = []
        p["per_start_sd"] = None

    # Step 5: Fangraphs probables
    print("\n[5/8] Pulling Fangraphs probables grid...")
    try:
        probables_raw = fetch_probables_grid()
        probables_by_pitcher = starts_by_pitcher(probables_raw)
        print(f"  {len(probables_raw)} games, {len(probables_by_pitcher)} unique pitchers")
    except Exception as e:
        print(f"  WARN: Fangraphs pull failed: {e}")
        probables_raw = []
        probables_by_pitcher = {}

    # Compute fantasy week bounds (Mon-Sun)
    tw_start, tw_end, nw_start, nw_end = get_fantasy_week_bounds()
    print(f"  This week:  {tw_start} -> {tw_end}")
    print(f"  Next week:  {nw_start} -> {nw_end}")

    # Attach to my pitchers + FA pitchers
    attach_probable_starts(my_pitchers, probables_by_pitcher,
                          tw_start, tw_end, nw_start, nw_end)
    attach_probable_starts(fa_pitchers, probables_by_pitcher,
                          tw_start, tw_end, nw_start, nw_end)

    # Step 5b: Avg fantasy points per week over last 4 weeks
    # Yahoo exposes a `lastmonth` (30-day) total; we divide by 4 per request.
    print("\nPulling last-month fantasy points from Yahoo...")
    all_players = my_hitters + my_pitchers + fa_hitters + fa_pitchers
    all_ids = [p["player_id"] for p in all_players if p.get("player_id")]
    fp_30d = fetch_last_month_fp(all_ids)
    print(f"  Got last-month FP for {len(fp_30d)}/{len(all_ids)} players")
    for p in all_players:
        total = fp_30d.get(p.get("player_id"))
        p["avg_fp_4w"] = (total / 4) if total is not None else None

    # Step 5b': last-week stats (recency signal + hitter PA filter)
    # Yahoo doesn't expose 14-day cumulative, so we use lastweek (7d) and
    # extrapolate to 2 weeks for filter thresholds and hybrid scoring.
    print("\nPulling last-week stats from Yahoo (recency)...")
    lw_stats = fetch_last_week_stats(all_ids)
    print(f"  Got last-week stats for {len(lw_stats)}/{len(all_ids)} players")
    for p in all_players:
        s = lw_stats.get(p.get("player_id"))
        if s:
            p["fp_1w"] = s["fp_1w"]
            p["pa_1w"] = s["pa"]
            p["avg_fp_2w_est"] = s["fp_1w"]  # per-week avg (1w data extrapolated to 2w)
        else:
            p["fp_1w"] = None
            p["pa_1w"] = None
            p["avg_fp_2w_est"] = None

    # Step 5b'': season PA + xFP/wk for hitters (volume signal + composite KPI)
    # xFP/wk = xwOBA * 3.5 * weekly_PA. The 3.5 constant is calibrated from
    # this league's scoring (R=1.5, BB=1, HR=4, etc.) so an avg hitter
    # (xwOBA .310, 22 PA/wk) projects to ~24 FP/wk, matching observed values.
    print("\nPulling season totals for hitters (volume + xFP/wk)...")
    league_obj = get_league()
    weeks_played = max(1, int(league_obj.current_week()) - 1)
    hitter_list = my_hitters + fa_hitters + rostered_hitters_other
    hitter_ids = [h["player_id"] for h in hitter_list if h.get("player_id")]
    season_stats = fetch_yahoo_stats(hitter_ids, "season")
    matched = 0
    for h in hitter_list:
        s = season_stats.get(h.get("player_id"))
        if s:
            pa = parse_pa_from_yahoo_stats(s)
            h["pa_season"] = pa
            h["pa_per_wk"] = round(pa / weeks_played, 1) if pa else 0.0
            try:
                sb = int(float(s.get("SB") or 0))
            except (ValueError, TypeError):
                sb = 0
            h["sb_season"] = sb
            h["sb_per_wk"] = round(sb / weeks_played, 2) if sb else 0.0
            matched += 1
        else:
            h["pa_season"] = None
            h["pa_per_wk"] = None
            h["sb_season"] = None
            h["sb_per_wk"] = None
        xw = h.get("xwoba")
        pa_wk = h.get("pa_per_wk")
        sb_wk = h.get("sb_per_wk") or 0.0
        if xw is not None and pa_wk:
            hitting_pts = xw * 3.5 * pa_wk
            sb_pts = sb_wk * 2.0
            h["xfp_hit"] = round(hitting_pts, 1)
            h["xfp_sb"] = round(sb_pts, 1)
            h["xfp_per_wk"] = round(hitting_pts + sb_pts, 1)
        else:
            h["xfp_hit"] = None
            h["xfp_sb"] = None
            h["xfp_per_wk"] = None
    print(f"  Computed PA/wk + SB/wk + xFP/wk for {matched}/{len(hitter_list)} hitters "
          f"(weeks_played={weeks_played})")

    # Step 5b''': forward-looking projections — next week (NW) + rest-of-season (ROS)
    # NW = current xFP/wk × (games_next_week / typical_week_games)
    # ROS = current xFP/wk × weeks_remaining_to_end_of_playoffs
    end_week = int(league_obj.end_week())
    current_week_num = int(league_obj.current_week())
    weeks_remaining = max(0, end_week - current_week_num + 1)  # inclusive of in-progress
    typical_week_games = 6.0  # MLB averages ~6.2 games/wk; round factor for stability
    games_per_team_nw = count_team_games_in_window(probables_raw, nw_start, nw_end)
    print(f"\nForward projections: end_week={end_week}, current={current_week_num}, "
          f"weeks_remaining={weeks_remaining}")
    print(f"  Next week games per team (sample): "
          f"{dict(list(games_per_team_nw.items())[:4])}")
    for h in hitter_list:
        cur = h.get("xfp_per_wk")
        if cur is None:
            h["xfp_next_week"] = None
            h["xfp_ros"] = None
            h["games_next_week"] = None
            continue
        team = h.get("team")
        games_nw = games_per_team_nw.get(team, int(typical_week_games))
        h["games_next_week"] = games_nw
        h["xfp_next_week"] = round(cur * (games_nw / typical_week_games), 1)
        h["xfp_ros"] = round(cur * weeks_remaining, 0)

    # Filter + hybrid-rerank FA pools, then trim to display count.
    # Note: Yahoo's FA list returns fantasy_points=None for all FAs (only
    # populated for rostered players), so we use avg_fp_4w (lastmonth/4)
    # as the longer-term per-week signal and fp_1w (lastweek) as the
    # recent per-week signal. Hybrid = sum of both.
    def _hybrid_score(p):
        long_term = p.get("avg_fp_4w") or 0.0   # ~per-week over last 4 weeks
        recent = p.get("fp_1w") or 0.0          # last 1-week total
        return long_term + recent

    def _keep_hitter(h):
        pa = h.get("pa_1w")
        if pa is None:
            return False
        return pa * 2 >= 15  # estimate 2-week PA from 1-week data

    def _keep_pitcher(p):
        eligible = set(p.get("eligible_positions") or [])
        is_pure_rp = "RP" in eligible and "SP" not in eligible
        if is_pure_rp:
            xw = p.get("xwoba")
            if xw is None or xw >= 0.300:
                return False
        return True

    pre_h = len(fa_hitters)
    pre_p = len(fa_pitchers)
    fa_hitters = [h for h in fa_hitters if _keep_hitter(h)]
    fa_pitchers = [p for p in fa_pitchers if _keep_pitcher(p)]
    print(f"  After filters: {len(fa_hitters)}/{pre_h} hitters, "
          f"{len(fa_pitchers)}/{pre_p} pitchers")

    fa_hitters.sort(key=lambda p: -_hybrid_score(p))
    fa_pitchers.sort(key=lambda p: -_hybrid_score(p))
    fa_hitters = fa_hitters[:FA_HITTER_COUNT]
    fa_pitchers = fa_pitchers[:FA_PITCHER_COUNT]
    print(f"  After hybrid ranking + trim: {len(fa_hitters)} hitters, "
          f"{len(fa_pitchers)} pitchers (top {FA_HITTER_COUNT})")

    # Step 5c: League weekly results + distribution metrics + standings
    print("\nPulling weekly league results...")
    league_metrics = None
    try:
        weeks_data = fetch_all_weeks()
        completed_weeks = [w["week"] for w in weeks_data if not w.get("in_progress")]
        print(f"  Have {len(weeks_data)} weeks of data (completed: {completed_weeks})")
        distributions = compute_team_distributions(weeks_data, exclude_weeks=[1])
        my_summary = get_my_team_summary(distributions)
        recent = get_most_recent_completed_week(weeks_data)
        current = next((w for w in weeks_data if w.get("in_progress")), None)
        print("  Pulling standings...")
        standings = fetch_standings()
        print(f"  Got standings for {len(standings)} teams")
        league_metrics = {
            "current": current,
            "most_recent": recent,
            "distributions": distributions,
            "my_summary": my_summary,
            "standings": standings,
            "weeks_data": weeks_data,
        }
        if my_summary:
            print(f"  Tamp Slam: hit #{my_summary['hit']['rank']}, "
                  f"pitch #{my_summary['pitch']['rank']}, "
                  f"total #{my_summary['total']['rank']}")
    except Exception as e:
        print(f"  WARN: weekly metrics failed: {e}")

    # Step 6: Historical Statcast (2025 + career) for trade-target scoring
    print("\n[6/8] Pulling 2025 + career Savant for trade targets...")
    h2025 = {}
    career_hitters = {}
    try:
        h2025 = load_or_fetch_2025_hitters()
        career_hitters = load_or_fetch_career_hitters()
        print(f"  2025 hitters: {len(h2025)}; career records: {len(career_hitters)}")
    except Exception as e:
        print(f"  WARN: historical Savant pull failed: {e}")

    # Step 7: Score + rank trade targets (uses already-enriched rostered_hitters_other)
    print("\n[7/8] Scoring trade targets...")
    trade_targets = []
    try:
        trade_targets = rank_trade_targets(
            rostered_hitters_other, h2025, career_hitters, top_n=20
        )
        print(f"  {len(trade_targets)} ranked targets")
        if trade_targets:
            print_top_targets(trade_targets, n=5)
    except Exception as e:
        print(f"  WARN: trade-target scoring failed: {e}")

    # Step 8: Build snapshot, write JSON + HTML
    print("\n[8/8] Writing report...")

    # Try matchup info (best-effort; might fail)
    week = "—"
    try:
        m = fetch_current_matchup()
        week = m.get("week", "—")
    except Exception as e:
        print(f"  WARN: current matchup fetch failed: {type(e).__name__}: {e}")

    record = ""
    if league_metrics:
        my_id = int(YAHOO_TEAM_ID)
        my_st = next((s for s in (league_metrics.get("standings") or [])
                      if s.get("team_id") == my_id), None)
        if my_st:
            w, l, t = my_st.get("wins", 0), my_st.get("losses", 0), my_st.get("ties", 0)
            record = f"{w}-{l}" + (f"-{t}" if t else "")

    snapshot = {
        "date": today,
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "week": week,
        "record": record,
        "my_hitters": my_hitters,
        "my_pitchers": my_pitchers,
        "fa_hitters": fa_hitters,
        "fa_pitchers": fa_pitchers,
        "rostered_hitters_other": rostered_hitters_other,
        "trade_targets": trade_targets,
        "fantasy_week_bounds": {
            "this_week_start": tw_start.isoformat(),
            "this_week_end": tw_end.isoformat(),
            "next_week_start": nw_start.isoformat(),
            "next_week_end": nw_end.isoformat(),
        },
        "league_metrics": league_metrics,
    }

    # Ensure dirs exist
    for d in (SNAPSHOT_DIR, REPORT_DIR):
        d.mkdir(parents=True, exist_ok=True)

    # Snapshot JSON (in data/, not deployed)
    snapshot_path = SNAPSHOT_DIR / f"{today}.json"
    with snapshot_path.open("w") as f:
        json.dump(snapshot, f, indent=2, default=str)
    print(f"  Wrote snapshot: {snapshot_path}")

    # HTML report
    html = render_html(snapshot)

    # Latest report at root index.html (served by GitHub Pages)
    index_path = REPO_ROOT / "index.html"
    index_path.write_text(html, encoding="utf-8")
    print(f"  Wrote: {index_path}")

    # Archived report at reports/YYYY-MM-DD.html
    archive_path = REPORT_DIR / f"{today}.html"
    archive_path.write_text(html, encoding="utf-8")
    print(f"  Wrote: {archive_path}")

    print(f"\nDone. View: index.html")
    return 0


if __name__ == "__main__":
    sys.exit(main())
