"""LinkedIn publishing via the versioned Posts API.

Two things make this unlike the Instagram publisher.

First, LinkedIn never fetches a URL - we hand it the JPEG bytes - so this needs
the card on disk, not a public link. That also means LinkedIn needs no public
repo and, more importantly, no App Review: `w_member_social` arrives by adding
the self-serve "Share on LinkedIn" product in the developer portal, so this
destination can be live the same day while Instagram waits on Meta.

Second, the token cannot be renewed in the background. LinkedIn issues
programmatic refresh tokens only to approved Marketing Developer Platform
partners, which a self-serve app is not, so the 60-day access token has to be
re-minted by hand with scripts/linkedin_auth.py. preflight() warns while there
is still time, so an expiry is never discovered on a morning the post is due.

Three calls per post: register the upload, PUT the bytes, create the post.
"""

from __future__ import annotations

import logging
from datetime import date, datetime, timezone

import httpx

from ..config import (
    LINKEDIN_API_VERSION,
    LINKEDIN_COMMENTARY_LIMIT,
    LINKEDIN_TOKEN_WARN_DAYS,
    env,
)
from .base import Card, PublishResult

log = logging.getLogger(__name__)

API = "https://api.linkedin.com"

# Reserved by LinkedIn's "little text format". Every one of these must be
# backslash-escaped in `commentary` even when it is not being used as markup,
# or the post is rejected or renders mangled. Note `_` and `~`: those appear in
# ordinary source URLs, which is how this bites you.
RESERVED = set(r"\|{}@[]()<>#*_~")


class LinkedInError(RuntimeError):
    pass


def escape_little(text: str) -> str:
    """Escape every reserved little-text character.

    Appending the backslash before the character it protects means a literal
    backslash in the input is handled by the same pass - there is no second
    round to double up what the first one added.
    """
    out: list[str] = []
    for char in text:
        if char in RESERVED:
            out.append("\\")
        out.append(char)
    return "".join(out)


def hashtag(tag: str) -> str:
    """A rendering hashtag, which is a template rather than a literal '#tag'.

    The '#' inside the template is itself escaped - that is what the API
    expects, not a nicety.
    """
    return "{hashtag|\\#|" + tag.lstrip("#") + "}"


class LinkedInPublisher:
    name = "linkedin"

    def __init__(self) -> None:
        self.token = env("LINKEDIN_ACCESS_TOKEN", required=True)
        self.person_urn = env("LINKEDIN_PERSON_URN", required=True)
        if not self.person_urn.startswith("urn:li:person:"):
            raise LinkedInError(
                f"LINKEDIN_PERSON_URN must look like urn:li:person:xxxx, "
                f"got {self.person_urn!r} - run scripts/linkedin_auth.py"
            )
        self.expires_at = env("LINKEDIN_TOKEN_EXPIRES_AT")

    @property
    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self.token}",
            "LinkedIn-Version": LINKEDIN_API_VERSION,
            "X-Restli-Protocol-Version": "2.0.0",
        }

    # --- http -------------------------------------------------------------

    def _post(self, client: httpx.Client, path: str, body: dict) -> httpx.Response:
        response = client.post(
            f"{API}{path}", json=body, headers={**self._headers, "Content-Type": "application/json"}
        )
        if response.status_code >= 400:
            raise LinkedInError(f"POST {path} -> {response.status_code}: {response.text[:400]}")
        return response

    # --- token ------------------------------------------------------------

    def days_left(self) -> int | None:
        """Days until the access token expires, if we were told when that is."""
        if not self.expires_at:
            return None
        try:
            expiry = date.fromisoformat(self.expires_at[:10])
        except ValueError:
            log.warning("LINKEDIN_TOKEN_EXPIRES_AT is not a date: %r", self.expires_at)
            return None
        return (expiry - datetime.now(timezone.utc).date()).days

    def preflight(self) -> str:
        """Confirm the token still works, and say how long it has left.

        /v2/userinfo is the cheapest authenticated call available to us: a GET
        on /rest/images is forbidden to a write-only `w_member_social` token,
        so it cannot stand in for a health check.
        """
        with httpx.Client(timeout=30.0) as client:
            response = client.get(f"{API}/v2/userinfo", headers=self._headers)
        if response.status_code == 401:
            raise LinkedInError(
                "LinkedIn access token is expired or revoked. LinkedIn does not "
                "grant refresh tokens to self-serve apps, so re-mint it: "
                "python scripts/linkedin_auth.py"
            )
        if response.status_code >= 400:
            raise LinkedInError(f"userinfo -> {response.status_code}: {response.text[:200]}")

        subject = response.json().get("sub", "")
        if subject and f"urn:li:person:{subject}" != self.person_urn:
            raise LinkedInError(
                f"token belongs to urn:li:person:{subject} but LINKEDIN_PERSON_URN "
                f"is {self.person_urn} - they must match"
            )

        remaining = self.days_left()
        if remaining is None:
            return "linkedin ok - token valid, expiry unknown"
        if remaining <= 0:
            raise LinkedInError("LinkedIn token has expired - run scripts/linkedin_auth.py")
        if remaining <= LINKEDIN_TOKEN_WARN_DAYS:
            log.warning("LinkedIn token expires in %d days - re-mint it soon", remaining)
        return f"linkedin ok - token valid, {remaining} days left"

    # --- publish ----------------------------------------------------------

    def _upload_image(self, client: httpx.Client, card: Card) -> str:
        """Register, upload, and return the image URN."""
        registered = self._post(
            client,
            "/rest/images?action=initializeUpload",
            {"initializeUploadRequest": {"owner": self.person_urn}},
        ).json()["value"]
        upload_url, image_urn = registered["uploadUrl"], registered["image"]

        # The upload URL is pre-signed and carries its own auth, but LinkedIn's
        # own examples send the bearer token anyway, so we match them.
        response = client.put(
            upload_url,
            content=card.path.read_bytes(),
            headers={
                "Authorization": f"Bearer {self.token}",
                "Content-Type": "image/jpeg",
            },
        )
        if response.status_code >= 400:
            raise LinkedInError(
                f"image upload -> {response.status_code}: {response.text[:200]}"
            )
        log.info("uploaded card to linkedin as %s", image_urn)
        return image_urn

    def publish(self, card: Card, caption: str) -> PublishResult:
        if not card.path.exists():
            raise LinkedInError(f"card not found at {card.path} - LinkedIn uploads the file")

        commentary = caption
        if len(commentary) > LINKEDIN_COMMENTARY_LIMIT:
            log.warning(
                "commentary truncated from %d to %d chars",
                len(commentary),
                LINKEDIN_COMMENTARY_LIMIT,
            )
            commentary = commentary[:LINKEDIN_COMMENTARY_LIMIT]

        with httpx.Client(timeout=120.0, follow_redirects=True) as client:
            image_urn = self._upload_image(client, card)

            response = self._post(
                client,
                "/rest/posts",
                {
                    "author": self.person_urn,
                    "commentary": commentary,
                    "visibility": "PUBLIC",
                    "distribution": {
                        "feedDistribution": "MAIN_FEED",
                        "targetEntities": [],
                        "thirdPartyDistributionChannels": [],
                    },
                    "content": {
                        "media": {
                            "id": image_urn,
                            # Truncated to the length LinkedIn recommends for
                            # screen readers rather than the 4,086 it allows.
                            "altText": (card.alt or "Daily AI news card")[:300],
                        }
                    },
                    "lifecycleState": "PUBLISHED",
                    "isReshareDisabledByAuthor": False,
                },
            )

        # The id comes back in a header, not the body.
        post_id = response.headers.get("x-restli-id", "")
        if not post_id:
            raise LinkedInError("post created but LinkedIn returned no x-restli-id")
        log.info("published to linkedin: %s", post_id)
        return PublishResult(
            platform=self.name,
            post_id=post_id,
            url=f"https://www.linkedin.com/feed/update/{post_id}/",
        )
