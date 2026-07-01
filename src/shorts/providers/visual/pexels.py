"""Pexels visual provider — vertical stock video (requires PEXELS_API_KEY).

    GET https://api.pexels.com/videos/search?query=&orientation=portrait

Picks a portrait video file meeting the minimum height and downloads it. Both
the search and the download are injectable so tests never hit the network.
"""

from __future__ import annotations

import os
import re
from collections.abc import Callable
from pathlib import Path
from typing import Any, ClassVar

from ...domain.exceptions import VisualError
from ...domain.interfaces import VisualProvider
from ...domain.models import Scene, VisualAsset, VisualType

_SEARCH_URL = "https://api.pexels.com/videos/search"


class PexelsVisualProvider(VisualProvider):
    name = "pexels"
    provides: ClassVar[set[VisualType]] = {VisualType.STOCK_VIDEO}

    def __init__(
        self,
        *,
        api_key: str,
        min_height: int = 1280,
        per_page: int = 5,
        timeout: float = 30.0,
        search: Callable[[str], dict[str, Any]] | None = None,
        download: Callable[[str], bytes] | None = None,
    ) -> None:
        self._api_key = api_key
        self._min_height = min_height
        self._per_page = per_page
        self._timeout = timeout
        self._search = search or self._http_search
        self._download = download  # None -> stream via httpx (see _save)

    # --- network (injectable) ------------------------------------------- #
    def _http_search(self, query: str) -> dict[str, Any]:
        import httpx

        response = httpx.get(
            _SEARCH_URL,
            params={
                "query": query,
                "orientation": "portrait",
                "per_page": self._per_page,
            },
            headers={"Authorization": self._api_key},
            timeout=self._timeout,
        )
        response.raise_for_status()
        return response.json()

    def _save(self, url: str, dest: Path) -> None:
        # Injected downloaders (tests) return bytes; the default path streams the
        # (potentially large) video to disk in chunks instead of buffering it all.
        if self._download is not None:
            dest.write_bytes(self._download(url))
            return
        import httpx

        with httpx.stream(
            "GET", url, timeout=self._timeout, follow_redirects=True
        ) as response:
            response.raise_for_status()
            with dest.open("wb") as fh:
                for chunk in response.iter_bytes():
                    fh.write(chunk)

    # --- selection ------------------------------------------------------- #
    def _pick(self, data: dict[str, Any]) -> tuple[str, int, int, float | None]:
        # Pexels returns videos in relevance order, so honor that: take the
        # first video that has a portrait file meeting the height floor (picking
        # its largest such file). Maximizing resolution across all results
        # instead would grab the biggest clip regardless of topical relevance.
        for video in data.get("videos") or []:
            duration = video.get("duration")
            best: tuple[str, int, int, float | None] | None = None
            best_height = -1
            for file in video.get("video_files") or []:
                width = int(file.get("width") or 0)
                height = int(file.get("height") or 0)
                link = file.get("link")
                if not link:
                    continue
                portrait = height >= width and height >= self._min_height
                if portrait and height > best_height:
                    best, best_height = (link, width, height, duration), height
            if best is not None:
                return best
        raise VisualError("pexels returned no suitable portrait video")

    @staticmethod
    def _search_query(query: str) -> str:
        # Stock search ranks far better on a short subject phrase than on the
        # script's full visual instruction, so drop trailing camera/direction
        # filler ("..., with the camera panning across the sky"). Take the first
        # NON-EMPTY clause so leading punctuation doesn't defeat the shortening.
        clauses = (part.strip() for part in re.split(r"[,.;]", query))
        first = next((part for part in clauses if part), "")
        return first or query

    def fetch(self, scene: Scene, output_dir: Path) -> VisualAsset:
        output_dir.mkdir(parents=True, exist_ok=True)
        path = output_dir / f"scene_{scene.index:02d}.mp4"
        # Download to a temp name, then atomically move into place, so a
        # truncated/failed download never leaves a corrupt final asset.
        tmp = path.with_name(path.name + ".part")
        try:
            data = self._search(self._search_query(scene.visual_query))
            link, width, height, duration = self._pick(data)
            self._save(link, tmp)
            if not tmp.exists() or tmp.stat().st_size == 0:
                raise VisualError(
                    f"pexels returned empty video for scene {scene.index}"
                )
            os.replace(tmp, path)
        except VisualError:
            raise
        except Exception as exc:
            raise VisualError(f"pexels failed for scene {scene.index}: {exc}") from exc
        finally:
            tmp.unlink(missing_ok=True)
        return VisualAsset(
            scene_index=scene.index,
            visual_type=VisualType.STOCK_VIDEO,
            path=path,
            source=self.name,
            source_url=link,
            width=width,
            height=height,
            duration_seconds=float(duration) if duration else None,
            license="Pexels",
        )
