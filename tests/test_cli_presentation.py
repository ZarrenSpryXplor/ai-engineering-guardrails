from __future__ import annotations

import contextlib
import io
import json
import os
import re
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from ai_engineering_guardrails import cli, terminal_ux


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

    def assert_bounded_human_output(self, output: str) -> None:
        plain = re.sub(r"\x1b\[[0-9;]*m", "", output)
        self.assertTrue(plain.strip())
        self.assertLessEqual(max(map(len, plain.splitlines()), default=0), 80)

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
            self.assert_bounded_human_output(coloured)

            result, plain, errors = self.run_cli(["validate", "--no-color"], tty=True)
            self.assertEqual(0, result, errors)
            self.assertIn("AI Guardrails Validation", plain)
            self.assertNotIn("\x1b[", plain)
            self.assert_bounded_human_output(plain)

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
                self.assert_bounded_human_output(output.getvalue())

    def test_help_is_bounded_even_when_the_environment_is_wide(self) -> None:
        output = io.StringIO()
        with (
            mock.patch.dict(os.environ, {"COLUMNS": "160", "NO_COLOR": "1"}, clear=False),
            contextlib.redirect_stdout(output),
            self.assertRaises(SystemExit) as raised,
        ):
            cli.main(["--help"])
        self.assertEqual(0, raised.exception.code)
        self.assertIn("usage:", output.getvalue())
        self.assert_bounded_human_output(output.getvalue())

        plain = TtyBuffer()
        with (
            mock.patch.dict(os.environ, {"COLUMNS": "160", "TERM": "xterm-256color"}, clear=True),
            contextlib.redirect_stdout(plain),
            self.assertRaises(SystemExit) as raised,
        ):
            cli.main(["--no-color", "--help"])
        self.assertEqual(0, raised.exception.code)
        self.assertNotIn("\x1b[", plain.getvalue())
        self.assert_bounded_human_output(plain.getvalue())

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
            self.assert_bounded_human_output(human)

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

    def test_representative_human_command_families_use_bounded_rich_layouts(self) -> None:
        cases = (
            (
                ["--no-color", "build"],
                (mock.patch("ai_engineering_guardrails.cli.build.build", return_value=None),),
                "Build",
            ),
            (
                ["--no-color", "doctor", "--home", "/synthetic/home"],
                (
                    mock.patch(
                        "ai_engineering_guardrails.cli.install.doctor",
                        return_value={
                            "checks": [
                                {"id": "runtime", "outcome": "pass", "detail": "ready"}
                            ]
                        },
                    ),
                ),
                "AI Guardrails Doctor",
            ),
            (
                ["--no-color", "effective", "--home", "/synthetic/home", "--format", "human"],
                (
                    mock.patch(
                        "ai_engineering_guardrails.cli.install.effective_configuration",
                        return_value={"schema_version": 1, "products": {"codex": {"state": "installed"}}},
                    ),
                ),
                "Effective configuration",
            ),
            (
                ["--no-color", "diff-installed", "--home", "/synthetic/home"],
                (
                    mock.patch(
                        "ai_engineering_guardrails.cli.install.diff_installed",
                        return_value={
                            "products": {
                                "codex": [
                                    {
                                        "state": "unchanged",
                                        "path": self.long_instruction_path,
                                    }
                                ]
                            }
                        },
                    ),
                ),
                "Installed content diff",
            ),
            (
                ["--no-color", "docs", "audit", "--repo", "/synthetic/repository"],
                (
                    mock.patch(
                        "ai_engineering_guardrails.cli.scan.audit_documentation",
                        return_value=(Path("/synthetic/repository"), [], 3),
                    ),
                ),
                "Documentation audit",
            ),
            (
                ["--no-color", "packs", "validate"],
                (mock.patch("ai_engineering_guardrails.cli.packs.validate_packs", return_value=(22, 44)),),
                "Capability pack validation",
            ),
            (
                ["--no-color", "component", "list", "--home", "/synthetic/home"],
                (mock.patch("ai_engineering_guardrails.cli.components.list_trust", return_value=[]),),
                "Component trust records",
            ),
            (
                ["--no-color", "events", "summary", "--home", "/synthetic/home"],
                (
                    mock.patch(
                        "ai_engineering_guardrails.cli.terminal_ux.audit_summary",
                        return_value={
                            "window": "24h",
                            "warnings": 0,
                            "denials": 0,
                            "last_event_at": None,
                        },
                    ),
                    mock.patch("ai_engineering_guardrails.cli.terminal_ux.refresh_audit_summary_cache"),
                ),
                "Guardrail events",
            ),
        )
        for arguments, patches, expected in cases:
            with self.subTest(arguments=arguments), contextlib.ExitStack() as stack:
                for patcher in patches:
                    stack.enter_context(patcher)
                result, output, errors = self.run_cli(arguments)
                self.assertEqual(0, result, errors)
                self.assertIn(expected, output)
                self.assertNotIn("\x1b[", output)
                self.assertNotIn("…", output)
                self.assert_bounded_human_output(output)

    def test_effective_keeps_json_default_and_offers_explicit_human_output(self) -> None:
        report = {"schema_version": 1, "products": {"codex": {"state": "installed"}}}
        with mock.patch(
            "ai_engineering_guardrails.cli.install.effective_configuration",
            return_value=report,
        ):
            result, machine, errors = self.run_cli(["effective", "--home", "/synthetic/home"])
            self.assertEqual(0, result, errors)
            self.assertEqual(report, json.loads(machine))
            self.assertNotIn("\x1b[", machine)

            result, human, errors = self.run_cli(
                ["effective", "--home", "/synthetic/home", "--format", "human", "--no-color"]
            )
            self.assertEqual(0, result, errors)
            self.assertIn("Effective configuration", human)
            self.assert_bounded_human_output(human)

    def test_scan_machine_formats_remain_unstyled_including_file_output(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            for output_format in ("json", "sarif", "junit"):
                with self.subTest(output_format=output_format):
                    result, output, errors = self.run_cli(
                        ["scan", "--repo", str(root), "--format", output_format]
                    )
                    self.assertEqual(0, result, errors)
                    self.assertNotIn("\x1b[", output)
                    self.assertTrue(output.strip())

            destination = root / "report.json"
            result, output, errors = self.run_cli(
                [
                    "scan",
                    "--repo",
                    str(root),
                    "--format",
                    "json",
                    "--output",
                    str(destination),
                ]
            )
            self.assertEqual(0, result, errors)
            self.assertNotIn("\x1b[", output)
            self.assertTrue(destination.is_file())
            json.loads(destination.read_text(encoding="utf-8"))

    def test_scan_and_docs_human_findings_preserve_limitations(self) -> None:
        finding = cli.scan.Finding(
            "bounded-parser",
            "warning",
            "configuration.yml",
            7,
            "Review the bounded structural match.",
            "YAML anchors and templates were not evaluated.",
        )
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            destination = root / "human-report.txt"
            with mock.patch(
                "ai_engineering_guardrails.cli.scan.scan_repository",
                return_value=[finding],
            ):
                result, output, errors = self.run_cli(["scan", "--repo", str(root)])
                self.assertEqual(0, result, errors)
                self.assertIn("Limitation: YAML anchors and templates were not evaluated.", output)
                self.assert_bounded_human_output(output)

                result, notice, errors = self.run_cli(
                    ["scan", "--repo", str(root), "--format", "human", "--output", str(destination)]
                )
                self.assertEqual(0, result, errors)
                self.assertIn("Report written", notice)
                rendered = destination.read_text(encoding="utf-8")
                self.assertIn("Repository scan", rendered)
                self.assertIn("Limitation: YAML anchors and templates were not evaluated.", rendered)
                self.assertNotIn("\x1b[", rendered)
                self.assertNotIn("…", rendered)
                self.assert_bounded_human_output(rendered)

            with mock.patch(
                "ai_engineering_guardrails.cli.scan.audit_documentation",
                return_value=(root, [finding], 1),
            ):
                result, output, errors = self.run_cli(["docs", "audit", "--repo", str(root)])
            self.assertEqual(0, result, errors)
            self.assertIn("Limitation: YAML anchors and templates were not evaluated.", output)

    def test_receipt_errors_follow_the_effective_machine_or_human_mode(self) -> None:
        cases = (
            ([], False),
            (["--format", "json"], False),
            (["--format", "compact"], True),
            (["--compact"], True),
            (["--fun"], True),
            (["--format", "human"], True),
        )
        for options, human in cases:
            arguments = ["receipt", "--home", "/synthetic/home", "--repo", "/synthetic/repo", *options]
            with self.subTest(options=options), mock.patch(
                "ai_engineering_guardrails.cli.scan.session_receipt",
                side_effect=OSError("synthetic receipt failure"),
            ):
                result, output, errors = self.run_cli(arguments)
            self.assertEqual(1, result)
            self.assertEqual("", output)
            if human:
                self.assertIn("Error: synthetic receipt failure", errors)
                self.assertNotIn("error: synthetic receipt failure", errors)
                self.assert_bounded_human_output(errors)
            else:
                self.assertEqual("error: synthetic receipt failure\n", errors)

    def test_exact_setup_payloads_bypass_rich_rendering(self) -> None:
        cases = (
            (["statusline", "print-codex-setup", "--profile", "standard"], terminal_ux.codex_setup("standard")),
            (["statusline", "print-cursor-setup"], terminal_ux.cursor_setup()),
        )
        for arguments, expected in cases:
            with self.subTest(arguments=arguments), mock.patch(
                "ai_engineering_guardrails.cli.presentation.print_records",
                side_effect=AssertionError("exact setup output must bypass Rich"),
            ):
                result, output, errors = self.run_cli(arguments)
                self.assertEqual(0, result, errors)
                self.assertEqual(expected + "\n", output)


if __name__ == "__main__":
    unittest.main()
