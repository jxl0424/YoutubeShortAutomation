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

import shutil
import subprocess
from pathlib import Path
from typing import Any, ClassVar

from trend_intelligence.logging.setup import get_logger

from ...domain.exceptions import RenderError
from ...domain.interfaces import VideoRenderer
from ...domain.models import RenderedVideo, RenderRequest, RenderScene, VisualType

_VIDEO_TYPES = {VisualType.STOCK_VIDEO, VisualType.AI_VIDEO}


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

            clips = [self._scene_clip(s, request, opened) for s in request.scenes]
            if not clips:
                raise RenderError("no scenes to render")

            video = concatenate_videoclips(clips, method="compose")
            duration = min(video.duration, total)
            video = video.subclipped(0, duration)
            video = video.with_audio(
                self._build_audio(audio, request, duration, opened)
            )

            raw_path = request.output_path.with_name("render_raw.mp4")
            video.write_videofile(
                str(raw_path),
                fps=request.fps,
                codec="libx264",
                audio_codec="aac",
                bitrate=request.bitrate,
                threads=4,
                logger=None,
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
    def _scene_clip(
        self, scene: RenderScene, request: RenderRequest, opened: list[Any]
    ) -> Any:
        from moviepy import VideoFileClip

        w, h, d = request.width, request.height, scene.duration_seconds
        if scene.visual_type in _VIDEO_TYPES:
            clip = VideoFileClip(str(scene.asset_path)).without_audio()
            opened.append(clip)
            clip = self._fit_video(clip, d)
            return self._fill(clip, w, h)

        base = self._still_clip(scene.asset_path, w, h, d)
        if not request.ken_burns:
            return base
        return self._ken_burns(base, w, h, d)

    def _still_clip(self, path: Path, w: int, h: int, d: float) -> Any:
        from moviepy import ImageClip

        # Generated images can come back well below the frame size (Pollinations
        # caps at 576x1024), so a naive fill upscales them soft. Upscale with
        # Lanczos + an unsharp mask first, then the clip is already frame-sized.
        try:
            return ImageClip(self._upscale_sharpen(path, w, h)).with_duration(d)
        except Exception:
            self._logger.warning("still_upscale_failed", path=str(path))
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
            return CompositeAudioClip([narration, music])
        except Exception as exc:
            self._logger.warning("music_mix_failed", error=str(exc))
            return narration

    # --- finalize (burn subtitles or move raw into place) ---------------- #
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
            subprocess.run(
                [
                    ffmpeg,
                    "-y",
                    "-i",
                    str(raw_path.resolve()),
                    "-vf",
                    f"subtitles={subtitle_path.name}",
                    *quality,
                    "-c:a",
                    "copy",
                    str(request.output_path.resolve()),
                ],
                cwd=str(subtitle_path.resolve().parent),
                check=True,
                capture_output=True,
            )
            raw_path.unlink(missing_ok=True)
        except Exception as exc:
            self._logger.warning("subtitle_burn_failed", error=str(exc))
            shutil.move(str(raw_path), str(request.output_path))
