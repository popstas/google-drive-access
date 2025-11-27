"""Translation helpers for localized responses."""

from typing import Any, Dict

TRANSLATIONS: Dict[str, Dict[str, str]] = {
    "en": {
        "missing_or_invalid_auth_header": "Missing or invalid Authorization header",
        "invalid_token": "Invalid token",
        "request_body_required": "Request body is required",
        "invalid_json": "Invalid JSON: {detail}",
        "missing_fields": "Missing fields: {fields}",
        "client_task_not_found": "Client task not found",
        "task_and_assignee_together": "task_id and assignee_id must both be provided or omitted",
        "internal_server_error": "Internal server error",
        "granted_existing": "Granted: {granted}; Existing: {existing}",
        "folder_name_empty": "folder_name must not be empty",
        "client_folder_exists": "Client folder already exists: {folder_url}",
        "folder_created": "Folder {folder_name} created. {details}, folder_url: {folder_url}",
        "not_found": "Not found",
        "unable_extract_folder_id": "Unable to extract folder_id from folder_url",
        "none": "none",
    },
    "ru": {
        "missing_or_invalid_auth_header": "Отсутствует или некорректный заголовок Authorization",
        "invalid_token": "Неверный токен",
        "request_body_required": "Требуется тело запроса",
        "invalid_json": "Некорректный JSON: {detail}",
        "missing_fields": "Отсутствуют поля: {fields}",
        "client_task_not_found": "Задача клиента не найдена",
        "task_and_assignee_together": "Поля task_id и assignee_id должны быть указаны вместе или оба отсутствовать",
        "internal_server_error": "Внутренняя ошибка сервера",
        "granted_existing": "Выданы права: {granted}. Уже были права: {existing}",
        "folder_name_empty": "folder_name не должно быть пустым",
        "client_folder_exists": "Папка клиента уже существует: {folder_url}",
        "folder_created": "Папка {folder_name} создана. {details}. {folder_url}",
        "not_found": "Не найдено",
        "unable_extract_folder_id": "Не удалось извлечь folder_id из folder_url",
        "none": "нет",
    },
}


def translate(lang: str, key: str, **context: Any) -> str:
    translations = TRANSLATIONS.get(lang, TRANSLATIONS["en"])
    template = translations.get(key, TRANSLATIONS["en"].get(key, key))
    return template.format(**context)
