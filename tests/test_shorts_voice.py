"""Tests for voice generation: subtitle helpers, stage, and provider factory."""

from __future__ import annotations

from pathlib import Path

import pytest

from shorts.config.settings import ShortsConfig, VoiceConfig
from shorts.domain.brief import TopicBrief
from shorts.domain.exceptions import ShortsConfigurationError, VoiceError
from shorts.domain.interfaces import VoiceProvider
from shorts.domain.models import CaptionCue, Script, VoiceResult
from shorts.pipeline import PipelineContext
from shorts.providers.voice.edge_tts_provider import EdgeTTSVoiceProvider
from shorts.providers.voice.factory import build_voice_provider
from shorts.providers.voice.subtitles import cues_to_srt, group_words_into_cues
from shorts.stages.voice import VoiceGenerator


class FakeVoice(VoiceProvider):
    name = "fake"

    def __init__(self):
        self.last = None

    def synthesize(self, *, text, output_dir, voice, language, rate=None):
        self.last = {"text": text, "voice": voice, "rate": rate}
        return VoiceResult(
            audio_path=output_dir / "narration.mp3",
            subtitle_path=output_dir / "captions.srt",
            duration_seconds=5.0,
            cues=[CaptionCue(index=0, start_seconds=0.0, end_seconds=5.0, text=text)],
        )


def _ctx(*, script=True):
    brief = TopicBrief(title="T", category="technology", keywords=["k"], confidence=0.5)
    s = Script(hook="Hook", narration="This is the narration.") if script else None
    return PipelineContext(
        brief=brief, config=ShortsConfig(), work_dir=Path("out"), script=s
    )


# --- subtitle helpers ------------------------------------------------------ #
def test_group_words_into_cues_chunks_by_max():
    words = [(float(i), float(i) + 1, f"w{i}") for i in range(10)]
    cues = group_words_into_cues(words, max_words=8)
    assert len(cues) == 2
    assert cues[0].start_seconds == 0.0
    assert cues[0].end_seconds == 8.0  # 8th word (index 7) ends at 8.0
    assert cues[1].text == "w8 w9"


def test_cues_to_srt_formats_timestamps():
    cue = CaptionCue(index=0, start_seconds=0.0, end_seconds=1.5, text="hello world")
    srt = cues_to_srt([cue])
    assert "1\n00:00:00,000 --> 00:00:01,500\nhello world" in srt


# --- stage ----------------------------------------------------------------- #
def test_voice_stage_synthesizes_from_script():
    ctx = _ctx()
    provider = FakeVoice()
    VoiceGenerator(provider).run(ctx)
    assert ctx.voice is not None
    assert ctx.voice.duration_seconds == 5.0
    assert provider.last["text"] == "This is the narration."
    assert provider.last["voice"] == ctx.config.voice.voice


def test_voice_stage_requires_script():
    with pytest.raises(VoiceError):
        VoiceGenerator(FakeVoice()).run(_ctx(script=False))


# --- factory --------------------------------------------------------------- #
def test_factory_builds_edge_tts():
    provider = build_voice_provider(VoiceConfig(provider="edge_tts"))
    assert isinstance(provider, EdgeTTSVoiceProvider)


def test_factory_rejects_unknown_provider():
    with pytest.raises(ShortsConfigurationError):
        build_voice_provider(VoiceConfig(provider="does_not_exist"))


def test_edge_provider_rejects_empty_text(tmp_path):
    with pytest.raises(VoiceError):
        EdgeTTSVoiceProvider().synthesize(
            text="   ", output_dir=tmp_path, voice="en-US-AriaNeural", language="en"
        )
