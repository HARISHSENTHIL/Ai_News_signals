"""The lead/brief split, which decides how much of the card each story gets.

The model is asked for 3-5 leads and at most 4 briefs, but a JSON schema cannot
express that, so write._shelve repairs whatever comes back. These tests pin the
repair rather than the model.
"""

from newsletter.models import CATEGORIES, StoryBlock
from newsletter.write import _shelve


def _story(headline: str, tier: str, category: str = "MODEL") -> StoryBlock:
    return StoryBlock(
        headline=headline,
        detail="Something happened.",
        source_name="TechCrunch",
        source_url=f"https://e.com/{headline.lower()}",
        category=category,
        tier=tier,
    )


def _tiers(stories: list[StoryBlock]) -> list[str]:
    return [s.tier for s in stories]


class TestShelve:
    def test_a_valid_split_is_left_alone(self):
        stories = [_story(f"S{i}", "lead") for i in range(4)]
        stories += [_story(f"B{i}", "brief") for i in range(2)]
        assert _tiers(_shelve(stories)) == ["lead"] * 4 + ["brief"] * 2

    def test_too_few_leads_promotes_the_strongest_briefs(self):
        """A model that marks almost everything 'brief' still owes us a card."""
        stories = [_story("Lead", "lead")] + [_story(f"B{i}", "brief") for i in range(4)]
        shelved = _shelve(stories)
        assert _tiers(shelved) == ["lead"] * 3 + ["brief"] * 2
        # Promotion takes from the front, so the highest-ranked briefs are the
        # ones that move up.
        assert [s.headline for s in shelved[:3]] == ["Lead", "B0", "B1"]

    def test_too_many_leads_demotes_the_weakest(self):
        stories = [_story(f"S{i}", "lead") for i in range(8)]
        shelved = _shelve(stories)
        assert _tiers(shelved) == ["lead"] * 5 + ["brief"] * 3
        # The last lead is the lowest ranked, so it is the one that gives way.
        assert [s.headline for s in shelved[5:]] == ["S5", "S6", "S7"]

    def test_briefs_past_the_cards_room_are_dropped(self):
        stories = [_story(f"S{i}", "lead") for i in range(3)]
        stories += [_story(f"B{i}", "brief") for i in range(9)]
        shelved = _shelve(stories)
        assert _tiers(shelved) == ["lead"] * 3 + ["brief"] * 4
        assert len(shelved) == 7

    def test_all_briefs_still_produces_a_card(self):
        """The degenerate case: a thin day where nothing looked like a lead."""
        shelved = _shelve([_story(f"B{i}", "brief") for i in range(5)])
        assert _tiers(shelved) == ["lead"] * 3 + ["brief"] * 2

    def test_fewer_stories_than_the_lead_minimum_is_not_padded(self):
        """Two real stories beat three, one of which is invented to fill a slot."""
        shelved = _shelve([_story("A", "brief"), _story("B", "brief")])
        assert _tiers(shelved) == ["lead", "lead"]

    def test_order_within_a_shelf_is_preserved(self):
        stories = [_story("A", "lead"), _story("B", "brief"), _story("C", "lead")]
        shelved = _shelve(stories)
        # Leads keep their relative order even though C came after a brief.
        assert [s.headline for s in shelved] == ["A", "C", "B"]


class TestCategories:
    def test_no_label_is_wider_than_the_column_allows(self):
        """The card's category column is a fixed width tuned to the longest label.

        RESEARCH and SECURITY are both 8 characters, which is what .cat in
        template.html.j2 is sized for. A longer member has to grow that width
        with it or the headlines stop aligning.
        """
        assert max(len(c) for c in CATEGORIES) == 8

    def test_news_is_available_as_a_fallback(self):
        assert "NEWS" in CATEGORIES
