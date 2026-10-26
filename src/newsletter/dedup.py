"""Stages 1 and 2 of dedup: the cheap ones.

Stage 1  canonical_url  - exact duplicates and anything already seen.
Stage 2  title_jaccard  - the same item syndicated under a near-identical title.
Stage 3  lives in curate.py: one Claude call groups the same *event* reported in
         different words, which no hashing scheme can do.

Both functions here are pure and stdlib-only, which is why they are the part
under unit test.
"""

from __future__ import annotations

import json
import logging
import re
from datetime import date, datetime, timedelta
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from .config import SEEN_WINDOW_DAYS, STATE_DIR, TITLE_JACCARD_THRESHOLD
from .models import Item

log = logging.getLogger(__name__)

SEEN_PATH = STATE_DIR / "seen.json"

# Tracking junk that makes one URL look like several.
TRACKING_PREFIXES = ("utm_", "mc_", "pk_")
TRACKING_KEYS = {
    "ref", "ref_src", "ref_url", "source", "fbclid", "gclid", "igshid",
    "sh", "share", "si", "cmpid", "ncid", "at_medium", "at_campaign",
}

# Dropped from titles before comparison: outlet suffixes and filler words that
# make unrelated headlines look similar.
STOPWORDS = {
    "a", "an", "the", "and", "or", "of", "to", "in", "on", "for", "with", "at",
    "by", "from", "is", "are", "its", "it", "as", "that", "this", "new", "now",
    "says", "will", "has", "have", "be", "but", "not", "you", "your", "we",
}
WORD_RE = re.compile(r"[a-z0-9]+")


def canonical_url(url: str) -> str:
    """A stable key for one web resource.

    Strips tracking params, AMP suffixes, fragments, default ports and the
    www. prefix, and lowercases the host. The path's case is preserved -
    some CMSes are case-sensitive.
    """
    if not url:
        return ""
    try:
        parts = urlsplit(url.strip())
    except ValueError:
        return url.strip()

    host = (parts.hostname or "").lower()
    if not host:
        # Not a URL at all. Return it untouched rather than inventing a host,
        # which would make unrelated garbage strings collide.
        return url.strip()

    scheme = "https" if parts.scheme in ("", "http", "https") else parts.scheme
    if host.startswith("www."):
        host = host[4:]
    # Keep a non-default port; drop 80/443.
    if parts.port and parts.port not in (80, 443):
        host = f"{host}:{parts.port}"

    path = parts.path
    for suffix in ("/amp", "/amp/", "amp.html"):
        if path.endswith(suffix):
            path = path[: -len(suffix)]
            break
    if len(path) > 1:
        path = path.rstrip("/")

    kept = [
        (key, value)
        for key, value in parse_qsl(parts.query, keep_blank_values=False)
        if key.lower() not in TRACKING_KEYS
        and not key.lower().startswith(TRACKING_PREFIXES)
    ]
    kept.sort()

    return urlunsplit((scheme, host, path, urlencode(kept), ""))


def title_tokens(title: str) -> frozenset[str]:
    """Normalised content words, with the outlet suffix removed."""
    # "Headline | TechCrunch" / "Headline - The Verge" -> "Headline"
    trimmed = re.split(r"\s+[|–—]\s+|\s+-\s+(?=[A-Z])", title)[0]
    words = WORD_RE.findall(trimmed.lower())
    return frozenset(w for w in words if w not in STOPWORDS and len(w) > 2)


def title_jaccard(left: str, right: str) -> float:
    """Token-set overlap of two titles, 0.0 to 1.0."""
    a, b = title_tokens(left), title_tokens(right)
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def dedupe_items(
    items: list[Item], threshold: float = TITLE_JACCARD_THRESHOLD
) -> list[Item]:
    """Collapse exact-URL and near-identical-title duplicates.

    When two items collide the heavier source wins, so a lab's own announcement
    survives and an aggregator's repost of it does not.
    """
    for item in items:
        item.canonical = canonical_url(item.url)

    # Heaviest first so the winner of each collision is the one we keep.
    ordered = sorted(items, key=lambda i: (-i.weight, i.title))

    kept: list[Item] = []
    seen_urls: set[str] = set()
    for item in ordered:
        if item.canonical and item.canonical in seen_urls:
            continue
        if any(title_jaccard(item.title, k.title) >= threshold for k in kept):
            continue
        kept.append(item)
        if item.canonical:
            seen_urls.add(item.canonical)

    log.info("dedup: %d candidates -> %d after url/title collapse", len(items), len(kept))
    return kept


# --- the seen store --------------------------------------------------------


def load_seen() -> dict[str, str]:
    """canonical url -> ISO date first seen. Missing or corrupt file starts empty."""
    if not SEEN_PATH.exists():
        return {}
    try:
        return json.loads(SEEN_PATH.read_text())
    except (json.JSONDecodeError, OSError) as exc:
        log.warning("seen store unreadable, starting fresh (%s)", exc)
        return {}


def prune_seen(seen: dict[str, str], window_days: int = SEEN_WINDOW_DAYS) -> dict[str, str]:
    cutoff = date.today() - timedelta(days=window_days)
    out = {}
    for url, iso in seen.items():
        try:
            if datetime.fromisoformat(iso).date() > cutoff:
                out[url] = iso
        except ValueError:
            continue  # drop unparseable entries
    return out


def drop_seen(items: list[Item], seen: dict[str, str]) -> list[Item]:
    fresh = [i for i in items if i.canonical not in seen]
    log.info("dedup: %d -> %d after dropping previously seen", len(items), len(fresh))
    return fresh


def record_seen(items: list[Item], seen: dict[str, str], path: Path = SEEN_PATH) -> None:
    today = date.today().isoformat()
    for item in items:
        if item.canonical:
            seen.setdefault(item.canonical, today)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(prune_seen(seen), indent=0, sort_keys=True))
