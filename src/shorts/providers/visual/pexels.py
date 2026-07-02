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
        # A wider page gives the slug re-ranker real candidates to find a
        # topical match in; with 5, an off-topic first page was game over.
        per_page: int = 15,
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
    def _pick(
        self, data: dict[str, Any], query: str = ""
    ) -> tuple[str, int, int, float | None]:
        # Pexels search order is only roughly topical ("northern lights glowing
        # green" can lead with a green-lit city). Each video's page URL carries
        # a descriptive slug, so prefer the candidate whose slug shares the most
        # content words with the query; Pexels' own order breaks ties — and
        # decides outright when no slug overlaps (the previous behavior).
        query_tokens = self._tokens(query)
        candidates: list[tuple[int, int, tuple[str, int, int, float | None]]] = []
        for order, video in enumerate(data.get("videos") or []):
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
            if best is None:
                continue
            overlap = len(query_tokens & self._slug_tokens(video))
            candidates.append((-overlap, order, best))
        if not candidates:
            raise VisualError("pexels returned no suitable portrait video")
        candidates.sort(key=lambda c: (c[0], c[1]))
        return candidates[0][2]

    # Grammar words carry no topical signal in either slugs or queries.
    _STOPWORDS: ClassVar[set[str]] = {
        "a",
        "an",
        "and",
        "at",
        "for",
        "in",
        "of",
        "on",
        "over",
        "the",
        "to",
        "with",
    }

    @classmethod
    def _tokens(cls, text: str) -> set[str]:
        return {
            t for t in re.findall(r"[a-z0-9]+", text.lower()) if t not in cls._STOPWORDS
        }

    @classmethod
    def _slug_tokens(cls, video: dict[str, Any]) -> set[str]:
        match = re.search(r"/video/([a-z0-9-]+?)(?:-\d+)?/?$", video.get("url") or "")
        if match is None:
            return set()
        return cls._tokens(match.group(1).replace("-", " "))

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
            search_query = self._search_query(scene.visual_query)
            data = self._search(search_query)
            link, width, height, duration = self._pick(data, search_query)
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
