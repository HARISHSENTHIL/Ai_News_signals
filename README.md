# AI Daily

An autonomous daily AI-news post for Instagram. It reads ~20 free sources, collapses
the same story arriving from several of them, writes a card and a caption, renders a
1080×1350 JPEG, and asks you on Telegram before anything goes public.

Runs entirely on GitHub Actions. Everything except the LLM is free.

```
sources ──► dedup ──► cluster + rank ──► write ──► render ──► Telegram ──► Instagram
 20 feeds   url/title     LLM call 1    LLM call 2  Playwright   you tap      Graph API
 + HN       matching     (OpenRouter)  (OpenRouter)              a button
```

## Cost

| | |
|---|---|
| LLM | **$6.40/month** all-Opus, or **$1.60** with Haiku curation — measured, not estimated |
| Sources | $0 — every feed is keyless |
| Hosting | $0 — GitHub Actions, public repo |
| Images | $0 — keyless Openverse, or a generated gradient |

Measured on a real run (2026-10-23): curation is 21.5k in / 3.9k out, writing is
2.0k in / 2.0k out. Curation is where the money goes, and it is the mechanical
step — setting `CURATE_MODEL=anthropic/claude-haiku-5.5` cuts the bill by 75% and
leaves the quality-sensitive writing call on Opus.

## Why these sources

The X API has no usable free read tier (pay-per-use, ~$0.005/read), and Reddit's
official Data API free tier is non-commercial with gated registration. Reddit's
**public `.rss` feeds** need no key at all, and anything trending on X reaches
Hacker News or the AI subreddits within hours. Anthropic and Meta publish no working
public RSS, so they are covered by keyless Google News queries.

## Why the model does the deduplication

Hashing (MinHash/SimHash) only catches near-verbatim reposts. Six outlets reporting
one announcement in six different wordings share too few tokens to match — see
`tests/test_source_overlap.py`, which pins this down with real captured headlines.
So the cheap stages run first (canonical URL, then title overlap), and only the
survivors — about 100 items — go to one model call that clusters *and* ranks them
for roughly two cents. Embeddings plus graph clustering would be the move past
~1,000 items/day; at this volume they are strictly worse.

## Setup

### 1. Repo

Make it **public**. That gives unlimited Actions minutes and, more importantly, free
public image hosting — Instagram fetches the card from a URL itself, so the JPEG has
to be publicly reachable. Secrets live in Actions secrets, not in the code.

### 2. Telegram (the approval gate)

1. Message [@BotFather](https://t.me/BotFather), `/newbot`, keep the token.
2. Send your new bot any message.
3. Open `https://api.telegram.org/bot<TOKEN>/getUpdates` and read `message.chat.id`.

### 3. Meta (Instagram publishing)

Nothing else blocks on this — the pipeline runs end to end to Telegram without it.

1. Instagram app → Settings → Account type → switch to **Professional**.
2. [developers.facebook.com](https://developers.facebook.com) → create an app →
   add the **Instagram** product → Instagram API with Instagram Login.
3. Request `instagram_business_basic` and `instagram_business_content_publish`,
   then submit for **App Review**. This takes days to weeks.
4. Generate a long-lived token and note your Instagram user id.
5. `python scripts/check_ig.py` — verifies the token, the account type and the quota.
6. `python scripts/check_ig.py --container` — proves Meta can actually fetch your
   card URL. This is the step most likely to fail. It never publishes anything.

### 3b. LinkedIn (no App Review)

Worth doing first. LinkedIn's `w_member_social` is self-serve, so this can be
live in about twenty minutes while Instagram is still queued behind Meta.

1. [linkedin.com/developers/apps](https://www.linkedin.com/developers/apps) →
   create an app. It must be linked to a LinkedIn **company page**, which you
   can create in a minute and never post to — it is only there to own the app.
2. Products tab → add **Share on LinkedIn** (grants `w_member_social`) and
   **Sign In with LinkedIn using OpenID Connect** (lets us read your person
   URN). Both are instant.
3. Auth tab → add the redirect URL `http://localhost:8765/callback`, and copy the
   client id and secret into `.env`.
4. `python scripts/linkedin_auth.py` — opens a browser, you approve once, and it
   prints `LINKEDIN_ACCESS_TOKEN`, `LINKEDIN_PERSON_URN` and
   `LINKEDIN_TOKEN_EXPIRES_AT`.
5. `python scripts/check_linkedin.py` — confirms the token, the scope and the URN
   agree. `--caption` also shows the escaped commentary.

**The one ongoing chore.** LinkedIn issues programmatic refresh tokens only to
approved Marketing Developer Platform partners, so a self-serve app's 60-day
token cannot be renewed in the background the way the Instagram one can. Step 4
has to be repeated about six times a year. `preflight()` warns for the last ten
days and `refresh-token.yml` cannot help; this is the honest cost of skipping
App Review.

### 4. Background images (nothing required)

Providers are tried in order; the first that answers wins:

| | Key | Notes |
|---|---|---|
| Pexels | required | Best quality. **Key issuance was paused as of Oct 2026** |
| Pixabay | required | [Open signup](https://pixabay.com/api/docs/), commercial use, no attribution |
| Openverse | **none** | Keyless. Restricted to CC0/public-domain so it is safe on a brand account |
| Gradient | — | Always works |

With no keys set at all you still get real photos, via Openverse. Add a Pixabay key
if you want a bigger, better-curated pool.

Openverse carries a lot of NonCommercial and ShareAlike work, which is the wrong fit
for a branded post that overlays text on it. We request CC0/public-domain only and
accept the smaller pool.

### 5. Secrets and variables

Repo → Settings → Secrets and variables → Actions.

**Secrets:** `OPENROUTER_API_KEY`, `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`,
`PIXABAY_API_KEY` (optional), `IG_USER_ID`, `IG_ACCESS_TOKEN`, `META_APP_ID`, `META_APP_SECRET`,
`SECRETS_PAT` (a fine-grained PAT with `secrets: write`, only for token refresh),
`LINKEDIN_ACCESS_TOKEN`, `LINKEDIN_PERSON_URN`.

**Variables:** `PUBLIC_BASE_URL` = `https://raw.githubusercontent.com/<you>/<repo>/main`,
`IG_HANDLE` = `@yourhandle`, `DESTINATIONS` = `instagram`, `linkedin`, or
`instagram,linkedin`, `LINKEDIN_TOKEN_EXPIRES_AT` = the date `linkedin_auth.py`
printed. Optionally `CURATE_MODEL` / `WRITE_MODEL` to override the default
`anthropic/claude-opus-5.5`.

`DESTINATIONS` is what lets LinkedIn run alone until Instagram is approved. One
destination failing never costs you the other — both are attempted and the
Telegram reply says what landed and what did not.

## Running it

```bash
pip install -e ".[dev]"
playwright install chromium
cp .env.example .env          # then fill it in

python -m newsletter.pipeline draft --dry-run   # renders to out/dry-run/, sends nothing
python -m newsletter.pipeline draft             # real run: Telegram, state, commit
python -m newsletter.pipeline publish           # acts on whichever button you pressed
pytest                                          # 35 tests, no network, no API key
```

`--dry-run` touches no state, so you can run it as often as you like while tuning.

## Schedule

| Workflow | When (UTC) | When (IST) | What |
|---|---|---|---|
| `draft.yml` | 00:45 daily | 06:15 | Build the post, send it to you |
| `publish.yml` | every 10 min, 01:30–03:50 | 07:00–09:20 | Pick up your decision, publish |
| `refresh-token.yml` | Mondays 04:00 | Mon 09:30 | Refresh the 60-day Instagram token |

The card reaches you around 06:18 IST and the first publish check runs at 07:00,
so a post approved over breakfast goes live on the hour. The last check is 09:20;
approve after that and nothing posts until you trigger `publish.yml` by hand.

Two workflows rather than one because Actions cannot receive a webhook: the draft job
exits after asking, and a separate job reads the answer from `getUpdates`.

Actions cron fires 5–30 minutes late under load. Don't promise an exact post time.

## Tuning

Nearly everything lives in `src/newsletter/config.py`: the feed list with per-source
weights and caps, the dedup thresholds, `STORIES_PER_POST`, and the model plus effort
level for each call. Any OpenRouter model works as long as its `supported_parameters`
include `structured_outputs` — check before switching:
`curl -s https://openrouter.ai/api/v1/models | jq '.data[] | select(.id=="<id>")'`. Voice and editorial judgement live in the `SYSTEM` prompts in
`curate.py` (what counts as important) and `write.py` (how it reads).

The card layout is `src/newsletter/render/template.html.j2`. Copy length varies run to
run, so the renderer measures the content and shrinks it until it fits rather than
assuming a fixed amount of text.

## Not built yet

- **Carousel.** The template system is built for it; the renderer is single-card.
- **LinkedIn company pages.** Posting as *you* is built and needs no review.
  Posting as a *company page* needs `w_organization_social`, which comes through
  the partner-gated Community Management API — a different application entirely.
- **A LinkedIn-shaped card.** Both platforms currently get the same 1080×1350
  portrait image. LinkedIn's feed favours 1200×1200 or 1200×628, so the card is
  taller than ideal there. The renderer takes a size, so this is a small change.
