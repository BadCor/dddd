"""Stage 5 microphone -> STT -> existing Stage 4 text pipeline."""
from __future__ import annotations

import logging

from core.errors import ErrorCategory, error_info
from dataclasses import dataclass

from llm.pipeline import LLMCommandPipeline, LLMRunResult

from .microphone import Microphone
from .provider import SpeechRecognitionProvider
from .result import SpeechError, SpeechResult, SpeechStatus

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class VoiceRunResult:
    speech: SpeechResult
    command: LLMRunResult | None = None


class SpeechPipeline:
    def __init__(self, microphone: Microphone, provider: SpeechRecognitionProvider | None, command_pipeline: LLMCommandPipeline):
        self.microphone = microphone
        self.provider = provider
        self.command_pipeline = command_pipeline

    def close(self) -> None:
        """Release microphone/provider resources owned by this pipeline."""
        try:
            self.microphone.close()
        finally:
            close = getattr(self.provider, "close", None)
            if callable(close):
                try:
                    close()
                except Exception:
                    logger.debug("Speech provider cleanup failed.", exc_info=False)

    def listen_once(self, *, cancel_requested: callable | None = None) -> VoiceRunResult:
        try:
            audio = self.microphone.record()
        except SpeechError as exc:
            result = self._speech_error(exc)
            logger.warning("Voice input failed: %s", error_info(exc, category=ErrorCategory.AUDIO, user_message=result.message).diagnostic)
            return VoiceRunResult(result)
        except Exception as exc:
            info = error_info(exc, category=ErrorCategory.INTERNAL, user_message="Microphone input failed.")
            logger.error("Unexpected microphone failure: %s", info.diagnostic)
            return VoiceRunResult(SpeechResult(SpeechStatus.ERROR, message=info.user_message, error_info=info))

        if self.provider is None:
            return VoiceRunResult(SpeechResult(SpeechStatus.ERROR, message="Speech recognition provider is not configured."))
        try:
            text = self.provider.transcribe(audio, filename="speech.wav").strip()
        except SpeechError as exc:
            info = error_info(exc, category=ErrorCategory.NETWORK, user_message=str(exc))
            logger.warning("Speech recognition failed: %s", info.diagnostic)
            return VoiceRunResult(SpeechResult(SpeechStatus.ERROR, message=info.user_message, error_info=info))
        except Exception as exc:
            info = error_info(exc, category=ErrorCategory.INTERNAL, user_message="Speech recognition failed.")
            logger.error("Unexpected speech recognition failure: %s", info.diagnostic)
            return VoiceRunResult(SpeechResult(SpeechStatus.ERROR, message=info.user_message, error_info=info))

        if not text:
            return VoiceRunResult(SpeechResult(SpeechStatus.NO_SPEECH, message="No speech was detected."))

        speech = SpeechResult(SpeechStatus.SUCCESS, text=text, message="Speech recognized.")
        # Critical invariant: recognized text is the only thing passed onward.
        return VoiceRunResult(speech, self.command_pipeline.handle(text))

    @staticmethod
    def _speech_error(exc: SpeechError) -> SpeechResult:
        message = str(exc) or "Voice input failed."
        return SpeechResult(SpeechStatus.ERROR, message=message)
