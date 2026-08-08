from __future__ import annotations

import contextlib
import datetime as dt
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from ai_engineering_guardrails import cli, enforcement, policy, scan, state
from ai_engineering_guardrails.util import GuardrailsError


class TtyBuffer(io.StringIO):
    def isatty(self) -> bool:
        return True


def runtime_metadata(home: Path) -> dict[str, object]:
    return {
        "format_version": 1,
        "product": "codex",
        "policy_digest": "0" * 64,
        "safety_profile": "infrastructure-observe",
        "trust_mode": "trusted-workspace",
        "home_directory": str(home),
        "audit_directory": str(home / ".ai-guardrails/audit"),
        "waiver_directory": str(home / ".ai-guardrails/waivers"),
        "targets_path": str(home / ".ai-guardrails/targets.json"),
        "state_path": str(home / ".ai-guardrails/state.json"),
        "managed_paths": [],
    }


class WaiverTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.home = Path(self.temporary.name).resolve()
        self.repo = self.home / "repo"
        self.repo.mkdir()
        self.policy = policy.load_enforcement_policy()
        self.payload = {
            "hook_event_name": "PreToolUse",
            "tool_name": "Bash",
            "tool_input": {"command": "git reset --hard"},
            "cwd": str(self.repo),
        }

    def create(self, *, digest: str, target: str = "none", uses: int = 1) -> dict[str, object]:
        rule = policy.find_rule("git-reset-hard")
        self.assertIsNotNone(rule)
        identifier = "waiver-00000000000000000000000000000001"
        input_stream = TtyBuffer(f"CREATE WAIVER {identifier}\n")
        output_stream = TtyBuffer()
        with mock.patch("ai_engineering_guardrails.state.uuid.uuid4", return_value=mock.Mock(hex=identifier.removeprefix("waiver-"))):
            return state.create_waiver(
                self.home,
                rule=rule or {},
                repository_scope=str(self.repo),
                target_scope=target,
                request_digest=digest,
                reason="Synthetic bounded exception",
                change_reference="CHANGE-123",
                maximum_uses=uses,
                input_stream=input_stream,
                output_stream=output_stream,
            )

    def test_creation_requires_tty_and_exact_confirmation(self) -> None:
        rule = policy.find_rule("git-reset-hard") or {}
        with self.assertRaisesRegex(GuardrailsError, "interactive TTY"):
            state.create_waiver(
                self.home,
                rule=rule,
                repository_scope=str(self.repo),
                target_scope="none",
                request_digest="0" * 64,
                reason="Synthetic",
                change_reference="CHANGE-123",
                input_stream=io.StringIO(),
                output_stream=io.StringIO(),
            )
        with mock.patch("ai_engineering_guardrails.state.uuid.uuid4", return_value=mock.Mock(hex="0" * 32)):
            with self.assertRaisesRegex(GuardrailsError, "did not match"):
                state.create_waiver(
                    self.home,
                    rule=rule,
                    repository_scope=str(self.repo),
                    target_scope="none",
                    request_digest="0" * 64,
                    reason="Synthetic",
                    change_reference="CHANGE-123",
                    input_stream=TtyBuffer("incorrect\n"),
                    output_stream=TtyBuffer(),
                )

    def test_waiver_is_exact_bounded_consumed_and_revocable(self) -> None:
        initial = enforcement.evaluate_request(
            self.payload,
            policy_data=self.policy,
            metadata=runtime_metadata(self.home),
        )
        waiver = self.create(digest=initial.request_digest)
        self.assertNotIn("git reset", json.dumps(waiver))
        allowed = enforcement.evaluate_request(
            self.payload,
            policy_data=self.policy,
            metadata=runtime_metadata(self.home),
            consume_waiver=True,
        )
        self.assertEqual("no-decision", allowed.decision)
        self.assertEqual(waiver["id"], allowed.waiver_id)
        denied_again = enforcement.evaluate_request(
            self.payload,
            policy_data=self.policy,
            metadata=runtime_metadata(self.home),
            consume_waiver=True,
        )
        self.assertEqual("deny", denied_again.decision)
        self.assertTrue(state.revoke_waiver(self.home, str(waiver["id"])))
        self.assertFalse(state.list_waivers(self.home))

    def test_expired_or_wrong_digest_waiver_does_not_apply(self) -> None:
        decision = enforcement.evaluate_request(
            self.payload,
            policy_data=self.policy,
            metadata=runtime_metadata(self.home),
        )
        waiver = self.create(digest="f" * 64)
        target = state.waiver_directory(self.home) / f"{waiver['id']}.json"
        value = json.loads(target.read_text(encoding="utf-8"))
        created = dt.datetime.now(dt.timezone.utc) - dt.timedelta(minutes=2)
        value["created_at"] = created.replace(microsecond=0).isoformat().replace("+00:00", "Z")
        value["expires_at"] = (created + dt.timedelta(minutes=1)).replace(microsecond=0).isoformat().replace("+00:00", "Z")
        target.write_text(json.dumps(value) + "\n", encoding="utf-8")
        denied = enforcement.evaluate_request(
            self.payload,
            policy_data=self.policy,
            metadata=runtime_metadata(self.home),
            consume_waiver=True,
        )
        self.assertNotEqual(decision.request_digest, waiver["command_tool_call_digest"])
        self.assertEqual("deny", denied.decision)

    def test_destructive_wildcard_waivers_are_rejected(self) -> None:
        rule = policy.find_rule("git-reset-hard") or {}
        with self.assertRaisesRegex(GuardrailsError, "wildcard"):
            state.create_waiver(
                self.home,
                rule=rule,
                repository_scope="*",
                target_scope="*",
                request_digest="0" * 64,
                reason="Synthetic",
                change_reference="CHANGE-123",
                input_stream=TtyBuffer(),
                output_stream=TtyBuffer(),
            )

    def test_runtime_rejects_tampered_overlong_or_extended_waivers(self) -> None:
        decision = enforcement.evaluate_request(
            self.payload,
            policy_data=self.policy,
            metadata=runtime_metadata(self.home),
        )
        waiver = self.create(digest=decision.request_digest)
        target = state.waiver_directory(self.home) / f"{waiver['id']}.json"
        value = json.loads(target.read_text(encoding="utf-8"))
        created = dt.datetime.now(dt.timezone.utc).replace(microsecond=0)
        value["created_at"] = created.isoformat().replace("+00:00", "Z")
        value["expires_at"] = (created + dt.timedelta(days=2)).isoformat().replace("+00:00", "Z")
        target.write_text(json.dumps(value) + "\n", encoding="utf-8")
        overlong = enforcement.evaluate_request(
            self.payload,
            policy_data=self.policy,
            metadata=runtime_metadata(self.home),
        )
        self.assertEqual("deny", overlong.decision)

        value["expires_at"] = (created + dt.timedelta(minutes=10)).isoformat().replace("+00:00", "Z")
        value["raw_command"] = "must never be accepted"
        target.write_text(json.dumps(value) + "\n", encoding="utf-8")
        extended = enforcement.evaluate_request(
            self.payload,
            policy_data=self.policy,
            metadata=runtime_metadata(self.home),
        )
        self.assertEqual("deny", extended.decision)
        with self.assertRaisesRegex(GuardrailsError, "supported schema"):
            state.validate_waiver(value)

    def test_waiver_consumption_failure_keeps_dangerous_request_denied(self) -> None:
        initial = enforcement.evaluate_request(
            self.payload,
            policy_data=self.policy,
            metadata=runtime_metadata(self.home),
        )
        self.create(digest=initial.request_digest)
        with mock.patch("ai_engineering_guardrails.enforcement._atomic_json", side_effect=OSError("synthetic")):
            decision = enforcement.evaluate_request(
                self.payload,
                policy_data=self.policy,
                metadata=runtime_metadata(self.home),
                consume_waiver=True,
            )
        self.assertEqual("deny", decision.decision)
        self.assertFalse(any(state.waiver_directory(self.home).glob("*.lock")))


class ExplainAndReceiptTests(unittest.TestCase):
    def test_explain_and_simulate_do_not_execute_input(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            marker = root / "must-not-exist"
            command = f"touch {marker}; git reset --hard"
            for name in ("explain", "simulate"):
                output = io.StringIO()
                with contextlib.redirect_stdout(output):
                    result = cli.main(
                        [name, "--home", str(root), "--repo", str(root), "--command", command, "--format", "json"]
                    )
                value = json.loads(output.getvalue())
                with self.subTest(command=name):
                    self.assertEqual(0, result)
                    self.assertEqual("deny", value["decision"])
                    self.assertIn("policy_source", value)
                    self.assertFalse(marker.exists())

    def test_structured_explain_redacts_never_log_fields(self) -> None:
        secret = "synthetic-token-that-must-not-appear"
        with tempfile.TemporaryDirectory() as temporary:
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                result = cli.main(
                    [
                        "explain",
                        "--home",
                        temporary,
                        "--tool",
                        "mcp__spacelift__mutate",
                        "--pack",
                        "spacelift",
                        "--tool-arguments",
                        json.dumps({"query": "mutation { synthetic }", "token": secret}),
                        "--format",
                        "json",
                    ]
                )
            self.assertEqual(0, result)
            self.assertNotIn(secret, output.getvalue())
            self.assertEqual("deny", json.loads(output.getvalue())["decision"])

    def test_session_receipt_is_content_free(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            home = Path(temporary)
            secret = "synthetic-secret-that-must-not-appear"
            audit = home / ".ai-guardrails/audit/events.jsonl"
            audit.parent.mkdir(parents=True)
            audit.write_text(
                json.dumps(
                    {
                        "decision": "deny",
                        "policy_digest": "0" * 64,
                        "request_digest": "1" * 64,
                    }
                )
                + "\n",
                encoding="utf-8",
            )
            receipt = scan.session_receipt(home, home, ("codex",))
            rendered = json.dumps(receipt)
            self.assertNotIn(secret, rendered)
            self.assertNotIn(str(home), rendered)
            self.assertEqual(1, receipt["decision_counts"]["denied"])
            self.assertRegex(receipt["repository_identifier_hash"], r"^[0-9a-f]{64}$")


if __name__ == "__main__":
    unittest.main()
