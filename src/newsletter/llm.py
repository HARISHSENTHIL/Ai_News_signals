"""One place that talks to a model, through OpenRouter.

OpenRouter is an OpenAI-compatible gateway, so this uses the OpenAI SDK pointed
at their base URL rather than a provider SDK. Two things matter here:

  * `provider.require_parameters` - without it OpenRouter treats response_format
    as a soft preference and may route to an endpoint that ignores it, which
    would hand us prose instead of JSON and break the pipeline silently.
  * Schemas must stay inside strict mode's subset: no numeric bounds, no
    optional fields. See the note on Cluster.importance in models.py.

No prompt caching: this runs twice a day and cache windows are minutes, so a
breakpoint would never be hit.
"""

from __future__ import annotations

import logging
from typing import TypeVar

from openai import ContentFilterFinishReasonError, LengthFinishReasonError, OpenAI
from pydantic import BaseModel

from .config import CURATE_MODEL, OPENROUTER_BASE_URL, env

log = logging.getLogger(__name__)

T = TypeVar("T", bound=BaseModel)

_client: OpenAI | None = None


def client() -> OpenAI:
    global _client
    if _client is None:
        _client = OpenAI(
            base_url=OPENROUTER_BASE_URL,
            api_key=env("OPENROUTER_API_KEY", required=True),
            # Optional, and only used for OpenRouter's public leaderboards.
            default_headers={
                "HTTP-Referer": env("OPENROUTER_SITE_URL", "https://github.com"),
                "X-Title": env("OPENROUTER_APP_NAME", "AI Daily"),
            },
        )
    return _client


def ask(
    *,
    system: str,
    prompt: str,
    schema: type[T],
    effort: str,
    model: str = CURATE_MODEL,
    max_tokens: int = 16000,
) -> T:
    """One structured-output call. Returns a validated instance of `schema`."""
    try:
        completion = client().chat.completions.parse(
            model=model,
            max_tokens=max_tokens,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": prompt},
            ],
            response_format=schema,
            reasoning_effort=effort,
            extra_body={
                # Route only to endpoints that actually honour response_format.
                "provider": {"require_parameters": True},
            },
        )
    except LengthFinishReasonError as exc:
        # Truncated JSON means silently missing stories, so this must be loud.
        raise RuntimeError(
            f"{schema.__name__}: response hit max_tokens ({max_tokens}) and is "
            f"incomplete - raise it or ask for fewer items"
        ) from exc
    except ContentFilterFinishReasonError as exc:
        raise RuntimeError(f"{schema.__name__}: the provider filtered the response") from exc

    choice = completion.choices[0]
    parsed = choice.message.parsed
    if parsed is None:
        # Refusal, or a provider that returned something unparseable despite
        # require_parameters. Surface the text so the cause is visible.
        refusal = getattr(choice.message, "refusal", None)
        raise RuntimeError(
            f"{schema.__name__}: no structured output returned "
            f"(refusal={refusal!r}, finish_reason={choice.finish_reason!r})"
        )

    if completion.usage:
        log.info(
            "%s via %s: %d in / %d out tokens",
            schema.__name__,
            completion.model,
            completion.usage.prompt_tokens,
            completion.usage.completion_tokens,
        )
    return parsed
