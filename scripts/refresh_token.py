#!/usr/bin/env python3
"""Refresh the 60-day Instagram long-lived token and write it back as a secret.

Meta's long-lived tokens expire after 60 days and can be refreshed any time
after they are 24 hours old. The weekly workflow runs this so the token never
gets close to expiry.

Writing the new value back needs the `gh` CLI authenticated with a token that
has `secrets: write` on this repo (GITHUB_TOKEN from Actions cannot do it).
Without that, this prints the new token and tells you to paste it, which is the
fallback if you would rather not keep a PAT around.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import httpx  # noqa: E402

from newsletter.config import env  # noqa: E402
from newsletter.publish.instagram import DEFAULT_GRAPH_VERSION  # noqa: E402

SECRET_NAME = "IG_ACCESS_TOKEN"


def refresh() -> tuple[str, int]:
    version = env("GRAPH_VERSION", DEFAULT_GRAPH_VERSION)
    response = httpx.get(
        f"https://graph.facebook.com/{version}/oauth/access_token",
        params={
            "grant_type": "fb_exchange_token",
            "client_id": env("META_APP_ID", required=True),
            "client_secret": env("META_APP_SECRET", required=True),
            "fb_exchange_token": env("IG_ACCESS_TOKEN", required=True),
        },
        timeout=30.0,
    )
    payload = response.json()
    if "error" in payload:
        raise RuntimeError(f"refresh failed: {payload['error'].get('message')}")
    return payload["access_token"], int(payload.get("expires_in", 0))


def store(token: str) -> bool:
    """Write the token back via gh. Returns False if gh cannot do it."""
    repo = os.environ.get("GITHUB_REPOSITORY")
    if not repo:
        return False
    try:
        subprocess.run(
            ["gh", "secret", "set", SECRET_NAME, "--repo", repo, "--body", token],
            check=True,
            capture_output=True,
            text=True,
        )
        return True
    except (subprocess.CalledProcessError, FileNotFoundError) as exc:
        detail = getattr(exc, "stderr", str(exc))
        print(f"could not write the secret via gh: {detail}", file=sys.stderr)
        return False


def main() -> int:
    try:
        token, expires_in = refresh()
    except Exception as exc:  # noqa: BLE001
        print(f"FAILED: {exc}", file=sys.stderr)
        return 1

    days = expires_in // 86400
    print(f"refreshed, valid for ~{days} days")

    if store(token):
        print(f"{SECRET_NAME} updated")
        return 0

    # Never print the token in CI logs - it would end up in the run history.
    if os.environ.get("CI"):
        print("set the secret manually - run this locally to see the value", file=sys.stderr)
        return 1
    print(f"\n{SECRET_NAME}={token}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
