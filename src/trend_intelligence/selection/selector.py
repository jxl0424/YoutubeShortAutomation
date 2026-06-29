"""Topic selection — picks the final topic for content generation.

Implements :class:`SelectionStrategy`. Automatic selection filters for
monetization safety and a minimum score, then ranks candidates by a selection
score that nudges toward evergreen content (configurable). A manual override by
title always wins and bypasses the filters. The result is a
:class:`SelectedTopic`, the single stable contract handed to Stage 2.
"""

from __future__ import annotations

from collections.abc import Sequence

from ..config.settings import SelectionConfig
from ..domain.exceptions import SelectionError
from ..domain.interfaces import SelectionStrategy
from ..domain.models import RankedTrend, SafetyFlag, SelectedTopic
from ..logging.setup import get_logger

# Safety flags that disqualify a topic from monetization.
_MONETIZATION_UNSAFE = {
    SafetyFlag.MISINFORMATION,
    SafetyFlag.HATE,
    SafetyFlag.ADULT,
    SafetyFlag.VIOLENCE,
}


class TopicSelector(SelectionStrategy):
    def __init__(self, config: SelectionConfig | None = None) -> None:
        self._config = config or SelectionConfig()
        self._logger = get_logger("selection")

    def select(
        self,
        ranked: Sequence[RankedTrend],
        override_title: str | None = None,
    ) -> SelectedTopic:
        if not ranked:
            raise SelectionError("no ranked trends available to select from")

        if override_title:
            return self._select_override(ranked, override_title)

        candidates = self._eligible(ranked)
        if not candidates:
            raise SelectionError(
                "no monetization-safe topic met the selection criteria"
            )

        candidates.sort(key=self._selection_score, reverse=True)
        chosen = candidates[0]
        alternatives = candidates[1 : 1 + self._config.max_alternatives]

        reason = (
            f"Highest selection score ({chosen.final_score:.3f}) among "
            f"{len(candidates)} monetization-safe candidate(s)."
        )
        topic = self._build(chosen, reason, alternatives, manual_override=False)
        self._logger.info(
            "topic_selected",
            title=topic.title,
            score=topic.score,
            candidates=len(candidates),
            cluster_id=chosen.aggregated_trend.cluster_id,
        )
        return topic

    # --- helpers --------------------------------------------------------- #
    def _select_override(
        self, ranked: Sequence[RankedTrend], override_title: str
    ) -> SelectedTopic:
        match = self._find_by_title(ranked, override_title)
        if match is None:
            raise SelectionError(
                f"override title {override_title!r} not found among ranked trends"
            )
        alternatives = [r for r in ranked if r is not match][
            : self._config.max_alternatives
        ]
        topic = self._build(
            match,
            f"Manually overridden to {override_title!r}.",
            alternatives,
            manual_override=True,
        )
        self._logger.info(
            "topic_selected", title=topic.title, manual_override=True
        )
        return topic

    def _eligible(self, ranked: Sequence[RankedTrend]) -> list[RankedTrend]:
        eligible = []
        for item in ranked:
            if item.final_score < self._config.min_score:
                continue
            if self._config.require_monetization_safe and not self._is_safe(item):
                continue
            eligible.append(item)
        return eligible

    def _is_safe(self, item: RankedTrend) -> bool:
        analysis = item.analysis
        if analysis is None:
            return True  # no analysis ⇒ no known safety issue
        if not analysis.is_safe:
            return False
        return not any(f in _MONETIZATION_UNSAFE for f in analysis.safety_flags)

    def _selection_score(self, item: RankedTrend) -> float:
        # Nudge toward evergreen (educational) content to balance pure trending.
        educational = item.analysis.educational_value if item.analysis else 0.5
        return item.final_score + self._config.evergreen_bonus * educational

    @staticmethod
    def _find_by_title(
        ranked: Sequence[RankedTrend], title: str
    ) -> RankedTrend | None:
        needle = title.strip().lower()
        # Exact match on canonical or refined title first, then substring.
        for item in ranked:
            titles = {item.aggregated_trend.canonical_title.lower()}
            if item.analysis:
                titles.add(item.analysis.refined_title.lower())
            if needle in titles:
                return item
        for item in ranked:
            if needle in item.aggregated_trend.canonical_title.lower():
                return item
        return None

    @staticmethod
    def _build(
        chosen: RankedTrend,
        reason: str,
        alternatives: Sequence[RankedTrend],
        *,
        manual_override: bool,
    ) -> SelectedTopic:
        title = (
            chosen.analysis.refined_title
            if chosen.analysis
            else chosen.aggregated_trend.canonical_title
        )
        return SelectedTopic(
            title=title,
            ranked_trend=chosen,
            selection_reason=reason,
            score=chosen.final_score,
            alternatives=list(alternatives),
            manual_override=manual_override,
        )
