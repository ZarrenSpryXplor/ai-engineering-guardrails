"""Command-line interface for AI engineering guardrails."""

from __future__ import annotations

import argparse
import contextlib
import io
import json
import os
import sys
from pathlib import Path
from typing import Any, Mapping, Sequence

from . import (
    __version__,
    assurance,
    build,
    complexity,
    components,
    enforcement,
    evidence,
    install,
    packs,
    policy,
    presentation,
    routing,
    scan,
    state,
    terminal_ux,
)
from .resources import repository_output_root
from .util import PRODUCTS, SAFETY_PROFILES, TRUST_MODES, GuardrailsError, atomic_write, home_path


class RichArgumentParser(argparse.ArgumentParser):
    """Keep argparse semantics while routing human help through Rich."""

    help_no_color = False

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        kwargs.setdefault(
            "formatter_class",
            lambda prog: argparse.HelpFormatter(prog, max_help_position=24, width=78),
        )
        if sys.version_info >= (3, 14):
            # Python 3.14 colours help itself, and `add_parser` propagates that
            # choice to subparsers. Keep the formatter plain so `--no-color`,
            # `NO_COLOR`, and the presentation layer remain the only styling owner.
            kwargs["color"] = False
        super().__init__(*args, **kwargs)

    def _print_message(self, message: str, file: Any | None = None) -> None:
        if message:
            presentation.print_help(message, file=file, no_color=self.help_no_color)


def selected_products(value: str) -> tuple[str, ...]:
    return PRODUCTS if value == "all" else (value,)


def add_product(parser: argparse.ArgumentParser, *, detect_by_default: bool = False) -> None:
    default = None if detect_by_default else "all"
    default_help = "detect installed products" if detect_by_default else "all"
    parser.add_argument(
        "--product",
        choices=(*PRODUCTS, "all"),
        default=default,
        help=f"product to inspect or manage (default: {default_help})",
    )


def add_home(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--home", type=Path, default=Path.home(), help="selected home directory (default: current user's home)")


def add_mutation_flags(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="preview the change without writing managed configuration",
    )
    parser.add_argument("--force", action="store_true", help="replace or remove modified managed content after backup")


def add_no_color(parser: argparse.ArgumentParser) -> None:
    """Accept the common explicit accessibility preference."""
    parser.add_argument(
        "--no-color",
        action="store_true",
        default=argparse.SUPPRESS,
        help="disable terminal colour in human output",
    )


def _human_ascii_only() -> bool:
    """Use the terminal UX ASCII fallback when stdout cannot encode its symbols."""
    encoding = getattr(sys.stdout, "encoding", None) or "ascii"
    try:
        "🛡✓⚠🔥💨▓░".encode(encoding)
    except (LookupError, UnicodeEncodeError):
        return True
    return False


def _human_options(args: argparse.Namespace) -> dict[str, bool]:
    """Return the two presentation preferences shared by human renderers."""
    return {
        "no_color": bool(getattr(args, "no_color", False)),
        "ascii_only": _human_ascii_only(),
    }


def _selected_output_format(args: argparse.Namespace) -> str:
    """Resolve the one command whose legacy default depends on other flags."""
    if args.command == "receipt" and args.format is None:
        return "compact" if args.compact else "human" if args.fun else "json"
    return str(getattr(args, "format", "human"))


def parse_model_overrides(values: Sequence[str]) -> dict[str, dict[str, str]]:
    result: dict[str, dict[str, str]] = {}
    for value in values:
        selector, separator, model = value.partition("=")
        product, colon, tier = selector.partition(":")
        if not separator or not colon or not product or not tier or not model:
            raise GuardrailsError(f"invalid model override {value!r}; expected PRODUCT:TIER=MODEL")
        if tier in result.setdefault(product, {}):
            raise GuardrailsError(f"duplicate model override: {product}:{tier}")
        result[product][tier] = model
    return result


def add_install_options(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--routing-profile",
        choices=("none", "economy", "balanced", "quality"),
        default=None,
        help="set routing agents; omission preserves an existing selection and uses none when fresh (balanced is recommended)",
    )
    parser.add_argument(
        "--statusline-profile",
        choices=terminal_ux.STATUSLINE_PROFILES,
        default=None,
        help="opt in to terminal UX; omission preserves existing status-line configuration and fresh installs remain unchanged",
    )
    parser.add_argument(
        "--model-override",
        action="append",
        default=[],
        metavar="PRODUCT:TIER=MODEL",
        help="override one subagent tier without changing the main-session model",
    )
    pack_group = parser.add_mutually_exclusive_group()
    pack_group.add_argument("--pack", action="append", default=[], metavar="ID", help="install a capability pack (repeatable)")
    pack_group.add_argument("--all-packs", action="store_true", help="install every capability pack progressively")
    parser.add_argument(
        "--skill-catalogue",
        choices=("contextual", "all"),
        default=None,
        help="expose contextual skills or all selected pack skills; omission preserves existing installs and uses contextual when fresh",
    )
    parser.add_argument(
        "--safety-profile",
        choices=SAFETY_PROFILES,
        default=None,
        help="set the safety profile; omission preserves an existing selection and uses infrastructure-observe when fresh",
    )
    parser.add_argument(
        "--trust-mode",
        choices=TRUST_MODES,
        default=None,
        help="set the trust mode; omission preserves an existing selection and uses trusted-workspace when fresh",
    )


def _resolve_consumer_products(value: str | None, home: Path, command: str) -> tuple[tuple[str, ...], dict[str, tuple[str, ...]]]:
    selected_home = home.expanduser().resolve(strict=False)
    detected = install.detect_products(selected_home)
    if value is not None:
        return selected_products(value), detected
    if command == "install":
        if detected:
            return tuple(product for product in PRODUCTS if product in detected), detected
        raise GuardrailsError(
            "No supported product was detected. Install a supported product or select one explicitly, for example: "
            "ai-guardrails install --product codex"
        )
    managed = install.installed_products(selected_home)
    if managed:
        return managed, detected
    if command == "status" and detected:
        return tuple(product for product in PRODUCTS if product in detected), detected
    raise GuardrailsError(f"no managed installation was found for `{command}`")


def _run_consumer_install(
    args: argparse.Namespace,
    products: Sequence[str],
    detected: Mapping[str, Sequence[str]],
    *,
    updating: bool,
) -> None:
    details = io.StringIO()
    with contextlib.redirect_stdout(details):
        install.prepare_installation(dry_run=args.dry_run, home=args.home)
        if updating:
            report = install.update(
                products,
                args.home,
                force=args.force,
                dry_run=args.dry_run,
                statusline_profile=args.statusline_profile,
            )
        else:
            report = install.install(
                products,
                args.home,
                force=args.force,
                dry_run=args.dry_run,
                pack_ids=args.pack,
                all_packs=args.all_packs,
                skill_catalogue=args.skill_catalogue,
                routing_profile=args.routing_profile,
                safety_profile=args.safety_profile,
                trust_mode=args.trust_mode,
                statusline_profile=args.statusline_profile,
                model_overrides=parse_model_overrides(args.model_override) or None,
                explicit_product=args.product is not None,
            )
    if args.verbose:
        presentation.print_operation_log(
            "Installation details",
            details.getvalue(),
            **_human_options(args),
        )
    summary = io.StringIO()
    with contextlib.redirect_stdout(summary):
        install.print_consumer_install_summary(report, detected)
    presentation.print_operation_log(
        "Installation preview" if args.dry_run else "Installation summary",
        summary.getvalue(),
        **_human_options(args),
    )


def _routing_show(args: argparse.Namespace) -> None:
    config = routing.load_config()
    profile = config["profiles"][args.profile]
    parallel = profile["parallelism"]
    presentation.print_properties(
        "Routing profile",
        (
            ("Profile", args.profile),
            ("Description", profile["description"]),
            (
                "Parallelism",
                f"{parallel['maximum_read_only_agents']} read-only, 1 writing, no parallel writers",
            ),
        ),
        notes=("Model availability is unverified; the main-session model is unchanged.",),
        **_human_options(args),
    )
    rows = []
    for product in selected_products(args.product):
        models = routing.resolved_models(product, config, None)
        rows.extend((product, tier, model, "unverified") for tier, model in models.items())
    presentation.print_records(
        "Resolved model mappings",
        ("Product", "Tier", "Model", "Availability"),
        rows,
        **_human_options(args),
    )


def _packs_list(args: argparse.Namespace) -> None:
    presentation.print_records(
        "Capability packs",
        ("Pack", "Type", "Description"),
        (
            (identifier, data["type"], data["description"])
            for identifier, data in packs.load_packs().items()
        ),
        **_human_options(args),
    )


def _packs_detect(args: argparse.Namespace) -> None:
    result = packs.detect_packs(args.repo)
    presentation.print_properties(
        "Repository capability detection",
        (
            ("Repository", result.repo),
            ("Detected packs", ", ".join(result.active_packs) or "none"),
            ("Node package manager", result.package_manager or "not detected"),
            ("Configured build root", result.build_root or "not configured"),
        ),
        **_human_options(args),
    )
    if args.packs_command == "explain":
        presentation.print_records(
            "Detection evidence",
            ("Pack", "Kind", "Path", "Detector"),
            (
                (item.pack_id, item.kind, item.path, item.detector)
                for item in result.evidence
            ),
            **_human_options(args),
        )
        if result.warnings:
            presentation.print_operation_log(
                "Detection warnings",
                (f"warning: {warning}" for warning in result.warnings),
                **_human_options(args),
            )
        available = packs.load_packs()
        guidance_rows = []
        for identifier in result.active_packs:
            guidance = packs.pack_guidance(available[identifier])
            guidance_rows.extend(
                (identifier, category, "; ".join(guidance[key]))
                for category, key in (
                    ("On-demand policy", "policy"),
                    ("Verification", "verification"),
                    ("Routing hints", "routing"),
                )
            )
        presentation.print_records(
            "Pack guidance",
            ("Pack", "Guidance", "Details"),
            guidance_rows,
            **_human_options(args),
        )


def _installed_runtime(home: Path, product: str) -> tuple[Mapping[str, Any], Mapping[str, Any]] | None:
    installed_state = state.load_state(home)
    data = installed_state.get("products", {}).get(product)
    if not isinstance(data, Mapping):
        return None
    runtime_record = next(
        (record for record in state.product_records(installed_state, product) if record.get("kind") == "runtime-directory"),
        None,
    )
    if runtime_record is None:
        return None
    runtime = home_path(home, str(runtime_record["path"]))
    if not runtime.is_dir():
        return None
    return (
        enforcement.load_installed_policy(runtime / "command-policy.json", runtime / "structured-tool-policy.json"),
        enforcement.load_runtime_metadata(runtime / "metadata.json"),
    )


def _simulation_payload(args: argparse.Namespace) -> dict[str, Any]:
    if args.command_text is not None:
        return {
            "hook_event_name": "PreToolUse",
            "tool_name": "shell",
            "tool_input": {"command": args.command_text},
            "cwd": str(args.repo.resolve(strict=False)),
        }
    try:
        arguments = json.loads(args.tool_arguments)
    except json.JSONDecodeError as exc:
        raise GuardrailsError("structured tool arguments must be valid JSON; values were not logged") from exc
    if not isinstance(arguments, dict):
        raise GuardrailsError("structured tool arguments must be a JSON object")
    return {
        "hook_event_name": "PreToolUse",
        "tool_name": args.tool_name,
        "tool_input": arguments,
        "cwd": str(args.repo.resolve(strict=False)),
    }


def _explain(args: argparse.Namespace) -> enforcement.Decision:
    home = args.home.expanduser().resolve(strict=False)
    installed = _installed_runtime(home, args.product)
    if installed:
        policy_data, metadata = installed
    else:
        policy_data = policy.load_enforcement_policy(args.pack)
        metadata = {
            "format_version": 1,
            "policy_digest": sha_for_policy(policy_data),
            "safety_profile": args.safety_profile,
            "trust_mode": args.trust_mode,
            "home_directory": str(home),
            "audit_directory": None,
            "waiver_directory": str(home / ".ai-guardrails/waivers"),
            "targets_path": str(home / ".ai-guardrails/targets.json"),
            "state_path": str(home / ".ai-guardrails/state.json"),
            "managed_paths": [],
        }
    decision = enforcement.evaluate_request(
        _simulation_payload(args), policy_data=policy_data, metadata=metadata, consume_waiver=False
    )
    value = decision.as_dict()
    if args.format == "json":
        print(json.dumps(value, indent=2, sort_keys=True))
    else:
        presentation.print_properties(
            "Deterministic decision",
            (
                ("Decision", value["decision"]),
                ("Rollout mode", value["rollout_mode"]),
                ("Rule", value["rule_id"] or "none"),
                ("Operation class", value["operation_class"] or "unclassified"),
                ("Matched tokens", ", ".join(value["matched_tokens"]) or "none"),
                ("Matched fields", ", ".join(value["matched_fields"]) or "none"),
                ("Target", value["target"] or "unknown/protected"),
                ("Lifecycle", value["target_lifecycle"]),
                ("Policy source", value["policy_source"] or "none"),
                ("Reason", value["reason"] or "no deterministic match"),
                ("Waiver", value["applicable_waiver"] or "none"),
                ("Safety profile", value["safety_profile"]),
                ("Trust mode", value["trust_mode"]),
            ),
            notes=("Simulation only: no command or tool call was executed.",),
            **_human_options(args),
        )
    return decision


def sha_for_policy(value: Mapping[str, Any]) -> str:
    import hashlib

    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()


def _waiver_create(args: argparse.Namespace) -> None:
    rule = policy.find_rule(args.rule_id)
    if rule is None:
        raise GuardrailsError(f"unknown deterministic rule: {args.rule_id}")
    value = state.create_waiver(
        args.home.expanduser().resolve(strict=False),
        rule=rule,
        repository_scope=str(args.repo.expanduser().resolve(strict=False)),
        target_scope=args.target_scope,
        request_digest=args.digest,
        reason=args.reason,
        change_reference=args.change_reference,
        expiry_minutes=args.expires_minutes,
        maximum_uses=args.maximum_uses,
    )
    presentation.print_properties(
        "Waiver created",
        (
            ("ID", value["id"]),
            ("Rule", value["rule_id"]),
            ("Expires", value["expires_at"]),
            ("Remaining uses", value["remaining_uses"]),
        ),
        notes=("Raw command and tool arguments were not stored.",),
        **_human_options(args),
    )


def _waiver_list(args: argparse.Namespace) -> None:
    values = state.list_waivers(args.home.expanduser().resolve(strict=False))
    presentation.print_records(
        "Local waivers",
        ("Waiver", "Details"),
        (
            (
                value["id"],
                f"rule={value['rule_id']}\nexpires={value['expires_at']}\n"
                f"remaining={value['remaining_uses']}/{value['maximum_uses']}\n"
                f"change={value['change_reference']}",
            )
            for value in values
        ),
        empty_message="No local waivers.",
        **_human_options(args),
    )


def _policy_source_label(value: object) -> str:
    source = str(value or "bundled")
    if "/packs/" in source or source.startswith("packs/"):
        return "pack"
    return "local" if source == "local policy overlay" else "bundled"


def _policy_list(args: argparse.Namespace) -> None:
    effective = policy.validate_local_overlay(args.home.expanduser().resolve(strict=False))["policy"]
    rows = []
    for group in ("rules", "classifications", "structured_tool_rules"):
        for rule in effective[group]:
            mode = str(rule.get("rollout_mode", "n/a"))
            rows.append(
                (
                    rule["id"],
                    f"source={_policy_source_label(rule.get('policy_source'))}; "
                    f"operation={rule.get('operation_class', 'unclassified')}; mode={mode}",
                )
            )
    presentation.print_records(
        "Effective policy",
        ("Rule", "Effective classification"),
        rows,
        **_human_options(args),
    )


def _policy_show(args: argparse.Namespace) -> None:
    effective = policy.validate_local_overlay(args.home.expanduser().resolve(strict=False))["policy"]
    rule = next(
        (
            candidate
            for group in ("rules", "classifications", "structured_tool_rules")
            for candidate in effective[group]
            if candidate["id"] == args.rule_id
        ),
        None,
    )
    if rule is None:
        raise GuardrailsError(f"unknown effective policy rule: {args.rule_id}")
    strategy = rule.get("matching_strategy")
    presentation.print_properties(
        "Policy rule",
        (
            ("ID", rule["id"]),
            ("Description", rule.get("description", "operation classification")),
            ("Source", _policy_source_label(rule.get("policy_source"))),
            ("Risk category", rule.get("risk_category", "not applicable")),
            ("Operation class", rule.get("operation_class", "unclassified")),
            ("Effective rollout mode", rule.get("rollout_mode", "n/a")),
            ("Local mode strengthening", "yes" if rule.get("local_mode_strengthening") else "no"),
            ("Matching strategy", strategy.get("type", "unknown") if isinstance(strategy, Mapping) else "n/a"),
        ),
        **_human_options(args),
    )


def _policy_validate(args: argparse.Namespace) -> None:
    result = policy.validate_local_overlay(args.home.expanduser().resolve(strict=False))
    presentation.print_properties(
        "Local policy validation",
        (
            ("Result", "passed"),
            ("Behavioural fragments", len(result["fragments"])),
            ("Mode strengthenings", len(result["overlay"]["rule_modes"])),
            ("Additional deterministic rules", len(result["overlay"]["additional_rules"])),
        ),
        **_human_options(args),
    )


def _policy_diff(args: argparse.Namespace) -> None:
    diff = policy.local_policy_diff(args.home.expanduser().resolve(strict=False))
    presentation.print_properties(
        "Local policy differences",
        ((label.replace("_", " ").title(), ", ".join(values) or "none") for label, values in diff.items()),
        **_human_options(args),
    )


def _policy_apply(args: argparse.Namespace) -> None:
    home = args.home.expanduser().resolve(strict=False)
    policy.validate_local_overlay(home)
    products = install.installed_products(home)
    if not products:
        raise GuardrailsError("no managed installation was found; install a product before applying local policy")
    output = io.StringIO()
    with contextlib.redirect_stdout(output):
        install.update(products, home, force=args.force, dry_run=args.dry_run)
    presentation.print_operation_log(
        "Policy apply preview" if args.dry_run else "Policy applied",
        output.getvalue(),
        **_human_options(args),
    )


def _policy_audit(args: argparse.Namespace) -> bool:
    result = evidence.audit_registry(policy.load_manifest(), generated_artifacts=build.build_artifacts())
    if args.format == "json":
        print(json.dumps(result, indent=2, sort_keys=True))
        return not result["errors"]
    presentation.print_properties(
        "Policy evidence audit",
        (
            ("Structural checks", "passed" if not result["errors"] else "issues found"),
            ("Evidence sources", result["sources"]),
            ("Policy records", result["policy_records"]),
            ("Reviews due", len(result["reviews"])),
        ),
        **_human_options(args),
    )
    presentation.print_findings(
        "Evidence findings",
        [
            *(
                {"level": "error", "id": item["id"], "message": item["detail"]}
                for item in result["errors"]
            ),
            *(
                {"level": "review", "id": item["id"], "message": item["detail"]}
                for item in result["reviews"]
            ),
        ],
        clean_message="No evidence review dates are overdue.",
        **_human_options(args),
    )
    return not result["errors"]


def _policy_evidence(args: argparse.Namespace) -> None:
    result = evidence.evidence_for_policy(args.policy_id, policy.load_manifest())
    if args.format == "json":
        print(json.dumps(result, indent=2, sort_keys=True))
        return
    metadata = result["policy"]
    presentation.print_properties(
        "Policy evidence",
        (
            ("Policy", metadata["id"]),
            ("Polarity", metadata["polarity"]),
            ("Scope", metadata["scope"]),
            ("Rationale", metadata["rationale"]),
            ("Confidence", metadata["confidence"]),
            ("Review after", metadata["review_after"]),
        ),
        **_human_options(args),
    )
    presentation.print_records(
        "Evidence sources",
        ("Source", "Title", "URL"),
        ((source["id"], source["title"], source["url"]) for source in result["sources"]),
        **_human_options(args),
    )
    if result["review_findings"]:
        presentation.print_findings(
            "Review findings",
            ({"level": "review", "id": "review-date", "message": item["detail"]} for item in result["review_findings"]),
            clean_message="No review findings.",
            **_human_options(args),
        )


def _task_result(args: argparse.Namespace, *, receipt: bool) -> bool:
    result = assurance.task_receipt(args.repo, home=args.home) if receipt else assurance.task_status(args.repo, home=args.home)
    task_result = result["task_assurance"] if receipt else result
    if args.format == "json":
        print(json.dumps(result, indent=2, sort_keys=True))
    else:
        title = "Task receipt" if receipt else "Task status"
        scope = task_result["scope"]
        scope_detail = (
            f"{scope['files_changed']} file(s), {scope['lines_added']} added, "
            f"{scope['lines_removed']} removed, {scope['directories_changed']} directories changed"
            if scope["available"]
            else "unavailable"
        )
        rows: list[tuple[object, object]] = [
            ("Effective status", task_result["effective_status"]),
            ("Scope", scope_detail),
            (
                "Evidence",
                ", ".join(f"{item['id']}={item['state']}" for item in task_result["evidence"])
                or "none required",
            ),
            ("Contract continuity", task_result["contract_continuity"]),
        ]
        coverage = task_result.get("coverage")
        if isinstance(coverage, Mapping):
            rows.append(("Coverage line-rate delta", f"{coverage['line_rate_delta']:+.4f}"))
        presentation.print_properties(title, rows, **_human_options(args))
        findings: list[dict[str, object]] = []
        for invariant in task_result.get("invariants", []):
            if isinstance(invariant, Mapping) and invariant.get("state") != "declared-evidence-fresh":
                findings.append(
                    {
                        "level": "review",
                        "id": invariant.get("id", "invariant"),
                        "message": invariant.get("state", "unknown"),
                    }
                )
        for item in task_result.get("contract_violations", []):
            findings.append({"level": "error", "id": "contract-violation", "message": item["detail"]})
        for item in task_result.get("evidence_gaps", []):
            findings.append({"level": "review", "id": "evidence-gap", "message": item["detail"]})
        for item in task_result.get("warnings", []):
            findings.append({"level": "warning", "id": "warning", "message": item["detail"]})
        if findings:
            presentation.print_findings(
                "Assurance findings",
                findings,
                clean_message="No assurance findings.",
                **_human_options(args),
            )
        if task_result.get("safe_halt", {}).get("required") or task_result.get("halt_reasons"):
            presentation.print_message(
                "Safe halt",
                "Preserve work; refresh or supply the named evidence before claiming completion.",
                outcome="warning",
                **_human_options(args),
            )
    return bool(task_result["completed"] or task_result["contract_status"] != "completed")


def _task_init(args: argparse.Namespace) -> None:
    paths = assurance.initialise_task(args.repo, force=args.force, dry_run=args.dry_run)
    prefix = "would create" if args.dry_run else "created"
    presentation.print_properties(
        "Task assurance initialisation",
        (("Task contract", f"{prefix}: {paths['contract']}"), ("Evidence ledger example", paths["evidence_example"])),
        **_human_options(args),
    )


def _task_establish(args: argparse.Namespace) -> None:
    result = assurance.establish_contract(args.repo, args.home, dry_run=args.dry_run)
    if args.format == "json":
        print(json.dumps(result, indent=2, sort_keys=True))
        return
    action = "would establish" if args.dry_run else "established"
    notes = () if args.dry_run else (
        "Interactive confirmation completed. Supported agent-issued establishment commands are blocked by deterministic command policy; local filesystem control remains outside this boundary.",
    )
    presentation.print_properties(
        "Task contract",
        (("Action", action), ("Digest", result["contract_digest"])),
        notes=notes,
        **_human_options(args),
    )


def _component_inspect(args: argparse.Namespace) -> bool:
    result = components.inspect(args.path)
    if args.format == "json":
        print(json.dumps(result, indent=2, sort_keys=True))
        return not any(item["level"] == "error" for item in result["findings"])
    presentation.print_properties(
        "Component inspection",
        (
            ("Component type", result["component_type"]),
            ("Digest", result["component_digest"]),
            ("Files inspected", result["files_inspected"]),
            ("Entry document", result["entry_document"] or "not found"),
        ),
        **_human_options(args),
    )
    presentation.print_findings(
        "Inspection findings",
        result["findings"],
        clean_message="No structural or high-confidence indicators found; this is not a safety guarantee.",
        **_human_options(args),
    )
    return not any(item["level"] == "error" for item in result["findings"])


def _component_audit(args: argparse.Namespace) -> bool:
    result = components.audit(args.home, repo=args.repo)
    if args.format == "json":
        print(json.dumps(result, indent=2, sort_keys=True))
        return not any("error" in item for item in result["components"])
    if result["components"]:
        presentation.print_records(
            "Component audit",
            ("State", "Path", "Type / error"),
            (
                (item["state"], item["path"], item.get("component_type", item.get("error", "component")))
                for item in result["components"]
            ),
            outcome_column=0,
            **_human_options(args),
        )
    else:
        presentation.print_message(
            "Component audit",
            "No known component locations were present beneath the selected home.",
            outcome="warning",
            **_human_options(args),
        )
    presentation.print_message(
        "Limitation",
        result["limitation"],
        outcome="warning",
        **_human_options(args),
    )
    return not any("error" in item for item in result["components"])


def _component_trust(args: argparse.Namespace) -> None:
    record = components.trust(
        args.path,
        args.home,
        expires_at=args.expires_at,
        source=args.source,
        version_reference=args.version_reference,
        reviewed_by=args.reviewed_by,
        permission_tier=args.permission_tier,
        dry_run=args.dry_run,
    )
    if args.format == "json":
        print(json.dumps(record, indent=2, sort_keys=True))
        return
    presentation.print_properties(
        "Trust preview" if args.dry_run else "Trusted component",
        (
            ("Digest", record["component_digest"]),
            ("Expires", record["expires_at"]),
            ("Permission tier", record["permission_tier"]),
        ),
        notes=("Trust is local and digest-bound; it does not grant runtime authority.",),
        **_human_options(args),
    )


def _component_list(args: argparse.Namespace) -> None:
    values = components.list_trust(args.home)
    if args.format == "json":
        print(json.dumps({"schema_version": 1, "components": values}, indent=2, sort_keys=True))
        return
    presentation.print_records(
        "Component trust records",
        ("Status", "Digest", "Details"),
        (
            (
                value["trust_status"],
                value["component_digest"],
                f"type={value['component_type']}\nexpires={value['expires_at']}",
            )
            for value in values
        ),
        outcome_column=0,
        empty_message="No local component trust records.",
        **_human_options(args),
    )


def _component_revoke(args: argparse.Namespace) -> None:
    changed = components.revoke(args.digest, args.home, dry_run=args.dry_run)
    value = {"schema_version": 1, "digest": args.digest, "revoked": changed, "dry_run": args.dry_run}
    if args.format == "json":
        print(json.dumps(value, indent=2, sort_keys=True))
        return
    presentation.print_message(
        "Component trust",
        ("Would revoke" if args.dry_run else "Revoked") if changed else "Trust record not found or already revoked",
        outcome="warning" if args.dry_run or not changed else "passed",
        **_human_options(args),
    )


def _skills_audit(args: argparse.Namespace) -> bool:
    result = components.skills_audit(args.path)
    if args.format == "json":
        print(json.dumps(result, indent=2, sort_keys=True))
        return bool(result["audit_complete"]) and not any(item["level"] == "error" for item in result["findings"])
    presentation.print_skills_audit(
        result,
        no_color=args.no_color,
        ascii_only=_human_ascii_only(),
    )
    return bool(result["audit_complete"]) and not any(item["level"] == "error" for item in result["findings"])


def _statusline_products(value: str) -> tuple[str, ...]:
    return terminal_ux.STATUSLINE_PRODUCTS if value == "all" else (value,)


def _print_value(value: Mapping[str, Any], args: argparse.Namespace) -> None:
    if args.format == "json":
        print(json.dumps(value, indent=2, sort_keys=True))
        return
    rows = []
    for product, details in value.get("products", value).items():
        if isinstance(details, Mapping):
            state_value = details.get("state", details.get("integration", "configured"))
            profile = details.get("profile")
            note = details.get("note") or details.get("manual_step") or details.get("capability")
            rows.append((product, state_value, profile or "not applicable", note or "none"))
    presentation.print_records(
        "Terminal UX",
        ("Product", "State / integration", "Profile", "Notes"),
        rows,
        outcome_column=1,
        **_human_options(args),
    )


def _statusline_capabilities(args: argparse.Namespace) -> None:
    value = {
        "schema_version": 1,
        "products": {
            "claude": {"integration": "managed", "capability": "documented command-based statusLine; activation requires workspace trust and is disabled by disableAllHooks"},
            "codex": {"integration": "managed-native", "capability": "documented tui.status_line edit with current exact item IDs; no documented arbitrary external renderer"},
            "cursor": {"integration": "native-manual", "capability": "documented /status-indicators terminal-title control; programmable usage bar unsupported"},
        },
    }
    _print_value(value, args)


def _statusline_preview(args: argparse.Namespace) -> None:
    products = _statusline_products(args.product)
    values = {
        product: terminal_ux.statusline_preview(product, args.profile, ascii_only=args.format != "json" and _human_ascii_only())
        for product in products
    }
    if args.format == "json":
        print(json.dumps({"schema_version": 1, "products": values}, indent=2, sort_keys=True))
        return
    rows = []
    for product, value in values.items():
        example = value.get("example")
        fields = value.get("native_fields")
        preview = example if isinstance(example, str) else ", ".join(fields) if isinstance(fields, list) else "none"
        rows.append((product, value["integration"], preview, value["note"]))
    presentation.print_records(
        "Terminal UX preview",
        ("Product", "Integration", "Preview / native fields", "Notes"),
        rows,
        **_human_options(args),
    )


def _statusline_install(args: argparse.Namespace) -> None:
    # Status-line installation is an installation transaction, so use the same
    # resource/build preflight as the ordinary consumer installer.
    if args.format == "json":
        with contextlib.redirect_stdout(io.StringIO()):
            install.prepare_installation(dry_run=args.dry_run, home=args.home)
            report = install.statusline_install(
                _statusline_products(args.product), args.home, profile=args.profile, force=args.force, dry_run=args.dry_run
            )
    else:
        details = io.StringIO()
        with contextlib.redirect_stdout(details):
            install.prepare_installation(dry_run=args.dry_run, home=args.home)
            report = install.statusline_install(
                _statusline_products(args.product), args.home, profile=args.profile, force=args.force, dry_run=args.dry_run
            )
    if args.format == "json":
        print(json.dumps(report, indent=2, sort_keys=True))
        return
    if details.getvalue():
        presentation.print_operation_log("Terminal UX changes", details.getvalue(), **_human_options(args))
    presentation.print_records(
        "Terminal UX preview" if args.dry_run else "Terminal UX installed",
        ("Product", "Integration", "Profile", "Manual step"),
        (
            (
                product,
                entry["integration"],
                entry["profile"],
                entry.get("manual_step", "none").splitlines()[0],
            )
            for product, entry in report["products"].items()
        ),
        **_human_options(args),
    )
    if args.dry_run:
        presentation.print_message("Dry run", "No changes were made.", outcome="warning", **_human_options(args))


def _statusline_status(args: argparse.Namespace) -> None:
    _print_value({"products": install.statusline_status(_statusline_products(args.product), args.home)}, args)


def _events_summary(args: argparse.Namespace) -> None:
    summary = terminal_ux.audit_summary(args.home, window=args.window, product=args.product)
    terminal_ux.refresh_audit_summary_cache(args.home)
    if args.format == "json":
        print(json.dumps(summary, indent=2, sort_keys=True))
    else:
        presentation.print_properties(
            "Guardrail events",
            (
                ("Window", summary["window"]),
                ("Warnings", summary["warnings"]),
                ("Denials", summary["denials"]),
                ("Last recorded event", summary["last_event_at"] or "none"),
            ),
            **_human_options(args),
        )


def _activity(args: argparse.Namespace) -> None:
    product = None if args.product == "all" else args.product
    summary = terminal_ux.audit_summary(args.home, window=args.since, product=product)
    terminal_ux.refresh_audit_summary_cache(args.home)
    value = {
        **summary,
        "repository_filter": "not-recorded; all local events in the selected time window are shown",
        "coverage": {
            "hook_products": ["codex", "claude", "cursor", "vscode"],
            "no_deterministic_hook_events_expected": ["visualstudio", "jetbrains"],
        },
    }
    if args.format == "json":
        print(json.dumps(value, indent=2, sort_keys=True))
        return
    presentation.print_properties(
        "Guardrail activity",
        (
            ("Window", summary["window"]),
            ("Observed", summary["observed"]),
            ("Warnings", summary["warnings"]),
            ("Denials", summary["denials"]),
            (
                "Operation classes",
                ", ".join(f"{name}={count}" for name, count in summary["operation_classes"].items()) or "none",
            ),
            ("Rules", ", ".join(f"{name}={count}" for name, count in summary["rule_ids"].items()) or "none"),
            ("Last recorded event", summary["last_event_at"] or "none"),
        ),
        notes=("Visual Studio and JetBrains have no deterministic hook events.",),
        **_human_options(args),
    )


def _complexity(args: argparse.Namespace) -> None:
    report_options = (
        args.baseline_sarif,
        args.current_sarif,
        args.baseline_coverage,
        args.current_coverage,
        args.junit,
    )
    if args.complexity_mode == "compare" or any(report_options):
        if not any(report_options):
            raise GuardrailsError("complexity compare requires at least one supplied SARIF, Cobertura, or JUnit report")
        if args.write_snapshot:
            raise GuardrailsError("complexity report comparison does not write a terminal status snapshot")
        result = assurance.compare_reports(
            args.repo,
            baseline_sarif=args.baseline_sarif,
            current_sarif=args.current_sarif,
            baseline_coverage=args.baseline_coverage,
            current_coverage=args.current_coverage,
            junit=args.junit,
        )
        if args.format == "json":
            print(json.dumps(result, indent=2, sort_keys=True))
            return
        rows = []
        sarif = result["reports"].get("sarif")
        if isinstance(sarif, Mapping):
            rows.append(
                (
                    "SARIF",
                    f"{sarif['new_findings']} new, {sarif['resolved_findings']} resolved, "
                    f"{sarif['unchanged_findings']} unchanged",
                )
            )
        coverage = result["reports"].get("cobertura")
        if isinstance(coverage, Mapping):
            rows.append(("Coverage line-rate delta", f"{coverage['line_rate_delta']:+.4f}"))
        junit = result["reports"].get("junit")
        if isinstance(junit, Mapping):
            rows.append(("JUnit", f"{junit['tests']} tests, {junit['failures']} failures, {junit['errors']} errors"))
        presentation.print_properties(
            "Maintainability evidence comparison",
            rows,
            **_human_options(args),
        )
        if result["findings"]:
            presentation.print_findings(
                "Comparison findings",
                (
                    {"level": "review", "id": finding["id"], "message": finding["evidence"]}
                    for finding in result["findings"]
                ),
                clean_message="No comparison findings.",
                **_human_options(args),
            )
        return
    result = complexity.analyse(args.repo, base=args.base, staged=args.staged)
    if args.write_snapshot:
        complexity.write_cache(args.home, result, dry_run=False)
    if args.format == "json":
        print(json.dumps(result, indent=2, sort_keys=True))
        return
    presentation.print_properties(
        "KISS complexity",
        (
            ("Classification", result["classification"]),
            ("Available", "yes" if result.get("available") else "no"),
            ("Limitation", result.get("limitation") or "none"),
        ),
        **_human_options(args),
    )
    presentation.print_records(
        "Complexity signals",
        ("Signal", "Evidence"),
        (
            (
                signal.get("id", "signal") if isinstance(signal, Mapping) else "signal",
                signal.get("evidence", signal.get("id", "signal")) if isinstance(signal, Mapping) else signal,
            )
            for signal in result.get("signals", [])
        ),
        empty_message="No complexity signals.",
        **_human_options(args),
    )


def _receipt(args: argparse.Namespace) -> None:
    receipt = scan.session_receipt(args.home, args.repo, selected_products(args.product))
    output_format = _selected_output_format(args)
    if output_format == "json":
        print(json.dumps(receipt, indent=2, sort_keys=True))
        return
    if output_format == "compact":
        events = receipt["guardrail_events"]
        files_changed = receipt["files_modified_count"]
        presentation.print_properties(
            ("[G] Change summary" if _human_ascii_only() else "🛡 Change summary") if args.fun else "Change summary",
            (
                ("Repository", receipt["repository_identifier_hash"][:12]),
                ("Products", ", ".join(receipt["products"])),
                ("Files changed", files_changed if files_changed is not None else "unavailable"),
                ("Guardrails", f"{events['warnings']} warning(s), {events['denials']} denial(s) in {events['window']}"),
                ("Complexity", receipt["complexity"]["classification"]),
                ("Routing", ", ".join(f"{name}={profile}" for name, profile in receipt["model_routing_profiles"].items())),
                ("Policy", str(receipt["policy_digest"])[:12]),
                ("Verification gaps", "; ".join(receipt["unverified_checks"]) or "none"),
            ),
            **_human_options(args),
        )
        return
    presentation.print_json_human(
        ("[G] Repository/change receipt" if _human_ascii_only() else "🛡 Repository/change receipt") if args.fun else "Repository/change receipt",
        receipt,
        **_human_options(args),
    )


def _print_repository_scan(args: argparse.Namespace, findings: Sequence[scan.Finding]) -> None:
    presentation.print_properties(
        "Repository scan",
        (
            ("Repository", args.repo.resolve(strict=False)),
            ("Semantic analysis", "not claimed"),
            ("Errors", sum(item.level == "error" for item in findings)),
            ("Warnings", sum(item.level == "warning" for item in findings)),
            ("Notes", sum(item.level == "note" for item in findings)),
        ),
        notes=("Conservative static checks only; no YAML, Rego, shell, SQL, or schema semantic parser is claimed.",),
        **_human_options(args),
    )
    presentation.print_findings(
        "Scan findings",
        (item.as_dict() for item in findings),
        clean_message="No findings.",
        **_human_options(args),
    )


def _demo(args: argparse.Namespace) -> None:
    policy_data = policy.load_enforcement_policy()
    metadata = {
        "safety_profile": "infrastructure-observe", "trust_mode": "trusted-workspace", "home_directory": None,
        "audit_directory": None, "waiver_directory": None, "targets_path": None, "state_path": None, "managed_paths": [],
    }
    scenarios = {
        "core": ("git status", "git reset --hard", "git push origin feature/example", "git push --force-with-lease"),
        "development": ("npm test", "npm publish"),
        "infrastructure": ("terraform plan", "terraform destroy", "kubectl get pods", "kubectl delete namespace payments", "helm template demo", "helm uninstall demo"),
    }
    selected_scenarios = scenarios if args.scenario == "all" else ({args.scenario: scenarios[args.scenario]} if args.scenario in scenarios else {})
    rendered = {
        scenario: [
            {
                "synthetic": True,
                "command": command,
                "decision": enforcement.evaluate_request(
                    {"hook_event_name": "PreToolUse", "tool_name": "shell", "tool_input": {"command": command}},
                    policy_data=policy_data,
                    metadata=metadata,
                ).decision,
            }
            for command in commands
        ]
        for scenario, commands in selected_scenarios.items()
    }
    if args.scenario in {"all", "spacelift"}:
        requests = (("read-only run inspection", "mcp__spacelift__query"), ("run confirmation", "mcp__spacelift__confirm_stack_run"), ("mutation tool", "mcp__spacelift__mutate"))
        rendered["spacelift"] = [
            {
                "synthetic": True,
                "operation": label,
                "decision": enforcement.evaluate_request(
                    {"hook_event_name": "PreToolUse", "tool_name": tool, "tool_input": {"operation": "synthetic"}},
                    policy_data=policy_data,
                    metadata=metadata,
                ).decision,
            }
            for label, tool in requests
        ]
    if args.scenario == "all":
        rendered["statusline"] = [
            {
                "synthetic": True,
                "profile": profile,
                "line": terminal_ux.statusline_preview("claude", profile, ascii_only=args.format != "json" and _human_ascii_only())["example"],
            }
            for profile in terminal_ux.STATUSLINE_PROFILES
        ]
        rendered["complexity"] = [
            {"synthetic": True, "classification": "clear", "signal_ids": []},
            {"synthetic": True, "classification": "review", "signal_ids": ["large-change-surface"]},
            {"synthetic": True, "classification": "high-change", "signal_ids": ["high-risk-governance-files"]},
        ]
    value = {"schema_version": 1, "synthetic": True, "scenarios": rendered, "note": "Synthetic demonstration only; no displayed command was executed."}
    if args.format == "json":
        print(json.dumps(value, indent=2, sort_keys=True))
        return
    human_options = _human_options(args)
    ascii_only = human_options["ascii_only"]
    header = "[G] Synthetic demonstration" if ascii_only else "🛡 Synthetic demonstration"
    separator = " - " if ascii_only else " — "
    for name, section in rendered.items():
        rows = []
        for item in section:
            if "decision" in item:
                label = item.get("command", item.get("operation", "synthetic"))
                rows.append((label, item["decision"].upper() if item["decision"] != "no-decision" else "ALLOW", "synthetic"))
            elif "line" in item:
                rows.append((item["profile"], item["line"], "status line"))
            else:
                label = "OK" if item["classification"] == "clear" else item["classification"]
                rows.append((f"KISS {label}", ", ".join(item["signal_ids"]) or "no signals", "complexity"))
        presentation.print_records(
            f"{header if args.fun else 'Synthetic demonstration'}{separator}{name}",
            ("Scenario", "Result", "Kind"),
            rows,
            outcome_column=1 if all("decision" in item for item in section) else None,
            **human_options,
        )
    presentation.print_message(
        "Safety note",
        "No displayed command was executed.",
        outcome="passed",
        **human_options,
    )


def create_parser() -> argparse.ArgumentParser:
    parser = RichArgumentParser(description="Vendor-neutral AI engineering guardrails")
    parser.add_argument("--version", action="version", version=f"ai-engineering-guardrails {__version__}")
    parser.add_argument("--no-color", action="store_true", help="disable terminal colour in human output")
    sub = parser.add_subparsers(dest="command", required=True, metavar="COMMAND")

    build_parser = sub.add_parser("build", help="build deterministic generated adapters")
    add_product(build_parser)
    validate_parser = sub.add_parser("validate", help="validate canonical and generated data")
    add_product(validate_parser)
    validate_parser.add_argument("--format", choices=("human", "json"), default="human")
    add_no_color(validate_parser)

    install_parser = sub.add_parser("install", help="install into a selected user home")
    add_product(install_parser, detect_by_default=True)
    add_home(install_parser)
    add_mutation_flags(install_parser)
    add_install_options(install_parser)
    install_parser.add_argument("--verbose", action="store_true", help="show internal build and adapter details")

    update_parser = sub.add_parser("update", help="atomically update an existing installation")
    add_product(update_parser, detect_by_default=True)
    add_home(update_parser)
    add_mutation_flags(update_parser)
    update_parser.add_argument("--statusline-profile", choices=terminal_ux.STATUSLINE_PROFILES, default=None)
    update_parser.add_argument("--verbose", action="store_true", help="show internal build and adapter details")

    uninstall_parser = sub.add_parser("uninstall", help="remove only managed installation content")
    add_product(uninstall_parser, detect_by_default=True)
    add_home(uninstall_parser)
    add_mutation_flags(uninstall_parser)

    status_parser = sub.add_parser("status", help="inspect installation status without mutation")
    add_product(status_parser, detect_by_default=True)
    add_home(status_parser)
    status_parser.add_argument("--show-routing", action="store_true")
    status_parser.add_argument("--repo", type=Path)
    status_parser.add_argument("--format", choices=("human", "json"), default="human")
    add_no_color(status_parser)

    doctor_parser = sub.add_parser("doctor", help="check repository and installation consistency")
    add_product(doctor_parser)
    add_home(doctor_parser)

    effective_parser = sub.add_parser("effective", help="show effective profiles, packs, and runtime digests")
    add_product(effective_parser)
    add_home(effective_parser)
    effective_parser.add_argument("--repo", type=Path)
    effective_parser.add_argument(
        "--format",
        choices=("human", "json"),
        default="json",
        help="output format; JSON remains the compatibility default",
    )
    add_no_color(effective_parser)

    diff_parser = sub.add_parser("diff-installed", help="compare managed paths to installation state")
    add_product(diff_parser)
    add_home(diff_parser)

    for name in ("explain", "simulate"):
        explain_parser = sub.add_parser(name, help="explain a deterministic decision without execution")
        explain_parser.add_argument("--product", choices=PRODUCTS, default="codex")
        add_home(explain_parser)
        group = explain_parser.add_mutually_exclusive_group(required=True)
        group.add_argument("--command", dest="command_text", help="shell command text to inspect but never run")
        group.add_argument("--tool", dest="tool_name", help="structured/MCP tool name to inspect but never call")
        explain_parser.add_argument("--tool-arguments", default="{}", help="structured arguments as JSON; values are never printed")
        explain_parser.add_argument("--repo", type=Path, default=Path.cwd())
        explain_parser.add_argument("--pack", action="append", default=[])
        explain_parser.add_argument("--safety-profile", choices=SAFETY_PROFILES, default="infrastructure-observe")
        explain_parser.add_argument("--trust-mode", choices=TRUST_MODES, default="trusted-workspace")
        explain_parser.add_argument("--format", choices=("human", "json"), default="human")

    scan_parser = sub.add_parser("scan", help="conservatively scan a repository")
    scan_parser.add_argument("--repo", type=Path, required=True)
    scan_parser.add_argument("--format", choices=("human", "json", "sarif", "junit"), default="human")
    scan_parser.add_argument("--output", type=Path)

    docs_parser = sub.add_parser("docs", help="run advisory technical-writing checks")
    docs_sub = docs_parser.add_subparsers(dest="docs_command", required=True)
    docs_audit = docs_sub.add_parser("audit", help="audit Markdown clarity without rewriting text")
    docs_scope = docs_audit.add_mutually_exclusive_group()
    docs_scope.add_argument("--repo", type=Path)
    docs_scope.add_argument("--path", type=Path)
    docs_audit.add_argument("--format", choices=("human", "json"), default="human")

    packs_parser = sub.add_parser("packs", help="list, detect, explain, or validate capability packs")
    packs_sub = packs_parser.add_subparsers(dest="packs_command", required=True)
    packs_sub.add_parser("list")
    for name in ("detect", "explain"):
        selected = packs_sub.add_parser(name)
        selected.add_argument("--repo", type=Path, required=True)
    packs_sub.add_parser("validate")

    routing_parser = sub.add_parser("routing", help="show, validate, or explicitly set model routing")
    routing_sub = routing_parser.add_subparsers(dest="routing_command", required=True)
    routing_show = routing_sub.add_parser("show")
    add_product(routing_show)
    routing_show.add_argument("--profile", choices=("economy", "balanced", "quality"), default="balanced")
    routing_sub.add_parser("validate")
    routing_set = routing_sub.add_parser("set")
    routing_set.add_argument("profile", choices=("none", "economy", "balanced", "quality"))
    add_product(routing_set)
    add_home(routing_set)
    add_mutation_flags(routing_set)
    routing_set.add_argument("--model-override", action="append", default=[], metavar="PRODUCT:TIER=MODEL")

    cursor_parser = sub.add_parser("print-cursor-rules", help="print generated Cursor User Rules")
    cursor_parser.add_argument("--clipboard", action="store_true")
    add_home(cursor_parser)

    jetbrains_parser = sub.add_parser("jetbrains", help="print or explicitly export JetBrains guidance")
    jetbrains_sub = jetbrains_parser.add_subparsers(dest="jetbrains_command", required=True)
    chat_instructions = jetbrains_sub.add_parser("print-chat-instructions")
    chat_instructions.add_argument("--clipboard", action="store_true")
    add_home(chat_instructions)
    project_rules = jetbrains_sub.add_parser("export-project-rules")
    project_rules.add_argument("--repo", type=Path, required=True)
    add_home(project_rules)
    add_mutation_flags(project_rules)

    waiver_parser = sub.add_parser("waiver", help="manage local, expiring, interactively confirmed waivers")
    waiver_sub = waiver_parser.add_subparsers(dest="waiver_command", required=True)
    waiver_create = waiver_sub.add_parser("create", help="interactively create a bounded local waiver (mutates local state)")
    add_home(waiver_create)
    waiver_create.add_argument("--rule-id", required=True)
    waiver_create.add_argument("--repo", type=Path, default=Path.cwd())
    waiver_create.add_argument("--target-scope", required=True)
    waiver_create.add_argument("--digest", required=True)
    waiver_create.add_argument("--reason", required=True)
    waiver_create.add_argument("--change-reference", required=True)
    waiver_create.add_argument("--expires-minutes", type=int, default=15)
    waiver_create.add_argument("--maximum-uses", type=int, default=1)
    waiver_list = waiver_sub.add_parser("list", help="list local waiver metadata without mutation")
    add_home(waiver_list)
    waiver_revoke = waiver_sub.add_parser("revoke", help="revoke a local waiver (mutates local state)")
    add_home(waiver_revoke)
    waiver_revoke.add_argument("id")

    policy_parser = sub.add_parser("policy", help="inspect and manage a local policy overlay")
    policy_sub = policy_parser.add_subparsers(dest="policy_command", required=True)
    for name in ("list", "validate", "diff"):
        command = policy_sub.add_parser(name)
        add_home(command)
    policy_show = policy_sub.add_parser("show")
    policy_show.add_argument("rule_id")
    add_home(policy_show)
    policy_init = policy_sub.add_parser("init", help="initialise a local policy overlay (mutates local files)")
    add_home(policy_init)
    add_mutation_flags(policy_init)
    policy_apply = policy_sub.add_parser("apply", help="apply a validated local policy overlay (mutates managed files)")
    add_home(policy_apply)
    add_mutation_flags(policy_apply)
    policy_audit = policy_sub.add_parser("audit", help="audit canonical policy evidence metadata offline")
    policy_audit.add_argument("--format", choices=("human", "json"), default="human")
    policy_evidence = policy_sub.add_parser("evidence", help="show evidence metadata for one canonical policy fragment")
    policy_evidence.add_argument("policy_id")
    policy_evidence.add_argument("--format", choices=("human", "json"), default="human")

    task_parser = sub.add_parser("task", help="create, establish, validate, and report bounded local task assurance")
    task_sub = task_parser.add_subparsers(dest="task_command", required=True)
    task_init = task_sub.add_parser("init", help="create a minimal repository task contract")
    task_init.add_argument("--repo", type=Path, default=Path.cwd())
    add_mutation_flags(task_init)
    task_establish = task_sub.add_parser("establish", help="explicitly establish the reviewed task contract as the local baseline")
    task_establish.add_argument("--repo", type=Path, default=Path.cwd())
    add_home(task_establish)
    task_establish.add_argument(
        "--dry-run",
        action="store_true",
        help="preview task provenance without writing installation state",
    )
    task_establish.add_argument("--format", choices=("human", "json"), default="human")
    task_help = {
        "validate": "validate the task contract and evidence ledger without running checks",
        "status": "report configured local assurance status without running checks",
        "receipt": "emit the existing receipt envelope with optional local task assurance",
    }
    for name in ("validate", "status", "receipt"):
        task_command = task_sub.add_parser(name, help=task_help[name])
        task_command.add_argument("--repo", type=Path, default=Path.cwd())
        add_home(task_command)
        task_command.add_argument("--format", choices=("human", "json"), default="human")

    component_parser = sub.add_parser("component", help="statically inspect components and manage local digest-bound review records")
    component_sub = component_parser.add_subparsers(dest="component_command", required=True)
    component_inspect = component_sub.add_parser("inspect", help="inspect a bounded local component without executing it")
    component_inspect.add_argument("path", type=Path)
    component_inspect.add_argument("--format", choices=("human", "json"), default="human")
    component_audit = component_sub.add_parser("audit", help="audit known local component locations without mutation")
    add_home(component_audit)
    component_audit.add_argument("--repo", type=Path)
    component_audit.add_argument("--format", choices=("human", "json"), default="human")
    component_trust = component_sub.add_parser("trust", help="interactively create a digest-bound review record (mutates local state)")
    component_trust.add_argument("path", type=Path)
    add_home(component_trust)
    component_trust.add_argument("--expires-at", required=True, help="future ISO-8601 timestamp, at most one year away")
    component_trust.add_argument("--source", required=True, help="operator-provided provenance label")
    component_trust.add_argument("--version-reference", default="local", help="operator-provided version or reference")
    component_trust.add_argument("--reviewed-by", default=None, help="reviewer label (defaults to the local account name)")
    component_trust.add_argument("--permission-tier", default="review-only", help="operator-provided review classification; it grants no authority")
    component_trust.add_argument(
        "--dry-run",
        action="store_true",
        help="preview the trust record without writing installation state",
    )
    component_trust.add_argument("--format", choices=("human", "json"), default="human")
    component_list = component_sub.add_parser("list", help="list local component review records without mutation")
    add_home(component_list)
    component_list.add_argument("--format", choices=("human", "json"), default="human")
    component_revoke = component_sub.add_parser("revoke", help="revoke a local component review record (mutates local state)")
    component_revoke.add_argument("digest")
    add_home(component_revoke)
    component_revoke.add_argument(
        "--dry-run",
        action="store_true",
        help="preview revocation without writing installation state",
    )
    component_revoke.add_argument("--format", choices=("human", "json"), default="human")

    skills_parser = sub.add_parser("skills", help="audit portable skill structure and estimated context size")
    skills_sub = skills_parser.add_subparsers(dest="skills_command", required=True)
    skills_audit = skills_sub.add_parser("audit")
    skills_audit.add_argument("--path", type=Path)
    skills_audit.add_argument("--format", choices=("human", "json"), default="human")
    add_no_color(skills_audit)

    receipt_parser = sub.add_parser("receipt", help="emit a content-free local session receipt")
    add_home(receipt_parser)
    add_product(receipt_parser)
    receipt_parser.add_argument("--repo", type=Path, default=Path.cwd())
    receipt_parser.add_argument("--format", choices=("json", "human", "compact"))
    receipt_parser.add_argument("--compact", action="store_true", help="print a concise repository/change summary")
    receipt_parser.add_argument("--fun", action="store_true", help="add restrained symbols to human receipt output")
    add_no_color(receipt_parser)

    statusline_parser = sub.add_parser("statusline", help="manage optional terminal UX integrations")
    statusline_sub = statusline_parser.add_subparsers(dest="statusline_command", required=True)
    for name in ("capabilities", "status"):
        command = statusline_sub.add_parser(name)
        command.add_argument("--product", choices=(*terminal_ux.STATUSLINE_PRODUCTS, "all"), default="all")
        add_home(command)
        command.add_argument("--format", choices=("human", "json"), default="human")
        add_no_color(command)
    preview = statusline_sub.add_parser("preview")
    preview.add_argument("--product", choices=(*terminal_ux.STATUSLINE_PRODUCTS, "all"), default="all")
    preview.add_argument("--profile", choices=terminal_ux.STATUSLINE_PROFILES, default="standard")
    preview.add_argument("--format", choices=("human", "json"), default="human")
    add_no_color(preview)
    install_statusline = statusline_sub.add_parser("install")
    install_statusline.add_argument("--product", choices=(*terminal_ux.STATUSLINE_PRODUCTS, "all"), default="all")
    install_statusline.add_argument("--profile", choices=terminal_ux.STATUSLINE_PROFILES, required=True)
    add_home(install_statusline)
    add_mutation_flags(install_statusline)
    install_statusline.add_argument("--format", choices=("human", "json"), default="human")
    add_no_color(install_statusline)
    uninstall_statusline = statusline_sub.add_parser("uninstall")
    uninstall_statusline.add_argument("--product", choices=(*terminal_ux.STATUSLINE_PRODUCTS, "all"), default="all")
    add_home(uninstall_statusline)
    add_mutation_flags(uninstall_statusline)
    uninstall_statusline.add_argument("--format", choices=("human", "json"), default="human")
    add_no_color(uninstall_statusline)
    codex_setup = statusline_sub.add_parser("print-codex-setup")
    codex_setup.add_argument("--profile", choices=terminal_ux.STATUSLINE_PROFILES, default="standard")
    cursor_setup = statusline_sub.add_parser("print-cursor-setup")

    events_parser = sub.add_parser("events", help="summarise local content-free guardrail events")
    events_sub = events_parser.add_subparsers(dest="events_command", required=True)
    events_summary = events_sub.add_parser("summary")
    add_home(events_summary)
    events_summary.add_argument("--window", choices=("today", "24h"), default="24h")
    events_summary.add_argument("--product", choices=PRODUCTS)
    events_summary.add_argument("--format", choices=("human", "json"), default="human")

    complexity_parser = sub.add_parser("complexity", help="report deterministic repository-change complexity signals")
    complexity_parser.add_argument("complexity_mode", nargs="?", choices=("compare",))
    complexity_parser.add_argument("--repo", type=Path, default=Path.cwd())
    complexity_parser.add_argument("--base")
    complexity_parser.add_argument("--staged", action="store_true")
    complexity_parser.add_argument("--baseline-sarif", type=Path)
    complexity_parser.add_argument("--current-sarif", type=Path)
    complexity_parser.add_argument("--baseline-coverage", type=Path)
    complexity_parser.add_argument("--current-coverage", type=Path)
    complexity_parser.add_argument("--junit", type=Path)
    complexity_parser.add_argument("--format", choices=("human", "json"), default="human")
    complexity_parser.add_argument("--write-snapshot", "--write-cache", dest="write_snapshot", action="store_true", help="write only a compact local status snapshot")
    add_home(complexity_parser)
    add_no_color(complexity_parser)

    activity_parser = sub.add_parser("activity", help="summarise content-free local guardrail activity")
    activity_parser.add_argument("--since", choices=("1h", "24h", "7d"), default="24h")
    activity_parser.add_argument("--product", choices=(*PRODUCTS, "all"), default="all")
    activity_parser.add_argument("--repo", type=Path, default=Path.cwd(), help="accepted for consistent repository-scoped workflows; audit events do not store repository identity")
    add_home(activity_parser)
    activity_parser.add_argument("--format", choices=("human", "json"), default="human")
    add_no_color(activity_parser)

    demo_parser = sub.add_parser("demo", help="show an entirely synthetic guardrails demonstration")
    demo_parser.add_argument("--scenario", choices=("all", "core", "development", "infrastructure", "spacelift"), default="all")
    demo_parser.add_argument("--format", choices=("human", "json"), default="human")
    demo_parser.add_argument("--fun", action="store_true", help="add restrained symbols to synthetic human output")
    add_no_color(demo_parser)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    if sys.version_info < (3, 11):
        print("error: Python 3.11 or newer is required", file=sys.stderr)
        return 1
    arguments = list(sys.argv[1:] if argv is None else argv)
    RichArgumentParser.help_no_color = "--no-color" in arguments or "NO_COLOR" in os.environ
    args = create_parser().parse_args(arguments)
    try:
        if args.command == "build":
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                build.build(selected_products(args.product))
            presentation.print_operation_log("Build", output.getvalue(), **_human_options(args))
        elif args.command == "validate":
            output_root = repository_output_root()
            with contextlib.redirect_stdout(io.StringIO()):
                report = build.validate(
                    selected_products(args.product),
                    require_current=output_root is not None,
                    output_root=output_root,
                )
            if args.format == "json":
                print(json.dumps(report, indent=2, sort_keys=True))
            else:
                presentation.print_validation(
                    report,
                    no_color=args.no_color,
                    ascii_only=_human_ascii_only(),
                )
        elif args.command == "install":
            if args.product == "visualstudio" and sys.platform != "win32":
                raise GuardrailsError(
                    "Visual Studio installation is supported only on Windows; build and validation remain cross-platform"
                )
            products, detected = _resolve_consumer_products(args.product, args.home, "install")
            if args.product == "all" and sys.platform != "win32" and "visualstudio" in products:
                products = tuple(product for product in products if product != "visualstudio")
                presentation.print_message(
                    "Product selection",
                    "Visual Studio was skipped: its user-level adapter is supported only on Windows.",
                    outcome="warning",
                    **_human_options(args),
                )
            _run_consumer_install(args, products, detected, updating=False)
        elif args.command == "update":
            products, detected = _resolve_consumer_products(args.product, args.home, "update")
            _run_consumer_install(args, products, detected, updating=True)
        elif args.command == "uninstall":
            products, _ = _resolve_consumer_products(args.product, args.home, "uninstall")
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                install.uninstall(products, args.home, force=args.force, dry_run=args.dry_run)
            presentation.print_operation_log(
                "Uninstall preview" if args.dry_run else "Uninstall",
                output.getvalue(),
                **_human_options(args),
            )
        elif args.command == "status":
            products, _ = _resolve_consumer_products(args.product, args.home, "status")
            with contextlib.redirect_stdout(io.StringIO()):
                report = install.status(
                    products, args.home, show_routing_details=args.show_routing, repo=args.repo
                )
            if args.format == "json":
                print(json.dumps(report, indent=2, sort_keys=True))
            else:
                presentation.print_status(
                    report,
                    no_color=args.no_color,
                    ascii_only=_human_ascii_only(),
                )
        elif args.command == "doctor":
            with contextlib.redirect_stdout(io.StringIO()):
                report = install.doctor(selected_products(args.product), args.home)
            presentation.print_checks(
                "AI Guardrails Doctor",
                report["checks"],
                **_human_options(args),
            )
            if any(check["outcome"] == "fail" for check in report["checks"]):
                return 1
        elif args.command == "effective":
            with contextlib.redirect_stdout(io.StringIO()):
                report = install.effective_configuration(selected_products(args.product), args.home, args.repo)
            if args.format == "json":
                print(json.dumps(report, indent=2, sort_keys=True))
            else:
                presentation.print_json_human(
                    "Effective configuration",
                    report,
                    **_human_options(args),
                )
        elif args.command == "diff-installed":
            with contextlib.redirect_stdout(io.StringIO()):
                report = install.diff_installed(selected_products(args.product), args.home)
            rows = []
            for product, items in report["products"].items():
                if not items:
                    rows.append((product, "not installed", "No managed paths recorded"))
                    continue
                rows.extend((product, item["state"], item["path"]) for item in items)
            presentation.print_records(
                "Installed content diff",
                ("Product", "State", "Path"),
                rows,
                outcome_column=1,
                **_human_options(args),
            )
        elif args.command in {"explain", "simulate"}:
            _explain(args)
        elif args.command == "scan":
            if args.format == "human":
                findings = scan.scan_repository(args.repo)
                if args.output is None:
                    _print_repository_scan(args, findings)
                else:
                    rendered = io.StringIO()
                    with contextlib.redirect_stdout(rendered):
                        _print_repository_scan(args, findings)
                    target = args.output.expanduser().resolve(strict=False)
                    atomic_write(target, rendered.getvalue().encode("utf-8"))
                    presentation.print_message(
                        "Repository scan",
                        f"Report written to {target}",
                        **_human_options(args),
                    )
            else:
                output = io.StringIO()
                with contextlib.redirect_stdout(output):
                    findings, _ = scan.run_scan(args.repo, args.format, args.output)
                print(output.getvalue(), end="")
            if any(item.level == "error" for item in findings):
                return 1
        elif args.command == "docs":
            if args.format == "human":
                root, findings, audited_files = scan.audit_documentation(args.repo, args.path)
                presentation.print_properties(
                    "Documentation audit",
                    (
                        ("Scope", root.resolve(strict=False)),
                        ("Audited Markdown files", audited_files),
                        ("Assessment", "advisory clarity checks; not ASD-STE100 compliance"),
                    ),
                    **_human_options(args),
                )
                presentation.print_findings(
                    "Documentation findings",
                    (item.as_dict() for item in findings),
                    clean_message="No technical-writing findings.",
                    **_human_options(args),
                )
            else:
                scan.run_documentation_audit(args.repo, args.path, args.format)
        elif args.command == "packs":
            if args.packs_command == "list":
                _packs_list(args)
            elif args.packs_command in {"detect", "explain"}:
                _packs_detect(args)
            else:
                count, examples = packs.validate_packs()
                presentation.print_properties(
                    "Capability pack validation",
                    (("Result", "passed"), ("Packs", count), ("Fixtures", examples)),
                    **_human_options(args),
                )
        elif args.command == "routing":
            if args.routing_command == "show":
                _routing_show(args)
            elif args.routing_command == "validate":
                config = routing.load_config()
                presentation.print_properties(
                    "Routing validation",
                    (("Result", "passed"), ("Agents", len(config["agents"])), ("Profiles", len(config["profiles"]))),
                    **_human_options(args),
                )
            else:
                output = io.StringIO()
                with contextlib.redirect_stdout(output):
                    install.set_routing(
                        selected_products(args.product),
                        args.home,
                        args.profile,
                        model_overrides=parse_model_overrides(args.model_override) or None,
                        force=args.force,
                        dry_run=args.dry_run,
                    )
                presentation.print_operation_log(
                    "Routing preview" if args.dry_run else "Routing update",
                    output.getvalue(),
                    **_human_options(args),
                )
        elif args.command == "print-cursor-rules":
            install.print_cursor_rules(clipboard=args.clipboard, home=args.home)
        elif args.command == "jetbrains":
            if args.jetbrains_command == "print-chat-instructions":
                install.print_jetbrains_chat_instructions(clipboard=args.clipboard, home=args.home)
            else:
                output = io.StringIO()
                with contextlib.redirect_stdout(output):
                    install.export_jetbrains_project_rules(
                        args.repo, dry_run=args.dry_run, force=args.force, home=args.home
                    )
                presentation.print_operation_log(
                    "JetBrains project-rule preview" if args.dry_run else "JetBrains project-rule export",
                    output.getvalue(),
                    **_human_options(args),
                )
        elif args.command == "waiver":
            if args.waiver_command == "create":
                _waiver_create(args)
            elif args.waiver_command == "list":
                _waiver_list(args)
            else:
                changed = state.revoke_waiver(args.home, args.id)
                presentation.print_message(
                    "Waiver",
                    "Revoked" if changed else "Waiver not found",
                    outcome="passed" if changed else "warning",
                    **_human_options(args),
                )
        elif args.command == "policy":
            if args.policy_command == "list":
                _policy_list(args)
            elif args.policy_command == "show":
                _policy_show(args)
            elif args.policy_command == "init":
                output = io.StringIO()
                with contextlib.redirect_stdout(output):
                    policy.initialise_local_overlay(args.home, force=args.force, dry_run=args.dry_run)
                presentation.print_operation_log(
                    "Policy initialisation preview" if args.dry_run else "Policy initialisation",
                    output.getvalue(),
                    **_human_options(args),
                )
            elif args.policy_command == "validate":
                _policy_validate(args)
            elif args.policy_command == "diff":
                _policy_diff(args)
            elif args.policy_command == "apply":
                _policy_apply(args)
            elif args.policy_command == "audit":
                if not _policy_audit(args):
                    return 1
            else:
                _policy_evidence(args)
        elif args.command == "task":
            if args.task_command == "init":
                _task_init(args)
            elif args.task_command == "establish":
                _task_establish(args)
            elif args.task_command == "validate":
                _, contract = assurance.load_contract(args.repo)
                if args.format == "json":
                    print(json.dumps({"schema_version": 1, "valid": True, "status": contract["status"]}, indent=2, sort_keys=True))
                else:
                    presentation.print_properties(
                        "Task contract validation",
                        (("Result", "passed"), ("Status", contract["status"])),
                        **_human_options(args),
                    )
            elif not _task_result(args, receipt=args.task_command == "receipt"):
                return 1
        elif args.command == "component":
            if args.component_command == "inspect":
                if not _component_inspect(args):
                    return 1
            elif args.component_command == "audit":
                if not _component_audit(args):
                    return 1
            elif args.component_command == "trust":
                _component_trust(args)
            elif args.component_command == "list":
                _component_list(args)
            else:
                _component_revoke(args)
        elif args.command == "skills":
            if not _skills_audit(args):
                return 1
        elif args.command == "receipt":
            _receipt(args)
        elif args.command == "statusline":
            if args.statusline_command == "capabilities":
                _statusline_capabilities(args)
            elif args.statusline_command == "preview":
                _statusline_preview(args)
            elif args.statusline_command == "install":
                _statusline_install(args)
            elif args.statusline_command == "uninstall":
                if args.format == "json":
                    with contextlib.redirect_stdout(io.StringIO()):
                        report = install.statusline_uninstall(_statusline_products(args.product), args.home, force=args.force, dry_run=args.dry_run)
                    print(json.dumps(report, indent=2, sort_keys=True))
                else:
                    output = io.StringIO()
                    with contextlib.redirect_stdout(output):
                        report = install.statusline_uninstall(_statusline_products(args.product), args.home, force=args.force, dry_run=args.dry_run)
                    outcomes = report["products"]
                    retained = [product for product, outcome in outcomes.items() if outcome == "retained-modified"]
                    removed = [product for product, outcome in outcomes.items() if outcome in {"removed", "would-remove"}]
                    if output.getvalue():
                        presentation.print_operation_log("Terminal UX changes", output.getvalue(), **_human_options(args))
                    if args.dry_run:
                        message = "Preview complete; no changes were made"
                        outcome = "warning"
                    elif retained:
                        message = "Partially complete; retained modified configuration: " + ", ".join(retained)
                        outcome = "warning"
                    elif removed:
                        message = "Uninstalled"
                        outcome = "passed"
                    else:
                        message = "No managed terminal UX configuration was found"
                        outcome = "warning"
                    presentation.print_message("Terminal UX uninstall", message, outcome=outcome, **_human_options(args))
            elif args.statusline_command == "status":
                _statusline_status(args)
            elif args.statusline_command == "print-codex-setup":
                print(terminal_ux.codex_setup(args.profile))
            else:
                print(terminal_ux.cursor_setup())
        elif args.command == "events":
            _events_summary(args)
        elif args.command == "activity":
            _activity(args)
        elif args.command == "complexity":
            _complexity(args)
        elif args.command == "demo":
            _demo(args)
        else:
            raise GuardrailsError(f"unsupported command: {args.command}")
    except (GuardrailsError, OSError, UnicodeError, enforcement.PolicyError) as exc:
        if _selected_output_format(args) in {"human", "compact"}:
            presentation.print_error(exc, no_color=bool(getattr(args, "no_color", False)))
        else:
            print(f"error: {exc}", file=sys.stderr)
        return 1
    return 0
