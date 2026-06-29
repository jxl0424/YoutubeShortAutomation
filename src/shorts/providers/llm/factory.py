"""Builds the script-generation LLM from configuration.

Maps provider names to their OpenAI-compatible endpoints and default models, then
assembles a primary + fallback chain — skipping any provider whose API key is not
present so the pipeline degrades gracefully to whatever is configured.
"""

from __future__ import annotations

import os

from ...config.settings import ScriptConfig
from ...domain.exceptions import ScriptGenerationError
from ...domain.interfaces import LLMProvider
from .fallback import FallbackLLM
from .openai_compatible import OpenAICompatibleLLM

# Provider name -> OpenAI-compatible base URL.
ENDPOINTS = {
    "gemini_flash": "https://generativelanguage.googleapis.com/v1beta/openai/",
    "groq": "https://api.groq.com/openai/v1",
    "openrouter": "https://openrouter.ai/api/v1",
    "nvidia_nim": "https://integrate.api.nvidia.com/v1",
}

# Env var holding each provider's API key.
KEY_ENVS = {
    "gemini_flash": "GEMINI_API_KEY",
    "groq": "GROQ_API_KEY",
    "openrouter": "OPENROUTER_API_KEY",
    "nvidia_nim": "NVIDIA_API_KEY",
}

# Sensible default model per provider (used for fallbacks).
DEFAULT_MODELS = {
    "gemini_flash": "gemini-2.0-flash",
    "groq": "llama-3.3-70b-versatile",
    "openrouter": "meta-llama/llama-3.3-70b-instruct",
    "nvidia_nim": "meta/llama-3.1-70b-instruct",
}


def build_script_llm(config: ScriptConfig) -> LLMProvider:
    """Assemble the primary + fallback LLM chain from config and env keys."""
    order = [config.provider, *config.fallback_providers]
    chain: list[LLMProvider] = []

    for index, name in enumerate(order):
        base_url = ENDPOINTS.get(name)
        if base_url is None:
            continue  # unknown provider name — skip
        # Primary uses the resolved config key; fallbacks read their own env var.
        api_key = (
            config.api_key
            if index == 0 and config.api_key
            else os.getenv(KEY_ENVS.get(name, ""))
        )
        if not api_key:
            continue  # no credentials for this provider — skip it
        model = config.model if index == 0 else DEFAULT_MODELS.get(name, config.model)
        chain.append(
            OpenAICompatibleLLM(
                base_url=base_url,
                api_key=api_key,
                model=model,
                temperature=config.temperature,
                max_tokens=config.max_tokens,
                name=name,
            )
        )

    if not chain:
        wanted = ", ".join(KEY_ENVS.get(n, n) for n in order if n in ENDPOINTS)
        raise ScriptGenerationError(
            f"no script LLM provider available — set one of: {wanted} in .env"
        )
    return FallbackLLM(chain)
