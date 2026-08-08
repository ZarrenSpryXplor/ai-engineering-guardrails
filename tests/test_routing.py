from __future__ import annotations

import contextlib
import io
import json
import shutil
import tempfile
import tomllib
import unittest
from pathlib import Path

from ai_engineering_guardrails import install as installer, routing
from ai_engineering_guardrails.util import PRODUCTS, ROOT, GuardrailsError


class RoutingConfigurationTests(unittest.TestCase):
    def test_native_agent_generation_is_deterministic_and_valid(self) -> None:
        for product in PRODUCTS:
            first = routing.render_agents(product)
            self.assertEqual(first, routing.render_agents(product))
            self.assertEqual(5, len(first))
            for filename, content in first.items():
                text = content.decode("utf-8")
                with self.subTest(product=product, filename=filename):
                    self.assertIn("GENERATED — DO NOT EDIT", text)
                    self.assertTrue(content.endswith(b"\n"))
                    self.assertFalse(content.endswith(b"\n\n"))
                    self.assertNotIn(str(Path.home()), text)
                    self.assertNotIn(str(ROOT), text)
                    if product == "codex":
                        fields = tomllib.loads(text)
                        self.assertEqual(Path(filename).stem, fields["name"])
                        self.assertIn("developer_instructions", fields)
                    else:
                        fields = routing.frontmatter_fields(text, filename)
                        self.assertEqual(Path(filename).stem, fields["name"])
                        self.assertIn("model", fields)

    def test_official_default_tier_maps(self) -> None:
        config = routing.load_config()
        self.assertEqual(
            {"economy":"gpt-5.6-luna", "balanced":"gpt-5.6-terra", "deep":"gpt-5.6-sol"},
            routing.resolved_models("codex", config, None),
        )
        self.assertEqual(
            {"economy":"haiku", "balanced":"sonnet", "deep":"opus"},
            routing.resolved_models("claude", config, None),
        )
        self.assertEqual({"economy":"inherit", "balanced":"inherit", "deep":"inherit"}, routing.resolved_models("cursor", config, None))

    def test_profile_selection_and_product_specific_override(self) -> None:
        codex = routing.render_agents("codex", "quality")
        explorer = tomllib.loads(codex["workstation_explorer.toml"].decode())
        reviewer = tomllib.loads(codex["workstation_reviewer.toml"].decode())
        self.assertEqual("gpt-5.6-terra", explorer["model"])
        self.assertEqual("gpt-5.6-sol", reviewer["model"])
        self.assertEqual("high", reviewer["model_reasoning_effort"])
        cursor = routing.render_agents("cursor", "quality", model_overrides={"cursor":{"deep":"provider/model-family"}})
        fields = routing.frontmatter_fields(cursor["workstation-reviewer.md"].decode(), "reviewer")
        self.assertEqual("provider/model-family[effort=high]", fields["model"])
        with self.assertRaisesRegex(GuardrailsError, "unsupported product"):
            routing.render_agents("cursor", model_overrides={"codex":{"deep":"x"}})

    def test_concurrency_write_and_high_risk_invariants(self) -> None:
        config = routing.load_config()
        expected = {"economy":1, "balanced":2, "quality":3}
        for name, profile in config["profiles"].items():
            self.assertEqual(expected[name], profile["parallelism"]["maximum_read_only_agents"])
            self.assertEqual(1, profile["parallelism"]["maximum_writing_agents"])
            self.assertFalse(profile["parallelism"]["parallel_writing_agents"])
            self.assertLessEqual(profile["escalation"]["maximum_bounded_attempts"], 2)
            for identifier, task in config["tasks"].items():
                if task["risk"] == "high":
                    self.assertEqual("deep", profile["task_tiers"][identifier])
        agents = {item["fields"]["name"]:item["fields"] for item in config["agents"]}
        self.assertEqual(["workstation_implementer"], [name for name, fields in agents.items() if fields["capability"] == "write"])
        for name in ("workstation_explorer", "workstation_reviewer", "workstation_verifier"):
            self.assertEqual("read-only", agents[name]["capability"])

    def test_escalation_policy_rejects_economy_high_risk(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            copy = Path(temporary) / "routing"
            shutil.copytree(routing.ROUTING_ROOT, copy)
            path = copy / "escalation-policy.json"
            data = json.loads(path.read_text())
            data["constraints"]["high_risk_minimum_tier"] = "economy"
            path.write_text(json.dumps(data), encoding="utf-8")
            with self.assertRaisesRegex(GuardrailsError, "high-risk"):
                routing.load_config(copy)

    def test_profiles_never_change_main_session_model(self) -> None:
        config = routing.load_config()
        for model_map in config["model_maps"].values():
            self.assertTrue(model_map["main_session_unchanged"])
        self.assertFalse(config["model_maps"]["claude"]["global_subagent_model_environment_variable"])
        for profile in config["profiles"].values():
            self.assertNotIn("main_model", profile)
            self.assertNotIn("environment", profile)

    def test_metrics_schema_is_content_free(self) -> None:
        properties = set(routing.load_config()["metrics"]["properties"])
        expected = {
            "product", "model", "task_class", "tier", "reasoning_level", "subagent_count",
            "input_tokens", "cached_tokens", "output_tokens", "wall_clock_duration_ms", "retries",
            "escalation_count", "completion_outcome",
        }
        self.assertEqual(expected, properties)
        self.assertFalse(properties & {"prompt", "source_code", "command", "arguments", "tool_output", "secret"})

    def test_none_profile_generates_no_agents(self) -> None:
        for product in PRODUCTS:
            self.assertEqual({}, routing.render_agents(product, "none"))


class RoutingInstallationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.home = Path(self.temporary.name)

    def install(self, product: str, profile: str = "none") -> None:
        with contextlib.redirect_stdout(io.StringIO()):
            installer.install((product,), self.home, force=False, dry_run=False, routing_profile=profile)

    def test_explicit_profile_install_is_product_specific_and_idempotent(self) -> None:
        self.install("claude", "balanced")
        agent = self.home / ".claude/agents/workstation-explorer.md"
        before = agent.read_bytes()
        self.install("claude", "balanced")
        self.assertEqual(before, agent.read_bytes())
        self.assertFalse((self.home / ".codex").exists())
        self.assertFalse((self.home / ".cursor").exists())

    def test_routing_set_updates_only_agents_and_keeps_main_config_unmodified(self) -> None:
        self.install("codex")
        with contextlib.redirect_stdout(io.StringIO()):
            installer.set_routing(("codex",), self.home, "balanced", model_overrides=None, force=False, dry_run=False)
        self.assertTrue((self.home / ".codex/agents/workstation_explorer.toml").is_file())
        self.assertFalse((self.home / ".codex/config.toml").exists())

    def test_routing_set_requires_existing_installation(self) -> None:
        with self.assertRaisesRegex(GuardrailsError, "not installed"):
            installer.set_routing(("cursor",), self.home, "balanced", model_overrides=None, force=False, dry_run=False)

    def test_none_removes_managed_agents_but_preserves_unmanaged(self) -> None:
        self.install("cursor", "balanced")
        unmanaged = self.home / ".cursor/agents/my-agent.md"
        unmanaged.write_text("mine\n", encoding="utf-8")
        with contextlib.redirect_stdout(io.StringIO()):
            installer.set_routing(("cursor",), self.home, "none", model_overrides=None, force=False, dry_run=False)
        self.assertTrue(unmanaged.is_file())
        self.assertFalse((self.home / ".cursor/agents/workstation-explorer.md").exists())

    def test_status_reports_mapping_as_configured_but_availability_unverified(self) -> None:
        self.install("cursor")
        with contextlib.redirect_stdout(io.StringIO()):
            installer.set_routing(
                ("cursor",), self.home, "balanced", model_overrides={"cursor":{"balanced":"vendor/model"}}, force=False, dry_run=False
            )
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            result = installer.status(("cursor",), self.home, show_routing_details=True)
        self.assertEqual("unverified", result["products"]["cursor"]["model_availability"])
        self.assertIn("vendor/model", output.getvalue())
        self.assertIn("fallback may apply", output.getvalue())
        self.assertIn("main-session model unchanged", output.getvalue())


if __name__ == "__main__":
    unittest.main()
