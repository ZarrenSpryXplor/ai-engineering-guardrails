from __future__ import annotations

import json
import stat
import unittest
from pathlib import Path

from ai_engineering_guardrails import components, packs, policy
from ai_engineering_guardrails.resources import RESOURCE_ROOT


PACK_ROOT = RESOURCE_ROOT / "packs/shared/architecture-diagramming"
SKILL_ROOT = PACK_ROOT / "skills/workstation-architecture-diagramming"
SKILL = SKILL_ROOT / "SKILL.md"
STANDARDS = SKILL_ROOT / "references/standards-and-notation.md"
DIAGRAMS_NET = SKILL_ROOT / "references/diagrams-net.md"


class ArchitectureDiagrammingTests(unittest.TestCase):
    def test_skill_metadata_is_portable_concise_front_loaded_and_unique(self) -> None:
        raw = SKILL.read_text(encoding="utf-8")
        fields, body = policy.parse_skill(SKILL)
        frontmatter = raw.split("---\n", 2)[1]
        frontmatter_fields = {
            line.split(":", 1)[0]
            for line in frontmatter.splitlines()
            if ":" in line
        }
        audit = components.skills_audit()
        names = [item["name"] for item in audit["skills"]]
        description = fields["description"]

        self.assertEqual("workstation-architecture-diagramming", fields["name"])
        self.assertEqual({"name", "description"}, frontmatter_fields)
        self.assertEqual(1, names.count(fields["name"]))
        self.assertTrue(description.startswith("Architecture diagram creation and review"))
        self.assertIn("software, cloud, deployment, network, data-flow", description[:120])
        self.assertLess(
            len(description),
            components.load_thresholds()["skills"]["description_characters"],
        )
        self.assertLess(len(body), 6_000)
        self.assertIsNone(components._routing_description_issue(fields["name"], description))
        self.assertIsNone(components.GENERIC_ROUTING_PREFIX_RE.match(description))
        self.assertFalse(
            any(fields["name"] in warning["skills"] for warning in audit["catalogue"]["routing_overlap_warnings"])
        )
        self.assertLess(
            audit["catalogue"]["total_description_characters"],
            components.load_thresholds()["skills"]["catalogue_reference_budget_characters"],
        )

    def test_pack_is_markerless_shared_specialist_and_not_a_fresh_default_skill(self) -> None:
        manifest = json.loads((PACK_ROOT / "pack.json").read_text(encoding="utf-8"))
        available = packs.load_packs()

        self.assertEqual("shared", manifest["type"])
        self.assertEqual("specialist", manifest["catalogue_tier"])
        self.assertEqual(["skills/workstation-architecture-diagramming/SKILL.md"], manifest["skills"])
        for field in (
            "file_detectors",
            "directory_detectors",
            "explicit_exclusions",
            "dependent_packs",
            "conflicting_packs",
            "policy_fragments",
            "command_policy_fragments",
            "verification_definitions",
            "routing_additions",
        ):
            self.assertEqual([], manifest[field], field)
        self.assertEqual("specialist", packs.catalogue_tier(available["architecture-diagramming"]))
        self.assertIn("architecture-diagramming", packs.default_pack_ids(available))
        self.assertNotIn("architecture-diagramming", packs.default_skill_pack_ids(available))

    def test_pack_contains_only_portable_text_sources_and_two_references(self) -> None:
        files = sorted(path for path in PACK_ROOT.rglob("*") if path.is_file())
        relative_files = {path.relative_to(PACK_ROOT).as_posix() for path in files}
        self.assertEqual(
            {
                "pack.json",
                "skills/workstation-architecture-diagramming/SKILL.md",
                "skills/workstation-architecture-diagramming/references/diagrams-net.md",
                "skills/workstation-architecture-diagramming/references/standards-and-notation.md",
            },
            relative_files,
        )
        skill_text = SKILL.read_text(encoding="utf-8")
        self.assertIn("](references/standards-and-notation.md)", skill_text)
        self.assertIn("](references/diagrams-net.md)", skill_text)
        self.assertTrue(STANDARDS.is_file())
        self.assertTrue(DIAGRAMS_NET.is_file())

        forbidden_suffixes = {
            ".drawio", ".xml", ".pdf", ".png", ".jpg", ".jpeg", ".gif",
            ".svg", ".ico", ".zip", ".gz", ".jar", ".py", ".sh", ".js", ".ts",
        }
        self.assertFalse(any(path.suffix.casefold() in forbidden_suffixes for path in files))
        self.assertFalse(any(stat.S_IMODE(path.stat().st_mode) & 0o111 for path in files))
        for path in files:
            with self.subTest(path=path):
                path.read_bytes().decode("utf-8")
                self.assertFalse(any(token in path.name.casefold() for token in ("icon", "logo", "stencil", "template")))

    def test_references_are_bounded_and_record_official_provenance(self) -> None:
        standards = STANDARDS.read_text(encoding="utf-8")
        diagrams_net = DIAGRAMS_NET.read_text(encoding="utf-8")
        required_urls = (
            "https://www.iso.org/standard/74393.html",
            "https://c4model.com/diagrams",
            "https://c4model.com/diagrams/notation",
            "https://www.omg.org/spec/UML/2.5.1/",
            "https://www.omg.org/spec/BPMN/2.0.2/",
            "https://mermaid.js.org/syntax/c4.html",
            "https://aws.amazon.com/architecture/icons/",
            "https://learn.microsoft.com/en-us/azure/architecture/icons/",
            "https://cloud.google.com/icons",
            "https://www.opengroup.org/archimate-licensed-downloads",
        )

        self.assertIn("Last project verification: 2026-08-13", standards)
        for url in required_urls:
            self.assertIn(url, standards)
        self.assertLess(len(standards), 8_000)
        self.assertLess(len(diagrams_net), 8_000)
        self.assertLess(len(standards) + len(diagrams_net), 18_000)
        self.assertNotIn("</root>", standards + diagrams_net)
        self.assertNotIn("<mxfile", diagrams_net)

    def test_skill_sets_concern_routes_and_evidence_boundaries(self) -> None:
        text = SKILL.read_text(encoding="utf-8")
        for required in (
            "C4-informed system-context or container view",
            "UML-informed sequence view",
            "UML-informed state view",
            "Crow's Foot-style ERD",
            "Network, security, or deployment topology",
            "Data flow",
            "Simple decision or operational flow",
            "Never invent services, protocols, placement, flows, controls, dependencies, availability, or ownership",
            "workstation-technical-writing` owns prose-only architecture documentation",
        ):
            self.assertIn(required, text)

    def test_conformance_certification_approval_and_endorsement_are_negated(self) -> None:
        combined = "\n".join(
            path.read_text(encoding="utf-8")
            for path in (PACK_ROOT / "pack.json", SKILL, STANDARDS, DIAGRAMS_NET)
        )

        self.assertIn(
            "no claim of formal conformance, certification, approval, or endorsement",
            combined,
        )
        self.assertIn("does not establish formal notation conformance, certification, or vendor endorsement", combined)
        self.assertIn("does not mean conformant, certified, approved, or endorsed", combined)
        self.assertIn("does not claim diagrams.net approval, endorsement, certification, or formal format conformance", combined)

    def test_diagrams_net_guidance_distinguishes_structure_rendering_and_source_truth(self) -> None:
        skill = SKILL.read_text(encoding="utf-8")
        reference = DIAGRAMS_NET.read_text(encoding="utf-8")
        combined = skill + "\n" + reference

        self.assertIn("uncompressed UTF-8 XML", combined)
        self.assertIn("Structural review proves only these source invariants", reference)
        self.assertIn("Never call it render validation", reference)
        self.assertIn("accepts the file without a repair prompt", reference)
        self.assertIn("Maintain one authoritative source for a diagram", reference)
        self.assertIn("regenerating or reimporting Mermaid can reset manual geometry", reference)
        self.assertIn("bundles no `.drawio` template, XML template", reference)

    def test_bpmn_and_archimate_are_explicitly_out_of_scope_for_v1(self) -> None:
        skill = SKILL.read_text(encoding="utf-8")
        standards = STANDARDS.read_text(encoding="utf-8")

        self.assertIn("BPMN and ArchiMate are outside v1", skill)
        self.assertIn("BPMN-conformance guidance is intentionally excluded from v1", standards)
        self.assertIn("ArchiMate 4 is outside v1", standards)
        self.assertIn("current authorized source and qualified review", skill)


if __name__ == "__main__":
    unittest.main()
