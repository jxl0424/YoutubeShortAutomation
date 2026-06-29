"""Default weighted scoring strategy.

Derives a 0-1 signal for each configured factor from an aggregated trend and its
LLM analysis, then combines them using the configurable weights. The result is a
transparent :class:`ScoreBreakdown` (per-factor weighted contributions + total).
The whole strategy is replaceable via the :class:`ScoringStrategy` interface.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime

from ..domain.interfaces import ScoringStrategy
from ..domain.models import (
    AggregatedTrend,
    ContentCategory,
    ScoreBreakdown,
    TrendAnalysis,
    TrendSource,
)

_RECENCY_WINDOW_HOURS = 48.0


def _clamp(value: float) -> float:
    return max(0.0, min(1.0, value))


def _recency(timestamp: datetime, window_hours: float = _RECENCY_WINDOW_HOURS) -> float:
    age_hours = (datetime.now(UTC) - timestamp).total_seconds() / 3600
    return _clamp(1.0 - age_hours / window_hours)


class WeightedScoringStrategy(ScoringStrategy):
    def score(
        self,
        trend: AggregatedTrend,
        analysis: TrendAnalysis | None,
        weights: Mapping[str, float],
    ) -> ScoreBreakdown:
        signals = self._signals(trend, analysis)

        contributions: dict[str, float] = {}
        weighted_sum = 0.0
        total_weight = 0.0
        for factor, weight in weights.items():
            signal = _clamp(signals.get(factor, 0.0))
            contributions[factor] = round(weight * signal, 6)
            weighted_sum += weight * signal
            total_weight += weight

        total = weighted_sum / total_weight if total_weight > 0 else 0.0
        return ScoreBreakdown(factors=contributions, total=round(_clamp(total), 4))

    def _signals(
        self, trend: AggregatedTrend, analysis: TrendAnalysis | None
    ) -> dict[str, float]:
        # LLM-derived factors fall back to neutral defaults when no analysis.
        ai_confidence = analysis.ai_confidence if analysis else 0.3
        visual = analysis.visual_potential if analysis else 0.5
        educational = analysis.educational_value if analysis else 0.5
        entertainment = analysis.entertainment_value if analysis else 0.5
        interest = (
            analysis.estimated_audience_interest if analysis else trend.popularity_score
        )

        is_news = (
            TrendSource.NEWS_RSS in trend.sources
            or ContentCategory.NEWS in trend.categories
        )

        return {
            "search_popularity": trend.popularity_score,
            "growth_rate": trend.growth_score,
            "recent_activity": _recency(trend.last_seen),
            "engagement": trend.engagement_score,
            # Fewer corroborating sources ⇒ less saturated ⇒ less competition.
            "competition": 1.0 - min(1.0, (trend.source_count - 1) / 5),
            "freshness": _recency(trend.first_seen),
            "news_relevance": 1.0 if is_news else 0.3,
            "uniqueness": 1.0 - min(1.0, (trend.source_count - 1) / 8),
            "visual_potential": visual,
            "educational_value": educational,
            "entertainment_value": entertainment,
            "estimated_virality": (interest + entertainment + trend.growth_score) / 3,
            "ai_confidence": ai_confidence,
        }
