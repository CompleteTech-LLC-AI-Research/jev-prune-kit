import os
from pathlib import Path
import subprocess
import shutil
import sys
import tempfile
import unittest
import zipfile
from unittest.mock import patch

from jev_prune.client import evaluate
from jev_prune.config import assessment_environment
from jev_prune.core import PruneError


class ConfigTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.path = Path(temporary.name) / ".env"
        for mock in (patch.dict(os.environ, {}, clear=True),
                     patch("jev_prune.config.ENV_FILE", self.path)):
            mock.start()
            self.addCleanup(mock.stop)

    def write(self, content):
        self.path.write_text(content, encoding="utf-8")

    def test_missing_default_is_optional(self):
        self.assertEqual(assessment_environment(), {})

    def test_literal_values_and_known_settings_only(self):
        self.write('\ufeff# comment\nexport TYPESAFE_API_KEY="literal-$KEY#value"\n'
                   "JEV_PRUNE_ALLOW_REMOTE='1'\nUNRELATED=ignored\n")
        self.assertEqual(assessment_environment(), {
            "TYPESAFE_API_KEY": "literal-$KEY#value", "JEV_PRUNE_ALLOW_REMOTE": "1"})
        self.assertNotIn("TYPESAFE_API_KEY", os.environ)

    def test_process_overrides_including_empty(self):
        self.write("TYPESAFE_API_KEY=file-key\nJEV_PRUNE_ALLOW_REMOTE=1\n")
        os.environ.update(TYPESAFE_API_KEY="", JEV_PRUNE_ALLOW_REMOTE="0")
        with patch("jev_prune.client.subprocess.run") as run:
            with self.assertRaises(PruneError):
                evaluate({})
            run.assert_not_called()
        self.assertEqual(assessment_environment()["TYPESAFE_API_KEY"], "")

    def test_explicit_path_and_missing_file(self):
        other = self.path.with_name("private.env")
        other.write_text("TYPESAFE_API_KEY=explicit", encoding="utf-8")
        os.environ["JEV_PRUNE_ENV_FILE"] = str(other)
        self.assertEqual(assessment_environment()["TYPESAFE_API_KEY"], "explicit")
        other.unlink()
        with self.assertRaises(PruneError):
            assessment_environment()

    def test_invalid_files_do_not_disclose_secrets(self):
        for content in ('TYPESAFE_API_KEY="secret', "TYPESAFE_API_KEY=secret\x00",
                        "JEV_PRUNE_ALLOW_REMOTE", "secret" * 12000):
            with self.subTest():
                self.write(content)
                with self.assertRaises(PruneError) as caught:
                    assessment_environment()
                self.assertNotIn("secret", str(caught.exception))

    def test_transport_receives_file_settings_without_global_mutation(self):
        self.write("TYPESAFE_API_KEY=test-key\nJEV_PRUNE_ALLOW_REMOTE=1\n")
        completed = subprocess.CompletedProcess([], 0, stdout=b'{}')
        with patch("jev_prune.client.subprocess.run", return_value=completed) as run:
            self.assertEqual(evaluate({}), {})
        self.assertEqual(run.call_args.kwargs["env"]["TYPESAFE_API_KEY"], "test-key")
        self.assertNotIn("test-key", str(run.call_args.args))
        self.assertNotIn("TYPESAFE_API_KEY", os.environ)

    def test_release_and_install_exclude_private_env_files(self):
        from jev_prune.installer import build_plan

        source = Path(__file__).resolve().parents[1]
        root = self.path.parent / "source"
        root.mkdir()
        for name in ("jev_prune", "adapters", "docs"):
            shutil.copytree(source / name, root / name,
                            ignore=shutil.ignore_patterns("__pycache__", ".env*"))
        for name in ("build_release.py", "install.py", "runner.py", ".env.example"):
            shutil.copy2(source / name, root / name)
        for name in (".env", ".env.backup.json", "jev_prune/.env.private.json"):
            (root / name).write_text("PRIVATE_SENTINEL", encoding="utf-8")
        plan, _, _ = build_plan(root, root / "data", [], False, False, sys.executable)
        self.assertFalse(any(b"PRIVATE_SENTINEL" in item.data for item in plan))
        subprocess.run([sys.executable, str(root / "build_release.py")],
                       check=True, capture_output=True)
        with zipfile.ZipFile(root.parent / "jev-prune-kit.zip") as archive:
            names = archive.namelist()
            self.assertIn("jev-prune-kit/.env.example", names)
            self.assertFalse(any(b"PRIVATE_SENTINEL" in archive.read(name) for name in names))
