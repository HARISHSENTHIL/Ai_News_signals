# Source research — free, keyless additions

**Measured 2026-10-28.** Every URL below was fetched live; the numbers are what
came back, not what the sites claim. Baseline being extended: **37 RSS feeds +
2 keyless JSON APIs** (Hacker News Algolia, Hugging Face Hub) = 39 sources.

**Summary: 22 feeds verified live and worth adding — 12 recommended now, 10
optional.** 31 further candidates were fetched and rejected with a measured
reason. **3 of the existing 37 feeds are dead or badly degraded** and one of
them (Qwen) is a frontier lab the pipeline has silently not covered since
September 2025.

The metric that decides everything here is **`ai48`: AI-relevant entries inside
the pipeline's own 48-hour window** (`rss.MAX_AGE_HOURS`). A feed with 50
entries and none in 48h contributes nothing on a given morning. `fresh48` is
total entries in the window; `ai48` is the subset whose title or summary matches
an AI keyword set.

One load-bearing result: **for policy, targeted Google News queries beat every
primary regulator feed.** The Federal Register AI search, whitehouse.gov
presidential actions, NIST news and the EU digital-strategy feed are all live
and all returned **`ai48` = 0**, while `q="AI Act" OR "AI regulation" OR "AI
executive order"` returned **18 fresh entries, 18 of them AI-relevant — 100%
precision**. That is the same pattern as the existing Anthropic and Meta
queries, so it needs no new code.

---

## Recommended additions — tier 1 (add now)

Paste-ready for `config.py` `FEEDS`. Weights and caps follow existing
conventions (labs 1.1–1.6/cap 6–8; Google News 1.2–1.4/cap 8–10; press
0.9–1.1/cap 8–12; analysis 1.0–1.2/cap 4–6).

### PRIMARY

```python
    Feed("https://about.fb.com/news/feed/", "Meta Newsroom", 1.3, 5, PRIMARY),
    Feed("https://nvidianews.nvidia.com/releases.xml", "NVIDIA Newsroom", 1.2, 5, PRIMARY),
    Feed("https://epoch.ai/atom.xml", "Epoch AI", 1.2, 4, PRIMARY),
    Feed("https://metr.org/feed.xml", "METR", 1.2, 3, PRIMARY),
```

| Source | Feed URL | HTTP | entries | newest | fresh48 / ai48 | size | Unique coverage |
|---|---|---|---|---|---|---|---|
| Meta Newsroom | `https://about.fb.com/news/feed/` | 200 | 10 | 2026-10-28 (0.3d) | 1 / 1 | 127KB | **Meta's own announcement channel actually works.** `ARCHITECTURE.md` records "Meta publishes no working public RSS" and falls back to a Google News proxy; `ai.meta.com/blog/rss/` is indeed 404, but `about.fb.com/news/feed/` is live and is where Muse / Llama launches land. Upgrades Meta from REPORTED proxy to PRIMARY. |
| NVIDIA Newsroom | `https://nvidianews.nvidia.com/releases.xml` | 200 | 20 | 2026-10-27 (0.6d) | 3 / 3 | 66KB | Actual press releases (Vera Rubin GA, Oracle multi-gigawatt, Meta Muse collaboration) rather than `blogs.nvidia.com`'s marketing posts. Compute-deal announcements the existing NVIDIA feed misses. |
| Epoch AI | `https://epoch.ai/atom.xml` | 200 | 50 | 2026-10-27 (1.3d) | 1 / 1 | 41KB | Compute/trend datasets nobody else publishes (e.g. "AI Chip Imports explorer"). Quantitative claims with a citable primary source. Note: autodiscovery only — `epoch.ai/rss.xml` and `/blog/rss.xml` are both 404. |
| METR | `https://metr.org/feed.xml` | 200 | 100 | 2026-10-22 (6.0d) | 0 / 0 | **3977KB** | Pre-deployment dangerous-capability evaluations — the only source that reports what a frontier model *can do* rather than that it shipped. **Caveat: 4MB full-content feed for roughly one post a week.** Worth it for the tier, but it is the heaviest fetch in the list. |

### REPORTED

```python
    Feed("https://news.google.com/rss/search?q=DeepSeek+OR+Moonshot+OR+Zhipu+OR+MiniMax+AI+when:2d&hl=en-US&gl=US&ceid=US:en",
         "China labs/news", 1.3, 8, REPORTED),
    Feed("https://news.google.com/rss/search?q=Qwen+OR+Alibaba+AI+model+when:2d&hl=en-US&gl=US&ceid=US:en",
         "Qwen/news", 1.3, 8, REPORTED),
    Feed("https://news.google.com/rss/search?q=%22AI+Act%22+OR+%22AI+regulation%22+OR+%22AI+executive+order%22+when:2d&hl=en-US&gl=US&ceid=US:en",
         "AI policy/news", 1.2, 8, REPORTED),
    Feed("https://www.datacenterdynamics.com/en/rss/", "DCD", 1.0, 6, REPORTED),
    Feed("https://www.nextplatform.com/feed/", "The Next Platform", 1.0, 5, REPORTED),
    Feed("https://pandaily.com/feed/", "Pandaily", 0.9, 6, REPORTED),
    Feed("https://www.scmp.com/rss/36/feed", "SCMP Tech", 0.9, 6, REPORTED),
    Feed("https://www.transformernews.ai/feed", "Transformer", 1.1, 4, REPORTED),
```

| Source | HTTP | entries | newest | fresh48 / ai48 | size | Unique coverage |
|---|---|---|---|---|---|---|
| China labs/news (Google News) | 200 | 59 | 0.0d | 59 / **50** | 74KB | **DeepSeek, Moonshot, Zhipu/z.ai, MiniMax and Baidu Research publish no RSS at all** — confirmed by fetching each site and finding no `rel=alternate` feed link, and `github.com/deepseek-ai/DeepSeek-V3/releases.atom` last fired 2025-06-27 (488d). A Google News query is the only keyless route to the largest uncovered share of real model releases. |
| Qwen/news (Google News) | 200 | 62 | 0.0d | 62 / **58** | 86KB | **Direct replacement for the dead `qwenlm.github.io` feed** (see degraded section). Caught the Alibaba/Cohere "model phoned home to Beijing" story on the day. |
| AI policy/news (Google News) | 200 | 18 | 0.0d | 18 / **18** | 23KB | 100% precision on EU AI Act standards, Italy's implementing decree, US state/midterm regulation. Measured to beat four live government feeds that each scored `ai48`=0. |
| DCD | 200 | 20 | 0.4d | 20 / **12** | **14KB** | **Best yield per byte of anything measured.** Datacenter/compute buildout — TPU-on-OCI, Vera Rubin availability, power deals. Compute capacity is upstream of most AI news and no existing feed covers it. |
| The Next Platform | 200 | 88 | 0.5d | 4 / 3 | 72KB | Deep silicon/systems analysis. Partially replaces the dead SemiAnalysis feed. |
| Pandaily | 200 | 20 | 0.0d | 19 / 9 | 79KB | Chinese model open-sourcing reported on the day ("Ant Group Open-Sources Ling-3.1-flash"). English-language, high AI density. |
| SCMP Tech | 200 | 50 | 0.2d | 13 / 9 | 80KB | Chinese AI ecosystem journalism with Western-readable sourcing (ByteDance robotics, China risk factors in Anthropic's S-1). |
| Transformer | 200 | 20 | 0.6d | 1 / 1 | 715KB | Daily AI-policy-and-safety journalism. Closest thing to a dedicated AI-governance desk; no overlap with the existing newsletter set. |

---

## Recommended additions — tier 2 (optional, all verified live)

Defensible but each is either low-volume, softer, or partially duplicative. Add
as appetite allows.

```python
    # PRIMARY
    Feed("https://machinelearning.apple.com/rss.xml", "Apple ML", 1.1, 4, PRIMARY),
    Feed("https://www.gov.uk/search/all.atom?organisations%5B%5D=ai-security-institute",
         "UK AISI", 1.2, 3, PRIMARY),
    Feed("https://research.ibm.com/rss", "IBM Research", 1.0, 4, PRIMARY),
    Feed("https://news.microsoft.com/source/feed/", "Microsoft Source", 1.0, 4, PRIMARY),
    # REPORTED
    Feed("https://chatgptiseatingtheworld.com/feed/", "AI Litigation", 1.0, 4, REPORTED),
    Feed("https://www.platformer.news/rss/", "Platformer", 1.0, 4, REPORTED),
    Feed("https://spectrum.ieee.org/feeds/topic/artificial-intelligence.rss", "IEEE Spectrum", 0.9, 5, REPORTED),
    Feed("https://rss.arxiv.org/rss/cs.LG", "arXiv cs.LG", 0.6, 5, PRIMARY),
    # SIGNAL
    Feed("https://www.lesswrong.com/feed.xml?view=rss&karmaThreshold=75", "LessWrong", 0.9, 6, SIGNAL),
    Feed("https://www.alignmentforum.org/feed.xml", "Alignment Forum", 0.9, 4, SIGNAL),
```

| Source | HTTP | entries | newest | fresh48 / ai48 | size | Note |
|---|---|---|---|---|---|---|
| Apple ML | 200 | 10 | 2026-10-26 (2.3d) | 0 / 0 | 10KB | Zero Apple coverage today. Low volume — ~2 posts/week — but tiny and genuinely PRIMARY. |
| UK AISI | 200 | 10 | 2026-10-12 (**15.9d**) | 0 / 0 | 7KB | Government eval reports. ~2 items/month, but 7KB and high signal when it fires. **Use the `ai-security-institute` org slug** — the older `ai-safety-institute` slug is live but its newest entry is 2025-02-14 (621 days), a renaming trap. |
| IBM Research | 200 | 20 | 0.8d | 3 / 2 | 15KB | Granite models and quantum. Autodiscovery only (`research.ibm.com/blog/rss` is 404). Quantum-heavy, so cap low. |
| Microsoft Source | 200 | 10 | 0.3d | 3 / 3 | 22KB | Microsoft's *product* AI news (Copilot etc.), which Microsoft Research does not carry. Softer, marketing-adjacent headlines. |
| AI Litigation | 200 | 10 | 0.5d | 1 / 1 | 79KB | Tracks AI copyright/fair-use filings docket by docket ("Anthropic defends fair use in acquiring & using training data"). Nothing in the current 37 covers court filings. |
| Platformer | 200 | 15 | 0.3d | 1 / 1 | 159KB | Platform-policy reporting on AI products. Some posts are subscriber-only; the free ones carry full text in RSS. |
| IEEE Spectrum | 200 | 30 | 0.6d | 3 / 2 | 263KB | Engineering-press angle, rarely duplicated by the consumer tech desks. |
| arXiv cs.LG | 200 | 437 | 0.1d | 437 / 307 | 905KB | **Measured overlap: only 36% of cs.LG ids also appear in cs.AI or cs.CL, so 64% is net new.** Same low-newsworthiness problem as the existing two, so same conventions (0.6 / cap 5). |
| LessWrong (karma ≥75) | 200 | 10 | 0.1d | 8 / 6 | 294KB | Best measured volume of any safety-community source. The karma threshold matters: the `view=curated-rss` variant is 2.4d stale by comparison. SIGNAL — forum posts must not be quotable. |
| Alignment Forum | 200 | 10 | 0.5d | 1 / 1 | 670KB | Alignment research attention. SIGNAL for the same reason, though note some lab research debuts here before it is published anywhere citable. |

---

## Checked and rejected, with the measured reason

### No feed exists at all (verified by fetching the page and finding no `rel=alternate` feed link)

| Candidate | Measurement |
|---|---|
| Anthropic | `anthropic.com/rss.xml`, `/news/rss.xml`, `/engineering/rss.xml` all 404; `alignment.anthropic.com/feed.xml` 404. `ARCHITECTURE.md` remains correct — the Google News proxy is still the only route. |
| xAI | `x.ai/rss.xml`, `/feed.xml`, `/news/rss` all 404; no declared feed on `x.ai/news`. |
| Cohere | `cohere.com/blog/rss.xml` redirects to HTML; `/rss.xml` and `/feed` 404; no declared feed. |
| Groq | `groq.com/feed/` and `/blog/rss.xml` 404; no declared feed. |
| Cerebras | `cerebras.ai/blog/rss.xml` and `/rss.xml` 404; no declared feed. |
| AI21 | `ai21.com/blog/feed/` redirects to the homepage as HTML; no declared feed. |
| DeepSeek / Moonshot / Zhipu (z.ai) / MiniMax / Baidu Research | None declare a feed. `deepseek-ai/DeepSeek-V3/releases.atom` has 1 entry, last 2025-06-27 (488d); its commits atom last fired 2025-08-28 (426d). `MoonshotAI/Kimi-K2` and `zai-org/GLM-4.5` release atoms are valid but **empty — 0 entries**. Covered by the Google News query instead. |
| Apollo Research | `apolloresearch.ai/blog?format=rss` returns HTML (Webflow, no feed). |
| Stanford HAI | `hai.stanford.edu/rss.xml`, `/feed`, `/news/rss.xml` all return the HTML app shell; no declared feed. |
| Runway | `runwayml.com/blog/rss.xml` → 404 at `runway.com/news/rss.xml`. |
| Cursor | `cursor.com/blog/rss.xml` 404. |
| LangChain (blog) | `blog.langchain.dev/rss/` redirects to a Webflow HTML page. |
| OpenRouter | `openrouter.ai/rss.xml` 404, `/announcements/rss.xml` → `/blog/rss.xml` 404. |

### Live but blocked, stale, or low-precision

| Candidate | Measurement |
|---|---|
| FTC press releases | `ftc.gov/feeds/press-releases.xml` → **403** to non-browser agents. |
| Axios Technology | **403** (Cloudflare interstitial). |
| Perplexity blog | `perplexity.ai/hub/rss.xml` → **403** (Cloudflare "Just a moment"). |
| VentureBeat AI | **429 on two separate attempts** — rate-limits bot agents. |
| Microsoft AI blog | `blogs.microsoft.com/ai/feed/` → **410 Gone** (feed retired). |
| Azure blog | Live, 10 entries, **fresh48 = 0**. |
| Google Cloud blog | `cloud.google.com/blog/rss` → 200 but **0 entries parsed**. |
| EU digital-strategy | Live, 10 entries, **ai48 = 0**. `/en/policies/rss.xml` returns 0 entries. |
| EU AI Act newsroom | `artificialintelligenceact.eu/feed/` live but newest entry **2026-08-07 (82 days stale)**. |
| Federal Register AI search | Live, 30 entries, **fresh48 = 1, ai48 = 0**; matches any document that merely mentions AI (top hit: "Critical Material List; Addition of Helium"). A narrowed `PRESDOCU`/`RULE` variant returned **3 entries total, 0 fresh**. |
| whitehouse.gov presidential actions | Live, 30 entries, **fresh48 = 0**; the window is entirely tariff proclamations. |
| NIST news / Taking Measure | Live, 40 entries, **fresh48 = 1, ai48 = 0**. The `?topic=artificial-intelligence` parameter is **ignored** — identical bytes to the unfiltered feed. |
| gov.uk `ai-safety-institute` | Live, 10 entries, newest **2025-02-14 (621 days)** — stale org slug, superseded by `ai-security-institute`. |
| CourtListener search feed | Live and daily (`type=r`, 20 fresh), but **ai48 = 1 of 20** — mostly unrelated dockets that match the phrase. `AI Litigation` above covers the same beat with human filtering. |
| SEC EDGAR | Atom works, but **only with an SEC-style User-Agent containing a contact email**: 403 under the pipeline's `ai-newsletter/0.1` agent, 200 with one. And the entry titles are literally `8-K - Current report` — no content a card could use. Rejected on both counts. |
| EFF Deeplinks | Live, 50 entries, **ai48 = 1 of 5 fresh** — mostly non-AI privacy work. |
| Tom's Hardware | Live and high volume (36 fresh), but **only 14 AI-relevant** in a **957KB** all-topics feed; the rest is consumer PC hardware. DCD + Next Platform give the same coverage at 14KB and 72KB. |
| TechNode | Main feed live and fresh but returns **2000 entries / 11.9MB** per fetch. Its `tag/artificial-intelligence/feed/` is newest **2023-07-05 (1211 days)** and `category/artificial-intelligence/feed/` is 404. Pandaily + SCMP cover China at 1/150th the bytes. |
| Synced (syncedreview) | Live, but newest entry **2025-08-14 (440 days)** — dead. |
| Last Week in AI | Live, newest **2026-10-09 (19d)**; weekly digest. |
| TLDR AI | Live and daily, but each entry is one bundled digest, not one story — nothing a cluster can cite. Pure rehash. |
| MarkTechPost | Live and daily, but SEO-shaped paper rehash ("Meet LEANN: An Open-Source Vector Index that…"). |
| The Information | Live atom, 20 entries, fresh daily — **rejected because it is paywalled**: the card would cite a URL the reader cannot open. |
| Stability AI | Live (autodiscovered `news-updates?format=rss`) but newest **2026-08-25 (64 days)**. |
| Amazon Science | Live, 25 entries, **fresh48 = 0** (newest 4.7d). |
| ElevenLabs | Live and fresh, but content marketing ("How to build an AI voice assistant", "How text to speech technology works"). |
| Replit | Live, **469 entries / 702KB**, fresh48 = 2, and those are SEO pages ("What Is Vibe Coding?"). |
| Databricks | Live, 8 fresh, but product marketing ("How to teach with Databricks Free Edition"). |
| AWS ML blog | Live, 7 fresh / 6 AI, but almost entirely service-release marketing; 651KB. Borderline — excluded to keep vendor-marketing noise out of the 160-candidate budget. |
| NVIDIA developer blog | Live, 6 fresh / 6 AI, but tutorials, not news ("Memory-Enforced GPU Sharing in Kubernetes with CUDA 13.4"). NVIDIA Newsroom carries the announcements instead. |
| Together AI | Live, 100 entries, fresh48 = 1 — infrastructure ops posts. |
| Cloudflare blog | Live, 3 fresh / 1 AI. That one was a real AI security story (KV-cache exposure in a Workers AI model), but 1-in-20 precision at 315KB. |
| Rest of World | Live, 12 entries, fresh48 = 1 — genuinely unique Global South angle but near-weekly cadence. |
| Lawfare | Live but the feed holds only **4 entries**, ai48 = 1. |
| Understanding AI / AI as Normal Technology (ex-AI Snake Oil) | Live but newest 8.7d and 8.5d — weekly essays, fresh48 = 0. |
| Don't Worry About the Vase (Zvi) | Live and daily, but the posts are 600KB weekly roundups of other people's news — rehash by construction. |
| Gary Marcus / Ed Zitron | Opinion columns, not reporting; Zitron's fresh48 = 0. |
| pytorch/pytorch releases.atom | Live and daily, but the entries are **CI tags** (`viable/strict/1793169165`), not releases. |
| langchain releases.atom | Live and daily, but per-package version bumps (`langchain-anthropic==1.7.7`). |
| anthropics/claude-code releases.atom | Live, ~10 patch releases/day (`v2.1.312`) — would burn the cap on noise. |
| sgl-project/sglang releases.atom | Live but **fresh48 = 0** at **1393KB**; duplicates vLLM's coverage of the inference-engine beat. |
| unslothai/unsloth releases.atom | Live, a decent canary for new Chinese model support ("MiniMax-M3.1-Flash"), but **2588KB** per fetch for ~1 entry/48h. |
| Comfy-Org/ComfyUI releases.atom | Live and daily, but titles are bare version numbers — nothing a card can say. |
| modelcontextprotocol spec releases | Live but newest **2026-07-28 (92 days)**. |
| ggml-org/whisper.cpp releases | Live but newest 20.8d. |
| vllm-project/vllm-ascend | Live, newest 14.1d — interesting Huawei-silicon angle, too slow to earn a slot. |
| Sifted | Live and daily, but European startup funding generally, not AI-specific. |
| Hugging Face zh blog | `huggingface.co/blog/zh/feed.xml` → 404. |
| Google News: Cohere/Groq/Cerebras/Mistral | 100 entries, 81 AI — but the window was wall-to-wall Oracle chip-deal coverage already carried by Techmeme, DCD and Next Platform. Matches vendor names inside other companies' stories rather than surfacing vendor announcements. |
| Google News: Nvidia earnings/capex | 54 entries, 50 AI, but ticker-list noise ("Broadcom, Nvidia, Boeing, GM, UPS, JetBlue and More Stocks…"). Same failure mode the GDELT work already measured: volume tracking syndication, not newsworthiness. |
| Google News: AI copyright/lawsuit | 12 entries but celebrity-rights noise (Elvis, Drake, Neil Young). The AI Litigation blog is better targeted. |
| Google News: xAI/Grok | 28–32 entries, ~20 AI, but affiliate SEO dominates ("Grok Spicy Mode: How to Enable It (2026 Guide)") plus crypto cross-matches on "xAI". **Judgement call:** xAI is a frontier lab with literally zero coverage today and no feed of its own, so if you want it, `q="xAI"+Grok+when:2d` at weight 1.0 / cap 6 is the only keyless route — but it is the noisiest thing in this document and is listed here rather than above deliberately. |

### Already rejected upstream, not revisited
X/Twitter API, Reddit's official Data API, GDELT, embedding-based dedup — per
`ARCHITECTURE.md`. (Reddit's public `.rss` stays as-is.)

---

## Existing feeds that are dead or degraded

All 37 returned **HTTP 200** — nothing is hard-broken. But three return only
stale content, so they cost wall-clock and yield nothing inside the 48h window:

| Source | Configured URL | Newest entry | Verdict |
|---|---|---|---|
| **Qwen** | `qwenlm.github.io/blog/index.xml` | **2025-09-23 — 400 days** | **Dead.** The blog moved to `qwen.ai/blog`, which is a JS app with **no feed** (`qwen.ai/blog/rss.xml` and `/blog/feed` both return the HTML shell with a 200). A major lab has been uncovered for over a year. Replace with the `Qwen/news` Google News query above. |
| **SemiAnalysis** | `semianalysis.com/feed/` | **2025-09-16 — 407 days** | **Dead.** Confirmed at source: `wp-json/wp/v2/posts` shows the site's own CMS has nothing newer than 2025-09-16, so this is not a feed bug — public publishing moved elsewhere. The Next Platform + DCD are the closest free replacements. |
| **AI News** (`news.smol.ai`) | `news.smol.ai/rss.xml` | **2026-09-09 — 49 days** | **Degraded.** 716 entries / 2.2MB per fetch for zero fresh items, and the feed contains duplicate entries ("not much happened today" twice). Largest wasted download in the set. |

Four more work but are being fetched through a redirect; pointing `config.py` at
the final URL would save a round trip each run:

| Source | Configured | Resolves to |
|---|---|---|
| Mistral | `mistral.ai/rss.xml` | `mistral.ai/news/rss` |
| Google AI | `blog.google/technology/ai/rss/` | `blog.google/innovation-and-ai/technology/ai/rss/` |
| Latent Space | `www.latent.space/feed` | `latent.space/feed` |
| The Register | `theregister.com/software/ai_ml/headlines.atom` | `api.theregister.com/api/v1/article?...remapper=rss...` |

Also worth knowing, though not broken: **OpenAI's feed ships 1331 entries /
792KB and Hugging Face's 891 / 257KB per fetch** for 7 and a handful of fresh
items respectively. Neither feed supports a size parameter, so this is a
download cost, not a bug — but it is where the 28 seconds of collect time goes.

---

## Candidates that would need a new fetcher

Nothing in the **tier 1 or tier 2 recommendations** needs code — all 22 are
RSS/Atom that `fetch_rss` consumes as-is, including the four Google News
queries, which already hit the existing `news.google.com` branch in
`rss.py:_fetch_one` for publisher extraction and `cite_url`. Three rejected
candidates would need work, listed here so the trade-off is on record:

1. **Per-feed request headers (small, and it unlocks SEC EDGAR).** Measured: the
   SEC serves `browse-edgar?...&output=atom` with 200 to a User-Agent carrying a
   contact email and **403** to the pipeline's `ai-newsletter/0.1 (+https://github.com/)`.
   Sketch: add an optional `headers: tuple[tuple[str, str], ...] = ()` field to
   the `Feed` dataclass and merge it into the per-request headers in
   `_fetch_one`. ~5 lines. **I do not recommend acting on it** — even with
   access, the entries are titled `8-K - Current report` with no body, so the
   payoff is nil. The header hook would be worth adding only if another
   UA-gated source turns up.

2. **A Qwen releases fetcher over the Hugging Face Hub API.** Since Qwen has no
   blog feed, the durable fix is to reuse the existing keyless JSON pattern:
   `GET https://huggingface.co/api/models?author=Qwen&sort=createdAt&direction=-1&limit=20`
   and emit PRIMARY `Item`s for models created inside `HF_MAX_AGE_HOURS`. This
   is a near-copy of `_fetch_models` in `sources/huggingface.py` with an
   `author` filter and a creation-date floor instead of a likes floor, and it
   generalises: the same function parameterised by author would cover DeepSeek,
   Moonshot (`moonshotai`), Zhipu (`zai-org`) and MiniMax, all of which ship to
   the Hub and none of which have RSS. The existing global `models` call only
   catches them once they clear `HF_MIN_MODEL_LIKES` (80), which is days after
   release — an author-scoped call catches them on day one. **This is the single
   highest-value code change available**, and it would make the Google News
   China queries corroboration rather than the sole route.

3. **Cloudflare-gated sources (Perplexity, Axios, FTC) would need a headless
   browser.** Playwright is already a dependency for rendering, so it is
   technically reachable, but fetching feeds through Chromium to defeat a bot
   challenge is fragile, slow, and against the spirit of those sites' blocks.
   Recommend against.

---

## Net effect if tier 1 is adopted

37 → 49 RSS feeds (51 sources with the two JSON APIs), of which 5 are Google
News queries. Summed measured `ai48` across the 12 additions was **165 items**,
which the caps above cut to **at most 68** — against a 160-candidate budget
currently filled by ~146 raw items. Two caveats on that 165: the China and Qwen
queries overlap each other heavily (both carried the Alibaba/Cohere story), and
Google News results overlap the existing press feeds by design — so after
canonical-URL and Jaccard dedup the real increase will be well under 68. The
caps were chosen so the additions compete for the candidate budget rather than
flood it. Retiring the three dead feeds identified above frees ~2.3MB of
download and three HTTP round trips per run, roughly offsetting METR's 4MB.
