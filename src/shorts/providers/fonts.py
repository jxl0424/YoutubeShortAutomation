"""Shared Pillow text helpers for renderers (thumbnail + scene-text overlays).

Font lookup degrades gracefully (system bold TTF → Pillow's scalable default)
so rendering works on any machine without bundling a font.
"""

from __future__ import annotations

from typing import Any

FONT_CANDIDATES = (
    "C:/Windows/Fonts/arialbd.ttf",
    "C:/Windows/Fonts/Arial.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "DejaVuSans-Bold.ttf",
)


def load_bold_font(size: int) -> Any:
    from PIL import ImageFont

    for path in FONT_CANDIDATES:
        try:
            return ImageFont.truetype(path, size)
        except Exception:
            continue
    try:
        return ImageFont.load_default(size=size)
    except TypeError:  # Pillow < 10.1 has no size arg
        return ImageFont.load_default()


def wrap_text(draw: Any, text: str, font: Any, max_width: int) -> list[str]:
    """Greedy word wrap by rendered width (same rules the thumbnail used)."""
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
    return lines
