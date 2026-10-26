"""LinkedIn's `commentary` is little text, not plain text.

Every one of `\\ | { } @ [ ] ( ) < > # * _ ~` is markup there and must be
escaped even when it is not being used as markup. Source URLs routinely contain
`_` and `~`, and a model writing about "GPT-5 (preview)" produces parentheses,
so an unescaped caption is the normal case rather than an edge case.
"""

import pytest

from newsletter.pipeline import _caption_for
from newsletter.publish.linkedin import RESERVED, escape_little, hashtag

POST = {
    "hook": "Agents everywhere",
    "caption": "OpenAI shipped the Decisions API (finally).",
    "stories": [
        {
            "headline": "OpenAI makes its Decisions API broadly available",
            "detail": "Generally available today.",
            "source_name": "OpenAI",
            "source_url": "https://openai.com/index/decisions_api~v2",
        }
    ],
    "hashtags": ["ai", "openai", "llm", "agents", "devtools", "machinelearning", "tech"],
}


@pytest.mark.parametrize("char", sorted(RESERVED))
def test_every_reserved_character_is_escaped(char):
    assert escape_little(f"a{char}b") == f"a\\{char}b"


def test_underscores_and_tildes_in_a_url_are_escaped():
    """The realistic failure: a perfectly ordinary source URL is markup."""
    escaped = escape_little("https://openai.com/index/decisions_api~v2")
    assert escaped == "https://openai.com/index/decisions\\_api\\~v2"


def test_a_literal_backslash_is_escaped_once():
    """A second escaping pass would turn one backslash into four."""
    assert escape_little("a\\b") == "a\\\\b"


def test_plain_text_is_untouched():
    assert escape_little("Anthropic ships Opus 5.5 today.") == "Anthropic ships Opus 5.5 today."


def test_hashtag_uses_the_template_with_an_escaped_hash():
    assert hashtag("ai") == "{hashtag|\\#|ai}"
    assert hashtag("#ai") == "{hashtag|\\#|ai}"


def test_linkedin_caption_escapes_body_but_leaves_hashtag_templates_intact():
    caption = _caption_for("linkedin", POST)
    # The body's parentheses are escaped...
    assert "\\(finally\\)" in caption
    # ...and the hashtag templates survive, unescaped, so they still render.
    assert "{hashtag|\\#|ai}" in caption
    # A template that got escaped would show these instead.
    assert "\\{hashtag" not in caption


def test_linkedin_caption_trims_hashtags_and_instagram_does_not():
    linkedin = _caption_for("linkedin", POST)
    instagram = _caption_for("instagram", POST)
    assert linkedin.count("{hashtag|") == 5
    assert instagram.count("#") == len(POST["hashtags"])


def test_instagram_caption_is_not_escaped():
    """Escaping Instagram's caption would publish visible backslashes."""
    caption = _caption_for("instagram", POST)
    assert "\\" not in caption
    assert "decisions_api~v2" in caption


class _FakeResponse:
    def __init__(self, status=200, payload=None, headers=None, text=""):
        self.status_code = status
        self._payload = payload or {}
        self.headers = headers or {}
        self.text = text

    def json(self):
        return self._payload


class _FakeClient:
    """Records the three calls a LinkedIn publish makes, in order."""

    def __init__(self, calls):
        self.calls = calls

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def post(self, url, json=None, headers=None):
        self.calls.append(("POST", url, json, headers))
        if "initializeUpload" in url:
            return _FakeResponse(
                payload={
                    "value": {
                        "uploadUrl": "https://www.linkedin.com/dms-uploads/abc",
                        "image": "urn:li:image:ABC123",
                    }
                }
            )
        return _FakeResponse(status=201, headers={"x-restli-id": "urn:li:share:999"})

    def put(self, url, content=None, headers=None):
        self.calls.append(("PUT", url, content, headers))
        return _FakeResponse()


@pytest.fixture
def linkedin_env(monkeypatch):
    monkeypatch.setenv("LINKEDIN_ACCESS_TOKEN", "test-token")
    monkeypatch.setenv("LINKEDIN_PERSON_URN", "urn:li:person:XYZ")
    monkeypatch.setenv("LINKEDIN_TOKEN_EXPIRES_AT", "2099-01-01")


def test_publish_sends_the_documented_three_calls(linkedin_env, monkeypatch, tmp_path):
    import newsletter.publish.linkedin as li
    from newsletter.publish.base import Card

    card = tmp_path / "card.jpg"
    card.write_bytes(b"\xff\xd8jpegbytes")

    calls = []
    monkeypatch.setattr(li.httpx, "Client", lambda **kw: _FakeClient(calls))

    result = li.LinkedInPublisher().publish(Card(path=card, alt="Agents everywhere"), "hello")

    assert [c[0] for c in calls] == ["POST", "PUT", "POST"]

    # 1. register the upload, owned by the person
    init_url, init_body = calls[0][1], calls[0][2]
    assert init_url.endswith("/rest/images?action=initializeUpload")
    assert init_body == {"initializeUploadRequest": {"owner": "urn:li:person:XYZ"}}

    # 2. the bytes themselves go to the returned upload URL, not to the API
    assert calls[1][1] == "https://www.linkedin.com/dms-uploads/abc"
    assert calls[1][2] == b"\xff\xd8jpegbytes"

    # 3. the post references the image URN and carries the alt text
    body = calls[2][2]
    assert body["author"] == "urn:li:person:XYZ"
    assert body["content"]["media"]["id"] == "urn:li:image:ABC123"
    assert body["content"]["media"]["altText"] == "Agents everywhere"
    assert body["lifecycleState"] == "PUBLISHED"
    assert body["distribution"]["feedDistribution"] == "MAIN_FEED"

    # Versioned APIs reject a call without these two headers.
    headers = calls[2][3]
    assert headers["LinkedIn-Version"]
    assert headers["X-Restli-Protocol-Version"] == "2.0.0"

    assert result.post_id == "urn:li:share:999"
    assert result.url == "https://www.linkedin.com/feed/update/urn:li:share:999/"


def test_publish_refuses_a_missing_card(linkedin_env, tmp_path):
    from newsletter.publish.base import Card
    from newsletter.publish.linkedin import LinkedInError, LinkedInPublisher

    with pytest.raises(LinkedInError, match="card not found"):
        LinkedInPublisher().publish(Card(path=tmp_path / "nope.jpg"), "hi")


def test_a_malformed_person_urn_is_caught_at_construction(monkeypatch):
    from newsletter.publish.linkedin import LinkedInError, LinkedInPublisher

    monkeypatch.setenv("LINKEDIN_ACCESS_TOKEN", "test-token")
    monkeypatch.setenv("LINKEDIN_PERSON_URN", "XYZ")
    with pytest.raises(LinkedInError, match="urn:li:person"):
        LinkedInPublisher()


def test_expiry_warning_window(linkedin_env, monkeypatch):
    from newsletter.publish.linkedin import LinkedInPublisher

    monkeypatch.setenv("LINKEDIN_TOKEN_EXPIRES_AT", "1999-01-01")
    assert LinkedInPublisher().days_left() < 0
    monkeypatch.setenv("LINKEDIN_TOKEN_EXPIRES_AT", "")
    assert LinkedInPublisher().days_left() is None
