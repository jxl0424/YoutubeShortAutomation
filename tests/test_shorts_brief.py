"""Tests for the Stage 1 → Stage 2 adapter (TopicBrief.from_selected_topic)."""

from __future__ import annotations

from shorts.domain.brief import TopicBrief
from trend_intelligence.domain.models import (
    AggregatedTrend,
    ContentCategory,
    RankedTrend,
    ScoreBreakdown,
    SelectedTopic,
    TrendAnalysis,
    TrendSource,
)


def _selected(*, with_analysis: bool = True) -> SelectedTopic:
    aggregated = AggregatedTrend(
        cluster_id="c1",
        canonical_title="AI breakthrough",
        keywords=["ai", "chip"],
        categories=[ContentCategory.TECHNOLOGY],
        sources=[TrendSource.HACKER_NEWS],
        source_count=1,
        popularity_score=0.8,
    )
    analysis = (
        TrendAnalysis(
            cluster_id="c1",
            refined_title="This AI Chip Changes Everything",
            target_audience="tech enthusiasts",
            hooks=["You won't believe this chip"],
            video_angles=["Show the benchmark", "Explain inference"],
            recommended_category=ContentCategory.TECHNOLOGY,
            ai_confidence=0.72,
        )
        if with_analysis
        else None
    )
    ranked = RankedTrend(
        aggregated_trend=aggregated,
        analysis=analysis,
        score_breakdown=ScoreBreakdown(total=0.7),
        final_score=0.7,
        rank=1,
    )
    return SelectedTopic(
        title="This AI Chip Changes Everything",
        ranked_trend=ranked,
        selection_reason="highest score",
        score=0.65,
    )


def test_maps_all_fields_from_analysis():
    brief = TopicBrief.from_selected_topic(_selected())
    assert brief.title == "This AI Chip Changes Everything"
    assert brief.category == "technology"
    assert brief.keywords == ["ai", "chip"]
    assert brief.target_audience == "tech enthusiasts"
    assert brief.hook_idea == "You won't believe this chip"
    assert brief.confidence == 0.72
    assert brief.reasoning == "highest score"
    assert brief.visual_suggestions == ["Show the benchmark", "Explain inference"]


def test_falls_back_when_no_analysis():
    brief = TopicBrief.from_selected_topic(_selected(with_analysis=False))
    assert brief.category == "technology"  # from aggregated categories
    assert brief.confidence == 0.65  # from topic.score
    assert brief.hook_idea is None
    assert brief.target_audience is None
    assert brief.visual_suggestions == []
    assert brief.keywords == ["ai", "chip"]


def test_brief_is_decoupled_from_stage1_shape():
    # The brief exposes only flat fields — no reference to Stage 1 internals.
    brief = TopicBrief.from_selected_topic(_selected())
    assert set(brief.model_dump()) == {
        "title",
        "category",
        "keywords",
        "target_audience",
        "hook_idea",
        "confidence",
        "reasoning",
        "visual_suggestions",
    }
