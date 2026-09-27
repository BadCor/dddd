"""Small, presentation-only widgets used by the Stage 7 GUI."""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QFrame, QLabel, QPushButton, QVBoxLayout, QWidget


class MessageCard(QFrame):
    def __init__(self, role: str, text: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("messageCard")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 10, 14, 10)
        title = QLabel(role)
        title.setObjectName("messageRole")
        title.setAlignment(Qt.AlignmentFlag.AlignLeft)
        body = QLabel(text)
        body.setObjectName("messageText")
        body.setWordWrap(True)
        body.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        layout.addWidget(title)
        layout.addWidget(body)


class StatusIndicator(QLabel):
    _labels = {
        "Ready": "Готов",
        "Listening": "Слушаю",
        "Processing": "Обрабатываю",
        "Speaking": "Говорю",
        "Error": "Ошибка",
    }

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("statusIndicator")
        self.set_status("Ready")

    def set_status(self, status: str) -> None:
        label = self._labels.get(status, "Ready")
        self.setText(f"● {label}")
        self.setProperty("status", label.lower())
        self.style().unpolish(self)
        self.style().polish(self)


class PrimaryButton(QPushButton):
    def __init__(self, text: str, parent: QWidget | None = None) -> None:
        super().__init__(text, parent)
        self.setMinimumHeight(40)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
