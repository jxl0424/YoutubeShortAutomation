# Trend Discovery & Intelligence Layer (Stage 1)

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

## Run tests

```bash
pytest
```

## Enabling YouTube

YouTube Trending is wired up but dormant until you supply a key. Get a free
**YouTube Data API v3** key (Google Cloud Console), then add it to `.env`:

```
YOUTUBE_API_KEY=your-key-here
```

It activates automatically on the next run — no code or config change needed
(`videos.list?chart=mostPopular`, 1 quota unit/call).

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
