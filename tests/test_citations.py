"""Where a reader is actually sent.

Google News is the only route we have to several labs' own writing - Anthropic
and Meta AI publish no working public RSS - but its links are opaque
/rss/articles/CBMi... redirects. Measured over 100 live entries on 2026-10-24:
median 254 characters, up to 660. Four of them eat roughly 950 characters of
LinkedIn's 3,000-character commentary, and a bad day's four would take most of
it - so they are never cited directly.

Measured on 2026-10-24: following the redirect returns Google's own JS page, not
the article, and the batchexecute decode that used to recover the real URL no
longer finds a signature. What does work is the feed's <source> element, which
names the publisher and its domain. So the rule is: cite a sibling feed's deep
link when one exists, and the publisher's domain when none does.
"""

import json

import httpx
import pytest

from newsletter.config import PRIMARY, REPORTED
from newsletter.curate import curate
from newsletter.models import Item

GNEWS_URL = (
    "https://news.google.com/rss/articles/CBMib0FVX3lxTE9hcjNRbVFacnhzLWNNYnRkSTlV"
    "M2FkMnotYTd0MEpwTmlsQ2N1NlVPdjJjdXJhNG9FbC14d3FIR3pVaEh0SEdIamRWWmNTaz"
)


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


def _gnews(title, source, domain):
    """A Google News item: real-looking redirect url, publisher domain to cite."""
    return Item(
        title=title, url=GNEWS_URL, source=source, canonical=GNEWS_URL,
        tier=REPORTED, cite_url=domain,
    )


def _direct(title, url, source, tier=REPORTED):
    return Item(title=title, url=url, source=source, canonical=url, tier=tier)


def _cluster(headline, primary_url, member_ids):
    return {
        "clusters": [{
            "headline": headline,
            "why_it_matters": "It changes what is available today.",
            "primary_url": primary_url,
            "member_ids": member_ids,
            "importance": 8,
        }]
    }


def test_google_news_only_story_is_cited_by_publisher_domain(monkeypatch):
    """Anthropic's own blog reaches us only this way - it must not be dropped."""
    items = [_gnews("An alignment assessment", "Anthropic", "https://www.anthropic.com")]
    _mock(monkeypatch, _cluster("Anthropic publishes an alignment assessment", GNEWS_URL, [0]))

    ranked = curate(items, [])

    assert len(ranked) == 1, "a Google-News-only story must survive, not be dropped"
    assert ranked[0].cluster.primary_url == "https://www.anthropic.com"
    assert "news.google.com" not in ranked[0].cluster.primary_url


def test_a_sibling_deep_link_is_preferred_over_the_domain(monkeypatch):
    """When any feed carried the story directly, readers get the article."""
    items = [
        _gnews("Anthropic debuts Claude Duet", "CBS News", "https://www.cbsnews.com"),
        _direct("Anthropic previews Claude Duet", "https://techcrunch.com/duet", "TechCrunch"),
    ]
    # The model picks the Google News item; we should still cite TechCrunch.
    _mock(monkeypatch, _cluster("Anthropic previews Claude Duet", GNEWS_URL, [0, 1]))

    ranked = curate(items, [])

    assert ranked[0].cluster.primary_url == "https://techcrunch.com/duet"


def test_an_ordinary_url_is_left_alone(monkeypatch):
    items = [_direct("Anthropic ships Opus 5.5", "https://anthropic.com/news/opus", "Anthropic", PRIMARY)]
    _mock(monkeypatch, _cluster("Anthropic ships Opus 5.5", "https://anthropic.com/news/opus", [0]))

    ranked = curate(items, [])

    assert ranked[0].cluster.primary_url == "https://anthropic.com/news/opus"


def test_a_domain_citation_is_far_shorter_than_the_redirect():
    """The concrete reason this exists, pinned so nobody 'simplifies' it away.

    Not an escaping problem - these base64 URLs contain no reserved characters,
    so escaping does not inflate them. It is a length and legibility problem.
    """
    from newsletter.config import LINKEDIN_COMMENTARY_LIMIT

    worst_case = 660  # the longest of 100 live entries, measured 2026-10-24
    assert worst_case * 4 > LINKEDIN_COMMENTARY_LIMIT * 0.8, (
        "four worst-case redirects crowd out the post itself"
    )
    assert len("https://www.anthropic.com") * 4 < LINKEDIN_COMMENTARY_LIMIT * 0.05


def test_item_citation_and_deep_link_properties():
    plain = _direct("x", "https://example.com/a", "Example")
    assert plain.deep_link is True
    assert plain.citation == "https://example.com/a"

    redirected = _gnews("x", "Example", "https://example.com")
    assert redirected.deep_link is False
    assert redirected.citation == "https://example.com"
