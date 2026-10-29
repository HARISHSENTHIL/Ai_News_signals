"""What goes out to Telegram, and what no longer does.

The card used to carry an inline keyboard, and a press on it was the decision.
That cost two days of posts: a press is only visible to a job that happens to
run after it, and the cursor used to read them advanced past presses it
declined to match, deleting them permanently. The decision now lives in a
GitHub environment review, so these tests pin the two properties that keeps:
the card ships no buttons, and the message says where to go instead.
"""

import pytest

from newsletter.notify import telegram

POST = {
    "hook": "Agents everywhere",
    "subhook": "A quiet day otherwise",
    "caption": "OpenAI shipped the Decisions API.",
    "hashtags": ["ai", "llm"],
    "stories": [
        {
            "headline": "OpenAI makes its Decisions API broadly available",
            "detail": "Generally available today.",
            "source_name": "OpenAI",
            "source_url": "https://openai.com/index/decisions-api",
            "category": "MODEL",
            "tier": "lead",
        }
    ],
}

RUN_ID = "2026-10-29"
APPROVAL = "https://github.com/HARISHSENTHIL/Ai_News_signals/actions/runs/12345"


@pytest.fixture
def sent(tmp_path, monkeypatch):
    """Capture every Telegram call instead of making it."""
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "test-token")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "4242")
    calls: list[tuple[str, dict]] = []

    def _call(method, *, data=None, files=None, params=None):
        calls.append((method, data or {}))
        return {}

    monkeypatch.setattr(telegram, "_call", _call)

    card = tmp_path / "card.jpg"
    card.write_bytes(b"not-really-a-jpeg")
    return calls, card


def test_the_card_carries_no_buttons(sent):
    """A button would mean a decision Telegram cannot reliably deliver."""
    calls, card = sent
    telegram.send_draft(card, POST, RUN_ID, 158, None, approval_url=APPROVAL)

    photo = next(data for method, data in calls if method == "sendPhoto")
    assert "reply_markup" not in photo
    assert not any("callback_data" in str(data) for _, data in calls)


def test_the_approval_link_is_sent_last(sent):
    """It should be the message sitting at the bottom of the chat."""
    calls, card = sent
    telegram.send_draft(card, POST, RUN_ID, 158, None, approval_url=APPROVAL)

    assert calls[0][0] == "sendPhoto"
    assert APPROVAL in calls[-1][1]["text"]
    assert calls[-1][1]["text"].startswith("APPROVE TO PUBLISH")


def test_a_local_run_omits_the_link(sent):
    """Off CI there is no run to approve, so the line is left out entirely."""
    calls, card = sent
    telegram.send_draft(card, POST, RUN_ID, 158, None)

    assert not any("APPROVE" in data.get("text", "") for _, data in calls)
    # The card and the caption still go out.
    assert [method for method, _ in calls] == ["sendPhoto", "sendMessage"]


def test_unsupported_terms_are_called_out_on_the_card(sent):
    """The hallucination check annotates the brief; it never blocks."""
    calls, card = sent
    telegram.send_draft(card, POST, RUN_ID, 158, ["ABC"], approval_url=APPROVAL)

    caption = next(data for method, data in calls if method == "sendPhoto")["caption"]
    assert "CHECK - not found in any source" in caption
    assert "ABC" in caption


def test_polling_helpers_are_gone(sent):
    """Guards the deletion: anything reading decisions back is the old bug."""
    for name in ("poll_decision", "acknowledge", "_load_offset", "_save_offset", "OFFSET_PATH"):
        assert not hasattr(telegram, name), f"{name} is back"
