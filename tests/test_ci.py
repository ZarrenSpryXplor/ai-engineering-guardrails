from __future__ import annotations

import contextlib
import importlib.util
import io
import json
import os
import subprocess
import sys
import tarfile
import tempfile
import unittest
import zipfile
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
    def write_release_artifacts(
        self,
        directory: Path,
        *,
        project_name: str = "ai-engineering-guardrails",
        version: str = "1.2.3",
        sdist_filename_name: str | None = None,
        wheel_version: str | None = None,
        sdist_version: str | None = None,
    ) -> tuple[Path, Path]:
        filename_name = project_name.replace("-", "_")

        def metadata(value: str) -> bytes:
            return f"Metadata-Version: 2.3\nName: {project_name}\nVersion: {value}\n".encode("utf-8")

        wheel = directory / f"{filename_name}-{version}-py3-none-any.whl"
        with zipfile.ZipFile(wheel, "w") as archive:
            archive.writestr(
                f"{filename_name}-{version}.dist-info/METADATA",
                metadata(wheel_version or version),
            )
        sdist_name = sdist_filename_name or project_name
        sdist = directory / f"{sdist_name}-{version}.tar.gz"
        payload = metadata(sdist_version or version)
        member = tarfile.TarInfo(f"{sdist_name}-{version}/PKG-INFO")
        member.size = len(payload)
        with tarfile.open(sdist, "w:gz") as archive:
            archive.addfile(member, io.BytesIO(payload))
        return wheel, sdist

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

    def test_validation_summary_reports_semantic_rego_pass(self) -> None:
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
            self.assertIn("| OPA semantic Rego | Passed |", text)
            self.assertNotIn(str(REPOSITORY_ROOT), text)

    def test_validation_failure_does_not_mislabel_canonical_data(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            summary = Path(temporary) / "summary.md"
            failed = subprocess.CompletedProcess(
                args=[sys.executable, "tools/guardrails.py", "validate", "--format", "json"],
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

    def test_validation_summary_preserves_optional_codex_skip(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            summary = Path(temporary) / "summary.md"
            skipped = subprocess.CompletedProcess(
                args=[sys.executable, "tools/guardrails.py", "validate", "--format", "json"],
                returncode=0,
                stdout=json.dumps(
                    {
                        "schema_version": 1,
                        "status": "passed",
                        "checks": [
                            {"id": "generated-output", "outcome": "passed"},
                            {"id": "policy-fixtures", "outcome": "passed"},
                            {"id": "capability-packs", "outcome": "passed"},
                            {"id": "routing-agents", "outcome": "passed"},
                            {"id": "codex-execpolicy", "outcome": "skipped"},
                            {"id": "spacelift-rego", "outcome": "passed"},
                        ],
                    }
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
            self.assertIn("| OPA semantic Rego | Passed |", text)

    def test_validation_rejects_skipped_spacelift_semantics(self) -> None:
        completed = subprocess.CompletedProcess(
            args=[sys.executable, "tools/guardrails.py", "validate", "--format", "json"],
            returncode=0,
            stdout=json.dumps(
                {
                    "schema_version": 1,
                    "status": "passed",
                    "checks": [
                        {"id": "generated-output", "outcome": "passed"},
                        {"id": "policy-fixtures", "outcome": "passed"},
                        {"id": "capability-packs", "outcome": "passed"},
                        {"id": "routing-agents", "outcome": "passed"},
                        {"id": "codex-execpolicy", "outcome": "skipped"},
                        {"id": "spacelift-rego", "outcome": "skipped"},
                    ],
                }
            ),
            stderr="",
        )
        errors = io.StringIO()
        with (
            mock.patch.object(CI_MODULE.subprocess, "run", return_value=completed),
            contextlib.redirect_stdout(io.StringIO()),
            contextlib.redirect_stderr(errors),
        ):
            returncode = CI_MODULE.run_validation()

        self.assertEqual(1, returncode)
        self.assertIn("requires OPA semantic Rego execution", errors.getvalue())

    def test_validation_workflows_provision_pinned_opa(self) -> None:
        action = "open-policy-agent/setup-opa@b2b258e089860efaadaaf71bf6e3aecb4a3eeff1 # v2.4.0"
        for relative, expected_uses in (
            (".github/workflows/tests.yml", 2),
            (".github/workflows/publish-pypi.yml", 1),
        ):
            with self.subTest(workflow=relative):
                text = (REPOSITORY_ROOT / relative).read_text(encoding="utf-8")
                self.assertIn('OPA_VERSION: "1.19.0"', text)
                self.assertEqual(expected_uses, text.count(action))
                self.assertEqual(expected_uses, text.count("version: ${{ env.OPA_VERSION }}"))

    def test_validation_summary_rejects_malformed_json_contract(self) -> None:
        checks = [
            {"id": "generated-output", "outcome": "passed"},
            {"id": "policy-fixtures", "outcome": "passed"},
            {"id": "capability-packs", "outcome": "passed"},
            {"id": "routing-agents", "outcome": "passed"},
            {"id": "codex-execpolicy", "outcome": "passed"},
            {"id": "spacelift-rego", "outcome": "passed"},
        ]
        malformed = (
            {"schema_version": 2, "status": "passed", "checks": checks},
            {"schema_version": 1, "status": "passed", "checks": "not-a-list"},
            {
                "schema_version": 1,
                "status": "passed",
                "checks": [*checks[:-1], {"id": "spacelift-rego", "outcome": "unknown"}],
            },
        )
        for report in malformed:
            with self.subTest(report=report), tempfile.TemporaryDirectory() as temporary:
                summary = Path(temporary) / "summary.md"
                completed = subprocess.CompletedProcess(
                    args=[sys.executable, "tools/guardrails.py", "validate", "--format", "json"],
                    returncode=0,
                    stdout=json.dumps(report),
                    stderr="",
                )
                errors = io.StringIO()
                with (
                    mock.patch.object(CI_MODULE.subprocess, "run", return_value=completed),
                    mock.patch.dict(os.environ, {"GITHUB_STEP_SUMMARY": str(summary)}),
                    contextlib.redirect_stdout(io.StringIO()),
                    contextlib.redirect_stderr(errors),
                ):
                    returncode = CI_MODULE.run_validation()

                self.assertEqual(1, returncode)
                self.assertIn("expected JSON report", errors.getvalue())
                self.assertFalse(summary.exists())

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

    def test_release_tag_validation_requires_documented_v_prefix(self) -> None:
        self.assertEqual("1.2.3", CI_MODULE.validate_release_tag("v1.2.3", "1.2.3"))
        self.assertEqual("1.2.3rc1", CI_MODULE.validate_release_tag("v1.2.3rc1", "1.2.3rc1"))
        for tag in ("1.2.3", "v1.2.4", "release-1.2.3"):
            with self.subTest(tag=tag):
                with self.assertRaises(ValueError):
                    CI_MODULE.validate_release_tag(tag, "1.2.3")

    def test_release_artifact_validation_accepts_one_matching_wheel_and_sdist(self) -> None:
        for sdist_filename_name in ("ai-engineering-guardrails", "ai_engineering_guardrails"):
            with self.subTest(sdist_filename_name=sdist_filename_name), tempfile.TemporaryDirectory() as temporary:
                directory = Path(temporary)
                wheel, sdist = self.write_release_artifacts(
                    directory,
                    sdist_filename_name=sdist_filename_name,
                )

                self.assertEqual(
                    (wheel, sdist),
                    CI_MODULE.validate_release_artifacts(
                        directory,
                        project_name="ai-engineering-guardrails",
                        package_version="1.2.3",
                    ),
                )

    def test_release_artifact_validation_rejects_missing_duplicate_and_unexpected_files(self) -> None:
        cases = ("missing-wheel", "duplicate-wheel", "unexpected-file", "metadata-mismatch")
        for case in cases:
            with self.subTest(case=case), tempfile.TemporaryDirectory() as temporary:
                directory = Path(temporary)
                wheel, _ = self.write_release_artifacts(directory)
                if case == "missing-wheel":
                    wheel.unlink()
                elif case == "duplicate-wheel":
                    duplicate = directory / "ai_engineering_guardrails-1.2.3-py2-none-any.whl"
                    duplicate.write_bytes(wheel.read_bytes())
                elif case == "unexpected-file":
                    (directory / "SHA256SUMS").write_text("not a distribution", encoding="utf-8")
                else:
                    for path in directory.iterdir():
                        path.unlink()
                    self.write_release_artifacts(directory, wheel_version="1.2.4")

                with self.assertRaises(ValueError):
                    CI_MODULE.validate_release_artifacts(
                        directory,
                        project_name="ai-engineering-guardrails",
                        package_version="1.2.3",
                    )


if __name__ == "__main__":
    unittest.main()
