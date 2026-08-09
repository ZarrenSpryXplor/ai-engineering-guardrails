from __future__ import annotations

import datetime as dt
import io
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from ai_engineering_guardrails import assurance, state
from ai_engineering_guardrails.util import GuardrailsError, file_hash


class TTYBuffer(io.StringIO):
    def isatty(self) -> bool:
        return True


class AssuranceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.repo = Path(self.temporary.name) / "repo"
        self.home = Path(self.temporary.name) / "home"
        self.home.mkdir()
        self.repo.mkdir()
        self.git("init")
        self.git("config", "user.email", "tests@example.invalid")
        self.git("config", "user.name", "Tests")
        (self.repo / "app.py").write_text("print('base')\n", encoding="utf-8")
        self.git("add", "app.py")
        self.git("commit", "-m", "base")

    def git(self, *arguments: str) -> None:
        subprocess.run(["git", "-C", str(self.repo), *arguments], check=True, capture_output=True)

    def write_json(self, relative: str, value: object) -> Path:
        path = self.repo / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(value), encoding="utf-8")
        return path

    def write_contract(self, *, establish: bool = True, **overrides: object) -> Path:
        value: dict[str, object] = {
            "schema_version": 1,
            "objective": "Preserve the documented synthetic behaviour.",
            "observable_outcomes": [{"id": "tests-pass", "description": "The supplied JUnit report has no failures."}],
            "non_goals": [],
            "risk_class": "normal",
            "status": "completed",
            "required_evidence": [{"id": "unit-tests", "type": "junit", "maximum_age_hours": 24}],
        }
        value.update(overrides)
        path = self.write_json(assurance.TASK_CONTRACT_NAME, value)
        if establish:
            confirmation = f"ESTABLISH TASK CONTRACT {file_hash(path)}\n"
            assurance.establish_contract(
                self.repo,
                self.home,
                input_stream=TTYBuffer(confirmation),
                prompt_stream=TTYBuffer(),
            )
        return path

    def test_task_init_validate_and_safe_path_rules(self) -> None:
        preview = assurance.initialise_task(self.repo, force=False, dry_run=True)
        self.assertFalse(preview["contract"].exists())
        assurance.initialise_task(self.repo, force=False, dry_run=False)
        _, contract = assurance.load_contract(self.repo)
        self.assertEqual("planned", contract["status"])
        with self.assertRaises(GuardrailsError):
            assurance.validate_contract({
                "schema_version": 1,
                "objective": "x",
                "observable_outcomes": ["x"],
                "non_goals": [],
                "risk_class": "normal",
                "status": "planned",
                "allowed_paths": ["../outside"],
            })

    def test_task_paths_reject_absolute_windows_and_unc_syntax_on_every_host(self) -> None:
        unsafe = (
            "/var/tmp/**",
            r"C:\Users\review\**",
            "C:/Users/review/**",
            r"\\server\share\**",
            "//server/share/**",
            r"\Windows\System32\**",
            "C:relative-looking/**",
        )
        base = {
            "schema_version": 1,
            "objective": "Validate portable path patterns.",
            "observable_outcomes": ["Paths remain repository relative."],
            "non_goals": [],
            "risk_class": "normal",
            "status": "planned",
        }
        for pattern in unsafe:
            with self.subTest(pattern=pattern), self.assertRaises(GuardrailsError):
                assurance.validate_contract({**base, "allowed_paths": [pattern]})

        result = assurance.validate_contract(
            {**base, "allowed_paths": ["src/**", "schemas:api/**"]}
        )
        self.assertEqual(["src/**", "schemas:api/**"], result["allowed_paths"])

    def test_report_parsers_compare_without_leaking_messages_or_absolute_paths(self) -> None:
        before = {
            "version": "2.1.0",
            "runs": [
                {
                    "tool": {"driver": {"name": "synthetic"}},
                    "results": [
                        {
                            "ruleId": "old",
                            "level": "warning",
                            "message": {"text": "secret value"},
                            "locations": [{"physicalLocation": {"artifactLocation": {"uri": "app.py"}, "region": {"startLine": 1}}}],
                        }
                    ],
                }
            ],
        }
        after = {
            "version": "2.1.0",
            "runs": [
                {
                    "tool": {"driver": {"name": "synthetic"}},
                    "results": [
                        {"ruleId": "old", "level": "warning", "locations": [{"physicalLocation": {"artifactLocation": {"uri": "app.py"}, "region": {"startLine": 1}}}]},
                        {"ruleId": "new", "level": "error", "message": {"text": "do not print me"}, "locations": [{"physicalLocation": {"artifactLocation": {"uri": "/Users/synthetic/private.py"}, "region": {"startLine": 2}}}]},
                    ],
                }
            ],
        }
        self.write_json("reports/before.sarif", before)
        self.write_json("reports/after.sarif", after)
        (self.repo / "reports/before.xml").write_text('<coverage line-rate="0.9" branch-rate="0.8"/>', encoding="utf-8")
        (self.repo / "reports/after.xml").write_text('<coverage line-rate="0.8" branch-rate="0.8"/>', encoding="utf-8")
        (self.repo / "reports/tests.xml").write_text('<testsuites><testsuite><testcase name="ok" time="0.1"/><testcase name="skip"><skipped/></testcase></testsuite></testsuites>', encoding="utf-8")
        result = assurance.compare_reports(
            self.repo,
            baseline_sarif=Path("reports/before.sarif"),
            current_sarif=Path("reports/after.sarif"),
            baseline_coverage=Path("reports/before.xml"),
            current_coverage=Path("reports/after.xml"),
            junit=Path("reports/tests.xml"),
        )
        self.assertEqual(1, result["reports"]["sarif"]["new_findings"])
        self.assertEqual(1, result["reports"]["sarif"]["new_error_or_high_severity_findings"])
        self.assertEqual(-0.1, result["reports"]["cobertura"]["line_rate_delta"])
        self.assertEqual(2, result["reports"]["junit"]["tests"])
        rendered = json.dumps(result)
        self.assertNotIn("secret value", rendered)
        self.assertNotIn("do not print me", rendered)
        self.assertNotIn("/Users/synthetic", rendered)

    def test_report_parsers_reject_unsafe_xml_and_outside_reports(self) -> None:
        (self.repo / "reports.xml").write_text('<!DOCTYPE value [<!ENTITY xxe SYSTEM "file:///etc/passwd">]><coverage line-rate="1"/>', encoding="utf-8")
        with self.assertRaises(GuardrailsError):
            assurance.parse_cobertura(Path("reports.xml"), self.repo)
        outside = Path(self.temporary.name) / "outside.xml"
        outside.write_text('<coverage line-rate="1"/>', encoding="utf-8")
        with self.assertRaises(GuardrailsError):
            assurance.parse_cobertura(outside, self.repo)

    def test_sarif_control_character_paths_are_not_rendered(self) -> None:
        self.write_json(
            "reports/control.sarif",
            {
                "version": "2.1.0",
                "runs": [{
                    "tool": {"driver": {"name": "synthetic"}},
                    "results": [{
                        "ruleId": "unsafe-path",
                        "locations": [{"physicalLocation": {"artifactLocation": {"uri": "src/line\nbreak.py"}}}],
                    }],
                }],
            },
        )

        result = assurance.parse_sarif(Path("reports/control.sarif"), self.repo)

        self.assertNotIn("line\nbreak", json.dumps(result))
        self.assertIn("<external>", result["_findings"][0]["path"])

    def test_sarif_partial_fingerprints_precede_location_identity(self) -> None:
        def report(tool: str, fingerprint: str, path: str, line: int) -> dict[str, object]:
            return {
                "version": "2.1.0",
                "runs": [{
                    "tool": {"driver": {"name": tool}},
                    "results": [{
                        "ruleId": "rule-one",
                        "partialFingerprints": {"primaryLocationLineHash": fingerprint},
                        "locations": [{"physicalLocation": {"artifactLocation": {"uri": path}, "region": {"startLine": line}}}],
                    }],
                }],
            }

        fixtures = (
            ("moved-location", report("tool-a", "stable", "a.py", 1), report("tool-a", "stable", "b.py", 20), (0, 0, 1)),
            ("changed-fingerprint", report("tool-a", "before", "a.py", 1), report("tool-a", "after", "a.py", 1), (1, 1, 0)),
            ("different-tools", report("tool-a", "stable", "a.py", 1), report("tool-b", "stable", "a.py", 1), (1, 1, 0)),
        )
        for name, before, after, expected in fixtures:
            with self.subTest(name=name):
                self.write_json("reports/before.sarif", before)
                self.write_json("reports/after.sarif", after)
                comparison = assurance.compare_reports(
                    self.repo,
                    baseline_sarif=Path("reports/before.sarif"),
                    current_sarif=Path("reports/after.sarif"),
                )["reports"]["sarif"]
                self.assertEqual(expected, (comparison["new_findings"], comparison["resolved_findings"], comparison["unchanged_findings"]))

    def test_sarif_location_fallback_normalises_portable_uri_paths(self) -> None:
        def report(uri: str) -> dict[str, object]:
            return {
                "version": "2.1.0",
                "runs": [{
                    "tool": {"driver": {"name": "tool-a"}},
                    "results": [{
                        "ruleId": "rule-one",
                        "locations": [{"physicalLocation": {"artifactLocation": {"uri": uri}, "region": {"startLine": 3}}}],
                    }],
                }],
            }

        variants = ("src\\helper.py", "src%2Fhelper.py", "./src/helper.py")
        self.write_json("reports/before.sarif", report(variants[0]))
        for index, uri in enumerate(variants[1:], start=1):
            with self.subTest(uri=uri):
                self.write_json(f"reports/after-{index}.sarif", report(uri))
                comparison = assurance.compare_reports(
                    self.repo,
                    baseline_sarif=Path("reports/before.sarif"),
                    current_sarif=Path(f"reports/after-{index}.sarif"),
                )["reports"]["sarif"]
                self.assertEqual((0, 0, 1), (comparison["new_findings"], comparison["resolved_findings"], comparison["unchanged_findings"]))

    def test_sarif_identity_deficient_results_never_collapse(self) -> None:
        report = {
            "version": "2.1.0",
            "runs": [{"tool": {"driver": {"name": "tool-a"}}, "results": [{}, {}]}],
        }
        self.write_json("reports/before.sarif", report)
        self.write_json("reports/after.sarif", report)

        parsed = assurance.parse_sarif(Path("reports/before.sarif"), self.repo)
        comparison = assurance.compare_reports(
            self.repo,
            baseline_sarif=Path("reports/before.sarif"),
            current_sarif=Path("reports/after.sarif"),
        )["reports"]["sarif"]

        self.assertEqual(2, parsed["identity_deficient_findings"])
        self.assertEqual(2, len({item["identity"] for item in parsed["_findings"]}))
        self.assertTrue(all(not item["identity_reliable"] for item in parsed["_findings"]))
        self.assertEqual((2, 2, 0), (comparison["new_findings"], comparison["resolved_findings"], comparison["unchanged_findings"]))

    def test_malformed_deep_and_oversized_sarif_fail_through_controlled_errors(self) -> None:
        reports = self.repo / "reports"
        reports.mkdir(exist_ok=True)
        malformed = reports / "malformed.sarif"
        malformed.write_text("{not-json", encoding="utf-8")
        deep = reports / "deep.sarif"
        deep.write_text("[" * 2000 + "0" + "]" * 2000, encoding="utf-8")
        oversized = reports / "oversized.sarif"
        oversized.write_text("x" * (assurance.MAX_REPORT_BYTES + 1), encoding="utf-8")
        for relative in (Path("reports/malformed.sarif"), Path("reports/deep.sarif")):
            with self.subTest(relative=relative), self.assertRaises(assurance.EvidenceParseError):
                assurance.parse_sarif(relative, self.repo)
        with self.assertRaisesRegex(GuardrailsError, "exceeds"):
            assurance.parse_sarif(Path("reports/oversized.sarif"), self.repo)

        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "ai_engineering_guardrails",
                "complexity",
                "compare",
                "--repo",
                str(self.repo),
                "--baseline-sarif",
                "reports/malformed.sarif",
                "--current-sarif",
                "reports/deep.sarif",
                "--format",
                "json",
            ],
            cwd=Path(__file__).resolve().parents[1],
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(1, result.returncode)
        self.assertIn("error:", result.stderr)
        self.assertNotIn("Traceback", result.stderr)

    def test_cobertura_present_numeric_rates_are_strict(self) -> None:
        malformed = (
            '<coverage line-rate="not-a-number"/>',
            '<coverage line-rate="1" branch-rate="not-a-number"/>',
            '<coverage line-rate="NaN" branch-rate="1"/>',
            '<coverage line-rate="1" branch-rate="Infinity"/>',
            '<coverage line-rate="-0.1" branch-rate="1"/>',
            '<coverage line-rate="1" lines-covered="not-a-number"/>',
            '<coverage line-rate="1" lines-valid="-1"/>',
            '<coverage line-rate="1" lines-covered="2" lines-valid="1"/>',
            '<coverage line-rate="1" complexity="NaN"/>',
            '<coverage line-rate="1" timestamp="Infinity"/>',
        )
        for xml in malformed:
            with self.subTest(xml=xml):
                (self.repo / "coverage.xml").write_text(xml, encoding="utf-8")
                with self.assertRaises(assurance.EvidenceParseError):
                    assurance.parse_cobertura(Path("coverage.xml"), self.repo)

    def test_cobertura_present_rates_are_coherent_with_counts(self) -> None:
        contradictory = (
            '<coverage line-rate="1" lines-covered="0" lines-valid="1"/>',
            '<coverage line-rate="0.5" branch-rate="1" branches-covered="0" branches-valid="1"/>',
            '<coverage line-rate="0.25" lines-covered="3" lines-valid="4"/>',
        )
        for xml in contradictory:
            with self.subTest(xml=xml):
                (self.repo / "coverage.xml").write_text(xml, encoding="utf-8")
                with self.assertRaises(assurance.EvidenceParseError):
                    assurance.parse_cobertura(Path("coverage.xml"), self.repo)

        (self.repo / "coverage.xml").write_text(
            '<coverage line-rate="0.67" branch-rate="0.3333" '
            'lines-covered="2" lines-valid="3" branches-covered="1" branches-valid="3"/>',
            encoding="utf-8",
        )
        parsed = assurance.parse_cobertura(Path("coverage.xml"), self.repo)
        self.assertEqual(0.67, parsed["line_rate"])
        self.assertEqual(0.3333, parsed["branch_rate"])

    def test_junit_aggregate_suite_attributes_are_counted_without_failure_bodies(self) -> None:
        (self.repo / "reports.xml").write_text(
            '<testsuites><testsuite tests="3" failures="1" errors="1" skipped="1" time="2.5">'
            '<system-out>do not retain</system-out><failure>do not retain</failure></testsuite></testsuites>',
            encoding="utf-8",
        )

        result = assurance.parse_junit(Path("reports.xml"), self.repo)

        self.assertEqual(3, result["tests"])
        self.assertEqual(1, result["failures"])
        self.assertEqual(1, result["errors"])
        self.assertEqual(1, result["skipped"])
        self.assertEqual(2.5, result["duration_seconds"])
        self.assertNotIn("do not retain", json.dumps(result))

    def test_junit_present_counts_are_strict_and_coherent(self) -> None:
        malformed = {
            "invalid-tests": '<testsuite tests="not-a-number" failures="0" errors="0"/>',
            "invalid-failures": '<testsuite tests="1" failures="NaN" errors="0"/>',
            "invalid-errors": '<testsuite tests="1" failures="0" errors="Infinity"/>',
            "negative": '<testsuite tests="-1" failures="0" errors="0"/>',
            "too-large": '<testsuite tests="2147483648" failures="0" errors="0"/>',
            "failures-exceed-tests": '<testsuite tests="1" failures="2" errors="0"/>',
            "outcomes-exceed-tests": '<testsuite tests="2" failures="1" errors="1" skipped="1"/>',
            "partial-aggregate": '<testsuite tests="2"/>',
            "child-mismatch": '<testsuite tests="2" failures="0" errors="0"><testcase name="one"/></testsuite>',
        }
        for name, xml in malformed.items():
            with self.subTest(name=name):
                (self.repo / "reports.xml").write_text(xml, encoding="utf-8")
                with self.assertRaises(assurance.EvidenceParseError):
                    assurance.parse_junit(Path("reports.xml"), self.repo)

    def test_junit_derives_children_and_distinguishes_empty_from_passing(self) -> None:
        fixtures = {
            "children": (
                '<testsuite><testcase name="ok"/><testcase name="failed"><failure/></testcase></testsuite>',
                (2, 1, 0, True),
            ),
            "nested": (
                '<testsuites tests="2" failures="0" errors="0"><testsuite tests="1" failures="0" errors="0">'
                '<testcase name="one"/></testsuite><testsuite><testcase name="two"/></testsuite></testsuites>',
                (2, 0, 0, True),
            ),
            "aggregate-passing": ('<testsuite tests="1" failures="0" errors="0"/>', (1, 0, 0, True)),
            "aggregate-failing": ('<testsuite tests="1" failures="1" errors="0"/>', (1, 1, 0, True)),
            "zero-tests": ('<testsuite tests="0" failures="0" errors="0"/>', (0, 0, 0, False)),
            "empty-suite": ("<testsuite/>", (0, 0, 0, False)),
            "empty-root": ("<testsuites/>", (0, 0, 0, False)),
        }
        for name, (xml, expected) in fixtures.items():
            with self.subTest(name=name):
                (self.repo / "reports.xml").write_text(xml, encoding="utf-8")
                result = assurance.parse_junit(Path("reports.xml"), self.repo)
                self.assertTrue(result["parsed"])
                self.assertTrue(result["valid"])
                self.assertEqual(expected, (result["tests"], result["failures"], result["errors"], result["sufficient_for_completion"]))

    def test_malformed_junit_with_current_digests_cannot_complete(self) -> None:
        contract_path = self.write_contract()
        report = self.repo / "reports.xml"
        report.write_text(
            '<testsuite tests="not-a-number" failures="not-a-number" errors="not-a-number"/>',
            encoding="utf-8",
        )
        current = assurance.repository_state_digest(self.repo)
        self.assertIsNotNone(current)
        self.write_json(
            assurance.TASK_EVIDENCE_NAME,
            {
                "schema_version": 1,
                "evidence": [{
                    "id": "unit-tests",
                    "type": "junit",
                    "path": "reports.xml",
                    "captured_at": "2026-08-09T11:00:00Z",
                    "repository_state_digest": current,
                    "contract_digest": file_hash(contract_path),
                    "report_digest": file_hash(report),
                    "parser_version": 1,
                    "result": "passed",
                }],
            },
        )

        result = assurance.task_status(self.repo, home=self.home, now=dt.datetime(2026, 8, 9, 12, tzinfo=dt.timezone.utc))

        self.assertFalse(result["completed"])
        self.assertEqual("malformed", result["evidence"][0]["state"])
        self.assertIn("evidence-malformed", {item["id"] for item in result["evidence_gaps"]})

    def test_zero_test_junit_is_insufficient_completion_evidence(self) -> None:
        contract_path = self.write_contract()
        report = self.repo / "reports.xml"
        report.write_text('<testsuite tests="0" failures="0" errors="0"/>', encoding="utf-8")
        current = assurance.repository_state_digest(self.repo)
        self.assertIsNotNone(current)
        self.write_json(
            assurance.TASK_EVIDENCE_NAME,
            {
                "schema_version": 1,
                "evidence": [{
                    "id": "unit-tests",
                    "type": "junit",
                    "path": "reports.xml",
                    "captured_at": "2026-08-09T11:00:00Z",
                    "repository_state_digest": current,
                    "contract_digest": file_hash(contract_path),
                    "report_digest": file_hash(report),
                    "parser_version": 1,
                    "result": "passed",
                }],
            },
        )

        result = assurance.task_status(self.repo, home=self.home, now=dt.datetime(2026, 8, 9, 12, tzinfo=dt.timezone.utc))

        self.assertFalse(result["completed"])
        self.assertEqual("insufficient", result["evidence"][0]["state"])
        self.assertIn("evidence-insufficient", {item["id"] for item in result["evidence_gaps"]})

    def test_completed_task_requires_fresh_state_bound_passing_evidence(self) -> None:
        contract_path = self.write_contract()
        report = self.repo / "reports/tests.xml"
        report.parent.mkdir(parents=True, exist_ok=True)
        report.write_text('<testsuite><testcase name="ok"/></testsuite>', encoding="utf-8")
        now = dt.datetime(2026, 8, 9, 12, tzinfo=dt.timezone.utc)
        current = assurance.repository_state_digest(self.repo)
        self.assertIsNotNone(current)
        self.write_json(
            assurance.TASK_EVIDENCE_NAME,
            {
                "schema_version": 1,
                "evidence": [{
                    "id": "unit-tests",
                    "type": "junit",
                    "path": "reports/tests.xml",
                    "captured_at": "2026-08-09T11:00:00Z",
                    "repository_state_digest": current,
                    "contract_digest": file_hash(contract_path),
                    "report_digest": file_hash(report),
                    "parser_version": 1,
                    "result": "passed",
                }],
            },
        )
        fresh = assurance.task_receipt(self.repo, home=self.home, now=now)
        task_assurance = fresh["task_assurance"]
        self.assertEqual(2, fresh["schema_version"])
        self.assertIn("policy_digest", fresh)
        self.assertTrue(task_assurance["completed"], fresh)
        self.assertEqual("fresh", task_assurance["evidence"][0]["state"])
        self.assertEqual(current, task_assurance["repository_state_digest"])
        self.assertEqual(file_hash(contract_path), task_assurance["contract_digest"])
        self.assertEqual({"id", "type", "state"}, set(task_assurance["evidence"][0]))
        self.assertNotIn("reports/tests.xml", json.dumps(fresh))
        (self.repo / "app.py").write_text("print('changed')\n", encoding="utf-8")
        stale = assurance.task_status(self.repo, home=self.home, now=now)
        self.assertFalse(stale["completed"])
        self.assertEqual("halted", stale["effective_status"])
        self.assertIn("evidence-state-mismatch", {item["id"] for item in stale["evidence_gaps"]})

    def test_task_receipt_preserves_existing_envelope_for_noncompleted_lifecycle_states(self) -> None:
        for lifecycle in ("partial", "blocked", "halted"):
            with self.subTest(lifecycle=lifecycle):
                self.write_contract(status=lifecycle, required_evidence=[])
                receipt = assurance.task_receipt(
                    self.repo,
                    home=self.home,
                    now=dt.datetime(2026, 8, 9, tzinfo=dt.timezone.utc),
                )
                reparsed = json.loads(json.dumps(receipt))
                task_assurance = reparsed["task_assurance"]
                self.assertEqual(2, reparsed["schema_version"])
                self.assertIn("verification_outcomes", reparsed)
                self.assertEqual(lifecycle, task_assurance["effective_status"])
                self.assertFalse(task_assurance["completed"])
                self.assertEqual(file_hash(self.repo / assurance.TASK_CONTRACT_NAME), task_assurance["contract_digest"])

    def test_missing_evidence_and_scope_limit_halt_completed_task(self) -> None:
        self.write_contract(maximum_files_changed=0)
        (self.repo / "app.py").write_text("print('changed')\n", encoding="utf-8")
        result = assurance.task_status(self.repo, home=self.home, now=dt.datetime(2026, 8, 9, tzinfo=dt.timezone.utc))
        self.assertTrue(result["safe_halt"]["required"])
        self.assertIn("files-changed-limit", {item["id"] for item in result["contract_violations"]})
        self.assertIn("required-evidence-missing", {item["id"] for item in result["evidence_gaps"]})

    def test_completed_task_requires_available_git_scope_even_without_evidence(self) -> None:
        for name, initialise_git in (("plain", False), ("unborn", True)):
            with self.subTest(name=name):
                root = Path(self.temporary.name) / name
                root.mkdir()
                if initialise_git:
                    subprocess.run(["git", "-C", str(root), "init"], check=True, capture_output=True)
                (root / "app.py").write_text("print('draft')\n", encoding="utf-8")
                (root / assurance.TASK_CONTRACT_NAME).write_text(
                    json.dumps(
                        {
                            "schema_version": 1,
                            "objective": "Inspect a bounded task.",
                            "observable_outcomes": ["The task is inspected."],
                            "non_goals": [],
                            "risk_class": "normal",
                            "status": "completed",
                            "required_evidence": [],
                            "maximum_files_changed": 0,
                            "allowed_paths": ["app.py"],
                            "forbidden_paths": ["secrets/**"],
                        }
                    ),
                    encoding="utf-8",
                )

                result = assurance.task_status(root, home=self.home)

                self.assertFalse(result["completed"])
                self.assertTrue(result["safe_halt"]["required"])
                self.assertIn("repository-state-unavailable", {item["id"] for item in result["safe_halt"]["reasons"]})
                self.assertFalse(result["scope"]["available"])
                self.assertIsNone(result["scope"]["files_changed"])
                self.assertIsNone(result["repository_state_digest"])

    def test_completed_non_git_task_with_declared_evidence_still_halts(self) -> None:
        root = Path(self.temporary.name) / "plain-with-evidence"
        root.mkdir()
        contract = {
            "schema_version": 1,
            "objective": "Inspect a bounded task.",
            "observable_outcomes": ["Tests pass."],
            "non_goals": [],
            "risk_class": "normal",
            "status": "completed",
            "required_evidence": [{"id": "unit-tests", "type": "junit"}],
        }
        contract_path = root / assurance.TASK_CONTRACT_NAME
        contract_path.write_text(json.dumps(contract), encoding="utf-8")
        report = root / "tests.xml"
        report.write_text('<testsuite><testcase name="ok"/></testsuite>', encoding="utf-8")
        (root / assurance.TASK_EVIDENCE_NAME).write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "evidence": [{
                        "id": "unit-tests",
                        "type": "junit",
                        "path": "tests.xml",
                        "captured_at": "2026-08-09T11:00:00Z",
                        "repository_state_digest": "0" * 64,
                        "contract_digest": file_hash(contract_path),
                        "report_digest": file_hash(report),
                        "parser_version": 1,
                        "result": "passed",
                    }],
                }
            ),
            encoding="utf-8",
        )

        result = assurance.task_status(root, home=self.home, now=dt.datetime(2026, 8, 9, 12, tzinfo=dt.timezone.utc))

        self.assertFalse(result["completed"])
        self.assertEqual("unavailable", result["evidence"][0]["state"])
        self.assertIn("repository-state-unavailable", {item["id"] for item in result["safe_halt"]["reasons"]})

    def test_generated_changes_count_toward_all_task_scope_limits(self) -> None:
        (self.repo / "dist").mkdir()
        (self.repo / "dist/tracked.txt").write_text("base\n", encoding="utf-8")
        self.git("add", "dist/tracked.txt")
        self.git("commit", "-m", "tracked generated fixture")
        (self.repo / "dist/tracked.txt").write_text("base\nchanged\n", encoding="utf-8")
        (self.repo / "dist/untracked.txt").write_text("one\ntwo\n", encoding="utf-8")
        self.write_contract(
            required_evidence=[],
            allowed_paths=["dist/**"],
            maximum_files_changed=1,
            maximum_lines_changed=2,
            maximum_directories_changed=0,
        )

        result = assurance.task_status(self.repo, home=self.home)

        self.assertEqual(2, result["scope"]["files_changed"])
        self.assertEqual(3, result["scope"]["lines_added"])
        self.assertEqual(1, result["scope"]["directories_changed"])
        self.assertEqual(100, result["scope"]["generated_output_share_percent"])
        self.assertTrue(result["scope"]["generated_output_dominance"])
        identifiers = {item["id"] for item in result["contract_violations"]}
        self.assertTrue({"files-changed-limit", "lines-changed-limit", "directories-changed-limit"}.issubset(identifiers))
        self.assertNotIn("paths-outside-allowed-set", identifiers)

    def test_source_and_generated_changes_share_one_task_scope(self) -> None:
        (self.repo / "dist").mkdir()
        (self.repo / "dist/output.js").write_text("generated\n", encoding="utf-8")
        (self.repo / "app.py").write_text("print('changed')\n", encoding="utf-8")
        self.write_contract(
            required_evidence=[],
            allowed_paths=["dist/**"],
            forbidden_paths=["app.py"],
            maximum_files_changed=1,
        )

        result = assurance.task_status(self.repo, home=self.home)

        self.assertEqual(2, result["scope"]["files_changed"])
        self.assertEqual(50, result["scope"]["generated_output_share_percent"])
        identifiers = {item["id"] for item in result["contract_violations"]}
        self.assertTrue({"files-changed-limit", "paths-outside-allowed-set", "forbidden-path-changed"}.issubset(identifiers))
        self.assertNotIn(assurance.TASK_CONTRACT_NAME, assurance._changed_paths(self.repo))

    def test_dependency_policy_halts_on_recognised_unsupported_manifest_or_lock(self) -> None:
        fixtures = (
            ("requirements.txt", "example==1\n"),
            ("package-lock.json", '{"lockfileVersion": 3, "packages": {}}\n'),
            ("pom.xml", "<project/>\n"),
        )
        for relative, content in fixtures:
            with self.subTest(relative=relative):
                path = self.repo / relative
                path.write_text(content, encoding="utf-8")
                self.write_contract(required_evidence=[], dependency_policy="forbid-new-runtime-dependencies")

                result = assurance.task_status(self.repo, home=self.home)

                self.assertFalse(result["completed"])
                self.assertEqual("unavailable", result["scope"]["dependency_assurance"])
                self.assertIn(relative, result["scope"]["dependency_files_changed"])
                self.assertIn("dependency-assurance-unavailable", {item["id"] for item in result["safe_halt"]["reasons"]})
                path.unlink()

    def test_dependency_policy_distinguishes_verified_unchanged_and_violation(self) -> None:
        self.write_contract(required_evidence=[], dependency_policy="forbid-new-runtime-dependencies")
        unchanged = assurance.task_status(self.repo, home=self.home)
        self.assertEqual("verified", unchanged["scope"]["dependency_assurance"])

        manifest = self.repo / "package.json"
        manifest.write_text(json.dumps({"dependencies": {"new-runtime": "1"}}), encoding="utf-8")
        changed = assurance.task_status(self.repo, home=self.home)

        self.assertEqual("violation", changed["scope"]["dependency_assurance"])
        self.assertIn("package.json:new-runtime", changed["scope"]["dependency_changes"])
        self.assertIn("new-dependency-violates-policy", {item["id"] for item in changed["contract_violations"]})

    def test_nested_repository_state_prevents_completed_task_assurance(self) -> None:
        self.write_contract(required_evidence=[])
        nested = self.repo / "nested"
        nested.mkdir()
        subprocess.run(["git", "-C", str(nested), "init"], check=True, capture_output=True)
        (nested / "app.py").write_text("value = 1\n", encoding="utf-8")

        result = assurance.task_status(self.repo, home=self.home)

        self.assertFalse(result["completed"])
        self.assertEqual("unsupported", result["nested_repository_state"])
        self.assertFalse(result["scope"]["available"])
        self.assertIn("repository-state-unavailable", {item["id"] for item in result["safe_halt"]["reasons"]})

    def test_contract_without_provenance_cannot_claim_continuous_completion(self) -> None:
        contract_path = self.write_contract(establish=False, required_evidence=[])

        unavailable = assurance.task_status(self.repo, home=self.home)
        preview = assurance.establish_contract(self.repo, self.home, dry_run=True)
        still_unavailable = assurance.task_status(self.repo, home=self.home)

        self.assertFalse(unavailable["completed"])
        self.assertEqual("unavailable", unavailable["contract_continuity"])
        self.assertIn("contract-continuity-unavailable", {item["id"] for item in unavailable["safe_halt"]["reasons"]})
        self.assertFalse(preview["established"])
        self.assertEqual(file_hash(contract_path), preview["contract_digest"])
        self.assertEqual("unavailable", still_unavailable["contract_continuity"])

    def test_assurance_critical_contract_changes_break_continuity(self) -> None:
        fixtures = (
            (
                "required-evidence-removed",
                {"required_evidence": [{"id": "unit-tests", "type": "junit"}]},
                {"required_evidence": []},
            ),
            ("allowed-scope-expanded", {"allowed_paths": ["src/**"]}, {"allowed_paths": ["src/**", "tests/**"]}),
            ("forbidden-path-removed", {"forbidden_paths": ["secrets/**"]}, {}),
            ("file-limit-increased", {"maximum_files_changed": 1}, {"maximum_files_changed": 2}),
            (
                "dependency-policy-weakened",
                {"dependency_policy": "forbid-new-runtime-dependencies"},
                {"dependency_policy": "allow"},
            ),
            ("notes-change-is-strict", {"notes": "First reviewed note."}, {"notes": "Revised reviewed note."}),
        )
        for name, before, after in fixtures:
            with self.subTest(name=name):
                base: dict[str, object] = {
                    "schema_version": 1,
                    "objective": "Preserve the documented synthetic behaviour.",
                    "observable_outcomes": [{"id": "tests-pass", "description": "The declared outcome holds."}],
                    "non_goals": [],
                    "risk_class": "normal",
                    "status": "completed",
                    "required_evidence": [],
                }
                base.update(before)
                path = self.write_json(assurance.TASK_CONTRACT_NAME, base)
                confirmation = f"ESTABLISH TASK CONTRACT {file_hash(path)}\n"

                assurance.establish_contract(
                    self.repo,
                    self.home,
                    input_stream=TTYBuffer(confirmation),
                    prompt_stream=TTYBuffer(),
                )
                revised = dict(base)
                for removed in set(before) - set(after):
                    revised.pop(removed, None)
                revised.update(after)
                self.write_json(assurance.TASK_CONTRACT_NAME, revised)

                result = assurance.task_status(self.repo, home=self.home)

                self.assertEqual("changed", result["contract_continuity"])
                self.assertFalse(result["completed"])
                self.assertIn("contract-continuity-changed", {item["id"] for item in result["safe_halt"]["reasons"]})

    def test_explicit_rebaseline_restores_current_continuity(self) -> None:
        path = self.write_contract(required_evidence=[], notes="Initial reviewed note.")
        initial = assurance.task_status(self.repo, home=self.home)
        self.assertEqual("current", initial["contract_continuity"])
        self.assertTrue(initial["completed"])
        path = self.write_contract(establish=False, required_evidence=[], notes="Deliberately revised note.")
        changed = assurance.task_status(self.repo, home=self.home)
        self.assertEqual("changed", changed["contract_continuity"])
        self.assertFalse(changed["completed"])

        prompt = TTYBuffer()
        established = assurance.establish_contract(
            self.repo,
            self.home,
            now=dt.datetime(2026, 8, 9, 12, tzinfo=dt.timezone.utc),
            input_stream=TTYBuffer(f"ESTABLISH TASK CONTRACT {file_hash(path)}\n"),
            prompt_stream=prompt,
        )
        current = assurance.task_status(self.repo, home=self.home)

        self.assertTrue(established["established"])
        self.assertIn("does not prove human identity", prompt.getvalue())
        self.assertEqual("current", current["contract_continuity"])
        self.assertTrue(current["completed"])
        self.assertEqual(file_hash(path), current["contract_digest"])
        persisted = (self.home / ".ai-guardrails/state.json").read_text(encoding="utf-8")
        self.assertNotIn("Preserve the documented synthetic behaviour", persisted)
        self.assertIn("assurance_summary", persisted)

    def test_state_version_six_migrates_with_no_synthetic_contract_history(self) -> None:
        value = state.empty_state()
        value["format_version"] = 6
        value.pop("task_contracts")
        path = self.home / ".ai-guardrails/state.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(value), encoding="utf-8")

        migrated = state.load_state(self.home)

        self.assertEqual([], migrated["task_contracts"])
        self.assertEqual(6, migrated[state.LEGACY_FORMAT_KEY])

    def test_manual_review_is_explicitly_labelled_and_renames_remain_in_scope(self) -> None:
        contract_path = self.write_contract(
            required_evidence=[{"id": "review", "type": "manual-review", "maximum_age_hours": 24}],
            allowed_paths=["app.py"],
        )
        self.git("mv", "app.py", "restricted.py")
        paths = assurance._changed_paths(self.repo)
        self.assertIn("app.py", paths)
        self.assertIn("restricted.py", paths)
        current = assurance.repository_state_digest(self.repo)
        self.assertIsNotNone(current)
        self.write_json(
            assurance.TASK_EVIDENCE_NAME,
            {
                "schema_version": 1,
                "evidence": [{
                    "id": "review",
                    "type": "manual-review",
                    "manual_review_id": "peer-review-42",
                    "captured_at": "2026-08-09T11:00:00Z",
                    "repository_state_digest": current,
                    "contract_digest": file_hash(contract_path),
                    "parser_version": 1,
                    "result": "passed",
                }],
            },
        )
        result = assurance.task_status(self.repo, home=self.home, now=dt.datetime(2026, 8, 9, 12, tzinfo=dt.timezone.utc))
        self.assertTrue(result["evidence"][0]["manual"])
        self.assertIn("paths-outside-allowed-set", {item["id"] for item in result["contract_violations"]})

    def test_coverage_policy_and_invariant_evidence_are_reported_without_running_checks(self) -> None:
        contract_path = self.write_contract(
            invariants=[
                {
                    "id": "unit-tests-remain-passing",
                    "description": "The declared unit-test evidence remains fresh and passing.",
                    "evidence_id": "unit-tests",
                }
            ],
            coverage_policy={
                "baseline_path": "reports/before.xml",
                "current_path": "reports/after.xml",
                "maximum_line_rate_regression": 0,
            },
        )
        reports = self.repo / "reports"
        reports.mkdir()
        (reports / "before.xml").write_text('<coverage line-rate="0.9" branch-rate="0.8"/>', encoding="utf-8")
        (reports / "after.xml").write_text('<coverage line-rate="0.8" branch-rate="0.8"/>', encoding="utf-8")
        (reports / "tests.xml").write_text('<testsuite><testcase name="ok"/></testsuite>', encoding="utf-8")
        current = assurance.repository_state_digest(self.repo)
        self.assertIsNotNone(current)
        self.write_json(
            assurance.TASK_EVIDENCE_NAME,
            {
                "schema_version": 1,
                "evidence": [
                    {
                        "id": "unit-tests",
                        "type": "junit",
                        "path": "reports/tests.xml",
                        "captured_at": "2026-08-09T11:00:00Z",
                        "repository_state_digest": current,
                        "contract_digest": file_hash(contract_path),
                        "report_digest": file_hash(reports / "tests.xml"),
                        "parser_version": 1,
                        "result": "passed",
                    }
                ],
            },
        )

        result = assurance.task_status(self.repo, home=self.home, now=dt.datetime(2026, 8, 9, 12, tzinfo=dt.timezone.utc))

        self.assertEqual(-0.1, result["coverage"]["line_rate_delta"])
        self.assertIn("coverage-regression", {item["id"] for item in result["contract_violations"]})
        self.assertEqual("declared-evidence-fresh", result["invariants"][0]["state"])
        self.assertNotIn("reports/tests.xml", json.dumps(result["evidence"][0]["parsed_summary"]))

    def test_external_ci_artifact_requires_contract_permission_and_receipt_redacts_its_path(self) -> None:
        contract_path = self.write_contract(
            required_evidence=[
                {
                    "id": "unit-tests",
                    "type": "junit",
                    "maximum_age_hours": 24,
                    "allow_external_ci_artifact": True,
                }
            ]
        )
        artifact = Path(self.temporary.name) / "ci-artifacts" / "tests.xml"
        artifact.parent.mkdir()
        artifact.write_text('<testsuite><testcase name="ok"/></testsuite>', encoding="utf-8")
        current = assurance.repository_state_digest(self.repo)
        self.assertIsNotNone(current)
        self.write_json(
            assurance.TASK_EVIDENCE_NAME,
            {
                "schema_version": 1,
                "evidence": [
                    {
                        "id": "unit-tests",
                        "type": "junit",
                        "path": str(artifact),
                        "external_ci_artifact": True,
                        "captured_at": "2026-08-09T11:00:00Z",
                        "repository_state_digest": current,
                        "contract_digest": file_hash(contract_path),
                        "report_digest": file_hash(artifact),
                        "parser_version": 1,
                        "result": "passed",
                    }
                ],
            },
        )

        result = assurance.task_status(self.repo, home=self.home, now=dt.datetime(2026, 8, 9, 12, tzinfo=dt.timezone.utc))

        self.assertTrue(result["completed"])
        self.assertEqual("<external-ci-artifact>", result["evidence"][0]["path"])
        self.assertNotIn(str(artifact), json.dumps(result))
        receipt = assurance.task_receipt(self.repo, home=self.home, now=dt.datetime(2026, 8, 9, 12, tzinfo=dt.timezone.utc))
        self.assertNotIn(str(artifact), json.dumps(receipt))
        self.assertEqual({"id", "type", "state"}, set(receipt["task_assurance"]["evidence"][0]))
        artifact.write_text('<testsuite><testcase name="changed"/></testsuite>', encoding="utf-8")
        changed = assurance.task_status(self.repo, home=self.home, now=dt.datetime(2026, 8, 9, 12, tzinfo=dt.timezone.utc))
        self.assertEqual("report-mismatch", changed["evidence"][0]["state"])
        self.assertIn("evidence-report-mismatch", {item["id"] for item in changed["evidence_gaps"]})

    def test_repository_state_digest_changes_for_untracked_content(self) -> None:
        first = assurance.repository_state_digest(self.repo)
        (self.repo / "untracked.py").write_text("value = 1\n", encoding="utf-8")
        second = assurance.repository_state_digest(self.repo)
        (self.repo / "untracked.py").write_text("value = 2\n", encoding="utf-8")
        third = assurance.repository_state_digest(self.repo)

        self.assertNotEqual(first, second)
        self.assertNotEqual(second, third)

    def test_invariant_without_fresh_evidence_is_explicitly_unverified(self) -> None:
        self.write_contract(
            invariants=[
                {
                    "id": "unit-tests-remain-passing",
                    "description": "The declared test evidence remains current.",
                    "evidence_id": "unit-tests",
                }
            ]
        )

        result = assurance.task_status(self.repo, home=self.home, now=dt.datetime(2026, 8, 9, tzinfo=dt.timezone.utc))

        self.assertEqual("unverified", result["invariants"][0]["state"])
        self.assertIn("contract-invariant-unverified", {item["id"] for item in result["evidence_gaps"]})


if __name__ == "__main__":
    unittest.main()
