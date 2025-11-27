import sys
from types import SimpleNamespace

import pytest

from drive_audit import main as audit_main


def test_get_log_level_defaults_to_info():
    assert audit_main.get_log_level("unknown") == audit_main.logging.INFO


def test_main_success(monkeypatch, tmp_path):
    config_path = tmp_path / "config.yml"
    output_dir = tmp_path / "output"
    config_path.write_text(
        """
logLevel: INFO
drive:
  id: drive-id
  root_folder_id: ROOT_FOLDER_ID
  root_folder_name: Root
google:
  credentials_file: creds.json
scan:
  include_trashed: false
  include_shortcuts: true
  limit: 2
output:
  dir: {output_dir}
  yaml_file: data.yml
  files_csv: files.csv
  permissions_csv: perms.csv
""".format(
            output_dir=output_dir
        )
    )

    monkeypatch.setattr(audit_main, "get_service", lambda cfg: SimpleNamespace())
    monkeypatch.setattr(
        audit_main,
        "list_files",
        lambda service, drive_id, limit=None: [
            {"id": "file1"},
            {"id": "file2"},
        ],
    )
    monkeypatch.setattr(
        audit_main, "get_file_permissions", lambda service, file_id: [f"perm-{file_id}"]
    )
    processed = [
        SimpleNamespace(owners=["owner"], access=SimpleNamespace(permissions=[1, 2])),
        SimpleNamespace(owners=[], access=SimpleNamespace(permissions=[])),
    ]
    monkeypatch.setattr(audit_main, "build_file_tree", lambda files, cfg: processed)

    saved = {}
    monkeypatch.setattr(
        audit_main, "save_yaml", lambda data, cfg, path: saved.setdefault("yaml", path)
    )
    monkeypatch.setattr(
        audit_main, "save_files_csv", lambda data, path: saved.setdefault("files", path)
    )
    monkeypatch.setattr(
        audit_main,
        "save_permissions_csv",
        lambda data, path: saved.setdefault("perms", path),
    )

    argv = [
        "prog",
        "--config",
        str(config_path),
        "--drive-id",
        "override-drive",
        "--root-folder-id",
        "root-override",
    ]
    monkeypatch.setattr(sys, "argv", argv)

    audit_main.main()

    assert saved["yaml"].endswith("data.yml")
    assert output_dir.exists()


def test_main_missing_config(monkeypatch, tmp_path):
    missing_path = tmp_path / "missing.yml"
    monkeypatch.setattr(sys, "argv", ["prog", "--config", str(missing_path)])

    with pytest.raises(SystemExit):
        audit_main.main()
