from __future__ import annotations

import copy
import json
import tempfile
import unittest
from pathlib import Path

from ai_engineering_guardrails import build, policy
from ai_engineering_guardrails.util import ROOT, GuardrailsError


class BuildTests(unittest.TestCase):
    def _temporary_manifest(self) -> tuple[tempfile.TemporaryDirectory[str], Path, dict[str, object]]:
        temporary = tempfile.TemporaryDirectory()
        root = Path(temporary.name) / "policy"
        root.mkdir()
        manifest = copy.deepcopy(policy.load_manifest())
        for entry in manifest["fragments"]:
            source = policy.MANIFEST_PATH.parent / entry["path"]
            target = root / entry["path"]
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(source.read_bytes())
        return temporary, root / "manifest.json", manifest

    def test_fragment_order_and_product_outputs(self) -> None:
        artifacts = build.build_artifacts()
        codex = artifacts[Path("dist/codex/AGENTS.md")].decode()
        headings = [
            "## Operating principles",
            "## Investigation and scope",
            "## Maintainability",
            "## Change safety",
            "## Git safety",
            "## Security and secrets",
            "## Dependencies",
            "## Infrastructure posture",
            "## Testing and verification",
            "## Reporting",
        ]
        positions = [codex.index(heading) for heading in headings]
        self.assertEqual(positions, sorted(positions))

    def test_build_is_byte_deterministic(self) -> None:
        self.assertEqual(build.build_artifacts(), build.build_artifacts())

    def test_every_generated_file_has_header_and_one_newline(self) -> None:
        for path, content in build.build_artifacts().items():
            with self.subTest(path=path):
                self.assertIn(b"GENERATED \xe2\x80\x94 DO NOT EDIT", content)
                self.assertTrue(content.endswith(b"\n"))
                self.assertFalse(content.endswith(b"\n\n"))

    def test_missing_manifest_file_fails(self) -> None:
        temporary, manifest_path, manifest = self._temporary_manifest()
        self.addCleanup(temporary.cleanup)
        manifest["fragments"][0]["path"] = "fragments/missing.md"
        manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
        with self.assertRaisesRegex(GuardrailsError, "missing"):
            build.build_artifacts(manifest_path=manifest_path)

    def test_duplicate_fragment_identifier_fails(self) -> None:
        temporary, manifest_path, manifest = self._temporary_manifest()
        self.addCleanup(temporary.cleanup)
        manifest["fragments"][1]["id"] = manifest["fragments"][0]["id"]
        manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
        with self.assertRaisesRegex(GuardrailsError, "duplicate"):
            build.build_artifacts(manifest_path=manifest_path)

    def test_unknown_product_in_manifest_fails(self) -> None:
        temporary, manifest_path, manifest = self._temporary_manifest()
        self.addCleanup(temporary.cleanup)
        manifest["fragments"][0]["products"] = ["codex", "unknown"]
        manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
        with self.assertRaisesRegex(GuardrailsError, "unknown product"):
            build.build_artifacts(manifest_path=manifest_path)

    def test_unknown_policy_association_identifiers_fail(self) -> None:
        for field, message in (("enforcement_ids", "enforcement"), ("risk_ids", "risk")):
            temporary, manifest_path, manifest = self._temporary_manifest()
            with temporary:
                manifest["fragments"][0][field] = ["unknown-association"]
                manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
                with self.subTest(field=field):
                    with self.assertRaisesRegex(GuardrailsError, message):
                        build.build_artifacts(manifest_path=manifest_path)

    def test_product_filtering(self) -> None:
        temporary, manifest_path, manifest = self._temporary_manifest()
        self.addCleanup(temporary.cleanup)
        manifest["fragments"][0]["products"] = ["codex"]
        manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
        cursor = build.build_artifacts(("cursor",), manifest_path=manifest_path)[
            Path("dist/cursor/user-rules.md")
        ].decode()
        self.assertNotIn("## Operating principles", cursor)
        self.assertIn("## Investigation and scope", cursor)

    def test_maximum_output_size_fails(self) -> None:
        temporary, manifest_path, manifest = self._temporary_manifest()
        self.addCleanup(temporary.cleanup)
        manifest["output_limits_bytes"]["codex"] = 10
        manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
        with self.assertRaisesRegex(GuardrailsError, "exceeds"):
            build.build_artifacts(("codex",), manifest_path=manifest_path)

    def test_always_loaded_policy_budget_fails_before_product_limit(self) -> None:
        temporary, manifest_path, manifest = self._temporary_manifest()
        self.addCleanup(temporary.cleanup)
        manifest["always_loaded_budget_bytes"] = 10
        manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
        with self.assertRaisesRegex(GuardrailsError, "always-loaded budget"):
            build.build_artifacts(("codex",), manifest_path=manifest_path)

    def test_unknown_requested_product_fails(self) -> None:
        with self.assertRaisesRegex(GuardrailsError, "unknown product"):
            build.build_artifacts(("unknown",))

    def test_second_build_changes_no_bytes(self) -> None:
        build.build()
        first = {path: path.read_bytes() for path in build.build_artifacts()}
        build.build()
        self.assertEqual(first, {path: path.read_bytes() for path in build.build_artifacts()})


class SkillTests(unittest.TestCase):
    def test_required_portable_skills_and_frontmatter(self) -> None:
        expected = {
            "workstation-safe-change",
            "workstation-code-review",
            "workstation-git-workflow",
            "workstation-incident-analysis",
            "workstation-infrastructure-review",
            "workstation-guardrail-maintenance",
        }
        files = policy.discover_skills()
        names = {policy.parse_skill(path)[0]["name"] for path in files}
        self.assertEqual(expected, names)
        self.assertEqual(len(names), len(files))

    def test_missing_required_skill_field_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            skill = Path(temporary) / "bad-skill/SKILL.md"
            skill.parent.mkdir()
            skill.write_text("---\nname: bad-skill\n---\n\n# Body\n", encoding="utf-8")
            with self.assertRaises(GuardrailsError):
                policy.parse_skill(skill)

    def test_vendor_only_frontmatter_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            skill = Path(temporary) / "bad-skill/SKILL.md"
            skill.parent.mkdir()
            skill.write_text(
                "---\nname: bad-skill\ndescription: Test.\nallowed-tools: Bash\n---\n\n# Body\n",
                encoding="utf-8",
            )
            with self.assertRaises(GuardrailsError):
                policy.parse_skill(skill)

    def test_canonical_skills_contain_no_absolute_machine_path(self) -> None:
        for skill in policy.discover_skills():
            text = skill.read_text(encoding="utf-8")
            self.assertNotIn(str(Path.home()), text)
            self.assertNotIn(str(ROOT), text)

    def test_code_review_skill_requires_a_material_simplicity_review(self) -> None:
        text = (policy.SKILLS_ROOT / "workstation-code-review/SKILL.md").read_text(encoding="utf-8")
        self.assertIn("three concrete consumers", text)


if __name__ == "__main__":
    unittest.main()
