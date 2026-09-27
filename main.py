"""Windows desktop application: GUI over the existing Stage 3–8 pipelines."""
from __future__ import annotations

import logging
import sys
from pathlib import Path

from actions.manager import ActionManager
from config import ConfigError, ConfigManager
from core.exceptions import AssistantError, StartupError
from core.errors import ErrorCategory, error_info
from core.logger import setup_logging
from core.runtime_paths import executable_root
from llm import LLMCommandPipeline, build_provider
from discovery import DiscoveryManager
from commands.discovery_pipeline import DiscoveryAwareCommandPipeline
from commands.memory_pipeline import MemoryAwareCommandPipeline
from user_data import JsonStorage, MemoryManager, SettingsManager, default_storage_path
from speech import Microphone, RecordingConfig, SpeechPipeline, build_provider as build_speech_provider
from speech.result import SpeechStatus
from tts import TTSPipeline, TTSStatus, build_pipeline, response_text

PROJECT_ROOT = executable_root()


def bootstrap() -> tuple[ConfigManager, logging.Logger]:
    config_manager = ConfigManager(PROJECT_ROOT)
    try:
        config_manager.load()
    except ConfigError as exc:
        info = error_info(exc, category=ErrorCategory.CONFIGURATION, user_message="Configuration could not be loaded safely.", recoverable=False)
        print(f"[FATAL] {info.user_message}", file=sys.stderr)
        raise StartupError(info.user_message) from exc
    logger = setup_logging(PROJECT_ROOT, config_manager.get("logging", default={}))
    logger.info("Configuration loaded successfully from '%s'.", config_manager.user_config_path)
    return config_manager, logger


def _build_pipelines(config_manager: ConfigManager, logger: logging.Logger, settings_manager: SettingsManager | None = None) -> tuple[MemoryAwareCommandPipeline, SpeechPipeline | None, TTSPipeline, MemoryManager]:
    runtime_config = settings_manager.apply_to_config(config_manager.data) if settings_manager is not None else config_manager.data
    apps = runtime_config.get("apps", {}) or {}
    manager = ActionManager(apps)
    discovery_config = runtime_config.get("discovery", {}) or {}
    try:
        discovery_manager = DiscoveryManager(discovery_config, approved_apps=apps)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Discovery configuration unavailable; discovery disabled: %s", error_info(exc, category=ErrorCategory.DISCOVERY, user_message="Discovery disabled safely.").diagnostic)
        discovery_manager = DiscoveryManager({"enabled": False}, approved_apps=apps)

    try:
        llm_provider = build_provider(runtime_config.get("llm", {}) or {})
    except Exception as exc:  # noqa: BLE001
        logger.warning("LLM configuration unavailable; using Stage 3 fallback: %s", error_info(exc, category=ErrorCategory.CONFIGURATION, user_message="LLM configuration unavailable.").diagnostic)
        llm_provider = None
    base_command_pipeline = LLMCommandPipeline(
        llm_provider, apps=apps, manager=manager, allowed_path_roots=discovery_manager.safe_path_roots
    )
    command_pipeline = DiscoveryAwareCommandPipeline(base_command_pipeline, discovery_manager, manager)

    speech_config = runtime_config.get("speech", {}) or {}
    try:
        recording = RecordingConfig(
            device_index=speech_config.get("microphone_index"),
            sample_rate=int(speech_config.get("sample_rate", 16000)),
            channels=int(speech_config.get("channels", 1)),
            start_timeout=float(speech_config.get("start_timeout", 5)),
            silence_timeout=float(speech_config.get("silence_timeout", 1.2)),
            max_duration=float(speech_config.get("max_duration", 15)),
            silence_threshold=float(speech_config.get("silence_threshold", 0.015)),
            block_duration=float(speech_config.get("block_duration", 0.2)),
        )
        microphone = Microphone(recording)
        speech_provider = build_speech_provider(speech_config)
        speech_pipeline = SpeechPipeline(microphone, speech_provider, command_pipeline)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Voice input unavailable until configured: %s", error_info(exc, category=ErrorCategory.AUDIO, user_message="Voice input unavailable.").diagnostic)
        speech_pipeline = None
    tts_config = runtime_config.get("tts", {}) or {}
    try:
        tts_pipeline = build_pipeline(tts_config)
    except Exception as exc:  # noqa: BLE001
        logger.warning("TTS configuration unavailable; keeping text responses available: %s", error_info(exc, category=ErrorCategory.AUDIO, user_message="TTS unavailable.").diagnostic)
        tts_pipeline = TTSPipeline(None, None, enabled=False)
    memory_manager = MemoryManager(
        JsonStorage(default_storage_path(config_manager.get("app", "name", default="Voice Assistant"))),
        approved_apps=apps, allowed_folder_roots=discovery_manager.safe_path_roots
    )
    memory_pipeline = MemoryAwareCommandPipeline(command_pipeline, memory_manager)
    return memory_pipeline, speech_pipeline, tts_pipeline, memory_manager


def _show_microphones(speech_pipeline: SpeechPipeline | None) -> None:
    if speech_pipeline is None:
        print("Microphone: unavailable. Check Stage 5 configuration and dependencies.")
        return
    try:
        devices = speech_pipeline.microphone.list_devices()
    except Exception as exc:  # expected device-layer errors are already sanitized
        print(f"Microphone error: {exc}")
        return
    if not devices:
        print("No microphones found.")
        return
    for device in devices:
        print(f"[{device.index}] {device.name}")


def _run_typed(command_pipeline: LLMCommandPipeline, tts_pipeline: TTSPipeline, text: str, logger: logging.Logger) -> None:
    result = command_pipeline.handle(text)
    print(f"You: {text}")
    print(f"Understood: {result.command.message}")
    if result.used_fallback:
        print("Mode: deterministic Stage 3 fallback")
    if result.action_result is not None:
        print(f"Result: {result.action_result.message if result.action_result.success else result.action_result.error}")
    else:
        print(f"Result: {result.command.status.value}")
    response = response_text(result)
    print(f"Assistant: {response}")
    tts_result = tts_pipeline.speak(response)
    if tts_result.status is TTSStatus.ERROR:
        print(f"TTS: {tts_result.message}")
    elif tts_result.status is TTSStatus.DISABLED:
        print("TTS: disabled")
    logger.info("Text command parsed=%s action_success=%s tts_status=%s", result.command.status.value, result.action_result.success if result.action_result else None, tts_result.status.value)


def _run_voice(speech_pipeline: SpeechPipeline | None, tts_pipeline: TTSPipeline, logger: logging.Logger) -> None:
    if speech_pipeline is None:
        print("Voice input is unavailable. Configure a speech provider and microphone support first.")
        return
    print("Listening... Speak now. Recording stops after silence or the maximum duration.")
    result = speech_pipeline.listen_once()
    if result.speech.status is not SpeechStatus.SUCCESS:
        print(f"Voice result: {result.speech.message}")
        return
    print(f"Recognized: {result.speech.text}")
    if result.command is not None:
        print(f"Understood: {result.command.command.message}")
        if result.command.used_fallback:
            print("Mode: deterministic Stage 3 fallback")
        if result.command.action_result is not None:
            action = result.command.action_result
            print(f"Result: {action.message if action.success else action.error}")
        else:
            print(f"Result: {result.command.command.status.value}")
        response = response_text(result.command)
        print(f"Assistant: {response}")
        tts_result = tts_pipeline.speak(response)
        if tts_result.status is TTSStatus.ERROR:
            print(f"TTS: {tts_result.message}")
        elif tts_result.status is TTSStatus.DISABLED:
            print("TTS: disabled")
    logger.info("Voice command recognized; transcript length=%d", len(result.speech.text))


def run_interactive_loop(config_manager: ConfigManager, logger: logging.Logger) -> None:
    settings_manager = SettingsManager(JsonStorage(default_storage_path(config_manager.get("app", "name", default="Voice Assistant"))))
    command_pipeline, speech_pipeline, tts_pipeline, _memory_manager = _build_pipelines(config_manager, logger, settings_manager)
    app_name = config_manager.get("app", "name", default="Voice Assistant")
    version = config_manager.get("app", "version", default="0.0.0")
    print(f"\n{app_name} v{version} - Stage 11 (Performance and Resource Management)")
    print("t = typed command | v = listen once | m = list microphones | q = quit")
    print("Voice recording is explicit and is not continuous.\n")

    while True:
        try:
            mode = input("Mode [t/v/m/q] > ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            print()
            logger.info("Shutdown requested via EOF/interrupt.")
            break
        if mode in {"q", "quit", "exit"}:
            break
        if mode == "m":
            _show_microphones(speech_pipeline)
            continue
        if mode == "v":
            _run_voice(speech_pipeline, tts_pipeline, logger)
            continue
        if mode == "t":
            try:
                text = input("> ").strip()
            except (EOFError, KeyboardInterrupt):
                print()
                break
            if text:
                _run_typed(command_pipeline, tts_pipeline, text, logger)
            continue
        print("Choose t, v, m, or q.")


def run_gui(config_manager: ConfigManager, logger: logging.Logger) -> int:
    """Start the Stage 7 GUI without changing command-processing behavior."""
    try:
        from PySide6.QtWidgets import QApplication
        from gui.main_window import MainWindow
    except ImportError as exc:
        logger.error("PySide6 is required for the desktop GUI: %s", exc)
        print("Desktop GUI requires PySide6. Install project requirements first.", file=sys.stderr)
        return 1

    settings_manager = SettingsManager(JsonStorage(default_storage_path(config_manager.get("app", "name", default="Voice Assistant"))))
    command_pipeline, speech_pipeline, tts_pipeline, memory_manager = _build_pipelines(config_manager, logger, settings_manager)
    app_name = config_manager.get("app", "name", default="Voice Assistant")
    app = QApplication.instance() or QApplication(sys.argv)
    app.setApplicationName(app_name)
    window = MainWindow(command_pipeline, speech_pipeline, tts_pipeline, app_name=app_name, settings_manager=settings_manager, memory_manager=memory_manager)
    window.show()
    return app.exec()


def main() -> int:
    logger: logging.Logger | None = None
    try:
        config_manager, logger = bootstrap()
        return run_gui(config_manager, logger)
    except StartupError:
        return 1
    except AssistantError as exc:
        if logger is not None:
            info = error_info(exc, category=ErrorCategory.INTERNAL, user_message="The assistant stopped safely.", recoverable=False)
            logger.error("Unhandled application error: %s", info.diagnostic)
        return 1
    except Exception as exc:  # noqa: BLE001
        if logger is not None:
            info = error_info(exc, category=ErrorCategory.INTERNAL, user_message="The assistant encountered an unexpected error.", recoverable=False)
            logger.critical("Unexpected application failure (%s).", type(exc).__name__)
        return 1


if __name__ == "__main__":
    sys.exit(main())
