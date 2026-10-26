"""Flags claims in the generated post that are not supported by the sources.

A live run on 2026-10-23 produced "competition with Jev in decision models heats
up". "Jev" appears nowhere in any feed - the model invented a competitor. The
system prompt already forbade this, so prompt instructions alone are not enough.

This does not block publishing. It finds proper nouns, numbers and model names in
the output that never appeared in the input, and surfaces them in the Telegram
message so the human gate has something specific to check rather than being asked
to re-read four stories cold.

Deliberately biased toward false positives: a flagged word you recognise costs
you a second, an invented company that ships costs you the account's credibility.
"""

from __future__ import annotations

import logging
import re

from .models import Item, Post

log = logging.getLogger(__name__)

# Capitalised words, acronyms and version-ish tokens: the things a model invents.
ENTITY_RE = re.compile(r"\b[A-Z][a-zA-Z0-9.\-]{1,}\b|\b\d+(?:\.\d+)?[BMK]\b|\$\d[\d,.]*")

# Words that start sentences or are generic enough to be noise, not entities.
IGNORE = {
    "The", "This", "That", "These", "Those", "It", "Its", "They", "Their", "A", "An",
    "And", "But", "Or", "For", "With", "From", "In", "On", "At", "By", "To", "As",
    "After", "Before", "While", "When", "Where", "What", "Who", "How", "Why",
    "New", "Now", "Today", "Plus", "Also", "Both", "Not", "No", "Yes", "If", "Then",
    "AI", "API", "APIs", "LLM", "LLMs", "ML", "I", "We", "You", "Agents", "Agent",
    "Source", "Sources", "Open", "Model", "Models", "Data", "Users", "User",
}


# A capital after sentence-ending punctuation is just grammar, not an entity.
SENTENCE_START_RE = re.compile(r"(?:^|[.!?:;]\s+|\n\s*|\d\.\s+)$")

# Ordinary words that legitimately open a sentence in this kind of copy. Only
# these are forgiven their capital: skipping every sentence-initial word instead
# left a hole wide enough to drive an invented company through, because a name
# placed first in a sentence was never examined at all.
COMMON_WORDS = frozenset("""
built shipped launched released announced added updated expanded introduced
published opened closed raised cut doubled tripled halved replaced renamed
started stopped began ended continued remained became stayed arrived landed
developers users researchers customers companies startups labs teams vendors
models agents tools apps chips servers papers weights benchmarks prices
everyone anyone someone nobody nothing something everything
meanwhile elsewhere separately together instead still already finally
overall overnight yesterday today tomorrow earlier later soon
expect expects look looks read reads see sees think thinks want wants
most many much more less fewer several both either neither each every
one two three four five six seven eight nine ten
there here where when while after before since until because though although
given despite beyond across between among under over about against
""".split())


def _entities(text: str) -> list[tuple[str, bool]]:
    """Every entity-ish token, paired with whether it opened a sentence."""
    found = []
    for match in ENTITY_RE.finditer(text):
        found.append(
            (
                match.group().strip(".-"),
                bool(SENTENCE_START_RE.search(text[: match.start()])),
            )
        )
    return found


def _corpus(items: list[Item]) -> str:
    """Everything a claim is allowed to be grounded in.

    Signal-tier items are excluded deliberately. A subreddit or forum title is
    user-written and has had no editorial check, so a name appearing only there is
    precisely what we want flagged rather than quietly accepted as vocabulary.
    Excluding them here is what makes the source tiers an enforced constraint
    instead of a label: a signal source can lift a story's rank, but it cannot
    put a word in the caption.
    """
    return " ".join(f"{i.title} {i.summary} {i.source}" for i in items if i.quotable)


def unsupported_terms(post: Post, items: list[Item]) -> list[str]:
    """Entities in the post that never appear in the source material."""
    corpus = _corpus(items)
    corpus_lower = corpus.lower()
    known = {token.lower() for token, _ in _entities(corpus)}

    # Joined with ". " so each fragment's first word counts as sentence-initial;
    # these are independent pieces of prose, not one running sentence.
    generated = ". ".join(
        [post.hook, post.subhook, post.caption]
        + [part for s in post.stories for part in (s.headline, s.detail)]
    )

    suspect: set[str] = set()
    for token, sentence_initial in _entities(generated):
        if token in IGNORE or len(token) < 3:
            continue
        lowered = token.lower()
        # Present as a token, or as a substring (catches "OpenAI's" vs "OpenAI").
        if lowered in known or lowered in corpus_lower:
            continue
        # Opening a sentence excuses a capital only for a real word. Anything
        # else stays flagged, which is the right bias: a false positive costs a
        # glance, a false negative ships an invented name.
        if sentence_initial and lowered in COMMON_WORDS:
            continue
        suspect.add(token)

    flagged = sorted(suspect)
    if flagged:
        log.warning("unsupported terms in generated post: %s", ", ".join(flagged))
    return flagged
