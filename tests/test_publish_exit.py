"""The publish command's exit code.

There is exactly one legitimate no-op left - there being no draft for the day -
and it has to stay a success, because the catch-up run hits it. Everything else
that reaches publish has already been approved by a human, so a run that posts
nothing must exit non-zero: on 2026-10-28 a publish where every destination
failed still went green, which is indistinguishable from a quiet run and is how
a real failure stayed invisible for a day.
"""

import json
from datetime import date

import pytest

from newsletter import pipeline

RUN_DATE = date(2026, 10, 28)
RUN_ID = RUN_DATE.isoformat()

DRAFT = {
    "date": RUN_ID,
    "post": {
        "hook": "Agents everywhere",
        "subhook": "A quiet day otherwise",
        "caption": "OpenAI shipped the Decisions API.",
        "hashtags": ["ai"],
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
    },
    "card_path": "out/2026-10-28/card.jpg",
}


class _Telegram:
    """Stands in for the module; records what the operator would have been told."""

    def __init__(self):
        self.texts: list[str] = []

    def send_text(self, text):
        self.texts.append(text)


class _Publisher:
    name = "linkedin"

    def __init__(self, exc=None):
        self._exc = exc

    def preflight(self):
        return "linkedin ok"

    def publish(self, card, caption):
        if self._exc:
            raise self._exc
        from newsletter.publish.base import PublishResult

        return PublishResult(platform="linkedin", post_id="urn:li:share:1", url="")


@pytest.fixture
def wired(tmp_path, monkeypatch):
    """Point the pipeline at a throwaway draft and stub everything external."""
    out = tmp_path / RUN_ID
    out.mkdir(parents=True)
    (out / "draft.json").write_text(json.dumps(DRAFT))
    monkeypatch.setattr(pipeline, "run_dir", lambda d, dry_run=False: out)
    monkeypatch.setattr(pipeline, "append_history", lambda entry: None)
    monkeypatch.setattr(pipeline, "_card", lambda record: object())
    return monkeypatch


def _run_cli() -> int:
    return pipeline.main(["publish", "--date", RUN_ID])


def test_total_failure_exits_non_zero(wired):
    """The regression: every destination failed and the job still went green."""
    telegram = _Telegram()
    wired.setattr(pipeline, "telegram", telegram)
    wired.setattr(pipeline, "_publishers", lambda: [_Publisher(RuntimeError("401 expired"))])

    assert _run_cli() == 1
    # The operator is told why, not just that something went wrong.
    assert any("401 expired" in t for t in telegram.texts)


def test_total_failure_raises_a_distinct_error(wired):
    wired.setattr(pipeline, "telegram", _Telegram())
    wired.setattr(pipeline, "_publishers", lambda: [_Publisher(RuntimeError("boom"))])

    with pytest.raises(pipeline.PublishFailed):
        pipeline.publish_now(RUN_DATE)


def test_a_successful_publish_exits_zero(wired):
    wired.setattr(pipeline, "telegram", _Telegram())
    wired.setattr(pipeline, "_publishers", lambda: [_Publisher()])

    assert _run_cli() == 0


def test_no_draft_is_a_success(tmp_path, monkeypatch):
    """The catch-up run lands here on a day the draft never happened."""
    monkeypatch.setattr(pipeline, "run_dir", lambda d, dry_run=False: tmp_path / "empty")
    monkeypatch.setattr(pipeline, "telegram", _Telegram())
    monkeypatch.setattr(pipeline, "_publishers", lambda: [_Publisher()])

    assert _run_cli() == 0


def test_publishing_never_consults_telegram_for_a_decision(wired):
    """The gate is GitHub's. Anything that polls here is a reintroduced bug.

    The old code read the decision from Telegram, and advanced a stored offset
    past presses it declined to match - destroying them. Telegram is send-only
    now, so a `poll_decision` attribute reappearing on the stub would raise.
    """
    telegram = _Telegram()
    wired.setattr(pipeline, "telegram", telegram)
    wired.setattr(pipeline, "_publishers", lambda: [_Publisher()])

    assert _run_cli() == 0
    assert not hasattr(telegram, "poll_decision")
