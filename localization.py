"""Russian localization helpers for the existing assistant UI and responses."""
from __future__ import annotations

from llm.pipeline import LLMRunResult

_TRANSLATIONS = {
    "File opened successfully.": "Файл успешно открыт.",
    "Folder opened successfully.": "Папка успешно открыта.",
    "Application launched successfully.": "Приложение успешно запущено.",
    "URL opened successfully.": "Ссылка успешно открыта.",
    "File does not exist.": "Файл не существует.",
    "Folder does not exist.": "Папка не существует.",
    "Path is not a file.": "Указанный путь не является файлом.",
    "Path is not a folder.": "Указанный путь не является папкой.",
    "Permission denied.": "Доступ запрещён.",
    "Could not open file.": "Не удалось открыть файл.",
    "Could not open folder.": "Не удалось открыть папку.",
    "Could not launch application.": "Не удалось запустить приложение.",
    "Could not open URL.": "Не удалось открыть ссылку.",
    "Application is not approved/configured.": "Приложение не разрешено или не настроено.",
    "Configured application does not exist.": "Настроенное приложение не существует.",
    "Configured application path is not a file.": "Путь настроенного приложения не является файлом.",
    "Could not open file safely.": "Не удалось безопасно открыть файл.",
    "Could not open folder safely.": "Не удалось безопасно открыть папку.",
    "Could not launch application safely.": "Не удалось безопасно запустить приложение.",
    "Could not open URL safely.": "Не удалось безопасно открыть ссылку.",
    "Application name must be a non-empty string.": "Имя приложения не должно быть пустым.",
    "Configured application path is invalid.": "Путь настроенного приложения недействителен.",
    "I don't understand that command yet.": "Я пока не понимаю эту команду.",
    "Command must be text.": "Команда должна быть текстом.",
    "Command cannot be empty.": "Команда не может быть пустой.",
}


def ru(text: str) -> str:
    """Translate known safe system/action messages while preserving targets."""
    if not isinstance(text, str):
        return str(text)
    return _TRANSLATIONS.get(text, text)


def response_text(result: LLMRunResult) -> str:
    """Build a Russian user-facing response without exposing diagnostics."""
    if result.action_result is not None:
        action = result.action_result
        if action.success:
            return f"Готово. {ru(action.message or 'Действие успешно выполнено.')}"
        return ru(action.error or "Не удалось безопасно выполнить действие.")
    return ru(result.command.message or "Я не смог обработать этот запрос.")
