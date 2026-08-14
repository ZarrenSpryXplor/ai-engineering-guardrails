from __future__ import annotations

import json
import re
import unittest
from pathlib import Path

from ai_engineering_guardrails import components, evidence, packs, policy
from ai_engineering_guardrails.resources import RESOURCE_ROOT


ROOT = Path(__file__).resolve().parents[1]
PACK_ROOT = RESOURCE_ROOT / "packs/shared/technical-writing"
SKILL = PACK_ROOT / "skills/workstation-technical-writing/SKILL.md"


class TechnicalWritingTests(unittest.TestCase):
    def test_skill_metadata_is_portable_front_loaded_and_unique(self) -> None:
        fields, body = policy.parse_skill(SKILL)
        description = fields["description"]
        skill_files, boundary_findings = components._skill_files(
            None, components.load_thresholds()["component"]
        )
        self.assertEqual([], boundary_findings)
        all_names = [policy.parse_skill(path)[0]["name"] for path in skill_files]

        self.assertEqual("workstation-technical-writing", fields["name"])
        self.assertEqual(1, all_names.count(fields["name"]))
        self.assertTrue(description.startswith("Technical documentation with ASD-STE100"))
        self.assertLess(description.index("ASD-STE100"), 40)
        self.assertLess(description.index("READMEs"), 90)
        self.assertLess(len(description), components.load_thresholds()["skills"]["description_characters"])
        self.assertIsNone(components.GENERIC_ROUTING_PREFIX_RE.match(description))
        self.assertIn("commands, identifiers", body)
        self.assertIn("ordinary conversation", body)
        self.assertIn("formal ASD-STE100 compliance", body)

    def test_skill_is_specialist_and_excluded_from_fresh_default(self) -> None:
        available = packs.load_packs()

        self.assertEqual("specialist", packs.catalogue_tier(available["technical-writing"]))
        self.assertNotIn("technical-writing", packs.default_skill_pack_ids(available))
        self.assertIn("technical-writing", packs.default_pack_ids(available))

    def test_provenance_does_not_bundle_the_standard_or_logo(self) -> None:
        files = [path for path in PACK_ROOT.rglob("*") if path.is_file()]
        text = "\n".join(path.read_text(encoding="utf-8") for path in files)

        self.assertFalse(any(path.suffix.lower() == ".pdf" for path in files))
        self.assertFalse(any(path.suffix.lower() in {".png", ".jpg", ".jpeg", ".svg"} for path in files))
        self.assertIn("Issue 9", text)
        self.assertIn("15 January 2025", text)
        self.assertIn("does not use the ASD logo", text)
        self.assertNotIn("controlled dictionary entries", text)

    def test_asd_claims_are_negated_not_asserted(self) -> None:
        pattern = re.compile(
            r"\b(?:ASD[- ]approved|ASD[- ]certified|ASD-STE100[- ]compliant checker|officially certified STE software)\b",
            re.IGNORECASE,
        )
        paths = [SKILL, PACK_ROOT / "skills/workstation-technical-writing/references/asd-ste100.md"]
        public_guide = ROOT / "docs/technical-writing.md"
        if public_guide.is_file():
            paths.append(public_guide)
        for path in paths:
            for line in path.read_text(encoding="utf-8").splitlines():
                if pattern.search(line):
                    with self.subTest(path=path, line=line):
                        self.assertRegex(line.casefold(), r"\b(?:not|no|never|cannot|do not|does not)\b")

    def test_evidence_is_local_metadata_not_runtime_fetching(self) -> None:
        registry = evidence.load_registry()
        source = next(item for item in registry["sources"] if item["id"] == "asd-ste100-issue-9")
        runtime_sources = "\n".join(
            (ROOT / relative).read_text(encoding="utf-8")
            for relative in ("ai_engineering_guardrails/evidence.py", "ai_engineering_guardrails/scan.py")
        )

        self.assertEqual("official-standard-source", source["evidence_type"])
        self.assertNotIn("urlopen(", runtime_sources)
        self.assertNotIn("requests.", runtime_sources)


if __name__ == "__main__":
    unittest.main()
