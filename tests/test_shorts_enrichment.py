"""Tests for the Topic Enrichment stage (Google News RSS mocked via fetch)."""

from __future__ import annotations

from shorts.config.settings import ShortsConfig
from shorts.domain.brief import TopicBrief
from shorts.pipeline import PipelineContext
from shorts.stages.enrichment import TopicEnricher

_RSS = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0"><channel><title>news</title>
<item>
  <title>PlayStation ends disc production &amp; more - The Verge</title>
  <pubDate>Wed, 01 Jul 2026 10:00:00 GMT</pubDate>
</item>
<item>
  <title>Sony confirms the 2028 date - IGN</title>
  <pubDate>Tue, 30 Jun 2026 09:00:00 GMT</pubDate>
</item>
<item>
  <title>PlayStation ends disc production &amp; more - The Verge</title>
</item>
<item>
  <title>Collectors react to the announcement - Reuters</title>
</item>
</channel></rss>
"""


def _ctx(tmp_path, *, enabled=True, max_facts=5):
    config = ShortsConfig()
    config.enrichment.enabled = enabled
    config.enrichment.max_facts = max_facts
    return PipelineContext(
        brief=TopicBrief(title="PlayStation disc production", category="tech"),
        config=config,
        work_dir=tmp_path,
    )


def test_parses_headlines_into_research(tmp_path):
    seen = {}

    def fetch(query):
        seen["query"] = query
        return _RSS

    ctx = _ctx(tmp_path)
    TopicEnricher(fetch=fetch).run(ctx)

    assert seen["query"] == "PlayStation disc production"
    research = ctx.research
    assert research is not None
    # Duplicate headline dropped; entities unescaped.
    assert research.facts == [
        "PlayStation ends disc production & more - The Verge",
        "Sony confirms the 2028 date - IGN",
        "Collectors react to the announcement - Reuters",
    ]
    assert research.dates == [
        "Wed, 01 Jul 2026 10:00:00 GMT",
        "Tue, 30 Jun 2026 09:00:00 GMT",
    ]


def test_max_facts_caps_results(tmp_path):
    ctx = _ctx(tmp_path, max_facts=1)
    TopicEnricher(fetch=lambda q: _RSS).run(ctx)
    assert len(ctx.research.facts) == 1


def test_zero_max_facts_leaves_context_unenriched(tmp_path):
    ctx = _ctx(tmp_path, max_facts=0)
    TopicEnricher(fetch=lambda q: _RSS).run(ctx)
    assert ctx.research is None


def test_fetch_failure_never_fails_the_run(tmp_path):
    def broken(query):
        raise ConnectionError("dns down")

    ctx = _ctx(tmp_path)
    TopicEnricher(fetch=broken).run(ctx)  # must not raise
    assert ctx.research is None


def test_empty_feed_leaves_context_unenriched(tmp_path):
    ctx = _ctx(tmp_path)
    TopicEnricher(fetch=lambda q: "<rss><channel></channel></rss>").run(ctx)
    assert ctx.research is None


def test_is_enabled_follows_config(tmp_path):
    stage = TopicEnricher(fetch=lambda q: _RSS)
    assert stage.is_enabled(_ctx(tmp_path, enabled=True).config) is True
    assert stage.is_enabled(_ctx(tmp_path, enabled=False).config) is False
    assert stage.is_enabled(ShortsConfig()) is False  # code default: off
