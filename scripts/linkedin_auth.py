#!/usr/bin/env python3
"""Mint a LinkedIn access token, and print the three values to store.

    python scripts/linkedin_auth.py

LinkedIn hands programmatic refresh tokens only to approved Marketing Developer
Platform partners. A self-serve "Share on LinkedIn" app is not one, so there is
no background renewal to build: this is run by hand roughly every 60 days, and
LinkedInPublisher.preflight() warns before the token lapses.

It runs a one-request web server on localhost purely to catch the redirect, so
the authorization code never has to be copied out of a URL bar.

Prerequisites, all self-serve in https://www.linkedin.com/developers/apps:
  - Products tab: add "Share on LinkedIn" and "Sign In with LinkedIn using
    OpenID Connect". Both are instant; no review.
  - Auth tab: add this exact redirect URL: http://localhost:8765/callback
"""

from __future__ import annotations

import http.server
import secrets
import socket
import sys
import threading
import urllib.parse
import webbrowser
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import httpx  # noqa: E402

from newsletter.config import env  # noqa: E402

PORT = 8765
REDIRECT_URI = f"http://localhost:{PORT}/callback"
AUTH_URL = "https://www.linkedin.com/oauth/v2/authorization"
TOKEN_URL = "https://www.linkedin.com/oauth/v2/accessToken"
# w_member_social posts; openid+profile are what /v2/userinfo needs to tell us
# the person URN, which the publisher has to send as the post's author.
SCOPES = "openid profile w_member_social"

received: dict[str, str] = {}


class Handler(http.server.BaseHTTPRequestHandler):
    def do_GET(self) -> None:  # noqa: N802 - name fixed by BaseHTTPRequestHandler
        query = urllib.parse.parse_qs(urllib.parse.urlsplit(self.path).query)
        received.update({key: values[0] for key, values in query.items()})
        body = (
            b"<h2>Done.</h2><p>Close this tab and go back to the terminal.</p>"
            if "code" in received
            else b"<h2>No code in the callback.</h2><p>Check the terminal.</p>"
        )
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args) -> None:
        pass  # the handler's own logging would interleave with ours


def _port_is_free() -> bool:
    with socket.socket() as probe:
        return probe.connect_ex(("127.0.0.1", PORT)) != 0


def main() -> int:
    client_id = env("LINKEDIN_CLIENT_ID", required=True)
    client_secret = env("LINKEDIN_CLIENT_SECRET", required=True)

    if not _port_is_free():
        print(f"port {PORT} is already in use - stop whatever is on it and retry")
        return 1

    state = secrets.token_urlsafe(16)
    params = {
        "response_type": "code",
        "client_id": client_id,
        "redirect_uri": REDIRECT_URI,
        "state": state,
        "scope": SCOPES,
    }
    url = f"{AUTH_URL}?{urllib.parse.urlencode(params)}"

    server = http.server.HTTPServer(("127.0.0.1", PORT), Handler)
    thread = threading.Thread(target=server.handle_request, daemon=True)
    thread.start()

    print("Opening LinkedIn authorization in your browser.")
    print(f"If it does not open, paste this:\n\n{url}\n")
    webbrowser.open(url)

    thread.join(timeout=300)
    server.server_close()

    if "error" in received:
        print(f"LinkedIn refused: {received['error']} - {received.get('error_description', '')}")
        return 1
    if "code" not in received:
        print("timed out waiting for the redirect")
        return 1
    # Without this check a stray link could trade in a code we never requested.
    if received.get("state") != state:
        print("state mismatch - discarding this response")
        return 1

    response = httpx.post(
        TOKEN_URL,
        data={
            "grant_type": "authorization_code",
            "code": received["code"],
            "redirect_uri": REDIRECT_URI,
            "client_id": client_id,
            "client_secret": client_secret,
        },
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        timeout=30.0,
    )
    if response.status_code >= 400:
        print(f"token exchange failed: {response.status_code} {response.text[:300]}")
        return 1
    payload = response.json()
    token = payload["access_token"]
    expiry = date.today() + timedelta(seconds=int(payload.get("expires_in", 0)))

    granted = payload.get("scope", "")
    if "w_member_social" not in granted:
        print(
            f"token is missing w_member_social (got: {granted or 'nothing'}).\n"
            "Add the 'Share on LinkedIn' product to the app and run this again."
        )
        return 1

    userinfo = httpx.get(
        "https://api.linkedin.com/v2/userinfo",
        headers={"Authorization": f"Bearer {token}"},
        timeout=30.0,
    )
    if userinfo.status_code >= 400:
        print(f"userinfo failed: {userinfo.status_code} {userinfo.text[:200]}")
        print("Add the 'Sign In with LinkedIn using OpenID Connect' product and retry.")
        return 1
    info = userinfo.json()

    print(f"\nAuthenticated as {info.get('name', '?')}")
    print(f"Token expires {expiry.isoformat()} ({payload.get('expires_in', 0) // 86400} days)\n")
    print("Set these three as GitHub Actions secrets, and in .env for local runs:\n")
    print(f"LINKEDIN_ACCESS_TOKEN={token}")
    print(f"LINKEDIN_PERSON_URN=urn:li:person:{info['sub']}")
    print(f"LINKEDIN_TOKEN_EXPIRES_AT={expiry.isoformat()}")
    print(
        f"\nSet a calendar reminder for {(expiry - timedelta(days=7)).isoformat()} "
        "to run this again - there is no automatic refresh for a self-serve app."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
