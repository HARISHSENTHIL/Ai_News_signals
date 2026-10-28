"""Pins the source-tier contract and the corroboration signal.

The tiers exist because prompt rules alone did not stop the model inventing a
competitor (see verify.py). Two things make them real rather than decorative,
and both are easy to break without noticing:
  * a SIGNAL source can never be cited as a story's source, and
  * a SIGNAL source can never supply vocabulary a claim is grounded in.

Corroboration is the ranking half: how many independent feeds carried the same
event. No network - an httpx MockTransport stands in for the API.
"""

import json

import httpx
import pytest

from newsletter.config import PRIMARY, REPORTED, SIGNAL
from newsletter.curate import _priority, curate
from newsletter.models import Item, Post, StoryBlock
from newsletter.verify import unsupported_terms


def _mock(monkeypatch, reply: dict):
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-v1-test")
    import newsletter.llm as llm

    llm._client = None

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "id": "x", "object": "chat.completion", "created": 0,
                "model": "anthropic/claude-opus-5.5",
                "choices": [{
                    "index": 0, "finish_reason": "stop",
                    "message": {"role": "assistant", "content": json.dumps(reply)},
                }],
                "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
            },
        )

    llm.client()._client = httpx.Client(transport=httpx.MockTransport(handler))


def _item(title, url, source, tier, **kw):
    return Item(title=title, url=url, source=source, canonical=url, tier=tier, **kw)


# One real event carried by a lab, two outlets and two forums, plus a story that
# only a forum has - the shape that decides every assertion below.
ITEMS = [
    _item("Anthropic ships Opus 5.5", "https://anthropic.com/a", "Anthropic", PRIMARY),
    _item("Opus 5.5 is cheaper", "https://techcrunch.com/b", "TechCrunch", REPORTED),
    _item("Anthropic cuts frontier pricing", "https://theverge.com/c", "The Verge", REPORTED),
    _item("Opus 5.5 benchmarks thread", "https://reddit.com/d", "r/LocalLLaMA", SIGNAL),
    _item("Opus 5.5 discussion", "https://news.ycombinator.com/e", "Hacker News", SIGNAL),
    _item("Rumour about Zylox chips", "https://reddit.com/f", "r/LocalLLaMA", SIGNAL),
]


def test_signal_source_cannot_be_cited_and_is_repointed(monkeypatch):
    """A forum member may rank a story; the citation must move to a real source."""
    _mock(monkeypatch, {"clusters": [{
        "headline": "Opus 5.5 lands",
        "member_ids": [0, 1, 2, 3, 4],
        "primary_url": "https://reddit.com/d",  # the model picked the forum
        "importance": 8,
        "why_it_matters": "cheaper frontier model",
    }]})
    ranked = curate(ITEMS, [])
    assert len(ranked) == 1
    assert ranked[0].cluster.primary_url == "https://anthropic.com/a"


def test_cluster_only_a_forum_carries_is_dropped(monkeypatch):
    """Nothing quotable means nothing we can stand behind, so it goes."""
    _mock(monkeypatch, {"clusters": [{
        "headline": "Zylox chips rumour",
        "member_ids": [5],
        "primary_url": "https://reddit.com/f",
        "importance": 7,
        "why_it_matters": "would reshape supply",
    }]})
    assert curate(ITEMS, []) == []


def test_corroboration_counts_distinct_feeds(monkeypatch):
    _mock(monkeypatch, {"clusters": [{
        "headline": "Opus 5.5 lands",
        "member_ids": [0, 1, 2, 3, 4],
        "primary_url": "https://anthropic.com/a",
        "importance": 6,
        "why_it_matters": "cheaper frontier model",
    }]})
    ranked = curate(ITEMS, [])
    assert ranked[0].corroboration == 5
    assert ranked[0].sources[0] == "Anthropic"
    # 6 importance + min(5, cap) * 0.4
    assert ranked[0].score == pytest.approx(8.0)


def test_corroboration_can_lift_a_widely_carried_story(monkeypatch):
    """A 6 carried by five feeds outranks a 7 that only one feed has."""
    _mock(monkeypatch, {"clusters": [
        {"headline": "Lone story", "member_ids": [1], "importance": 7,
         "primary_url": "https://techcrunch.com/b", "why_it_matters": "x"},
        {"headline": "Everywhere story", "member_ids": [0, 1, 2, 3, 4], "importance": 6,
         "primary_url": "https://anthropic.com/a", "why_it_matters": "y"},
    ]})
    ranked = curate(ITEMS, [])
    assert [r.cluster.headline for r in ranked] == ["Everywhere story", "Lone story"]


def test_corroboration_bonus_cannot_overrule_importance(monkeypatch):
    """The bonus is capped, so a genuinely bigger story still wins."""
    _mock(monkeypatch, {"clusters": [
        {"headline": "Big story", "member_ids": [0], "importance": 10,
         "primary_url": "https://anthropic.com/a", "why_it_matters": "x"},
        {"headline": "Well covered", "member_ids": [0, 1, 2, 3, 4], "importance": 7,
         "primary_url": "https://anthropic.com/a", "why_it_matters": "y"},
    ]})
    ranked = curate(ITEMS, [])
    assert ranked[0].cluster.headline == "Big story"


def test_signal_items_cannot_ground_a_claim():
    """The enforcement half: a name only a forum used must be flagged.

    "Zylox" appears in a SIGNAL item and nowhere else, so it must read as
    unsupported exactly as an invented name would.
    """
    post = Post(
        hook="Zylox enters the race",
        subhook="Anthropic ships Opus 5.5",
        stories=[StoryBlock(headline="Opus 5.5 lands", detail="Anthropic cut pricing.",
                            source_name="Anthropic", source_url="https://anthropic.com/a",
                            category="MODEL", tier="lead")],
        caption="Anthropic shipped Opus 5.5. Zylox is said to be next.",
        hashtags=["ai"],
        image_query="server racks",
    )
    flagged = unsupported_terms(post, ITEMS)
    assert "Zylox" in flagged
    assert "Anthropic" not in flagged


def test_priority_cut_keeps_the_strongest_candidates():
    """MAX_CANDIDATES now bites, so the cut must be by weight, not fetch order."""
    weak = [_item(f"filler {n}", f"https://x.com/{n}", "Lemmy", SIGNAL, weight=0.6)
            for n in range(5)]
    strong = _item("OpenAI ships", "https://openai.com/x", "OpenAI", PRIMARY, weight=1.6)
    ordered = sorted(weak + [strong], key=_priority, reverse=True)
    assert ordered[0] is strong
