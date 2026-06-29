"""Trend aggregation service — provider-independent.

Merges trends discovered by every provider into a deduplicated, clustered set of
:class:`AggregatedTrend` objects:

* normalize titles and tokenize for comparison
* greedily cluster near-duplicate / overlapping titles by token similarity
* merge keywords, categories, URLs and **preserve source attribution**
* compute preliminary aggregate popularity/engagement/growth, rewarding
  cross-source corroboration

This layer knows nothing about specific providers — it operates purely on the
shared domain models.
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Iterable, Sequence

from ..domain.models import (
    AggregatedTrend,
    ContentCategory,
    Trend,
    TrendProviderResult,
    TrendSource,
)
from ..logging.setup import get_logger

_WORD_RE = re.compile(r"[A-Za-z0-9']+")
_STOPWORDS = {
    "the",
    "a",
    "an",
    "and",
    "or",
    "of",
    "to",
    "in",
    "on",
    "for",
    "with",
    "is",
    "are",
    "was",
    "were",
    "be",
    "by",
    "at",
    "as",
    "it",
    "this",
    "that",
    "from",
    "how",
    "why",
    "what",
    "new",
    "your",
    "you",
    "his",
    "her",
}


def _normalize_title(title: str) -> str:
    return " ".join(_WORD_RE.findall(title.lower()))


def _unique(items: Iterable) -> list:
    """Order-preserving de-duplication."""
    return list(dict.fromkeys(items))


class _Cluster:
    """Mutable accumulator for one group of near-duplicate trends. The first
    (most popular) member is the canonical representative."""

    __slots__ = ("key_tokens", "members")

    def __init__(self, trend: Trend, tokens: frozenset[str]) -> None:
        self.key_tokens = tokens
        self.members: list[Trend] = [trend]

    def add(self, trend: Trend) -> None:
        self.members.append(trend)


class TrendAggregator:
    """Aggregates raw provider trends into clustered, deduplicated trends."""

    def __init__(
        self,
        *,
        similarity_threshold: float = 0.6,
        cross_source_bonus: float = 0.08,
        max_aggregated: int = 50,
        min_token_length: int = 3,
    ) -> None:
        self._threshold = similarity_threshold
        self._bonus = cross_source_bonus
        self._max = max_aggregated
        self._min_token_len = min_token_length
        self._logger = get_logger("aggregation")

    # --- public API ------------------------------------------------------ #
    def aggregate(
        self, results: Sequence[TrendProviderResult]
    ) -> list[AggregatedTrend]:
        """Aggregate the trends from successful provider results."""
        trends = [t for r in results if r.success for t in r.trends]
        return self.aggregate_trends(trends)

    def aggregate_trends(self, trends: Sequence[Trend]) -> list[AggregatedTrend]:
        if not trends:
            self._logger.info("aggregation_empty", input=0)
            return []

        # Strongest first so canonical representatives are the highest-signal.
        ordered = sorted(
            trends, key=lambda t: (t.popularity_score, t.title), reverse=True
        )
        clusters = self._cluster(ordered)
        aggregated = sorted(
            (self._build(c) for c in clusters),
            key=lambda a: a.popularity_score,
            reverse=True,
        )

        self._logger.info(
            "aggregation_done",
            input=len(trends),
            clusters=len(aggregated),
            duplicates_removed=len(trends) - len(aggregated),
        )
        return aggregated[: self._max]

    # --- clustering ------------------------------------------------------ #
    def _tokens(self, title: str) -> frozenset[str]:
        return frozenset(
            w
            for w in _normalize_title(title).split()
            if len(w) >= self._min_token_len and w not in _STOPWORDS
        )

    def _similarity(self, a: frozenset[str], b: frozenset[str]) -> float:
        inter = len(a & b)
        if inter == 0:
            return 0.0
        jaccard = inter / len(a | b)
        # Containment helps when a short multi-word phrase is part of a longer
        # one, but is ignored for single-token titles to avoid over-merging on
        # one common word.
        if min(len(a), len(b)) >= 2:
            return max(jaccard, inter / min(len(a), len(b)))
        return jaccard

    def _cluster(self, ordered: Sequence[Trend]) -> list[_Cluster]:
        clusters: list[_Cluster] = []
        for trend in ordered:
            tokens = self._tokens(trend.title)
            best: _Cluster | None = None
            best_sim = 0.0
            if tokens:
                for cluster in clusters:
                    sim = self._similarity(tokens, cluster.key_tokens)
                    if sim > best_sim:
                        best_sim, best = sim, cluster
            if best is not None and best_sim >= self._threshold:
                best.add(trend)
            else:
                clusters.append(_Cluster(trend, tokens))
        return clusters

    # --- merging --------------------------------------------------------- #
    def _build(self, cluster: _Cluster) -> AggregatedTrend:
        members = cluster.members
        canonical = members[0]  # highest popularity (ordered upstream)

        aliases = _unique(
            m.title for m in members if m.title.lower() != canonical.title.lower()
        )
        keywords = _unique(k for m in members for k in m.keywords)[:15]
        categories: list[ContentCategory] = _unique(m.category for m in members)
        sources: list[TrendSource] = _unique(m.source for m in members)
        source_urls = _unique(m.source_url for m in members if m.source_url)

        n_sources = len(sources)
        mean_pop = sum(m.popularity_score for m in members) / len(members)
        mean_eng = sum(m.engagement_score for m in members) / len(members)
        mean_growth = sum(m.growth_score for m in members) / len(members)
        # Reward corroboration across distinct sources.
        popularity = min(1.0, mean_pop + self._bonus * (n_sources - 1))

        discovered = [m.discovered_at for m in members]

        return AggregatedTrend(
            cluster_id=self._cluster_id(canonical.title),
            canonical_title=canonical.title,
            aliases=aliases,
            keywords=keywords,
            categories=categories,
            sources=sources,
            source_urls=source_urls,
            member_trends=members,
            popularity_score=round(popularity, 4),
            engagement_score=round(mean_eng, 4),
            growth_score=round(mean_growth, 4),
            source_count=n_sources,
            first_seen=min(discovered),
            last_seen=max(discovered),
        )

    @staticmethod
    def _cluster_id(title: str) -> str:
        norm = _normalize_title(title)
        digest = hashlib.sha1(norm.encode("utf-8")).hexdigest()[:8]
        slug = re.sub(r"[^a-z0-9]+", "-", norm).strip("-")[:40] or "trend"
        return f"{slug}-{digest}"
