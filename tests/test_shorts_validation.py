"""Tests for the Asset Validation stage."""

from __future__ import annotations

import pytest

from shorts.config.settings import ShortsConfig
from shorts.domain.brief import TopicBrief
from shorts.domain.exceptions import AssetValidationError
from shorts.domain.models import Scene, ScenePlan, VisualAsset, VisualType
from shorts.pipeline import PipelineContext
from shorts.stages.validation import AssetValidator


def _scene(index, duration=3.0):
    return Scene(
        index=index,
        narration="n",
        duration_seconds=duration,
        visual_type=VisualType.GENERATED_IMAGE,
        visual_query="q",
    )


def _asset(tmp, index, *, content=None, width=1080, height=1920, duration=None):
    path = tmp / f"asset_{index}.bin"
    path.write_bytes(content if content is not None else f"data-{index}".encode())
    return VisualAsset(
        scene_index=index,
        visual_type=VisualType.GENERATED_IMAGE,
        path=path,
        source="x",
        width=width,
        height=height,
        duration_seconds=duration,
    )


def _ctx(tmp, scenes, assets):
    ctx = PipelineContext(
        brief=TopicBrief(title="t", category="c", confidence=0.5),
        config=ShortsConfig(),
        work_dir=tmp,
    )
    ctx.scene_plan = ScenePlan(scenes=scenes)
    ctx.assets = assets
    return ctx


def test_valid_assets_pass(tmp_path):
    ctx = _ctx(
        tmp_path, [_scene(0), _scene(1)], [_asset(tmp_path, 0), _asset(tmp_path, 1)]
    )
    AssetValidator().run(ctx)
    assert ctx.validation.ok is True
    assert ctx.validation.issues == []


def test_missing_asset_for_scene_fails(tmp_path):
    ctx = _ctx(tmp_path, [_scene(0), _scene(1)], [_asset(tmp_path, 0)])
    with pytest.raises(AssetValidationError):
        AssetValidator().run(ctx)
    assert ctx.validation.ok is False
    assert any(i.code == "missing_asset" for i in ctx.validation.issues)


def test_low_resolution_fails(tmp_path):
    ctx = _ctx(tmp_path, [_scene(0)], [_asset(tmp_path, 0, width=320, height=480)])
    with pytest.raises(AssetValidationError):
        AssetValidator().run(ctx)
    assert any(i.code == "low_resolution" for i in ctx.validation.issues)


def test_landscape_orientation_fails(tmp_path):
    ctx = _ctx(tmp_path, [_scene(0)], [_asset(tmp_path, 0, width=1920, height=1080)])
    with pytest.raises(AssetValidationError):
        AssetValidator().run(ctx)
    assert any(i.code == "wrong_orientation" for i in ctx.validation.issues)


def test_empty_file_fails(tmp_path):
    ctx = _ctx(tmp_path, [_scene(0)], [_asset(tmp_path, 0, content=b"")])
    with pytest.raises(AssetValidationError):
        AssetValidator().run(ctx)
    assert any(i.code == "empty_file" for i in ctx.validation.issues)


def test_duplicate_visuals_warn_not_fail(tmp_path):
    a0 = _asset(tmp_path, 0, content=b"identical")
    a1 = _asset(tmp_path, 1, content=b"identical")
    ctx = _ctx(tmp_path, [_scene(0), _scene(1)], [a0, a1])
    AssetValidator().run(ctx)  # should not raise
    assert ctx.validation.ok is True
    assert any(i.code == "duplicate_visual" for i in ctx.validation.issues)


def test_short_video_asset_warns(tmp_path):
    asset = _asset(tmp_path, 0, duration=1.0)  # scene is 3s
    ctx = _ctx(tmp_path, [_scene(0, duration=3.0)], [asset])
    AssetValidator().run(ctx)
    assert ctx.validation.ok is True
    assert any(i.code == "short_asset" for i in ctx.validation.issues)


def test_unknown_dimensions_warn(tmp_path):
    ctx = _ctx(tmp_path, [_scene(0)], [_asset(tmp_path, 0, width=0, height=0)])
    AssetValidator().run(ctx)
    assert ctx.validation.ok is True
    assert any(i.code == "unknown_dimensions" for i in ctx.validation.issues)
