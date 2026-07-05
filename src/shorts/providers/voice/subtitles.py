"""Subtitle helpers — group word timings into caption cues and render SRT.

Pure functions (no TTS dependency) so they're trivially testable.
"""

from __future__ import annotations

from collections.abc import Sequence

from ...domain.models import CaptionCue, CaptionWord

# A timed word: (start_seconds, end_seconds, text).
TimedWord = tuple[float, float, str]


def group_words_into_cues(
    words: Sequence[TimedWord], *, max_words: int = 4, max_chars: int = 18
) -> list[CaptionCue]:
    """Chunk timed words into short karaoke-style caption cues.

    A cue closes when adding the next word would exceed ``max_words`` or (for a
    non-empty cue) ``max_chars`` of joined text — so short words show 4 to a
    screen, long words 3 or fewer. Each cue keeps its per-word timings for the
    renderer's spoken-word highlight.
    """
    cues: list[CaptionCue] = []
    chunk: list[TimedWord] = []

    def close_chunk() -> None:
        if not chunk:
            return
        cues.append(
            CaptionCue(
                index=len(cues),
                start_seconds=chunk[0][0],
                end_seconds=chunk[-1][1],
                text=" ".join(w[2] for w in chunk).strip(),
                words=[
                    CaptionWord(start_seconds=s, end_seconds=e, text=t)
                    for s, e, t in chunk
                ],
            )
        )
        chunk.clear()

    for word in words:
        joined = sum(len(w[2]) for w in chunk) + len(chunk) + len(word[2])
        if chunk and (len(chunk) >= max_words or joined > max_chars):
            close_chunk()
        chunk.append(word)
    close_chunk()
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
