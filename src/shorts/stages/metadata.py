"""Metadata generation stage.

Produces YouTube-Shorts-optimized metadata (title, description, tags, hashtags,
keywords) from the brief + generated script via the configured LLM. Applies
config limits (title length, tag/hashtag counts) and guarantees a ``#Shorts``
hashtag. If the LLM is unavailable, a deterministic heuristic built from the
brief + script keeps the pipeline running.
"""

from __future__ import annotations

import json
import re

from pydantic import BaseModel, ConfigDict

from trend_intelligence.domain.exceptions import LLMError
from trend_intelligence.logging.setup import get_logger, log_duration

from ..config.settings import MetadataConfig
from ..domain.brief import TopicBrief
from ..domain.interfaces import LLMProvider, PipelineStage
from ..domain.models import Script, VideoMetadata


class LLMMetadata(BaseModel):
    model_config = ConfigDict(extra="ignore")

    title: str
    description: str
    tags: list[str] = []
    hashtags: list[str] = []
    keywords: list[str] = []


def _unique(items: list[str]) -> list[str]:
    return list(dict.fromkeys(s for s in (i.strip() for i in items) if s))


def _normalize_hashtags(raw: list[str], count: int) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for candidate in ["#Shorts", *raw]:
        token = re.sub(r"[^A-Za-z0-9]", "", candidate)
        if not token:
            continue
        tag = f"#{token}"
        if tag.lower() in seen:
            continue
        seen.add(tag.lower())
        out.append(tag)
    return out[:count] if count >= 0 else out


def build_system_prompt(config: MetadataConfig, language: str) -> str:
    return f"""\
You are a YouTube Shorts SEO expert. Given a topic brief and script, write
metadata optimized for discovery on YouTube Shorts (language: {language}).

Produce:
- title: catchy, <= {config.max_title_length} characters, front-load keywords.
- description: 2-3 sentences (hook first, then value), then a line of hashtags,
  then a short call-to-action.
- tags: up to {config.max_tags} search tags (plain words, no '#').
- hashtags: {config.hashtag_count} hashtags (with '#'); always include #Shorts.
- keywords: the core SEO keywords.

Respond with ONE JSON object and nothing else:
{{"title": "...", "description": "...", "tags": ["..."], "hashtags": ["#..."], "keywords": ["..."]}}
Do not wrap in markdown fences or add commentary."""


def build_user_prompt(brief: TopicBrief, script: Script | None) -> str:
    payload: dict[str, object] = {
        "title": brief.title,
        "category": brief.category,
        "keywords": brief.keywords,
        "target_audience": brief.target_audience,
    }
    if script is not None:
        payload["hook"] = script.hook
        payload["narration"] = script.narration
        payload["cta"] = script.cta
    return json.dumps(payload, ensure_ascii=False)


class MetadataGenerator(PipelineStage):
    name = "metadata_generation"

    def __init__(self, llm: LLMProvider, *, max_retries: int = 2) -> None:
        self._llm = llm
        self._max_retries = max_retries
        self._logger = get_logger("shorts.metadata")

    def run(self, ctx) -> None:
        config = ctx.config.metadata
        language = ctx.config.language
        system = build_system_prompt(config, language)
        user = build_user_prompt(ctx.brief, ctx.script)

        with log_duration(self._logger, "metadata_generation"):
            llm_metadata = self._generate(system, user)

        if llm_metadata is None:
            ctx.metadata = self._fallback(ctx.brief, ctx.script, config, language)
        else:
            ctx.metadata = self._to_metadata(llm_metadata, config, language)

        self._logger.info(
            "metadata_generated",
            tags=len(ctx.metadata.tags),
            hashtags=len(ctx.metadata.hashtags),
            fallback=llm_metadata is None,
        )

    def _generate(self, system: str, user: str) -> LLMMetadata | None:
        last_error: Exception | None = None
        for attempt in range(self._max_retries + 1):
            try:
                result = self._llm.generate_structured(
                    system=system, user=user, schema=LLMMetadata
                )
                if not isinstance(result, LLMMetadata):
                    raise LLMError(f"expected LLMMetadata, got {type(result).__name__}")
                return result
            except LLMError as exc:
                last_error = exc
                self._logger.warning(
                    "metadata_attempt_failed", attempt=attempt + 1, error=str(exc)
                )
        self._logger.warning("metadata_fallback", error=str(last_error))
        return None

    def _to_metadata(
        self, metadata: LLMMetadata, config: MetadataConfig, language: str
    ) -> VideoMetadata:
        return VideoMetadata(
            title=metadata.title.strip()[: config.max_title_length],
            description=metadata.description.strip(),
            tags=_unique(metadata.tags)[: config.max_tags],
            hashtags=_normalize_hashtags(metadata.hashtags, config.hashtag_count),
            keywords=_unique(metadata.keywords),
            category=None,
            language=language,
        )

    def _fallback(
        self,
        brief: TopicBrief,
        script: Script | None,
        config: MetadataConfig,
        language: str,
    ) -> VideoMetadata:
        hashtags = _normalize_hashtags(
            [f"#{k}" for k in brief.keywords], config.hashtag_count
        )
        if script is not None:
            parts = [script.hook, script.narration]
            if script.cta:
                parts.append(script.cta)
        else:
            parts = [brief.title]
        parts.append(" ".join(hashtags))
        return VideoMetadata(
            title=brief.title.strip()[: config.max_title_length],
            description="\n\n".join(p for p in parts if p),
            tags=_unique(brief.keywords)[: config.max_tags],
            hashtags=hashtags,
            keywords=_unique(brief.keywords),
            category=brief.category,
            language=language,
        )
