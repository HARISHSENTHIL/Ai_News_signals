"""Data shapes shared across the pipeline.

Item is our internal representation of one thing pulled off a feed.
The pydantic models below are the schemas the two Claude calls are held to.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

from pydantic import BaseModel, Field

from .config import CORROBORATION_CAP, CORROBORATION_WEIGHT, REPORTED, SIGNAL


@dataclass
class Item:
    """One candidate story as it came off a source."""

    title: str
    url: str
    source: str
    weight: float = 1.0
    # The feed's own summary. Passed to the model verbatim; never invented.
    summary: str = ""
    published: str = ""
    # Set by dedup.canonical_url; the key used for the seen-store and clustering.
    canonical: str = ""
    # HN only: upvotes, used as a newsworthiness signal.
    points: int | None = None
    # What this item is allowed to justify - see the tier notes in config.
    tier: str = REPORTED
    # Where to send a reader, when `url` is not somewhere you can send one.
    # Google News hands out opaque /rss/articles/CBMi... redirects. They do work
    # in a browser, but they are unreadable and long: measured over 100 entries
    # on 2026-10-24, median 254 characters and up to 660, so four of them take
    # about 950 characters of LinkedIn's 3,000-character commentary and in the
    # worst case most of it. The feed's <source> element carries the real
    # publisher domain, so we cite that instead. Empty means `url` is already a
    # real article link, which is the normal case.
    cite_url: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @property
    def quotable(self) -> bool:
        """Whether this item may supply a fact or be cited as a story's source."""
        return self.tier != SIGNAL

    @property
    def deep_link(self) -> bool:
        """Whether `url` points at the article itself rather than a redirect."""
        return not self.cite_url

    @property
    def citation(self) -> str:
        """The URL a reader should actually be given."""
        return self.cite_url or self.canonical or self.url

    def for_prompt(self, index: int) -> dict[str, Any]:
        """The trimmed view the model sees. Summary is capped to keep the prompt cheap."""
        out: dict[str, Any] = {
            "id": index,
            "title": self.title,
            "source": self.source,
            "url": self.canonical or self.url,
            # The model is told what each tier means, so it can pick an
            # authoritative primary_url instead of a forum thread about it.
            "kind": self.tier,
        }
        if self.summary:
            out["summary"] = self.summary[:400]
        if self.points is not None:
            out["hn_points"] = self.points
        return out


# --- Call 1: cluster + rank ------------------------------------------------


class Cluster(BaseModel):
    """One real-world story, with every feed item that reported it."""

    headline: str = Field(description="Neutral one-line description of what happened.")
    member_ids: list[int] = Field(
        description="Every candidate id that is reporting this same story."
    )
    primary_url: str = Field(
        description="The most authoritative URL among the members - prefer the "
        "original announcement over coverage of it."
    )
    # No ge/le: strict JSON-schema modes reject numeric bounds, and the schema
    # travels through OpenRouter to whichever provider serves the model. The
    # range is stated in the description and clamped in curate.py instead.
    importance: int = Field(
        description="Importance from 1 to 10. 10 = the AI story of the week. 1 = noise."
    )
    why_it_matters: str = Field(
        description="One sentence on the consequence, grounded only in the candidates."
    )


class Curation(BaseModel):
    clusters: list[Cluster]


@dataclass
class RankedCluster:
    """A cluster plus evidence computed from the feeds, which the model never sees.

    `sources` is the distinct feeds that reported the same event. Counting them is
    a genuine independence signal: TechCrunch, Ars and The Register each make their
    own editorial call, so five of them landing on one story is evidence it matters.

    Taking that count from a global news index instead was tried and rejected -
    there the top "story" was one AP markets piece carried by thirteen local
    papers, so the count measured wire syndication rather than newsworthiness.
    Independent desks are the thing worth counting, and we already read them.
    """

    cluster: Cluster
    sources: tuple[str, ...] = ()

    @property
    def corroboration(self) -> int:
        return len(self.sources)

    @property
    def score(self) -> float:
        """Importance, nudged by how many independent feeds carried the story."""
        bonus = min(self.corroboration, CORROBORATION_CAP) * CORROBORATION_WEIGHT
        return self.cluster.importance + bonus


# --- Call 2: the post ------------------------------------------------------


class StoryBlock(BaseModel):
    headline: str = Field(description="Punchy, under 70 characters, no clickbait.")
    detail: str = Field(description="One sentence of substance, under 160 characters.")
    source_name: str = Field(description="Who reported it, e.g. 'Anthropic' or 'TechCrunch'.")
    source_url: str = Field(description="Must be one of the cluster's primary_url values.")


class Post(BaseModel):
    hook: str = Field(description="The card's top line. Under 48 characters.")
    subhook: str = Field(description="Supporting line under the hook. Under 70 characters.")
    stories: list[StoryBlock]
    caption: str = Field(
        description="The Instagram caption. Opens with a hook, lists the stories, "
        "names each source. No hashtags here."
    )
    hashtags: list[str] = Field(description="8-12 relevant hashtags, no '#' prefix.")
    image_query: str = Field(
        description="Two or three concrete words for a stock-photo search that suits "
        "the lead story, e.g. 'server racks' or 'robot hand'."
    )


@dataclass
class Draft:
    """Everything a run produces, written to out/<date>/draft.json."""

    date: str
    post: dict[str, Any]
    clusters: list[dict[str, Any]] = field(default_factory=list)
    card_path: str = ""
    candidate_count: int = 0
