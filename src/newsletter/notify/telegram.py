"""The notification half of the approval gate.

The decision itself is a GitHub environment review, not a Telegram button.
Actions cannot receive a webhook, so the old design polled getUpdates from a
second scheduled job inside a fixed wall-clock window - and a window is
something a late cron can miss entirely. On 2026-10-29 GitHub delivered 2 of
the 15 scheduled checks and both ran hours after the window had closed, so the
press was never read. Worse, the offset bookkeeping that made polling work
advanced past presses it declined to match, which destroyed them outright.

So this module only ever sends. The card goes out with a link to the job that
is waiting for review, and GitHub holds that job - for up to 30 days - until
you act on it.
"""

from __future__ import annotations

import logging
from pathlib import Path

import httpx

from ..config import env

log = logging.getLogger(__name__)

# Telegram caps photo captions at 1024 characters, well under the 4096 for a
# plain message - so the card goes out with a short caption and the real one
# follows as text you can copy.
PHOTO_CAPTION_LIMIT = 1024
MESSAGE_LIMIT = 4096


class TelegramError(RuntimeError):
    pass


def _api(method: str) -> str:
    token = env("TELEGRAM_BOT_TOKEN", required=True)
    return f"https://api.telegram.org/bot{token}/{method}"


def _call(method: str, *, data=None, files=None, params=None) -> dict:
    with httpx.Client(timeout=60.0) as client:
        response = client.post(_api(method), data=data, files=files, params=params)
    payload = response.json()
    if not payload.get("ok"):
        raise TelegramError(f"{method} failed: {payload.get('description', response.text)}")
    return payload["result"]


def send_text(text: str) -> None:
    _call(
        "sendMessage",
        data={
            "chat_id": env("TELEGRAM_CHAT_ID", required=True),
            "text": text[:MESSAGE_LIMIT],
            "disable_web_page_preview": "true",
        },
    )


def send_draft(
    card_path: Path,
    post: dict,
    run_id: str,
    candidate_count: int,
    unsupported: list[str] | None = None,
    approval_url: str = "",
) -> None:
    """Send the card, then the caption, then where to approve it."""
    chat_id = env("TELEGRAM_CHAT_ID", required=True)

    summary = "\n".join(
        f"{i}. {story['headline']}  [{story['source_name']}]"
        for i, story in enumerate(post["stories"], 1)
    )
    brief = (
        f"Draft for {run_id}\n"
        f"{post['hook']} - {post['subhook']}\n\n"
        f"{summary}\n\n"
        f"from {candidate_count} candidates"
    )
    if unsupported:
        # Named explicitly so reviewing is a 5-second check, not a re-read.
        brief += "\n\nCHECK - not found in any source:\n" + ", ".join(unsupported)

    with card_path.open("rb") as handle:
        _call(
            "sendPhoto",
            data={"chat_id": chat_id, "caption": brief[:PHOTO_CAPTION_LIMIT]},
            files={"photo": (card_path.name, handle, "image/jpeg")},
        )

    # The real caption, as copyable text, with the links spelled out.
    links = "\n".join(f"- {s['source_name']}: {s['source_url']}" for s in post["stories"])
    hashtags = " ".join(f"#{tag.lstrip('#')}" for tag in post["hashtags"])
    send_text(f"CAPTION\n\n{post['caption']}\n\n{links}\n\n{hashtags}")

    # Sent last so it is the message waiting at the bottom of the chat. Nothing
    # in Telegram decides anything now: tapping through and approving the job on
    # GitHub is what publishes.
    if approval_url:
        send_text(f"APPROVE TO PUBLISH\n{approval_url}")

    log.info("draft sent to telegram")
