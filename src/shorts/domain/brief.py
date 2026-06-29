"""Topic brief — the anti-corruption boundary between Stage 1 and Stage 2.

Stage 1's ``SelectedTopic`` is a nested object (``ranked_trend → aggregated_trend
/ analysis``). The rest of Stage 2 must not depend on that shape, so this module
is the *only* place that imports Stage 1. It flattens a ``SelectedTopic`` into a
clean ``TopicBrief`` carrying exactly the fields the generator needs.

If Stage 1's internals ever change, only this adapter changes.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from trend_intelligence.domain.models import ContentCategory, SelectedTopic


class TopicBrief(BaseModel):
    """Flat, generator-facing view of a selected topic."""

    model_config = ConfigDict(extra="forbid")

    title: str
    category: str
    keywords: list[str] = Field(default_factory=list)
    target_audience: str | None = None
    hook_idea: str | None = None
    confidence: float = Field(default=0.5, ge=0.0, le=1.0)
    reasoning: str | None = None
    visual_suggestions: list[str] = Field(default_factory=list)

    @classmethod
    def from_selected_topic(cls, topic: SelectedTopic) -> TopicBrief:
        """Map Stage 1's ``SelectedTopic`` onto the Stage 2 brief."""
        ranked = topic.ranked_trend
        aggregated = ranked.aggregated_trend
        analysis = ranked.analysis

        if analysis is not None:
            category = analysis.recommended_category.value
            target_audience = analysis.target_audience
            hook_idea = analysis.hooks[0] if analysis.hooks else None
            confidence = analysis.ai_confidence
            visual_suggestions = list(analysis.video_angles)
        else:
            category = (
                aggregated.categories[0].value
                if aggregated.categories
                else ContentCategory.OTHER.value
            )
            target_audience = None
            hook_idea = None
            confidence = topic.score
            visual_suggestions = []

        return cls(
            title=topic.title,
            category=category,
            keywords=list(aggregated.keywords),
            target_audience=target_audience,
            hook_idea=hook_idea,
            confidence=confidence,
            reasoning=topic.selection_reason,
            visual_suggestions=visual_suggestions,
        )
