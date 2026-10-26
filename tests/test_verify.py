"""The grounding check.

Regression test for a real failure: on 2026-10-23 the model wrote "competition
with Jev in decision models heats up" when no feed anywhere mentioned "Jev".
The system prompt already forbade inventing names, so the prompt alone is not a
sufficient control - this check is what makes the human approval gate actionable.
"""

from newsletter.models import Item, Post, StoryBlock
from newsletter.verify import unsupported_terms

ITEMS = [
    Item(
        title="OpenAI launches Decisions API broadly",
        url="https://openai.com/index/decisions-api",
        source="OpenAI",
        summary="The Decisions API is now generally available to all developers.",
    ),
    Item(
        title="Anthropic previews Claude Duet",
        url="https://anthropic.com/news/duet",
        source="Anthropic",
        summary="An always-on agent app for professionals.",
    ),
]


def _post(detail: str) -> Post:
    return Post(
        hook="Agents everywhere",
        subhook="A quiet day otherwise",
        stories=[
            StoryBlock(
                headline="OpenAI makes its Decisions API broadly available",
                detail=detail,
                source_name="OpenAI",
                source_url="https://openai.com/index/decisions-api",
            )
        ],
        caption="OpenAI shipped the Decisions API today.",
        hashtags=["ai"],
        image_query="abstract",
    )


def test_invented_competitor_is_flagged():
    """The exact 2026-10-23 regression."""
    flagged = unsupported_terms(
        _post("Developers get low-cost calls as competition with Jev heats up."), ITEMS
    )
    assert "Jev" in flagged


def test_grounded_post_is_clean():
    flagged = unsupported_terms(
        _post("The Decisions API is now generally available to all developers."), ITEMS
    )
    assert flagged == []


def test_sentence_initial_capitals_are_not_entities():
    """'Built for professionals...' must not be reported as an invented name."""
    flagged = unsupported_terms(
        _post("Built to be generally available. Shipped to all developers."), ITEMS
    )
    assert "Built" not in flagged and "Shipped" not in flagged


def test_invented_numbers_are_flagged():
    flagged = unsupported_terms(
        _post("The Decisions API now serves 40B requests for $5 a month."), ITEMS
    )
    assert any(t in flagged for t in ("40B", "$5"))


def test_invented_name_opening_a_sentence_is_flagged():
    """Skipping every sentence-initial capital hid invented names entirely.

    The 2026-10-23 "Jev" case happened mid-sentence and was caught. The same
    name placed first in a sentence was not examined at all, so only ordinary
    words are forgiven their capital now.
    """
    flagged = unsupported_terms(
        _post("Zylox is said to be next. Shipped to all developers."), ITEMS
    )
    assert "Zylox" in flagged
    assert "Shipped" not in flagged
