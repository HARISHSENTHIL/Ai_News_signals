"""Hugging Face Hub candidates, via two keyless JSON endpoints.

These cover a gap no RSS feed can. `daily_papers` returns papers ranked by
community upvotes rather than arrival order, which is the quality signal our
raw arXiv feeds lack entirely. `models` sorted by trendingScore surfaces a
release on the day it lands, instead of whenever a journalist writes it up.

Both are PRIMARY: a model that exists on the Hub and a paper with an id are
facts, not somebody's account of a fact. Neither needs a token - verified
against the live API on 2026-10-23.
"""

from __future__ import annotations

import logging
import re
from datetime import date, datetime, timedelta, timezone

import httpx

from ..config import (
    HF_MAX_AGE_HOURS,
    HF_MIN_MODEL_LIKES,
    HF_MIN_PAPER_UPVOTES,
    HF_MODELS_MAX,
    HF_PAPERS_MAX,
    PRIMARY,
)
from ..models import Item

log = logging.getLogger(__name__)

PAPERS_API = "https://huggingface.co/api/daily_papers"
MODELS_API = "https://huggingface.co/api/models"
USER_AGENT = "ai-newsletter/0.1 (+https://github.com/)"

# The Hub returns "2026-10-17T02:40:38.000Z". Three-digit fractions and the Z
# suffix are not portable across the Pythons we target, so take the prefix.
TIMESTAMP_RE = re.compile(r"(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2})")


def _parsed(raw: str | None) -> datetime | None:
    match = TIMESTAMP_RE.search(raw or "")
    if not match:
        return None
    return datetime.strptime(match.group(1), "%Y-%m-%dT%H:%M:%S").replace(tzinfo=timezone.utc)


def _is_fresh(raw: str | None, cutoff: datetime) -> bool:
    stamp = _parsed(raw)
    # No usable date means we cannot tell, and a silent drop is worse than a
    # candidate the ranker can reject on its own.
    return stamp is None or stamp > cutoff


def _fetch_papers(client: httpx.Client, run_date: date) -> list[Item]:
    """Today's curated daily list, ranked by upvotes.

    Scoped by `date` rather than `sort=trending`, which is an all-time ranking and
    cheerfully returns 2024 papers. Membership of a given day's list is itself the
    recency signal, so no age filter is applied on top of it.

    Yesterday is merged in because the draft cron fires at 01:30 UTC, when the
    current day's list has barely been populated.
    """
    by_id: dict[str, Item] = {}
    for offset in (0, 1):
        day = (run_date - timedelta(days=offset)).isoformat()
        response = client.get(PAPERS_API, params={"date": day})
        response.raise_for_status()

        for entry in response.json():
            paper = entry.get("paper") or {}
            upvotes = paper.get("upvotes") or 0
            paper_id = paper.get("id")
            title = (entry.get("title") or paper.get("title") or "").strip()
            if not paper_id or not title or upvotes < HF_MIN_PAPER_UPVOTES:
                continue
            if paper_id in by_id:
                continue

            by_id[paper_id] = Item(
                title=title,
                url=f"https://huggingface.co/papers/{paper_id}",
                source="HF Papers",
                weight=0.9,
                summary=(paper.get("ai_summary") or paper.get("summary") or "")[:600],
                published=entry.get("publishedAt", ""),
                points=upvotes,
                tier=PRIMARY,
            )

    items = sorted(by_id.values(), key=lambda i: i.points or 0, reverse=True)
    return items[:HF_PAPERS_MAX]


def _fetch_models(client: httpx.Client, cutoff: datetime) -> list[Item]:
    response = client.get(
        MODELS_API,
        params={"sort": "trendingScore", "direction": -1, "limit": 100},
    )
    response.raise_for_status()

    items: list[Item] = []
    for model in response.json():
        model_id = model.get("id")
        likes = model.get("likes") or 0
        if not model_id or likes < HF_MIN_MODEL_LIKES:
            continue
        # Trending is not the same as new - a six-day-old model can still top the
        # list long after it was covered. Only a recent upload is today's news.
        if not _is_fresh(model.get("createdAt"), cutoff):
            continue

        task = model.get("pipeline_tag") or "unspecified task"
        downloads = model.get("downloads") or 0
        items.append(
            Item(
                title=f"{model_id} released on Hugging Face",
                url=f"https://huggingface.co/{model_id}",
                source="HF Models",
                weight=1.2,
                summary=(
                    f"New model {model_id} for {task}. "
                    f"{likes} likes and {downloads} downloads so far."
                ),
                published=model.get("createdAt", ""),
                points=likes,
                tier=PRIMARY,
            )
        )

    items.sort(key=lambda i: i.points or 0, reverse=True)
    return items[:HF_MODELS_MAX]


def fetch_hf(run_date: date | None = None) -> list[Item]:
    """Today's upvoted papers and newly released models. Either half may fail alone."""
    run_date = run_date or datetime.now(timezone.utc).date()
    cutoff = datetime.now(timezone.utc) - timedelta(hours=HF_MAX_AGE_HOURS)
    items: list[Item] = []

    with httpx.Client(timeout=20.0, headers={"User-Agent": USER_AGENT}) as client:
        work = (
            ("HF Papers", lambda c: _fetch_papers(c, run_date)),
            ("HF Models", lambda c: _fetch_models(c, cutoff)),
        )
        for label, fetch in work:
            try:
                found = fetch(client)
            except Exception as exc:  # noqa: BLE001 - one endpoint must not fail the run
                log.warning("feed failed: %s (%s)", label, exc)
                continue
            log.info("%-18s %2d items", label, len(found))
            items.extend(found)

    return items
