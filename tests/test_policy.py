import unittest
from datetime import datetime
from src.drive_audit.model import FileInfo, DriveConfig, AccessInfo, Permission, PolicyInfo
from src.drive_audit.policy import check_policy

class TestPolicy(unittest.TestCase):
    def setUp(self):
        self.config = DriveConfig(
            credentials_file="dummy",
            delegated_user=None,
            drive_id="dummy",
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

    def test_is_under_public_folder(self):
        # Case 1: Under public folder
        file_info = FileInfo(
            id="1", name="file.txt", type="file", mime_type="text/plain", parents=[],
            created=datetime.now(), modified=datetime.now(), viewed=None, trashed=False, starred=False,
            size_bytes=100, owners=[], last_modifying_user=None,
            location="/ClientA/public/subfolder/file.txt",
            access=AccessInfo(False, None, None, None, 'restricted', None, None, None, False)
        )
        policy = check_policy(file_info, self.config)
        self.assertTrue(policy.is_under_public_folder)

        # Case 2: Not under public folder
        file_info.location = "/ClientA/private/file.txt"
        policy = check_policy(file_info, self.config)
        self.assertFalse(policy.is_under_public_folder)
        
        # Case 3: Public folder name mismatch
        file_info.location = "/ClientA/Public/file.txt" # Case sensitive check in code? currently yes
        policy = check_policy(file_info, self.config)
        self.assertFalse(policy.is_under_public_folder)

    def test_is_public_anyone(self):
        # Case 1: General access is anyone
        file_info = FileInfo(
            id="1", name="file.txt", type="file", mime_type="text/plain", parents=[],
            created=datetime.now(), modified=datetime.now(), viewed=None, trashed=False, starred=False,
            size_bytes=100, owners=[], last_modifying_user=None,
            location="/ClientA/file.txt",
            access=AccessInfo(False, None, None, None, 'anyone', 'reader', None, None, True)
        )
        policy = check_policy(file_info, self.config)
        self.assertTrue(policy.is_public_anyone)
        
        # Case 2: Permission type is anyone
        file_info.access.general_access = 'restricted'
        file_info.access.permissions = [
            Permission(id="p1", type="anyone", role="reader")
        ]
        policy = check_policy(file_info, self.config)
        self.assertTrue(policy.is_public_anyone)

    def test_public_outside_public_folder(self):
        # Case 1: Public file outside public folder -> Violation
        file_info = FileInfo(
            id="1", name="file.txt", type="file", mime_type="text/plain", parents=[],
            created=datetime.now(), modified=datetime.now(), viewed=None, trashed=False, starred=False,
            size_bytes=100, owners=[], last_modifying_user=None,
            location="/ClientA/private/file.txt",
            access=AccessInfo(False, None, None, None, 'anyone', 'reader', None, None, True)
        )
        policy = check_policy(file_info, self.config)
        self.assertTrue(policy.public_outside_public_folder)
        self.assertIn("Public file outside public folder", policy.notes)
        
        # Case 2: Public file INSIDE public folder -> OK
        file_info.location = "/ClientA/public/file.txt"
        policy = check_policy(file_info, self.config)
        self.assertFalse(policy.public_outside_public_folder)

if __name__ == '__main__':
    unittest.main()
