"""The approval gate.

GitHub Actions cannot receive a webhook, so the decision is picked up by a second
scheduled workflow that reads getUpdates from a stored offset. Telegram keeps
updates for 24 hours, which is far longer than the approval window needs.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from pathlib import Path

import httpx

from ..config import STATE_DIR, env

log = logging.getLogger(__name__)

OFFSET_PATH = STATE_DIR / "tg_offset"
# Telegram caps photo captions at 1024 characters, well under the 4096 for a
# plain message - so the card goes out with a short caption and the real one
# follows as text you can copy.
PHOTO_CAPTION_LIMIT = 1024
MESSAGE_LIMIT = 4096


class TelegramError(RuntimeError):
    pass


@dataclass
class Decision:
    action: str  # "post" | "regen" | "skip"
    run_id: str
    callback_id: str
    update_id: int


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
) -> None:
    """Send the rendered card with approve/regenerate/skip buttons, then the caption."""
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

    keyboard = {
        "inline_keyboard": [[
            {"text": "Post it", "callback_data": f"post:{run_id}"},
            {"text": "Regenerate", "callback_data": f"regen:{run_id}"},
            {"text": "Skip today", "callback_data": f"skip:{run_id}"},
        ]]
    }

    with card_path.open("rb") as handle:
        _call(
            "sendPhoto",
            data={
                "chat_id": chat_id,
                "caption": brief[:PHOTO_CAPTION_LIMIT],
                "reply_markup": json.dumps(keyboard),
            },
            files={"photo": (card_path.name, handle, "image/jpeg")},
        )

    # The real caption, as copyable text, with the links spelled out.
    links = "\n".join(f"- {s['source_name']}: {s['source_url']}" for s in post["stories"])
    hashtags = " ".join(f"#{tag.lstrip('#')}" for tag in post["hashtags"])
    send_text(f"CAPTION\n\n{post['caption']}\n\n{links}\n\n{hashtags}")
    log.info("draft sent to telegram")


# --- reading the decision back --------------------------------------------


def _load_offset() -> int:
    try:
        return int(OFFSET_PATH.read_text().strip())
    except (OSError, ValueError):
        return 0


def _save_offset(update_id: int) -> None:
    OFFSET_PATH.parent.mkdir(parents=True, exist_ok=True)
    # Telegram's offset is "the next update I want", hence +1.
    OFFSET_PATH.write_text(str(update_id + 1))


def poll_decision(run_id: str) -> Decision | None:
    """Return the newest decision for `run_id`, or None if nobody has pressed yet.

    Always advances the stored offset past everything it read, so a stale button
    press from an earlier day cannot be replayed tomorrow.
    """
    updates = _call(
        "getUpdates",
        params={
            "offset": _load_offset(),
            "timeout": 0,
            "allowed_updates": json.dumps(["callback_query"]),
        },
    )
    if not updates:
        return None

    newest: Decision | None = None
    for update in updates:
        query = update.get("callback_query")
        if not query:
            continue
        action, _, seen_run = query.get("data", "").partition(":")
        if seen_run != run_id or action not in ("post", "regen", "skip"):
            continue
        # Later updates win, so a change of mind is honoured.
        newest = Decision(
            action=action,
            run_id=seen_run,
            callback_id=query["id"],
            update_id=update["update_id"],
        )

    _save_offset(max(u["update_id"] for u in updates))
    if newest:
        log.info("decision for %s: %s", run_id, newest.action)
    return newest


def acknowledge(decision: Decision, text: str) -> None:
    """Dismiss the button's spinner and confirm what happened."""
    try:
        _call(
            "answerCallbackQuery",
            data={"callback_query_id": decision.callback_id, "text": text[:200]},
        )
    except TelegramError as exc:
        # The callback id expires after a while; the publish already happened.
        log.warning("could not answer callback: %s", exc)
