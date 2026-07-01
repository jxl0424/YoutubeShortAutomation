"""Tests for voice generation: subtitle helpers, stage, and provider factory."""

from __future__ import annotations

import subprocess
import sys
import types
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
from shorts.providers.voice.kokoro_provider import KokoroVoiceProvider
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


def test_factory_builds_kokoro():
    provider = build_voice_provider(VoiceConfig(provider="kokoro"))
    assert isinstance(provider, KokoroVoiceProvider)
    assert provider.name == "kokoro"


def test_factory_rejects_unknown_provider():
    with pytest.raises(ShortsConfigurationError):
        build_voice_provider(VoiceConfig(provider="does_not_exist"))


# --- kokoro provider ------------------------------------------------------- #
def test_kokoro_rate_to_speed():
    assert KokoroVoiceProvider._rate_to_speed(None) == 1.0
    assert KokoroVoiceProvider._rate_to_speed("+0%") == 1.0
    assert abs(KokoroVoiceProvider._rate_to_speed("+10%") - 1.1) < 1e-9
    assert abs(KokoroVoiceProvider._rate_to_speed("-20%") - 0.8) < 1e-9
    assert KokoroVoiceProvider._rate_to_speed("garbage") == 1.0


def test_kokoro_estimates_word_times_span_duration():
    words = KokoroVoiceProvider._estimate_word_times("one two three", 6.0)
    assert len(words) == 3
    assert words[0][0] == 0.0
    assert abs(words[-1][1] - 6.0) < 1e-9  # last word ends at the audio duration


def test_kokoro_synthesizes_mp3_and_cues(tmp_path):
    # soundfile ships in the optional [kokoro] extra; skip if it isn't installed.
    pytest.importorskip("soundfile")
    import numpy as np

    def fake_synth(text, voice, speed, lang):
        assert voice == "af_heart" and lang == "en-us"
        return np.zeros(24000, dtype=np.float32), 24000  # 1.0s of silence

    provider = KokoroVoiceProvider(
        model_path="x.onnx", voices_path="v.bin", synth=fake_synth
    )
    result = provider.synthesize(
        text="hello from kokoro", output_dir=tmp_path, voice="af_heart", language="en"
    )
    assert result.audio_path.exists() and result.audio_path.name == "narration.mp3"
    assert result.subtitle_path.exists()
    assert result.cues
    assert abs(result.duration_seconds - 1.0) < 0.05


def test_kokoro_rejects_empty_text(tmp_path):
    with pytest.raises(VoiceError):
        KokoroVoiceProvider(model_path="x", voices_path="v").synthesize(
            text="  ", output_dir=tmp_path, voice="af_heart", language="en"
        )


def test_kokoro_missing_model_raises(tmp_path):
    provider = KokoroVoiceProvider(
        model_path=str(tmp_path / "absent.onnx"), voices_path=str(tmp_path / "v.bin")
    )
    with pytest.raises(VoiceError):
        provider.synthesize(
            text="hi", output_dir=tmp_path, voice="af_heart", language="en"
        )


# The tests below stub soundfile/imageio_ffmpeg/subprocess so they run without
# the optional [kokoro] extra or a real ffmpeg (unlike the mp3 test above).
def _stub_audio_deps(monkeypatch, run_fn):
    def fake_sf_write(path, samples, sample_rate):
        Path(path).write_bytes(b"RIFF-fake-wav")

    monkeypatch.setitem(
        sys.modules, "soundfile", types.SimpleNamespace(write=fake_sf_write)
    )
    monkeypatch.setitem(
        sys.modules,
        "imageio_ffmpeg",
        types.SimpleNamespace(get_ffmpeg_exe=lambda: "ffmpeg"),
    )
    monkeypatch.setattr(subprocess, "run", run_fn)


def _silence(frames=24000):
    import numpy as np

    return np.zeros(frames, dtype=np.float32), 24000


def test_kokoro_mp3_argv_and_wav_cleanup(tmp_path, monkeypatch):
    captured = {}

    def fake_run(cmd, **kwargs):
        captured["cmd"] = cmd
        Path(cmd[-1]).write_bytes(b"mp3")

    _stub_audio_deps(monkeypatch, fake_run)
    provider = KokoroVoiceProvider(
        model_path="x.onnx", voices_path="v.bin", synth=lambda t, v, s, lg: _silence()
    )
    result = provider.synthesize(
        text="hello", output_dir=tmp_path, voice="af_heart", language="en"
    )
    assert "-b:a" in captured["cmd"] and "128k" in captured["cmd"]
    assert not (tmp_path / "_narration.wav").exists()  # intermediate wav removed
    assert result.audio_path.name == "narration.mp3"


def test_kokoro_ffmpeg_failure_raises_voice_error_and_cleans_wav(tmp_path, monkeypatch):
    def failing_run(cmd, **kwargs):
        raise subprocess.CalledProcessError(1, cmd, stderr=b"boom")

    _stub_audio_deps(monkeypatch, failing_run)
    provider = KokoroVoiceProvider(
        model_path="x.onnx", voices_path="v.bin", synth=lambda t, v, s, lg: _silence()
    )
    with pytest.raises(VoiceError):
        provider.synthesize(
            text="hello", output_dir=tmp_path, voice="af_heart", language="en"
        )
    assert not (tmp_path / "_narration.wav").exists()  # no orphan on failure


def test_kokoro_empty_audio_raises(tmp_path):
    provider = KokoroVoiceProvider(
        model_path="x.onnx", voices_path="v.bin", synth=lambda t, v, s, lg: _silence(0)
    )
    with pytest.raises(VoiceError):
        provider.synthesize(
            text="hi", output_dir=tmp_path, voice="af_heart", language="en"
        )


def test_kokoro_british_voice_selects_en_gb(tmp_path, monkeypatch):
    seen = {}

    def synth(text, voice, speed, lang):
        seen["lang"] = lang
        return _silence()

    _stub_audio_deps(monkeypatch, lambda cmd, **kw: Path(cmd[-1]).write_bytes(b"mp3"))
    provider = KokoroVoiceProvider(model_path="x", voices_path="v", synth=synth)
    provider.synthesize(text="hi", output_dir=tmp_path, voice="bf_alice", language="en")
    assert seen["lang"] == "en-gb"


def test_edge_provider_rejects_empty_text(tmp_path):
    with pytest.raises(VoiceError):
        EdgeTTSVoiceProvider().synthesize(
            text="   ", output_dir=tmp_path, voice="en-US-AriaNeural", language="en"
        )
