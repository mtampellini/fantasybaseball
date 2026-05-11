"""
Team-vs-team SP comparison for league 41657.

For each team, join their rostered SPs to our 2026 projection table and
compute:
    - sum of top-5 projected FP/start (weekly-usage proxy)
    - sum of all rostered SPs
    - mean projection per matched SP
    - count of "top-30" SPs rostered
    - count of "top-50" SPs rostered

Outputs:
    output/team_compare.csv
    output/team_compare.html  (color-coded)
"""

from __future__ import annotations

import json
import unicodedata
from pathlib import Path

import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
ROSTERS = ROOT / "data" / "rosters.json"
PROJ_CSV = ROOT / "output" / "2026_pitcher_projections.csv"
OUT_CSV = ROOT / "output" / "team_compare.csv"
OUT_HTML = ROOT / "output" / "team_compare.html"


def norm_last(s: str) -> str:
    s = str(s).split(",", 1)[0].strip().lower()
    return "".join(c for c in unicodedata.normalize("NFKD", s) if not unicodedata.combining(c))


def last_name_of(full_name: str) -> str:
    return norm_last(full_name.rsplit(" ", 1)[-1])


def main():
    rosters = json.loads(ROSTERS.read_text())["teams"]
    proj = pd.read_csv(PROJ_CSV).reset_index(drop=True)
    proj["rank"] = proj.index + 1
    proj["last_norm"] = proj["pitcher_name"].map(norm_last)
    proj_lookup = proj.set_index("last_norm")

    rows = []
    by_team_detail = {}

    for tid, info in rosters.items():
        tname = info["name"]
        sps = [p for p in info["players"] if "SP" in (p.get("eligible_positions") or [])]
        matched, unmatched = [], []
        for p in sps:
            last = last_name_of(p["name"])
            if last in proj_lookup.index:
                row = proj_lookup.loc[last]
                # If duplicate last names, take the higher-projected one
                if isinstance(row, pd.DataFrame):
                    row = row.sort_values("fp_projection", ascending=False).iloc[0]
                matched.append({
                    "yahoo_name": p["name"],
                    "proj_name": row["pitcher_name"],
                    "team": row["team"],
                    "rank": int(row["rank"]),
                    "n_starts_prior": int(row["n_starts_prior"]),
                    "fp_projection": float(row["fp_projection"]),
                    "status": p.get("status", ""),
                })
            else:
                unmatched.append({"name": p["name"], "status": p.get("status", "")})

        matched_df = pd.DataFrame(matched).sort_values("fp_projection", ascending=False).reset_index(drop=True) if matched else pd.DataFrame()
        top5_sum = matched_df.head(5)["fp_projection"].sum() if len(matched_df) else 0.0
        all_sum = matched_df["fp_projection"].sum() if len(matched_df) else 0.0
        mean_proj = matched_df["fp_projection"].mean() if len(matched_df) else float("nan")
        top30_ct = int((matched_df["rank"] <= 30).sum()) if len(matched_df) else 0
        top50_ct = int((matched_df["rank"] <= 50).sum()) if len(matched_df) else 0

        rows.append({
            "team_id": int(tid),
            "team_name": tname,
            "sp_count_total": len(sps),
            "sp_count_matched": len(matched),
            "top30_rostered": top30_ct,
            "top50_rostered": top50_ct,
            "top5_proj_sum": round(top5_sum, 2),
            "all_proj_sum": round(all_sum, 2),
            "mean_proj": round(mean_proj, 2) if pd.notna(mean_proj) else None,
        })
        by_team_detail[int(tid)] = {"matched": matched_df, "unmatched": unmatched}

    df = pd.DataFrame(rows).sort_values("top5_proj_sum", ascending=False).reset_index(drop=True)
    df["rank_top5"] = df.index + 1
    df.to_csv(OUT_CSV, index=False)
    print(f"Wrote {OUT_CSV}\n")
    print("=== League SP rankings (sum of top-5 projected FP/start) ===")
    print(df[["rank_top5", "team_name", "top5_proj_sum", "all_proj_sum",
             "top30_rostered", "top50_rostered", "sp_count_total", "sp_count_matched"]].to_string(index=False))

    # ---- HTML report
    my_id = 11
    rows_html = []
    for _, r in df.iterrows():
        is_mine = int(r["team_id"]) == my_id
        bg = "#c8e6c9" if is_mine else "transparent"
        rows_html.append(
            f"<tr style='background:{bg};'>"
            f"<td style='text-align:right;'>{int(r['rank_top5'])}</td>"
            f"<td><b>{r['team_name']}</b>{' (you)' if is_mine else ''}</td>"
            f"<td style='text-align:right;'>{r['top5_proj_sum']:.2f}</td>"
            f"<td style='text-align:right;'>{r['all_proj_sum']:.2f}</td>"
            f"<td style='text-align:right;'>{r['mean_proj'] if pd.notna(r['mean_proj']) else '—':.2f}</td>"
            f"<td style='text-align:right;'>{int(r['top30_rostered'])}</td>"
            f"<td style='text-align:right;'>{int(r['top50_rostered'])}</td>"
            f"<td style='text-align:right;'>{int(r['sp_count_matched'])}/{int(r['sp_count_total'])}</td>"
            f"</tr>"
        )

    # Detail blocks per team (sorted by their rank)
    detail_blocks = []
    for _, r in df.iterrows():
        tid = int(r["team_id"])
        det = by_team_detail[tid]
        mine_class = " (you)" if tid == my_id else ""
        block = [
            f"<h3 id='t{tid}'>{int(r['rank_top5'])}. {r['team_name']}{mine_class}</h3>",
            f"<div class='sub'>Top-5 sum: <b>{r['top5_proj_sum']:.2f}</b> · All-SP sum: {r['all_proj_sum']:.2f} · Mean: {r['mean_proj']:.2f}</div>",
            "<table class='inner'>",
            "<thead><tr><th>Rank</th><th>Pitcher</th><th>Team</th><th>N</th><th>Proj FP/start</th><th>Status</th></tr></thead><tbody>",
        ]
        for _, mp in det["matched"].iterrows():
            top5_class = "top5" if mp.name < 5 else ""  # name == positional index post-reset
            block.append(
                f"<tr class='{top5_class}'>"
                f"<td style='text-align:right;'>{mp['rank']}</td>"
                f"<td>{mp['proj_name']}</td>"
                f"<td>{mp['team']}</td>"
                f"<td style='text-align:right;'>{mp['n_starts_prior']}</td>"
                f"<td style='text-align:right;'>{mp['fp_projection']:.2f}</td>"
                f"<td>{mp['status']}</td>"
                f"</tr>"
            )
        block.append("</tbody></table>")
        if det["unmatched"]:
            names = ", ".join(f"{p['name']}{' ['+p['status']+']' if p['status'] else ''}" for p in det["unmatched"])
            block.append(f"<div class='note'>Not in dataset (need ≥4 starts or IL): {names}</div>")
        detail_blocks.append("\n".join(block))

    html = f"""<!doctype html><html><head><meta charset="utf-8">
<title>League SP Power Rankings — 2026</title>
<style>
body {{ font-family: -apple-system, Segoe UI, sans-serif; max-width: 1000px; margin: 2em auto; padding: 0 1em; color: #222; }}
h1 {{ margin-bottom: 0.2em; }}
.sub {{ color: #777; margin-bottom: 1.2em; font-size: 14px; }}
table {{ border-collapse: collapse; width: 100%; font-size: 14px; margin-bottom: 0.5em; }}
th, td {{ padding: 6px 10px; border-bottom: 1px solid #e5e5e5; }}
th {{ background: #f5f5f5; text-align: left; }}
.note {{ color: #777; font-size: 13px; margin-bottom: 1em; }}
.top5 td {{ background: #e3f2fd; font-weight: 600; }}
h3 {{ margin-top: 2em; margin-bottom: 0.2em; }}
.inner th {{ background: #fafafa; }}
</style></head><body>
<h1>League SP Power Rankings — League 41657 · 2026</h1>
<div class='sub'>Generated 2026-05-11. Ranked by sum of each team's top-5 projected FP/start (5 SPs = typical weekly-usage cap).</div>

<table>
<thead><tr>
  <th>Rank</th><th>Team</th><th>Top-5 sum</th><th>All-SP sum</th><th>Mean/SP</th>
  <th>Top-30 SPs</th><th>Top-50 SPs</th><th>Matched/Total</th>
</tr></thead>
<tbody>{chr(10).join(rows_html)}</tbody>
</table>

<h2>Team detail</h2>
{chr(10).join(detail_blocks)}
</body></html>
"""
    OUT_HTML.write_text(html, encoding="utf-8")
    print(f"\nWrote {OUT_HTML}")


if __name__ == "__main__":
    main()
