from __future__ import annotations

import contextlib
import io
import json
import os
import tempfile
import unittest
from pathlib import Path

from ai_engineering_guardrails import build, cli, install, policy, state
from ai_engineering_guardrails.util import GuardrailsError, json_bytes


class LocalPolicyOverlayTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.home = Path(self.temporary.name) / "home"

    def initialise(self) -> Path:
        return policy.initialise_local_overlay(self.home, force=False, dry_run=False)

    def write_overlay(self, value: dict[str, object]) -> Path:
        target = policy.local_overlay_path(self.home)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(json_bytes(value))
        return target

    @staticmethod
    def local_rule(identifier: str = "local-block-demo") -> dict[str, object]:
        return {
            "id": identifier,
            "description": "Block a synthetic destructive demonstration command.",
            "risk_category": "local_test",
            "operation_class": "destructive",
            "rollout_mode": "deny",
            "reason": "Blocked synthetic local destructive command.",
            "matching_strategy": {
                "type": "command_regex",
                "executables": ["demo"],
                "pattern": "^wipe$",
            },
            "must_match": ["demo wipe"],
            "must_not_match": ["demo inspect"],
        }

    def test_no_overlay_preserves_effective_baseline_and_init_is_safe(self) -> None:
        baseline = policy.load_enforcement_policy()
        effective = policy.validate_local_overlay(self.home)["policy"]
        self.assertEqual(baseline, effective)
        target = self.initialise()
        self.assertEqual(policy.empty_local_overlay(), json.loads(target.read_text(encoding="utf-8")))
        self.assertEqual({"behavioural_fragments": [], "strengthened_rule_modes": [], "additional_rules": []}, policy.local_policy_diff(self.home))
        with self.assertRaisesRegex(GuardrailsError, "already exists"):
            policy.initialise_local_overlay(self.home, force=False, dry_run=False)
        target.write_text('{"synthetic": true}\n', encoding="utf-8")
        policy.initialise_local_overlay(self.home, force=True, dry_run=False)
        self.assertTrue(list((self.home / ".ai-guardrails/backups").glob("*.bak")))

    def test_local_fragment_is_product_scoped_and_cannot_escape(self) -> None:
        self.initialise()
        fragment = policy.local_policy_root(self.home) / "fragments/local-extra.md"
        fragment.write_text("Use the repository formatter before reporting completion.\n", encoding="utf-8")
        self.write_overlay(
            {
                "schema_version": 1,
                "behavioural_fragments": [
                    {
                        "id": "local-extra",
                        "path": "fragments/local-extra.md",
                        "products": ["codex", "cursor"],
                        "description": "Local completion clarification.",
                    }
                ],
                "rule_modes": {},
                "additional_rules": [],
            }
        )
        artifacts = build.build_artifacts(("codex", "claude", "cursor"), home=self.home)
        self.assertIn(b"Use the repository formatter", artifacts[Path("dist/codex/AGENTS.md")])
        self.assertIn(b"Use the repository formatter", artifacts[Path("dist/cursor/user-rules.md")])
        self.assertNotIn(
            b"Use the repository formatter",
            b"".join(value for key, value in artifacts.items() if key.parent == Path("dist/claude/rules")),
        )
        data = json.loads(policy.local_overlay_path(self.home).read_text(encoding="utf-8"))
        data["behavioural_fragments"][0]["path"] = "../escape.md"
        self.write_overlay(data)
        with self.assertRaisesRegex(GuardrailsError, "must remain"):
            policy.validate_local_overlay(self.home)

    def test_local_fragment_rejects_symlink_empty_unknown_product_and_duplicate_id(self) -> None:
        self.initialise()
        fragments = policy.local_policy_root(self.home) / "fragments"
        empty = fragments / "empty.md"
        empty.write_text("\n", encoding="utf-8")
        overlay = policy.empty_local_overlay()
        overlay["behavioural_fragments"] = [
            {"id": "local-empty", "path": "fragments/empty.md", "products": ["codex"], "description": "empty"}
        ]
        self.write_overlay(overlay)
        with self.assertRaisesRegex(GuardrailsError, "empty"):
            policy.validate_local_overlay(self.home)
        if hasattr(os, "symlink"):
            target = fragments / "target.md"
            target.write_text("synthetic\n", encoding="utf-8")
            link = fragments / "linked.md"
            try:
                link.symlink_to(target)
            except OSError:
                self.skipTest("symbolic links are unavailable")
            overlay["behavioural_fragments"] = [
                {"id": "local-link", "path": "fragments/linked.md", "products": ["codex"], "description": "link"}
            ]
            self.write_overlay(overlay)
            with self.assertRaisesRegex(GuardrailsError, "unsafe|symbolic"):
                policy.validate_local_overlay(self.home)
        overlay["behavioural_fragments"] = [
            {"id": "local-one", "path": "fragments/empty.md", "products": ["unknown"], "description": "bad"},
            {"id": "local-one", "path": "fragments/empty.md", "products": ["codex"], "description": "duplicate"},
        ]
        self.write_overlay(overlay)
        with self.assertRaisesRegex(GuardrailsError, "unknown product"):
            policy.validate_local_overlay(self.home)

    def test_rule_modes_can_only_strengthen_existing_rules(self) -> None:
        self.initialise()
        self.write_overlay(
            {
                "schema_version": 1,
                "behavioural_fragments": [],
                "rule_modes": {"ansible-inventory-variable-output": "deny"},
                "additional_rules": [],
            }
        )
        effective = policy.validate_local_overlay(self.home)["policy"]
        rule = next(item for item in effective["rules"] if item["id"] == "ansible-inventory-variable-output")
        self.assertEqual("deny", rule["rollout_mode"])
        self.assertTrue(rule["local_mode_strengthening"])
        data = policy.empty_local_overlay()
        data["rule_modes"] = {"git-reset-hard": "warn"}
        self.write_overlay(data)
        with self.assertRaisesRegex(GuardrailsError, "cannot weaken"):
            policy.validate_local_overlay(self.home)
        data["rule_modes"] = {"not-a-rule": "deny"}
        self.write_overlay(data)
        with self.assertRaisesRegex(GuardrailsError, "unknown bundled"):
            policy.validate_local_overlay(self.home)

    def test_additional_rules_validate_examples_and_cannot_collide(self) -> None:
        self.initialise()
        data = policy.empty_local_overlay()
        data["additional_rules"] = [self.local_rule()]
        self.write_overlay(data)
        effective = policy.validate_local_overlay(self.home)["policy"]
        self.assertIn("local-block-demo", {rule["id"] for rule in effective["rules"]})
        data["additional_rules"] = [self.local_rule("git-reset-hard")]
        self.write_overlay(data)
        with self.assertRaisesRegex(GuardrailsError, "local-\* prefix|collides"):
            policy.validate_local_overlay(self.home)
        bad = self.local_rule()
        bad["matching_strategy"] = {"type": "not-implemented"}
        data["additional_rules"] = [bad]
        self.write_overlay(data)
        with self.assertRaisesRegex(GuardrailsError, "unknown matching strategy|unsupported matching strategy"):
            policy.validate_local_overlay(self.home)
        bad = self.local_rule()
        bad["must_not_match"] = ["demo wipe"]
        data["additional_rules"] = [bad]
        self.write_overlay(data)
        with self.assertRaises(GuardrailsError):
            policy.validate_local_overlay(self.home)

    def test_invalid_overlay_fails_before_install_and_apply_preserves_settings(self) -> None:
        self.initialise()
        self.write_overlay({"schema_version": 1, "behavioural_fragments": [], "rule_modes": {"not-a-rule": "deny"}, "additional_rules": []})
        with self.assertRaises(GuardrailsError):
            install.install(("codex",), self.home, force=False, dry_run=False)
        self.assertFalse((self.home / ".codex").exists())
        self.write_overlay(policy.empty_local_overlay())
        install.install(
            ("codex",),
            self.home,
            force=False,
            dry_run=False,
            pack_ids=("python",),
            routing_profile="none",
            safety_profile="infrastructure-observe",
            trust_mode="trusted-workspace",
        )
        before = state.load_state(self.home)
        data = policy.empty_local_overlay()
        data["additional_rules"] = [self.local_rule()]
        self.write_overlay(data)
        before_state = (self.home / ".ai-guardrails/state.json").read_bytes()
        install.update(("codex",), self.home, force=False, dry_run=True)
        self.assertEqual(before_state, (self.home / ".ai-guardrails/state.json").read_bytes())
        install.update(("codex",), self.home, force=False, dry_run=False)
        after = state.load_state(self.home)
        self.assertEqual(before["products"]["codex"]["installed_packs"], after["products"]["codex"]["installed_packs"])
        self.assertEqual(before["products"]["codex"]["routing_profile"], after["products"]["codex"]["routing_profile"])
        self.assertNotEqual(before["overlay_digest"], after["overlay_digest"])

    def test_overlay_change_is_stale_and_uninstall_keeps_user_policy(self) -> None:
        self.initialise()
        install.install(("codex",), self.home, force=False, dry_run=False, pack_ids=("python",))
        fragment = policy.local_policy_root(self.home) / "fragments/local-note.md"
        fragment.write_text("Use local checks.\n", encoding="utf-8")
        self.write_overlay(
            {
                "schema_version": 1,
                "behavioural_fragments": [
                    {"id": "local-note", "path": "fragments/local-note.md", "products": ["codex"], "description": "note"}
                ],
                "rule_modes": {},
                "additional_rules": [],
            }
        )
        with contextlib.redirect_stdout(io.StringIO()):
            report = install.status(("codex",), self.home)
        self.assertEqual("stale", report["products"]["codex"]["state"])
        install.uninstall(("codex",), self.home, force=False, dry_run=False)
        self.assertTrue(policy.local_overlay_path(self.home).is_file())
        self.assertTrue(fragment.is_file())

    def test_prepackaging_state_is_migrated_without_creating_a_second_installation(self) -> None:
        install.install(("codex",), self.home, force=False, dry_run=False, pack_ids=("python",))
        state_path = self.home / ".ai-guardrails/state.json"
        legacy = json.loads(state_path.read_text(encoding="utf-8"))
        legacy["format_version"] = 2
        legacy.pop("overlay_digest", None)
        state_path.write_bytes(json_bytes(legacy))
        with contextlib.redirect_stdout(io.StringIO()):
            legacy_report = install.status(("codex",), self.home)
        self.assertEqual("installed", legacy_report["products"]["codex"]["state"])
        self.assertIn("legacy", legacy_report["products"]["codex"]["state_format"])
        install.update(("codex",), self.home, force=False, dry_run=False)
        migrated = state.load_state(self.home)
        self.assertEqual(state.FORMAT_VERSION, migrated["format_version"])
        self.assertNotIn(state.LEGACY_FORMAT_KEY, migrated)
        self.assertEqual(["codex"], sorted(migrated["products"]))
        install.uninstall(("codex",), self.home, force=False, dry_run=False)
        self.assertFalse((self.home / ".codex/rules/workstation-guardrails.rules").exists())

    def test_policy_cli_list_show_validate_diff_and_apply(self) -> None:
        self.initialise()
        install.install(("codex",), self.home, force=False, dry_run=False, pack_ids=("python",))
        data = policy.empty_local_overlay()
        data["additional_rules"] = [self.local_rule()]
        self.write_overlay(data)
        for arguments, expected in (
            (["policy", "list", "--home", str(self.home)], "local-block-demo"),
            (["policy", "show", "local-block-demo", "--home", str(self.home)], "source: local"),
            (["policy", "validate", "--home", str(self.home)], "validation passed"),
            (["policy", "diff", "--home", str(self.home)], "local-block-demo"),
        ):
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                self.assertEqual(0, cli.main(arguments))
            self.assertIn(expected, output.getvalue())
        self.assertEqual(0, cli.main(["policy", "apply", "--home", str(self.home), "--dry-run"]))


if __name__ == "__main__":
    unittest.main()
