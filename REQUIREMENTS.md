ниже - формальное ТЗ на Python-проект: цель, функциональные требования, формат YML/CSV, структура CLI-утилиты, конфиг, алгоритм обхода shared drive, работа с permissions, правила политики `public`, логирование и тесты.

---

## 1. Цель проекта

Реализовать CLI-утилиту на Python, которая:

1. Подключается к Google Drive API для конкретного Shared Drive.
2. Обходит все файлы и папки (кроме удалённых).
3. Собирает информацию о:

   * структуре папок (клиенты, public-папки),
   * файлах (метаданные, shortcut’ы),
   * правах доступа (permissions, наследование, публичность, expirationTime).
4. На основе данных формирует:

   * один YML-файл со сводной структурой документов и прав;
   * два CSV-файла:

     * `files.csv` - список файлов/папок с ключевыми флагами;
     * `permissions.csv` - детальный список прав доступа по каждому документу.

Основная бизнес-цель: аудит прав и поиск ошибок выдачи публичного доступа (особенно публичные файлы вне `public`-папок).

---

## 2. Технологический стек

* Язык: Python 3.11+.
* Зависимости (минимум):

  * `google-auth`
  * `google-auth-httplib2`
  * `google-api-python-client`
  * `PyYAML` для YML.
  * `python-dotenv` (опционально) для локальной конфигурации.
* Формат проекта:

  * Отдельный репозиторий или подпроект типа:

    * `src/drive_audit/__init__.py`
    * `src/drive_audit/main.py` (CLI-вход)
    * `src/drive_audit/google_client.py`
    * `src/drive_audit/model.py`
    * `src/drive_audit/export_yaml.py`
    * `src/drive_audit/export_csv.py`
    * `tests/…`

---

## 3. Конфигурация

**Важно:**
- Все изменяемые файлы должны лежать в директории `data`.
- data/service-account.json создан и имеет доступ к диску

### 3.1. Файл конфигурации (например, `config.yml`)

Минимальные параметры:

```yml
google:
  credentials_file: "data/service-account.json"   # путь к JSON с сервисным аккаунтом
  delegated_user: "admin@company.com"        # если используется domain-wide delegation (опционально)

drive:
  id: "FOLDER_ID"                      # ID shared drive
  root_folder_id: "ROOT_FOLDER_ID"           # корневая папка с клиентами (может быть id корня диска)
  root_folder_name: "Clients"

scan:
  include_trashed: false                     # по ТЗ - всегда false
  include_shortcuts: true
  max_depth: null                            # без ограничения по глубине
  public_folder_name: "public"               # имя public-папок

output:
  dir: "./data"
  yaml_file: "drive_audit.yml"
  files_csv: "files.csv"
  permissions_csv: "permissions.csv"
```

### 3.2. Параметры CLI

CLI-команда (пример):

```bash
python -m drive_audit \
  --config ./config.yml \
  --drive-id SHARED_DRIVE_ID \
  --root-folder-id ROOT_FOLDER_ID
```

Параметры CLI должны иметь приоритет над конфигом.

---

## 4. Формат выходных данных

### 4.1. YML (один сводный файл)

Структура YML:

```yml
version: 1
generated_at: <ISO8601 UTC>

drive:
  id: <string>
  name: <string>
  root_folder_id: <string>
  root_folder_name: <string>

config:
  include_trashed: <bool>
  include_shortcuts: <bool>
  public_folder_name: <string>
  max_depth: <int|null>

documents:
  - id: <string>
    name: <string>
    type: file | folder | shortcut
    mime_type: <string>
    client:
      id: <string|null>        # id папки верхнего уровня, если определён
      name: <string|null>      # имя папки-клиента
    location: <string>         # путь вида "/Client/public/file.ext"
    depth: <int>

    parents:
      - id: <string>
        name: <string>
        type: "folder"

    shortcut:
      is_shortcut: <bool>
      target_id: <string|null>
      target_type: file | folder | null
      target_mime_type: <string|null>

    created: <ISO8601>
    modified: <ISO8601>
    viewed: <ISO8601|null>
    trashed: <bool>
    starred: <bool>
    size_bytes: <int|null>

    owners:
      - email: <string>
        display_name: <string>

    last_modifying_user:
      email: <string|null>
      display_name: <string|null>

    access:
      inherited: <bool>
      inherited_from:
        id: <string|null>
        name: <string|null>
        location: <string|null>

      general:
        access: restricted | domain | anyone
        role: reader | commenter | writer | organizer | owner | null
        domain: <string|null>
        allow_file_discovery: <bool|null>
        has_link_sharing: <bool>   # type=anyone существует

      permissions:
        - id: <string>
          type: user | group | domain | anyone
          role: owner | organizer | fileOrganizer | writer | commenter | reader
          email: <string|null>
          domain: <string|null>
          display_name: <string|null>
          allow_file_discovery: <bool|null>
          expiration: <ISO8601|null>
          deleted: <bool|null>
          permission_details:
            - permission_type: file | member
              role: <string>
              inherited: <bool>
              inherited_from: <string|null>

    policy:
      is_under_public_folder: <bool>
      is_public_anyone: <bool>
      is_public_by_domain: <bool>
      public_outside_public_folder: <bool>
      notes: [<string>, ...]
```

### 4.2. `files.csv`

Столбцы:

* `file_id`
* `name`
* `type`
* `mime_type`
* `client_name`
* `location`
* `depth`
* `is_shortcut`
* `shortcut_target_id`
* `created`
* `modified`
* `viewed`
* `owner_email`
* `last_modifying_user_email`
* `size_bytes`
* `general_access`
* `general_role`
* `general_domain`
* `general_has_link_sharing`
* `policy_is_under_public_folder`
* `policy_is_public_anyone`
* `policy_is_public_by_domain`
* `policy_public_outside_public_folder`

### 4.3. `permissions.csv`

Столбцы:

* `file_id`
* `file_name`
* `location`
* `client_name`
* `permission_id`
* `permission_type`
* `permission_role`
* `permission_email`
* `permission_domain`
* `display_name`
* `allow_file_discovery`
* `expiration`
* `deleted`
* `inherited`              - первый permissionDetails.inherited или агрегированный
* `inherited_from_id`
* `inherited_from_location`

---

## 5. Логика работы и алгоритм

### 5.1. Авторизация

1. Прочитать `config.yml`.
2. Инициализировать Google API client:

   * Сервисный аккаунт из `credentials_file`.
   * При необходимости domain-wide delegation от `delegated_user`.
3. Создать сервис `drive = googleapiclient.discovery.build("drive", "v3", ...)` с `supportsAllDrives=True`.

### 5.2. Получение информации о shared drive

1. Вызвать `drives.get` для `drive.id` (опционально, для имени диска).
2. Проверить доступ.

### 5.3. Обход файлов

Использовать `files.list`:

* Параметры:

  * `corpora="drive"`
  * `driveId=<SHARED_DRIVE_ID>`
  * `includeItemsFromAllDrives=True`
  * `supportsAllDrives=True`
  * `q="trashed = false"`
  * `pageSize` порядка 1000
  * `fields="nextPageToken, files(id,name,mimeType,parents,createdTime,modifiedTime,viewedByMeTime,owners,lastModifyingUser,trashed,starred,size,shortcutDetails,permissions)"`

Собрать все файлы в память (ожидание до 10k объектов).

### 5.4. Построение дерева и путей

1. Создать map `id -> file`.
2. Для каждого файла:

   * Восстановить путь `location` поднимаясь по `parents` до `root_folder_id`:

     * если `root_folder_id` не найден по цепочке - помечать как «вне зоны интереса» (можно либо исключить, либо включить с пометкой).
   * Определить `depth` как количество сегментов в пути.
   * Определить `client`:

     * первый сегмент пути (после `root_folder_name`), например `/ClientA/...`.

### 5.5. Обработка shortcut’ов

Для файла с `mimeType = application/vnd.google-apps.shortcut`:

* `type = "shortcut"`.
* Взять сведения из `shortcutDetails`:

  * `targetId`
  * `targetMimeType`
* `shortcut.target_type` определить как `file`/`folder` по targetMimeType.

### 5.6. Анализ прав (permissions)

Для каждого файла:

1. Из `permissions` сформировать список `access.permissions`.

2. Для каждого permission:

   * Считать:

     * `type`, `role`, `emailAddress`, `domain`, `displayName`, `allowFileDiscovery`, `expirationTime`, `deleted`, `permissionDetails`.
   * Если `permissionDetails` пуст, всё равно создавать элемент с пустым списком.
   * `inherited` (в CSV) брать как:

     * `True`, если все permissionDetails.inherited = True;
     * `False`, если есть хотя бы один inherited = False;
     * `null`, если permissionDetails пуст.

3. Общее поле `access.inherited` для файла:

   * `True`, если все permissionDetails по всем permissions inherited = True.
   * `False`, если хотя бы один permissionDetails.inherited = False.
   * В `access.inherited_from` можно брать первый `inherited_from`, если есть.

4. `access.general`:

   * Если есть permission с `type=anyone`:

     * `access = "anyone"`
     * `role` = роль этого permission (если несколько - можно взять максимально «широкую» или первый).
     * `allow_file_discovery` = значение этого permission.
   * Если нет `anyone`, но есть `type=domain`:

     * `access = "domain"`
     * `domain` = domain.
     * `role` и `allow_file_discovery` по аналогии.
   * Если нет ни `anyone`, ни `domain`:

     * `access = "restricted"`.
     * Остальные поля null/по умолчанию.

### 5.7. Логика политики (public-папки и нарушения)

На основе `location` и `config.public_folder_name`:

1. `is_under_public_folder`:

   * `True`, если путь имеет вид `"/<Client>/public/..."` или папка `public` вторая в пути.
2. `is_public_anyone`:

   * `True`, если есть permission `type=anyone`.
3. `is_public_by_domain`:

   * `True`, если есть permission `type=domain`.
4. `public_outside_public_folder`:

   * `True`, если:

     * `is_public_anyone = True` и
     * `is_under_public_folder = False`.

В `notes` можно добавлять текстовые пометки для удобного ручного анализа.

---

## 6. Нефункциональные требования

1. **Производительность:**

   * Работа для 10k файлов должна укладываться в разумное время (до нескольких минут).
   * Минимизировать количество запросов к API:

     * использовать `files.list` с широким `fields`;
     * избегать дополнительных `permissions.list`, если не нужно.

2. **Надёжность:**

   * Обрабатывать ситуации:

     * отсутствие доступа к shared drive;
     * частичную недоступность API (retry с exponential backoff).
   * Адекватно логировать ошибки и продолжать обработку остальных файлов, если возможно.

3. **Логирование:**

   * Стандартный вывод:

     * уровень INFO: прогресс (кол-во прочитанных файлов, формирование YML/CSV).
     * уровень ERROR: ошибки API, ошибки парсинга.
   * Возможность включить DEBUG через флаг CLI.

4. **Тесты:**

   * Юнит-тесты для:

     * восстановления пути `location` и определения `client`;
     * логики `access.general` (restricted/domain/anyone);
     * вычисления `policy`-флагов.
   * Моки для Google API (использовать `httplib2.Http()` с заглушками или `unittest.mock`).

---

## 7. Результат реализации

На выходе разработчик должен предоставить:

1. Репозиторий с исходным кодом:

   * структура `src/...`, `tests/...`.
2. Инструкцию по запуску:

   * как создать сервисный аккаунт;
   * как выдать ему доступ к shared drive;
   * пример `config.yml`;
   * пример вызова CLI.
3. Пример выходных файлов:

   * `drive_audit.yml` с несколькими тестовыми клиентами;
   * `files.csv` и `permissions.csv` для этого же тестового набора.
