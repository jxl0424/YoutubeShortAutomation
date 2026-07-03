# Trend Discovery & Intelligence Layer (Stage 1)

[![CI](https://github.com/jxl0424/YoutubeShortAutomation/actions/workflows/ci.yml/badge.svg)](https://github.com/jxl0424/YoutubeShortAutomation/actions/workflows/ci.yml)

Stage 1 of a YouTube Shorts automation pipeline. It automatically **discovers,
aggregates, analyzes, scores, and selects** a high-potential Shorts topic before
any content is generated. Built on Clean Architecture + SOLID so new trend
sources and scoring algorithms can be added through configuration without
changing the rest of the pipeline.

```text
Trend Sources → Discovery → Aggregation → Intelligence (LLM) → Scoring → Topic Selection → SelectedTopic → Stage 2
```

## Status

| Step | Feature | State |
|------|---------|-------|
| 1 | Foundations: models, interfaces, config, logging, cache | ✅ done |
| 2 | Trend providers (News RSS, Google Trends RSS, Hacker News, YouTube; Reddit scaffolded) | ✅ done |
| 3 | Aggregation (dedup, cluster, merge) | ✅ done |
| 4 | Intelligence (NVIDIA NIM LLM, structured JSON) | ✅ done |
| 5 | Scoring engine (configurable weighted strategy) | ✅ done |
| 6 | Topic selection (with manual override) | ✅ done |
| 7 | Pipeline facade + CLI | ✅ done |

**Stage 1 is complete** — discovery → aggregation → intelligence → scoring → selection runs end-to-end.

## Stage 2 — AI Shorts Generation

Stage 2 (package `shorts`) turns a Stage 1 `SelectedTopic` into a fully rendered,
upload-ready YouTube Short. It reuses Stage 1's architecture, logging, and
`LLMProvider` interface, and depends only on a `TopicBrief` adapter — never on
Stage 1 internals.

```text
SelectedTopic → script → metadata → voice → visual planning → asset collection
→ validation → assembly → thumbnail → packaging → [upload]  →  output/<slug>/
```

Each stage is an independent, replaceable `PipelineStage`; external services sit
behind provider interfaces (LLM, voice, visual, renderer, thumbnail, storage,
upload) selected by config. **All Stage-2 stages are complete and verified with
full live runs** (NVIDIA NIM → Kokoro → Pexels/Pollinations → MoviePy/FFmpeg →
Pillow).

| Provider | Default | Credentials / setup |
|----------|---------|---------------------|
| Script / Metadata (LLM) | Gemini Flash (fallback Groq/OpenRouter) | `GEMINI_API_KEY` (or set `script.provider: nvidia_nim` to reuse `NVIDIA_API_KEY`) |
| Voice | Kokoro `af_heart` (local, offline) | no key, but one-time setup: `pip install -e ".[kokoro]"` + download `kokoro-v1.0.onnx` and `voices-v1.0.bin` into `models/kokoro/` (kokoro-onnx GitHub release). Zero-setup alternative: `voice.provider: edge_tts` |
| Visuals | Pexels (stock video) → Pollinations (image gen) fallback | Pexels `PEXELS_API_KEY` (free); Pollinations none |
| Render | MoviePy + bundled FFmpeg | none (imageio-ffmpeg) |
| Upload | YouTube Data API v3 (off by default) | `YOUTUBE_CLIENT_SECRETS` + `pip install -e ".[youtube]"` |

```bash
# End-to-end: Stage 1 discovery -> Stage 2 generation:
python -m shorts
# or, after install:  shorts-generate

# Reuse a saved topic instead of re-running discovery:
trend-discovery --json > topic.json
python -m shorts --topic-json topic.json

# Useful flags:
#   --override "Some title"   manually select the topic in discovery
#   --mock-llm                offline mock LLM for discovery
#   --work-dir output/my-run  choose the output folder
#   --json                    print the generated package as JSON
#   --log-level INFO          show structured stage logs
```

Or from Python:

```python
from trend_intelligence.domain.models import SelectedTopic   # from Stage 1
from shorts import ShortsConfig, build_pipeline

pipeline = build_pipeline(ShortsConfig.load())
package = pipeline.generate(selected_topic)   # -> output/<slug>/ with video.mp4, etc.
```

Output folder: `video.mp4`, `thumbnail.png`, `captions.srt`, `metadata.json`,
`description.txt`, `tags.txt`, `script.txt`, `assets/`, `logs/`.

Presentation is config-driven (`config/shorts.yaml` → `video:`): burned-caption
styling (`subtitles.font/font_size/color/position`), 0.3s crossfades between
scenes (`transitions`), and a CC0 lo-fi music bed mixed under the narration at
low volume (`music`, track shipped in `assets/music/`).

## Setup

```bash
python -m venv .venv
.venv\Scripts\activate          # Windows
pip install -e ".[dev]"
cp .env.example .env            # then paste your NVIDIA_API_KEY
```

## Run the pipeline

```bash
# Full run (uses NVIDIA NIM if NVIDIA_API_KEY is set; otherwise falls back to a
# heuristic analysis automatically):
python -m trend_intelligence.cli
# or, after install:  trend-discovery
# or, from a checkout: python scripts/run_discovery.py

# Run without contacting any LLM API:
python -m trend_intelligence.cli --mock-llm

# Useful flags:
#   --override "Some title"   manually select a topic
#   --region US --language en --max 10
#   --json                    print the SelectedTopic as JSON
#   --log-level INFO          show structured stage logs
```

Each enabled provider is queried concurrently; a failing provider is logged and
skipped, so a single outage never breaks a run.

## Run tests & lint

```bash
pytest                 # 244 tests, all external APIs mocked
ruff check .           # lint
ruff format .          # auto-format
```

CI (GitHub Actions) runs lint + format check + tests on every push and PR.

## Enabling YouTube

YouTube Trending is wired up but dormant until you supply a key. Get a free
**YouTube Data API v3** key (Google Cloud Console), then add it to `.env`:

```
YOUTUBE_API_KEY=your-key-here
```

It activates automatically on the next run — no code or config change needed
(`videos.list?chart=mostPopular`, 1 quota unit/call).

## Enabling YouTube upload (Stage 2)

Uploads are off by default. One-time setup (Google Cloud Console):

1. Create a project, then **enable "YouTube Data API v3"** in it (APIs & Services
   → Library). Skipping this yields `403 accessNotConfigured` at upload time.
2. OAuth consent screen: External; **add your own Google account under Test
   users** (Audience tab), or consent fails with `403 access_denied` while the
   app is in Testing status. Add the `youtube.upload` scope (Data Access tab).
3. Credentials → Create OAuth client ID → **Desktop app** → download the JSON to
   `.secrets/client_secrets.json` (gitignored) and set in `.env`:
   `YOUTUBE_CLIENT_SECRETS=.secrets/client_secrets.json`.
4. `pip install -e ".[youtube]"` and set `upload.enabled: true` in
   `config/shorts.yaml`. The shipped config publishes QA-passing shorts to
   `public`; set `privacy: private` for a manual-review workflow instead.

The first upload opens a browser consent once, then caches a refresh token at
`.secrets/youtube_token.json` — later runs are hands-free.

### Upload settings & the pre-publish QA gate

Before every upload, the `pre_publish_qa` stage runs deterministic checks on the
finished package — video integrity, duration/resolution bounds, captions and
thumbnail present, and a valid title/description/tags. A **pass** publishes at
`upload.privacy`; a **failure** downgrades that upload to
`upload.qa_fail_privacy` (`private`) so a bad render becomes a manual-review queue
instead of going live. QA never aborts the run.

Each upload also self-declares the YouTube `status` flags (`videos.insert`):

- **`contains_synthetic_media: true`** — discloses AI/altered content, as YouTube
  requires for realistic synthetic media. On by default for this channel.
- **`made_for_kids: false`** — general-audience news/tech, not child-directed.
- **Age restriction** is intentionally not set: `ytRating` is read-only in the
  Data API and can only be applied manually in YouTube Studio (general-audience
  content needs none).

## Daily scheduled run (Windows)

One short per day, hands-free:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\register_schedule.ps1 -Time "09:00"
Start-ScheduledTask -TaskName "YouTubeShortsDaily"     # optional test trigger
```

The task runs [`scripts/run_daily.ps1`](scripts/run_daily.ps1) as the current
user (while logged on), appending output to `logs/daily-<yyyyMMdd>.log`. Notes:

- **Duplicate protection**: topics generated in the last 14 days are remembered
  in `.state/topic_history.json`; a repeat trend re-selects the next-ranked
  alternative, and a day with nothing new is a logged no-op (exit 0). Bypass
  with `python -m shorts --allow-repeat`.
- **Quota**: one upload costs 1600 of the 10,000 daily YouTube API quota units.
- QA-passing shorts publish at `upload.privacy` (`public` = fully automatic);
  QA failures always land at `qa_fail_privacy` (`private`) for review.
- Remove with `Unregister-ScheduledTask -TaskName "YouTubeShortsDaily"`.

## Configuration

Everything is configured in [`config/default.yaml`](config/default.yaml) — enabled
providers, region/language, cache TTLs, LLM settings, and scoring weights.
**Secrets are never stored in YAML**; they are read from environment variables
(`NVIDIA_API_KEY`, `REDDIT_CLIENT_ID/SECRET`, `YOUTUBE_API_KEY`) declared via
`*_env` keys in the config.

## Layout

```text
src/trend_intelligence/
  domain/        # Pydantic models, interfaces, exceptions (no outward deps)
  config/        # AppConfig (YAML + env secrets)
  logging/       # structlog setup + timing helper
  cache/         # TrendCache interface + LocalFileCache
  providers/     # trend sources (step 2)
  aggregation/   # dedup & clustering (step 3)
  intelligence/  # LLM analysis (step 4)
  scoring/       # scoring engine (step 5)
  selection/     # topic selection (step 6)
  pipeline.py    # composition root (step 7)
```
