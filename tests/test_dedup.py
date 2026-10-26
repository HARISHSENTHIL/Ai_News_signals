"""Stage 1 and 2 of dedup. These are pure functions, so they are cheap to pin down."""

from newsletter.dedup import (
    canonical_url,
    dedupe_items,
    drop_seen,
    prune_seen,
    title_jaccard,
    title_tokens,
)
from newsletter.models import Item


class TestCanonicalUrl:
    def test_strips_tracking_params(self):
        assert canonical_url(
            "https://techcrunch.com/2026/10/23/openai-thing/?utm_source=x&utm_medium=social"
        ) == "https://techcrunch.com/2026/10/23/openai-thing"

    def test_keeps_meaningful_params(self):
        assert canonical_url("https://news.ycombinator.com/item?id=12345") == (
            "https://news.ycombinator.com/item?id=12345"
        )

    def test_normalises_host_scheme_and_trailing_slash(self):
        a = canonical_url("http://WWW.Example.com/path/")
        b = canonical_url("https://example.com/path")
        assert a == b == "https://example.com/path"

    def test_strips_amp_and_fragment(self):
        assert canonical_url("https://example.com/story/amp#section-2") == (
            "https://example.com/story"
        )

    def test_param_order_does_not_matter(self):
        assert canonical_url("https://e.com/x?b=2&a=1") == canonical_url("https://e.com/x?a=1&b=2")

    def test_keeps_non_default_port(self):
        assert canonical_url("https://example.com:8443/x") == "https://example.com:8443/x"

    def test_empty_and_garbage_do_not_raise(self):
        assert canonical_url("") == ""
        assert canonical_url("not a url") == "not a url"


class TestTitleSimilarity:
    def test_outlet_suffix_is_ignored(self):
        assert title_jaccard(
            "OpenAI launches GPT-6 for enterprise",
            "OpenAI launches GPT-6 for enterprise | TechCrunch",
        ) == 1.0

    def test_case_and_punctuation_ignored(self):
        assert title_jaccard(
            "Anthropic Releases Claude Opus 5.5",
            "anthropic releases claude opus 5.5!",
        ) == 1.0

    def test_unrelated_titles_score_low(self):
        assert title_jaccard(
            "Meta open-sources a new speech model",
            "EU regulators open an antitrust probe into chip supply",
        ) < 0.2

    def test_stopwords_do_not_create_false_matches(self):
        # Both are mostly filler; the content words must drive the score.
        assert title_jaccard("The new AI is here now", "The new chips are here now") < 0.72

    def test_empty_title_is_not_a_match(self):
        assert title_jaccard("", "anything at all") == 0.0

    def test_tokens_drop_short_words_and_stopwords(self):
        assert title_tokens("The AI of a new era") == frozenset({"era"})


class TestDedupeItems:
    def test_same_story_from_three_sources_collapses_to_the_primary(self):
        """The case the whole stage exists for: one event, three feeds."""
        items = [
            Item(
                title="Anthropic launches Claude Opus 5.5 | TechCrunch",
                url="https://techcrunch.com/2026/10/23/anthropic-opus/?utm_source=rss",
                source="TechCrunch",
                weight=1.0,
            ),
            Item(
                title="Anthropic launches Claude Opus 5.5",
                url="https://www.anthropic.com/news/claude-opus-5-5",
                source="Anthropic",
                weight=1.6,
            ),
            Item(
                title="Anthropic launches Claude Opus 5.5 - The Verge",
                url="https://www.theverge.com/2026/10/23/anthropic-opus-5-5",
                source="The Verge",
                weight=1.0,
            ),
        ]
        kept = dedupe_items(items)
        assert len(kept) == 1
        # The lab's own announcement outranks coverage of it.
        assert kept[0].source == "Anthropic"

    def test_identical_url_with_different_tracking_collapses(self):
        items = [
            Item(title="Story one", url="https://e.com/a?utm_source=reddit", source="r/x"),
            Item(title="Totally different wording here", url="https://e.com/a", source="HN"),
        ]
        assert len(dedupe_items(items)) == 1

    def test_distinct_stories_all_survive(self):
        items = [
            Item(title="Google ships a new TPU generation", url="https://e.com/1", source="A"),
            Item(title="Mistral raises a funding round", url="https://e.com/2", source="B"),
            Item(title="Researchers find a jailbreak in vision models", url="https://e.com/3", source="C"),
        ]
        assert len(dedupe_items(items)) == 3


class TestSeenStore:
    def test_drop_seen_filters_on_canonical(self):
        items = [
            Item(title="Old", url="https://e.com/old", source="A", canonical="https://e.com/old"),
            Item(title="New", url="https://e.com/new", source="A", canonical="https://e.com/new"),
        ]
        fresh = drop_seen(items, {"https://e.com/old": "2026-10-20"})
        assert [i.title for i in fresh] == ["New"]

    def test_prune_drops_old_and_unparseable_entries(self):
        seen = {
            "https://e.com/recent": "2026-10-22",
            "https://e.com/ancient": "2020-01-01",
            "https://e.com/broken": "not-a-date",
        }
        pruned = prune_seen(seen, window_days=30)
        assert "https://e.com/ancient" not in pruned
        assert "https://e.com/broken" not in pruned
