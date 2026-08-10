from __future__ import annotations

import copy
import datetime as dt
import json
import tempfile
import unittest
from pathlib import Path

from ai_engineering_guardrails import build, evidence, policy
from ai_engineering_guardrails.util import GuardrailsError


class PolicyEvidenceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.registry = Path(self.temporary.name) / "registry.json"
        self.value = evidence.load_registry()

    def write(self, value: dict[str, object]) -> None:
        self.registry.write_text(json.dumps(value), encoding="utf-8")

    def test_canonical_registry_is_structurally_valid_and_traceable(self) -> None:
        result = evidence.audit_registry(policy.load_manifest(), today=dt.date(2026, 8, 10))
        self.assertTrue(result["valid"])
        self.assertEqual([], result["errors"])
        self.assertEqual(10, result["policy_records"])

    def test_asd_ste100_official_source_records_issue_and_review_lifecycle(self) -> None:
        source = next(item for item in self.value["sources"] if item["id"] == "asd-ste100-issue-9")
        reporting = next(item for item in self.value["policies"] if item["id"] == "reporting")

        self.assertEqual("official-standard-source", source["evidence_type"])
        self.assertEqual("2025-01-15", source["publication_date"])
        self.assertEqual("2026-08-10", source["last_reviewed"])
        self.assertGreater(source["review_after"], source["last_reviewed"])
        self.assertEqual("https://www.asd-ste100.org/", source["url"])
        self.assertIn(source["id"], reporting["evidence_source_ids"])
        self.assertIn("not redistributed", source["limitations"])

    def test_structural_errors_and_overdue_reviews_are_distinct(self) -> None:
        value = copy.deepcopy(self.value)
        value["sources"].append(copy.deepcopy(value["sources"][0]))
        value["sources"][0]["url"] = "not a URL"
        value["policies"][0]["evidence_source_ids"] = ["missing-source"]
        value["policies"][0]["fixture_ids"] = ["missing-fixture"]
        value["policies"][0]["introduced_date"] = "2025-01-01"
        value["policies"][0]["last_reviewed"] = "2025-12-01"
        value["policies"][0]["review_after"] = "2026-01-01"
        self.write(value)
        result = evidence.audit_registry(policy.load_manifest(), registry_path=self.registry, today=dt.date(2026, 8, 9))
        identifiers = {item["id"] for item in result["errors"]}
        self.assertIn("duplicate-evidence-id", identifiers)
        self.assertIn("invalid-evidence-url", identifiers)
        self.assertIn("unknown-evidence-reference", identifiers)
        self.assertIn("missing-policy-fixture", identifiers)
        self.assertIn("policy-review-overdue", {item["id"] for item in result["reviews"]})
        with self.assertRaises(GuardrailsError):
            evidence.validate_registry(policy.load_manifest(), registry_path=self.registry)

    def test_positive_guidance_requires_evidence_and_rationale(self) -> None:
        value = copy.deepcopy(self.value)
        record = value["policies"][0]
        record["polarity"] = "positive-guidance"
        record["rationale"] = ""
        record["evidence_source_ids"] = []
        self.write(value)
        result = evidence.audit_registry(policy.load_manifest(), registry_path=self.registry)
        self.assertIn("positive-guidance-unjustified", {item["id"] for item in result["errors"]})

    def test_unknown_policy_scope_is_a_structural_error(self) -> None:
        value = copy.deepcopy(self.value)
        value["policies"][0]["scope"] = "unbounded-free-text"
        self.write(value)

        result = evidence.audit_registry(policy.load_manifest(), registry_path=self.registry)

        self.assertIn("unknown-policy-scope", {item["id"] for item in result["errors"]})

    def test_manifest_ids_must_be_present_unique_and_traceable(self) -> None:
        manifest = copy.deepcopy(policy.load_manifest())
        manifest["fragments"].append(copy.deepcopy(manifest["fragments"][0]))
        manifest["fragments"].append({"path": "fragments/missing.md"})

        result = evidence.audit_registry(manifest)

        identifiers = {item["id"] for item in result["errors"]}
        self.assertIn("duplicate-canonical-policy-id", identifiers)
        self.assertIn("missing-canonical-policy-id", identifiers)

    def test_generated_policy_traceability_is_checked_when_rendered_artifacts_are_supplied(self) -> None:
        artifacts = build.build_artifacts()
        artifacts = {
            path: data.replace(b"Canonical policy IDs:", b"Canonical policy id list:").replace(
                b"Canonical policy ID:", b"Canonical policy id:")
            for path, data in artifacts.items()
        }

        result = evidence.audit_registry(policy.load_manifest(), generated_artifacts=artifacts)

        self.assertIn("generated-policy-untraceable", {item["id"] for item in result["errors"]})

    def test_policy_lookup_returns_canonical_metadata_only(self) -> None:
        result = evidence.evidence_for_policy("maintainability", policy.load_manifest())
        self.assertEqual("maintainability", result["policy"]["id"])
        self.assertTrue(result["sources"])
        self.assertNotIn("content", result)

    def test_policy_lookup_includes_overdue_referenced_source_review(self) -> None:
        value = copy.deepcopy(self.value)
        value["sources"][0]["last_reviewed"] = "2026-03-01"
        value["sources"][0]["review_after"] = "2026-06-01"
        self.write(value)

        result = evidence.evidence_for_policy(
            "operating-principles", policy.load_manifest(), registry_path=self.registry
        )

        self.assertIn("evidence-review-overdue", {item["id"] for item in result["review_findings"]})

    def test_evidence_source_dates_are_temporally_coherent(self) -> None:
        fixtures = (
            ("future-last-reviewed", {"last_reviewed": "2030-01-01", "review_after": "2031-01-01"}, "future-evidence-review"),
            ("future-publication", {"publication_date": "2030-01-01", "last_reviewed": "2030-01-01", "review_after": "2031-01-01"}, "future-evidence-publication"),
            ("review-before-publication", {"publication_date": "2026-06-01", "last_reviewed": "2026-05-31"}, "evidence-review-before-publication"),
            ("window-reversed", {"last_reviewed": "2026-08-01", "review_after": "2026-07-31"}, "invalid-evidence-review-window"),
        )
        for name, changes, expected in fixtures:
            with self.subTest(name=name):
                value = copy.deepcopy(self.value)
                value["sources"][0].update(changes)
                self.write(value)
                result = evidence.audit_registry(
                    policy.load_manifest(), registry_path=self.registry, today=dt.date(2026, 8, 9)
                )
                self.assertIn(expected, {item["id"] for item in result["errors"]})

    def test_policy_dates_are_temporally_coherent(self) -> None:
        fixtures = (
            ("future-last-reviewed", {"last_reviewed": "2030-01-01", "review_after": "2031-01-01"}, "future-policy-review"),
            ("future-introduction", {"introduced_date": "2030-01-01", "last_reviewed": "2030-01-01", "review_after": "2031-01-01"}, "future-policy-introduction"),
            ("review-before-introduction", {"introduced_date": "2026-08-02", "last_reviewed": "2026-08-01"}, "policy-review-before-introduction"),
            ("window-reversed", {"last_reviewed": "2026-08-01", "review_after": "2026-07-31"}, "invalid-policy-review-window"),
        )
        for name, changes, expected in fixtures:
            with self.subTest(name=name):
                value = copy.deepcopy(self.value)
                value["policies"][0].update(changes)
                self.write(value)
                result = evidence.audit_registry(
                    policy.load_manifest(), registry_path=self.registry, today=dt.date(2026, 8, 9)
                )
                self.assertIn(expected, {item["id"] for item in result["errors"]})

    def test_same_day_and_historical_dates_are_valid_while_expiry_is_review_only(self) -> None:
        value = copy.deepcopy(self.value)
        value["sources"][0].update(
            {"publication_date": "2026-08-10", "last_reviewed": "2026-08-10", "review_after": "2026-08-10"}
        )
        value["policies"][0].update(
            {"introduced_date": "2025-01-01", "last_reviewed": "2026-01-01", "review_after": "2026-08-09"}
        )
        self.write(value)

        same_day = evidence.audit_registry(
            policy.load_manifest(), registry_path=self.registry, today=dt.date(2026, 8, 10)
        )

        self.assertNotIn("future-evidence-review", {item["id"] for item in same_day["errors"]})
        self.assertNotIn("invalid-evidence-review-window", {item["id"] for item in same_day["errors"]})
        self.assertIn("policy-review-overdue", {item["id"] for item in same_day["reviews"]})


if __name__ == "__main__":
    unittest.main()
