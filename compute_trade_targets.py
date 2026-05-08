"""
Score and rank "Trade Targets" — undervalued hitters rostered by other teams.

Three signals combined into one unlucky score:
  a) 2026 xwOBA - wOBA gap          (weight 2.0, primary)
  b) 2026 BABIP below career baseline (weight 1.0)
  c) 2026 wOBA below 2025 wOBA       (weight 1.0, capped)

Filters: ≥50 PA in 2026 (uses Yahoo `pa_season`); YoY signal only counts when
2025 had ≥200 PA. Excludes catchers, IL/NA/suspended, my team.

Inputs are the already-Statcast-enriched `rostered_hitters_other` list from
daily_report (which has woba/xwoba/babip/mlbam_id and Yahoo pa_season attached),
plus the 2025 + career hitter indices from pull_savant_historical.
"""

from utils import normalize_name
from config import YAHOO_TEAM_ID


DEFAULT_BABIP_BASELINE = 0.290

MIN_PA_2026 = 50
MIN_PA_2025 = 200

W_GAP = 2.0
W_BABIP = 1.0
W_YOY = 1.0

YOY_DROP_CAP = 0.040  # cap raw drop at 40 wOBA points so a collapse doesn't dominate


def is_eligible_target(player):
    """Hitter trade-target candidate filter."""
    if str(player.get("owner_team_id")) == str(YAHOO_TEAM_ID):
        return False
    if player.get("position_type") and player["position_type"] != "B":
        return False
    pos = player.get("eligible_positions") or []
    if "C" in pos:
        return False
    s = (player.get("status") or "").upper()
    if "IL" in s or s == "NA" or "SUSP" in s:
        return False
    return True


def score_hitter_unlucky(stats_2026, stats_2025, career_babip):
    """Compute combined unlucky score + driver breakdown.

    stats_2026 dict needs keys: pa, woba, xwoba, babip
    stats_2025 dict (or None) needs keys: pa, woba, babip
    career_babip is a float or None.

    Returns (score, drivers) or (None, None) if 2026 sample is too small.
    """
    if not stats_2026:
        return None, None
    pa_2026 = stats_2026.get("pa") or 0
    if pa_2026 < MIN_PA_2026:
        return None, None

    woba_2026 = stats_2026.get("woba")
    xwoba_2026 = stats_2026.get("xwoba")
    babip_2026 = stats_2026.get("babip")

    # a) xwOBA - wOBA (positive = unlucky / undervalued)
    gap_raw = None
    gap_score = 0.0
    if woba_2026 is not None and xwoba_2026 is not None:
        gap_raw = xwoba_2026 - woba_2026
        gap_score = max(0.0, gap_raw) * 1000

    # b) BABIP luck — career baseline preferred, then 2025, then default
    babip_baseline = career_babip
    babip_baseline_source = "career"
    if babip_baseline is None:
        babip_baseline = stats_2025.get("babip") if stats_2025 else None
        babip_baseline_source = "2025"
    if babip_baseline is None:
        babip_baseline = DEFAULT_BABIP_BASELINE
        babip_baseline_source = "default"

    babip_score = 0.0
    babip_delta = None
    if babip_2026 is not None:
        babip_delta = babip_baseline - babip_2026
        babip_score = max(0.0, babip_delta) * 100

    # c) YoY wOBA — only counts when 2025 was a real sample
    yoy_score = 0.0
    yoy_delta = None
    pa_2025 = (stats_2025.get("pa") if stats_2025 else None) or 0
    woba_2025 = stats_2025.get("woba") if stats_2025 else None
    if pa_2025 >= MIN_PA_2025 and woba_2025 is not None and woba_2026 is not None:
        yoy_delta = woba_2025 - woba_2026
        yoy_score = max(0.0, min(YOY_DROP_CAP, yoy_delta)) * 100

    score = W_GAP * gap_score + W_BABIP * babip_score + W_YOY * yoy_score

    drivers = {
        "pa_2026": pa_2026,
        "woba_2026": woba_2026,
        "xwoba_2026": xwoba_2026,
        "babip_2026": babip_2026,
        "gap_raw": round(gap_raw, 3) if gap_raw is not None else None,
        "gap_points": round(gap_raw * 1000, 1) if gap_raw is not None else None,
        "gap_score": round(W_GAP * gap_score, 2),
        "babip_baseline": round(babip_baseline, 3) if babip_baseline is not None else None,
        "babip_baseline_source": babip_baseline_source,
        "babip_delta": round(babip_delta, 3) if babip_delta is not None else None,
        "babip_score": round(W_BABIP * babip_score, 2),
        "pa_2025": pa_2025 or None,
        "woba_2025": woba_2025,
        "yoy_delta": round(yoy_delta, 3) if yoy_delta is not None else None,
        "yoy_score": round(W_YOY * yoy_score, 2),
    }
    return round(score, 2), drivers


def rank_trade_targets(rostered_hitters, hitter_2025_index, career_index, top_n=20):
    """Score every eligible rostered hitter and return ranked list.

    `rostered_hitters` is the already-enriched `rostered_hitters_other` list
    from daily_report — each entry has Statcast fields (woba/xwoba/babip)
    and Yahoo `pa_season`.
    """
    out = []
    for player in rostered_hitters:
        if not is_eligible_target(player):
            continue
        # Use Yahoo pa_season (it's there for every rostered hitter that
        # daily_report processed); fall back to 0 to fail the MIN_PA check.
        pa_2026 = player.get("pa_season") or 0

        stats_2026 = {
            "pa": pa_2026,
            "woba": player.get("woba"),
            "xwoba": player.get("xwoba"),
            "babip": player.get("babip"),
        }

        norm = normalize_name(player.get("name") or "")
        stats_2025 = hitter_2025_index.get(norm)
        if not stats_2025:
            # Last-name fallback
            parts = norm.split()
            if parts:
                last, first_init = parts[-1], parts[0][0]
                for k, v in hitter_2025_index.items():
                    if k.endswith(" " + last) and k.startswith(first_init):
                        stats_2025 = v
                        break
        career = career_index.get(norm)
        if not career:
            parts = norm.split()
            if parts:
                last, first_init = parts[-1], parts[0][0]
                for k, v in career_index.items():
                    if k.endswith(" " + last) and k.startswith(first_init):
                        career = v
                        break
        career_babip = career.get("career_babip") if career else None

        score, drivers = score_hitter_unlucky(stats_2026, stats_2025, career_babip)
        if score is None:
            continue

        out.append({
            "name": player.get("name"),
            "owner_team_id": player.get("owner_team_id"),
            "owner_team_name": player.get("owner_team_name"),
            "team": player.get("team") or "",
            "eligible_positions": player.get("eligible_positions") or [],
            "mlbam_id": player.get("mlbam_id"),
            "score": score,
            "drivers": drivers,
        })

    out.sort(key=lambda x: x["score"], reverse=True)
    return out[:top_n]


def print_top_targets(targets, n=5):
    """Console summary for the validation step."""
    print(f"\n  === Top {n} Trade Targets ===")
    for i, t in enumerate(targets[:n], 1):
        d = t["drivers"]
        print(f"  #{i}  {t['name']}  ({t['team'] or '—'}, {','.join(t['eligible_positions'])}) "
              f"— rostered by {t['owner_team_name']}  | score {t['score']}")
        print(f"      2026: PA {d['pa_2026']}  wOBA {_fmt(d['woba_2026'])}  "
              f"xwOBA {_fmt(d['xwoba_2026'])}  gap {d['gap_points']:+}  "
              f"BABIP {_fmt(d['babip_2026'])}")
        print(f"      baseline BABIP {_fmt(d['babip_baseline'])} ({d['babip_baseline_source']})  "
              f"Δ {_fmt(d['babip_delta'])}")
        print(f"      2025: PA {d['pa_2025']}  wOBA {_fmt(d['woba_2025'])}  "
              f"YoY Δ {_fmt(d['yoy_delta'])}")
        print(f"      scores: gap {d['gap_score']}  babip {d['babip_score']}  yoy {d['yoy_score']}")


def _fmt(v):
    if v is None:
        return "—"
    if isinstance(v, float):
        return f"{v:.3f}"
    return str(v)
