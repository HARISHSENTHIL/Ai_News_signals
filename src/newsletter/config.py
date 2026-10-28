"""Feeds, thresholds and environment loading.

Everything tunable about the pipeline lives here. Adding or dropping a source is
a one-line edit to FEEDS.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

def env(name: str, default: str | None = None, *, required: bool = False) -> str:
    # An unset GitHub Actions variable arrives as "", not as a missing key, so
    # empty has to mean "fall back to the default" or every override wins blank.
    value = os.environ.get(name) or default
    if required and not value:
        raise RuntimeError(
            f"{name} is not set. Copy .env.example to .env and fill it in, "
            f"or set it as a GitHub Actions secret."
        )
    return value or ""


ROOT = Path(__file__).resolve().parents[2]
STATE_DIR = ROOT / "state"
OUT_DIR = ROOT / "out"

# All model access goes through OpenRouter, so ids are OpenRouter's (dots, not
# dashes: "claude-opus-5.5", not "claude-opus-5-5") and must be models whose
# supported_parameters include `structured_outputs`. Check before switching:
#   curl -s https://openrouter.ai/api/v1/models | jq '.data[] | select(.id=="<id>")'
OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"

# Clustering is mechanical; writing is the quality-sensitive step. Both are
# overridable so you can trade cost for quality without touching code -
# anthropic/claude-haiku-5.5 is ~40x cheaper and is usually fine for curation.
CURATE_MODEL = env("CURATE_MODEL", "anthropic/claude-opus-5.5")
WRITE_MODEL = env("WRITE_MODEL", "anthropic/claude-opus-5.5")
CURATE_EFFORT = env("CURATE_EFFORT", "medium")
WRITE_EFFORT = env("WRITE_EFFORT", "high")

# How many days a URL stays in state/seen.json before it can resurface.
SEEN_WINDOW_DAYS = 30
# Titles whose normalised token sets overlap by at least this much are the same item.
TITLE_JACCARD_THRESHOLD = 0.72
# Items handed to the clustering call. This is the main cost dial: a candidate
# costs roughly 220 prompt tokens, so 160 is about 35k tokens in. Candidates are
# ranked by tier, weight and votes before being cut, so what gets dropped is
# always the least promising rather than whatever happened to fetch last.
MAX_CANDIDATES = 160
# The card has two shelves, because a fixed count is wrong in both directions: a
# day with nine real stories should not be cut to five, and a quiet day should
# not be padded to five. The model marks each story `lead` or `brief`, and the
# card gives them different amounts of room.
#
# The split is the model's call rather than a score cutoff, because a cutoff
# cannot make it. Measured on two consecutive days:
#
#   2026-10-27  8.2 6.4 5.4 4.8 4.8 4.4 4.4 4.4
#   2026-10-28  9.0 7.6 7.2 6.4 5.8 5.6 5.4 5.4
#
# A threshold of 6.0 selects 2 stories on the 27th and 4 on the 28th; 5.0 selects
# 3 and 8. Importance is scored relative to each day's own pool, not on an
# absolute scale, and the scores bunch - four of the 28th's sat within 0.4 of one
# another - so any arithmetic cut swings the count by several stories.
#
# The shelf sizes come from a render measurement, not a guess. Fit scale against
# the real 2026-10-28 copy, leads using the model's own 160-char detail lines:
#
#   leads  briefs 0    1    2    3
#       3        100%  92%  90%  90%
#       4         88%  82%  80%  78%
#       5         76%  74%  74%  74%
#
# A lead costs about 6 points of scale; a brief costs 1 to 2. That asymmetry is
# the whole point of the second shelf: 3 leads plus 3 briefs puts 6 stories on
# the card at 90%, which is more legible than 5 leads alone at 76%. Nothing here
# can fall below render.card.MIN_SCALE, where the render is rejected outright.
LEADS_MIN = int(env("LEADS_MIN", "3"))
# STORIES_PER_POST was this value's name before the split existed; it is still
# read so an existing deployment's Actions variable keeps working.
LEADS_MAX = int(env("LEADS_MAX", env("STORIES_PER_POST", "5")))
BRIEFS_MAX = int(env("BRIEFS_MAX", "4"))

# --- brand -----------------------------------------------------------------

# The eyebrow on the card and the handle in its footer. Kept here rather than in
# the template so a rename never means touching markup.
BRAND_NAME = env("BRAND_NAME", "AI Signals")
BRAND_HANDLE = env("BRAND_HANDLE", "@aisignals")
# Previous posts shown to the ranker so it will not repeat itself.
HISTORY_LOOKBACK = 14

# --- destinations ----------------------------------------------------------

# Where an approved post goes. Comma-separated so a destination can be added or
# muted without a code change. Defaults to linkedin alone: its permission is
# self-serve, so it works today, while Instagram cannot publish until Meta's App
# Review clears. Set DESTINATIONS=instagram,linkedin once it does.
DESTINATIONS = tuple(
    name.strip().lower() for name in env("DESTINATIONS", "linkedin").split(",") if name.strip()
)

# LinkedIn's versioned APIs require this header on every call. The November 2025
# version is sunset on 2026-11-16, so this must stay recent; bump it and re-run
# scripts/check_linkedin.py when LinkedIn publishes a newer one.
LINKEDIN_API_VERSION = env("LINKEDIN_API_VERSION", "202610")
# LinkedIn allows 3,000 characters of commentary against Instagram's 2,200.
LINKEDIN_COMMENTARY_LIMIT = 3000
# LinkedIn convention is a handful of tags, not Instagram's wall of them.
LINKEDIN_HASHTAG_LIMIT = 5
# Self-serve apps get no refresh token, so the 60-day token is re-minted by
# hand. Start nagging with enough slack to get round to it.
LINKEDIN_TOKEN_WARN_DAYS = 10


# --- source tiers ----------------------------------------------------------
# Sources differ in what they are allowed to justify, not just in how much they
# are worth. A lab's own post *is* the event; a newspaper reports it; a subreddit
# only tells us people are talking about it. Keeping that explicit is what lets
# us add noisy sources to improve ranking without letting them put words on the
# card: verify.py builds its corpus from PRIMARY and REPORTED only, and curate.py
# refuses to cite a SIGNAL item as a story's source.
PRIMARY = "primary"    # the announcement itself - may be stated as fact
REPORTED = "reported"  # journalism - fact, with attribution
SIGNAL = "signal"      # attention only - may raise a rank, never be quoted

# How much one extra independent feed covering the same event is worth on the
# 1-10 importance scale, and how many are counted before the bonus saturates.
# Deliberately small: corroboration breaks ties and lifts a widely-covered
# story, but must not overrule the model's judgement of importance.
CORROBORATION_WEIGHT = 0.4
CORROBORATION_CAP = 5


@dataclass(frozen=True)
class Feed:
    url: str
    source: str
    # Nudges the ranker: a lab's own announcement outranks an aggregator's take on it.
    weight: float = 1.0
    # Hard per-feed item cap. arXiv and Reddit will otherwise drown everything else.
    cap: int = 15
    # What this source is allowed to justify. See the tier notes above.
    tier: str = REPORTED


FEEDS: list[Feed] = [
    # --- Primary: labs and vendors announcing their own work -------------------
    Feed("https://openai.com/news/rss.xml", "OpenAI", 1.6, 8, PRIMARY),
    Feed("https://deepmind.google/blog/rss.xml", "Google DeepMind", 1.5, 8, PRIMARY),
    Feed("https://blog.google/technology/ai/rss/", "Google AI", 1.4, 8, PRIMARY),
    Feed("https://research.google/blog/rss/", "Google Research", 1.3, 6, PRIMARY),
    Feed("https://mistral.ai/rss.xml", "Mistral", 1.3, 6, PRIMARY),
    Feed("https://qwenlm.github.io/blog/index.xml", "Qwen", 1.3, 6, PRIMARY),
    Feed("https://huggingface.co/blog/feed.xml", "Hugging Face", 1.2, 8, PRIMARY),
    Feed("https://allenai.org/rss.xml", "Allen AI", 1.2, 6, PRIMARY),
    Feed("https://engineering.fb.com/category/ai-research/feed/", "Meta Engineering", 1.2, 6, PRIMARY),
    Feed("https://www.microsoft.com/en-us/research/feed/", "Microsoft Research", 1.1, 6, PRIMARY),
    Feed("https://blogs.nvidia.com/feed/", "NVIDIA", 1.1, 6, PRIMARY),

    # Shipped versions are the hardest facts available: a release either exists
    # or it does not, and these Atom feeds are keyless and unthrottled. Capped
    # low because a chatty project would otherwise crowd out everything else.
    Feed("https://github.com/vllm-project/vllm/releases.atom", "vLLM", 1.2, 3, PRIMARY),
    Feed("https://github.com/ollama/ollama/releases.atom", "Ollama", 1.1, 3, PRIMARY),
    Feed("https://github.com/ggml-org/llama.cpp/releases.atom", "llama.cpp", 1.1, 3, PRIMARY),
    Feed("https://github.com/huggingface/transformers/releases.atom", "Transformers", 1.1, 3, PRIMARY),

    # --- Reported: press and analysis -----------------------------------------
    # Anthropic and Meta publish no working public RSS (both 404 as of Oct 2026),
    # so they are covered by targeted Google News queries, which need no key.
    # These are REPORTED, not PRIMARY: the content is other outlets' coverage.
    Feed("https://news.google.com/rss/search?q=Anthropic+Claude+when:2d&hl=en-US&gl=US&ceid=US:en",
         "Anthropic/news", 1.4, 10, REPORTED),
    Feed("https://news.google.com/rss/search?q=%22Meta+AI%22+OR+Llama+when:2d&hl=en-US&gl=US&ceid=US:en",
         "Meta AI/news", 1.2, 8, REPORTED),
    # Techmeme is already clustered by a human editor, which makes it an unusually
    # dense signal of what the tech press collectively decided mattered today.
    Feed("https://www.techmeme.com/feed.xml", "Techmeme", 1.1, 10, REPORTED),
    Feed("https://techcrunch.com/category/artificial-intelligence/feed/", "TechCrunch", 1.0, 12, REPORTED),
    Feed("https://www.theverge.com/rss/ai-artificial-intelligence/index.xml", "The Verge", 1.0, 12, REPORTED),
    Feed("https://feeds.arstechnica.com/arstechnica/technology-lab", "Ars Technica", 0.9, 10, REPORTED),
    Feed("https://www.wired.com/feed/tag/ai/latest/rss", "WIRED", 0.9, 8, REPORTED),
    Feed("https://www.theregister.com/software/ai_ml/headlines.atom", "The Register", 0.9, 8, REPORTED),
    Feed("https://the-decoder.com/feed/", "The Decoder", 0.9, 8, REPORTED),
    Feed("https://www.technologyreview.com/feed/", "MIT Tech Review", 0.9, 6, REPORTED),
    Feed("https://www.theguardian.com/technology/artificialintelligenceai/rss", "The Guardian", 0.8, 6, REPORTED),

    # Analysis and practitioner newsletters: low volume, high signal per item.
    Feed("https://importai.substack.com/feed", "Import AI", 1.2, 4, REPORTED),
    Feed("https://www.interconnects.ai/feed", "Interconnects", 1.2, 4, REPORTED),
    Feed("https://semianalysis.com/feed/", "SemiAnalysis", 1.1, 4, REPORTED),
    Feed("https://simonwillison.net/atom/everything/", "Simon Willison", 1.1, 6, REPORTED),
    Feed("https://www.latent.space/feed", "Latent Space", 1.0, 4, REPORTED),
    Feed("https://news.smol.ai/rss.xml", "AI News", 1.0, 5, REPORTED),

    # --- Signal: what people are talking about --------------------------------
    # These exist to raise a story's rank, never to supply a fact or a citation.
    # Reddit tightened its public .rss to roughly one request per minute in June
    # 2026, so only the single most valuable subreddit is worth the wall clock -
    # a measured run got 429s on three of four before the budget ran out.
    Feed("https://www.reddit.com/r/LocalLLaMA/top/.rss?t=day", "r/LocalLLaMA", 1.1, 12, SIGNAL),
    Feed("https://lobste.rs/t/ai.rss", "Lobsters", 0.8, 10, SIGNAL),
    Feed("https://lemmy.world/feeds/c/technology.xml?sort=Hot", "Lemmy", 0.6, 8, SIGNAL),

    # --- Research: capped hard, it is high-volume and low-newsworthiness ------
    Feed("https://rss.arxiv.org/rss/cs.AI", "arXiv cs.AI", 0.6, 5, PRIMARY),
    Feed("https://rss.arxiv.org/rss/cs.CL", "arXiv cs.CL", 0.6, 5, PRIMARY),
]

# Hosts that 429 when hit in parallel. Requests to these are serialised with a
# gap between them; everything else is fetched concurrently.
RATE_LIMITED_HOSTS = {"reddit.com", "www.reddit.com"}
HOST_DELAY_S = 4.0
# Total seconds the whole throttled group may spend. Only one Reddit feed is left,
# so this is now a backstop against a hang rather than a budget to ration.
RATE_LIMITED_BUDGET_S = 15.0

# Hacker News, via the keyless Algolia search endpoint.
HN_MIN_POINTS = 60
HN_MAX_ITEMS = 20
HN_QUERIES = ["AI", "LLM", "OpenAI", "Anthropic", "machine learning"]

# Hugging Face's Hub API is keyless JSON. Two things it gives that no RSS feed
# does: papers ranked by community upvotes rather than arrival order, and model
# releases on the day they land instead of when a journalist writes them up.
HF_PAPERS_MAX = 6
HF_MODELS_MAX = 6
# Floors that keep the long tail of daily uploads out. Measured against a live
# listing where the genuinely notable entries sat far above these.
HF_MIN_PAPER_UPVOTES = 20
HF_MIN_MODEL_LIKES = 80
HF_MAX_AGE_HOURS = 48
