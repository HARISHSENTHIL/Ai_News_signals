#!/usr/bin/env python3
"""Validate the Instagram side before trusting it with a real post.

Run this the moment your Meta app is approved and the token exists:

    python scripts/check_ig.py              # token, permissions, quota
    python scripts/check_ig.py --container  # also prove Meta can fetch the card

--container creates a real media container but never publishes it. Containers
expire on their own after 24 hours, so this is safe to run repeatedly. It is the
step most likely to fail, because it is the only one that depends on your image
URL actually being public.
"""

from __future__ import annotations

import argparse
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import httpx  # noqa: E402

from newsletter.config import env  # noqa: E402
from newsletter.publish.instagram import InstagramError, InstagramPublisher  # noqa: E402


def check_token(publisher: InstagramPublisher) -> None:
    data = publisher._request("GET", publisher.user_id, fields="username,account_type")
    print(f"  account     @{data.get('username')} ({data.get('account_type', 'unknown type')})")


def check_quota(publisher: InstagramPublisher) -> None:
    used, total = publisher.quota()
    print(f"  quota       {used}/{total or '?'} posts used in the last 24h")
    if total and used >= total:
        raise InstagramError("at the cap right now - publishing would fail")


def check_image_url() -> str:
    base = env("PUBLIC_BASE_URL", required=True).rstrip("/")
    url = f"{base}/out/{date.today().isoformat()}/card.jpg"
    response = httpx.head(url, follow_redirects=True, timeout=20.0)
    content_type = response.headers.get("content-type", "")
    print(f"  image       {response.status_code} {content_type} {url}")
    if response.status_code != 200:
        raise InstagramError(
            f"image is not publicly reachable ({response.status_code}). "
            f"Meta fetches this URL itself, so it must be public and committed."
        )
    if "jpeg" not in content_type:
        raise InstagramError(f"Instagram accepts JPEG only, got {content_type!r}")
    return url


def check_container(publisher: InstagramPublisher, image_url: str) -> None:
    container = publisher._request(
        "POST", f"{publisher.user_id}/media", image_url=image_url, caption="preflight check"
    )
    print(f"  container   created {container['id']}, waiting for Meta to fetch...")
    publisher._wait_for_container(container["id"])
    print("  container   FINISHED - not published, it will expire in 24h")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--container",
        action="store_true",
        help="also create (but never publish) a real container from today's card",
    )
    args = parser.parse_args()

    print("checking instagram setup")
    try:
        publisher = InstagramPublisher()
        check_token(publisher)
        check_quota(publisher)
        if args.container:
            check_container(publisher, check_image_url())
    except Exception as exc:  # noqa: BLE001
        print(f"\nFAILED: {type(exc).__name__}: {exc}")
        return 1

    print("\nall checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
