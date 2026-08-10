from __future__ import annotations

import contextlib
import io
import json
import shutil
import tempfile
import unittest
from pathlib import Path

from ai_engineering_guardrails import cli, install as installer, packs
from ai_engineering_guardrails.resources import RESOURCE_ROOT
from ai_engineering_guardrails.util import ROOT, GuardrailsError


FIXTURES = ROOT / "tests/fixtures/packs"


class PackDetectionTests(unittest.TestCase):
    def assert_detects(self, fixture: str, identifiers: tuple[str, ...]) -> packs.DetectionResult:
        result = packs.detect_packs(FIXTURES / fixture)
        for identifier in identifiers:
            self.assertIn(identifier, result.active_packs, fixture)
            self.assertTrue(any(item.pack_id == identifier for item in result.evidence), identifier)
        return result

    def test_java_maven_single_and_multi_module(self) -> None:
        self.assert_detects("maven-single", ("java",))
        result = self.assert_detects("maven-multi", ("java",))
        self.assertGreaterEqual(len([item for item in result.evidence if item.pack_id == "java"]), 2)

    def test_gradle_and_mixed_java_monorepo(self) -> None:
        self.assert_detects("gradle", ("java",))
        result = self.assert_detects("mixed-java", ("java",))
        evidence = {item.path for item in result.evidence if item.pack_id == "java"}
        self.assertTrue(any("maven" in path for path in evidence))
        self.assertTrue(any("gradle" in path for path in evidence))

    def test_dotnet_solution_global_json_and_central_packages(self) -> None:
        first = self.assert_detects("dotnet-solution", ("dotnet",))
        second = self.assert_detects("dotnet-central", ("dotnet",))
        self.assertTrue(any(item.path.endswith("global.json") for item in first.evidence))
        self.assertTrue(any(item.path.endswith("Directory.Packages.props") for item in second.evidence))

    def test_python_manager_fixtures(self) -> None:
        for fixture in ("python-uv", "python-poetry", "python-requirements"):
            with self.subTest(fixture=fixture):
                self.assert_detects(fixture, ("python",))

    def test_node_manager_selection(self) -> None:
        expected = {"npm":"npm", "pnpm-workspace":"pnpm", "yarn-workspace":"yarn", "typescript-monorepo":"pnpm"}
        for fixture, manager in expected.items():
            with self.subTest(fixture=fixture):
                result = self.assert_detects(fixture, ("node",))
                self.assertEqual(manager, result.package_manager)

    def test_language_extensions_alone_do_not_detect_stack(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "Main.java").write_text("class Main {}", encoding="utf-8")
            (root / "example.ts").write_text("export const value = 1;", encoding="utf-8")
            result = packs.detect_packs(root)
            self.assertNotIn("java", result.active_packs)
            self.assertNotIn("node", result.active_packs)

    def test_generic_yaml_alone_does_not_detect_ansible(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "site.yml").write_text(
                "---\n- name: Synthetic example\n  hosts: all\n  tasks: []\n",
                encoding="utf-8",
            )
            result = packs.detect_packs(root)
            self.assertNotIn("ansible", result.active_packs)

    def test_detection_does_not_follow_repository_file_symlinks(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            external = root.parent / f"{root.name}-external-package.json"
            external.write_text('{"packageManager":"pnpm@10.0.0"}\n', encoding="utf-8")
            self.addCleanup(external.unlink, missing_ok=True)
            (root / "package.json").symlink_to(external)
            result = packs.detect_packs(root)
            self.assertNotIn("node", result.active_packs)
            self.assertIsNone(result.package_manager)

    def test_infrastructure_fixtures(self) -> None:
        expected = {
            "ansible": ("ansible",),
            "kubernetes": ("kubernetes",),
            "helm-chart": ("helm",),
            "kustomize": ("kustomize", "kubernetes"),
            "terraform": ("terraform",),
            "opentofu": ("opentofu",),
            "terragrunt": ("terragrunt",),
            "spacelift": ("spacelift",),
        }
        for fixture, identifiers in expected.items():
            with self.subTest(fixture=fixture):
                self.assert_detects(fixture, identifiers)

    def test_v11_fixtures(self) -> None:
        expected = {
            "containers-oci": "containers-oci",
            "azure": "azure",
            "source-control-cicd": "source-control-cicd",
            "database-migrations": "database-migrations",
            "observability": "observability",
            "api-schema": "api-schema-compatibility",
            "secrets-pki": "secrets-pki",
        }
        for fixture, identifier in expected.items():
            with self.subTest(fixture=fixture):
                self.assert_detects(fixture, (identifier,))

    def test_polyglot_monorepo_detects_multiple_packs(self) -> None:
        result = packs.detect_packs(FIXTURES / "polyglot")
        self.assertTrue({"java", "python", "node", "terraform", "helm"} <= set(result.active_packs))

    def test_build_output_vendor_and_fixture_directories_are_ignored(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            for relative in (
                "vendor/pom.xml",
                "build/package.json",
                "node_modules/package.json",
                "tests/fixtures/pom.xml",
                ".ansible/collections/ansible_collections/example/demo/galaxy.yml",
                "collections/ansible_collections/example/demo/galaxy.yml",
            ):
                path = root / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text("{}", encoding="utf-8")
            self.assertEqual((), packs.detect_packs(root).active_packs)

    def test_explicit_override_enables_disables_and_reports_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "pom.xml").write_text("<project/>", encoding="utf-8")
            (root / ".ai-guardrails.json").write_text(
                json.dumps({"schema_version":1,"enable_packs":["azure"],"disable_packs":["java"],"package_manager":"pnpm","target_classifications":{"azure_subscriptions":{"synthetic":"dev"}}}),
                encoding="utf-8",
            )
            result = packs.detect_packs(root)
            self.assertIn("azure", result.active_packs)
            self.assertNotIn("java", result.active_packs)
            self.assertTrue(any(item.kind == "override" for item in result.evidence))

    def test_override_rejects_sensitive_fields_and_bad_lifecycle(self) -> None:
        for value, message in (
            ({"schema_version":1,"api_token":"synthetic"}, "sensitive"),
            ({"schema_version":1,"target_classifications":{"azure_subscriptions":{"x":"prod"}}}, "dev, tst, int, or prd"),
        ):
            with tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                (root / ".ai-guardrails.json").write_text(json.dumps(value), encoding="utf-8")
                with self.subTest(value=value), self.assertRaisesRegex(GuardrailsError, message):
                    packs.detect_packs(root)

    def test_java_wrapper_selection(self) -> None:
        self.assertEqual("./mvnw", packs.select_java_tool(FIXTURES / "maven-single"))
        self.assertEqual("./gradlew", packs.select_java_tool(FIXTURES / "gradle"))

    def test_explain_reports_on_demand_pack_policy_verification_and_routing(self) -> None:
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            self.assertEqual(0, cli.main(["packs", "explain", "--repo", str(FIXTURES / "maven-single")]))
        text = output.getvalue()
        self.assertIn("java: on-demand policy: policy.md: Java capability policy", text)
        self.assertIn("java: verification: java-targeted-test (test; affected-module-first)", text)
        self.assertIn("java: routing hints: java-implementation -> balanced/medium (write)", text)


class PackValidationTests(unittest.TestCase):
    def test_all_packs_validate(self) -> None:
        count, examples = packs.validate_packs()
        self.assertEqual(23, count)
        self.assertGreater(examples, 375)

    def test_pack_types_define_small_catalogue_tiers_and_contextual_defaults(self) -> None:
        available = packs.load_packs()
        tiers = {identifier: packs.catalogue_tier(pack) for identifier, pack in available.items()}

        self.assertEqual(10, sum(tier == "contextual" for tier in tiers.values()))
        self.assertEqual(13, sum(tier == "specialist" for tier in tiers.values()))
        self.assertEqual("specialist", tiers["technical-writing"])
        self.assertEqual(set(available), set(packs.default_pack_ids(available)))
        skill_defaults = set(packs.default_skill_pack_ids(available))
        self.assertTrue({"python", "node", "java", "dotnet", "dependency-management"}.issubset(skill_defaults))
        self.assertTrue({"kubernetes", "terraform", "spacelift", "source-control-cicd", "technical-writing"}.isdisjoint(skill_defaults))

    def test_explicit_catalogue_tier_is_bounded(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            destination = Path(temporary) / "shared/technical-writing"
            shutil.copytree(RESOURCE_ROOT / "packs/shared/technical-writing", destination)
            config = json.loads((destination / "pack.json").read_text(encoding="utf-8"))
            config["catalogue_tier"] = "always"
            (destination / "pack.json").write_text(json.dumps(config), encoding="utf-8")

            with self.assertRaisesRegex(GuardrailsError, "catalogue_tier"):
                packs.load_pack(destination / "pack.json")

    def test_dependency_patterns_are_classified_by_existing_capability_packs(self) -> None:
        available = packs.load_packs()
        manifests, lockfiles = packs.dependency_file_patterns(available)

        self.assertTrue(
            {"package.json", "pyproject.toml", "requirements*.txt", "pom.xml", "*.csproj", "Chart.yaml"}
            <= set(manifests)
        )
        self.assertTrue(
            {"package-lock.json", "poetry.lock", "gradle.lockfile", "packages.lock.json", ".terraform.lock.hcl", "Chart.lock"}
            <= set(lockfiles)
        )
        for pack in available.values():
            detectors = set(pack["file_detectors"])
            self.assertTrue(set(pack["dependency_manifests"]) <= detectors)
            self.assertTrue(set(pack["dependency_lockfiles"]) <= detectors)

    def test_missing_pack_field_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            destination = Path(temporary) / "languages/java"
            shutil.copytree(RESOURCE_ROOT / "packs/languages/java", destination)
            config = json.loads((destination / "pack.json").read_text())
            config.pop("description")
            (destination / "pack.json").write_text(json.dumps(config), encoding="utf-8")
            with self.assertRaisesRegex(GuardrailsError, "missing field"):
                packs.load_pack(destination / "pack.json")

    def test_invalid_pack_verification_and_routing_data_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            packs_root = Path(temporary) / "packs"
            shutil.copytree(RESOURCE_ROOT / "packs", packs_root)
            destination = packs_root / "languages/java"
            verification = json.loads((destination / "verification.json").read_text(encoding="utf-8"))
            verification["checks"][0]["commands"] = []
            (destination / "verification.json").write_text(json.dumps(verification), encoding="utf-8")
            with self.assertRaisesRegex(GuardrailsError, "verification commands"):
                packs.validate_packs(packs_root)

            verification["checks"][0]["commands"] = ["synthetic check"]
            (destination / "verification.json").write_text(json.dumps(verification), encoding="utf-8")
            routing_data = json.loads((destination / "routing.json").read_text(encoding="utf-8"))
            routing_data["task_classes"][0]["tier"] = "unbounded"
            (destination / "routing.json").write_text(json.dumps(routing_data), encoding="utf-8")
            with self.assertRaisesRegex(GuardrailsError, "routing task metadata"):
                packs.validate_packs(packs_root)

    def test_pack_skill_frontmatter_is_portable_and_unique(self) -> None:
        names: set[str] = set()
        for pack in packs.load_packs().values():
            for skill in packs.pack_skill_files(pack):
                frontmatter = skill.read_text(encoding="utf-8").split("---\n", 2)[1]
                fields = {line.split(":", 1)[0] for line in frontmatter.splitlines() if ":" in line}
                self.assertEqual({"name", "description"}, fields)
                name = skill.parent.name
                self.assertNotIn(name, names)
                names.add(name)

    def test_lifecycle_vocabulary_is_canonical(self) -> None:
        targets = json.loads((RESOURCE_ROOT / "config/targets.example.json").read_text())
        values = {value for mapping in targets["classifications"].values() for value in mapping.values()}
        self.assertTrue(values <= {"dev", "tst", "int", "prd"})
        self.assertNotIn("prod", values)
        self.assertNotIn("qa", values)


class PackInstallTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.home = Path(self.temporary.name)

    def test_selected_pack_closure_installs_on_demand_skills_and_runtime_policy(self) -> None:
        with contextlib.redirect_stdout(io.StringIO()):
            installer.install(("codex",), self.home, force=False, dry_run=False, pack_ids=("azure",))
        self.assertTrue((self.home / ".agents/skills/workstation-azure/SKILL.md").is_file())
        self.assertTrue((self.home / ".agents/skills/workstation-secrets-pki/SKILL.md").is_file())
        state_data = json.loads((self.home / ".ai-guardrails/state.json").read_text())
        self.assertEqual(["azure", "secrets-pki", "sensitive-output"], state_data["products"]["codex"]["installed_packs"])
        runtime = self.home / ".ai-guardrails/runtime" / state_data["products"]["codex"]["runtime_digest"]
        command = json.loads((runtime / "command-policy.json").read_text())
        self.assertIn("azure-sensitive-credential-read", {rule["id"] for rule in command["rules"]})

    def test_unmanaged_pack_skill_is_preserved(self) -> None:
        collision = self.home / ".agents/skills/workstation-kubernetes"
        collision.mkdir(parents=True)
        (collision / "mine.txt").write_text("mine", encoding="utf-8")
        with self.assertRaisesRegex(GuardrailsError, "unmanaged skill collision"):
            with contextlib.redirect_stdout(io.StringIO()):
                installer.install(("codex",), self.home, force=False, dry_run=False, pack_ids=("kubernetes",))
        self.assertEqual("mine", (collision / "mine.txt").read_text())

    def test_ansible_pack_installs_portable_skill_and_dependencies(self) -> None:
        with contextlib.redirect_stdout(io.StringIO()):
            installer.install(("codex",), self.home, force=False, dry_run=False, pack_ids=("ansible",))
        self.assertTrue((self.home / ".agents/skills/workstation-ansible/SKILL.md").is_file())
        state_data = json.loads((self.home / ".ai-guardrails/state.json").read_text())
        self.assertEqual(
            ["ansible", "sensitive-output"],
            state_data["products"]["codex"]["installed_packs"],
        )


if __name__ == "__main__":
    unittest.main()
