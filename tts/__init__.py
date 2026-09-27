"""Stage 6 Text-to-Speech and voice response output."""
from .audio import AudioOutput, WindowsDefaultAudioOutput
from .pipeline import AssistantResponse, TTSPipeline, build_pipeline
from .provider import TTSProvider, WindowsSAPIProvider, build_provider
from .response import response_text
from .result import (
    TTSConfigurationError,
    TTSError,
    TTSPlaybackError,
    TTSResult,
    TTSStatus,
    TTSSynthesisError,
    TTSTextError,
    TTSTimeoutError,
)

__all__ = [
    "AudioOutput", "WindowsDefaultAudioOutput", "AssistantResponse", "TTSPipeline", "build_pipeline",
    "TTSProvider", "WindowsSAPIProvider", "build_provider", "response_text",
    "TTSConfigurationError", "TTSError", "TTSPlaybackError", "TTSResult", "TTSStatus",
    "TTSSynthesisError", "TTSTextError", "TTSTimeoutError",
]
