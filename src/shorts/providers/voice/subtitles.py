"""Subtitle helpers — group word timings into caption cues and render SRT.

Pure functions (no TTS dependency) so they're trivially testable.
"""

from __future__ import annotations

from collections.abc import Sequence

from ...domain.models import CaptionCue

# A timed word: (start_seconds, end_seconds, text).
TimedWord = tuple[float, float, str]


def group_words_into_cues(
    words: Sequence[TimedWord], *, max_words: int = 8
) -> list[CaptionCue]:
    """Chunk timed words into readable caption cues."""
    cues: list[CaptionCue] = []
    for cue_index, start in enumerate(range(0, len(words), max_words)):
        chunk = words[start : start + max_words]
        cues.append(
            CaptionCue(
                index=cue_index,
                start_seconds=chunk[0][0],
                end_seconds=chunk[-1][1],
                text=" ".join(w[2] for w in chunk).strip(),
            )
        )
    return cues


def _format_timestamp(seconds: float) -> str:
    seconds = max(0.0, seconds)
    hours, rem = divmod(int(seconds), 3600)
    minutes, secs = divmod(rem, 60)
    millis = int(round((seconds - int(seconds)) * 1000))
    return f"{hours:02d}:{minutes:02d}:{secs:02d},{millis:03d}"


def cues_to_srt(cues: Sequence[CaptionCue]) -> str:
    blocks: list[str] = []
    for cue in cues:
        blocks.append(
            f"{cue.index + 1}\n"
            f"{_format_timestamp(cue.start_seconds)} --> "
            f"{_format_timestamp(cue.end_seconds)}\n"
            f"{cue.text}\n"
        )
    return "\n".join(blocks)
