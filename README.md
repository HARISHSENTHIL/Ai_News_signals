# AI Signals

An autonomous daily AI-news post for LinkedIn (Instagram when Meta approves it). It
reads 37 free sources, collapses the same story arriving from several of them, writes
a card and a caption, renders a 1080×1350 JPEG, and asks you on Telegram before
anything goes public.

Runs entirely on GitHub Actions. Everything except the LLM is free.

```
sources ──► dedup ──► cluster + rank ──► write ──► render ──► Telegram ──► LinkedIn 
 37 feeds   url/title     LLM call 1    LLM call 2  Playwright   you tap      versioned
 + HN       matching     (OpenRouter)  (OpenRouter)              a button       API
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
`BRAND_NAME` = `AI Signals`, `BRAND_HANDLE` = `@aisignals`,
`STORIES_PER_POST` = `5`, `DESTINATIONS` = `instagram`, `linkedin`, or
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
pytest                                          # 84 tests, no network, no API key
```

`--dry-run` touches no state, so you can run it as often as you like while tuning.

## Schedule

| Workflow | When (UTC) | When (IST) | What |
|---|---|---|---|
| `draft.yml` | 00:45 daily | 06:15 | Build the post, send it to you |
| `publish.yml` | every 10 min, 01:30–03:50 | 07:00–09:20 | Pick up your decision, publish |
| `refresh-token.yml` | Mondays 04:00 | Mon 09:30 | Refresh the 60-day Instagram token |

Two workflows rather than one because Actions cannot receive a webhook: the draft job
exits after asking, and a separate job reads the answer from `getUpdates`.

### Don't trust the clock

GitHub's `schedule` trigger is best-effort, and the docs say so plainly: *"The schedule
event can be delayed during periods of high loads"* and *"if the load is sufficiently
high enough, some queued jobs may be dropped."* Measured here, not guessed:

| Date | `draft` scheduled | `draft` actually ran | Late by |
|---|---|---|---|
| 2026-10-28 | 00:45 UTC | 06:16 UTC | **5h 31m** |

That one delay broke the whole day, because `publish.yml`'s window closes at 03:50 UTC
— two and a half hours *before* the draft it was meant to publish existed. The two
workflows are coupled by wall-clock time with no causal link, so a late draft is an
unrecoverable day. `publish.yml` has never once fired usefully on cron.

**So: treat the schedule as a convenience, not a guarantee.** If no card has arrived by
mid-morning, the automation has missed and the runbook below is the fix. The planned
repair is to merge both workflows into one job that long-polls Telegram for the
decision in-process, so a late start just means a late post instead of no post.

## When automation fails — run it by hand

Everything the workflows do, you can do locally. The whole fallback is five commands.

```bash
cd ~/Documents/PERSONAL/Ai_news_letter
source .venv/bin/activate

git pull --rebase --autostash            # 1. ALWAYS first — see below
python -m newsletter.pipeline draft      # 2. builds the post, sends card to Telegram

#    ... tap a button in Telegram, wait a few seconds ...

python -m newsletter.pipeline publish    # 3. acts on your tap, posts to LinkedIn

git add out/ state/                      # 4. record it
git commit -m "publish $(date -u +%F)"
git push                                 # 5.
```

**Step 1 is not optional.** The workflows commit `state/seen.json` and
`state/posted.jsonl` back to the repo — that state is the database. Skip the pull and
you draft from a stale `seen.json`, risk re-posting stories the bot already used, and
your push collides with the bot's commit.

**Step 5 is not optional either.** Without it the next run has no record that today
happened, and tomorrow's ranker may serve the same five stories again.

### Things that go wrong, and what they mean

| What you see | What it means | Do this |
|---|---|---|
| `no decision yet for <date>` | Telegram hasn't registered your tap yet, or you haven't tapped | Wait ~5s, run `publish` again |
| `no draft for <date> - nothing to publish` | No draft exists locally for today | `git pull`, then run `draft` |
| `nothing new today - every candidate was already seen` | Every story was used on an earlier day | Normal if you re-run days later; otherwise check `state/seen.json` |
| `could not answer callback: query is too old` | Only the button spinner expired | Ignore — the post went out |
| `linkedin ... N days left` where N < 10 | The 60-day token is expiring | `python scripts/linkedin_auth.py` |

### Useful variants

```bash
python -m newsletter.pipeline draft --dry-run        # renders to out/dry-run/, sends nothing,
                                                     # touches no state — safe to repeat
python -m newsletter.pipeline publish --date 2026-10-28   # act on a specific day
python scripts/check_linkedin.py                     # token, scope and URN agree?
python scripts/linkedin_auth.py                      # re-mint the 60-day token
```

### Did the automation actually run?

The Actions tab shows this, but the API is faster and unambiguous — a *scheduled* run
that fired hours late looks identical to an on-time one in the UI:

```bash
curl -s "https://api.github.com/repos/HARISHSENTHIL/Ai_News_signals/actions/runs?per_page=10" \
  | python3 -c "import json,sys
for r in json.load(sys.stdin)['workflow_runs']:
    print(f\"{r['name']:9} #{r['run_number']:<3} {r['event']:17} {str(r['conclusion']):10} {r['created_at']}\")"
```

Compare `created_at` against the cron in the table above. `event=schedule` means cron
fired it; `event=workflow_dispatch` means a human did.

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
  Posting as a *company page* needs `w_organization_social` from the Community
  Management API. That API is **open to all developers** through the standard
  application — not partner-gated — at 500 calls/app/day on the development tier.
  The publisher takes an author URN, so this is a config change plus that approval.
- **A LinkedIn-shaped card.** Both platforms currently get the same 1080×1350
  portrait image. LinkedIn's feed favours 1200×1200 or 1200×628, so the card is
  taller than ideal there. The renderer takes a size, so this is a small change.
