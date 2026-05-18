import unittest

from drive_audit.model import DriveConfig
from drive_audit.scanner import build_file_tree, compute_file_depth


class TestScanner(unittest.TestCase):
    def setUp(self):
        self.config = DriveConfig(
            credentials_file="dummy",
            delegated_user=None,
            drive_id="drive1",
            root_folder_id="root",
            root_folder_name="Clients",
            include_trashed=False,
            include_shortcuts=True,
            max_depth=None,
            limit=None,
            public_subdir="public",
            output_dir="dummy",
            yaml_file="dummy",
            files_csv="dummy",
            permissions_csv="dummy",
        )

    def test_build_file_tree_path_resolution(self):
        # Mock data
        files_data = [
            {
                "id": "root",
                "name": "Clients",
                "mimeType": "application/vnd.google-apps.folder",
                "parents": ["drive_root"],
            },
            {
                "id": "clientA",
                "name": "ClientA",
                "mimeType": "application/vnd.google-apps.folder",
                "parents": ["root"],
            },
            {
                "id": "public",
                "name": "public",
                "mimeType": "application/vnd.google-apps.folder",
                "parents": ["clientA"],
            },
            {
                "id": "file1",
                "name": "file1.txt",
                "mimeType": "text/plain",
                "parents": ["public"],
            },
            {
                "id": "orphan",
                "name": "orphan.txt",
                "mimeType": "text/plain",
                "parents": ["unknown_parent"],
            },
        ]

        processed = build_file_tree(files_data, self.config)

        # We expect 3 files processed: clientA, public, file1. root is excluded as it is the root. orphan excluded.
        # Wait, the logic in scanner:
        # "if parent_id == config.root_folder_id: break"
        # So items directly under root (ClientA) will have path /ClientA

        file_map = {f.id: f for f in processed}

        self.assertIn("clientA", file_map)
        self.assertEqual(file_map["clientA"].location, "/ClientA")
        self.assertEqual(file_map["clientA"].client_name, "ClientA")

        self.assertIn("public", file_map)
        self.assertEqual(file_map["public"].location, "/ClientA/public")

        self.assertIn("file1", file_map)
        self.assertEqual(file_map["file1"].location, "/ClientA/public/file1.txt")
        self.assertTrue(file_map["file1"].policy.is_under_public_folder)

        self.assertNotIn("orphan", file_map)


class TestComputeFileDepth(unittest.TestCase):
    def _config(self, drive_id="drive1", root_folder_id="root"):
        return DriveConfig(
            credentials_file="dummy",
            delegated_user=None,
            drive_id=drive_id,
            root_folder_id=root_folder_id,
            root_folder_name="Clients",
            include_trashed=False,
            include_shortcuts=True,
            max_depth=None,
            limit=None,
            public_subdir="public",
            output_dir="dummy",
            yaml_file="dummy",
            files_csv="dummy",
            permissions_csv="dummy",
        )

    def test_sub_folder_scan_returns_depth(self):
        config = self._config()
        files = [
            {"id": "clientA", "name": "ClientA", "parents": ["root"]},
            {"id": "sub", "name": "sub", "parents": ["clientA"]},
            {"id": "file1", "name": "file1.txt", "parents": ["sub"]},
        ]
        file_map = {f["id"]: f for f in files}

        self.assertEqual(compute_file_depth(file_map["clientA"], file_map, config), 1)
        self.assertEqual(compute_file_depth(file_map["sub"], file_map, config), 2)
        self.assertEqual(compute_file_depth(file_map["file1"], file_map, config), 3)

    def test_sub_folder_scan_returns_none_for_orphan(self):
        config = self._config()
        files = [
            {"id": "orphan", "name": "orphan.txt", "parents": ["unknown_parent"]},
            {"id": "no_parent", "name": "rootless", "parents": []},
        ]
        file_map = {f["id"]: f for f in files}

        self.assertIsNone(compute_file_depth(file_map["orphan"], file_map, config))
        self.assertIsNone(compute_file_depth(file_map["no_parent"], file_map, config))

    def test_drive_wide_scan_counts_full_chain(self):
        # Drive-wide scan: root_folder_id == drive_id; parents not in file_map terminate the walk.
        config = self._config(drive_id="drive1", root_folder_id="drive1")
        files = [
            {"id": "clientA", "name": "ClientA", "parents": ["drive1"]},
            {"id": "sub", "name": "sub", "parents": ["clientA"]},
            {"id": "file1", "name": "file1.txt", "parents": ["sub"]},
        ]
        file_map = {f["id"]: f for f in files}

        self.assertEqual(compute_file_depth(file_map["clientA"], file_map, config), 1)
        self.assertEqual(compute_file_depth(file_map["sub"], file_map, config), 2)
        self.assertEqual(compute_file_depth(file_map["file1"], file_map, config), 3)


if __name__ == "__main__":
    unittest.main()
