"""The two entry points, and the CLI that GitHub Actions calls.

    draft    collect -> dedup -> cluster/rank -> write -> render -> ask for approval
    publish  read the decision -> publish or skip

They are separate processes because Actions cannot receive a webhook: the draft
job exits after asking, and a second scheduled job picks the answer up.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from datetime import date
from pathlib import Path

from . import dedup
from .config import (
    DESTINATIONS,
    HISTORY_LOOKBACK,
    LINKEDIN_HASHTAG_LIMIT,
    OUT_DIR,
    STATE_DIR,
    env,
)
from .curate import curate
from .notify import telegram
from .publish.base import Card
from .publish.linkedin import escape_little, hashtag
from .render.card import render_card
from .sources import fetch_hf, fetch_hn, fetch_rss
from .verify import unsupported_terms
from .write import write_post

log = logging.getLogger(__name__)

POSTED_PATH = STATE_DIR / "posted.jsonl"


# --- history ---------------------------------------------------------------


def load_history(limit: int = HISTORY_LOOKBACK) -> list[dict]:
    """The last N posts, newest last. Fed to the ranker so it will not repeat itself."""
    if not POSTED_PATH.exists():
        return []
    entries = []
    for line in POSTED_PATH.read_text().splitlines():
        if not line.strip():
            continue
        try:
            entries.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return entries[-limit:]


def append_history(entry: dict) -> None:
    POSTED_PATH.parent.mkdir(parents=True, exist_ok=True)
    with POSTED_PATH.open("a") as handle:
        handle.write(json.dumps(entry) + "\n")


def run_dir(run_date: date, dry_run: bool = False) -> Path:
    return OUT_DIR / ("dry-run" if dry_run else run_date.isoformat())


# --- draft -----------------------------------------------------------------


def draft(run_date: date | None = None, dry_run: bool = False, notify: bool = True) -> dict:
    run_date = run_date or date.today()
    out = run_dir(run_date, dry_run)

    # 1. collect
    items = fetch_rss() + fetch_hn() + fetch_hf(run_date)
    log.info("collected %d raw items", len(items))
    if not items:
        raise RuntimeError("every source returned nothing - check network access")

    # 2. cheap dedup, then drop what we have already seen
    items = dedup.dedupe_items(items)
    seen = dedup.prune_seen(dedup.load_seen())
    items = dedup.drop_seen(items, seen)
    if not items:
        raise RuntimeError("nothing new today - every candidate was already seen")

    # 3. the expensive stage: same-event clustering and ranking
    ranked = curate(items, load_history())
    if not ranked:
        raise RuntimeError("the model produced no usable clusters")

    # 4. write, 5. render
    post = write_post(ranked)

    # Prompt rules alone did not stop the model inventing a competitor on
    # 2026-10-23, so every draft is checked against what the sources actually
    # said. This never blocks - it tells the human gate what to look at.
    suspect = unsupported_terms(post, items)

    card_path = render_card(post, out, run_date)

    draft_record = {
        "date": run_date.isoformat(),
        "post": post.model_dump(),
        # sources/corroboration are ours, not the model's - keeping them in the
        # record is what makes a ranking decision reviewable after the fact.
        "clusters": [
            {
                **r.cluster.model_dump(),
                "sources": list(r.sources),
                "corroboration": r.corroboration,
            }
            for r in ranked[:8]
        ],
        "card_path": str(card_path.relative_to(OUT_DIR.parent)),
        "candidate_count": len(items),
        "unsupported_terms": suspect,
    }
    (out / "draft.json").write_text(json.dumps(draft_record, indent=2, ensure_ascii=False))
    log.info("draft written to %s", out / "draft.json")

    if dry_run:
        log.info("dry run: not recording seen urls, not sending to telegram")
        return draft_record

    # Only a real run burns the candidates, so a dry run can be repeated freely.
    dedup.record_seen(items, seen)

    if notify:
        telegram.send_draft(
            card_path,
            draft_record["post"],
            run_date.isoformat(),
            len(items),
            suspect,
        )
    return draft_record


# --- publish ---------------------------------------------------------------


def _card(record: dict) -> Card:
    """The rendered card, in both forms a destination might want.

    PUBLIC_BASE_URL is deliberately not required: LinkedIn uploads the bytes, so
    a LinkedIn-only setup needs no public host at all. The Instagram publisher
    raises its own error if the URL it needs is missing.
    """
    base = env("PUBLIC_BASE_URL").rstrip("/")
    return Card(
        path=OUT_DIR.parent / record["card_path"],
        url=f"{base}/{record['card_path']}" if base else "",
        alt=record["post"].get("hook", ""),
    )


def _publishers() -> list:
    """Build a publisher per configured destination, in DESTINATIONS order."""
    from .publish import InstagramPublisher, LinkedInPublisher

    known = {"instagram": InstagramPublisher, "linkedin": LinkedInPublisher}
    unknown = [name for name in DESTINATIONS if name not in known]
    if unknown:
        raise RuntimeError(f"unknown destination(s) in DESTINATIONS: {', '.join(unknown)}")
    if not DESTINATIONS:
        raise RuntimeError("DESTINATIONS is empty - nowhere to publish")
    return [known[name]() for name in DESTINATIONS]


def publish_approved(run_date: date | None = None) -> str:
    """Act on whatever button was pressed. Returns a one-line status."""
    run_date = run_date or date.today()
    run_id = run_date.isoformat()
    draft_path = run_dir(run_date) / "draft.json"

    if not draft_path.exists():
        return f"no draft for {run_id} - nothing to publish"

    decision = telegram.poll_decision(run_id)
    if decision is None:
        return f"no decision yet for {run_id}"

    if decision.action == "skip":
        telegram.acknowledge(decision, "Skipped.")
        append_history({"date": run_id, "status": "skipped", "headlines": []})
        return f"{run_id} skipped by request"

    if decision.action == "regen":
        telegram.acknowledge(decision, "Regenerating...")
        # Record what was turned down before rebuilding. The ranker is shown
        # recent headlines and told not to repeat them, and nothing else marks
        # a rejected draft as rejected - so without this a regenerate can hand
        # back the same four stories it was just asked to replace.
        rejected = json.loads(draft_path.read_text())["post"]
        append_history(
            {
                "date": run_id,
                "status": "rejected",
                "headlines": [s["headline"] for s in rejected["stories"]],
            }
        )
        record = draft(run_date)
        return f"{run_id} regenerated with {record['candidate_count']} candidates"

    record = json.loads(draft_path.read_text())
    post = record["post"]
    card = _card(record)

    # One failing destination must not cost us the other: a LinkedIn token that
    # lapsed overnight should not stop the Instagram post going out. Everything
    # is attempted, then reported together.
    posted: dict[str, str] = {}
    failures: list[str] = []
    for publisher in _publishers():
        try:
            log.info(publisher.preflight())
            result = publisher.publish(card, _caption_for(publisher.name, post))
            posted[result.platform] = result.post_id
            if result.url:
                log.info("%s: %s", result.platform, result.url)
        except Exception as exc:  # noqa: BLE001 - report every destination's fate
            log.error("%s failed: %s", publisher.name, exc)
            failures.append(f"{publisher.name}: {exc}")

    if not posted:
        telegram.acknowledge(decision, "Failed.")
        telegram.send_text("Nothing published:\n" + "\n".join(failures))
        return f"{run_id} failed on every destination"

    telegram.acknowledge(decision, "Posted.")
    summary = ", ".join(f"{platform} {post_id}" for platform, post_id in posted.items())
    message = f"Published to {summary}"
    if failures:
        message += "\n\nFailed:\n" + "\n".join(failures)
    telegram.send_text(message)

    append_history(
        {
            "date": run_id,
            "status": "published",
            "posts": posted,
            "failed": failures,
            "headlines": [s["headline"] for s in post["stories"]],
            "urls": [s["source_url"] for s in post["stories"]],
        }
    )
    return f"{run_id} published to {summary}"


def _body(post: dict) -> str:
    """Caption body and the source list every destination carries."""
    links = "\n".join(f"{s['source_name']}: {s['source_url']}" for s in post["stories"])
    return f"{post['caption']}\n\nSources:\n{links}"


def _caption_for(platform: str, post: dict) -> str:
    """The same post, in each platform's own conventions.

    Instagram takes plain text and rewards a wall of hashtags. LinkedIn parses
    `commentary` as little text, where `_`, `~`, `(` and `)` are markup and have
    to be escaped even in a URL, and where a dozen hashtags read as spam - so it
    gets the escaped body plus a handful of tags as hashtag templates.
    """
    if platform == "linkedin":
        tags = " ".join(hashtag(tag) for tag in post["hashtags"][:LINKEDIN_HASHTAG_LIMIT])
        return f"{escape_little(_body(post))}\n\n{tags}".rstrip()
    hashtags = " ".join(f"#{tag.lstrip('#')}" for tag in post["hashtags"])
    return f"{_body(post)}\n\n{hashtags}".rstrip()


# --- cli -------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="newsletter")
    parser.add_argument("command", choices=["draft", "publish"])
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="draft only: render locally, touch no state and send nothing",
    )
    parser.add_argument("--date", help="override the run date, YYYY-MM-DD")
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s  %(levelname)-7s %(message)s",
        datefmt="%H:%M:%S",
    )
    # httpx logs every request URL at INFO, and the Telegram bot token is *in*
    # the URL path - so this would print a live credential on every run, into
    # CI logs and any terminal output that gets pasted somewhere. Our own log
    # lines already say what each call did, so nothing useful is lost.
    logging.getLogger("httpx").setLevel(logging.WARNING)

    run_date = date.fromisoformat(args.date) if args.date else date.today()

    try:
        if args.command == "draft":
            record = draft(run_date, dry_run=args.dry_run)
            print(f"\nhook:    {record['post']['hook']}")
            print(f"stories: {len(record['post']['stories'])}")
            print(f"card:    {record['card_path']}")
        else:
            print(publish_approved(run_date))
    except Exception as exc:  # noqa: BLE001 - the CLI is the top of the stack
        log.error("%s: %s", type(exc).__name__, exc)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
