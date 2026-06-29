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

_FONT_CANDIDATES = (
    "C:/Windows/Fonts/arialbd.ttf",
    "C:/Windows/Fonts/Arial.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "DejaVuSans-Bold.ttf",
)


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
    def _background(self, request: ThumbnailRequest, w: int, h: int) -> Any:
        from PIL import Image

        if request.background_path and Path(request.background_path).exists():
            try:
                bg = Image.open(request.background_path).convert("RGB")
                return self._cover(bg, w, h)
            except Exception as exc:
                self._logger.warning("thumbnail_background_failed", error=str(exc))
        return Image.new("RGB", (w, h), (20, 24, 40))

    @staticmethod
    def _cover(image: Any, w: int, h: int) -> Any:
        scale = max(w / image.width, h / image.height)
        resized = image.resize((int(image.width * scale), int(image.height * scale)))
        left = (resized.width - w) // 2
        top = (resized.height - h) // 2
        return resized.crop((left, top, left + w, top + h))

    # --- text ------------------------------------------------------------ #
    def _font(self, size: int) -> Any:
        from PIL import ImageFont

        for path in _FONT_CANDIDATES:
            try:
                return ImageFont.truetype(path, size)
            except Exception:
                continue
        try:
            return ImageFont.load_default(size=size)
        except TypeError:  # Pillow < 10.1 has no size arg
            return ImageFont.load_default()

    def _draw_title(self, draw: Any, title: str, w: int, h: int) -> None:
        font_size = max(36, w // 12)
        font = self._font(font_size)
        lines = self._wrap(draw, title.upper(), font, w - w // 8)
        line_height = font_size + 14
        block_height = line_height * len(lines)
        top = int(h * 0.60)

        draw.rectangle([0, top - 24, w, top + block_height + 24], fill=(0, 0, 0, 150))
        stroke = max(2, font_size // 18)
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

    @staticmethod
    def _wrap(draw: Any, text: str, font: Any, max_width: int) -> list[str]:
        lines: list[str] = []
        current = ""
        for word in text.split():
            candidate = f"{current} {word}".strip()
            if draw.textlength(candidate, font=font) <= max_width:
                current = candidate
            else:
                if current:
                    lines.append(current)
                current = word
        if current:
            lines.append(current)
        return lines[:4]

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
