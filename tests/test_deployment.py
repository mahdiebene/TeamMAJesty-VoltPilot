import os
import stat
import tempfile
import unittest
from pathlib import Path

from scripts.configure_model import save_environment, validate_key


class KeyValidationTests(unittest.TestCase):
    def test_control_characters_and_empty_key_are_rejected(self):
        for key in ("", "bad key", "bad\nkey", "bad\rkey", "bad\tkey", "bad\x00key", "bad\x7fkey"):
            with self.subTest(key_length=len(key)), self.assertRaises(ValueError):
                validate_key(key)
        validate_key("not-a-real-credential")


@unittest.skipUnless(os.name == "posix", "Requires POSIX ownership and file modes; exercised in Linux image")
class PrivateConfigurationTests(unittest.TestCase):
    def test_create_and_rotate_preserve_permissions_and_other_values(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary) / "private"
            save_environment(directory, "fake-first-key")
            target = directory / "voltpilot.env"
            self.assertEqual(stat.S_IMODE(directory.stat().st_mode), 0o700)
            self.assertEqual(stat.S_IMODE(target.stat().st_mode), 0o600)
            original = target.read_text()
            with self.assertRaises(FileExistsError):
                save_environment(directory, "fake-overwrite")
            self.assertEqual(target.read_text(), original)
            target.write_text(original.replace("CORS_ORIGINS=", "CORS_ORIGINS=https://frontend.example"))
            save_environment(directory, "fake-rotated-key", rotate=True)
            self.assertIn("LLM_API_KEY=fake-rotated-key\n", target.read_text())
            self.assertIn("CORS_ORIGINS=https://frontend.example\n", target.read_text())
            self.assertEqual(stat.S_IMODE(target.stat().st_mode), 0o600)
            self.assertEqual(list(directory.iterdir()), [target])

    def test_unsafe_directories_symlinks_and_missing_rotation_are_refused(self):
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            unsafe = base / "unsafe"
            unsafe.mkdir(mode=0o755)
            unsafe.chmod(0o755)
            with self.assertRaises(ValueError):
                save_environment(unsafe, "fake-key")
            target = base / "target"
            target.mkdir(mode=0o700)
            link = base / "link"
            link.symlink_to(target, target_is_directory=True)
            with self.assertRaises(ValueError):
                save_environment(link, "fake-key")
            with self.assertRaises(FileNotFoundError):
                save_environment(target, "fake-key", rotate=True)
            outside = base / "outside"
            outside.write_text("untouched")
            (target / "voltpilot.env").symlink_to(outside)
            with self.assertRaises(ValueError):
                save_environment(target, "fake-key", rotate=True)
            self.assertEqual(outside.read_text(), "untouched")