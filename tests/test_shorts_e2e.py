"""End-to-end Stage 2 test: build_pipeline with every provider faked.

Proves the composition root wires all stages in order and the pipeline turns a
Stage 1 SelectedTopic into a complete GeneratedShort — without any network,
LLM, ffmpeg or Google calls.
"""

from __future__ import annotations

from typing import ClassVar

from shorts.config.settings import ShortsConfig
from shorts.domain.interfaces import (
    LLMProvider,
    ThumbnailRenderer,
    VideoRenderer,
    VisualProvider,
    VoiceProvider,
)
from shorts.domain.models import (
    RenderedVideo,
    ThumbnailResult,
    VisualAsset,
    VisualType,
    VoiceResult,
)
from shorts.pipeline import build_pipeline
from shorts.providers.storage import LocalStorageProvider
from trend_intelligence.domain.models import (
    AggregatedTrend,
    ContentCategory,
    RankedTrend,
    ScoreBreakdown,
    SelectedTopic,
    TrendAnalysis,
    TrendSource,
)

SCRIPT = {
    "hook": "You won't believe this AI chip.",
    "narration": " ".join(["word"] * 70),
    "scenes": [
        {
            "narration": "first scene",
            "on_screen_text": "ONE",
            "visual_instruction": "show a chip",
        },
        {
            "narration": "second scene",
            "on_screen_text": "TWO",
            "visual_instruction": "show a graph",
        },
    ],
    "caption_text": "AI chip",
    "cta": "Follow!",
}
METADATA = {
    "title": "This AI Chip Doubles Speed",
    "description": "The chip everyone is talking about.",
    "tags": ["ai", "chip"],
    "hashtags": ["#Shorts", "#ai"],
    "keywords": ["ai chip"],
}


class SchemaFakeLLM(LLMProvider):
    def generate_structured(self, *, system, user, schema):
        data = SCRIPT if schema.__name__ == "LLMScript" else METADATA
        return schema.model_validate(data)


class FakeVoice(VoiceProvider):
    name: ClassVar[str] = "fake"

    def synthesize(self, *, text, output_dir, voice, language, rate=None):
        output_dir.mkdir(parents=True, exist_ok=True)
        (output_dir / "narration.mp3").write_bytes(b"audio")
        (output_dir / "captions.srt").write_text(
            "1\n00:00:00,000 --> 00:00:04,000\nhi\n"
        )
        return VoiceResult(
            audio_path=output_dir / "narration.mp3",
            subtitle_path=output_dir / "captions.srt",
            duration_seconds=4.0,
        )


class FakeVisual(VisualProvider):
    name: ClassVar[str] = "fake"
    provides: ClassVar[set[VisualType]] = {VisualType.GENERATED_IMAGE}

    def fetch(self, scene, output_dir):
        output_dir.mkdir(parents=True, exist_ok=True)
        path = output_dir / f"scene_{scene.index:02d}.jpg"
        path.write_bytes(f"image-{scene.index}".encode())  # distinct per scene
        return VisualAsset(
            scene_index=scene.index,
            visual_type=VisualType.GENERATED_IMAGE,
            path=path,
            source="fake",
            width=1080,
            height=1920,
        )


class FakeRenderer(VideoRenderer):
    name: ClassVar[str] = "fake"

    def render(self, request):
        request.output_path.write_bytes(b"video")
        return RenderedVideo(
            path=request.output_path,
            width=request.width,
            height=request.height,
            fps=request.fps,
            duration_seconds=4.0,
        )


class FakeThumb(ThumbnailRenderer):
    name: ClassVar[str] = "fake"

    def render(self, request):
        request.output_path.write_bytes(b"png")
        return ThumbnailResult(
            path=request.output_path, width=request.width, height=request.height
        )


def _selected() -> SelectedTopic:
    aggregated = AggregatedTrend(
        cluster_id="c1",
        canonical_title="AI chip breakthrough",
        keywords=["ai", "chip"],
        categories=[ContentCategory.TECHNOLOGY],
        sources=[TrendSource.HACKER_NEWS],
        source_count=1,
    )
    analysis = TrendAnalysis(
        cluster_id="c1",
        refined_title="This AI Chip Doubles Speed",
        recommended_category=ContentCategory.TECHNOLOGY,
        ai_confidence=0.7,
    )
    ranked = RankedTrend(
        aggregated_trend=aggregated,
        analysis=analysis,
        score_breakdown=ScoreBreakdown(total=0.7),
        final_score=0.7,
    )
    return SelectedTopic(
        title="This AI Chip Doubles Speed",
        ranked_trend=ranked,
        selection_reason="top",
        score=0.7,
    )


def test_end_to_end_produces_complete_package(tmp_path):
    pipeline = build_pipeline(
        ShortsConfig(),
        script_llm=SchemaFakeLLM(),
        voice_provider=FakeVoice(),
        visual_providers=[FakeVisual()],
        renderer=FakeRenderer(),
        thumbnail_renderer=FakeThumb(),
        storage=LocalStorageProvider(),
    )

    package = pipeline.generate(_selected(), work_dir=tmp_path)

    assert package.output_dir == tmp_path
    for artifact in (
        "video.mp4",
        "thumbnail.png",
        "captions.srt",
        "metadata.json",
        "description.txt",
        "tags.txt",
        "script.txt",
    ):
        assert (tmp_path / artifact).exists(), f"missing {artifact}"
    assert (tmp_path / "assets").is_dir()
    assert (tmp_path / "logs" / "summary.json").exists()

    # upload is off by default -> no upload result recorded
    assert package.upload is None
    assert package.video_path == tmp_path / "video.mp4"


def test_build_pipeline_wires_all_stages():
    pipeline = build_pipeline(
        ShortsConfig(),
        script_llm=SchemaFakeLLM(),
        voice_provider=FakeVoice(),
        visual_providers=[FakeVisual()],
        renderer=FakeRenderer(),
        thumbnail_renderer=FakeThumb(),
        storage=LocalStorageProvider(),
    )
    names = [s.name for s in pipeline._stages]
    assert names == [
        "topic_enrichment",
        "script_generation",
        "metadata_generation",
        "voice_generation",
        "visual_planning",
        "asset_collection",
        "asset_validation",
        "video_assembly",
        "thumbnail_generation",
        "packaging",
        "youtube_upload",
    ]
