"""
One-time Yahoo OAuth2 bootstrap.

Yahoo deprecated the `oob` redirect_uri in their developer console, but the
yahoo_oauth library still hardcodes it. So we do the auth code exchange
manually here using the redirect_uri registered with the Yahoo app
(https://localhost/) and write the resulting tokens into oauth2.json in
the format yahoo_oauth expects. After this runs once, the rest of the
codebase uses yahoo_oauth normally and tokens auto-refresh.

Run:
    python setup_oauth.py
"""

import json
import time
import sys
import webbrowser
from pathlib import Path
from urllib.parse import urlencode, urlparse, parse_qs

import requests

OAUTH_FILE = Path(__file__).parent / "oauth2.json"
REDIRECT_URI = "https://oauth.pstmn.io/v1/callback"
AUTH_URL = "https://api.login.yahoo.com/oauth2/request_auth"
TOKEN_URL = "https://api.login.yahoo.com/oauth2/get_token"


def main():
    creds = json.loads(OAUTH_FILE.read_text())
    client_id = creds["consumer_key"]
    client_secret = creds["consumer_secret"]

    # Step 1: build authorization URL
    auth_params = {
        "client_id": client_id,
        "redirect_uri": REDIRECT_URI,
        "response_type": "code",
        "language": "en-us",
    }
    auth_url = f"{AUTH_URL}?{urlencode(auth_params)}"

    print("\n=== Yahoo OAuth bootstrap ===\n")
    print("1. A browser will open. Sign in to Yahoo and click 'Agree'.")
    print("2. After you click Agree, you'll land on Postman's OAuth callback")
    print("   page — it'll display the auth code clearly on the page.")
    print("3. Copy the displayed code (or the entire URL — script extracts it).")
    print("4. Paste it back here.\n")
    print(f"Auth URL:\n{auth_url}\n")

    try:
        webbrowser.open(auth_url)
    except Exception:
        print("(Couldn't auto-open browser. Copy the URL above manually.)")

    code = input("Paste the `code` value from the redirected URL: ").strip()

    # Some users paste the whole URL — handle that gracefully
    if code.startswith("http"):
        qs = parse_qs(urlparse(code).query)
        code = qs.get("code", [""])[0].strip()
        print(f"  (Extracted code: {code[:8]}...)")

    if not code:
        print("ERROR: empty code")
        return 1

    # Step 2: exchange code for tokens
    print("\nExchanging code for tokens...")
    resp = requests.post(
        TOKEN_URL,
        data={
            "grant_type": "authorization_code",
            "redirect_uri": REDIRECT_URI,
            "code": code,
        },
        auth=(client_id, client_secret),
        headers={"Accept": "application/json"},
    )
    if resp.status_code != 200:
        print(f"ERROR {resp.status_code}: {resp.text}")
        return 1

    data = resp.json()
    print("Got tokens.")

    # Step 3: write oauth2.json in yahoo_oauth's expected shape
    out = {
        "consumer_key": client_id,
        "consumer_secret": client_secret,
        "access_token": data["access_token"],
        "refresh_token": data["refresh_token"],
        "guid": data.get("xoauth_yahoo_guid", ""),
        "token_time": time.time(),
        "token_type": data.get("token_type", "bearer"),
    }
    OAUTH_FILE.write_text(json.dumps(out, indent=2))
    print(f"Wrote {OAUTH_FILE}")

    # Step 4: smoke test
    print("\nSmoke test...")
    from yahoo_oauth import OAuth2
    sess = OAuth2(None, None, from_file=str(OAUTH_FILE))
    if sess.token_is_valid():
        print("✓ TOKEN VALID — you're good to go.")
        return 0
    print("Token reports invalid; trying refresh...")
    sess.refresh_access_token()
    if sess.token_is_valid():
        print("✓ TOKEN VALID after refresh.")
        return 0
    print("✗ Token still invalid. Something's off.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
