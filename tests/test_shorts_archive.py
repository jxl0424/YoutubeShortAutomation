"""Tests for the cloud archive provider + CloudArchiver stage (boto3 faked)."""

from __future__ import annotations

import pytest

from shorts.config.settings import ShortsConfig
from shorts.domain.brief import TopicBrief
from shorts.domain.exceptions import ArchiveError
from shorts.domain.models import GeneratedShort
from shorts.pipeline import PipelineContext
from shorts.providers.archive.s3 import S3ArchiveProvider
from shorts.stages.archive import ARCHIVED_MARKER, CloudArchiver


class FakeS3Client:
    def __init__(self, *, fail=False):
        self.fail = fail
        self.puts = []

    def put_object(self, *, Bucket, Key, Body, ContentType):  # noqa: N803 (boto3 names)
        if self.fail:
            raise RuntimeError("network down")
        self.puts.append({"Bucket": Bucket, "Key": Key, "ContentType": ContentType})


def _package(tmp, *, assets=True):
    (tmp / "video.mp4").write_bytes(b"video")
    (tmp / "thumbnail.png").write_bytes(b"png")
    (tmp / "metadata.json").write_text("{}", encoding="utf-8")
    logs = tmp / "logs"
    logs.mkdir()
    (logs / "summary.json").write_text("{}", encoding="utf-8")
    assets_dir = None
    if assets:
        assets_dir = tmp / "assets"
        assets_dir.mkdir()
        (assets_dir / "scene_00.mp4").write_bytes(b"a" * 100)
    return GeneratedShort(
        output_dir=tmp,
        video_path=tmp / "video.mp4",
        thumbnail_path=tmp / "thumbnail.png",
        metadata_path=tmp / "metadata.json",
        assets_dir=assets_dir,
        logs_dir=logs,
    )


# --- provider -------------------------------------------------------------- #
def test_archive_uploads_deliverable_and_skips_assets(tmp_path):
    client = FakeS3Client()
    provider = S3ArchiveProvider(client=client)
    result = provider.archive(_package(tmp_path), bucket="my-bucket", prefix="shorts")

    assert result.archived is True
    assert result.bucket == "my-bucket"
    keys = {p["Key"] for p in client.puts}
    run = tmp_path.name
    assert f"shorts/{run}/video.mp4" in keys
    assert f"shorts/{run}/logs/summary.json" in keys
    # Raw footage skipped by default.
    assert not any("assets/" in k for k in keys)
    # Content type is guessed.
    video_put = next(p for p in client.puts if p["Key"].endswith("video.mp4"))
    assert video_put["ContentType"] == "video/mp4"


def test_archive_includes_assets_when_requested(tmp_path):
    client = FakeS3Client()
    provider = S3ArchiveProvider(client=client)
    provider.archive(
        _package(tmp_path), bucket="b", prefix="shorts", include_assets=True
    )
    keys = {p["Key"] for p in client.puts}
    assert any(k.endswith("assets/scene_00.mp4") for k in keys)


def test_archive_empty_prefix_omits_leading_slash(tmp_path):
    client = FakeS3Client()
    S3ArchiveProvider(client=client).archive(_package(tmp_path), bucket="b", prefix="")
    run = tmp_path.name
    assert all(p["Key"].startswith(f"{run}/") for p in client.puts)


def test_archive_no_artifacts_raises(tmp_path):
    empty = GeneratedShort(output_dir=tmp_path)
    with pytest.raises(ArchiveError):
        S3ArchiveProvider(client=FakeS3Client()).archive(empty, bucket="b")


# --- stage ----------------------------------------------------------------- #
def _ctx(tmp, package):
    ctx = PipelineContext(
        brief=TopicBrief(title="t", category="c", confidence=0.5),
        config=ShortsConfig(),
        work_dir=tmp,
    )
    ctx.config.archive.enabled = True
    ctx.config.archive.bucket = "my-bucket"
    ctx.package = package
    return ctx


def test_stage_archives_and_writes_marker(tmp_path):
    client = FakeS3Client()
    ctx = _ctx(tmp_path, _package(tmp_path))
    CloudArchiver(S3ArchiveProvider(client=client)).run(ctx)

    assert ctx.archive_result.archived is True
    assert ctx.package.archive.archived is True
    assert (tmp_path / ARCHIVED_MARKER).exists()


def test_stage_is_best_effort_on_failure(tmp_path):
    client = FakeS3Client(fail=True)
    ctx = _ctx(tmp_path, _package(tmp_path))
    # Must not raise — the short is already published.
    CloudArchiver(S3ArchiveProvider(client=client)).run(ctx)

    assert ctx.archive_result.archived is False
    assert not (tmp_path / ARCHIVED_MARKER).exists()


def test_stage_self_gates_without_config(tmp_path):
    stage = CloudArchiver(S3ArchiveProvider(client=FakeS3Client()))
    config = ShortsConfig()
    assert stage.is_enabled(config) is False  # disabled by default


def test_stage_skips_without_credentials(tmp_path, monkeypatch):
    monkeypatch.delenv("R2_ENDPOINT_URL", raising=False)
    stage = CloudArchiver(S3ArchiveProvider(client=FakeS3Client()))
    config = ShortsConfig()
    config.archive.enabled = True
    config.archive.bucket = "b"
    # enabled but no endpoint/key env → skip, don't fail.
    assert stage.is_enabled(config) is False
