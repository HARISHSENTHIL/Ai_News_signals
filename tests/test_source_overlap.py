"""Pins down where cheap dedup stops and the model has to take over.

The titles below are real, captured from a live run on 2026-10-23: six outlets
reporting one Anthropic announcement. Stage 2 deliberately does NOT collapse
these - the wordings share too few tokens - which is the whole reason curate.py
makes a model call. If a future change makes stage 2 aggressive enough to merge
them, it is also aggressive enough to merge genuinely different stories, and
this test should fail loudly.
"""

import pytest

from newsletter.dedup import dedupe_items, title_jaccard
from newsletter.models import Item

# One real-world event, six outlets.
CLAUDE_DUET = [
    ("Anthropic Introduces Claude Duet: A New Agentic AI App for Professionals - CNET", "CNET"),
    ("Anthropic Joins the A.I. Agent Race With Claude Duet - The New York Times", "NYT"),
    ("Claude Duet app is Anthropic's bet on agents - TechCrunch", "TechCrunch"),
    ("Anthropic's Claude Duet joins the race for always-on agents - R&D World", "R&D World"),
    ("How Anthropic's Claude Duet Differs From Meta Muse in the AI Agent Race - Barron's", "Barron's"),
    ("Anthropic announces preview of Claude Duet, a personal AI agent", "The Verge"),
]


def test_same_event_different_wording_survives_stage_two():
    """These must reach the model, not be silently dropped by title matching."""
    items = [
        Item(title=title, url=f"https://example.com/{i}", source=source)
        for i, (title, source) in enumerate(CLAUDE_DUET)
    ]
    kept = dedupe_items(items)
    # Nothing is lost: every distinct wording goes through to clustering.
    assert len(kept) == len(CLAUDE_DUET)


@pytest.mark.parametrize("left,right", [(a[0], b[0]) for a in CLAUDE_DUET for b in CLAUDE_DUET if a < b])
def test_cross_outlet_wordings_stay_below_the_threshold(left, right):
    """Documents the gap stage 3 fills: real same-event pairs score well under 0.72."""
    assert title_jaccard(left, right) < 0.72


def test_syndicated_identical_wording_is_still_collapsed():
    """Stage 2 must still earn its place on true syndication."""
    headline = "Anthropic announces preview of Claude Duet, a personal AI agent"
    items = [
        Item(title=headline, url="https://a.com/1", source="A"),
        Item(title=f"{headline} | TechCrunch", url="https://b.com/2", source="B"),
        Item(title=f"{headline} - Reuters", url="https://c.com/3", source="C"),
    ]
    assert len(dedupe_items(items)) == 1
