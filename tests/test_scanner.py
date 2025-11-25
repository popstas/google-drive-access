import unittest
from src.drive_audit.model import DriveConfig
from src.drive_audit.scanner import build_file_tree

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
            permissions_csv="dummy"
        )

    def test_build_file_tree_path_resolution(self):
        # Mock data
        files_data = [
            {'id': 'root', 'name': 'Clients', 'mimeType': 'application/vnd.google-apps.folder', 'parents': ['drive_root']},
            {'id': 'clientA', 'name': 'ClientA', 'mimeType': 'application/vnd.google-apps.folder', 'parents': ['root']},
            {'id': 'public', 'name': 'public', 'mimeType': 'application/vnd.google-apps.folder', 'parents': ['clientA']},
            {'id': 'file1', 'name': 'file1.txt', 'mimeType': 'text/plain', 'parents': ['public']},
            {'id': 'orphan', 'name': 'orphan.txt', 'mimeType': 'text/plain', 'parents': ['unknown_parent']}
        ]
        
        processed = build_file_tree(files_data, self.config)
        
        # We expect 3 files processed: clientA, public, file1. root is excluded as it is the root. orphan excluded.
        # Wait, the logic in scanner:
        # "if parent_id == config.root_folder_id: break"
        # So items directly under root (ClientA) will have path /ClientA
        
        file_map = {f.id: f for f in processed}
        
        self.assertIn('clientA', file_map)
        self.assertEqual(file_map['clientA'].location, '/ClientA')
        self.assertEqual(file_map['clientA'].client_name, 'ClientA')
        
        self.assertIn('public', file_map)
        self.assertEqual(file_map['public'].location, '/ClientA/public')
        
        self.assertIn('file1', file_map)
        self.assertEqual(file_map['file1'].location, '/ClientA/public/file1.txt')
        self.assertTrue(file_map['file1'].policy.is_under_public_folder)
        
        self.assertNotIn('orphan', file_map)

if __name__ == '__main__':
    unittest.main()
