"""Tests for the Metadata Generation stage (LLM injected as a fake)."""

from __future__ import annotations

from pathlib import Path

from shorts.config.settings import ShortsConfig
from shorts.domain.brief import TopicBrief
from shorts.domain.interfaces import LLMProvider
from shorts.domain.models import Script
from shorts.pipeline import PipelineContext
from shorts.stages.metadata import MetadataGenerator
from trend_intelligence.domain.exceptions import LLMError

CANNED = {
    "title": "This AI Chip Doubles Inference Speed",
    "description": "The chip everyone is talking about.",
    "tags": ["ai", "chip", "ai", "tech"],  # duplicate to test de-dup
    "hashtags": ["ai", "#tech"],  # missing #Shorts; mixed prefixes
    "keywords": ["ai chip", "inference"],
}


class FakeLLM(LLMProvider):
    def __init__(self, data=CANNED, *, fail_times=0):
        self._data = data
        self._fail_times = fail_times
        self.calls = 0

    def generate_structured(self, *, system, user, schema):
        self.calls += 1
        if self.calls <= self._fail_times:
            raise LLMError("down")
        return schema.model_validate(self._data)


def _ctx(*, script=True):
    brief = TopicBrief(
        title="This AI Chip Doubles Inference Speed",
        category="technology",
        keywords=["ai", "chip", "inference"],
        confidence=0.7,
    )
    s = (
        Script(hook="Hook!", narration="Narration here.", cta="Follow!")
        if script
        else None
    )
    return PipelineContext(
        brief=brief, config=ShortsConfig(), work_dir=Path("out"), script=s
    )


def test_generates_metadata_and_dedupes_tags():
    ctx = _ctx()
    MetadataGenerator(FakeLLM()).run(ctx)
    assert ctx.metadata is not None
    assert ctx.metadata.tags == ["ai", "chip", "tech"]  # deduped, order preserved
    assert ctx.metadata.title.startswith("This AI Chip")


def test_hashtags_normalized_with_shorts():
    ctx = _ctx()
    MetadataGenerator(FakeLLM()).run(ctx)
    assert ctx.metadata.hashtags[0] == "#Shorts"
    assert "#ai" in ctx.metadata.hashtags
    assert "#tech" in ctx.metadata.hashtags


def test_title_truncated_to_config_limit():
    long = {**CANNED, "title": "X" * 200}
    ctx = _ctx()
    ctx.config.metadata.max_title_length = 50
    MetadataGenerator(FakeLLM(long)).run(ctx)
    assert len(ctx.metadata.title) == 50


def test_counts_capped():
    big = {
        **CANNED,
        "tags": [f"t{i}" for i in range(40)],
        "hashtags": [f"#h{i}" for i in range(40)],
    }
    ctx = _ctx()
    ctx.config.metadata.max_tags = 5
    ctx.config.metadata.hashtag_count = 3
    MetadataGenerator(FakeLLM(big)).run(ctx)
    assert len(ctx.metadata.tags) == 5
    assert len(ctx.metadata.hashtags) == 3
    assert ctx.metadata.hashtags[0] == "#Shorts"  # always kept


def test_fallback_when_llm_fails():
    ctx = _ctx()
    MetadataGenerator(FakeLLM(fail_times=99), max_retries=1).run(ctx)
    md = ctx.metadata
    assert md is not None
    assert md.title == "This AI Chip Doubles Inference Speed"
    assert md.tags == ["ai", "chip", "inference"]  # from brief keywords
    assert "#Shorts" in md.hashtags
    assert "Hook!" in md.description  # built from script
