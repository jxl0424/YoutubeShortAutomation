"""Scoring engine — ranks aggregated trends using a pluggable strategy.

Separate from the LLM: the engine combines signals (including the LLM's
estimates) into a final score via the injected :class:`ScoringStrategy` and the
configured weights, then sorts and ranks. Swapping the algorithm means passing a
different strategy — no change here.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from ..domain.interfaces import ScoringStrategy
from ..domain.models import AggregatedTrend, RankedTrend, TrendAnalysis
from ..logging.setup import get_logger


class ScoringEngine:
    def __init__(self, strategy: ScoringStrategy, weights: Mapping[str, float]) -> None:
        self._strategy = strategy
        self._weights = dict(weights)
        self._logger = get_logger("scoring")

    def rank(
        self,
        aggregated: Sequence[AggregatedTrend],
        analyses: Sequence[TrendAnalysis],
    ) -> list[RankedTrend]:
        """Score and rank trends, joining each trend to its analysis by id.

        Trends without a corresponding analysis (e.g. dropped by the LLM as weak)
        are excluded.
        """
        by_id = {t.cluster_id: t for t in aggregated}
        ranked: list[RankedTrend] = []
        for analysis in analyses:
            trend = by_id.get(analysis.cluster_id)
            if trend is None:
                continue
            breakdown = self._strategy.score(trend, analysis, self._weights)
            ranked.append(
                RankedTrend(
                    aggregated_trend=trend,
                    analysis=analysis,
                    score_breakdown=breakdown,
                    final_score=breakdown.total,
                )
            )

        ranked.sort(key=lambda r: r.final_score, reverse=True)
        for position, item in enumerate(ranked, start=1):
            item.rank = position

        if ranked:
            top = ranked[0]
            self._logger.info(
                "scoring_done",
                count=len(ranked),
                top_title=top.aggregated_trend.canonical_title,
                top_score=top.final_score,
                top_breakdown=top.score_breakdown.factors,
            )
        else:
            self._logger.info("scoring_done", count=0)
        return ranked
