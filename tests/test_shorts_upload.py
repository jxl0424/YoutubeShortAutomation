"""Tests for the YouTube upload provider + Uploader stage (Google API mocked)."""

from __future__ import annotations

from pathlib import Path
from typing import ClassVar

import pytest

from shorts.config.settings import ShortsConfig
from shorts.domain.brief import TopicBrief
from shorts.domain.exceptions import UploadError
from shorts.domain.interfaces import UploadProvider
from shorts.domain.models import GeneratedShort, UploadResult, VideoMetadata
from shorts.pipeline import PipelineContext
from shorts.providers.upload.youtube import YouTubeUploadProvider
from shorts.stages.upload import Uploader


class FakeRequest:
    def __init__(self, response):
        self._response = response

    def execute(self):
        return self._response


class FakeService:
    def __init__(self, response):
        self._response = response
        self.inserted = None
        self.thumb_set = None

    def videos(self):
        service = self

        class _Videos:
            def insert(self, *, part, body, media_body):
                service.inserted = {"part": part, "body": body, "media": media_body}
                return FakeRequest(service._response)

        return _Videos()

    def thumbnails(self):
        service = self

        class _Thumbnails:
            def set(self, *, videoId, media_body):  # noqa: N803 (Google's param name)
                service.thumb_set = videoId
                return FakeRequest({})

        return _Thumbnails()


def _package(tmp, *, thumbnail=True):
    (tmp / "video.mp4").write_bytes(b"video")
    thumb = None
    if thumbnail:
        (tmp / "thumbnail.png").write_bytes(b"png")
        thumb = tmp / "thumbnail.png"
    return GeneratedShort(
        output_dir=tmp, video_path=tmp / "video.mp4", thumbnail_path=thumb
    )


def _metadata():
    return VideoMetadata(
        title="My Short", description="desc", tags=["a", "b"], hashtags=["#Shorts"]
    )


def _provider(response, **kw):
    return YouTubeUploadProvider(
        build_service=lambda: FakeService(response),
        media_factory=lambda path: f"media:{path}",
        **kw,
    )


def test_uploads_video_and_returns_result(tmp_path):
    service = FakeService({"id": "abc123", "status": {"uploadStatus": "uploaded"}})
    provider = YouTubeUploadProvider(
        build_service=lambda: service, media_factory=lambda p: f"media:{p}"
    )
    result = provider.upload(_package(tmp_path), _metadata())
    assert result.uploaded is True
    assert result.video_id == "abc123"
    assert result.url == "https://www.youtube.com/shorts/abc123"
    assert service.inserted["body"]["snippet"]["title"] == "My Short"
    assert service.thumb_set == "abc123"  # thumbnail was set


def test_status_declares_synthetic_media_and_kids(tmp_path):
    service = FakeService({"id": "x"})
    provider = YouTubeUploadProvider(
        build_service=lambda: service,
        media_factory=lambda p: f"media:{p}",
        privacy="public",
    )
    provider.upload(_package(tmp_path), _metadata())
    status = service.inserted["body"]["status"]
    assert status["privacyStatus"] == "public"
    assert status["selfDeclaredMadeForKids"] is False
    assert status["containsSyntheticMedia"] is True


def test_privacy_override_wins_over_configured_default(tmp_path):
    service = FakeService({"id": "x"})
    provider = YouTubeUploadProvider(
        build_service=lambda: service,
        media_factory=lambda p: f"media:{p}",
        privacy="public",
    )
    provider.upload(_package(tmp_path), _metadata(), privacy="private")
    assert service.inserted["body"]["status"]["privacyStatus"] == "private"


def test_missing_video_raises(tmp_path):
    provider = _provider({"id": "x"})
    pkg = GeneratedShort(output_dir=tmp_path, video_path=None)
    with pytest.raises(UploadError):
        provider.upload(pkg, _metadata())


def test_missing_client_secrets_raises(tmp_path):
    provider = YouTubeUploadProvider(client_secrets_path=None)  # no build_service
    with pytest.raises(UploadError):
        provider.upload(_package(tmp_path), _metadata())


# --- stage ----------------------------------------------------------------- #
class FakeUploadProvider(UploadProvider):
    name: ClassVar[str] = "fake"

    def __init__(self):
        self.called = False
        self.privacy = None

    def upload(self, package, metadata, *, privacy=None) -> UploadResult:
        self.called = True
        self.privacy = privacy
        return UploadResult(uploaded=True, video_id="vid", url="u", status="uploaded")


def _ctx(tmp):
    ctx = PipelineContext(
        brief=TopicBrief(title="t", category="c", confidence=0.5),
        config=ShortsConfig(),
        work_dir=tmp,
    )
    ctx.metadata = _metadata()
    ctx.package = GeneratedShort(output_dir=tmp, video_path=tmp / "video.mp4")
    return ctx


def test_uploader_disabled_by_default():
    stage = Uploader(FakeUploadProvider())
    assert stage.is_enabled(ShortsConfig()) is False


def _enabled_config(tmp_path):
    config = ShortsConfig()
    config.upload.enabled = True
    config.upload.token_path = str(tmp_path / "no_token.json")  # not cached
    return config


def test_uploader_skips_when_enabled_but_no_credentials(tmp_path, monkeypatch):
    monkeypatch.delenv("YOUTUBE_CLIENT_SECRETS", raising=False)
    stage = Uploader(FakeUploadProvider())
    assert stage.is_enabled(_enabled_config(tmp_path)) is False


def test_uploader_enabled_with_client_secrets_env(tmp_path, monkeypatch):
    monkeypatch.setenv("YOUTUBE_CLIENT_SECRETS", str(tmp_path / "secrets.json"))
    stage = Uploader(FakeUploadProvider())
    assert stage.is_enabled(_enabled_config(tmp_path)) is True


def test_uploader_enabled_with_cached_token(tmp_path, monkeypatch):
    monkeypatch.delenv("YOUTUBE_CLIENT_SECRETS", raising=False)
    config = _enabled_config(tmp_path)
    Path(config.upload.token_path).write_text("{}", encoding="utf-8")
    stage = Uploader(FakeUploadProvider())
    assert stage.is_enabled(config) is True


def test_uploader_runs_when_enabled(tmp_path):
    provider = FakeUploadProvider()
    ctx = _ctx(tmp_path)
    ctx.config.upload.enabled = True
    ctx.publish_privacy = "public"  # as PrePublishQA would set on a pass
    Uploader(provider).run(ctx)
    assert provider.called is True
    assert provider.privacy == "public"  # QA-resolved privacy flows through
    assert ctx.upload_result.video_id == "vid"
    assert ctx.package.upload.video_id == "vid"  # recorded on package too


def test_uploader_requires_package(tmp_path):
    ctx = _ctx(tmp_path)
    ctx.package = None
    with pytest.raises(UploadError):
        Uploader(FakeUploadProvider()).run(ctx)
