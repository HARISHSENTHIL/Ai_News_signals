"""Pins the OpenRouter request contract.

Three things here are load-bearing and fail silently or confusingly if broken:
  * provider.require_parameters - without it OpenRouter may route to an endpoint
    that ignores response_format and hands back prose instead of JSON.
  * strict schemas with no numeric bounds - strict mode rejects minimum/maximum.
  * the importance clamp - the schema can no longer enforce the 1-10 range.

No network: an httpx MockTransport stands in for the API.
"""

import json

import httpx
import pytest

from newsletter.curate import curate
from newsletter.models import Curation, Item


@pytest.fixture
def capture(monkeypatch):
    """Intercept the outbound request and reply with a canned completion."""
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-v1-test")
    import newsletter.llm as llm

    llm._client = None  # drop any client built by an earlier test
    seen = {}
    reply = {
        "clusters": [
            {
                "headline": "Anthropic ships Opus 5.5",
                "member_ids": [0, 1],
                "primary_url": "https://anthropic.com/news/a",
                "importance": 99,  # out of range on purpose
                "why_it_matters": "cheaper frontier model",
            },
            {
                "headline": "An invented story",
                "member_ids": [2],
                "primary_url": "https://not-a-candidate.example/made-up",
                "importance": 8,
                "why_it_matters": "should be dropped",
            },
        ]
    }

    def handler(request: httpx.Request) -> httpx.Response:
        seen["body"] = json.loads(request.content)
        seen["url"] = str(request.url)
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
    return seen


ITEMS = [
    Item(title="Anthropic ships Opus 5.5", url="https://anthropic.com/news/a",
         source="Anthropic", canonical="https://anthropic.com/news/a"),
    Item(title="Opus 5.5 is cheaper - TechCrunch", url="https://techcrunch.com/b",
         source="TechCrunch", canonical="https://techcrunch.com/b"),
    Item(title="Unrelated chip news", url="https://e.com/c",
         source="Reuters", canonical="https://e.com/c"),
]


def test_request_targets_openrouter_with_require_parameters(capture):
    curate(ITEMS, [])
    assert capture["url"] == "https://openrouter.ai/api/v1/chat/completions"
    assert capture["body"]["provider"] == {"require_parameters": True}
    assert capture["body"]["model"].startswith("anthropic/")
    assert capture["body"]["reasoning_effort"] in ("low", "medium", "high")


def test_schema_stays_inside_strict_mode(capture):
    curate(ITEMS, [])
    schema = capture["body"]["response_format"]["json_schema"]
    assert schema["strict"] is True
    cluster = schema["schema"]["$defs"]["Cluster"]
    assert cluster["additionalProperties"] is False
    # Every property must be required, and none may carry numeric bounds.
    assert set(cluster["required"]) == set(cluster["properties"])
    for prop in cluster["properties"].values():
        assert "minimum" not in prop and "maximum" not in prop


def test_out_of_range_importance_is_clamped(capture):
    ranked = curate(ITEMS, [])
    assert all(1 <= r.cluster.importance <= 10 for r in ranked)


def test_cluster_citing_a_url_we_never_supplied_is_dropped(capture):
    ranked = curate(ITEMS, [])
    urls = {r.cluster.primary_url for r in ranked}
    assert "https://not-a-candidate.example/made-up" not in urls
    assert len(ranked) == 1


def test_truncated_response_fails_loudly(monkeypatch):
    """finish_reason=length means silently missing stories - must raise."""
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-v1-test")
    import newsletter.llm as llm

    llm._client = None

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={
            "id": "x", "object": "chat.completion", "created": 0, "model": "m",
            "choices": [{"index": 0, "finish_reason": "length",
                         "message": {"role": "assistant", "content": "{"}}],
        })

    llm.client()._client = httpx.Client(transport=httpx.MockTransport(handler))
    with pytest.raises(RuntimeError, match="max_tokens"):
        llm.ask(system="s", prompt="p", schema=Curation, effort="medium")
