"""Stage 3 of dedup, plus ranking - one Claude call.

Hashing cannot tell that "Anthropic ships Opus 5.5" and "New Claude model tops
the benchmarks" are the same event. A model can. At ~180 candidates this costs
about two cents and replaces an embedding + graph-clustering pipeline.
"""

from __future__ import annotations

import json
import logging

from .config import CURATE_EFFORT, CURATE_MODEL, MAX_CANDIDATES
from .llm import ask
from .models import Curation, Item, RankedCluster

log = logging.getLogger(__name__)

SYSTEM = """You are the editor of a daily AI newsletter. You are given today's \
candidate stories, each scraped from a feed, and recently published posts.

Your job has two parts:

1. CLUSTER. Group every candidate that reports the same real-world event into one \
cluster, however differently they are worded. A lab's announcement, a news site's \
write-up of it and a Reddit thread about it are ONE cluster. Two different models \
released by the same company on the same day are TWO clusters. Every candidate id \
appears in at most one cluster. Candidates that are not newsworthy may be left out \
of every cluster.

2. RANK. Score each cluster's importance from 1 to 10. Weight by: how many people \
it affects, whether it is a real capability or availability change versus an \
announcement of an intention, and whether a practitioner would change what they do \
tomorrow. Fundraising rounds and benchmark claims rank low unless they are enormous. \
Incremental arXiv preprints rank low. Corporate drama ranks low.

Each candidate carries a `kind`:
- "primary" - the announcement itself, a shipped release, or a paper. Most trustworthy.
- "reported" - journalism about an event.
- "signal" - a forum or community post. It tells you people are paying attention, \
so use it when judging importance and do list it in `member_ids`, but never choose \
it as `primary_url`.

Rules you must not break:
- Every cluster must be about AI. Several feeds carry general technology and \
security news, and a story that would be just as true in a world without AI does \
not belong in this newsletter - give it importance 1. A vulnerability in an AI \
system, model or agent counts; a vulnerability in an unrelated language runtime \
or web framework does not.
- `primary_url` must be copied verbatim from one of that cluster's own candidates, \
and must belong to a "primary" or "reported" candidate. Prefer the original \
announcement over coverage of it.
- `why_it_matters` must be supported by the candidate titles and summaries you were \
given. If you do not know the consequence, describe what happened instead. Never \
invent a number, a date, a price or a benchmark result.
- If a cluster covers a story that already appeared in a recent post, give it \
importance 1 so it drops out."""


def _history_block(history: list[dict]) -> str:
    if not history:
        return "No recent posts."
    lines = [f"- {entry.get('date', '?')}: {h}" for entry in history for h in entry.get("headlines", [])]
    return "\n".join(lines[:40]) or "No recent posts."


def _priority(item: Item) -> tuple[float, int]:
    # Weight is the editorial dial; votes break ties within a feed. The cut has to
    # be deliberate now that the feed list can produce more candidates than
    # MAX_CANDIDATES - left unsorted, fetch order would decide which lab
    # announcements the ranker never gets to see.
    return (item.weight, item.points or 0)


def curate(items: list[Item], history: list[dict]) -> list[RankedCluster]:
    """Cluster and rank candidates. Returns clusters sorted by blended score."""
    candidates = sorted(items, key=_priority, reverse=True)[:MAX_CANDIDATES]
    payload = [item.for_prompt(i) for i, item in enumerate(candidates)]

    prompt = (
        f"RECENTLY PUBLISHED (do not repeat these):\n{_history_block(history)}\n\n"
        f"TODAY'S CANDIDATES ({len(payload)}):\n"
        f"{json.dumps(payload, ensure_ascii=False, indent=1)}"
    )

    result = ask(
        system=SYSTEM,
        prompt=prompt,
        schema=Curation,
        effort=CURATE_EFFORT,
        model=CURATE_MODEL,
    )

    by_url = {item.canonical or item.url: item for item in candidates}
    ranked: list[RankedCluster] = []
    unquotable = 0
    domain_only = 0

    for cluster in result.clusters:
        # The schema cannot enforce "copied verbatim from the candidates", so we do.
        if cluster.primary_url not in by_url:
            log.warning("dropping cluster with invented url: %s", cluster.primary_url)
            continue
        # The schema can no longer bound this (strict mode rejects numeric
        # bounds), so clamp it here rather than trusting the model.
        cluster.importance = max(1, min(10, cluster.importance))

        members = [candidates[i] for i in cluster.member_ids if 0 <= i < len(candidates)]

        primary = by_url[cluster.primary_url]

        # The prompt asks for a quotable primary_url; this makes it true. A signal
        # source may raise a story's rank but never be cited for it, so re-point
        # the citation at a member we can stand behind. A story that only forums
        # carry has no such member, and goes.
        if not primary.quotable:
            swap = next((m for m in members if m.quotable), None)
            if swap is None:
                log.info("dropping signal-only cluster: %s", cluster.headline[:60])
                unquotable += 1
                continue
            primary = swap

        # Prefer whichever member links straight to the article. A Google News
        # item is a redirect that cites only its publisher's domain, so if any
        # other feed carried the same story we would rather send readers there
        # and keep the deep link. Falling back to the domain is what preserves
        # the labs that publish no usable feed of their own - Anthropic's blog
        # reaches us only through Google News - instead of dropping them.
        if not primary.deep_link:
            better = next((m for m in members if m.quotable and m.deep_link), None)
            if better is not None:
                primary = better
            else:
                domain_only += 1

        cluster.primary_url = primary.citation

        # Every distinct source counts, signal included: telling us a story has
        # attention is exactly what a signal source is for. See RankedCluster.
        sources = tuple(dict.fromkeys(member.source for member in members))
        ranked.append(RankedCluster(cluster=cluster, sources=sources))

    ranked.sort(key=lambda r: r.score, reverse=True)
    log.info(
        "curate: %d candidates -> %d clusters (%d signal-only dropped, "
        "%d cited by domain), top corroboration %d",
        len(payload),
        len(ranked),
        unquotable,
        domain_only,
        max((r.corroboration for r in ranked), default=0),
    )
    return ranked
