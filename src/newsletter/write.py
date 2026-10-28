"""Claude call 2: turn the top clusters into card copy and a caption.

The model sees only the clusters built in curate.py - titles, sources and URLs
that actually exist. Every story block must carry the source URL it came from,
so no claim can exist without an item behind it.
"""

from __future__ import annotations

import json
import logging

from .config import BRIEFS_MAX, LEADS_MAX, LEADS_MIN, WRITE_EFFORT, WRITE_MODEL
from .llm import ask
from .models import BRIEF, CATEGORIES, LEAD, Post, RankedCluster, StoryBlock

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

The caption lists every story - leads and briefs alike - with its source named in \
plain text, then closes with one short line. Hashtags go in the separate field, \
not the caption.

Two things to decide per story:

`tier` - how much room the story earns on the card.
- "lead" for a story a reader would want to know about today: a real launch, a \
funding round, a policy change, a security finding, a result that moves something.
- "brief" for a story that is genuine but minor: a routine version bump, an \
incremental addition, a story that only matters to people already following it.
- Judge each story on its own merit, not against a quota. Some days are heavy and \
some are thin; say so with the split rather than promoting filler or demoting \
real news to hit a number.

`category` - the card's left column. Exactly one of: MODEL, TOOLS, RESEARCH, \
FUNDING, POLICY, SECURITY, BUSINESS, NEWS. Use NEWS only when nothing else fits."""


def _shelve(stories: list[StoryBlock]) -> list[StoryBlock]:
    """Force the model's split into the shelf sizes the card can render.

    No JSON schema can say "3 to 5 leads and at most 4 briefs", so the model is
    asked in the prompt and corrected here. Stories arrive in the running order
    curate ranked them in, so promoting the first brief takes the strongest one
    available and demoting the last lead gives up the weakest - which is what
    makes a repair cheaper than a re-ask.
    """
    leads = [s for s in stories if s.is_lead]
    briefs = [s for s in stories if not s.is_lead]

    while len(leads) < LEADS_MIN and briefs:
        promoted = briefs.pop(0)
        promoted.tier = LEAD
        leads.append(promoted)
    while len(leads) > LEADS_MAX:
        demoted = leads.pop()
        demoted.tier = BRIEF
        briefs.insert(0, demoted)

    if len(briefs) > BRIEFS_MAX:
        log.info("dropping %d brief(s) past the card's room", len(briefs) - BRIEFS_MAX)
        briefs = briefs[:BRIEFS_MAX]

    log.info("shelved %d lead(s) and %d brief(s)", len(leads), len(briefs))
    return leads + briefs


def write_post(ranked: list[RankedCluster], limit: int = 0) -> Post:
    # Enough for a full card on a heavy day. Anything past this was ranked below
    # nine other stories and is not going to earn a line.
    limit = limit or LEADS_MAX + BRIEFS_MAX
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
        f"Produce exactly {len(payload)} story blocks, in this order, each with a "
        f"`tier` and a `category`.\n"
        f"Aim for {LEADS_MIN}-{LEADS_MAX} leads and at most {BRIEFS_MAX} briefs; "
        f"anything beyond that is dropped, so put the weakest stories last.\n\n"
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

    # Same reason the tier split is repaired rather than trusted: the vocabulary
    # lives in a field description, which is guidance, not a constraint.
    for story in post.stories:
        upper = story.category.strip().upper()
        if upper not in CATEGORIES:
            log.info("unknown category %r on %r - using NEWS", story.category, story.headline[:40])
            upper = "NEWS"
        story.category = upper

    post.stories = _shelve(post.stories)

    log.info("write: %d story blocks, caption %d chars", len(post.stories), len(post.caption))
    return post
