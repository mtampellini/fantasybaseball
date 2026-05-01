# Tamp Slam Fantasy Tracker

Daily report for Mike's fantasy baseball team in Il Nuovo Vesuvio (Yahoo H2H points league).

**Live report:** `https://mtampellini.github.io/fantasybaseball/`
**Draft HQ:** `https://mtampellini.github.io/fantasybaseball/draft/`

## What it does

Every morning at 8am ET, a GitHub Action runs `daily_report.py`, which:

1. Pulls my current roster from Yahoo
2. Pulls top 30 free agent hitters and pitchers from Yahoo
3. Pulls season Statcast (xwOBA, K%, BB%, BABIP, etc.) from Baseball Savant
4. Pulls per-start xwOBA for my pitchers + top 15 FA SPs from Savant's player-services endpoint
5. Pulls 16-day probable starting pitchers grid from Fangraphs RosterResource
6. Renders an HTML report and commits it to `index.html`
7. GitHub Pages serves the latest report

Open the site each morning, get a fresh report.

## Report sections

1. **My Hitters** — current lineup with BABIP, wOBA, xwOBA, xSLG, wOBA−xwOBA gap (regression flag)
2. **My Pitchers** — current rotation with K%, BB%, K-BB%, BABIP, wOBA, xwOBA, per-start xwOBA SD, and last 5 starts
3. **FA Hitters (Top 30)** — same metrics, sortable in browser
4. **FA Pitchers (Top 30)** — same metrics + per-start for top 15
5. **Probable Pitchers** — my rotation's upcoming starts + FA pitchers' starts (this week + next week)

## One-time setup

### 1. Register a Yahoo Developer App

1. Go to https://developer.yahoo.com/apps/
2. Create new app:
   - Name: anything (e.g. "Fantasy Tracker")
   - Redirect URI: `oob` (out of band)
   - API Permissions: Fantasy Sports → Read
3. Save the **Client ID** and **Client Secret**

### 2. Bootstrap OAuth tokens locally

Create `oauth2.json` in repo root:

```json
{
  "consumer_key": "YOUR_CLIENT_ID",
  "consumer_secret": "YOUR_CLIENT_SECRET"
}
```

Then:

```bash
pip install -r requirements.txt
python -c "from yahoo_oauth import OAuth2; o = OAuth2(None, None, from_file='oauth2.json'); print('OK' if o.token_is_valid() else 'AUTH NEEDED')"
```

The first run will open a browser for you to authorize. After consenting, paste the verification code into your terminal. The library writes the access/refresh tokens back into `oauth2.json`.

### 3. Test locally

```bash
python daily_report.py
```

This should print progress for each step and write `index.html`. Open it in a browser.

### 4. Add OAuth secret to GitHub

```bash
# Get the contents of oauth2.json (it now has tokens)
cat oauth2.json

# Go to your repo → Settings → Secrets and variables → Actions → New repository secret
#   Name:  YAHOO_OAUTH_JSON
#   Value: <paste the entire JSON file>
```

### 5. Enable GitHub Pages

Repo → Settings → Pages → Source: **Deploy from a branch** → Branch: **main** → Folder: **/ (root)** → Save.

After the first successful workflow run, your report is live at `https://mtampellini.github.io/fantasybaseball/`.

### 6. Verify the workflow

Go to **Actions** tab → **Daily Fantasy Report** → **Run workflow** (manual trigger). After ~2 minutes it should commit a fresh report. Check `index.html` updated in the repo and the live URL shows it.

## File layout

```
fantasybaseball/
├── config.py                       # league IDs, team IDs, thresholds
├── utils.py                        # name normalization helpers
├── pull_yahoo.py                   # roster + FA wire from Yahoo
├── pull_savant.py                  # season Statcast leaderboards
├── pull_per_start.py               # per-start xwOBA endpoint
├── pull_probables.py               # Fangraphs probables grid
├── enrich.py                       # merge Yahoo players w/ Savant stats
├── render_report.py                # HTML output
├── daily_report.py                 # main orchestrator
├── requirements.txt
├── index.html                      # latest daily report (overwritten daily, served at /)
├── reports/
│   └── YYYY-MM-DD.html             # archived per-day reports
├── draft/
│   └── index.html                  # Draft HQ / Mock Draft / Roster Builder app
├── data/
│   └── snapshots/                  # daily JSON archives (raw data)
└── .github/workflows/
    └── daily-report.yml            # cron + manual workflow
```

## Notes

- **Per-start xwOBA accuracy:** uses Savant's `/player-services/statcast-pitches-breakdown` endpoint with `timeFrame=game`. Aggregates per-pitch-type rows by game date, weighted by PA. Matches the values shown in Savant's player page Pitch Tracking → All Pitches → Game view.
- **Fangraphs probables:** parses the `__NEXT_DATA__` JSON blob from the Probables Grid page. No JS execution required. ~16 days of forward-looking starts.
- **Yahoo OAuth:** tokens auto-refresh. If the GitHub Action ever fails with auth errors, regenerate locally and update the `YAHOO_OAUTH_JSON` secret.
- **Color coding in report:**
  - Pitcher xwOBA: green ≤ .260, red ≥ .330
  - Hitter xwOBA: green ≥ .350, red ≤ .280
  - K-BB%: green ≥ 18, red ≤ 12
  - wOBA−xwOBA gap: red if > +80 (regression coming), green if < −50 (positive regression)

## Future enhancements (not built yet)

- Day-over-day deltas (need 2+ snapshots in `data/snapshots/`)
- Trend tracking (e.g. xwOBA 7-day rolling)
- Weekly matchup analysis vs current opponent
- Lineup recommendations based on opposing SP handedness
