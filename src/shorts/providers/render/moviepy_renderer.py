"""MoviePy/FFmpeg video renderer.

Assembles narration audio + per-scene visuals into a vertical MP4. Stills get a
subtle Ken Burns zoom; videos are filled/cropped to frame; background music is
mixed under the narration; subtitles are burned via FFmpeg as a best-effort
post-step (the SRT is always packaged for soft subs regardless).

MoviePy is imported lazily so the module loads without it; FFmpeg is provided by
imageio-ffmpeg (no system install required). Enhancements are individually
wrapped so a failing nicety never fails the core render.
"""

from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path
from typing import Any, ClassVar

from trend_intelligence.logging.setup import get_logger

from ...domain.exceptions import RenderError
from ...domain.interfaces import VideoRenderer
from ...domain.models import RenderedVideo, RenderRequest, RenderScene, VisualType

_VIDEO_TYPES = {VisualType.STOCK_VIDEO, VisualType.AI_VIDEO}

# Crossfade length between scenes (clamped to half the shortest scene).
_CROSSFADE_SECONDS = 0.3

# libass renders SRT-converted subs against a 384x288 canvas and scales to the
# output, so pixel sizes from config must be expressed in that coordinate space.
_ASS_PLAY_RES_Y = 288

_NAMED_COLORS = {
    "white": (255, 255, 255),
    "black": (0, 0, 0),
    "yellow": (255, 255, 0),
    "red": (255, 0, 0),
    "green": (0, 255, 0),
    "blue": (0, 0, 255),
    "cyan": (0, 255, 255),
    "magenta": (255, 0, 255),
    "orange": (255, 165, 0),
}

# ASS numpad alignment + vertical margin (in PlayRes units) per position.
_POSITIONS = {"bottom": (2, 50), "center": (5, 0), "top": (8, 30)}


class MoviePyRenderer(VideoRenderer):
    name: ClassVar[str] = "moviepy"

    def __init__(self) -> None:
        self._logger = get_logger("shorts.render")

    def render(self, request: RenderRequest) -> RenderedVideo:
        from moviepy import AudioFileClip, concatenate_videoclips

        request.output_path.parent.mkdir(parents=True, exist_ok=True)
        opened: list[Any] = []
        try:
            audio = AudioFileClip(str(request.audio_path))
            opened.append(audio)
            total = audio.duration

            if not request.scenes:
                raise RenderError("no scenes to render")
            fade = self._fade_seconds(request)
            # Crossfading overlaps scene boundaries, so every clip except the
            # last carries `fade` extra seconds of content to fade over —
            # scene start times (and narration/caption sync) stay untouched.
            clips = [
                self._scene_clip(
                    s,
                    request,
                    opened,
                    extra=fade if i < len(request.scenes) - 1 else 0.0,
                )
                for i, s in enumerate(request.scenes)
            ]
            # Derived/composite clips hold their own reader handles; track them
            # alongside the file-opened clips so the finally block closes all.
            opened.extend(clips)

            if fade:
                video = self._crossfade(clips, request, fade)
            else:
                video = concatenate_videoclips(clips, method="compose")
            opened.append(video)

            if request.scene_text:
                # Best-effort like Ken Burns/music: a failed overlay never
                # fails the render.
                try:
                    overlays = self._text_overlays(request)
                    if overlays:
                        from moviepy import CompositeVideoClip

                        opened.extend(overlays)
                        video = CompositeVideoClip(
                            [video, *overlays],
                            size=(request.width, request.height),
                        )
                        opened.append(video)
                except Exception as exc:
                    self._logger.warning("scene_text_failed", error=str(exc))

            duration = min(video.duration, total)
            video = video.subclipped(0, duration)
            opened.append(video)
            video = video.with_audio(
                self._build_audio(audio, request, duration, opened)
            )
            opened.append(video)

            raw_path = request.output_path.with_name("render_raw.mp4")
            video.write_videofile(
                str(raw_path),
                fps=request.fps,
                codec="libx264",
                audio_codec="aac",
                bitrate=request.bitrate,
                threads=4,
                logger=None,
                # Keep MoviePy's *TEMP_MPY_* audio scratch file in the work dir
                # (default is the process CWD, which litters the repo on crash).
                temp_audiofile_path=str(raw_path.parent),
            )
        except RenderError:
            raise
        except Exception as exc:
            raise RenderError(f"video assembly failed: {exc}") from exc
        finally:
            for clip in opened:
                try:
                    clip.close()
                except Exception:
                    pass

        self._finalize(raw_path, request)
        return RenderedVideo(
            path=request.output_path,
            width=request.width,
            height=request.height,
            fps=request.fps,
            duration_seconds=round(duration, 3),
            bitrate=request.bitrate,
        )

    # --- scene clips ----------------------------------------------------- #
    @staticmethod
    def _fade_seconds(request: RenderRequest) -> float:
        if not request.transitions or len(request.scenes) < 2:
            return 0.0
        shortest = min(s.duration_seconds for s in request.scenes)
        return min(_CROSSFADE_SECONDS, shortest / 2)

    def _scene_clip(
        self,
        scene: RenderScene,
        request: RenderRequest,
        opened: list[Any],
        extra: float = 0.0,
    ) -> Any:
        from moviepy import VideoFileClip

        w, h = request.width, request.height
        d = scene.duration_seconds + extra
        if scene.visual_type in _VIDEO_TYPES:
            clip = VideoFileClip(str(scene.asset_path)).without_audio()
            opened.append(clip)
            clip = self._fit_video(clip, d)
            return self._fill(clip, w, h)

        base = self._still_clip(scene.asset_path, w, h, d)
        if not request.ken_burns:
            return base
        return self._ken_burns(base, w, h, d)

    def _crossfade(self, clips: list[Any], request: RenderRequest, fade: float) -> Any:
        """Composite scene clips at their planned start times with crossfades."""
        try:
            from moviepy import CompositeVideoClip, vfx

            placed, start = [], 0.0
            for i, (clip, scene) in enumerate(zip(clips, request.scenes, strict=True)):
                clip = clip.with_start(start)
                if i > 0:
                    clip = clip.with_effects([vfx.CrossFadeIn(fade)])
                placed.append(clip)
                start += scene.duration_seconds
            return CompositeVideoClip(
                placed, size=(request.width, request.height)
            ).with_duration(start)
        except Exception as exc:
            # Fallback concatenates the padded clips (slightly long; render()
            # trims to the narration), so a failed nicety never fails the run.
            self._logger.warning("crossfade_failed", error=str(exc))
            from moviepy import concatenate_videoclips

            return concatenate_videoclips(clips, method="compose")

    # --- scene-text overlays ---------------------------------------------- #
    def _text_overlays(self, request: RenderRequest) -> list[Any]:
        """One timed transparent text strip per scene with on_screen_text."""
        overlays: list[Any] = []
        start = 0.0
        for scene in request.scenes:
            text = (scene.on_screen_text or "").strip()
            if text:
                clip = self._text_clip(text, request)
                overlays.append(
                    clip.with_start(start).with_duration(scene.duration_seconds)
                )
            start += scene.duration_seconds
        return overlays

    def _text_clip(self, text: str, request: RenderRequest) -> Any:
        import numpy as np
        from moviepy import ImageClip
        from PIL import Image, ImageDraw

        from ..fonts import load_bold_font, wrap_text

        w = request.width
        font_size = max(32, w // 15)  # ~72px at 1080w
        font = load_bold_font(font_size)
        stroke = max(3, font_size // 9)  # heavier stroke for pop on any bg

        probe = ImageDraw.Draw(Image.new("RGBA", (1, 1)))
        lines = wrap_text(probe, text.upper(), font, int(w * 0.86))[:2]
        line_height = int(font_size * 1.2)
        pad_x, pad_y = font_size // 2, font_size // 6  # pill padding around text

        strip = Image.new(
            "RGBA", (w, line_height * len(lines) + stroke * 2 + 16), (0, 0, 0, 0)
        )
        draw = ImageDraw.Draw(strip)
        for i, line in enumerate(lines):
            text_width = draw.textlength(line, font=font)
            x = (w - text_width) // 2
            y = stroke + i * line_height
            # Semi-transparent rounded pill behind the text so it stays legible
            # over bright footage (flag/sky/pale rooms washed out plain white).
            draw.rounded_rectangle(
                [x - pad_x, y - pad_y, x + text_width + pad_x, y + font_size + pad_y],
                radius=font_size // 3,
                fill=(0, 0, 0, 140),
            )
            draw.text(
                (x, y),
                line,
                font=font,
                fill=(255, 255, 255, 255),
                stroke_width=stroke,
                stroke_fill=(0, 0, 0, 255),
            )
        # Top-center (~20% down): clear of the YouTube Shorts UI (channel/
        # subscribe crowd the top edge) and the burned captions at the bottom.
        clip = ImageClip(np.asarray(strip), transparent=True)
        return clip.with_position((0, int(request.height * 0.20)))

    def _still_clip(self, path: Path, w: int, h: int, d: float) -> Any:
        from moviepy import ImageClip

        # Generated images can come back well below the frame size (Pollinations
        # caps at 576x1024), so a naive fill upscales them soft. Upscale with
        # Lanczos + an unsharp mask first, then the clip is already frame-sized.
        try:
            return ImageClip(self._upscale_sharpen(path, w, h)).with_duration(d)
        except Exception as exc:
            self._logger.warning("still_upscale_failed", path=str(path), error=str(exc))
            return self._fill(ImageClip(str(path)).with_duration(d), w, h)

    @staticmethod
    def _upscale_sharpen(path: Path, w: int, h: int) -> Any:
        import numpy as np
        from PIL import Image, ImageFilter

        img = Image.open(path).convert("RGB")
        scale = max(w / img.width, h / img.height)
        img = img.resize(
            (round(img.width * scale), round(img.height * scale)), Image.LANCZOS
        )
        if scale > 1.0:
            img = img.filter(
                ImageFilter.UnsharpMask(radius=2.2, percent=130, threshold=2)
            )
        left, top = (img.width - w) // 2, (img.height - h) // 2
        return np.asarray(img.crop((left, top, left + w, top + h)))

    def _fit_video(self, clip: Any, duration: float) -> Any:
        if clip.duration >= duration:
            return clip.subclipped(0, duration)
        try:
            from moviepy import vfx

            return clip.with_effects([vfx.Loop(duration=duration)])
        except Exception:
            self._logger.warning("video_loop_failed", duration=duration)
            return clip

    @staticmethod
    def _fill(clip: Any, w: int, h: int) -> Any:
        scale = max(w / clip.w, h / clip.h)
        clip = clip.resized(scale)
        return clip.cropped(width=w, height=h, x_center=clip.w / 2, y_center=clip.h / 2)

    def _ken_burns(self, base: Any, w: int, h: int, d: float) -> Any:
        try:
            from moviepy import CompositeVideoClip

            zoom = base.resized(lambda t: 1 + 0.08 * (t / d)).with_position(
                ("center", "center")
            )
            return CompositeVideoClip([zoom], size=(w, h)).with_duration(d)
        except Exception:
            self._logger.warning("ken_burns_failed")
            return base

    # --- audio ----------------------------------------------------------- #
    def _build_audio(
        self, narration: Any, request: RenderRequest, duration: float, opened: list[Any]
    ) -> Any:
        narration = narration.subclipped(0, duration)
        opened.append(narration)
        if not (request.music_path and Path(request.music_path).exists()):
            return narration
        try:
            from moviepy import AudioFileClip, CompositeAudioClip, afx

            music = AudioFileClip(str(request.music_path))
            opened.append(music)
            if music.duration < duration:
                music = music.with_effects([afx.AudioLoop(duration=duration)])
            else:
                music = music.subclipped(0, duration)
            music = music.with_effects([afx.MultiplyVolume(request.music_volume)])
            opened.append(music)
            mixed = CompositeAudioClip([narration, music])
            opened.append(mixed)
            return mixed
        except Exception as exc:
            self._logger.warning("music_mix_failed", error=str(exc))
            return narration

    # --- finalize (burn subtitles or move raw into place) ---------------- #
    def _force_style(self, request: RenderRequest) -> str:
        """Map the semantic subtitle style to an ASS force_style override."""
        # Bold text with a solid outline is the standard Shorts caption look;
        # these aren't configurable, they just make any font/color readable.
        parts = [f"FontName={request.subtitle_font}", "Bold=1", "Outline=1.5"]
        size = round(request.subtitle_font_size * _ASS_PLAY_RES_Y / request.height)
        parts.append(f"FontSize={max(size, 1)}")
        color = self._ass_color(request.subtitle_color)
        if color:
            parts.append(f"PrimaryColour={color}")
        position = _POSITIONS.get(request.subtitle_position.strip().lower())
        if position:
            alignment, margin_v = position
            parts.append(f"Alignment={alignment}")
            if margin_v:
                parts.append(f"MarginV={margin_v}")
        return ",".join(parts)

    @staticmethod
    def _ass_color(color: str) -> str | None:
        """Convert a color name or #RRGGBB to ASS &H00BBGGRR (BGR order)."""
        normalized = color.strip().lower()
        rgb = _NAMED_COLORS.get(normalized)
        if rgb is None and re.fullmatch(r"#?[0-9a-f]{6}", normalized):
            hex_value = normalized.lstrip("#")
            rgb = tuple(int(hex_value[i : i + 2], 16) for i in (0, 2, 4))
        if rgb is None:
            return None
        r, g, b = rgb
        return f"&H00{b:02X}{g:02X}{r:02X}"

    def _finalize(self, raw_path: Path, request: RenderRequest) -> None:
        subtitle = request.subtitle_path
        if not (request.burn_subtitles and subtitle and Path(subtitle).exists()):
            shutil.move(str(raw_path), str(request.output_path))
            return
        try:
            import imageio_ffmpeg

            ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
            # Burning subtitles forces a video re-encode; mirror the configured
            # quality target here, otherwise this pass falls back to libx264's
            # default CRF and discards the bitrate MoviePy used for the raw file
            # (which is what made low-detail renders come out blurry).
            quality = ["-c:v", "libx264", "-preset", "medium", "-pix_fmt", "yuv420p"]
            if request.bitrate:
                quality += ["-b:v", request.bitrate]
            # Run in the subtitle's directory so the filter gets a bare filename
            # (avoids Windows path-escaping issues in the subtitles filter). The
            # in/out video paths must be absolute since cwd changes underneath us.
            subtitle_path = Path(subtitle)
            style = self._force_style(request)
            subprocess.run(
                [
                    ffmpeg,
                    "-y",
                    "-i",
                    str(raw_path.resolve()),
                    "-vf",
                    f"subtitles={subtitle_path.name}:force_style='{style}'",
                    *quality,
                    "-c:a",
                    "copy",
                    str(request.output_path.resolve()),
                ],
                cwd=str(subtitle_path.resolve().parent),
                check=True,
                capture_output=True,
                timeout=600,
            )
            raw_path.unlink(missing_ok=True)
        except Exception as exc:
            # Degrade gracefully (ship the raw video + packaged soft-sub SRT),
            # but surface ffmpeg's stderr so burn failures are diagnosable.
            stderr = getattr(exc, "stderr", None)
            if isinstance(stderr, bytes):
                stderr = stderr.decode(errors="replace")
            self._logger.error(
                "subtitle_burn_failed",
                error=str(exc),
                ffmpeg_stderr=(stderr or "")[-2000:],
            )
            shutil.move(str(raw_path), str(request.output_path))
