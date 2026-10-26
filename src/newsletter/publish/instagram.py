"""Instagram publishing via the Graph API.

Two steps, always: create a media container pointing at a publicly reachable
JPEG, then publish that container. Meta fetches the image itself, which is why
the card has to be committed to a public repo before this runs.
"""

from __future__ import annotations

import logging
import time

import httpx

from ..config import env
from .base import Card, PublishResult

log = logging.getLogger(__name__)

# v26.0 is current as of 2026; override with GRAPH_VERSION if Meta moves on.
DEFAULT_GRAPH_VERSION = "v26.0"
CAPTION_LIMIT = 2200

# "You reached maximum number of posts" - the daily publishing cap.
RATE_LIMIT_CODES = {9, 2207042}
# How long to wait for Meta to finish fetching our image.
CONTAINER_TIMEOUT_S = 90
CONTAINER_POLL_S = 3


class InstagramError(RuntimeError):
    pass


class InstagramPublisher:
    name = "instagram"

    def __init__(self) -> None:
        self.user_id = env("IG_USER_ID", required=True)
        self.token = env("IG_ACCESS_TOKEN", required=True)
        self.base = f"https://graph.facebook.com/{env('GRAPH_VERSION', DEFAULT_GRAPH_VERSION)}"

    # --- http -------------------------------------------------------------

    def _request(self, method: str, path: str, **params) -> dict:
        params["access_token"] = self.token
        with httpx.Client(timeout=60.0) as client:
            response = client.request(method, f"{self.base}/{path}", params=params)
        payload = response.json()
        if "error" in payload:
            error = payload["error"]
            code = error.get("code")
            subcode = error.get("error_subcode")
            message = error.get("message", "unknown error")
            if code in RATE_LIMIT_CODES or subcode in RATE_LIMIT_CODES:
                raise InstagramError(f"daily publishing cap reached: {message}")
            raise InstagramError(f"graph api error {code}/{subcode}: {message}")
        response.raise_for_status()
        return payload

    # --- api --------------------------------------------------------------

    def quota(self) -> tuple[int, int]:
        """(used, total) posts in the current 24-hour window.

        Meta's own docs disagree on the cap (50 vs 100), so we read it live
        rather than hardcoding either number.
        """
        data = self._request(
            "GET",
            f"{self.user_id}/content_publishing_limit",
            fields="config,quota_usage",
        )
        entry = (data.get("data") or [{}])[0]
        used = entry.get("quota_usage", 0)
        total = (entry.get("config") or {}).get("quota_total", 0)
        return used, total

    def preflight(self) -> str:
        used, total = self.quota()
        if total and used >= total:
            raise InstagramError(f"daily publishing cap reached ({used}/{total})")
        return f"instagram ok - {used}/{total or '?'} posts used in the last 24h"

    def _wait_for_container(self, container_id: str) -> None:
        """Block until Meta has fetched the image, or give up with a clear reason."""
        deadline = time.monotonic() + CONTAINER_TIMEOUT_S
        last = "UNKNOWN"
        while time.monotonic() < deadline:
            data = self._request("GET", container_id, fields="status_code,status")
            last = data.get("status_code", "UNKNOWN")
            if last == "FINISHED":
                return
            if last in ("ERROR", "EXPIRED"):
                raise InstagramError(
                    f"container {last}: {data.get('status', 'no detail')} - "
                    f"Meta could not fetch the image URL"
                )
            time.sleep(CONTAINER_POLL_S)
        raise InstagramError(f"container still {last} after {CONTAINER_TIMEOUT_S}s")

    def publish(self, card: Card, caption: str) -> PublishResult:
        # Meta fetches the image itself, so only the URL matters here - the
        # local file in card.path is what LinkedIn uses.
        if not card.url:
            raise InstagramError(
                "no public card URL - set PUBLIC_BASE_URL; Meta fetches the JPEG itself"
            )
        if len(caption) > CAPTION_LIMIT:
            log.warning("caption truncated from %d to %d chars", len(caption), CAPTION_LIMIT)
            caption = caption[:CAPTION_LIMIT]

        log.info("creating container for %s", card.url)
        container = self._request(
            "POST", f"{self.user_id}/media", image_url=card.url, caption=caption
        )
        container_id = container["id"]

        self._wait_for_container(container_id)

        published = self._request(
            "POST", f"{self.user_id}/media_publish", creation_id=container_id
        )
        post_id = published["id"]
        log.info("published to instagram: %s", post_id)
        return PublishResult(platform=self.name, post_id=post_id)
