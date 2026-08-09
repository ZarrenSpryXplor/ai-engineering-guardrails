from __future__ import annotations

import contextlib
import datetime as dt
import hashlib
import io
import json
import os
import subprocess
import sys
import tempfile
import tomllib
import unittest
from unittest import mock
from pathlib import Path

from ai_engineering_guardrails import build, cli, install, state, terminal_renderer, terminal_ux
from ai_engineering_guardrails.util import GuardrailsError


class TerminalUxTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        build.build()

    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.home = Path(self.temporary.name).resolve()

    def test_profiles_render_one_line_with_ascii_and_width_fallback(self) -> None:
        profiles = terminal_ux.load_profiles()
        self.assertTrue(all(item["fallback"] == "omit" for item in profiles["profiles"].values()))
        payload = {
            "model": {"display_name": "Claude"},
            "context_window": {"used_percentage": 92},
            "rate_limits": {"five_hour": {"used_percentage": 20}, "seven_day": {"used_percentage": 45}},
            "cost": {"total_cost_usd": 1.23, "total_duration_ms": 61_000},
            "worktree": {"branch": "feature"},
        }
        rendered = terminal_renderer.render_status_line(payload, profiles, "fun", "infrastructure-observe", ascii_only=True, columns=42)
        self.assertIn("[G]", rendered)
        self.assertIn("ctx", rendered)
        self.assertNotIn("\n", rendered)
        self.assertLessEqual(len(rendered), 42)
        self.assertNotIn("\x1b", rendered)

    def test_human_terminal_ux_commands_fall_back_to_ascii_for_legacy_stdout(self) -> None:
        binary = io.BytesIO()
        legacy_stdout = io.TextIOWrapper(binary, encoding="cp1252")
        with mock.patch.object(sys, "stdout", legacy_stdout):
            self.assertEqual(0, cli.main(["statusline", "preview", "--product", "all", "--profile", "standard"]))
            self.assertEqual(0, cli.main(["demo", "--scenario", "all", "--fun"]))
            self.assertEqual(0, cli.main(["complexity", "--repo", str(self.home)]))
        legacy_stdout.flush()
        output = binary.getvalue().decode("cp1252")
        self.assertIn("[G]", output)
        self.assertIn("KISS OK", output)
        self.assertNotIn("🛡", output)

    def test_renderer_omits_stale_cache(self) -> None:
        cache = terminal_ux.cache_directory(self.home)
        terminal_ux.audit_summary_path(self.home).parent.mkdir(parents=True)
        terminal_ux.audit_summary_path(self.home).write_text(
            '{"generated_at":"2020-01-01T00:00:00Z","warnings":99,"denials":99}', encoding="utf-8"
        )
        line = terminal_renderer.render_status_line({}, terminal_ux.load_profiles(), "standard", "development", cache)
        self.assertNotIn("99W", line)

    def test_fun_renderer_uses_only_matching_recent_complexity_snapshot(self) -> None:
        project = "/synthetic/project"
        repository_hash = hashlib.sha256(project.encode("utf-8")).hexdigest()
        snapshot = terminal_ux.complexity_snapshot_path(self.home, repository_hash)
        snapshot.parent.mkdir(parents=True)
        snapshot.write_text(json.dumps({"schema_version": 1, "repository_identifier_hash": repository_hash, "classification": "review", "signals": [], "generated_at": dt.datetime.now(dt.timezone.utc).isoformat()}), encoding="utf-8")
        line = terminal_renderer.render_status_line({"workspace": {"project_dir": project}}, terminal_ux.load_profiles(), "fun", "development", terminal_ux.cache_directory(self.home))
        self.assertIn("KISS review", line)
        self.assertNotIn(project, snapshot.read_text(encoding="utf-8"))

    def test_renderer_omits_missing_values_and_rejects_malformed_input(self) -> None:
        profiles = terminal_ux.load_profiles()
        self.assertEqual("🛡 development", terminal_renderer.render_status_line({}, profiles, "compact", "development"))
        line = terminal_renderer.render_status_line({"model": {"display_name": "Claude"}}, profiles, "standard", "development")
        self.assertEqual("🛡 development | Claude", line)
        result = subprocess.run(
            [sys.executable, "-m", "ai_engineering_guardrails.terminal_renderer", "--profiles", str(terminal_ux.PROFILE_PATH), "--profile", "standard", "--safety-profile", "development"],
            input="not-json",
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(0, result.returncode)
        self.assertEqual("", result.stdout)

    def test_renderer_strips_control_sequences_and_invalid_width(self) -> None:
        payload = {"model": {"display_name": "\x1b]0;not-a-title\x07Claude\n"}}
        line = terminal_renderer.render_status_line(payload, terminal_ux.load_profiles(), "compact", "development")
        self.assertNotIn("\x1b", line)
        self.assertNotIn("\n", line)
        command = [
            sys.executable,
            "-m",
            "ai_engineering_guardrails.terminal_renderer",
            "--profiles", str(terminal_ux.PROFILE_PATH),
            "--profile", "compact",
            "--safety-profile", "development",
        ]
        result = subprocess.run(command, input=json.dumps({"model": {"display_name": "Claude"}}), text=True, capture_output=True, check=False, env={**os.environ, "COLUMNS": "not-a-number"})
        self.assertEqual(0, result.returncode)
        self.assertIn("Claude", result.stdout)
        nonfinite = subprocess.run(
            command,
            input='{"context_window":{"used_percentage":1e309},"cost":{"total_duration_ms":1e309}}',
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(0, nonfinite.returncode)
        self.assertNotIn("ctx", nonfinite.stdout)
        self.assertEqual("", nonfinite.stderr)

    def test_audit_summary_rotations_cache_and_redaction(self) -> None:
        audit = self.home / ".ai-guardrails/audit"
        audit.mkdir(parents=True)
        (audit / "events.jsonl").write_text(
            '\n'.join((
                '{"timestamp":"2026-08-09T10:00:00Z","product":"claude","decision":"warn","command":"never-cache-me"}',
                '{invalid',
            )) + "\n",
            encoding="utf-8",
        )
        (audit / "events.jsonl.1").write_text(
            '{"timestamp":"2026-08-09T09:00:00Z","product":"claude","decision":"deny"}\n', encoding="utf-8"
        )
        now = dt.datetime(2026, 8, 9, 11, tzinfo=dt.timezone.utc)
        summary = terminal_ux.audit_summary(self.home, product="claude", now=now)
        self.assertEqual((1, 1), (summary["warnings"], summary["denials"]))
        terminal_ux.write_audit_summary_cache(self.home, summary)
        cached = terminal_ux.audit_summary_path(self.home).read_text(encoding="utf-8")
        self.assertNotIn("never-cache-me", cached)
        self.assertNotIn("command", cached)

    def test_activity_is_content_free_and_duration_bounded(self) -> None:
        audit = self.home / ".ai-guardrails/audit"
        audit.mkdir(parents=True)
        timestamp = dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
        audit.joinpath("events.jsonl").write_text(
            json.dumps({"timestamp": timestamp, "product": "codex", "decision": "no-decision", "operation_class": "observe", "rule_id": None, "command": "secret"}) + "\n",
            encoding="utf-8",
        )
        summary = terminal_ux.audit_summary(self.home, window="7d", now=dt.datetime(2026, 8, 9, 11, tzinfo=dt.timezone.utc))
        self.assertEqual(1, summary["observed"])
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            self.assertEqual(0, cli.main(["activity", "--home", str(self.home), "--since", "7d"]))
        self.assertIn("Observed 1", output.getvalue())
        self.assertNotIn("secret", output.getvalue())

    def test_activity_rejects_malformed_identifiers_and_refreshes_the_renderer_cache(self) -> None:
        audit = self.home / ".ai-guardrails/audit"
        audit.mkdir(parents=True)
        timestamp = dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
        audit.joinpath("events.jsonl").write_text(
            "\n".join((
                json.dumps({"timestamp": timestamp, "product": "claude", "decision": "deny", "operation_class": "observe", "rule_id": "safe-rule"}),
                json.dumps({"timestamp": timestamp, "product": "claude", "decision": "warn", "operation_class": "command = secret", "rule_id": "user supplied command = hello"}),
            )) + "\n",
            encoding="utf-8",
        )
        summary = terminal_ux.audit_summary(self.home)
        self.assertEqual((0, 1, 1), (summary["warnings"], summary["denials"], summary["skipped_malformed_events"]))
        self.assertNotIn("secret", json.dumps(summary))
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(0, cli.main(["activity", "--home", str(self.home)]))
        line = terminal_renderer.render_status_line({}, terminal_ux.load_profiles(), "standard", "development", terminal_ux.cache_directory(self.home))
        self.assertIn("24h 0W 1D", line)
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(0, cli.main(["activity", "--home", str(self.home), "--product", "claude"]))
        refreshed = json.loads(terminal_ux.audit_summary_path(self.home).read_text(encoding="utf-8"))
        self.assertEqual((None, "24h"), (refreshed["product"], refreshed["window"]))
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(0, cli.main(["activity", "--home", str(self.home), "--since", "1h"]))
        refreshed = json.loads(terminal_ux.audit_summary_path(self.home).read_text(encoding="utf-8"))
        self.assertEqual((None, "24h"), (refreshed["product"], refreshed["window"]))

    def test_claude_command_uses_fixed_platform_quoting(self) -> None:
        runtime = self.home / "runtime with space"
        posix = terminal_ux.claude_command(runtime, "compact", "development", self.home, platform_name="posix")
        windows = terminal_ux.claude_command(runtime, "compact", "development", self.home, platform_name="nt")
        self.assertIn("terminal_renderer.py", posix)
        self.assertIn("powershell -NoProfile", windows)
        self.assertIn("terminal_renderer.py", windows)

    def test_claude_install_preserves_unrelated_settings_and_runtime_is_standalone(self) -> None:
        settings = self.home / ".claude/settings.json"
        settings.parent.mkdir(parents=True)
        settings.write_text(json.dumps({"hooks": {"PreToolUse": []}, "unrelated": True}) + "\n", encoding="utf-8")
        report = install.statusline_install(("claude",), self.home, profile="standard", force=False, dry_run=False)
        entry = report["products"]["claude"]
        merged = json.loads(settings.read_text(encoding="utf-8"))
        self.assertTrue(merged["unrelated"])
        self.assertIn("hooks", merged)
        self.assertEqual("command", merged["statusLine"]["type"])
        runtime = self.home / ".ai-guardrails/runtime" / entry["runtime_digest"]
        self.assertEqual({"terminal_renderer.py", "statusline-profiles.json"}, {path.name for path in runtime.iterdir()})
        result = subprocess.run(
            [sys.executable, str(runtime / "terminal_renderer.py"), "--profiles", str(runtime / "statusline-profiles.json"), "--profile", "standard", "--safety-profile", "development", "--cache-dir", str(self.home / ".ai-guardrails/cache")],
            input=json.dumps({"model": {"display_name": "Claude"}, "context_window": {"used_percentage": 8}}),
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(0, result.returncode)
        self.assertIn("Claude", result.stdout)
        self.assertNotIn(str(Path(__file__).parents[1]), merged["statusLine"]["command"])

    def test_claude_collision_force_idempotency_and_uninstall(self) -> None:
        settings = self.home / ".claude/settings.json"
        settings.parent.mkdir(parents=True)
        settings.write_text('{"statusLine":{"type":"command","command":"user"},"other":1}\n', encoding="utf-8")
        with self.assertRaisesRegex(GuardrailsError, "unmanaged Claude statusLine collision"):
            install.statusline_install(("claude",), self.home, profile="compact", force=False, dry_run=False)
        install.statusline_install(("claude",), self.home, profile="compact", force=True, dry_run=False)
        first = settings.read_bytes()
        install.statusline_install(("claude",), self.home, profile="compact", force=False, dry_run=False)
        self.assertEqual(first, settings.read_bytes())
        install.statusline_uninstall(("claude",), self.home, force=False, dry_run=False)
        self.assertEqual({"other": 1}, json.loads(settings.read_text(encoding="utf-8")))
        self.assertFalse(terminal_ux.audit_summary_path(self.home).exists())

    def test_claude_uninstall_keeps_an_empty_settings_file_and_malformed_settings_keep_state(self) -> None:
        settings = self.home / ".claude/settings.json"
        install.statusline_install(("claude",), self.home, profile="compact", force=False, dry_run=False)
        install.statusline_uninstall(("claude",), self.home, force=False, dry_run=False)
        self.assertTrue(settings.is_file())
        self.assertEqual({}, json.loads(settings.read_text(encoding="utf-8")))
        install.statusline_install(("claude",), self.home, profile="compact", force=False, dry_run=False)
        settings.write_text("{malformed", encoding="utf-8")
        install.statusline_uninstall(("claude",), self.home, force=True, dry_run=False)
        self.assertIn("claude", state.load_state(self.home)[install.TERMINAL_UX_KEY]["products"])

    def test_cursor_remains_manual_without_private_configuration_mutation(self) -> None:
        config = self.home / ".codex/config.toml"
        config.parent.mkdir(parents=True)
        config.write_text("[tui]\nstatus_line = [\"model\"]\n", encoding="utf-8")
        before = config.read_bytes()
        install.statusline_install(("cursor",), self.home, profile="fun", force=False, dry_run=False)
        self.assertEqual(before, config.read_bytes())
        status = install.statusline_status(("codex", "cursor"), self.home)
        self.assertEqual("native-user-controlled", status["codex"]["state"])
        self.assertEqual(["model"], status["codex"]["native_status_line"])
        self.assertEqual("manual-native-step-required", status["cursor"]["state"])

    def test_codex_status_line_is_a_narrow_managed_toml_edit(self) -> None:
        config = self.home / ".codex/config.toml"
        config.parent.mkdir(parents=True)
        config.write_text('# preserve\nmodel = "keep"\n[tui]\ntheme = "night"\n[other]\nvalue = 1\n', encoding="utf-8")
        install.statusline_install(("codex",), self.home, profile="standard", force=False, dry_run=False)
        changed = config.read_text(encoding="utf-8")
        self.assertIn('# preserve\nmodel = "keep"', changed)
        self.assertIn('theme = "night"', changed)
        self.assertIn('BEGIN AI ENGINEERING GUARDRAILS STATUSLINE', changed)
        self.assertEqual(list(terminal_ux.CODEX_NATIVE_FIELDS["standard"]), tomllib.loads(changed)["tui"]["status_line"])
        before = config.read_bytes()
        install.statusline_install(("codex",), self.home, profile="standard", force=False, dry_run=False)
        self.assertEqual(before, config.read_bytes())
        install.statusline_uninstall(("codex",), self.home, force=False, dry_run=False)
        restored = config.read_text(encoding="utf-8")
        self.assertNotIn("STATUSLINE", restored)
        self.assertEqual("night", tomllib.loads(restored)["tui"]["theme"])

    def test_codex_status_requires_its_owned_marker_and_preserves_crlf(self) -> None:
        config = self.home / ".codex/config.toml"
        config.parent.mkdir(parents=True)
        config.write_bytes(b'# preserve\r\n[tui]\r\ntheme = "night"\r\n[other]\r\nvalue = 1\r\n')
        install.statusline_install(("codex",), self.home, profile="standard", force=False, dry_run=False)
        changed = config.read_bytes()
        self.assertNotIn(b"\n", changed.replace(b"\r\n", b""))
        self.assertEqual(list(terminal_ux.CODEX_NATIVE_FIELDS["standard"]), tomllib.loads(changed.decode("utf-8"))["tui"]["status_line"])
        text = changed.decode("utf-8").replace(install.CODEX_STATUSLINE_BEGIN + "\r\n", "").replace("\r\n" + install.CODEX_STATUSLINE_END, "")
        config.write_text(text, encoding="utf-8", newline="")
        self.assertEqual("modified-or-stale-native-config", install.statusline_status(("codex",), self.home)["codex"]["state"])

    def test_codex_unmanaged_or_invalid_toml_is_preserved(self) -> None:
        config = self.home / ".codex/config.toml"
        config.parent.mkdir(parents=True)
        config.write_text('[tui]\nstatus_line = ["model"]\n', encoding="utf-8")
        with self.assertRaisesRegex(GuardrailsError, "unmanaged Codex"):
            install.statusline_install(("codex",), self.home, profile="compact", force=False, dry_run=False)
        install.statusline_install(("codex",), self.home, profile="compact", force=True, dry_run=False)
        self.assertTrue(any((self.home / ".ai-guardrails/backups").iterdir()))
        install.statusline_uninstall(("codex",), self.home, force=False, dry_run=False)
        config.write_text("[tui\n", encoding="utf-8")
        with self.assertRaisesRegex(GuardrailsError, "invalid"):
            install.statusline_install(("codex",), self.home, profile="compact", force=False, dry_run=False)

    def test_codex_statusline_editor_rejects_a_table_marker_inside_a_multiline_string(self) -> None:
        config = self.home / ".codex/config.toml"
        config.parent.mkdir(parents=True)
        original = 'note = """\n[tui]\nnot a table\n"""\n'
        config.write_text(original, encoding="utf-8")
        with self.assertRaisesRegex(GuardrailsError, "did not produce the requested"):
            install.statusline_install(("codex",), self.home, profile="compact", force=False, dry_run=False)
        self.assertEqual(original, config.read_text(encoding="utf-8"))
        with self.assertRaisesRegex(GuardrailsError, "did not produce the requested"):
            install.install(("codex", "claude"), self.home, force=False, dry_run=False, statusline_profile="compact")
        self.assertFalse((self.home / ".claude/settings.json").exists())
        self.assertFalse((self.home / ".ai-guardrails/state.json").exists())

    def test_collision_does_not_create_a_runtime(self) -> None:
        settings = self.home / ".claude/settings.json"
        settings.parent.mkdir(parents=True)
        settings.write_text('{"statusLine":{"type":"command","command":"user"}}\n', encoding="utf-8")
        with self.assertRaises(GuardrailsError):
            install.statusline_install(("claude",), self.home, profile="standard", force=False, dry_run=False)
        self.assertFalse((self.home / ".ai-guardrails/runtime").exists())

    def test_multi_product_collision_does_not_partially_install(self) -> None:
        settings = self.home / ".claude/settings.json"
        settings.parent.mkdir(parents=True)
        settings.write_text('{"statusLine":{"type":"command","command":"user"}}\n', encoding="utf-8")
        with self.assertRaises(GuardrailsError):
            install.statusline_install(("codex", "claude", "cursor"), self.home, profile="standard", force=False, dry_run=False)
        self.assertFalse((self.home / ".codex/config.toml").exists())
        self.assertFalse((self.home / ".ai-guardrails/runtime").exists())

    def test_optional_statusline_collision_precedes_ordinary_installation(self) -> None:
        settings = self.home / ".claude/settings.json"
        settings.parent.mkdir(parents=True)
        settings.write_text('{"statusLine":{"type":"command","command":"user"}}\n', encoding="utf-8")
        with self.assertRaisesRegex(GuardrailsError, "unmanaged Claude statusLine collision"):
            install.install(("codex", "claude"), self.home, force=False, dry_run=False, statusline_profile="standard")
        self.assertFalse((self.home / ".codex/AGENTS.md").exists())
        self.assertFalse((self.home / ".ai-guardrails/runtime").exists())
        self.assertFalse((self.home / ".ai-guardrails/state.json").exists())

    def test_ordinary_install_keeps_terminal_ux_disabled_and_update_preserves_an_opt_in(self) -> None:
        install.install(("codex",), self.home, force=False, dry_run=False)
        self.assertFalse((self.home / ".codex/config.toml").exists())
        install.install(("codex",), self.home, force=False, dry_run=False, statusline_profile="compact")
        before = (self.home / ".codex/config.toml").read_bytes()
        install.update(("codex",), self.home, force=False, dry_run=False)
        state_value = install.statusline_status(("codex",), self.home)["codex"]
        self.assertEqual("compact", state_value["profile"])
        self.assertEqual(before, (self.home / ".codex/config.toml").read_bytes())

    def test_update_refreshes_existing_claude_terminal_ux_without_requiring_the_option_again(self) -> None:
        install.install(("claude",), self.home, force=False, dry_run=False, statusline_profile="compact")
        current = state.load_state(self.home)
        entry = current[install.TERMINAL_UX_KEY]["products"]["claude"]
        entry["runtime_digest"] = "0" * 64
        entry["runtime_path"] = ".ai-guardrails/runtime/" + "0" * 64
        state.save_state(self.home, current, dry_run=False)
        install.update(("claude",), self.home, force=False, dry_run=False)
        refreshed = state.load_state(self.home)[install.TERMINAL_UX_KEY]["products"]["claude"]
        self.assertNotEqual("0" * 64, refreshed["runtime_digest"])
        settings = json.loads((self.home / ".claude/settings.json").read_text(encoding="utf-8"))
        self.assertIn(refreshed["runtime_path"], settings["statusLine"]["command"])

    def test_demo_spacelift_and_explicit_json_receipts_are_machine_readable(self) -> None:
        demo = io.StringIO()
        with contextlib.redirect_stdout(demo):
            self.assertEqual(0, cli.main(["demo", "--scenario", "spacelift", "--format", "json"]))
        self.assertIn("spacelift", json.loads(demo.getvalue())["scenarios"])
        all_demo = io.StringIO()
        with contextlib.redirect_stdout(all_demo):
            self.assertEqual(0, cli.main(["demo", "--scenario", "all", "--format", "json"]))
        self.assertTrue({"statusline", "complexity"}.issubset(json.loads(all_demo.getvalue())["scenarios"]))
        receipt = io.StringIO()
        with contextlib.redirect_stdout(receipt):
            self.assertEqual(0, cli.main(["receipt", "--home", str(self.home), "--repo", str(self.home), "--format", "json", "--fun"]))
        self.assertIsInstance(json.loads(receipt.getvalue()), dict)
        receipt = io.StringIO()
        with contextlib.redirect_stdout(receipt):
            self.assertEqual(0, cli.main(["receipt", "--home", str(self.home), "--repo", str(self.home), "--format", "json", "--compact"]))
        self.assertIsInstance(json.loads(receipt.getvalue()), dict)

    def test_statusline_json_mutations_do_not_mix_human_progress_with_json(self) -> None:
        installed = io.StringIO()
        with contextlib.redirect_stdout(installed):
            self.assertEqual(0, cli.main(["statusline", "install", "--product", "claude", "--profile", "compact", "--home", str(self.home), "--format", "json"]))
        self.assertEqual("managed", json.loads(installed.getvalue())["products"]["claude"]["integration"])
        removed = io.StringIO()
        with contextlib.redirect_stdout(removed):
            self.assertEqual(0, cli.main(["statusline", "uninstall", "--product", "claude", "--home", str(self.home), "--format", "json"]))
        self.assertEqual("removed", json.loads(removed.getvalue())["products"]["claude"])

    def test_statusline_uninstall_reports_and_core_uninstall_retains_modified_configuration(self) -> None:
        install.statusline_install(("claude",), self.home, profile="compact", force=False, dry_run=False)
        settings = self.home / ".claude/settings.json"
        data = json.loads(settings.read_text(encoding="utf-8"))
        data["statusLine"]["command"] = "user-owned"
        settings.write_text(json.dumps(data), encoding="utf-8")
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            self.assertEqual(0, cli.main(["statusline", "uninstall", "--product", "claude", "--home", str(self.home)]))
        self.assertIn("partially complete", output.getvalue())
        result = io.StringIO()
        with contextlib.redirect_stdout(result):
            self.assertEqual(0, cli.main(["statusline", "uninstall", "--product", "claude", "--home", str(self.home), "--format", "json"]))
        self.assertEqual("retained-modified", json.loads(result.getvalue())["products"]["claude"])
        core_output = io.StringIO()
        with contextlib.redirect_stdout(core_output):
            install.uninstall(("claude",), self.home, force=False, dry_run=False)
        self.assertIn("modified managed paths were retained", core_output.getvalue())

    def test_dry_run_does_not_write(self) -> None:
        with contextlib.redirect_stdout(io.StringIO()):
            install.statusline_install(("claude",), self.home, profile="standard", force=False, dry_run=True)
        self.assertFalse((self.home / ".claude/settings.json").exists())
        self.assertFalse((self.home / ".ai-guardrails/state.json").exists())


if __name__ == "__main__":
    unittest.main()
