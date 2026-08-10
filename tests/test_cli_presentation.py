from __future__ import annotations

import contextlib
import io
import json
import os
import re
import unittest
from pathlib import Path
from unittest import mock

from ai_engineering_guardrails import cli


class TtyBuffer(io.StringIO):
    @property
    def encoding(self) -> str:
        return "utf-8"

    def isatty(self) -> bool:
        return True


class CliPresentationTests(unittest.TestCase):
    long_instruction_path = "/synthetic/home/" + "managed-directory/" * 6 + "AGENTS.md"
    validation_report = {
        "schema_version": 1,
        "status": "passed",
        "checks": [
            {
                "id": "generated-output",
                "label": "Generated output",
                "outcome": "passed",
                "detail": "120 files",
            },
            {
                "id": "spacelift-rego",
                "label": "Spacelift Rego",
                "outcome": "skipped",
                "detail": "semantic execution unavailable",
            },
        ],
    }
    status_report = {
        "schema_version": 1,
        "home": "/synthetic/home",
        "products": {
            "codex": {
                "state": "installed",
                "product_availability": "available",
                "safety_profile": "infrastructure-observe",
                "trust_mode": "trusted-workspace",
                "routing_profile": "none",
                "model_availability": "unverified",
                "installed_packs": ["python"],
                "installed_skill_packs": [],
                "shell_enforcement": "configured",
                "structured_tool_enforcement": "configured",
                "spacelift_mcp_enforcement": "pack not installed",
                "effective_global_instruction_file": long_instruction_path,
                "hook_trust": "unverified; changed user hooks may require Codex trust review",
            }
        },
        "safety_profile": "infrastructure-observe",
        "trust_mode": "trusted-workspace",
        "installed_packs": ["python"],
        "target_mapping": "missing; unknown remote targets are protected",
        "credential_capability_detected": False,
        "credential_classes": [],
        "publication_policy": "denied",
        "repository": {
            "repo": "/synthetic/repository",
            "active_packs": ["python", "dependency-management"],
            "disabled_packs": [],
            "evidence": [
                {
                    "pack_id": "python",
                    "kind": "file",
                    "path": "pyproject.toml",
                }
            ],
            "warnings": [],
        },
    }

    def run_cli(self, arguments: list[str], *, tty: bool = False) -> tuple[int, str, str]:
        stdout = TtyBuffer() if tty else io.StringIO()
        stderr = io.StringIO()
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            result = cli.main(arguments)
        return result, stdout.getvalue(), stderr.getvalue()

    def test_validate_human_output_is_rich_and_no_color_is_respected(self) -> None:
        with (
            mock.patch("ai_engineering_guardrails.cli.build.validate", return_value=self.validation_report),
            mock.patch.dict(os.environ, {"TERM": "xterm-256color"}, clear=True),
        ):
            result, coloured, errors = self.run_cli(["validate"], tty=True)
            self.assertEqual(0, result, errors)
            self.assertIn("AI Guardrails Validation", coloured)
            self.assertIn("Generated output", coloured)
            self.assertRegex(coloured, re.compile(r"\x1b\[[0-9;]*3[0-7]m"))

            result, plain, errors = self.run_cli(["validate", "--no-color"], tty=True)
            self.assertEqual(0, result, errors)
            self.assertIn("AI Guardrails Validation", plain)
            self.assertNotIn("\x1b[", plain)

        with (
            mock.patch("ai_engineering_guardrails.cli.build.validate", return_value=self.validation_report),
            mock.patch.dict(os.environ, {"TERM": "xterm-256color", "NO_COLOR": "1"}, clear=True),
        ):
            result, plain, errors = self.run_cli(["validate"], tty=True)
            self.assertEqual(0, result, errors)
            self.assertNotIn("\x1b[", plain)

    def test_shared_product_and_mutation_help_use_neutral_precise_wording(self) -> None:
        help_cases = (
            (["status", "--help"], "product to inspect or manage"),
            (["install", "--help"], "without writing managed configuration"),
            (["task", "establish", "--help"], "without writing installation state"),
            (["component", "trust", "--help"], "without writing installation state"),
            (["component", "revoke", "--help"], "without writing installation state"),
        )
        for arguments, expected in help_cases:
            with self.subTest(arguments=arguments):
                output = io.StringIO()
                with contextlib.redirect_stdout(output), self.assertRaises(SystemExit) as raised:
                    cli.main(arguments)
                self.assertEqual(0, raised.exception.code)
                self.assertIn(expected, " ".join(output.getvalue().split()))

    def test_validate_json_is_one_unstyled_document(self) -> None:
        with (
            mock.patch("ai_engineering_guardrails.cli.build.validate", return_value=self.validation_report),
            mock.patch(
                "ai_engineering_guardrails.cli.presentation.print_validation",
                side_effect=AssertionError("Rich rendering must be bypassed"),
            ),
        ):
            result, output, errors = self.run_cli(["validate", "--format", "json"])
        self.assertEqual(0, result, errors)
        self.assertEqual(self.validation_report, json.loads(output))
        self.assertNotIn("\x1b[", output)

    def test_status_human_and_json_share_the_same_report(self) -> None:
        with (
            mock.patch(
                "ai_engineering_guardrails.cli._resolve_consumer_products",
                return_value=(("codex",), {}),
            ),
            mock.patch("ai_engineering_guardrails.cli.install.status", return_value=self.status_report),
        ):
            result, human, errors = self.run_cli(
                ["status", "--product", "codex", "--home", "/synthetic/home", "--no-color"],
                tty=True,
            )
            self.assertEqual(0, result, errors)
            self.assertIn("AI Guardrails Status", human)
            self.assertIn("infrastructure-observe", human)
            self.assertIn("unverified", human)
            self.assertIn("packs=python", human)
            self.assertIn("exposed pack skills=none", human)
            self.assertIn("hook trust=unverified", human)
            self.assertIn("Repository context", human)
            self.assertIn("dependency-management", human)
            self.assertIn("Repository evidence", human)
            self.assertIn("pyproject.toml", human)
            self.assertNotIn("…", human)
            self.assertIn(self.long_instruction_path, "".join(human.split()))
            self.assertNotIn("\x1b[", human)

            with mock.patch(
                "ai_engineering_guardrails.cli.presentation.print_status",
                side_effect=AssertionError("Rich rendering must be bypassed"),
            ):
                result, machine, errors = self.run_cli(
                    ["status", "--product", "codex", "--home", "/synthetic/home", "--format", "json"]
                )
            self.assertEqual(0, result, errors)
            self.assertEqual(self.status_report, json.loads(machine))

    def test_skills_json_bypasses_rich_and_human_output_is_readable(self) -> None:
        result, human, errors = self.run_cli(["skills", "audit", "--no-color"])
        self.assertEqual(0, result, errors)
        self.assertIn("Skills Audit", human)
        self.assertIn("Skill footprint", human)
        self.assertIn("characters divided by 4", human)
        self.assertIn("Longest descriptions", human)
        self.assertIn("workstation-infrastructure-review", "".join(human.split()))
        self.assertNotIn("\x1b[", human)

        with mock.patch(
            "ai_engineering_guardrails.cli.presentation.print_skills_audit",
            side_effect=AssertionError("Rich rendering must be bypassed"),
        ):
            result, machine, errors = self.run_cli(["skills", "audit", "--format", "json"])
        self.assertEqual(0, result, errors)
        self.assertTrue(json.loads(machine)["audit_complete"])


if __name__ == "__main__":
    unittest.main()
