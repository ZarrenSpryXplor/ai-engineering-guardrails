from __future__ import annotations

import contextlib
import importlib.util
import io
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
CI_TOOL = REPOSITORY_ROOT / "tools/ci.py"
CI_SPEC = importlib.util.spec_from_file_location("guardrails_ci", CI_TOOL)
if CI_SPEC is None or CI_SPEC.loader is None:
    raise RuntimeError("cannot load CI reporting helper")
CI_MODULE = importlib.util.module_from_spec(CI_SPEC)
CI_SPEC.loader.exec_module(CI_MODULE)


class CiReportingTests(unittest.TestCase):
    def run_ci(self, arguments: list[str], environment: dict[str, str]) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, str(CI_TOOL), *arguments],
            cwd=REPOSITORY_ROOT,
            env={**os.environ, **environment},
            check=False,
            capture_output=True,
            text=True,
        )

    def test_unittest_summary_contains_only_aggregate_results(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            tests = root / "test_sample.py"
            tests.write_text(
                """import unittest

class SampleTests(unittest.TestCase):
    def test_failure(self):
        self.fail(\"synthetic-sensitive-detail\")

    @unittest.skip(\"synthetic skip\")
    def test_skip(self):
        pass
""",
                encoding="utf-8",
            )
            summary = root / "summary.md"
            result = self.run_ci(
                ["test", "discover", "-s", str(root), "-p", "test_sample.py", "-v"],
                {
                    "GITHUB_STEP_SUMMARY": str(summary),
                    "CI_TEST_SUMMARY_TITLE": "Synthetic tests",
                    "CI_SUMMARY_PLATFORM": "synthetic-os / Python 3.11",
                },
            )

            self.assertEqual(1, result.returncode)
            text = summary.read_text(encoding="utf-8")
            self.assertIn("### Synthetic tests", text)
            self.assertIn("| Failed | 2 | 1 | 0 | 1 | 0 | 0 |", text)
            self.assertNotIn("synthetic-sensitive-detail", text)
            self.assertNotIn("synthetic skip", text)

    def test_unittest_summary_preserves_success(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "test_sample.py").write_text(
                """import unittest

class SampleTests(unittest.TestCase):
    def test_success(self):
        self.assertTrue(True)
""",
                encoding="utf-8",
            )
            summary = root / "summary.md"
            result = self.run_ci(
                ["test", "discover", "-s", str(root), "-p", "test_sample.py"],
                {"GITHUB_STEP_SUMMARY": str(summary)},
            )

            self.assertEqual(0, result.returncode)
            self.assertIn("| Passed | 1 | 0 | 0 | 0 | 0 | 0 |", summary.read_text(encoding="utf-8"))

    def test_missing_github_summary_is_a_noop(self) -> None:
        result = self.run_ci(
            ["test", "tests.test_ci.CiReportingTests.test_job_summary_escapes_metadata_and_links_the_run"],
            {"GITHUB_STEP_SUMMARY": ""},
        )

        self.assertEqual(0, result.returncode)

    def test_job_summary_escapes_metadata_and_links_the_run(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            summary = Path(temporary) / "summary.md"
            result = self.run_ci(
                ["summary"],
                {
                    "GITHUB_STEP_SUMMARY": str(summary),
                    "GITHUB_SERVER_URL": "https://github.example",
                    "GITHUB_REPOSITORY": "owner/repository",
                    "GITHUB_RUN_ID": "1234",
                    "CI_SUMMARY_TITLE": "Wheel smoke | Windows",
                    "CI_SUMMARY_RESULT": "failure",
                    "CI_SUMMARY_PLATFORM": "Windows | Python 3.11",
                    "CI_SUMMARY_CHECKS": "Build=success\nTests=failure\nArtifact=skipped",
                },
            )

            self.assertEqual(0, result.returncode)
            text = summary.read_text(encoding="utf-8")
            self.assertIn("### Wheel smoke \\| Windows", text)
            self.assertIn("Platform: Windows \\| Python 3.11", text)
            self.assertIn("| Build | Passed |", text)
            self.assertIn("| Tests | Failed |", text)
            self.assertIn("| Artifact | Skipped |", text)
            self.assertIn("https://github.example/owner/repository/actions/runs/1234", text)

    def test_validation_summary_reports_optional_validator_outcomes(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            summary = Path(temporary) / "summary.md"
            result = self.run_ci(
                ["validate"],
                {
                    "GITHUB_STEP_SUMMARY": str(summary),
                    "CI_VALIDATION_SUMMARY_TITLE": "Synthetic validation",
                    "CI_SUMMARY_PLATFORM": "synthetic-os / Python 3.11",
                },
            )

            self.assertEqual(0, result.returncode)
            text = summary.read_text(encoding="utf-8")
            self.assertIn("### Synthetic validation", text)
            self.assertIn("| Repository validation | Passed |", text)
            self.assertRegex(text, r"\| Codex execpolicy \| (Passed|Skipped) \|")
            self.assertIn("| Spacelift policy structure | Passed |", text)
            self.assertRegex(text, r"\| OPA semantic Rego \| (Passed|Skipped) \|")
            self.assertNotIn(str(REPOSITORY_ROOT), text)

    def test_validation_failure_does_not_mislabel_canonical_data(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            summary = Path(temporary) / "summary.md"
            failed = subprocess.CompletedProcess(
                args=[sys.executable, "tools/guardrails.py", "validate"],
                returncode=1,
                stdout="",
                stderr="error: OPA semantic policy tests failed\n",
            )
            with (
                mock.patch.object(CI_MODULE.subprocess, "run", return_value=failed),
                mock.patch.dict(os.environ, {"GITHUB_STEP_SUMMARY": str(summary)}),
                contextlib.redirect_stderr(io.StringIO()),
            ):
                returncode = CI_MODULE.run_validation()

            self.assertEqual(1, returncode)
            text = summary.read_text(encoding="utf-8")
            self.assertIn("| Repository validation | Failed |", text)
            self.assertIn("| Codex execpolicy | Unknown |", text)
            self.assertIn("| Spacelift policy structure | Unknown |", text)
            self.assertIn("| OPA semantic Rego | Unknown |", text)
            self.assertNotIn("Canonical and generated data", text)

    def test_validation_summary_preserves_explicit_skips(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            summary = Path(temporary) / "summary.md"
            skipped = subprocess.CompletedProcess(
                args=[sys.executable, "tools/guardrails.py", "validate"],
                returncode=0,
                stdout=(
                    "validation passed: synthetic aggregate\n"
                    "codex execpolicy check: skipped (codex executable not available)\n"
                    "Spacelift policy validation: skipped semantic Rego execution "
                    "(opa executable not available); structural checks passed\n"
                ),
                stderr="",
            )
            with (
                mock.patch.object(CI_MODULE.subprocess, "run", return_value=skipped),
                mock.patch.dict(os.environ, {"GITHUB_STEP_SUMMARY": str(summary)}),
                contextlib.redirect_stdout(io.StringIO()),
            ):
                returncode = CI_MODULE.run_validation()

            self.assertEqual(0, returncode)
            text = summary.read_text(encoding="utf-8")
            self.assertIn("| Repository validation | Passed |", text)
            self.assertIn("| Codex execpolicy | Skipped |", text)
            self.assertIn("| Spacelift policy structure | Passed |", text)
            self.assertIn("| OPA semantic Rego | Skipped |", text)

    def test_job_summary_rejects_malformed_check_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            summary = Path(temporary) / "summary.md"
            result = self.run_ci(
                ["summary"],
                {
                    "GITHUB_STEP_SUMMARY": str(summary),
                    "CI_SUMMARY_RESULT": "success",
                    "CI_SUMMARY_CHECKS": "missing-outcome",
                },
            )

            self.assertNotEqual(0, result.returncode)
            self.assertFalse(summary.exists())


if __name__ == "__main__":
    unittest.main()
