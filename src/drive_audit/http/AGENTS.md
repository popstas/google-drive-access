# HTTP Package

Route handlers for the HTTP server. Each route lives in its own module.

## Structure

- `handler.py` — `create_handler()` factory, `AccessHandler` class with `do_POST` dispatch, `_log_request`, `_format_accounts`
- `set_client_folder_access.py` — handles `/set_client_folder_access` POST route
- `create_client_folder.py` — handles `/create_client_folder` POST route
- `__init__.py` — re-exports `create_handler`

## Adding a New Route

1. Create `src/drive_audit/http/<route_name>.py` with a `handle` function:
   ```python
   def handle(handler, payload, *, planfix_client, service, drive_config, role):
   ```
   - `handler` is the `AccessHandler` instance (provides `send_json`, `translate`, `_format_accounts`)
   - Use `LocalizedError` from `..http_utils` for error handling
2. Wire the route in `handler.py` `do_POST`: add a path check block that calls your `handle` function
3. Add tests in `tests/test_http_handler.py`, monkeypatching at `drive_audit.http.<route_module>.<function>`

## Conventions

- All responses use HTTP 200 with `"answer"` key in the JSON body
- Route modules import from `..access_service`, not from `handler.py`
- `http_utils.py` stays at `src/drive_audit/http_utils.py` (not in this package) — it's shared by non-HTTP modules too
