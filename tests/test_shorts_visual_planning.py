"""Tests for the Visual Planning stage."""

from __future__ import annotations

from pathlib import Path

import pytest

from shorts.config.settings import ShortsConfig
from shorts.domain.brief import TopicBrief
from shorts.domain.exceptions import VisualPlanningError
from shorts.domain.models import Script, ScriptScene, VisualType, VoiceResult
from shorts.pipeline import PipelineContext
from shorts.stages.visual_planning import VisualPlanner


def _script(scenes=True):
    return Script(
        hook="Hook",
        narration="three words here and two more",
        scenes=(
            [
                ScriptScene(
                    index=0,
                    narration="three words here",
                    visual_instruction="show a city",
                ),
                ScriptScene(index=1, narration="and two", on_screen_text="2x"),
            ]
            if scenes
            else []
        ),
    )


def _ctx(*, script=True, voice_seconds=None, keywords=("ai", "chip"), suggestions=()):
    brief = TopicBrief(
        title="T",
        category="technology",
        keywords=list(keywords),
        visual_suggestions=list(suggestions),
        confidence=0.5,
    )
    voice = (
        VoiceResult(audio_path=Path("a.mp3"), duration_seconds=voice_seconds)
        if voice_seconds is not None
        else None
    )
    return PipelineContext(
        brief=brief,
        config=ShortsConfig(),
        work_dir=Path("out"),
        script=_script(script) if script else None,
        voice=voice,
    )


def test_requires_script():
    with pytest.raises(VisualPlanningError):
        VisualPlanner().run(_ctx(script=False))


def test_distributes_duration_by_word_count():
    ctx = _ctx(voice_seconds=10.0)  # scene words: 3 and 2 -> 6s and 4s
    VisualPlanner().run(ctx)
    plan = ctx.scene_plan
    assert plan is not None
    assert [s.index for s in plan.scenes] == [0, 1]
    assert plan.scenes[0].duration_seconds == pytest.approx(6.0, abs=1e-3)
    assert plan.scenes[1].duration_seconds == pytest.approx(4.0, abs=1e-3)
    assert plan.total_duration_seconds == pytest.approx(10.0, abs=1e-3)


def test_visual_query_uses_instruction_then_fallbacks():
    ctx = _ctx(voice_seconds=8.0)
    VisualPlanner().run(ctx)
    scenes = ctx.scene_plan.scenes
    assert scenes[0].visual_query == "show a city"  # from visual_instruction
    assert scenes[1].visual_query == "ai chip"  # fallback to keywords
    assert scenes[0].visual_type is VisualType.STOCK_VIDEO


def test_estimates_duration_without_voice():
    ctx = _ctx(voice_seconds=None)  # no audio -> estimate from words_per_second
    VisualPlanner().run(ctx)
    # 6 narration words across scenes; words_per_second default 2.5 -> ~2.4s total
    assert ctx.scene_plan.total_duration_seconds > 0


def test_falls_back_to_single_scene_when_no_breakdown():
    ctx = _ctx(script=True, voice_seconds=5.0)
    ctx.script.scenes = []  # script without a scene breakdown
    VisualPlanner().run(ctx)
    assert len(ctx.scene_plan.scenes) == 1
    assert ctx.scene_plan.scenes[0].duration_seconds == pytest.approx(5.0, abs=1e-3)
