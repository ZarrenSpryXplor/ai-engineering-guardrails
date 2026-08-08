from __future__ import annotations

import ast
import json
import tempfile
import tomllib
import unittest
from pathlib import Path
from unittest import mock

from ai_engineering_guardrails import build, policy, routing, scan
from ai_engineering_guardrails.resources import RESOURCE_ROOT
from ai_engineering_guardrails.util import PRODUCTS, ROOT, GuardrailsError, home_path, read_json


class ValidationTests(unittest.TestCase):
    def test_generated_json_toml_markdown_are_valid_and_portable(self) -> None:
        artifacts = build.build_artifacts()
        self.assertTrue(artifacts)
        for path, content in artifacts.items():
            text = content.decode("utf-8")
            with self.subTest(path=path):
                self.assertTrue(text.strip())
                self.assertNotIn(str(Path.home()), text)
                self.assertNotIn(str(ROOT), text)
                if path.suffix == ".json":
                    json.loads(text)
                if path.suffix == ".toml":
                    tomllib.loads(text)

    def test_full_validation_without_optional_executables(self) -> None:
        with mock.patch("ai_engineering_guardrails.build.shutil.which", return_value=None):
            build.validate(check_codex=True)

    def test_codex_check_skips_when_unavailable(self) -> None:
        with mock.patch("ai_engineering_guardrails.build.shutil.which", return_value=None):
            self.assertIn("skipped", build.validate_codex_rules())

    def test_selected_home_guard_rejects_posix_and_windows_escape(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            selected = Path(temporary)
            for value in ("../escape", "/absolute/escape", r"C:\\Users\\Example\\escape"):
                with self.subTest(value=value), self.assertRaisesRegex(GuardrailsError, "outside selected home"):
                    home_path(selected, value)

    def test_canonical_json_reader_rejects_symbolic_links(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "source.json"
            source.write_text("{}\n", encoding="utf-8")
            link = root / "linked.json"
            try:
                link.symlink_to(source)
            except OSError:
                self.skipTest("symbolic links are unavailable")
            with self.assertRaisesRegex(GuardrailsError, "symbolic link"):
                read_json(link)

    def test_generated_output_is_current(self) -> None:
        build.assert_generated_current(PRODUCTS)

    def test_canonical_governance_data_validates(self) -> None:
        policy.validate_canonical_data()

    def test_risk_verification_requirements_reject_duplicate_risk_classes(self) -> None:
        requirements_path = RESOURCE_ROOT / "risk/verification-requirements.json"
        original_read_json = policy.read_json
        duplicate_data = original_read_json(requirements_path)
        duplicate = dict(duplicate_data["requirements"][0])
        duplicate["id"] = "another-high-risk-change"
        duplicate_data["requirements"].append(duplicate)

        def read_with_duplicate(path: Path, default: object = None) -> object:
            if path == requirements_path:
                return duplicate_data
            return original_read_json(path, default=default)

        with mock.patch("ai_engineering_guardrails.policy.read_json", side_effect=read_with_duplicate):
            with self.assertRaisesRegex(GuardrailsError, "risk class"):
                policy.validate_canonical_data()

    def test_high_risk_classification_covers_required_domains(self) -> None:
        data = json.loads((RESOURCE_ROOT / "risk/path-classification.json").read_text(encoding="utf-8"))
        identifiers = {entry["id"] for entry in data["classifications"]}
        self.assertTrue(
            {
                "security-and-identity",
                "secrets-and-pki",
                "contracts",
                "persistent-data",
                "concurrency-and-distributed-systems",
                "infrastructure-control",
                "ci-cd",
                "package-and-release",
                "production-configuration",
            }.issubset(identifiers)
        )

    def test_supply_chain_validation_flags_mutable_and_write_capable_entries(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "trusted.json"
            path.write_text(
                json.dumps({"components":[{
                    "id":"spacelift-unsafe", "kind":"mcp-server", "source":"https://example.invalid/package@latest",
                    "version":"latest", "digest":None, "allowed_tools":["mutate"], "denied_tools":[],
                    "credential_class":"write-capable", "expected_network_destinations":["example.invalid"]
                }]}),
                encoding="utf-8",
            )
            findings = policy.supply_chain_findings(path)
            self.assertTrue(any("mutable" in item for item in findings))
            self.assertTrue(any("write-capable Spacelift" in item for item in findings))

    def test_supply_chain_validation_flags_local_digest_executable_and_expanded_tools(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            skill = root / "skill"
            skill.mkdir()
            (skill / "SKILL.md").write_text("synthetic\n", encoding="utf-8")
            (skill / "runner.py").write_text("print('synthetic')\n", encoding="utf-8")
            registry = root / "trusted.json"
            registry.write_text(
                json.dumps(
                    {
                        "components": [
                            {
                                "id": "local-skill",
                                "kind": "skill",
                                "source": "skill",
                                "version": "1",
                                "digest": "0" * 64,
                                "allowed_tools": ["read"],
                                "denied_tools": ["write"],
                                "observed_tools": ["read", "write", "unexpected"],
                                "executable_files": [],
                                "credential_class": "none",
                                "expected_network_destinations": [],
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )
            findings = policy.supply_chain_findings(registry)
            self.assertTrue(any("digest changed" in item for item in findings))
            self.assertTrue(any("undeclared executable" in item for item in findings))
            self.assertTrue(any("expanded tool surface" in item for item in findings))

    def test_spacelift_policy_structure_uses_current_categories_and_rego_v1(self) -> None:
        root = RESOURCE_ROOT / "platform-policies/spacelift"
        scan.validate_spacelift_policy_structure(root)
        for name in ("approval", "login", "notification", "plan", "push", "trigger"):
            self.assertTrue((root / name).is_dir())
        for path in root.rglob("*.rego"):
            self.assertIn("import rego.v1", path.read_text(encoding="utf-8"))
        self.assertFalse(any(path.name in {"access", "task", "initialization"} for path in root.rglob("*")))

    def test_generated_enterprise_spacelift_bundle_is_complete_and_review_only(self) -> None:
        root = ROOT / "dist/enterprise/spacelift/policies"
        for name in ("approval", "login", "notification", "plan", "push", "trigger"):
            policy_file = root / name / "guardrails.rego"
            test_file = root / name / "guardrails_test.rego"
            self.assertTrue(policy_file.is_file())
            self.assertTrue(test_file.is_file())
            self.assertIn("GENERATED — DO NOT EDIT", policy_file.read_text(encoding="utf-8"))
            self.assertIn("import rego.v1", policy_file.read_text(encoding="utf-8"))
        self.assertTrue((root / "fixtures/guardrails.json").is_file())
        self.assertNotIn("/intent/mcp", "\n".join(path.read_text(encoding="utf-8") for path in root.rglob("*.*")))

    def test_generated_codex_requirements_use_current_managed_schema(self) -> None:
        content = build.build_artifacts(("codex",))[Path("dist/enterprise/codex/requirements.toml")]
        requirements = tomllib.loads(content.decode("utf-8"))
        self.assertEqual(":workspace", requirements["default_permissions"])
        self.assertEqual(
            {":read-only": True, ":workspace": True},
            requirements["allowed_permission_profiles"],
        )
        self.assertNotIn("allowed_sandbox_modes", requirements)
        self.assertTrue(requirements["allow_managed_hooks_only"])
        self.assertTrue(requirements["features"]["hooks"])
        self.assertIn("managed_dir", requirements["hooks"])
        self.assertEqual("command", requirements["hooks"]["PreToolUse"][0]["hooks"][0]["type"])

    def test_one_language_implementation_constraint(self) -> None:
        allowed = {".py", ".json", ".md", ".toml", ".rules"}
        for directory in (ROOT / "ai_engineering_guardrails", ROOT / "tools", ROOT / "enforcement"):
            for path in directory.rglob("*"):
                if path.is_file() and "__pycache__" not in path.parts and "_resources" not in path.parts:
                    self.assertIn(path.suffix, allowed, path)

    def test_python_implementation_imports_no_external_runtime_dependency(self) -> None:
        standard = set(__import__("sys").stdlib_module_names)
        for directory in (ROOT / "ai_engineering_guardrails", ROOT / "tools", ROOT / "enforcement"):
            for path in directory.rglob("*.py"):
                tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
                for node in ast.walk(tree):
                    module = node.module if isinstance(node, ast.ImportFrom) else None
                    names = [alias.name for alias in node.names] if isinstance(node, ast.Import) else []
                    roots = ([module.split(".")[0]] if module and node.level == 0 else []) + [name.split(".")[0] for name in names]
                    for imported in roots:
                        self.assertTrue(
                            imported in standard or imported in {"ai_engineering_guardrails"},
                            f"external import {imported} in {path}",
                        )

    def test_routing_and_policy_identifiers_are_unique(self) -> None:
        merged = policy.load_enforcement_policy()
        identifiers = [entry["id"] for collection in ("rules", "classifications", "structured_tool_rules") for entry in merged[collection]]
        self.assertEqual(len(identifiers), len(set(identifiers)))
        self.assertEqual(5, len(routing.load_config()["agents"]))

    def test_canonical_policy_is_not_generated_output(self) -> None:
        for path in (RESOURCE_ROOT / "policy/fragments").glob("*.md"):
            self.assertNotIn("GENERATED — DO NOT EDIT", path.read_text(encoding="utf-8"))
        for path in (ROOT / "dist").rglob("*"):
            if path.is_file():
                self.assertIn("GENERATED — DO NOT EDIT", path.read_text(encoding="utf-8"))

    def test_repository_claude_file_delegates_to_agents(self) -> None:
        self.assertEqual("@AGENTS.md\n", (ROOT / "CLAUDE.md").read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
