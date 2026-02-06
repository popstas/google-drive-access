# HTTP Package

Route handlers for the HTTP server. Each route lives in its own module.

## Structure

- `handler.py` — `create_handler()` factory, `AccessHandler` class with `do_POST` dispatch, `_log_request`, `_format_accounts`
- `set_client_folder_access.py` — handles `/set_client_folder_access` POST route
- `create_client_folder.py` — handles `/create_client_folder` POST route
- `share_file.py` — handles `/share_file` POST route (shares a file via "anyone with the link")
- `__init__.py` — re-exports `create_handler`

## Adding a New Route

1. Create `src/drive_audit/http/<route_name>.py` with a `handle` function:
   ```python
   def handle(handler, payload, *, service, drive_config, **other_kwargs):
   ```
   - `handler` is the `AccessHandler` instance (provides `send_json`, `translate`, `_format_accounts`)
   - Keyword args vary per route: some need `planfix_client` and `role`, others need `share_file_config`, etc.
   - Use `LocalizedError` from `..http_utils` for error handling
2. Wire the route in `handler.py` `do_POST`: add a path check block that calls your `handle` function
3. If the route needs extra config, add a parameter to `create_handler()` and pass it through the closure
4. Add tests in `tests/test_http_handler.py`, monkeypatching at `drive_audit.http.<route_module>.<function>`
5. If adding new config, add dataclass to `model.py`, builder to `config_loader.py`, load in `server.py`

## Conventions

- All responses use HTTP 200 with `"answer"` key in the JSON body
- Route modules import from `..access_service`, not from `handler.py`
- `http_utils.py` stays at `src/drive_audit/http_utils.py` (not in this package) — it's shared by non-HTTP modules too
