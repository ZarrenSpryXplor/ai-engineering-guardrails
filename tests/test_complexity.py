from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

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

    def test_recognised_unsupported_dependency_files_are_not_reported_as_no_change(self) -> None:
        fixtures = (
            ("requirements.txt", "example==1\n"),
            ("poetry.lock", "[[package]]\nname = \"example\"\nversion = \"1\"\n"),
            ("pom.xml", "<project><dependencies/></project>\n"),
            ("pdm.lock", "[metadata]\nlock_version = \"4.5\"\n"),
            ("Directory.Packages.props", "<Project/>\n"),
            ("gradle.lockfile", "example:dependency:1.0\n"),
            ("packages.lock.json", "{}\n"),
            ("Chart.lock", "dependencies: []\n"),
            (".terraform.lock.hcl", "provider \"registry.invalid/example\" {}\n"),
            ("Cargo.toml", "[dependencies]\nexample = \"1\"\n"),
            ("Cargo.lock", "# synthetic lock\n"),
        )
        for relative, content in fixtures:
            with self.subTest(relative=relative):
                path = self.repo / relative
                path.write_text(content, encoding="utf-8")
                result = complexity.analyse(self.repo, task_assurance=True)
                self.assertIn(relative, result["dependency_files_changed"])
                self.assertIn(relative, result["ambiguous_dependency_manifests"])
                path.unlink()

    def test_supported_manifest_can_prove_no_new_runtime_dependency(self) -> None:
        manifest = self.repo / "package.json"
        manifest.write_text(json.dumps({"dependencies": {"existing": "1"}}), encoding="utf-8")
        self.git("add", "package.json")
        self.git("commit", "-m", "dependency baseline")
        manifest.write_text(json.dumps({"dependencies": {"existing": "2"}}), encoding="utf-8")

        result = complexity.analyse(self.repo, task_assurance=True)

        self.assertEqual([], result["new_runtime_dependencies"])
        self.assertEqual([], result["ambiguous_dependency_manifests"])
        self.assertEqual(["package.json"], result["dependency_files_changed"])

    def test_mandatory_peer_dependencies_are_runtime_dependencies(self) -> None:
        manifest = self.repo / "package.json"
        manifest.write_text(json.dumps({"peerDependencies": {"existing-peer": "1"}}), encoding="utf-8")
        self.git("add", "package.json")
        self.git("commit", "-m", "peer dependency baseline")
        manifest.write_text(
            json.dumps(
                {
                    "peerDependencies": {"existing-peer": "1", "required-peer": "1", "optional-peer": "1"},
                    "peerDependenciesMeta": {"optional-peer": {"optional": True}},
                }
            ),
            encoding="utf-8",
        )

        result = complexity.analyse(self.repo, task_assurance=True)

        self.assertEqual(["package.json:required-peer"], result["new_runtime_dependencies"])
        self.assertEqual([], result["ambiguous_dependency_manifests"])

    def test_task_assurance_counts_tracked_scanner_ignored_paths_and_rejects_oversized_untracked_lines(self) -> None:
        vendor = self.repo / "vendor"
        vendor.mkdir()
        tracked = vendor / "generated.py"
        tracked.write_text("base\n", encoding="utf-8")
        self.git("add", "vendor/generated.py")
        self.git("commit", "-m", "tracked vendor fixture")
        tracked.write_text("base\nchanged\n", encoding="utf-8")

        ordinary = complexity.analyse(self.repo)
        assured = complexity.analyse(self.repo, task_assurance=True)

        self.assertEqual(0, ordinary["files_changed"])
        self.assertEqual(1, assured["files_changed"])
        self.assertEqual(["vendor/generated.py"], assured["changed_paths"])

        (self.repo / "large-untracked.txt").write_bytes(b"x\n" * 524_289)
        unavailable = complexity.analyse(self.repo, task_assurance=True)

        self.assertFalse(unavailable["available"])
        self.assertIn("line count is unavailable", unavailable["limitation"])

    def test_pep621_is_supported_but_dynamic_or_tool_only_pyproject_is_uncertain(self) -> None:
        manifest = self.repo / "pyproject.toml"
        manifest.write_text(
            '[project]\nname = "synthetic"\nversion = "1"\ndependencies = ["existing>=1"]\n',
            encoding="utf-8",
        )
        self.git("add", "pyproject.toml")
        self.git("commit", "-m", "PEP 621 dependency baseline")
        manifest.write_text(
            '[project]\nname = "synthetic"\nversion = "1"\ndependencies = ["existing>=2", "new-runtime>=1"]\n',
            encoding="utf-8",
        )

        supported = complexity.analyse(self.repo, task_assurance=True)

        self.assertEqual(["pyproject.toml:new-runtime"], supported["new_runtime_dependencies"])
        self.assertEqual([], supported["ambiguous_dependency_manifests"])
        uncertain_values = (
            '[tool.poetry.dependencies]\npython = ">=3.11"\nexample = "1"\n',
            '[project]\nname = "synthetic"\nversion = "1"\ndynamic = ["dependencies"]\n',
        )
        for value in uncertain_values:
            with self.subTest(value=value):
                manifest.write_text(value, encoding="utf-8")
                result = complexity.analyse(self.repo, task_assurance=True)
                self.assertIn("pyproject.toml", result["ambiguous_dependency_manifests"])

    def test_dependency_words_in_documentation_do_not_create_manifest_changes(self) -> None:
        (self.repo / "README.md").write_text("requirements.txt and package-lock.json are examples.\n", encoding="utf-8")

        result = complexity.analyse(self.repo, task_assurance=True)

        self.assertEqual([], result["dependency_files_changed"])
        self.assertEqual([], result["ambiguous_dependency_manifests"])

    def test_untracked_nested_repository_makes_outer_state_unsupported(self) -> None:
        before = complexity.repository_state_digest(self.repo)
        nested = self.repo / "nested"
        nested.mkdir()
        subprocess.run(["git", "-C", str(nested), "init"], check=True, capture_output=True)
        subprocess.run(["git", "-C", str(nested), "config", "user.email", "tests@example.invalid"], check=True)
        subprocess.run(["git", "-C", str(nested), "config", "user.name", "Tests"], check=True)
        (nested / "app.py").write_text("value = 1\n", encoding="utf-8")
        subprocess.run(["git", "-C", str(nested), "add", "app.py"], check=True)
        subprocess.run(["git", "-C", str(nested), "commit", "-m", "nested"], check=True, capture_output=True)

        state = complexity.repository_state(self.repo)
        analysis = complexity.analyse(self.repo)
        (nested / "app.py").write_text("value = 2\n", encoding="utf-8")
        after_edit = complexity.repository_state(self.repo)

        self.assertIsNotNone(before)
        self.assertFalse(state["available"])
        self.assertEqual("unsupported", state["nested_repository_state"])
        self.assertIsNone(state["digest"])
        self.assertFalse(analysis["available"])
        self.assertEqual("unsupported", analysis["nested_repository_state"])
        self.assertIsNone(after_edit["digest"])
        self.assertEqual("unsupported", after_edit["nested_repository_state"])

    def test_ordinary_untracked_directory_is_not_a_nested_repository(self) -> None:
        directory = self.repo / "nested-like"
        directory.mkdir()
        (directory / "app.py").write_text("value = 1\n", encoding="utf-8")

        state = complexity.repository_state(self.repo)

        self.assertTrue(state["available"])
        self.assertEqual("supported", state["nested_repository_state"])
        self.assertIsNotNone(state["digest"])

    def test_gitlink_enumeration_failure_makes_repository_state_unavailable(self) -> None:
        real_git = complexity._git

        def fail_gitlink_enumeration(repo: Path, arguments: tuple[str, ...]) -> bytes:
            if arguments[:2] == ("ls-files", "--stage"):
                raise GuardrailsError("fixture Git link inspection failure")
            return real_git(repo, arguments)

        with mock.patch.object(complexity, "_git", side_effect=fail_gitlink_enumeration):
            state = complexity.repository_state(self.repo)

        self.assertFalse(state["available"])
        self.assertIsNone(state["digest"])
        self.assertEqual("unsupported", state["nested_repository_state"])
        self.assertIn("Git link state", state["limitation"])

    def test_unreadable_untracked_content_makes_repository_state_unavailable(self) -> None:
        opaque = self.repo / "opaque.py"
        opaque.write_text("value = 1\n", encoding="utf-8")
        real_open = Path.open

        def fail_opaque_read(path: Path, *args: object, **kwargs: object):
            if path.name == opaque.name:
                raise OSError("fixture read failure")
            return real_open(path, *args, **kwargs)

        with mock.patch.object(Path, "open", fail_opaque_read):
            state = complexity.repository_state(self.repo)

        self.assertFalse(state["available"])
        self.assertIsNone(state["digest"])
        self.assertEqual("unavailable", state["nested_repository_state"])
        self.assertIn("untracked file content", state["limitation"])

    def test_clean_gitlink_is_supported_but_dirty_submodule_is_not(self) -> None:
        source = Path(self.temporary.name) / "submodule-source"
        source.mkdir()
        subprocess.run(["git", "-C", str(source), "init"], check=True, capture_output=True)
        subprocess.run(["git", "-C", str(source), "config", "user.email", "tests@example.invalid"], check=True)
        subprocess.run(["git", "-C", str(source), "config", "user.name", "Tests"], check=True)
        (source / "module.py").write_text("value = 1\n", encoding="utf-8")
        subprocess.run(["git", "-C", str(source), "add", "module.py"], check=True)
        subprocess.run(["git", "-C", str(source), "commit", "-m", "base"], check=True, capture_output=True)
        subprocess.run(
            ["git", "-c", "protocol.file.allow=always", "-C", str(self.repo), "submodule", "add", str(source), "modules/example"],
            check=True,
            capture_output=True,
        )
        self.git("add", ".gitmodules", "modules/example")
        self.git("commit", "-m", "add local submodule fixture")

        clean = complexity.repository_state(self.repo)
        (self.repo / "modules/example/module.py").write_text("value = 2\n", encoding="utf-8")
        dirty = complexity.repository_state(self.repo)

        self.assertTrue(clean["available"])
        self.assertEqual("supported", clean["nested_repository_state"])
        self.assertFalse(dirty["available"])
        self.assertEqual("unsupported", dirty["nested_repository_state"])


if __name__ == "__main__":
    unittest.main()
