from __future__ import annotations

import contextlib
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from ai_engineering_guardrails import build, cli, install, packs, state
from ai_engineering_guardrails.util import ROOT, json_bytes


class ConsumerJourneyTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        root = Path(self.temporary.name).resolve()
        self.home = root / "home"
        self.repo = root / "application"
        self.bin = root / "bin"
        self.home.mkdir()
        self.repo.mkdir()
        self.bin.mkdir()
        (self.repo / "pyproject.toml").write_text('[project]\nname = "synthetic"\n', encoding="utf-8")

        codex_config = self.home / ".codex/config.toml"
        codex_config.parent.mkdir(parents=True)
        codex_config.write_bytes(b'model = "user-selected-model"\napproval_policy = "user-choice"\n')

        cursor_root = self.home / ".cursor"
        cursor_root.mkdir()
        (cursor_root / "preferences.json").write_bytes(b'{"theme":"user-choice"}\n')
        (cursor_root / "hooks.json").write_bytes(
            json_bytes({"version": 1, "hooks": {"stop": [{"command": "user-audit"}]}})
        )

        cursor_executable = self.bin / "cursor"
        cursor_executable.write_text("#!/usr/bin/env python3\n", encoding="utf-8")
        cursor_executable.chmod(0o755)

        self.original_codex_config = codex_config.read_bytes()
        self.original_cursor_preferences = (cursor_root / "preferences.json").read_bytes()
        self.original_cursor_hooks = (cursor_root / "hooks.json").read_bytes()

    def run_cli(self, arguments: list[str]) -> tuple[int, str, str]:
        stdout = io.StringIO()
        stderr = io.StringIO()
        environment = {"PATH": str(self.bin), "CODEX_HOME": ""}
        with (
            mock.patch.dict(os.environ, environment, clear=False),
            mock.patch("ai_engineering_guardrails.cli.Path.cwd", return_value=self.repo),
            contextlib.redirect_stdout(stdout),
            contextlib.redirect_stderr(stderr),
        ):
            result = cli.main(arguments)
        return result, stdout.getvalue(), stderr.getvalue()

    def snapshot(self) -> dict[str, bytes]:
        return {
            path.relative_to(self.home).as_posix(): path.read_bytes()
            for path in sorted(self.home.rglob("*"))
            if path.is_file() and not path.is_symlink()
        }

    def test_no_argument_consumer_journey(self) -> None:
        before_preview = self.snapshot()
        result, preview, errors = self.run_cli(["install", "--home", str(self.home), "--dry-run"])
        self.assertEqual(0, result, errors)
        self.assertEqual(before_preview, self.snapshot())
        self.assertIn("Detected products: OpenAI Codex, Cursor", preview)
        self.assertIn("Repository capability detection: not run by install/update", preview)
        self.assertIn("ai-guardrails packs detect --repo <path>", preview)
        self.assertIn("Default safety posture", preview)
        self.assertIn("Normal application development: enabled", preview)
        self.assertIn("Infrastructure observation and local validation/planning: enabled", preview)
        self.assertIn("Remote infrastructure and production mutation: denied", preview)
        self.assertIn("Unknown remote targets: protected; no target mapping required", preview)
        self.assertIn("Model/subagent routing: disabled; primary model unchanged", preview)
        self.assertIn("Denied operation classes: destructive, sensitive-read, publish", preview)
        self.assertIn("Managed block", preview)
        self.assertIn(str(self.home / ".codex/AGENTS.md"), preview)
        self.assertIn(str(self.home / ".cursor/hooks.json"), preview)
        self.assertIn(str(self.home / state.STATE_RELATIVE), preview)
        self.assertIn("Skills to install", preview)
        self.assertIn("workstation-java", preview)
        self.assertIn("Agents to install: none", preview)
        self.assertIn("Backups planned for", preview)
        self.assertIn(str(self.home / ".cursor/hooks.json"), preview)
        self.assertIn("Left unchanged: primary model", preview)
        self.assertIn("Manual step after install", preview)
        self.assertIn("print-cursor-rules", preview)
        self.assertIn("No changes were made", preview)
        self.assertNotIn(str(ROOT), preview)
        self.assertNotRegex(preview, r"\b[0-9a-f]{32,64}\b")

        result, installed_output, errors = self.run_cli(["install", "--home", str(self.home)])
        self.assertEqual(0, result, errors)
        self.assertIn("Installation integrity: passed", installed_output)
        installed_state = json.loads((self.home / state.STATE_RELATIVE).read_text(encoding="utf-8"))
        self.assertEqual({"codex", "cursor"}, set(installed_state["products"]))
        expected_packs = set(packs.default_pack_ids())
        expected_skill_packs = set(packs.default_skill_pack_ids())
        for product in ("codex", "cursor"):
            product_state = installed_state["products"][product]
            self.assertEqual(expected_packs, set(product_state["installed_packs"]))
            self.assertEqual(expected_skill_packs, set(product_state["installed_skill_packs"]))
            self.assertEqual("none", product_state["routing_profile"])
            self.assertEqual("infrastructure-observe", product_state["safety_profile"])
            self.assertEqual({}, product_state["model_overrides"])
        self.assertTrue((self.home / ".agents/skills/workstation-java/SKILL.md").is_file())
        self.assertFalse((self.home / ".agents/skills/workstation-kubernetes/SKILL.md").exists())
        self.assertFalse((self.home / ".codex/agents").exists())
        self.assertFalse((self.home / ".cursor/agents").exists())
        self.assertEqual(self.original_codex_config, (self.home / ".codex/config.toml").read_bytes())
        self.assertEqual(
            self.original_cursor_preferences,
            (self.home / ".cursor/preferences.json").read_bytes(),
        )

        first_install = self.snapshot()
        result, repeated_output, errors = self.run_cli(["install", "--home", str(self.home)])
        self.assertEqual(0, result, errors)
        self.assertEqual(first_install, self.snapshot())
        self.assertIn("already current", repeated_output)

        result, update_output, errors = self.run_cli(["update", "--home", str(self.home)])
        self.assertEqual(0, result, errors)
        self.assertEqual(first_install, self.snapshot())
        self.assertIn("already current", update_output)

        result, status_output, errors = self.run_cli(["status", "--home", str(self.home)])
        self.assertEqual(0, result, errors)
        self.assertIn("codex: state: installed", status_output)
        self.assertIn("cursor: state: installed", status_output)
        self.assertNotIn("claude:", status_output)
        self.assertIn("manual step outstanding", status_output)
        self.assertNotIn("User Rules installed", status_output)
        self.assertIn("routing: configured (none)", status_output)
        self.assertIn("active safety profile: infrastructure-observe", status_output)

        runtime_record = next(
            record
            for record in installed_state["products"]["codex"]["managed"]
            if record["kind"] == "runtime-directory"
        )
        runtime = self.home / runtime_record["path"]
        denied = subprocess.run(
            [sys.executable, str(runtime / "hook_runtime.py"), "--product", "codex"],
            input=json.dumps(
                {
                    "hook_event_name": "PreToolUse",
                    "tool_name": "Bash",
                    "tool_input": {
                        "command": "kubectl --context synthetic-dev --namespace app apply -f manifest.yaml"
                    },
                }
            ),
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual("deny", json.loads(denied.stdout)["hookSpecificOutput"]["permissionDecision"])

        before_uninstall = self.snapshot()
        result, uninstall_preview, errors = self.run_cli(
            ["uninstall", "--home", str(self.home), "--dry-run"]
        )
        self.assertEqual(0, result, errors)
        self.assertEqual(before_uninstall, self.snapshot())
        self.assertIn("dry run complete; no files were changed", uninstall_preview)

        result, _, errors = self.run_cli(["uninstall", "--home", str(self.home)])
        self.assertEqual(0, result, errors)
        self.assertFalse((self.home / ".codex/AGENTS.md").exists())
        self.assertFalse((self.home / ".agents/skills/workstation-java").exists())
        self.assertEqual(self.original_codex_config, (self.home / ".codex/config.toml").read_bytes())
        self.assertEqual(
            self.original_cursor_preferences,
            (self.home / ".cursor/preferences.json").read_bytes(),
        )
        self.assertEqual(self.original_cursor_hooks, (self.home / ".cursor/hooks.json").read_bytes())
        self.assertTrue((self.bin / "cursor").is_file())

    def test_install_and_update_do_not_scan_the_current_directory(self) -> None:
        with mock.patch(
            "ai_engineering_guardrails.cli.packs.detect_packs",
            side_effect=AssertionError("install/update must not scan the current directory"),
        ):
            result, install_output, errors = self.run_cli(
                ["install", "--product", "codex", "--home", str(self.home)]
            )
            self.assertEqual(0, result, errors)
            self.assertIn("Repository capability detection: not run", install_output)

            result, update_output, errors = self.run_cli(
                ["update", "--product", "codex", "--home", str(self.home), "--verbose"]
            )
            self.assertEqual(0, result, errors)
            self.assertIn("Repository capability detection: not run", update_output)

    def test_skill_catalogue_cli_option_previews_full_managed_exposure(self) -> None:
        before = self.snapshot()

        result, output, errors = self.run_cli(
            [
                "install",
                "--product",
                "codex",
                "--home",
                str(self.home),
                "--skill-catalogue",
                "all",
                "--dry-run",
            ]
        )

        self.assertEqual(0, result, errors)
        self.assertEqual(before, self.snapshot())
        self.assertIn("Global skill catalogue: 22 pack skill(s), plus six core skills", output)

    def test_no_detected_product_reports_explicit_command_without_writing(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            empty_home = Path(temporary).resolve()
            empty_bin = empty_home / "bin"
            empty_bin.mkdir()
            stdout = io.StringIO()
            stderr = io.StringIO()
            with (
                mock.patch.dict(os.environ, {"PATH": str(empty_bin), "CODEX_HOME": ""}, clear=False),
                contextlib.redirect_stdout(stdout),
                contextlib.redirect_stderr(stderr),
            ):
                result = cli.main(["install", "--home", str(empty_home), "--dry-run"])
            self.assertEqual(1, result)
            self.assertIn("No supported product was detected", stderr.getvalue())
            self.assertIn("ai-guardrails install --product codex", stderr.getvalue())
            self.assertEqual([empty_bin], list(empty_home.iterdir()))

    def test_dry_run_uses_in_memory_build_when_checked_in_output_is_stale(self) -> None:
        original_build_artifacts = build.build_artifacts

        def render_with_unwritten_change(*args: object, **kwargs: object) -> dict[Path, bytes]:
            artifacts = original_build_artifacts(*args, **kwargs)  # type: ignore[arg-type]
            policy_path = Path("dist/codex/AGENTS.md")
            artifacts[policy_path] = artifacts[policy_path].replace(
                b"# Workstation AI Guardrails\n",
                b"# Workstation AI Guardrails\n\nIn-memory preview fixture.\n",
                1,
            )
            return artifacts

        before_preview = self.snapshot()
        with mock.patch("ai_engineering_guardrails.build.build_artifacts", side_effect=render_with_unwritten_change):
            result, preview, errors = self.run_cli(
                ["install", "--home", str(self.home), "--dry-run"]
            )
        self.assertEqual(0, result, errors)
        self.assertEqual(before_preview, self.snapshot())
        self.assertIn("Build and local compatibility validation: passed", preview)
        self.assertIn("No changes were made", preview)

    def test_product_detection_reuses_executable_and_configuration_evidence(self) -> None:
        with mock.patch.dict(os.environ, {"PATH": str(self.bin), "CODEX_HOME": ""}, clear=False):
            detected = install.detect_products(self.home)
        self.assertEqual(("codex", "cursor"), tuple(detected))
        self.assertIn("configuration", detected["codex"])
        self.assertIn("executable", detected["cursor"])

    def test_product_detection_honours_safe_alternate_codex_home(self) -> None:
        alternate_codex_home = self.home / ".custom-codex"
        alternate_codex_home.mkdir()
        with mock.patch.dict(
            os.environ,
            {"PATH": str(self.bin), "CODEX_HOME": str(alternate_codex_home)},
            clear=False,
        ):
            detected = install.detect_products(self.home)
        self.assertIn("configuration", detected["codex"])


if __name__ == "__main__":
    unittest.main()
