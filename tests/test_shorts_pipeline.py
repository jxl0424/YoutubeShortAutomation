"""Tests for the ShortsPipeline orchestrator with mock stages (no real work)."""

from __future__ import annotations

from pathlib import Path

import pytest

from shorts.config.settings import ShortsConfig
from shorts.domain.exceptions import ShortsPipelineError
from shorts.domain.interfaces import PipelineStage
from shorts.domain.models import GeneratedShort
from shorts.pipeline import PipelineContext, ShortsPipeline
from trend_intelligence.domain.models import (
    AggregatedTrend,
    ContentCategory,
    RankedTrend,
    ScoreBreakdown,
    SelectedTopic,
    TrendAnalysis,
    TrendSource,
)


def _selected() -> SelectedTopic:
    aggregated = AggregatedTrend(
        cluster_id="c1",
        canonical_title="Topic",
        keywords=["k"],
        categories=[ContentCategory.TECHNOLOGY],
        sources=[TrendSource.HACKER_NEWS],
        source_count=1,
    )
    analysis = TrendAnalysis(
        cluster_id="c1",
        refined_title="Punchy Title",
        recommended_category=ContentCategory.TECHNOLOGY,
    )
    ranked = RankedTrend(
        aggregated_trend=aggregated,
        analysis=analysis,
        score_breakdown=ScoreBreakdown(total=0.5),
        final_score=0.5,
    )
    return SelectedTopic(
        title="Punchy Title", ranked_trend=ranked, selection_reason="r", score=0.5
    )


class _Stage(PipelineStage):
    def __init__(
        self,
        name,
        order,
        *,
        enabled=True,
        sets_package=False,
        captures=None,
        fail=False,
    ):
        self.name = name
        self._order = order
        self._enabled = enabled
        self._sets_package = sets_package
        self._captures = captures
        self._fail = fail

    def is_enabled(self, config):
        return self._enabled

    def run(self, ctx: PipelineContext) -> None:
        self._order.append(self.name)
        if self._captures is not None:
            self._captures.append(ctx)
        if self._fail:
            raise RuntimeError("boom")
        if self._sets_package:
            ctx.package = GeneratedShort(output_dir=ctx.work_dir)


def _pipeline(stages):
    return ShortsPipeline(stages, ShortsConfig())


def test_runs_stages_in_order_and_returns_package():
    order: list[str] = []
    stages = [
        _Stage("script", order),
        _Stage("packaging", order, sets_package=True),
    ]
    result = _pipeline(stages).generate(_selected())
    assert order == ["script", "packaging"]
    assert isinstance(result, GeneratedShort)


def test_disabled_stage_is_skipped():
    order: list[str] = []
    stages = [
        _Stage("enrichment", order, enabled=False),
        _Stage("packaging", order, sets_package=True),
    ]
    _pipeline(stages).generate(_selected())
    assert order == ["packaging"]


def test_stage_failure_is_wrapped_with_name():
    order: list[str] = []
    stages = [_Stage("voice", order, fail=True)]
    with pytest.raises(ShortsPipelineError) as exc:
        _pipeline(stages).generate(_selected())
    assert exc.value.stage == "voice"


def test_missing_package_raises():
    order: list[str] = []
    stages = [_Stage("script", order)]  # never sets ctx.package
    with pytest.raises(ShortsPipelineError):
        _pipeline(stages).generate(_selected())


def test_brief_is_derived_from_selected_topic():
    captures: list[PipelineContext] = []
    order: list[str] = []
    stages = [
        _Stage("capture", order, captures=captures),
        _Stage("packaging", order, sets_package=True),
    ]
    _pipeline(stages).generate(_selected())
    assert captures[0].brief.title == "Punchy Title"
    assert captures[0].brief.category == "technology"


def test_custom_work_dir_is_used():
    captures: list[PipelineContext] = []
    order: list[str] = []
    stages = [
        _Stage("capture", order, captures=captures),
        _Stage("packaging", order, sets_package=True),
    ]
    _pipeline(stages).generate(_selected(), work_dir=Path("custom/dir"))
    assert captures[0].work_dir == Path("custom/dir")
