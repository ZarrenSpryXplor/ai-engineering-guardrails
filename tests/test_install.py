from __future__ import annotations

import contextlib
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from ai_engineering_guardrails import build, install as installer, packs, state
from ai_engineering_guardrails.util import PRODUCTS, ROOT, GuardrailsError, home_path


class InstallTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        build.build()

    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.home = Path(self.temporary.name).resolve()

    def install(self, products: tuple[str, ...] = PRODUCTS, **kwargs: object) -> str:
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            installer.install(
                products,
                self.home,
                force=bool(kwargs.pop("force", False)),
                dry_run=bool(kwargs.pop("dry_run", False)),
                **kwargs,
            )
        return output.getvalue()

    def uninstall(self, products: tuple[str, ...] = PRODUCTS, **kwargs: object) -> str:
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            installer.uninstall(
                products,
                self.home,
                force=bool(kwargs.get("force", False)),
                dry_run=bool(kwargs.get("dry_run", False)),
            )
        return output.getvalue()

    def read_state(self) -> dict[str, object]:
        return json.loads((self.home / state.STATE_RELATIVE).read_text(encoding="utf-8"))

    def test_fresh_all_product_install_uses_immutable_runtime(self) -> None:
        self.install()
        self.assertTrue((self.home / ".codex/AGENTS.md").is_file())
        self.assertTrue((self.home / ".codex/hooks.json").is_file())
        self.assertTrue((self.home / ".claude/settings.json").is_file())
        self.assertTrue((self.home / ".cursor/hooks.json").is_file())
        self.assertTrue((self.home / ".agents/skills/workstation-safe-change/SKILL.md").is_file())
        self.assertTrue((self.home / ".claude/skills/workstation-safe-change/SKILL.md").is_file())
        data = self.read_state()
        self.assertEqual(set(PRODUCTS), set(data["products"]))
        self.assertRegex(data["policy_digest"], r"^[0-9a-f]{64}$")
        # Visual Studio and JetBrains deliberately have no managed deterministic
        # hook, so only hook-capable adapters own an immutable runtime.
        for product in ("codex", "claude", "cursor"):
            digest = data["products"][product]["runtime_digest"]
            runtime = self.home / ".ai-guardrails/runtime" / digest
            self.assertEqual(
                {"hook_runtime.py", "command-policy.json", "structured-tool-policy.json", "redaction-policy.json", "metadata.json"},
                {path.name for path in runtime.iterdir()},
            )

    def test_runtime_metadata_names_exact_managed_skill_and_agent_paths(self) -> None:
        self.install(("codex",), routing_profile="balanced")
        data = self.read_state()
        digest = data["products"]["codex"]["runtime_digest"]
        runtime = self.home / ".ai-guardrails/runtime" / digest
        metadata = json.loads((runtime / "metadata.json").read_text(encoding="utf-8"))
        managed = set(metadata["managed_paths"])
        self.assertEqual(str(self.home / ".ai-guardrails/state.json"), metadata["state_path"])
        self.assertEqual(str(self.home / ".ai-guardrails/targets.json"), metadata["targets_path"])
        self.assertIn(str(self.home / ".agents/skills/workstation-safe-change"), managed)
        self.assertIn(str(self.home / ".codex/agents/workstation_explorer.toml"), managed)
        self.assertNotIn(str(self.home / ".agents/skills"), managed)
        self.assertNotIn(str(self.home / ".codex/agents"), managed)

    def test_effective_configuration_summarises_installed_policy(self) -> None:
        self.install(("codex",), pack_ids=("kubernetes",))
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            report = installer.effective_configuration(("codex",), self.home)
        effective = report["products"]["codex"]["effective_policy"]
        self.assertRegex(effective["digest"], r"^[0-9a-f]{64}$")
        self.assertGreater(effective["command_rules"], 0)
        self.assertGreater(effective["structured_tool_rules"], 0)
        self.assertGreater(effective["rollout_modes"]["deny"], 0)

    def test_installed_runtime_runs_without_repository_imports(self) -> None:
        self.install(("codex",))
        data = self.read_state()
        runtime = self.home / ".ai-guardrails/runtime" / data["products"]["codex"]["runtime_digest"]
        source = (runtime / "hook_runtime.py").read_text(encoding="utf-8")
        self.assertNotIn(str(ROOT), source)
        result = subprocess.run(
            [
                sys.executable,
                str(runtime / "hook_runtime.py"),
                "--product", "codex",
                "--policy", str(runtime / "command-policy.json"),
                "--structured-policy", str(runtime / "structured-tool-policy.json"),
                "--metadata", str(runtime / "metadata.json"),
            ],
            cwd=self.home,
            input=json.dumps({"hook_event_name":"PreToolUse","tool_name":"Bash","tool_input":{"command":"git reset --hard"}}),
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual("deny", json.loads(result.stdout)["hookSpecificOutput"]["permissionDecision"])

    def test_existing_runtime_rejects_unexpected_nested_content(self) -> None:
        self.install(("codex",))
        data = self.read_state()
        runtime = self.home / ".ai-guardrails/runtime" / data["products"]["codex"]["runtime_digest"]
        unexpected = runtime / "unexpected"
        unexpected.mkdir()
        (unexpected / "payload.txt").write_text("synthetic\n", encoding="utf-8")
        with self.assertRaisesRegex(GuardrailsError, "immutable runtime digest collision"):
            self.install(("codex",), force=True)

    def test_hook_configuration_uses_absolute_python_and_not_clone(self) -> None:
        self.install(("codex",))
        hook = json.loads((self.home / ".codex/hooks.json").read_text())
        command = hook["hooks"]["PreToolUse"][0]["hooks"][0]["command"]
        self.assertIn(str(Path(sys.executable).resolve()), command)
        self.assertIn(str(self.home / ".ai-guardrails/runtime"), command)
        self.assertNotIn(str(ROOT), command)

    def test_managed_hook_recognition_supports_quoted_paths(self) -> None:
        groups = (
            {"command": "'/Users/Example/Home With Spaces/runtime/hook_runtime.py' --product cursor"},
            {
                "hooks": [
                    {
                        "command": (
                            '"C:\\Program Files\\Python311\\python.exe" '
                            '"C:\\Users\\Example User\\runtime\\hook_runtime.py" --product claude'
                        )
                    }
                ]
            },
        )
        self.assertTrue(installer._is_managed_hook(groups[0], "cursor"))
        self.assertTrue(installer._is_managed_hook(groups[1], "claude"))
        self.assertFalse(installer._is_managed_hook(groups[1], "codex"))

    def test_home_path_with_spaces_remains_idempotent_and_uninstallable(self) -> None:
        spaced_home = self.home / "home with spaces"
        spaced_home.mkdir()
        with contextlib.redirect_stdout(io.StringIO()):
            installer.install(("codex",), spaced_home, force=False, dry_run=False)
            installer.install(("codex",), spaced_home, force=False, dry_run=False)
        hook = json.loads((spaced_home / ".codex/hooks.json").read_text(encoding="utf-8"))
        self.assertEqual(1, len(installer._managed_hook_groups(hook, "codex")))
        with contextlib.redirect_stdout(io.StringIO()):
            installer.uninstall(("codex",), spaced_home, force=False, dry_run=False)
        self.assertFalse((spaced_home / ".codex/hooks.json").exists())

    def test_preexisting_codex_content_is_preserved_and_idempotent(self) -> None:
        target = self.home / ".codex/AGENTS.md"
        target.parent.mkdir(parents=True)
        target.write_text("# Personal instructions\n\nKeep this text.\n", encoding="utf-8")
        self.install(("codex",))
        self.install(("codex",))
        text = target.read_text(encoding="utf-8")
        self.assertIn("Keep this text.", text)
        self.assertEqual(1, text.count(installer.BEGIN_MARKER))

    def test_preexisting_empty_codex_agents_survives_uninstall(self) -> None:
        target = self.home / ".codex/AGENTS.md"
        target.parent.mkdir(parents=True)
        target.write_text("", encoding="utf-8")
        self.install(("codex",))
        self.uninstall(("codex",))
        self.assertTrue(target.is_file())
        self.assertEqual("", target.read_text(encoding="utf-8"))

    def test_nonempty_override_precedence(self) -> None:
        root = self.home / ".codex"
        root.mkdir()
        (root / "AGENTS.md").write_text("standard\n", encoding="utf-8")
        override = root / "AGENTS.override.md"
        override.write_text("override\n", encoding="utf-8")
        self.install(("codex",))
        self.assertIn(installer.BEGIN_MARKER, override.read_text())
        self.assertEqual("standard\n", (root / "AGENTS.md").read_text())

    def test_empty_override_does_not_suppress_nonempty_agents(self) -> None:
        root = self.home / ".codex"
        root.mkdir()
        normal = root / "AGENTS.md"
        normal.write_text("standard\n", encoding="utf-8")
        override = root / "AGENTS.override.md"
        override.write_text("", encoding="utf-8")
        self.install(("codex",))
        self.assertIn(installer.BEGIN_MARKER, normal.read_text())
        self.assertEqual("", override.read_text())

    def test_codex_home_inside_selected_home_is_honoured(self) -> None:
        custom = self.home / "custom-codex"
        with mock.patch.dict(os.environ, {"CODEX_HOME": str(custom)}):
            self.install(("codex",))
            report = installer.status(("codex",), self.home)
        self.assertTrue((custom / "AGENTS.md").is_file())
        self.assertTrue((custom / "hooks.json").is_file())
        self.assertTrue((custom / "rules/workstation-guardrails.rules").is_file())
        self.assertFalse((self.home / ".codex").exists())
        self.assertEqual(str(custom / "AGENTS.md"), report["products"]["codex"]["effective_global_instruction_file"])
        with contextlib.redirect_stdout(io.StringIO()):
            stale = installer.status(("codex",), self.home)
        self.assertEqual("stale", stale["products"]["codex"]["state"])
        self.uninstall(("codex",))
        self.assertFalse((custom / "AGENTS.md").exists())
        self.assertFalse((custom / "hooks.json").exists())
        self.assertFalse((custom / "rules/workstation-guardrails.rules").exists())

    def test_codex_home_outside_selected_home_is_rejected(self) -> None:
        external = Path(self.temporary.name).parent / f"{Path(self.temporary.name).name}-external-codex"
        with mock.patch.dict(os.environ, {"CODEX_HOME": str(external)}):
            with self.assertRaisesRegex(GuardrailsError, "CODEX_HOME is outside the selected home"):
                self.install(("codex",))
        self.assertFalse((self.home / ".ai-guardrails").exists())
        self.assertFalse(external.exists())

    def test_codex_effective_file_change_preserves_old_user_content(self) -> None:
        root = self.home / ".codex"
        root.mkdir()
        normal = root / "AGENTS.md"
        normal.write_text("personal instructions\n", encoding="utf-8")
        self.install(("codex",))
        override = root / "AGENTS.override.md"
        override.write_text("override instructions\n", encoding="utf-8")
        with contextlib.redirect_stdout(io.StringIO()):
            installer.update(("codex",), self.home, force=False, dry_run=False)
        self.assertEqual("personal instructions\n", normal.read_text(encoding="utf-8"))
        self.assertIn("override instructions", override.read_text(encoding="utf-8"))
        self.assertIn(installer.BEGIN_MARKER, override.read_text(encoding="utf-8"))

    def test_claude_settings_preserve_permissions_keys_and_hooks(self) -> None:
        target = self.home / ".claude/settings.json"
        target.parent.mkdir(parents=True)
        existing = {"matcher":"Write","hooks":[{"type":"command","command":"python existing.py"}]}
        target.write_text(json.dumps({"theme":"dark","permissions":{"deny":["Read(.env)"]},"hooks":{"PreToolUse":[existing]}}))
        self.install(("claude",))
        self.install(("claude",))
        data = json.loads(target.read_text())
        self.assertEqual("dark", data["theme"])
        self.assertEqual({"deny":["Read(.env)"]}, data["permissions"])
        self.assertIn(existing, data["hooks"]["PreToolUse"])
        self.assertEqual(1, len(installer._managed_hook_groups(data, "claude")))

    def test_malformed_hook_configuration_fails_before_runtime_install(self) -> None:
        target = self.home / ".claude/settings.json"
        target.parent.mkdir(parents=True)
        target.write_text("{malformed\n", encoding="utf-8")
        with self.assertRaisesRegex(GuardrailsError, "cannot parse JSON"):
            self.install(("claude",), force=True)
        self.assertEqual("{malformed\n", target.read_text(encoding="utf-8"))
        self.assertFalse((self.home / ".ai-guardrails").exists())

    def test_unmanaged_guardrail_markers_require_force_and_backup(self) -> None:
        agents = self.home / ".codex/AGENTS.md"
        agents.parent.mkdir(parents=True)
        agents.write_text(
            f"personal\n\n{installer.BEGIN_MARKER}\nunowned\n{installer.END_MARKER}\n",
            encoding="utf-8",
        )
        with self.assertRaisesRegex(GuardrailsError, "unmanaged guardrail block collision"):
            self.install(("codex",))
        self.assertFalse((self.home / ".ai-guardrails").exists())
        self.install(("codex",), force=True)
        record = next(
            item
            for item in self.read_state()["products"]["codex"]["managed"]
            if item["kind"] == "managed-block"
        )
        self.assertTrue((self.home / record["backup"]).is_file())

    def test_codex_and_cursor_hooks_preserve_unrelated_entries(self) -> None:
        codex = self.home / ".codex/hooks.json"
        cursor = self.home / ".cursor/hooks.json"
        codex.parent.mkdir(parents=True)
        cursor.parent.mkdir(parents=True)
        codex.write_text(json.dumps({"description":"mine","hooks":{"SessionStart":[{"hooks":[]}]}}))
        cursor.write_text(json.dumps({"version":1,"hooks":{"stop":[{"command":"audit"}]}}))
        self.install(("codex", "cursor"))
        self.install(("codex", "cursor"))
        codex_data = json.loads(codex.read_text())
        cursor_data = json.loads(cursor.read_text())
        self.assertEqual("mine", codex_data["description"])
        self.assertIn("SessionStart", codex_data["hooks"])
        self.assertIn("stop", cursor_data["hooks"])
        self.assertEqual(1, len(installer._managed_hook_groups(codex_data, "codex")))
        self.assertEqual(1, len(installer._managed_hook_groups(cursor_data, "cursor")))

    def test_backup_created_before_existing_configuration_mutation(self) -> None:
        target = self.home / ".claude/settings.json"
        target.parent.mkdir(parents=True)
        target.write_text(json.dumps({"theme":"dark"}))
        self.install(("claude",))
        record = next(item for item in self.read_state()["products"]["claude"]["managed"] if item["path"] == ".claude/settings.json")
        self.assertTrue((self.home / record["backup"]).is_file())

    def test_dry_run_changes_nothing(self) -> None:
        output = self.install(dry_run=True, all_packs=True, routing_profile="balanced")
        self.assertIn("dry run complete", output)
        self.assertEqual([], list(self.home.iterdir()))

    def test_product_specific_install_affects_only_selected_product(self) -> None:
        self.install(("claude",))
        self.assertTrue((self.home / ".claude").exists())
        self.assertFalse((self.home / ".codex").exists())
        self.assertFalse((self.home / ".cursor").exists())
        self.assertFalse((self.home / ".agents").exists())

    def test_all_packs_are_progressive_not_global(self) -> None:
        self.install(("codex",), all_packs=True)
        agents = (self.home / ".codex/AGENTS.md").read_text(encoding="utf-8")
        self.assertNotIn("# Azure capability policy", agents)
        self.assertTrue((self.home / ".agents/skills/workstation-azure/SKILL.md").is_file())
        self.assertTrue((self.home / ".agents/skills/workstation-containers-oci/SKILL.md").is_file())
        installed = self.read_state()["products"]["codex"]
        self.assertEqual(len(packs.load_packs()), len(installed["installed_packs"]))
        runtime = self.home / ".ai-guardrails/runtime" / installed["runtime_digest"]
        result = subprocess.run(
            [
                sys.executable,
                str(runtime / "hook_runtime.py"),
                "--product", "codex",
                "--policy", str(runtime / "command-policy.json"),
                "--structured-policy", str(runtime / "structured-tool-policy.json"),
                "--metadata", str(runtime / "metadata.json"),
            ],
            input=json.dumps(
                {
                    "hook_event_name": "PreToolUse",
                    "tool_name": "mcp__spacelift__mutate",
                    "tool_input": {"operation": "synthetic"},
                }
            ),
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual("deny", json.loads(result.stdout)["hookSpecificOutput"]["permissionDecision"])

    def test_unmanaged_skill_collision_refused_then_force_backed_up(self) -> None:
        collision = self.home / ".agents/skills/workstation-safe-change"
        collision.mkdir(parents=True)
        marker = collision / "mine.txt"
        marker.write_text("unmanaged", encoding="utf-8")
        with self.assertRaisesRegex(GuardrailsError, "unmanaged skill collision"):
            self.install(("codex",))
        self.assertEqual("unmanaged", marker.read_text())
        self.install(("codex",), force=True)
        record = next(item for item in self.read_state()["products"]["codex"]["managed"] if item["path"].endswith("workstation-safe-change"))
        self.assertTrue((self.home / record["backup"]).is_dir())

    def test_forced_skill_backup_preserves_symlinks_without_copying_targets(self) -> None:
        external = Path(self.temporary.name).parent / f"{Path(self.temporary.name).name}-external-skill-data"
        external.write_text("synthetic external content\n", encoding="utf-8")
        self.addCleanup(external.unlink, missing_ok=True)
        collision = self.home / ".agents/skills/workstation-safe-change"
        collision.mkdir(parents=True)
        (collision / "external-link").symlink_to(external)
        self.install(("codex",), force=True)
        record = next(
            item
            for item in self.read_state()["products"]["codex"]["managed"]
            if item["path"].endswith("skills/workstation-safe-change")
        )
        backup_link = self.home / record["backup"] / "external-link"
        self.assertTrue(backup_link.is_symlink())
        self.assertEqual("synthetic external content\n", external.read_text(encoding="utf-8"))

    def test_unmanaged_agent_collision_refused_then_force_backed_up(self) -> None:
        target = self.home / ".codex/agents/workstation_explorer.toml"
        target.parent.mkdir(parents=True)
        target.write_text("user_owned = true\n", encoding="utf-8")
        with self.assertRaisesRegex(GuardrailsError, "unmanaged agent collision"):
            self.install(("codex",), routing_profile="balanced")
        self.install(("codex",), routing_profile="balanced", force=True)
        record = next(item for item in self.read_state()["products"]["codex"]["managed"] if item["path"].endswith("workstation_explorer.toml"))
        self.assertTrue((self.home / record["backup"]).is_file())

    def test_modified_managed_content_fails_preflight_before_any_mutation(self) -> None:
        self.install(("codex",), routing_profile="balanced")
        agent = self.home / ".codex/agents/workstation_explorer.toml"
        agent.write_text(agent.read_text(encoding="utf-8") + "# user change\n", encoding="utf-8")
        hook_before = (self.home / ".codex/hooks.json").read_bytes()
        state_before = (self.home / state.STATE_RELATIVE).read_bytes()
        runtimes_before = sorted((self.home / ".ai-guardrails/runtime").iterdir())
        with self.assertRaisesRegex(GuardrailsError, "locally modified managed path"):
            self.install(("codex",), routing_profile="none")
        self.assertEqual(hook_before, (self.home / ".codex/hooks.json").read_bytes())
        self.assertEqual(state_before, (self.home / state.STATE_RELATIVE).read_bytes())
        self.assertEqual(runtimes_before, sorted((self.home / ".ai-guardrails/runtime").iterdir()))
        self.assertIn("# user change", agent.read_text(encoding="utf-8"))

    def test_multi_product_update_preflights_every_product_before_mutation(self) -> None:
        self.install(("codex", "claude"), routing_profile="balanced")
        claude_rule = self.home / ".claude/rules/workstation-guardrails-00-operating-principles.md"
        claude_rule.write_text(claude_rule.read_text(encoding="utf-8") + "user change\n", encoding="utf-8")
        codex_hook_before = (self.home / ".codex/hooks.json").read_bytes()
        state_before = (self.home / state.STATE_RELATIVE).read_bytes()
        runtimes_before = sorted((self.home / ".ai-guardrails/runtime").iterdir())
        with self.assertRaisesRegex(GuardrailsError, "locally modified managed path"):
            with contextlib.redirect_stdout(io.StringIO()):
                installer.update(("codex", "claude"), self.home, force=False, dry_run=False)
        self.assertEqual(codex_hook_before, (self.home / ".codex/hooks.json").read_bytes())
        self.assertEqual(state_before, (self.home / state.STATE_RELATIVE).read_bytes())
        self.assertEqual(runtimes_before, sorted((self.home / ".ai-guardrails/runtime").iterdir()))

    def test_symlinked_configuration_is_rejected_before_runtime_install(self) -> None:
        external = Path(self.temporary.name).parent / f"{Path(self.temporary.name).name}-external-settings.json"
        external.write_text('{"secret":"synthetic-do-not-read"}\n', encoding="utf-8")
        self.addCleanup(external.unlink, missing_ok=True)
        target = self.home / ".claude/settings.json"
        target.parent.mkdir(parents=True)
        for force in (False, True):
            with self.subTest(force=force):
                target.symlink_to(external)
                with self.assertRaisesRegex(GuardrailsError, "outside selected home|symbolic link"):
                    self.install(("claude",), force=force)
                self.assertEqual('{"secret":"synthetic-do-not-read"}\n', external.read_text(encoding="utf-8"))
                self.assertFalse((self.home / ".ai-guardrails").exists())
                target.unlink()

    def test_uninstall_removes_only_managed_content(self) -> None:
        agents = self.home / ".codex/AGENTS.md"
        agents.parent.mkdir(parents=True)
        agents.write_text("personal before\n", encoding="utf-8")
        settings = self.home / ".claude/settings.json"
        settings.parent.mkdir(parents=True)
        settings.write_text(json.dumps({"theme":"dark"}), encoding="utf-8")
        unmanaged = self.home / ".cursor/agents/mine.md"
        unmanaged.parent.mkdir(parents=True)
        unmanaged.write_text("mine\n", encoding="utf-8")
        self.install(routing_profile="balanced")
        self.uninstall()
        self.assertEqual("personal before\n", agents.read_text())
        self.assertEqual({"theme":"dark"}, json.loads(settings.read_text()))
        self.assertTrue(unmanaged.is_file())
        self.assertFalse((self.home / ".codex/rules/workstation-guardrails.rules").exists())
        self.assertTrue((self.home / ".codex").is_dir())
        self.assertTrue((self.home / ".ai-guardrails").is_dir())

    def test_update_then_uninstall_removes_installer_created_configurations(self) -> None:
        self.install()
        with contextlib.redirect_stdout(io.StringIO()):
            installer.update(PRODUCTS, self.home, force=False, dry_run=False)
        self.uninstall()
        for relative in (
            ".codex/AGENTS.md",
            ".codex/hooks.json",
            ".claude/settings.json",
            ".cursor/hooks.json",
        ):
            with self.subTest(path=relative):
                self.assertFalse((self.home / relative).exists())
        data = self.read_state()
        self.assertEqual({}, data["products"])
        self.assertEqual("", data["policy_digest"])
        self.assertIsNone(data["runtime_digest"])
        self.assertIsNone(data["runtime_path"])

    def test_created_cursor_hook_with_unrelated_setting_survives_uninstall(self) -> None:
        self.install(("cursor",))
        target = self.home / ".cursor/hooks.json"
        data = json.loads(target.read_text(encoding="utf-8"))
        data["unrelated"] = {"theme": "dark"}
        target.write_text(json.dumps(data), encoding="utf-8")
        self.uninstall(("cursor",))
        self.assertEqual(
            {"unrelated": {"theme": "dark"}, "version": 1},
            json.loads(target.read_text(encoding="utf-8")),
        )

    def test_uninstall_preserves_modified_managed_file_unless_forced(self) -> None:
        self.install(("codex",))
        target = self.home / ".codex/rules/workstation-guardrails.rules"
        target.write_text(target.read_text() + "# local change\n", encoding="utf-8")
        output = self.uninstall(("codex",))
        self.assertTrue(target.is_file())
        self.assertIn("retained modified managed path", output)
        self.uninstall(("codex",), force=True)
        self.assertFalse(target.exists())
        backups = list((self.home / ".ai-guardrails/backups").glob("*.bak"))
        self.assertTrue(any("# local change" in path.read_text(encoding="utf-8") for path in backups))

    def test_uninstall_retains_runtime_needed_by_modified_hook(self) -> None:
        self.install(("codex",))
        data = self.read_state()
        runtime = self.home / ".ai-guardrails/runtime" / data["products"]["codex"]["runtime_digest"]
        hook = self.home / ".codex/hooks.json"
        settings = json.loads(hook.read_text(encoding="utf-8"))
        settings["hooks"]["PreToolUse"][0]["local_note"] = "user change"
        hook.write_text(json.dumps(settings), encoding="utf-8")
        self.uninstall(("codex",))
        retained = self.read_state()["products"]["codex"]
        self.assertTrue(retained["partial_uninstall"])
        self.assertTrue(hook.is_file())
        self.assertTrue(runtime.is_dir())
        self.assertEqual(
            {"json-hook", "runtime-directory"},
            {item["kind"] for item in retained["managed"]},
        )
        self.uninstall(("codex",), force=True)
        self.assertFalse(hook.exists())
        self.assertFalse(runtime.exists())

    def test_uninstall_retains_malformed_hook_configuration_unless_forced(self) -> None:
        self.install(("claude",))
        settings = self.home / ".claude/settings.json"
        settings.write_text("{malformed\n", encoding="utf-8")
        output = self.uninstall(("claude",))
        self.assertIn("retained modified hook configuration", output)
        self.assertEqual("{malformed\n", settings.read_text(encoding="utf-8"))
        retained = self.read_state()["products"]["claude"]
        self.assertEqual(
            {"json-hook", "runtime-directory"},
            {item["kind"] for item in retained["managed"]},
        )
        self.uninstall(("claude",), force=True)
        self.assertFalse(settings.exists())
        backups = list((self.home / ".ai-guardrails/backups").glob("*.bak"))
        self.assertTrue(any(path.read_text(encoding="utf-8") == "{malformed\n" for path in backups))

    def test_status_and_uninstall_treat_non_utf8_managed_block_as_modified(self) -> None:
        self.install(("codex",))
        agents = self.home / ".codex/AGENTS.md"
        agents.write_bytes(b"\xff\xfeuser-content")
        with contextlib.redirect_stdout(io.StringIO()):
            report = installer.status(("codex",), self.home)
        self.assertEqual("modified", report["products"]["codex"]["state"])
        output = self.uninstall(("codex",))
        self.assertIn("retained modified managed block", output)
        self.assertEqual(b"\xff\xfeuser-content", agents.read_bytes())
        self.uninstall(("codex",), force=True)
        self.assertFalse(agents.exists())
        backups = list((self.home / ".ai-guardrails/backups").glob("*.bak"))
        self.assertTrue(any(path.read_bytes() == b"\xff\xfeuser-content" for path in backups))

    def test_all_product_uninstall_dry_run_lists_shared_paths_once(self) -> None:
        self.install(("codex", "cursor"))
        output = self.uninstall(("codex", "cursor"), dry_run=True)
        shared = str(self.home / ".agents/skills/workstation-safe-change")
        self.assertEqual(1, output.count(shared))
        self.assertTrue((self.home / ".ai-guardrails/state.json").is_file())

    def test_product_uninstall_preserves_shared_skill_owned_by_other_product(self) -> None:
        self.install(("codex", "cursor"))
        shared = self.home / ".agents/skills/workstation-safe-change"
        self.uninstall(("codex",))
        self.assertTrue(shared.is_dir())
        self.assertNotIn("codex", self.read_state()["products"])
        self.assertIn("cursor", self.read_state()["products"])
        self.uninstall(("cursor",))
        self.assertFalse(shared.exists())

    def test_multi_product_pack_change_removes_no_longer_owned_shared_content(self) -> None:
        self.install(("codex", "cursor"), pack_ids=("azure",))
        old_skill = self.home / ".agents/skills/workstation-azure"
        self.assertTrue(old_skill.is_dir())
        self.install(("codex", "cursor"), pack_ids=("java",))
        self.assertFalse(old_skill.exists())
        data = self.read_state()
        self.assertNotIn("azure", data["installed_packs"])
        self.assertIn("java", data["installed_packs"])

    def test_status_has_no_manual_or_hook_activation_step_after_uninstall(self) -> None:
        self.install(("codex", "cursor"))
        self.uninstall(("codex", "cursor"))
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            report = installer.status(("codex", "cursor"), self.home)
        self.assertEqual("not-applicable", report["products"]["cursor"]["manual_user_rules"])
        self.assertEqual("not installed", report["products"]["codex"]["hook_trust"])
        self.assertNotIn("manual step outstanding", output.getvalue())

    def test_status_reports_modified_stale_and_cursor_manual_step(self) -> None:
        self.install(("codex", "cursor"))
        target = self.home / ".codex/rules/workstation-guardrails.rules"
        target.write_text(target.read_text() + "# local\n", encoding="utf-8")
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            report = installer.status(("codex", "cursor"), self.home)
        self.assertEqual("modified", report["products"]["codex"]["state"])
        self.assertEqual("outstanding", report["products"]["cursor"]["manual_user_rules"])
        self.assertIn("Cursor Settings / Customize / Rules / User Rules", output.getvalue())

        data = self.read_state()
        target.write_bytes((ROOT / "dist/codex/rules/workstation-guardrails.rules").read_bytes())
        data["products"]["codex"]["source_digest"] = "0" * 64
        state.save_state(self.home, data, dry_run=False)
        with contextlib.redirect_stdout(io.StringIO()):
            stale = installer.status(("codex",), self.home)
        self.assertEqual("stale", stale["products"]["codex"]["state"])

    def test_doctor_reports_malformed_state_and_target_mapping(self) -> None:
        guardrails_root = self.home / ".ai-guardrails"
        guardrails_root.mkdir()
        (guardrails_root / "state.json").write_text("{malformed\n", encoding="utf-8")
        (guardrails_root / "targets.json").write_text(
            json.dumps({"schema_version": 1, "classifications": {"azure_subscriptions": {"synthetic": "prod"}}}),
            encoding="utf-8",
        )
        with contextlib.redirect_stdout(io.StringIO()):
            report = installer.doctor(("codex",), self.home)
        checks = {item["id"]: item["outcome"] for item in report["checks"]}
        self.assertEqual("fail", checks["installation-state"])
        self.assertEqual("fail", checks["target-mapping"])

    def test_doctor_reports_local_mcp_inventory_counts_without_tool_names(self) -> None:
        guardrails_root = self.home / ".ai-guardrails"
        guardrails_root.mkdir()
        (guardrails_root / "trusted-components.json").write_text(
            json.dumps(
                {
                    "components": [
                        {
                            "id": "synthetic-read-mcp",
                            "kind": "mcp-server",
                            "source": "https://example.invalid/mcp",
                            "version": "1.0.0",
                            "digest": None,
                            "allowed_tools": ["query"],
                            "denied_tools": ["mutate"],
                            "observed_tools": ["query"],
                            "executable_files": [],
                            "credential_class": "read-only",
                            "expected_network_destinations": ["example.invalid"],
                        }
                    ]
                }
            ),
            encoding="utf-8",
        )
        with contextlib.redirect_stdout(io.StringIO()):
            report = installer.doctor(("codex",), self.home)
        checks = {item["id"]: item for item in report["checks"]}
        self.assertEqual("pass", checks["mcp-tool-inventory"]["outcome"])
        self.assertIn("1 declared MCP server(s); 1 observed tool name(s)", checks["mcp-tool-inventory"]["detail"])
        self.assertNotIn("query", checks["mcp-tool-inventory"]["detail"])

    def test_status_does_not_claim_invalid_target_mapping_is_configured(self) -> None:
        guardrails_root = self.home / ".ai-guardrails"
        guardrails_root.mkdir()
        (guardrails_root / "targets.json").write_text(
            json.dumps({"schema_version": 1, "classifications": {"kubernetes_contexts": {"synthetic": "prod"}}}),
            encoding="utf-8",
        )
        with contextlib.redirect_stdout(io.StringIO()):
            report = installer.status(("codex",), self.home)
        self.assertIn("invalid", report["target_mapping"])
        self.assertIn("protected", report["target_mapping"])

    def test_update_is_idempotent_and_preserves_product_profiles(self) -> None:
        self.install(
            ("codex",),
            pack_ids=("java",),
            routing_profile="economy",
            safety_profile="infrastructure-strict",
            trust_mode="untrusted-workspace",
        )
        self.install(
            ("claude",),
            pack_ids=("kubernetes",),
            routing_profile="quality",
            safety_profile="development",
            trust_mode="trusted-workspace",
        )
        with contextlib.redirect_stdout(io.StringIO()):
            installer.update(("codex", "claude"), self.home, force=False, dry_run=False)
        data = self.read_state()
        self.assertEqual("economy", data["products"]["codex"]["routing_profile"])
        self.assertEqual("quality", data["products"]["claude"]["routing_profile"])
        self.assertIn("java", data["products"]["codex"]["installed_packs"])
        self.assertIn("kubernetes", data["products"]["claude"]["installed_packs"])
        self.assertEqual("per-product", data["routing_profile"])
        self.assertEqual("per-product", data["safety_profile"])
        self.assertEqual("per-product", data["trust_mode"])

        with contextlib.redirect_stdout(io.StringIO()):
            report = installer.status(("codex", "claude"), self.home)
        self.assertEqual("economy", report["products"]["codex"]["routing_profile"])
        self.assertEqual("quality", report["products"]["claude"]["routing_profile"])
        self.assertEqual("infrastructure-strict", report["products"]["codex"]["safety_profile"])
        self.assertEqual("development", report["products"]["claude"]["safety_profile"])

    def test_install_omission_preserves_existing_optional_configuration(self) -> None:
        self.install(
            ("codex",),
            pack_ids=("kubernetes",),
            routing_profile="quality",
            safety_profile="infrastructure-strict",
            trust_mode="untrusted-workspace",
            model_overrides={"codex": {"deep": "gpt-5.6-sol"}},
        )
        self.install(("codex",))
        data = self.read_state()["products"]["codex"]
        self.assertEqual("quality", data["routing_profile"])
        self.assertEqual("infrastructure-strict", data["safety_profile"])
        self.assertEqual("untrusted-workspace", data["trust_mode"])
        self.assertEqual({"deep": "gpt-5.6-sol"}, data["model_overrides"])
        self.assertIn("kubernetes", data["installed_packs"])
        self.assertTrue((self.home / ".codex/agents/workstation_explorer.toml").is_file())
        self.assertTrue((self.home / ".agents/skills/workstation-kubernetes/SKILL.md").is_file())

    def test_absolute_windows_path_is_rejected_outside_selected_home(self) -> None:
        with self.assertRaisesRegex(GuardrailsError, "outside selected home"):
            home_path(self.home, r"C:\\Users\\Example\\.codex")


if __name__ == "__main__":
    unittest.main()
