"""Claude call 2: turn the top clusters into card copy and a caption.

The model sees only the clusters built in curate.py - titles, sources and URLs
that actually exist. Every story block must carry the source URL it came from,
so no claim can exist without an item behind it.
"""

from __future__ import annotations

import json
import logging

from .config import STORIES_PER_POST, WRITE_EFFORT, WRITE_MODEL
from .llm import ask
from .models import Post, RankedCluster

log = logging.getLogger(__name__)

SYSTEM = """You write a daily AI-news post for Instagram. The audience is \
developers and technically literate people who want to know what changed today \
without hype.

Voice: plain, specific, confident. No "game-changer", no "the future is here", \
no "buckle up", no emoji in the card copy. You may use at most two emoji in the \
caption. Never open the caption with a rhetorical question.

The card is 1080x1350 and holds a hook, a subhook and the story headlines, so the \
copy must be short enough to read at thumbnail size. Respect every character limit \
in the schema - text that overflows breaks the layout.

Grounding rules you must not break:
- Use only the information in the clusters provided. Never add a number, date, \
price, model name, benchmark result or quote that is not there.
- Every story's `source_url` must be copied verbatim from that cluster's \
`primary_url`, and `source_name` must match that source.
- If a cluster is thin, say less about it. Do not pad.

The caption lists each story with its source named in plain text, then closes with \
one short line. Hashtags go in the separate field, not the caption."""


def write_post(ranked: list[RankedCluster], limit: int = STORIES_PER_POST) -> Post:
    chosen = [r.cluster for r in ranked[:limit]]
    if not chosen:
        raise RuntimeError("No clusters to write about - the collection stage came up empty.")

    # Corroboration is deliberately withheld: it decided the running order, and a
    # count handed to the writer is just another number it could put in the
    # caption and get wrong.
    payload = [
        {
            "headline": cluster.headline,
            "why_it_matters": cluster.why_it_matters,
            "primary_url": cluster.primary_url,
            "importance": cluster.importance,
        }
        for cluster in chosen
    ]

    prompt = (
        f"Write today's post from these {len(payload)} stories, most important first.\n"
        f"Produce exactly {len(payload)} story blocks, in this order.\n\n"
        f"{json.dumps(payload, ensure_ascii=False, indent=1)}"
    )

    post = ask(
        system=SYSTEM,
        prompt=prompt,
        schema=Post,
        effort=WRITE_EFFORT,
        model=WRITE_MODEL,
    )

    # The schema cannot enforce "copied verbatim", so check it here.
    allowed = {cluster.primary_url for cluster in chosen}
    for story in post.stories:
        if story.source_url not in allowed:
            raise RuntimeError(
                f"Model cited a url that was not in its input: {story.source_url}"
            )

    log.info("write: %d story blocks, caption %d chars", len(post.stories), len(post.caption))
    return post
