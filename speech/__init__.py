"""Stage 5 speech recognition and microphone input."""
from .microphone import Microphone, MicrophoneInfo, RecordingConfig
from .pipeline import SpeechPipeline, VoiceRunResult
from .provider import OpenAITranscriptionProvider, SpeechRecognitionProvider, build_provider
from .result import SpeechResult, SpeechStatus

__all__ = [
    "Microphone", "MicrophoneInfo", "RecordingConfig", "SpeechPipeline", "VoiceRunResult",
    "OpenAITranscriptionProvider", "SpeechRecognitionProvider", "build_provider",
    "SpeechResult", "SpeechStatus",
]
