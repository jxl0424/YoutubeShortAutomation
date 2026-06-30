"""Builds the configured voice provider.

Default is edge-tts (credential-free). Future providers (ElevenLabs, Azure
Speech, Google TTS) implement the same :class:`VoiceProvider` interface and are
added here without touching the stage.
"""

from __future__ import annotations

from ...config.settings import VoiceConfig
from ...domain.exceptions import ShortsConfigurationError
from ...domain.interfaces import VoiceProvider
from .edge_tts_provider import EdgeTTSVoiceProvider
from .kokoro_provider import KokoroVoiceProvider


def build_voice_provider(config: VoiceConfig) -> VoiceProvider:
    if config.provider == "edge_tts":
        return EdgeTTSVoiceProvider()
    if config.provider == "kokoro":
        return KokoroVoiceProvider(
            model_path=config.kokoro_model_path,
            voices_path=config.kokoro_voices_path,
        )
    raise ShortsConfigurationError(f"unknown voice provider: {config.provider!r}")
