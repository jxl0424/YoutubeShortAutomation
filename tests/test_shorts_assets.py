"""Tests for asset collection: collector stage + Pollinations/Pexels providers."""

from __future__ import annotations

from pathlib import Path

import pytest

from shorts.config.settings import AssetsConfig
from shorts.domain.exceptions import VisualError
from shorts.domain.interfaces import VisualProvider
from shorts.domain.models import Scene, VisualAsset, VisualType
from shorts.providers.visual import build_visual_providers
from shorts.providers.visual.pexels import PexelsVisualProvider
from shorts.providers.visual.pollinations import PollinationsVisualProvider
from shorts.stages.assets import AssetCollector


def _scene(index=0, vtype=VisualType.STOCK_VIDEO, query="city skyline"):
    return Scene(
        index=index,
        narration="n",
        duration_seconds=3.0,
        visual_type=vtype,
        visual_query=query,
    )


# --- fake provider for the collector --------------------------------------- #
class FakeProvider(VisualProvider):
    def __init__(self, name, vtype, *, fail=False):
        self.name = name
        self.provides = {vtype}
        self._vtype = vtype
        self._fail = fail
        self.calls = 0

    def fetch(self, scene, output_dir):
        self.calls += 1
        if self._fail:
            raise VisualError(f"{self.name} boom")
        return VisualAsset(
            scene_index=scene.index,
            visual_type=self._vtype,
            path=Path(f"{self.name}_{scene.index}.bin"),
            source=self.name,
        )


class _Ctx:
    def __init__(self, scenes, work_dir):
        self.scene_plan = type("P", (), {"scenes": scenes})()
        self.work_dir = work_dir
        self.assets = []


def test_collects_one_asset_per_scene(tmp_path):
    provider = FakeProvider("poll", VisualType.GENERATED_IMAGE)
    ctx = _Ctx([_scene(0), _scene(1)], tmp_path)
    AssetCollector([provider]).run(ctx)
    assert len(ctx.assets) == 2
    assert provider.calls == 2


def test_prefers_provider_matching_visual_type(tmp_path):
    stock = FakeProvider("pexels", VisualType.STOCK_VIDEO)
    image = FakeProvider("pollinations", VisualType.GENERATED_IMAGE)
    ctx = _Ctx([_scene(0, VisualType.STOCK_VIDEO)], tmp_path)
    AssetCollector([image, stock]).run(ctx)  # image listed first, but stock matches
    assert ctx.assets[0].source == "pexels"


def test_falls_back_to_next_provider_on_failure(tmp_path):
    failing = FakeProvider("pexels", VisualType.STOCK_VIDEO, fail=True)
    backup = FakeProvider("pollinations", VisualType.GENERATED_IMAGE)
    ctx = _Ctx([_scene(0, VisualType.STOCK_VIDEO)], tmp_path)
    AssetCollector([failing, backup]).run(ctx)
    assert ctx.assets[0].source == "pollinations"
    assert failing.calls == 1


def test_raises_when_all_providers_fail(tmp_path):
    ctx = _Ctx([_scene(0)], tmp_path)
    with pytest.raises(VisualError):
        AssetCollector([FakeProvider("a", VisualType.STOCK_VIDEO, fail=True)]).run(ctx)


# --- Pollinations ---------------------------------------------------------- #
def test_pollinations_writes_image(tmp_path):
    provider = PollinationsVisualProvider(download=lambda url: b"\xff\xd8imagebytes")
    asset = provider.fetch(_scene(2, query="sunset over city"), tmp_path)
    assert asset.visual_type is VisualType.GENERATED_IMAGE
    assert asset.path.exists()
    assert "sunset" in asset.source_url and "seed=2" in asset.source_url


def test_pollinations_empty_raises(tmp_path):
    provider = PollinationsVisualProvider(download=lambda url: b"")
    with pytest.raises(VisualError):
        provider.fetch(_scene(0), tmp_path)


# --- Pexels ---------------------------------------------------------------- #
PEXELS_JSON = {
    "videos": [
        {
            "duration": 12,
            "video_files": [
                {"width": 640, "height": 360, "link": "land.mp4"},  # landscape
                {"width": 1080, "height": 1920, "link": "port.mp4"},  # portrait
            ],
        }
    ]
}


def test_pexels_picks_portrait_and_downloads(tmp_path):
    provider = PexelsVisualProvider(
        api_key="k",
        search=lambda q: PEXELS_JSON,
        download=lambda url: b"videobytes",
    )
    asset = provider.fetch(_scene(1), tmp_path)
    assert asset.visual_type is VisualType.STOCK_VIDEO
    assert asset.source_url == "port.mp4"
    assert asset.width == 1080 and asset.height == 1920
    assert asset.duration_seconds == 12.0
    assert asset.path.exists()


def test_pexels_no_portrait_raises(tmp_path):
    only_landscape = {
        "videos": [{"video_files": [{"width": 1920, "height": 1080, "link": "l.mp4"}]}]
    }
    provider = PexelsVisualProvider(
        api_key="k", search=lambda q: only_landscape, download=lambda url: b"x"
    )
    with pytest.raises(VisualError):
        provider.fetch(_scene(0), tmp_path)


# --- factory --------------------------------------------------------------- #
def test_factory_skips_pexels_without_key():
    config = AssetsConfig(providers=["pexels", "pollinations"])
    providers = build_visual_providers(config)
    assert [p.name for p in providers] == ["pollinations"]


def test_factory_includes_pexels_with_key():
    config = AssetsConfig(providers=["pexels", "pollinations"])
    config.stock.pexels_api_key = "present"
    providers = build_visual_providers(config)
    assert {p.name for p in providers} == {"pexels", "pollinations"}
