from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from pathlib import Path

from ai_engineering_guardrails import complexity, terminal_ux
from ai_engineering_guardrails.util import GuardrailsError


class ComplexityTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.repo = Path(self.temporary.name) / "repo"
        self.repo.mkdir()
        self.git("init")
        self.git("config", "user.email", "tests@example.invalid")
        self.git("config", "user.name", "Tests")
        (self.repo / "app.py").write_text("print('base')\n", encoding="utf-8")
        (self.repo / "tests").mkdir()
        (self.repo / "tests/test_app.py").write_text("pass\n", encoding="utf-8")
        self.git("add", ".")
        self.git("commit", "-m", "base")

    def git(self, *arguments: str) -> None:
        subprocess.run(["git", "-C", str(self.repo), *arguments], check=True, capture_output=True)

    def test_working_staged_and_non_git_results_are_deterministic(self) -> None:
        (self.repo / "app.py").write_text("print('changed')\n", encoding="utf-8")
        (self.repo / "docs").mkdir()
        (self.repo / "docs/readme.md").write_text("change\n", encoding="utf-8")
        result = complexity.analyse(self.repo)
        self.assertTrue(result["available"])
        self.assertEqual(2, result["files_changed"])
        self.assertEqual(["Python"], result["implementation_languages"])
        self.assertEqual(1, result["documentation_files_changed"])
        self.git("add", "app.py")
        staged = complexity.analyse(self.repo, staged=True)
        self.assertEqual("staged", staged["scope"])
        plain = Path(self.temporary.name) / "plain"
        plain.mkdir()
        self.assertFalse(complexity.analyse(plain)["available"])

    def test_dependency_risk_deleted_test_and_cache(self) -> None:
        (self.repo / "package.json").write_text(json.dumps({"dependencies": {"safe": "1"}}), encoding="utf-8")
        (self.repo / "infra.tf").write_text("terraform {}\n", encoding="utf-8")
        (self.repo / "tests/test_app.py").unlink()
        result = complexity.analyse(self.repo)
        self.assertIn("package.json:safe", result["new_runtime_dependencies"])
        self.assertEqual(["tests/test_app.py"], result["deleted_test_files"])
        self.assertIn("persistent-data", result["high_risk_paths"])
        home = Path(self.temporary.name) / "home"
        path = complexity.write_cache(home, result)
        cached = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(result["classification"], cached["classification"])
        self.assertNotIn("package.json", path.read_text(encoding="utf-8"))

    def test_invalid_base_is_reported(self) -> None:
        with self.assertRaises(GuardrailsError):
            complexity.analyse(self.repo, base="missing-revision")

    def test_unborn_git_repository_returns_a_limited_result(self) -> None:
        unborn = Path(self.temporary.name) / "unborn"
        unborn.mkdir()
        subprocess.run(["git", "-C", str(unborn), "init"], check=True, capture_output=True)
        (unborn / "draft.py").write_text("print('draft')\n", encoding="utf-8")
        result = complexity.analyse(unborn)
        self.assertFalse(result["available"])
        self.assertEqual("clear", result["classification"])
        self.assertIn("HEAD", result["limitation"])

    def test_staged_changes_compare_against_head_not_the_index(self) -> None:
        (self.repo / "package.json").write_text(json.dumps({"dependencies": {"safe": "1"}}), encoding="utf-8")
        (self.repo / "new.go").write_text("package main\n", encoding="utf-8")
        self.git("add", "package.json", "new.go")
        result = complexity.analyse(self.repo, staged=True)
        self.assertIn("package.json:safe", result["new_runtime_dependencies"])
        self.assertEqual(["Go"], result["implementation_languages_introduced"])

    def test_ignored_vendor_and_build_paths_do_not_inflate_signals(self) -> None:
        (self.repo / "node_modules").mkdir()
        (self.repo / "node_modules/generated.js").write_text("x\n" * 500, encoding="utf-8")
        (self.repo / "build").mkdir()
        (self.repo / "build/output.py").write_text("x\n" * 500, encoding="utf-8")
        (self.repo / "app.py").write_text("print('changed')\n", encoding="utf-8")
        result = complexity.analyse(self.repo)
        self.assertEqual(1, result["files_changed"])
        self.assertEqual(1, result["lines_added"])
        self.assertEqual("review", result["classification"])
        self.assertEqual(["source-without-tests"], [signal["id"] for signal in result["signals"]])


if __name__ == "__main__":
    unittest.main()
