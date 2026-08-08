from __future__ import annotations

import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from ai_engineering_guardrails import build, cli, enforcement, install, policy
from ai_engineering_guardrails.util import PRODUCTS, GuardrailsError


class IdeAdapterTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        build.build(PRODUCTS)

    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.home = Path(self.temporary.name) / "home"
        self.home.mkdir()

    def install(self, products: tuple[str, ...], **kwargs: object) -> None:
        with contextlib.redirect_stdout(io.StringIO()):
            install.install(products, self.home, force=False, dry_run=False, **kwargs)

    def test_product_set_and_new_artifacts_are_complete(self) -> None:
        self.assertEqual(
            ("codex", "claude", "cursor", "vscode", "visualstudio", "jetbrains"),
            PRODUCTS,
        )
        artifacts = build.build_artifacts(PRODUCTS)
        expected = {
            Path("dist/vscode/instructions/workstation-guardrails.instructions.md"),
            Path("dist/vscode/hooks/workstation-guardrails.json"),
            Path("dist/visualstudio/copilot-instructions.md"),
            Path("dist/jetbrains/ai-assistant/chat-instructions.md"),
            Path("dist/jetbrains/ai-assistant/project-rules/workstation-guardrails.md"),
            Path("dist/jetbrains/copilot/global-copilot-instructions.md"),
        }
        self.assertTrue(expected.issubset(artifacts))
        vscode = artifacts[Path("dist/vscode/instructions/workstation-guardrails.instructions.md")].decode()
        self.assertTrue(vscode.startswith("---\n"))
        self.assertIn('applyTo: "**"', vscode)
        self.assertIn("GENERATED — DO NOT EDIT", vscode)
        for value in artifacts.values():
            self.assertTrue(value.endswith(b"\n"))
            self.assertFalse(value.endswith(b"\n\n"))

    def test_offline_product_detection_uses_bounded_executable_evidence(self) -> None:
        def which(name: str) -> str | None:
            return f"/synthetic/{name}" if name in {"code", "idea", "devenv.exe"} else None

        with mock.patch("ai_engineering_guardrails.install.shutil.which", side_effect=which):
            detected = install.detect_products(self.home)
        self.assertEqual(("executable",), detected["vscode"])
        self.assertEqual(("launcher",), detected["jetbrains"])
        self.assertNotIn("visualstudio", detected)
        with mock.patch.object(install.sys, "platform", "win32"), mock.patch(
            "ai_engineering_guardrails.install.shutil.which", side_effect=which
        ):
            windows_detected = install.detect_products(self.home)
        self.assertIn("devenv.exe", windows_detected["visualstudio"])

    def test_vscode_native_hook_and_routing_are_explicit(self) -> None:
        self.install(("vscode",))
        instruction = self.home / ".copilot/instructions/workstation-guardrails.instructions.md"
        hook = self.home / ".copilot/hooks/workstation-guardrails.json"
        self.assertTrue(instruction.is_file())
        self.assertTrue(hook.is_file())
        self.assertNotIn(str(Path.cwd()), hook.read_text(encoding="utf-8"))
        state = json.loads((self.home / ".ai-guardrails/state.json").read_text())
        self.assertEqual("native-vscode", state["products"]["vscode"]["hook_mode"])
        self.assertEqual("none", state["products"]["vscode"]["routing_profile"])
        self.assertFalse((self.home / ".copilot/agents").exists())
        self.install(("vscode",), routing_profile="balanced")
        agent = self.home / ".copilot/agents/workstation-explorer.agent.md"
        self.assertTrue(agent.is_file())
        self.assertNotIn("model:", agent.read_text(encoding="utf-8"))
        report = install.status(("vscode",), self.home)
        self.assertEqual("Preview", report["products"]["vscode"]["hook_maturity"])
        self.assertEqual("not covered", report["products"]["vscode"]["inline_suggestions"])

    def test_vscode_and_claude_have_one_project_owned_hook(self) -> None:
        self.install(("vscode",))
        self.assertTrue((self.home / ".copilot/hooks/workstation-guardrails.json").is_file())
        self.install(("claude",))
        data = json.loads((self.home / ".ai-guardrails/state.json").read_text())
        self.assertEqual("shared-claude", data["products"]["vscode"]["hook_mode"])
        self.assertFalse((self.home / ".copilot/hooks/workstation-guardrails.json").exists())
        claude = json.loads((self.home / ".claude/settings.json").read_text())
        self.assertEqual(1, len(install._managed_hook_groups(claude, "claude")))
        with contextlib.redirect_stdout(io.StringIO()):
            install.uninstall(("claude",), self.home, force=False, dry_run=False)
        self.assertTrue((self.home / ".copilot/hooks/workstation-guardrails.json").is_file())
        data = json.loads((self.home / ".ai-guardrails/state.json").read_text())
        self.assertEqual("native-vscode", data["products"]["vscode"]["hook_mode"])

    def test_claude_first_prefers_shared_hook(self) -> None:
        self.install(("claude",))
        self.install(("vscode",))
        data = json.loads((self.home / ".ai-guardrails/state.json").read_text())
        self.assertEqual("shared-claude", data["products"]["vscode"]["hook_mode"])
        self.assertFalse((self.home / ".copilot/hooks/workstation-guardrails.json").exists())

    def test_visualstudio_uses_a_managed_block_without_hook(self) -> None:
        target = self.home / "copilot-instructions.md"
        target.write_text("personal\n", encoding="utf-8")
        with mock.patch.object(install.sys, "platform", "win32"):
            self.install(("visualstudio",), routing_profile="balanced")
        text = target.read_text(encoding="utf-8")
        self.assertTrue(text.startswith("personal"))
        self.assertIn(install.BEGIN_MARKER, text)
        self.assertTrue((self.home / ".github/agents/workstation-explorer.agent.md").is_file())
        self.assertFalse((self.home / ".copilot/hooks").exists())
        self.assertEqual({"skills": "compatible", "agents": "compatible"}, install.visualstudio_capabilities("18.5"))
        self.assertEqual("too-old", install.visualstudio_capabilities("18.3")["agents"])
        self.assertEqual("version-unverified", install.visualstudio_capabilities(None)["skills"])

    def test_cli_rejects_real_visualstudio_install_on_non_windows(self) -> None:
        if __import__("sys").platform == "win32":
            self.skipTest("non-Windows guard is not applicable")
        errors = io.StringIO()
        with contextlib.redirect_stderr(errors):
            result = cli.main(["install", "--product", "visualstudio", "--home", str(self.home), "--dry-run"])
        self.assertEqual(1, result)
        self.assertIn("only on Windows", errors.getvalue())

    def test_jetbrains_manual_surfaces_and_platform_paths(self) -> None:
        with mock.patch.object(install.sys, "platform", "darwin"):
            self.install(("jetbrains",), routing_profile="balanced")
        target = self.home / ".config/github-copilot/intellij/global-copilot-instructions.md"
        self.assertTrue(target.is_file())
        self.assertTrue((self.home / ".ai-guardrails/manual/jetbrains/agents/workstation-explorer.agent.md").is_file())
        self.assertFalse((self.home / ".jetbrains/hooks").exists())
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            install.print_jetbrains_chat_instructions(clipboard=False, home=self.home)
        self.assertIn("GENERATED — DO NOT EDIT", output.getvalue())
        report = install.status(("jetbrains",), self.home)
        self.assertEqual("manual directory registration required", report["products"]["jetbrains"]["skills_registration"])

    def test_jetbrains_linux_does_not_invent_copilot_path_and_export_is_explicit(self) -> None:
        with mock.patch.object(install.sys, "platform", "linux"):
            self.install(("jetbrains",))
        self.assertFalse((self.home / ".config/github-copilot").exists())
        state = json.loads((self.home / ".ai-guardrails/state.json").read_text())
        self.assertTrue(any(step["id"] == "jetbrains-copilot-instructions" for step in state["manual_steps"]))
        repo = Path(self.temporary.name) / "repo"
        repo.mkdir()
        with contextlib.redirect_stdout(io.StringIO()):
            install.export_jetbrains_project_rules(repo, dry_run=False, force=False, home=self.home)
        rule = repo / ".aiassistant/rules/workstation-guardrails.md"
        self.assertTrue(rule.is_file())
        (repo / ".noai").write_text("\n", encoding="utf-8")
        with self.assertRaisesRegex(GuardrailsError, "\.noai"):
            install.export_jetbrains_project_rules(repo, dry_run=True, force=False, home=self.home)

    def test_jetbrains_windows_copilot_path_stays_beneath_selected_home(self) -> None:
        real_local_app_data = Path(self.temporary.name) / "outside-local-app-data"
        with mock.patch.dict("os.environ", {"LOCALAPPDATA": str(real_local_app_data)}, clear=False), mock.patch.object(
            install.sys, "platform", "win32"
        ):
            self.install(("jetbrains",))
        expected = self.home / "AppData/Local/github-copilot/intellij/global-copilot-instructions.md"
        self.assertTrue(expected.is_file())
        self.assertFalse(real_local_app_data.exists())

    def test_vscode_payload_and_installed_command_self_protection(self) -> None:
        decision = enforcement.evaluate_request(
            {
                "hook_event_name": "PreToolUse",
                "tool_name": "runTerminalCommand",
                "tool_input": {"command": "git reset --hard"},
            },
            policy_data=policy.load_enforcement_policy(),
            metadata={"safety_profile": "infrastructure-observe", "trust_mode": "trusted-workspace"},
            consume_waiver=False,
        )
        self.assertEqual("deny", decision.decision)
        for command in (
            "ai-guardrails install --product vscode",
            "ai-guardrails update --product visualstudio",
            "ai-guardrails uninstall --product jetbrains",
            "ai-guardrails routing set balanced --product vscode",
            "ai-guardrails jetbrains export-project-rules --repo .",
        ):
            with self.subTest(command=command):
                self.assertIsNotNone(enforcement.evaluate_command(command, policy.load_enforcement_policy()))
        for command in (
            "ai-guardrails status --product vscode",
            "ai-guardrails jetbrains print-chat-instructions",
            "echo ai-guardrails install --product vscode",
        ):
            with self.subTest(command=command):
                self.assertIsNone(enforcement.evaluate_command(command, policy.load_enforcement_policy()))


if __name__ == "__main__":
    unittest.main()
