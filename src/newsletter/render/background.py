"""The 'hybrid' half of the visual: a real photo behind templated text.

Providers are tried in order and the first one that answers wins. The last step
is always a generated mesh gradient, so the renderer never hard-depends on a
third party being up, reachable, or still issuing API keys.

  1. Pexels    - best quality, but key issuance was paused as of Oct 2026
  2. Pixabay   - free key, open signup, commercial use, no attribution required
  3. Openverse - no key at all; restricted to CC0/public-domain so the images
                 are safe on a brand account and need no credit
  4. gradient  - always works

Licensing matters here: Openverse serves a lot of NonCommercial and ShareAlike
work, which is the wrong fit for a branded post that overlays text (a derivative
work). We ask for CC0/PDM only and accept a smaller pool.
"""

from __future__ import annotations

import base64
import hashlib
import logging
import re
import time
from dataclasses import dataclass

import httpx

from ..config import env

log = logging.getLogger(__name__)

USER_AGENT = "ai-newsletter/0.1 (https://github.com/; daily AI news card generator)"
# Openverse is slow on a cold cache (~14s) and fast afterwards, so it needs more
# headroom than a normal API call.
SEARCH_TIMEOUT_S = 45.0
DOWNLOAD_TIMEOUT_S = 30.0
# Total wall-clock for finding a background. A picture is never worth stalling
# the run for - past this we take the gradient and move on.
BACKGROUND_BUDGET_S = 75.0
# Images to try per search before giving up on that query. Some hosts (Wikimedia
# especially) rate-limit hotlinking, so one dead image must not sink a provider.
MAX_DOWNLOAD_ATTEMPTS = 4
# Deep, desaturated palettes. Text sits on a scrim over these, so they stay dark.
GRADIENT_PALETTES = [
    ("#0b1021", "#1b2a5e", "#0e5a6b"),
    ("#10061f", "#3a1259", "#6b1f4d"),
    ("#04161a", "#0b3d3b", "#1f5e4a"),
    ("#140a05", "#4a2010", "#6b3a12"),
    ("#0a0d14", "#1f2937", "#374151"),
]
# Used when a narrow query returns nothing - broad terms always have results.
FALLBACK_QUERIES = ["artificial intelligence", "circuit board", "technology abstract"]


@dataclass
class Background:
    """`data_uri` is empty when every provider failed and we fell back to the gradient."""

    data_uri: str = ""
    credit: str = ""
    palette: tuple[str, str, str] = GRADIENT_PALETTES[0]
    provider: str = "gradient"


def _palette_for(seed: str) -> tuple[str, str, str]:
    """Deterministic per-day palette, so consecutive posts do not look identical."""
    digest = hashlib.sha256(seed.encode()).digest()
    return GRADIENT_PALETTES[digest[0] % len(GRADIENT_PALETTES)]


def _rotate(candidates: list, seed: str) -> list:
    """Deterministic daily rotation, best-first, with the rest kept as fallbacks."""
    if not candidates:
        return []
    offset = hashlib.sha256(seed.encode()).digest()[1] % len(candidates)
    return candidates[offset:] + candidates[:offset]


def _queries(query: str) -> list[str]:
    """The query, then progressively broader fallbacks."""
    words = re.findall(r"[a-zA-Z]+", query)
    attempts = [query]
    if len(words) > 1:
        attempts.append(" ".join(words[:2]))
    # Capped deliberately: each miss costs a round trip, and the gradient is a
    # perfectly good outcome.
    return (attempts + FALLBACK_QUERIES)[:4]


# --- providers -------------------------------------------------------------
# Each returns an ordered list of (image_url, credit) candidates, best first.
# An empty list means "nothing for this query".


def _pexels(client: httpx.Client, query: str, seed: str) -> list[tuple[str, str]]:
    key = env("PEXELS_API_KEY")
    if not key:
        return []
    response = client.get(
        "https://api.pexels.com/v1/search",
        headers={"Authorization": key},
        params={"query": query, "orientation": "portrait", "size": "large", "per_page": 15},
        timeout=SEARCH_TIMEOUT_S,
    )
    response.raise_for_status()
    photos = _rotate(response.json().get("photos", []), seed)
    return [
        (p["src"]["large2x"], f"Photo by {p.get('photographer', 'Pexels')} on Pexels")
        for p in photos
    ]


def _pixabay(client: httpx.Client, query: str, seed: str) -> list[tuple[str, str]]:
    key = env("PIXABAY_API_KEY")
    if not key:
        return []
    response = client.get(
        "https://pixabay.com/api/",
        params={
            "key": key,
            "q": query,
            "image_type": "photo",
            "orientation": "vertical",
            "safesearch": "true",
            "per_page": 20,
        },
        timeout=SEARCH_TIMEOUT_S,
    )
    response.raise_for_status()
    hits = _rotate(response.json().get("hits", []), seed)
    # Pixabay's licence needs no credit, but naming the photographer is polite.
    return [
        (h["largeImageURL"], f"Image by {h.get('user', 'Pixabay')} on Pixabay") for h in hits
    ]


def _openverse(client: httpx.Client, query: str, seed: str) -> list[tuple[str, str]]:
    """Keyless. CC0/public-domain only - safe to overlay text on commercially."""
    response = client.get(
        "https://api.openverse.org/v1/images/",
        params={
            "q": query,
            "license": "cc0,pdm",
            "orientation": "tall",
            "page_size": 20,
        },
        timeout=SEARCH_TIMEOUT_S,
    )
    response.raise_for_status()
    results = _rotate([r for r in response.json().get("results", []) if r.get("url")], seed)
    return [(r["url"], f"{r.get('title', 'Image')} (public domain)") for r in results]


PROVIDERS = (("pexels", _pexels), ("pixabay", _pixabay), ("openverse", _openverse))


def fetch_background(query: str, seed: str = "") -> Background:
    palette = _palette_for(seed or query)
    seed = seed or query

    deadline = time.monotonic() + BACKGROUND_BUDGET_S
    with httpx.Client(
        timeout=SEARCH_TIMEOUT_S, follow_redirects=True, headers={"User-Agent": USER_AGENT}
    ) as client:
        for name, provider in PROVIDERS:
            for attempt in _queries(query):
                if time.monotonic() > deadline:
                    log.warning("background budget spent; using gradient")
                    return Background(palette=palette)
                try:
                    candidates = provider(client, attempt, seed)
                except Exception as exc:  # noqa: BLE001 - move to the next provider
                    log.warning("%s search failed (%s)", name, exc)
                    break
                if not candidates:
                    continue  # nothing for this query; try a broader one

                # Some hosts rate-limit hotlinking, so walk the results rather
                # than letting one dead image disqualify the provider.
                for image_url, credit in candidates[:MAX_DOWNLOAD_ATTEMPTS]:
                    if time.monotonic() > deadline:
                        break
                    try:
                        image = client.get(image_url, timeout=DOWNLOAD_TIMEOUT_S)
                        image.raise_for_status()
                    except Exception as exc:  # noqa: BLE001
                        log.info("%s: skipping an image (%s)", name, type(exc).__name__)
                        continue
                    if len(image.content) < 10_000:
                        continue  # a placeholder or an error page, not a photo

                    encoded = base64.b64encode(image.content).decode()
                    media_type = image.headers.get(
                        "content-type", "image/jpeg"
                    ).split(";")[0]
                    log.info(
                        "background from %s (%r, %d KB)",
                        name, attempt, len(image.content) // 1024,
                    )
                    return Background(
                        data_uri=f"data:{media_type};base64,{encoded}",
                        credit=credit,
                        palette=palette,
                        provider=name,
                    )

    log.info("no provider returned an image; using generated gradient")
    return Background(palette=palette)
