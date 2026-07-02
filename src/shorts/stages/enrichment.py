"""Topic enrichment stage (optional).

Grounds the script in reality: fetches recent news headlines for the topic from
Google News RSS (keyless) and exposes them as ``TopicResearch`` facts for the
script prompt — which also lets the LLM size the script to the material.
Best-effort: any failure logs a warning and the pipeline continues un-enriched.
"""

from __future__ import annotations

import html
import re
from collections.abc import Callable
from urllib.parse import quote_plus

from trend_intelligence.logging.setup import get_logger, log_duration

from ..domain.interfaces import PipelineStage
from ..domain.models import TopicResearch

_SEARCH_URL = "https://news.google.com/rss/search?q={query}&hl=en-US&gl=US&ceid=US:en"
_TAG_RE = re.compile(r"<[^>]+>")


class TopicEnricher(PipelineStage):
    name = "topic_enrichment"

    def __init__(
        self,
        *,
        fetch: Callable[[str], str] | None = None,
        timeout: float = 30.0,
    ) -> None:
        self._fetch = fetch
        self._timeout = timeout
        self._logger = get_logger("shorts.enrichment")

    def is_enabled(self, config) -> bool:
        return config.enrichment.enabled

    def run(self, ctx) -> None:
        query = ctx.brief.title
        try:
            with log_duration(self._logger, "topic_enrichment", query=query):
                raw = self._download(query)
                research = self._parse(raw, max_facts=ctx.config.enrichment.max_facts)
        except Exception as exc:
            # Enrichment is a nicety — a script from the brief alone still
            # makes a video, so never fail the run over it.
            self._logger.warning("enrichment_failed", query=query, error=str(exc))
            return

        if not research.facts:
            self._logger.info("enrichment_empty", query=query)
            return
        ctx.research = research
        self._logger.info("enriched", facts=len(research.facts))

    def _download(self, query: str) -> str:
        if self._fetch is not None:
            return self._fetch(query)
        import httpx

        url = _SEARCH_URL.format(query=quote_plus(query))
        response = httpx.get(url, timeout=self._timeout, follow_redirects=True)
        response.raise_for_status()
        return response.text

    @staticmethod
    def _parse(raw: str, *, max_facts: int) -> TopicResearch:
        import feedparser

        feed = feedparser.parse(raw)
        facts: list[str] = []
        dates: list[str] = []
        for entry in feed.entries:
            if len(facts) >= max_facts:
                break
            # Google News titles read "Headline - Publisher"; that suffix is
            # useful grounding (tells the LLM the claim has a named source).
            title = html.unescape(_TAG_RE.sub("", entry.get("title", ""))).strip()
            if not title or title in facts:
                continue
            facts.append(title)
            published = (entry.get("published") or "").strip()
            if published:
                dates.append(published)
        return TopicResearch(facts=facts, dates=dates)
