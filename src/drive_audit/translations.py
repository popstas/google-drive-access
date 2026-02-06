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
        "client_folder_exists": "Client folder already exists: {folder_url}. {details}",
        "folder_created": "Folder {folder_name} created. {details}, folder_url: {folder_url}",
        "not_found": "Not found",
        "unable_extract_folder_id": "Unable to extract folder_id from folder_url",
        "rate_limit_exceeded": "Google API rate limit exceeded, please try again in a minute",
        "share_file_shared": "File shared for {days} days with {role} role",
        "share_file_shared_no_expire": "File shared with {role} role",
        "share_file_not_found": "File not found, please check the url",
        "share_file_outside_drive": "File outside of drive, please copy it to client folder",
        "unable_extract_file_id": "Unable to extract file ID from document_url",
        "none": "none",
        "folder_name_single_word": "Add client surname to make folder name unique.",
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
        "client_folder_exists": "Папка клиента уже существует: {folder_url}. {details}",
        "folder_created": "Папка {folder_name} создана. {details}. {folder_url}",
        "not_found": "Не найдено",
        "unable_extract_folder_id": 'Не удалось извлечь folder_id из folder_url. Это значит, что в поле папки клиента вписана ссылка на документ. Удалите ссылку и нажмите кнопку "Создать GDrive". Либо впишите ссылку на папку клиента вручную. Ссылки на документы можно указывать в поле дополнительной информации.',
        "rate_limit_exceeded": "Превышены лимиты Google API, попробуйте через минуту.",
        "share_file_shared": "Файл расшарен на {days} дней с ролью {role}",
        "share_file_shared_no_expire": "Файл расшарен с ролью {role}",
        "share_file_not_found": "Файл не найден, проверьте ссылку",
        "share_file_outside_drive": "Файл вне диска, скопируйте его в папку клиента",
        "unable_extract_file_id": "Не удалось извлечь ID файла из document_url",
        "none": "нет",
        "folder_name_single_word": "Добавьте фамилию клиенту, чтобы сделать название папки уникальной.",
    },
}


def translate(lang: str, key: str, **context: Any) -> str:
    translations = TRANSLATIONS.get(lang, TRANSLATIONS["en"])
    template = translations.get(key, TRANSLATIONS["en"].get(key, key))
    return template.format(**context)
