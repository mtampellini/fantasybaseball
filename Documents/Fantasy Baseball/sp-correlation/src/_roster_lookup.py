"""Pull Tamp Slam SPs from the latest local snapshot and join with projections."""
import json
from pathlib import Path
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
SNAP_DIR = Path(r"C:\Users\mtamp\data\snapshots")
PROJ_CSV = ROOT / "output" / "2026_pitcher_projections.csv"

# Find latest snapshot
snap_files = sorted(SNAP_DIR.glob("*.json"))
if not snap_files:
    raise SystemExit("no snapshots found")
latest = snap_files[-1]
print(f"Using snapshot: {latest.name}")
snap = json.loads(latest.read_text())

print(f"\n=== Tamp Slam pitchers ===")
sp_names = []
for p in snap["my_pitchers"]:
    name = p.get("name", "?")
    eligs = p.get("eligible_positions", [])
    is_sp = "SP" in eligs or p.get("selected_position") == "SP"
    if is_sp:
        sp_names.append(name)

# Free agent SPs from the snapshot
fa_sp_names = []
for p in snap.get("fa_pitchers", []):
    eligs = p.get("eligible_positions", [])
    if "SP" in eligs:
        fa_sp_names.append(p.get("name", "?"))

print(f"My SPs: {len(sp_names)}    FA SPs in snapshot: {len(fa_sp_names)}")

# Load projections, build the top-50 with rostered highlight
proj = pd.read_csv(PROJ_CSV).reset_index(drop=True)
proj["rank"] = proj.index + 1

# Match rostered names against projection's pitcher_name.
# Projection format: either just "Lastname" or "Lastname, F" (last-first-initial).
# Roster format: "First Last" or "First Lastname".
# Compare *last names* exactly (case-insensitive), ignoring suffixes/diacritics.
def _norm_last(s: str) -> str:
    # take everything before the first comma; lowercase; strip diacritics
    s = str(s).split(",", 1)[0].strip().lower()
    import unicodedata
    return "".join(c for c in unicodedata.normalize("NFKD", s) if not unicodedata.combining(c))

def match_one(full_name, proj_names):
    last = full_name.rsplit(" ", 1)[-1]
    target = _norm_last(last)
    hits = proj_names[proj_names.map(_norm_last) == target]
    return hits.index.tolist()

def attach_role(proj_df, my_names, fa_names):
    """Tag each projection row as 'mine', 'fa', or 'other' (rostered elsewhere)."""
    role = pd.Series(["other"] * len(proj_df), index=proj_df.index)
    name_to_role: dict[int, str] = {}
    for n in my_names:
        for idx in match_one(n, proj_df["pitcher_name"]):
            name_to_role[idx] = "mine"
    for n in fa_names:
        for idx in match_one(n, proj_df["pitcher_name"]):
            if idx not in name_to_role:  # mine wins over FA
                name_to_role[idx] = "fa"
    for idx, r in name_to_role.items():
        role.iloc[idx] = r
    return role

proj["role"] = attach_role(proj, sp_names, fa_sp_names)

# Identify unmatched rostered SPs
def matched_indices(names, proj_df):
    out = []
    for n in names:
        out.extend(match_one(n, proj_df["pitcher_name"]))
    return out

my_idx = matched_indices(sp_names, proj)
unmatched = [n for n in sp_names if not match_one(n, proj["pitcher_name"])]
print(f"\nMatched {len(set(my_idx))} of {len(sp_names)} rostered SPs")
print(f"FA SPs matched in projection: {sum(proj['role'] == 'fa')}")

top50 = proj.head(50).copy()

# Include any rostered SP below 50
rostered_below_50_idx = [i for i in set(my_idx) if i >= 50]
extras = proj.iloc[rostered_below_50_idx].copy() if rostered_below_50_idx else pd.DataFrame()
out = pd.concat([top50, extras], ignore_index=True) if len(extras) else top50

# --- Console
print(f"\n=== Top 50 SP Projections (+ {len(extras)} rostered below 50) ===")
print(f"{'#':>3}  {'Role':>5}  {'Pitcher':25s} {'Team':12s} {'N':>3} {'Proj FP':>8}")
print("-" * 70)
for _, r in out.iterrows():
    role = r.get("role", "other")
    flag = {"mine": " MINE", "fa": "   FA", "other": "     "}[role]
    print(f"{int(r['rank']):>3}  {flag:>5}  {str(r['pitcher_name']):25s} {str(r['team']):12s} {int(r['n_starts_prior']):>3} {r['fp_projection']:>8.2f}")

# --- HTML (with color highlight)
html_rows = []
for _, r in out.iterrows():
    role = r.get("role", "other")
    bg = {"mine": "#c8e6c9", "fa": "#fff9c4", "other": "transparent"}[role]
    label = {"mine": "★ MINE", "fa": "FA", "other": ""}[role]
    html_rows.append(
        f"<tr style='background:{bg};'>"
        f"<td style='text-align:right;'>{int(r['rank'])}</td>"
        f"<td><b>{r['pitcher_name']}</b></td>"
        f"<td>{r['team']}</td>"
        f"<td style='text-align:right;'>{int(r['n_starts_prior'])}</td>"
        f"<td style='text-align:right;'>{r['fp_projection']:.2f}</td>"
        f"<td>{label}</td>"
        f"</tr>"
    )
html = f"""<!doctype html><html><head><meta charset="utf-8">
<title>Top 50 SPs — Tamp Slam 2026</title>
<style>
body {{ font-family: -apple-system, Segoe UI, Helvetica, sans-serif; max-width: 900px; margin: 2em auto; padding: 0 1em; color: #222; }}
h1 {{ margin-bottom: 0.2em; }}
.sub {{ color: #777; margin-bottom: 1.5em; }}
table {{ border-collapse: collapse; width: 100%; font-size: 14px; }}
th, td {{ padding: 6px 10px; border-bottom: 1px solid #e5e5e5; }}
th {{ background: #f5f5f5; text-align: left; }}
.legend {{ margin-top: 1.5em; font-size: 13px; }}
.swatch {{ display: inline-block; width: 14px; height: 14px; margin-right: 4px; vertical-align: middle; border: 1px solid #ccc; }}
.note {{ color: #777; font-size: 13px; }}
</style></head><body>
<h1>Top 50 SP Projections — Tamp Slam (League 41657)</h1>
<div class="sub">Generated 2026-05-11. Roster source: data/snapshots/{latest.name}. Model: Ridge on 2024+2025 May-15+ as-of features.</div>
<table>
<thead><tr><th>Rank</th><th>Pitcher</th><th>Team</th><th>N starts</th><th>Proj FP/start</th><th>Role</th></tr></thead>
<tbody>
{chr(10).join(html_rows)}
</tbody></table>

<div class="legend">
<div><span class="swatch" style="background:#c8e6c9;"></span> My roster ({sum(out['role'] == 'mine')} in this table)</div>
<div><span class="swatch" style="background:#fff9c4;"></span> Free agent ({sum(out['role'] == 'fa')} in this table)</div>
<div><span class="swatch" style="background:transparent;border:1px solid #ccc;"></span> Rostered by another team</div>
</div>

<h3>Rostered SPs not in projection dataset</h3>
<div class="note">Need ≥4 starts to qualify. Currently excluded:</div>
<ul>
{chr(10).join(f"<li>{n}</li>" for n in unmatched)}
</ul>
</body></html>
"""
# Append: FAs ranked below 50 (waiver wire candidates)
fa_below_50 = proj[(proj["role"] == "fa") & (proj["rank"] > 50)].head(20)
if len(fa_below_50):
    fa_rows = []
    for _, r in fa_below_50.iterrows():
        fa_rows.append(
            f"<tr style='background:#fff9c4;'>"
            f"<td style='text-align:right;'>{int(r['rank'])}</td>"
            f"<td><b>{r['pitcher_name']}</b></td>"
            f"<td>{r['team']}</td>"
            f"<td style='text-align:right;'>{int(r['n_starts_prior'])}</td>"
            f"<td style='text-align:right;'>{r['fp_projection']:.2f}</td>"
            f"</tr>"
        )
    html = html.replace(
        "<h3>Rostered SPs not in projection dataset</h3>",
        f"""<h3>Top FAs ranked below 50 (waiver wire candidates)</h3>
<table>
<thead><tr><th>Rank</th><th>Pitcher</th><th>Team</th><th>N starts</th><th>Proj FP/start</th></tr></thead>
<tbody>{chr(10).join(fa_rows)}</tbody>
</table>
<h3>Rostered SPs not in projection dataset</h3>""",
    )

html_path = ROOT / "output" / "top50_with_roster.html"
html_path.write_text(html, encoding="utf-8")
print(f"\nWrote {html_path}")

# --- Markdown (uses GitHub HTML inline-style for color rows)
md = [
    "# Top 50 SP Projections — Tamp Slam 2026",
    "",
    f"_Generated 2026-05-11. Roster source: `data/snapshots/{latest.name}`._",
    "",
    "🟢 = my roster · 🟡 = free agent · ⬜ = rostered elsewhere",
    "",
    "| Rank | Pitcher | Team | N starts | Proj FP/start | Role |",
    "|---:|:---|:---|---:|---:|:---|",
]
for _, r in out.iterrows():
    role = r.get("role", "other")
    icon = {"mine": "🟢 MINE", "fa": "🟡 FA", "other": ""}[role]
    md.append(
        f"| {int(r['rank'])} | {r['pitcher_name']} | {r['team']} | {int(r['n_starts_prior'])} | {r['fp_projection']:.2f} | {icon} |"
    )
if len(fa_below_50):
    md += [
        "",
        "## Free agent SPs ranked below 50 (waiver wire candidates)",
        "",
        "| Rank | Pitcher | Team | N starts | Proj FP/start |",
        "|---:|:---|:---|---:|---:|",
    ] + [
        f"| {int(r['rank'])} | {r['pitcher_name']} | {r['team']} | {int(r['n_starts_prior'])} | {r['fp_projection']:.2f} |"
        for _, r in fa_below_50.iterrows()
    ]

md += [
    "",
    "## Rostered SPs not in projection dataset",
    "",
    "These pitchers don't have ≥4 starts in 2026 (or are on IL):",
    "",
] + [f"- **{n}**" for n in unmatched]
md_path = ROOT / "output" / "top50_with_roster.md"
md_path.write_text("\n".join(md), encoding="utf-8")
print(f"Wrote {md_path}")
