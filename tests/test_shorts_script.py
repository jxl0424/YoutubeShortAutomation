"""Tests for the Script Generation stage (LLM injected as a fake)."""

from __future__ import annotations

from pathlib import Path

import pytest

from shorts.config.settings import ShortsConfig
from shorts.domain.brief import TopicBrief
from shorts.domain.exceptions import ScriptGenerationError
from shorts.domain.interfaces import LLMProvider
from shorts.domain.models import TopicResearch
from shorts.pipeline import PipelineContext
from shorts.stages.script import (
    LLMScript,
    ScriptGenerator,
    build_system_prompt,
    build_user_prompt,
)
from trend_intelligence.domain.exceptions import InvalidLLMResponseError

CANNED = {
    "hook": "You won't believe what this AI chip just did.",
    "narration": " ".join(["word"] * 70),  # 70 words, within 60-90
    "scenes": [
        {
            "narration": "Intro",
            "on_screen_text": "AI CHIP",
            "visual_instruction": "show chip",
        },
        {
            "narration": "Benchmark",
            "on_screen_text": "2x",
            "visual_instruction": "show graph",
        },
    ],
    "caption_text": "This AI chip doubles speed",
    "cta": "Follow for more tech.",
}


class FakeLLM(LLMProvider):
    def __init__(self, data=CANNED, *, fail_times=0):
        self._data = data
        self._fail_times = fail_times
        self.calls = 0

    def generate_structured(self, *, system, user, schema):
        self.calls += 1
        if self.calls <= self._fail_times:
            raise InvalidLLMResponseError("bad output")
        return schema.model_validate(self._data)


def _ctx(research=None):
    brief = TopicBrief(
        title="This AI Chip Doubles Speed",
        category="technology",
        keywords=["ai", "chip"],
        hook_idea="hook",
        confidence=0.7,
        visual_suggestions=["benchmark"],
    )
    return PipelineContext(
        brief=brief, config=ShortsConfig(), work_dir=Path("out"), research=research
    )


def test_generates_structured_script():
    ctx = _ctx()
    ScriptGenerator(FakeLLM()).run(ctx)
    assert ctx.script is not None
    assert ctx.script.hook.startswith("You won't")
    assert ctx.script.word_count == 70
    assert [s.index for s in ctx.script.scenes] == [0, 1]
    assert ctx.script.scenes[0].on_screen_text == "AI CHIP"
    assert ctx.script.cta == "Follow for more tech."


def test_retries_then_succeeds():
    ctx = _ctx()
    llm = FakeLLM(fail_times=1)
    ScriptGenerator(llm, max_retries=2).run(ctx)
    assert ctx.script is not None
    assert llm.calls == 2


def test_fails_after_retries_raises_script_error():
    ctx = _ctx()
    with pytest.raises(ScriptGenerationError):
        ScriptGenerator(FakeLLM(fail_times=99), max_retries=1).run(ctx)


def test_user_prompt_includes_research_when_present():
    research = TopicResearch(facts=["A100 was 2020"], dates=["2026"])
    config = ShortsConfig().script
    brief = _ctx().brief
    prompt = build_user_prompt(brief, research, config)
    assert "A100 was 2020" in prompt
    # absent when no research
    assert "research" not in build_user_prompt(brief, None, config)


def test_system_prompt_respects_cta_toggle():
    config = ShortsConfig().script
    config.include_cta = False
    assert "set `cta` to null" in build_system_prompt(config)
    config.include_cta = True
    assert "call-to-action" in build_system_prompt(config)


def test_llm_script_schema_tolerates_extra_keys():
    # robustness: the LLM may add keys we don't model
    data = {**CANNED, "unexpected": 123}
    script = LLMScript.model_validate(data)
    assert script.hook
