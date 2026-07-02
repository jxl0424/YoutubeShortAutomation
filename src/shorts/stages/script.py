"""Script generation stage.

Turns the ``TopicBrief`` (plus optional research) into a structured ``Script``
via the configured LLM. Output is strict JSON — never free-form text. If the LLM
cannot produce a valid script after retries, a ``ScriptGenerationError`` is
raised (you can't build a video without a script); the pipeline wraps it.
"""

from __future__ import annotations

import json

from pydantic import BaseModel, ConfigDict

from trend_intelligence.domain.exceptions import LLMError
from trend_intelligence.logging.setup import get_logger, log_duration

from ..config.settings import ScriptConfig
from ..domain.brief import TopicBrief
from ..domain.exceptions import ScriptGenerationError
from ..domain.interfaces import LLMProvider, PipelineStage
from ..domain.models import Script, ScriptScene, TopicResearch


# --------------------------------------------------------------------------- #
# LLM output schema (lenient; mapped to the strict domain Script)
# --------------------------------------------------------------------------- #
class _LLMScene(BaseModel):
    model_config = ConfigDict(extra="ignore")

    narration: str
    on_screen_text: str | None = None
    visual_instruction: str | None = None


class LLMScript(BaseModel):
    model_config = ConfigDict(extra="ignore")

    hook: str
    narration: str
    scenes: list[_LLMScene] = []
    caption_text: str | None = None
    cta: str | None = None


# --------------------------------------------------------------------------- #
# Prompts
# --------------------------------------------------------------------------- #
def build_system_prompt(config: ScriptConfig) -> str:
    cta_line = (
        "- End with a short call-to-action (subscribe/follow) in `cta`."
        if config.include_cta
        else "- Do not include a call-to-action; set `cta` to null."
    )
    return f"""\
You are a viral short-form scriptwriter for YouTube Shorts (vertical video).
Write a tight, high-retention script from the given topic brief.

Requirements:
- A scroll-stopping `hook` (one punchy sentence).
- `narration`: conversational and energetic. Choose the length yourself, between
  {config.min_words} and {config.max_words} words, based on how much genuine
  material the brief (and `research`, when present) supports. Every sentence
  must deliver a new fact or payoff — never pad. A thin topic deserves a short,
  punchy script; only go long when the material is rich.
- When `research` facts are provided, ground the narration in them and do not
  invent specifics beyond the brief and research.
- Split the narration into `scenes` of roughly 20-25 spoken words each. For
  each scene provide:
  - `narration`: that scene's spoken segment,
  - `on_screen_text`: a very short caption (a few words),
  - `visual_instruction`: a SHORT real-world subject to film, 2-5 words, leading
    with the concrete subject so it works as a stock-footage search query
    (e.g. "aurora borealis over mountains", "solar flare on the sun"). Name a
    literal, filmable thing. Do NOT describe animations, illustrations, diagrams,
    cartoons, abstract concepts, on-screen text, or camera movements.
{cta_line}

Respond with ONE JSON object and nothing else, matching exactly:
{{
  "hook": "...",
  "narration": "...",
  "scenes": [
    {{"narration": "...", "on_screen_text": "...", "visual_instruction": "..."}}
  ],
  "caption_text": "<one-line caption for the whole short or null>",
  "cta": "<call to action or null>"
}}
Do not wrap the JSON in markdown fences or add commentary."""


def build_user_prompt(
    brief: TopicBrief, research: TopicResearch | None, config: ScriptConfig
) -> str:
    payload: dict[str, object] = {
        "title": brief.title,
        "category": brief.category,
        "keywords": brief.keywords,
        "target_audience": brief.target_audience,
        "hook_idea": brief.hook_idea,
        "visual_suggestions": brief.visual_suggestions,
        "angle": brief.reasoning,
        "word_target": {"min": config.min_words, "max": config.max_words},
    }
    if research is not None:
        payload["research"] = {
            "facts": research.facts,
            "statistics": research.statistics,
            "dates": research.dates,
            "context": research.context,
        }
    return json.dumps(payload, ensure_ascii=False)


# --------------------------------------------------------------------------- #
# Stage
# --------------------------------------------------------------------------- #
class ScriptGenerator(PipelineStage):
    name = "script_generation"

    def __init__(self, llm: LLMProvider, *, max_retries: int = 2) -> None:
        self._llm = llm
        self._max_retries = max_retries
        self._logger = get_logger("shorts.script")

    def run(self, ctx) -> None:
        config = ctx.config.script
        system = build_system_prompt(config)
        user = build_user_prompt(ctx.brief, ctx.research, config)

        with log_duration(self._logger, "script_generation", title=ctx.brief.title):
            llm_script = self._generate(system, user)

        ctx.script = self._to_script(llm_script)
        self._logger.info(
            "script_generated",
            words=ctx.script.word_count,
            scenes=len(ctx.script.scenes),
        )

    def _generate(self, system: str, user: str) -> LLMScript:
        last_error: Exception | None = None
        for attempt in range(self._max_retries + 1):
            try:
                result = self._llm.generate_structured(
                    system=system, user=user, schema=LLMScript
                )
                if not isinstance(result, LLMScript):
                    raise LLMError(f"expected LLMScript, got {type(result).__name__}")
                return result
            except LLMError as exc:
                last_error = exc
                self._logger.warning(
                    "script_attempt_failed", attempt=attempt + 1, error=str(exc)
                )
        raise ScriptGenerationError(
            f"script generation failed after retries: {last_error}"
        )

    def _to_script(self, llm_script: LLMScript) -> Script:
        scenes = [
            ScriptScene(
                index=i,
                narration=scene.narration,
                on_screen_text=scene.on_screen_text,
                visual_instruction=scene.visual_instruction,
            )
            for i, scene in enumerate(llm_script.scenes)
        ]
        return Script(
            hook=llm_script.hook,
            narration=llm_script.narration,
            scenes=scenes,
            caption_text=llm_script.caption_text,
            cta=llm_script.cta,
            word_count=len(llm_script.narration.split()),
        )
