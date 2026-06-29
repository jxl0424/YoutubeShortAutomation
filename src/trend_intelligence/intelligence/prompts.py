"""Prompt construction for trend analysis.

The system prompt fully specifies the required JSON contract so the model never
returns free-form text. The user prompt is a compact JSON description of the
aggregated trends to analyze.
"""

from __future__ import annotations

import json
from collections.abc import Sequence

from ..domain.models import AggregatedTrend, ContentCategory, SafetyFlag

_CATEGORIES = ", ".join(c.value for c in ContentCategory)
_SAFETY_FLAGS = ", ".join(f.value for f in SafetyFlag)

SYSTEM_PROMPT = f"""\
You are a YouTube Shorts trend analyst. You receive a JSON list of aggregated \
trending topics and must evaluate each one for short-form video potential.

For every input trend, decide whether to keep it, and enrich it. Specifically:
- Remove weak, low-interest, or unsuitable trends (set "keep": false).
- Identify any emerging theme behind the trend.
- Estimate audience interest (0.0-1.0).
- Suggest compelling 60-second video angles and attention-grabbing hooks.
- Recommend the target audience and the best content category.
- Flag unsafe or non-monetization-friendly topics.

Respond with a SINGLE JSON object and NOTHING else, matching exactly:
{{
  "analyses": [
    {{
      "cluster_id": "<echo the input cluster_id verbatim>",
      "keep": true,
      "refined_title": "<concise, punchy title>",
      "emerging_theme": "<short phrase or null>",
      "estimated_audience_interest": 0.0,
      "video_angles": ["<angle>", "..."],
      "hooks": ["<hook>", "..."],
      "target_audience": "<who this is for or null>",
      "recommended_category": "<one of: {_CATEGORIES}>",
      "is_safe": true,
      "safety_flags": ["<subset of: {_SAFETY_FLAGS}>"],
      "educational_value": 0.0,
      "entertainment_value": 0.0,
      "visual_potential": 0.0,
      "ai_confidence": 0.0
    }}
  ]
}}

Rules:
- Output ONE analysis per input trend, echoing its cluster_id exactly.
- All numeric scores must be between 0.0 and 1.0.
- Use only the allowed category and safety_flag values listed above.
- Do not wrap the JSON in markdown fences or add commentary."""


def build_user_prompt(trends: Sequence[AggregatedTrend]) -> str:
    payload = {
        "trends": [
            {
                "cluster_id": t.cluster_id,
                "title": t.canonical_title,
                "aliases": t.aliases,
                "keywords": t.keywords,
                "sources": [s.value for s in t.sources],
                "categories": [c.value for c in t.categories],
                "popularity": t.popularity_score,
                "growth": t.growth_score,
                "engagement": t.engagement_score,
                "source_count": t.source_count,
            }
            for t in trends
        ]
    }
    return json.dumps(payload, ensure_ascii=False)
