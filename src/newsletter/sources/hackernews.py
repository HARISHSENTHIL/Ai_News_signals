"""Hacker News candidates via the keyless Algolia search endpoint.

This is the practical stand-in for reading X: in 2026 the X API has no usable
free read tier, and anything that trends there surfaces here within hours.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

import httpx

from ..config import HN_MAX_ITEMS, HN_MIN_POINTS, HN_QUERIES, SIGNAL
from ..models import Item

log = logging.getLogger(__name__)

API = "https://hn.algolia.com/api/v1/search_by_date"


def fetch_hn(
    queries: list[str] | None = None,
    min_points: int = HN_MIN_POINTS,
    max_items: int = HN_MAX_ITEMS,
) -> list[Item]:
    queries = queries if queries is not None else HN_QUERIES
    since = int((datetime.now(timezone.utc) - timedelta(hours=36)).timestamp())
    by_url: dict[str, Item] = {}

    with httpx.Client(timeout=20.0) as client:
        for query in queries:
            params = {
                "query": query,
                "tags": "story",
                "numericFilters": f"points>{min_points},created_at_i>{since}",
                "hitsPerPage": 30,
                # Without this, Algolia matches the story text too and returns
                # things like "Airbnb bans..." for the query "AI".
                "restrictSearchableAttributes": "title",
            }
            try:
                response = client.get(API, params=params)
                response.raise_for_status()
                hits = response.json().get("hits", [])
            except Exception as exc:  # noqa: BLE001
                log.warning("HN query failed: %s (%s)", query, exc)
                continue

            for hit in hits:
                # Ask HN posts have no url; fall back to the discussion itself.
                url = hit.get("url") or f"https://news.ycombinator.com/item?id={hit['objectID']}"
                title = (hit.get("title") or "").strip()
                if not title or url in by_url:
                    continue
                by_url[url] = Item(
                    title=title,
                    url=url,
                    source="Hacker News",
                    weight=1.1,
                    published=hit.get("created_at", ""),
                    points=hit.get("points"),
                    # Signal, not reporting: the link is a real article but the
                    # title is submitter-written and there is no summary, so HN
                    # tells us a story has attention without vouching for a word
                    # of it. Upvotes still feed ranking.
                    tier=SIGNAL,
                )

    # Highest-voted first, then cut - points are our only quality signal here.
    items = sorted(by_url.values(), key=lambda i: i.points or 0, reverse=True)[:max_items]
    log.info("%-18s %2d items", "Hacker News", len(items))
    return items
