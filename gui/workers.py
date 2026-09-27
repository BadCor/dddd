"""Background workers for the GUI.

Workers call existing application pipelines only; they contain no command
parsing or Windows-action logic of their own.
"""
from __future__ import annotations

import logging

from core.errors import ErrorCategory, error_info

from PySide6.QtCore import QThread, Signal

from speech.result import SpeechStatus
from tts.response import response_text
from localization import ru
from tts.result import TTSStatus
# Stage 7 continues to use response_text(result.command); Russian localization is applied immediately after it.

logger = logging.getLogger(__name__)


class DeviceListWorker(QThread):
    """Enumerate microphones outside the Qt GUI thread."""
    devices_ready = Signal(object)
    failed = Signal(str)

    def __init__(self, speech_pipeline) -> None:
        super().__init__()
        self.speech_pipeline = speech_pipeline

    def run(self) -> None:
        try:
            devices = self.speech_pipeline.microphone.list_devices()
            self.devices_ready.emit(devices)
        except Exception as exc:
            info = error_info(exc, category=ErrorCategory.AUDIO, user_message="Could not enumerate microphones.")
            logger.warning("Microphone enumeration failed (%s).", type(exc).__name__)
            self.failed.emit(info.user_message)


class CommandWorker(QThread):
    finished_result = Signal(object, str, object)
    failed = Signal(str)
    stage_changed = Signal(str)

    def __init__(self, command_pipeline, tts_pipeline, text: str) -> None:
        super().__init__()
        self.command_pipeline = command_pipeline
        self.tts_pipeline = tts_pipeline
        self.text = text

    def run(self) -> None:
        try:
            self.stage_changed.emit("Processing")
            result = self.command_pipeline.handle(self.text)
            response = ru(response_text(result))
            self.stage_changed.emit("Speaking")
            tts_result = self.tts_pipeline.speak(response)
            self.finished_result.emit(result, response, tts_result)
        except Exception as exc:
            info = error_info(exc, category=ErrorCategory.GUI, user_message="The command could not be processed safely.")
            logger.error("Command worker failure (%s).", type(exc).__name__)
            self.failed.emit(info.user_message)


class VoiceWorker(QThread):
    speech_result = Signal(str)
    finished_result = Signal(object, str, object)
    failed = Signal(str)
    stage_changed = Signal(str)

    def __init__(self, speech_pipeline, tts_pipeline) -> None:
        super().__init__()
        self.speech_pipeline = speech_pipeline
        self.tts_pipeline = tts_pipeline
        self._stop_requested = False

    def request_stop(self) -> None:
        self._stop_requested = True
        microphone = getattr(self.speech_pipeline, "microphone", None)
        request = getattr(microphone, "request_stop", None)
        if callable(request):
            request()
        self.requestInterruption()

    def run(self) -> None:
        try:
            self.stage_changed.emit("Listening")
            result = self.speech_pipeline.listen_once()
            if result.speech.status is not SpeechStatus.SUCCESS:
                if self._stop_requested:
                    self.failed.emit("Listening stopped.")
                else:
                    self.failed.emit(result.speech.message or "Speech recognition failed.")
                return
            self.speech_result.emit(result.speech.text)
            if result.command is None:
                self.failed.emit("The recognized speech could not be processed.")
                return
            self.stage_changed.emit("Processing")
            response = ru(response_text(result.command))
            self.stage_changed.emit("Speaking")
            tts_result = self.tts_pipeline.speak(response)
            self.finished_result.emit(result.command, response, tts_result)
        except Exception as exc:
            info = error_info(exc, category=ErrorCategory.GUI, user_message="Voice input could not be processed safely.")
            logger.error("Voice worker failure (%s).", type(exc).__name__)
            self.failed.emit(info.user_message)
