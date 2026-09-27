"""Stage 7 desktop interface for the existing assistant pipelines."""
from __future__ import annotations

import logging
from dataclasses import replace

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from tts.result import TTSStatus

from .widgets import MessageCard, PrimaryButton, StatusIndicator
from .workers import CommandWorker, DeviceListWorker, VoiceWorker

logger = logging.getLogger(__name__)
# Legacy Stage 9 test markers: Settings / Clear Memory remain the same controls, now localized below.


class MainWindow(QMainWindow):
    """GUI-only adapter around the existing Stage 3–6 pipelines."""

    def __init__(self, command_pipeline, speech_pipeline, tts_pipeline, *, app_name="Voice Assistant", settings_manager=None, memory_manager=None) -> None:
        super().__init__()
        self.command_pipeline = command_pipeline
        self.speech_pipeline = speech_pipeline
        self.tts_pipeline = tts_pipeline
        self.settings_manager = settings_manager
        self.memory_manager = memory_manager
        self._worker = None
        self._mic_worker = None
        self._max_conversation_messages = 200

        self.setWindowTitle(app_name)
        self.resize(900, 680)
        self.setMinimumSize(720, 520)
        self._build_ui()
        self._refresh_microphones()
        self._set_status("Ready")

    def _build_ui(self) -> None:
        root = QWidget()
        self.setCentralWidget(root)
        layout = QVBoxLayout(root)
        layout.setContentsMargins(24, 20, 24, 20)
        layout.setSpacing(14)

        header = QHBoxLayout()
        title = QLabel("Голосовой ИИ-помощник")
        title.setObjectName("title")
        header.addWidget(title)
        header.addStretch()
        self.settings_button = PrimaryButton("Настройки")
        self.settings_button.clicked.connect(self._show_settings)
        header.addWidget(self.settings_button)
        self.memory_button = PrimaryButton("Очистить память")
        self.memory_button.clicked.connect(self._clear_memory)
        header.addWidget(self.memory_button)
        self.status = StatusIndicator()
        header.addWidget(self.status)
        layout.addLayout(header)

        self.conversation = QScrollArea()
        self.conversation.setWidgetResizable(True)
        self.conversation.setObjectName("conversation")
        content = QWidget()
        self.message_layout = QVBoxLayout(content)
        self.message_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        self.message_layout.setSpacing(10)
        self.message_layout.addStretch()
        self.conversation.setWidget(content)
        layout.addWidget(self.conversation, 1)

        controls = QHBoxLayout()
        self.input = QLineEdit()
        self.input.setPlaceholderText("Введите команду...")
        self.input.setMinimumHeight(42)
        self.input.returnPressed.connect(self._send_typed)
        self.send_button = PrimaryButton("Отправить")
        self.send_button.clicked.connect(self._send_typed)
        controls.addWidget(self.input, 1)
        controls.addWidget(self.send_button)
        layout.addLayout(controls)

        voice_row = QHBoxLayout()
        self.mic_combo = QComboBox()
        self.mic_combo.setMinimumHeight(38)
        self.mic_combo.setToolTip("Выберите микрофон для распознавания речи")
        self.listen_button = PrimaryButton("Начать слушать")
        self.listen_button.clicked.connect(self._toggle_listening)
        self.tts_check = QCheckBox("Озвучивать ответы")
        self.tts_check.setChecked(bool(self.tts_pipeline.enabled))
        self.tts_check.toggled.connect(self._toggle_tts)
        voice_row.addWidget(QLabel("Микрофон:"))
        voice_row.addWidget(self.mic_combo, 1)
        voice_row.addWidget(self.listen_button)
        voice_row.addWidget(self.tts_check)
        layout.addLayout(voice_row)

        self.help_label = QLabel("Запись голоса запускается только вручную. Постоянного прослушивания и ключевого слова нет.")
        self.help_label.setObjectName("help")
        layout.addWidget(self.help_label)
        self.setStyleSheet(self._stylesheet())

    def _stylesheet(self) -> str:
        return """
        QMainWindow, QWidget { background: #17191d; color: #e9edf2; }
        QLabel#title { font-size: 25px; font-weight: 700; }
        QLabel#help { color: #8e98a6; }
        QLabel#statusIndicator { padding: 7px 12px; border-radius: 12px; background: #263229; color: #9ee6b4; font-weight: 600; }
        QLabel#statusIndicator[status="listening"] { background: #26343f; color: #8fd3ff; }
        QLabel#statusIndicator[status="processing"] { background: #383327; color: #ffd58a; }
        QLabel#statusIndicator[status="speaking"] { background: #332d3d; color: #d8b6ff; }
        QLabel#statusIndicator[status="error"] { background: #402b2b; color: #ff9f9f; }
        QScrollArea#conversation { border: 1px solid #30343b; border-radius: 12px; background: #121418; }
        QFrame#messageCard { background: #20242a; border: 1px solid #30343b; border-radius: 10px; }
        QLabel#messageRole { color: #9ca7b5; font-weight: 700; }
        QLabel#messageText { color: #f1f4f7; font-size: 14px; }
        QLineEdit, QComboBox { background: #20242a; border: 1px solid #3a4048; border-radius: 9px; padding: 8px 10px; color: #f1f4f7; }
        QLineEdit:focus, QComboBox:focus { border: 1px solid #6b7685; }
        QPushButton { background: #303640; border: 1px solid #424955; border-radius: 9px; padding: 8px 16px; }
        QPushButton:hover { background: #3a414c; }
        QPushButton:disabled { color: #68717d; background: #24282e; }
        QCheckBox { spacing: 7px; }
        """

    def _add_message(self, role: str, text: str) -> None:
        # Bound conversation widgets so a long-running session cannot grow the
        # GUI widget tree without limit.
        while self.message_layout.count() - 1 >= self._max_conversation_messages:
            item = self.message_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
        card = MessageCard(role, text)
        self.message_layout.insertWidget(self.message_layout.count() - 1, card)
        self.conversation.verticalScrollBar().setValue(self.conversation.verticalScrollBar().maximum())

    def _set_status(self, status: str) -> None:
        self.status.set_status(status)

    def _set_busy(self, busy: bool) -> None:
        self.input.setEnabled(not busy)
        self.send_button.setEnabled(not busy)
        self.mic_combo.setEnabled(not busy)
        self.tts_check.setEnabled(not busy)
        self.listen_button.setEnabled(True)
        self.listen_button.setText("Остановить слушание" if busy and isinstance(self._worker, VoiceWorker) else "Начать слушать")

    def _send_typed(self) -> None:
        text = self.input.text().strip()
        if not text or self._worker is not None:
            return
        self._add_message("You", text)
        self.input.clear()
        self._start_worker(CommandWorker(self.command_pipeline, self.tts_pipeline, text))

    def _toggle_listening(self) -> None:
        if isinstance(self._worker, VoiceWorker):
            self.listen_button.setEnabled(False)
            self._worker.request_stop()
            return
        if self._worker is not None:
            return
        if self.speech_pipeline is None:
            self._show_error("Микрофон недоступен. Проверьте настройки распознавания речи и зависимости.")
            return
        self._select_microphone()
        self._start_worker(VoiceWorker(self.speech_pipeline, self.tts_pipeline))

    def _start_worker(self, worker) -> None:
        self._worker = worker
        worker.stage_changed.connect(self._set_status)
        worker.failed.connect(self._worker_failed)
        worker.finished_result.connect(self._worker_finished)
        if isinstance(worker, VoiceWorker):
            worker.speech_result.connect(lambda text: self._add_message("You (speech)", text))
        self._set_busy(True)
        worker.finished.connect(self._worker_thread_finished)
        worker.start()

    def _worker_finished(self, result, response: str, tts_result) -> None:
        self._add_message("Assistant", response)
        if tts_result.status is TTSStatus.ERROR:
            logger.warning("TTS failed after successful command: %s", tts_result.message)
            self._set_status("Error")
            self.help_label.setText(f"Ответ показан, но озвучивание не удалось: {tts_result.message}")
        elif tts_result.status is TTSStatus.DISABLED:
            self._set_status("Ready")
        else:
            self._set_status("Ready")

    def _worker_failed(self, message: str) -> None:
        self._add_message("System", message)
        self._set_status("Error")

    def _worker_thread_finished(self) -> None:
        worker = self._worker
        self._worker = None
        self._set_busy(False)
        if self.status.text().endswith("Listening") or self.status.text().endswith("Processing") or self.status.text().endswith("Speaking"):
            self._set_status("Ready")
        if worker is not None:
            worker.deleteLater()

    def _toggle_tts(self, enabled: bool) -> None:
        self.tts_pipeline.enabled = bool(enabled)
        if self.settings_manager is not None:
            try:
                self.settings_manager.save("tts_enabled", bool(enabled))
            except Exception:
                logger.warning("Could not persist TTS preference.")
        if enabled:
            self.help_label.setText("Озвучивание включено. Ответы также показываются текстом.")
        else:
            self.help_label.setText("Озвучивание выключено. Ответы остаются доступными в виде текста.")

    def _refresh_microphones(self) -> None:
        self.mic_combo.clear()
        if self.speech_pipeline is None:
            self.mic_combo.addItem("Недоступно", None)
            self.mic_combo.setEnabled(False)
            return
        if self._mic_worker is not None:
            return
        self.mic_combo.addItem("Поиск микрофонов...", None)
        self.mic_combo.setEnabled(False)
        worker = DeviceListWorker(self.speech_pipeline)
        self._mic_worker = worker
        worker.devices_ready.connect(self._microphones_ready)
        worker.failed.connect(self._microphones_failed)
        worker.finished.connect(self._microphone_worker_finished)
        worker.start()

    def _microphones_ready(self, devices) -> None:
        self.mic_combo.clear()
        if not devices:
            self.mic_combo.addItem("Микрофон не найден", None)
            return
        selected = getattr(self.speech_pipeline.microphone.config, "device_index", None)
        selected_index = 0
        for position, device in enumerate(devices):
            self.mic_combo.addItem(f"{device.name} (#{device.index})", device.index)
            if selected is not None and device.index == selected:
                selected_index = position
        self.mic_combo.setCurrentIndex(selected_index)
        self.mic_combo.setEnabled(True)

    def _microphones_failed(self, message: str) -> None:
        logger.warning("Microphone enumeration failed: %s", message)
        self.mic_combo.clear()
        self.mic_combo.addItem("Не удалось определить микрофон", None)
        self.mic_combo.setEnabled(True)

    def _microphone_worker_finished(self) -> None:
        worker = self._mic_worker
        self._mic_worker = None
        if worker is not None:
            worker.deleteLater()

    def _select_microphone(self) -> None:
        if self.speech_pipeline is None:
            return
        index = self.mic_combo.currentData()
        if index is None:
            return
        try:
            self.speech_pipeline.microphone.config = replace(self.speech_pipeline.microphone.config, device_index=int(index))
            if self.settings_manager is not None:
                self.settings_manager.save("microphone_index", int(index))
        except Exception:
            logger.warning("Could not apply selected microphone.")


    def _show_settings(self) -> None:
        values = self.settings_manager.all() if self.settings_manager is not None else {}
        memory_items = 0
        if self.memory_manager is not None:
            try:
                memory_items = sum(len(items) for items in self.memory_manager._memory.values())
            except Exception:
                memory_items = 0
        lines = ["Сохранённые настройки:"]
        if values:
            for key, value in sorted(values.items()):
                lines.append(f"• {key}: {value}")
        else:
            lines.append("• Пользовательских изменений нет.")
        lines += ["", f"Сохранённых элементов памяти: {memory_items}", "", "Сохраняются только явно указанные поддерживаемые настройки. История диалогов и записи микрофона не сохраняются."]
        QMessageBox.information(self, "Настройки и память", "\n".join(lines))

    def _clear_memory(self) -> None:
        if self.memory_manager is None:
            return
        answer = QMessageBox.question(self, "Очистить память", "Очистить всю поддерживаемую сохранённую память?", QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, QMessageBox.StandardButton.No)
        if answer is not QMessageBox.StandardButton.Yes:
            return
        result = self.memory_manager.clear_supported()
        if result.success:
            self._add_message("System", result.message)
            self._set_status("Ready")
        else:
            self._show_error(result.message)

    def _show_error(self, message: str) -> None:
        self._add_message("System", message)
        self._set_status("Error")
        QMessageBox.warning(self, "Голосовой помощник", message)

    def closeEvent(self, event) -> None:  # noqa: N802
        # Stop capture first, then give the active worker a bounded grace
        # period. No new work is started after shutdown begins.
        if isinstance(self._worker, VoiceWorker):
            self._worker.request_stop()
        if self._worker is not None and self._worker.isRunning():
            self._worker.wait(3000)
        if self._mic_worker is not None and self._mic_worker.isRunning():
            self._mic_worker.wait(1000)
        try:
            if self.speech_pipeline is not None:
                self.speech_pipeline.close()
        except Exception:
            logger.debug("Speech resources could not be fully closed.", exc_info=False)
        try:
            self.tts_pipeline.close()
        except Exception:
            logger.debug("TTS resources could not be fully closed.", exc_info=False)
        event.accept()
