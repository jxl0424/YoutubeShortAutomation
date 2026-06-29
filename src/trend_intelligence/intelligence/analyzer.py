"""Trend analyzer — orchestrates the LLM intelligence stage.

Owns the prompts and the call/retry/validation logic; the LLM provider is
injected so it can be swapped freely. Output is always strict, structured
:class:`TrendAnalysis` objects — never free-form text. If the LLM cannot
produce valid output after retries, a deterministic heuristic fallback keeps the
pipeline running.
"""

from __future__ import annotations

from collections.abc import Sequence

from ..domain.interfaces import LLMProvider
from ..domain.models import AggregatedTrend, ContentCategory, TrendAnalysis
from ..logging.setup import get_logger, log_duration
from .prompts import SYSTEM_PROMPT, build_user_prompt
from .schemas import TrendAnalysisBatch


class TrendAnalyzer:
    def __init__(self, llm: LLMProvider, *, max_retries: int = 2) -> None:
        self._llm = llm
        self._max_retries = max_retries
        self._logger = get_logger("intelligence")

    def analyze(
        self, trends: Sequence[AggregatedTrend]
    ) -> list[TrendAnalysis]:
        if not trends:
            return []

        valid_ids = {t.cluster_id for t in trends}
        system = SYSTEM_PROMPT
        user = build_user_prompt(trends)

        with log_duration(self._logger, "llm_analysis", trend_count=len(trends)):
            batch = self._call_with_retry(system, user)

        if batch is None:
            return self._fallback(trends)

        seen: set[str] = set()
        analyses: list[TrendAnalysis] = []
        for item in batch.analyses:
            if item.cluster_id not in valid_ids or item.cluster_id in seen:
                continue  # ignore hallucinated or duplicate cluster_ids
            seen.add(item.cluster_id)
            analyses.append(TrendAnalysis.model_validate(item.model_dump()))

        kept = [a for a in analyses if a.keep]
        self._logger.info(
            "llm_analysis_result",
            input=len(trends),
            returned=len(analyses),
            kept=len(kept),
            removed=len(trends) - len(kept),
        )
        return kept

    # --- internals ------------------------------------------------------- #
    def _call_with_retry(
        self, system: str, user: str
    ) -> TrendAnalysisBatch | None:
        last_error: Exception | None = None
        for attempt in range(self._max_retries + 1):
            try:
                result = self._llm.generate_structured(
                    system=system, user=user, schema=TrendAnalysisBatch
                )
                if not isinstance(result, TrendAnalysisBatch):
                    raise TypeError(
                        f"expected TrendAnalysisBatch, got {type(result).__name__}"
                    )
                return result
            except Exception as exc:
                last_error = exc
                self._logger.warning(
                    "llm_attempt_failed", attempt=attempt + 1, error=str(exc)
                )
        self._logger.error("llm_failed", error=str(last_error))
        return None

    def _fallback(
        self, trends: Sequence[AggregatedTrend]
    ) -> list[TrendAnalysis]:
        """Heuristic analyses used when the LLM is unavailable/invalid."""
        self._logger.warning("llm_fallback", count=len(trends))
        return [
            TrendAnalysis(
                cluster_id=t.cluster_id,
                keep=True,
                refined_title=t.canonical_title,
                estimated_audience_interest=t.popularity_score,
                recommended_category=(
                    t.categories[0] if t.categories else ContentCategory.OTHER
                ),
                ai_confidence=0.2,  # low — this is a heuristic, not the model
            )
            for t in trends
        ]
