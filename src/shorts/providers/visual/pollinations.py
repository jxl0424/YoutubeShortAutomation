"""Pollinations visual provider — credential-free AI image generation.

    GET https://image.pollinations.ai/prompt/{prompt}?width=&height=&seed=

Returns a generated image sized for vertical Shorts. No API key required, so this
is the default that lets the whole pipeline run end-to-end out of the box. The
downloader is injectable so tests never hit the network.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import ClassVar
from urllib.parse import quote

from ...domain.exceptions import VisualError
from ...domain.interfaces import VisualProvider
from ...domain.models import Scene, VisualAsset, VisualType

_BASE = "https://image.pollinations.ai/prompt/"


class PollinationsVisualProvider(VisualProvider):
    name = "pollinations"
    provides: ClassVar[set[VisualType]] = {VisualType.GENERATED_IMAGE}

    def __init__(
        self,
        *,
        width: int = 1080,
        height: int = 1920,
        timeout: float = 30.0,
        model: str | None = None,
        style: str | None = None,
        download: Callable[[str], bytes] | None = None,
    ) -> None:
        self._width = width
        self._height = height
        self._timeout = timeout
        self._model = model
        self._style = style
        self._download = download or self._http_download

    def _http_download(self, url: str) -> bytes:
        import httpx

        response = httpx.get(url, timeout=self._timeout, follow_redirects=True)
        response.raise_for_status()
        return response.content

    def _prompt(self, scene: Scene) -> str:
        # Style-anchor the LLM's visual instruction toward a consistent, realistic
        # look so generations don't drift into abstract art.
        if self._style:
            return f"{scene.visual_query}, {self._style}"
        return scene.visual_query

    def _url(self, scene: Scene) -> str:
        params = (
            f"width={self._width}&height={self._height}&nologo=true&seed={scene.index}"
        )
        if self._model:
            params += f"&model={self._model}"
        return f"{_BASE}{quote(self._prompt(scene))}?{params}"

    def fetch(self, scene: Scene, output_dir: Path) -> VisualAsset:
        output_dir.mkdir(parents=True, exist_ok=True)
        url = self._url(scene)
        try:
            data = self._download(url)
        except Exception as exc:
            raise VisualError(
                f"pollinations failed for scene {scene.index}: {exc}"
            ) from exc
        if not data:
            raise VisualError(
                f"pollinations returned empty image for scene {scene.index}"
            )

        path = output_dir / f"scene_{scene.index:02d}.jpg"
        path.write_bytes(data)
        return VisualAsset(
            scene_index=scene.index,
            visual_type=VisualType.GENERATED_IMAGE,
            path=path,
            source=self.name,
            source_url=url,
            width=self._width,
            height=self._height,
        )
