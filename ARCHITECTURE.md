# Architecture

One daily LinkedIn post about AI news, drafted by two LLM calls and published
only after you tap ✅ on Telegram. No server, no database, no agent framework —
a linear pipeline run twice a day by GitHub Actions cron.

```
                                  06:15 IST  draft.yml
  ┌──────────┐   ┌───────┐   ┌─────────┐   ┌───────┐   ┌────────┐   ┌──────────┐
  │ 39 srcs  │──▶│ dedup │──▶│ curate  │──▶│ write │──▶│ render │──▶│ Telegram │
  │ keyless  │   │ 3 way │   │ LLM #1  │   │ LLM#2 │   │ JPEG   │   │  ✅🔁❌   │
  └──────────┘   └───────┘   └─────────┘   └───────┘   └────────┘   └──────────┘
      ~32s          0.1s        ~40s         ~20s        ~8s             │
                                                                        │ you tap
   ┌────────────────────────────────────────────────────────────────────┘
   │  07:00–09:20 IST  publish.yml, every 10 min
   ▼
  ┌────────────┐   ┌──────────┐   ┌──────────────┐
  │ getUpdates │──▶│ LinkedIn │──▶│ posted.jsonl │
  │  decision  │   │ 3 calls  │   │   history    │
  └────────────┘   └──────────┘   └──────────────┘
```

Why two workflows and not one: **GitHub Actions cannot receive a webhook.** The
draft job asks and exits. A second job wakes up repeatedly and collects the
answer. That single constraint shapes the whole runtime.

---

## 1. Where the news comes from

**39 sources — 37 RSS feeds plus two keyless JSON APIs. Every one is free.** No API key, no signup, no quota
to manage. They are not treated as equals — each carries a *tier* that decides
what it is allowed to do.

| Tier | Meaning | May state a fact? | May be cited? | May raise a rank? |
|---|---|---|---|---|
| `PRIMARY` | The announcement itself | ✅ | ✅ | ✅ |
| `REPORTED` | Journalism about it | ✅ with attribution | ✅ | ✅ |
| `SIGNAL` | People are talking about it | ❌ | ❌ | ✅ |

This is enforced in code, not in a prompt: `verify.py` builds its fact corpus
from PRIMARY + REPORTED only, and `curate.py` refuses to cite a SIGNAL item.

### PRIMARY — 17 feeds, the labs' own words

OpenAI · Google DeepMind · Google AI · Google Research · Mistral · Qwen ·
Hugging Face · Allen AI · Meta Engineering · Microsoft Research · NVIDIA ·
arXiv cs.AI · arXiv cs.CL

Plus **GitHub release feeds** — vLLM, Ollama, llama.cpp, Transformers. A
shipped version is the hardest fact available: the release either exists or it
doesn't.

Plus **Hugging Face Hub JSON** (keyless): papers ranked by community upvotes
(≥20) and models by likes (≥80). This is the one source that surfaces a model
*on the day it lands*, before any journalist writes it up.

### REPORTED — 17 feeds, press and analysis

Techmeme · TechCrunch · The Verge · Ars Technica · WIRED · The Register ·
The Decoder · MIT Tech Review · The Guardian

Analysis newsletters, low volume and high signal per item: Import AI ·
Interconnects · SemiAnalysis · Simon Willison · Latent Space · AI News

**Two Google News queries**, because Anthropic and Meta publish no working
public RSS (both 404 as of Oct 2026):

```
news.google.com/rss/search?q=Anthropic+Claude+when:2d
news.google.com/rss/search?q="Meta AI"+OR+Llama+when:2d
```

### SIGNAL — 3 feeds + Hacker News

`r/LocalLLaMA` · Lobsters · Lemmy, plus **Hacker News** through the keyless
Algolia endpoint (≥60 points, last 36h).

> **Why only one subreddit?** Reddit tightened its public `.rss` to roughly one
> request per minute in June 2026. A measured run got `429` on three of four
> before the time budget ran out. So the single most valuable subreddit stays
> and the rest were cut — they were SIGNAL anyway, so nothing citable was lost.

### What we deliberately don't use

| Rejected | Why |
|---|---|
| **X / Twitter API** | No usable free read tier in 2026; ~$0.005 per post read. Anything trending on X reaches HN and r/LocalLLaMA within hours anyway. |
| **Reddit official API** | Free tier is non-commercial only and registration is gated behind manual approval. The public `.rss` needs none of that. |
| **GDELT** (global news index) | Researched, built, **then measured and removed.** Its corroboration count tracked *wire syndication*, not newsworthiness: the top "story" was one AP markets piece carried by thirteen local papers. 13–15s per request on a global rate limiter, and 250 articles yielded 29 usable. We count our own 37 independent desks instead. |
| **Embedding-based dedup** | Overkill at ~150 items/day. Documented as the upgrade path past ~1,000/day. |

### The cost of all of this

**₹0.** Every source above is keyless and free. The only line item is the LLM.

| Stage | Model | Tokens | Cost |
|---|---|---|---|
| Curate | Haiku 5.5 | 35,766 in / 6,926 out | $0.007 |
| Write | Opus 5.5 | 2,488 in / 2,068 out | $0.051 |
| | | **per day** | **$0.058** |
| | | **per month** | **≈ $1.75** |

Measured, not estimated. Both routed through **OpenRouter** — one key, no
direct provider keys. Model ids are OpenRouter's (`anthropic/claude-opus-5.5`,
dots not dashes) and are overridable via Actions variables, so you can trade
cost for quality without a code change.

---

## 2. How it runs, with real times

### 06:15 IST — `draft.yml`

**Step 1 · Collect (~32 seconds, measured)**

| Source group | Items | Seconds |
|---|---|---|
| RSS (37 feeds, concurrent) | 134 | 28.2 |
| Hacker News | 5 | 2.4 |
| Hugging Face | 7 | 1.0 |
| **raw total** | **146** | **31.6** |

Each feed has a hard `cap` so arXiv or Reddit volume cannot drown the labs.
Reddit is fetched serially with a 4s gap and a 15s total budget; everything
else goes in parallel.

**Lookback window** — not "yesterday", a rolling window per source:

| Source | Looks back |
|---|---|
| RSS | **48 hours** |
| Hugging Face | 48 hours |
| Hacker News | 36 hours |
| Google News | `when:2d` |

48h rather than 24h because The Register's AI section and the weekly analysis
newsletters routinely publish just past the 36h mark and were being dropped
unread. The window is a safety net for slow publishers — it is **not** what
prevents repeats. `state/seen.json` is, with a 30-day memory of every URL.

**Step 2 · Dedup, three stages, cheap → expensive (0.1s + the LLM call)**

1. **Canonical URL hash** — strip `utm_*`, `ref`, fragments, AMP; normalise
   host and trailing slash. Drops exact duplicates and anything in
   `seen.json`.
2. **Title token-set Jaccard ≥ 0.72** — pure stdlib, no model. Collapses
   `"OpenAI launches X"` against `"OpenAI Launches X | TechCrunch"`.
3. **Same-event clustering** — the LLM, below. This is the one that catches the
   same story told in genuinely different words.

146 → 144 after stages 1–2. Then the top **160** candidates by tier × weight ×
votes go to the model; that cap is the main cost dial (~220 prompt tokens each).

**Step 3 · Curate — LLM call #1 (~40s)**

All surviving headlines in, structured clusters out. One call does clustering
*and* ranking. The last 14 posts go in the prompt so it won't re-post
yesterday's story from a new angle.

```json
{
  "headline": "Anthropic previews a personal agent app",
  "member_ids": [12, 47, 88, 103],
  "primary_url": "https://www.anthropic.com",
  "importance": 8,
  "why_it_matters": "First consumer-facing agent product from a frontier lab."
}
```

Then **we** add what the model never sees — `corroboration`, the count of
distinct feeds in the cluster:

```
score = importance + min(corroboration, 5) × 0.4
```

Four independent desks landing on one story is real evidence. The weight is
deliberately small so it breaks ties without overruling judgement.

**Step 4 · Write — LLM call #2 (~20s)**

Takes the top clusters, returns the card copy and the caption. The schema
*requires* every story to carry a `source_url`, and the code rejects the
response if that URL was not in its input:

```
ValueError: Model cited a url that was not in its input
```

Then `verify.py` scans the draft for entities that appear in no PRIMARY or
REPORTED source. It never blocks — it annotates the Telegram message so you
know where to look. This exists because prompt rules alone didn't stop the
model inventing a competitor on 2026-10-23.

**Step 5 · Render (~8s)** — **HTML + CSS, not AI image generation.**

Jinja2 template → headless Chromium → **1080×1350 JPEG at q90**. The text is a
real CSS layout with a `--s` scale variable and a JS auto-fit pass, so long
headlines shrink rather than overflow. The background is a real photograph from
Pexels → Pixabay → Openverse, falling through on failure to a generated mesh
gradient, so the renderer never hard-depends on a third party.

AI image generation was rejected: it costs per image, it can't render text
reliably, and the brand drifts between runs.

**Step 6 · Ask (~2s)** — Telegram `sendPhoto` with an inline keyboard.

**Card on your phone by about 06:18.**

### What's on the card vs. in the caption

| | Card (the image) | Caption |
|---|---|---|
| Hook + subhook | ✅ | — |
| **Leads** (3–5) | category tag + headline + one-line detail + source | headline + detail |
| **Briefs** (0–4) | category tag + headline, under `ALSO TODAY` | headline + detail |
| Source | **name only** (`Anthropic`) | **name + full URL** |
| Hashtags | — | 5, as LinkedIn `{hashtag\|\#\|tag}` templates |

**Two shelves, because a fixed count is wrong in both directions.** A heavy day
should not be cut to five, and a thin day should not be padded to five. The
model marks each story `lead` or `brief`; `write._shelve` forces the result into
the sizes the card can render.

The split is the model's call, not a score cutoff, because a cutoff cannot make
it. Two consecutive days of `score`:

```
2026-10-27   8.2 6.4 5.4 4.8 4.8 4.4 4.4 4.4
2026-10-28   9.0 7.6 7.2 6.4 5.8 5.6 5.4 5.4
```

A threshold of 6.0 selects 2 stories on the 27th and 4 on the 28th; 5.0 selects
3 and 8. Importance is scored relative to each day's own pool rather than on an
absolute scale, and the scores bunch — four of the 28th's sit within 0.4 of one
another — so any arithmetic cut swings the count by several stories.

Shelf sizes come from a render measurement against real copy (fit scale, leads
using the model's own 160-char detail lines):

| leads \ briefs | 0 | 1 | 2 | 3 |
|---|---|---|---|---|
| **3** | 100% | 92% | 90% | 90% |
| **4** | 88% | 82% | 80% | 78% |
| **5** | 76% | 74% | 74% | 74% |

A lead costs ~6 points of scale, a brief 1–2. That asymmetry is the point:
**3 leads + 3 briefs puts 6 stories on the card at 90%, more legible than 5
leads alone at 76%.** Nothing can fall below `MIN_SCALE`, where the render is
rejected outright.

**The left column is a category, not a number.** `01 02 03` carried no
information; `MODEL` / `SECURITY` / `POLICY` uses the same pixels to tell the
reader what kind of news it is. The vocabulary is closed (`models.CATEGORIES`,
`NEWS` as the catch-all) because the column is a fixed 136px — the widest
rendered label is `RESEARCH` at 119px — and a longer label would break the
alignment every headline depends on.

Citations live in the caption only. LinkedIn's `little` text format has exactly
four element types — `TextElement`, `MentionElement`, `HashtagElement`,
`HashtagTemplate` — and **none attaches a URL to custom anchor text**, so a
"source" word cannot be made clickable. Raw URLs auto-linkify, which is why the
caption carries them in full. On Instagram caption links are not clickable at
all.

### 07:00–09:20 IST — `publish.yml`, the approval poller

15 wake-ups: 07:00, 07:10, 07:20 … 09:20. Each is a ~30-second job:

```
read state/tg_offset  →  Telegram getUpdates  →  nothing? print and exit
                                              →  ✅  publish, reply "Posted."
                                              →  ❌  record as skipped
                                              →  🔁  regenerate the draft
```

**Approve at 07:04 and it posts at 07:10** — the next check, not instantly.
That's the price of having no webhook. At most one of the 15 checks ever
publishes; the rest are no-ops.

**09:20 is the last check.** Approve later and the ✅ is not lost (the offset
is persisted) but there is no run left to collect it until tomorrow — trigger
`publish.yml` by hand from the Actions tab.

---

## 3. Publishing

### LinkedIn — live today

Three calls, and LinkedIn takes the **bytes**, not a URL:

```
POST /rest/images?action=initializeUpload   → uploadUrl + image URN
PUT  <uploadUrl>   (the JPEG itself)
POST /rest/posts   → post id in the x-restli-id response header
```

Two things that bite:

**`commentary` is parsed as "little text".** `\ | { } @ [ ] ( ) < > # * _ ~`
are all markup and must be backslash-escaped *even as plain text* — which
matters because `_` and `~` appear in ordinary article URLs. Hashtags are not
`#tag` but a template: `{hashtag|\#|AI}`.

**The post appears as you, not as the page.** `w_member_social` posts to
`urn:li:person:…`. The Company Page exists only because app registration demands
one. Posting as the page needs `w_organization_social` from the Community
Management API - an application-and-review product, but open to all developers
rather than partner-gated (LinkedIn docs li-lms-2026-10). Its Development tier
allows 500 calls/day against the 3 a post costs, and expires after 12 months.

**The token cannot auto-refresh.** LinkedIn grants programmatic refresh tokens
only to approved Marketing Developer Platform partners. A self-serve app gets a
60-day access token and no way to renew it, so it is re-minted by hand with
`scripts/linkedin_auth.py` — roughly **six times a year**. `preflight()` warns
at 10 days left and a weekly workflow nags on Telegram at 14, so an expiry is
never discovered on a morning the post is due.

What LinkedIn does *not* need: App Review (adding the self-serve "Share on
LinkedIn" product is enough), and a public image host.

### Instagram — wired, waiting on Meta

Code is complete and tested. It cannot publish until Meta's App Review clears
`instagram_business_content_publish`, which takes weeks. Meta **fetches** the
image rather than accepting bytes, which is why the public repo matters: it
makes `raw.githubusercontent.com` a free CDN Meta can reach.

Flip it on with one Actions variable, no code change:

```
DESTINATIONS=linkedin,instagram
```

One failing destination never costs you the other — every destination is
attempted, then reported together.

---

## 4. State and stack

No database. Four files committed back to the repo by the workflow:

| Path | Role |
|---|---|
| `state/seen.json` | 30-day URL memory — **this is what prevents repeats** |
| `state/posted.jsonl` | History; also fed to the ranker |
| `state/tg_offset` | Telegram cursor, so a decision is read exactly once |
| `out/<date>/card.jpg` | The card. For Instagram this path *is* the public URL |

| Layer | Choice | Why |
|---|---|---|
| Language | Python 3.12 (3.10-compatible) | — |
| Orchestration | **none** — plain functions | Linear scheduled job with structured outputs. LangGraph/CrewAI sell resumable state and approval loops this doesn't need; Pydantic AI is mid-2.0-beta churn. |
| LLM access | `openai` SDK → OpenRouter | One key. `provider: {require_parameters: true}` is load-bearing — without it OpenRouter may route to an endpoint that silently ignores `response_format`. |
| Schemas | Pydantic → strict JSON schema | No numeric bounds (strict mode rejects them); ranges are stated in descriptions and clamped in code. |
| Runtime | Actions cron, public repo | Free minutes + free image hosting. |
| Rendering | Playwright + Jinja2 | Full CSS control, any webfont, ~2s. |
| Approval | Telegram bot | Free, instant, works from your phone. |
| Tests | pytest, 83 passing | Dedup, canonicalisation, LinkedIn escaping, citation fallback. |

**Known rough edges:** Actions cron fires 5–30 min late under load, which the
45-minute head start absorbs. Google News hands out opaque redirects, so we
cite the publisher domain from the feed's `<source>` element instead — and
prefer a sibling feed's deep link when one exists. Meta's docs contradict
themselves on the daily publish cap, so we read `content_publishing_limit` live
rather than hardcoding it.
