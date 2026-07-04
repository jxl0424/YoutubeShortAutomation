"""Pillow thumbnail renderer.

Builds a vertical thumbnail: a background (the first scene image, cover-cropped,
or a solid fallback), a semi-transparent band, a bold wrapped title, and optional
branding. Pillow is imported lazily. Font lookup degrades gracefully (system bold
font → Pillow's scalable default) so it works on any machine.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, ClassVar

from trend_intelligence.logging.setup import get_logger

from ...domain.interfaces import ThumbnailRenderer
from ...domain.models import ThumbnailRequest, ThumbnailResult
from ..fonts import load_bold_font, wrap_text


class PillowThumbnailRenderer(ThumbnailRenderer):
    name: ClassVar[str] = "pillow"

    def __init__(self) -> None:
        self._logger = get_logger("shorts.thumbnail")

    def render(self, request: ThumbnailRequest) -> ThumbnailResult:
        from PIL import Image, ImageDraw

        w, h = request.width, request.height
        image = self._background(request, w, h)

        if request.title_overlay and request.title:
            band = Image.new("RGBA", (w, h), (0, 0, 0, 0))
            self._draw_title(ImageDraw.Draw(band), request.title, w, h)
            image = Image.alpha_composite(image.convert("RGBA"), band).convert("RGB")
        if request.branding:
            draw = ImageDraw.Draw(image)
            self._draw_branding(draw, request.branding, w, h)

        request.output_path.parent.mkdir(parents=True, exist_ok=True)
        image.save(request.output_path, "PNG")
        return ThumbnailResult(path=request.output_path, width=w, height=h)

    # --- background ------------------------------------------------------ #
    _VIDEO_SUFFIXES: ClassVar[set[str]] = {".mp4", ".mov", ".webm", ".mkv"}

    def _background(self, request: ThumbnailRequest, w: int, h: int) -> Any:
        from PIL import Image

        if request.background_path and Path(request.background_path).exists():
            try:
                bg = self._open_background(Path(request.background_path))
                return self._cover(bg, w, h)
            except Exception as exc:
                self._logger.warning("thumbnail_background_failed", error=str(exc))
        return Image.new("RGB", (w, h), (20, 24, 40))

    def _open_background(self, path: Path) -> Any:
        from PIL import Image

        # Stock-video scenes are the default asset type, so the background is
        # usually an mp4 — grab a mid-clip frame instead of failing to the
        # solid fill (which is what every thumbnail silently did before).
        if path.suffix.lower() in self._VIDEO_SUFFIXES:
            from moviepy import VideoFileClip

            with VideoFileClip(str(path)) as clip:
                frame = clip.get_frame(min(1.0, clip.duration / 2))
            return Image.fromarray(frame)
        return Image.open(path).convert("RGB")

    @staticmethod
    def _cover(image: Any, w: int, h: int) -> Any:
        scale = max(w / image.width, h / image.height)
        resized = image.resize((int(image.width * scale), int(image.height * scale)))
        left = (resized.width - w) // 2
        top = (resized.height - h) // 2
        return resized.crop((left, top, left + w, top + h))

    # --- text ------------------------------------------------------------ #
    def _font(self, size: int) -> Any:
        return load_bold_font(size)

    # Bright accent strip above the title band — the classic thumbnail cue that
    # makes the text block read as designed rather than auto-generated.
    _ACCENT = (255, 196, 0, 255)

    def _draw_title(self, draw: Any, title: str, w: int, h: int) -> None:
        font_size, font, lines = self._fit_title(draw, title.upper(), w)
        line_height = int(font_size * 1.12)
        block_height = line_height * len(lines)
        top = int(h * 0.55)  # higher band leaves room for the larger type

        accent_height = max(6, h // 160)
        draw.rectangle([0, top - 24 - accent_height, w, top - 24], fill=self._ACCENT)
        draw.rectangle([0, top - 24, w, top + block_height + 24], fill=(0, 0, 0, 170))
        stroke = max(3, font_size // 14)
        for i, line in enumerate(lines):
            text_width = draw.textlength(line, font=font)
            x = (w - text_width) // 2
            draw.text(
                (x, top + i * line_height),
                line,
                font=font,
                fill=(255, 255, 255, 255),
                stroke_width=stroke,
                stroke_fill=(0, 0, 0, 255),
            )

    _MAX_LINES = 4

    def _fit_title(self, draw: Any, text: str, w: int) -> tuple[int, Any, list[str]]:
        """Largest type size (w//8 down to w//16) that wraps within _MAX_LINES.

        Words are never dropped: if even the floor size needs more lines they
        are all kept — smaller type reads better than a clipped title (which
        is what the old hard ``[:4]`` truncation produced).
        """
        max_width = w - w // 8
        floor = max(48, w // 16)
        size = max(48, w // 8)  # thumbnail-scale type (~135px at 1080w)
        while True:
            font = self._font(size)
            lines = wrap_text(draw, text, font, max_width)
            if len(lines) <= self._MAX_LINES or size <= floor:
                return size, font, lines
            size = max(floor, int(size * 0.9))

    def _draw_branding(self, draw: Any, text: str, w: int, h: int) -> None:
        font = self._font(max(24, w // 28))
        text_width = draw.textlength(text, font=font)
        draw.text(
            ((w - text_width) // 2, h - int(h * 0.07)),
            text,
            font=font,
            fill=(255, 255, 255, 230),
            stroke_width=2,
            stroke_fill=(0, 0, 0, 255),
        )
