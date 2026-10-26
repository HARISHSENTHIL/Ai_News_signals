"""Pull candidates from the RSS/Atom feeds in config.FEEDS.

Every feed is keyless. One failing feed must never take the run down, so each is
fetched independently and failures are logged and skipped.
"""

from __future__ import annotations

import html
import logging
import re
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from urllib.parse import urlsplit

import feedparser
import httpx

from ..config import FEEDS, HOST_DELAY_S, RATE_LIMITED_BUDGET_S, RATE_LIMITED_HOSTS, Feed
from ..models import Item

log = logging.getLogger(__name__)

# Reddit and a few CDNs reject the default python-requests/feedparser agent.
USER_AGENT = "ai-newsletter/0.1 (+https://github.com/)"
# Anything older than this is not news. Widened from 36h once the feed list grew
# to include slower publishers: The Register's AI section and the weekly analysis
# newsletters routinely sit just past 36h, and were being dropped unread. Safe to
# widen because state/seen.json stops anything resurfacing a second time.
MAX_AGE_HOURS = 48
TAG_RE = re.compile(r"<[^>]+>")
# Google News titles are "Real headline - Publisher"; the feed-level source name
# would otherwise put "Google News" on the card instead of "TechCrunch".
PUBLISHER_SUFFIX_RE = re.compile(r"^(.*?)\s+-\s+([^-]{2,40})$")


def _clean(text: str) -> str:
    """Strip markup and collapse whitespace out of a feed summary."""
    if not text:
        return ""
    return re.sub(r"\s+", " ", html.unescape(TAG_RE.sub(" ", text))).strip()


def _is_recent(entry) -> bool:
    """Keep entries with no usable date - some lab blogs omit it."""
    parsed = entry.get("published_parsed") or entry.get("updated_parsed")
    if not parsed:
        return True
    published = datetime(*parsed[:6], tzinfo=timezone.utc)
    return published > datetime.now(timezone.utc) - timedelta(hours=MAX_AGE_HOURS)


def _get_with_retry(url: str, client: httpx.Client, attempts: int = 2) -> httpx.Response:
    """GET, retrying once on 429. Useful for a host having a brief moment.

    Not useful for Reddit, which since June 2026 allows roughly one request per
    minute on public .rss: a few seconds of backoff cannot clear a 60s window, so
    the throttled path passes attempts=1 and fails fast instead of burning ~9s
    per feed to earn a second 429. Observed in a live run on 2026-10-23.
    """
    for attempt in range(attempts):
        response = client.get(url)
        if response.status_code != 429:
            response.raise_for_status()
            return response
        if attempt < attempts - 1:
            wait = min(float(response.headers.get("retry-after", HOST_DELAY_S)), 10.0)
            log.info("429 on %s, retrying once in %.1fs", urlsplit(url).netloc, wait)
            time.sleep(wait)
    response.raise_for_status()
    return response


def _fetch_one(feed: Feed, client: httpx.Client, attempts: int = 2) -> list[Item]:
    try:
        response = _get_with_retry(feed.url, client, attempts)
    except Exception as exc:  # noqa: BLE001 - one dead feed must not fail the run
        log.warning("feed failed: %s (%s)", feed.source, exc)
        return []

    parsed = feedparser.parse(response.content)
    items: list[Item] = []
    for entry in parsed.entries:
        if len(items) >= feed.cap:
            break
        title = _clean(entry.get("title", ""))
        link = entry.get("link", "")
        if not title or not link or not _is_recent(entry):
            continue

        source = feed.source
        cite_url = ""
        if "news.google.com" in feed.url:
            match = PUBLISHER_SUFFIX_RE.match(title)
            if match:
                title, source = match.group(1).strip(), match.group(2).strip()
            # Google's own link is an opaque redirect, but the entry's <source>
            # element names the publisher and its domain. Keep the redirect as
            # `url` - it is unique, so dedup still separates two stories from the
            # same publisher - and cite the domain.
            origin = entry.get("source") or {}
            cite_url = origin.get("href", "")
            if origin.get("title"):
                source = origin["title"]

        items.append(
            Item(
                title=title,
                url=link,
                source=source,
                weight=feed.weight,
                summary=_clean(entry.get("summary", ""))[:600],
                published=entry.get("published", "") or entry.get("updated", ""),
                tier=feed.tier,
                cite_url=cite_url,
            )
        )
    log.info("%-18s %2d items", feed.source, len(items))
    return items


def fetch_rss(feeds: list[Feed] | None = None) -> list[Item]:
    """Fetch every feed. Rate-limited hosts go one at a time, the rest in parallel."""
    feeds = feeds if feeds is not None else FEEDS
    throttled = sorted(
        (f for f in feeds if urlsplit(f.url).hostname in RATE_LIMITED_HOSTS),
        key=lambda f: -f.weight,  # if the budget runs out, lose the least valuable
    )
    parallel = [f for f in feeds if f not in throttled]

    headers = {"User-Agent": USER_AGENT}
    items: list[Item] = []
    with httpx.Client(timeout=20.0, follow_redirects=True, headers=headers) as client:
        # Kick off the parallel ones, then walk the throttled hosts while they run.
        with ThreadPoolExecutor(max_workers=8) as pool:
            pending = pool.submit(
                lambda: [i for f in parallel for i in _fetch_one(f, client)]
            )
            deadline = time.monotonic() + RATE_LIMITED_BUDGET_S
            for index, feed in enumerate(throttled):
                if time.monotonic() > deadline:
                    log.warning(
                        "rate-limit budget spent; skipping %d throttled feed(s)",
                        len(throttled) - index,
                    )
                    break
                if index:
                    time.sleep(HOST_DELAY_S)
                items.extend(_fetch_one(feed, client, attempts=1))
            items.extend(pending.result())
    return items
