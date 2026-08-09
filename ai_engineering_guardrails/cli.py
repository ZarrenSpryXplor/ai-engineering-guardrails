"""Command-line interface for AI engineering guardrails."""

from __future__ import annotations

import argparse
import contextlib
import io
import json
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
    routing,
    scan,
    state,
    terminal_ux,
)
from .resources import repository_output_root
from .util import PRODUCTS, SAFETY_PROFILES, TRUST_MODES, GuardrailsError, home_path


def selected_products(value: str) -> tuple[str, ...]:
    return PRODUCTS if value == "all" else (value,)


def add_product(parser: argparse.ArgumentParser, *, detect_by_default: bool = False) -> None:
    default = None if detect_by_default else "all"
    default_help = "detect installed products" if detect_by_default else "all"
    parser.add_argument(
        "--product",
        choices=(*PRODUCTS, "all"),
        default=default,
        help=f"product to manage (default: {default_help})",
    )


def add_home(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--home", type=Path, default=Path.home(), help="selected home directory (default: current user's home)")


def add_mutation_flags(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--dry-run", action="store_true", help="print the change plan without writing")
    parser.add_argument("--force", action="store_true", help="replace or remove modified managed content after backup")


def add_no_color(parser: argparse.ArgumentParser) -> None:
    """Accept the common explicit accessibility preference; output is unstyled today."""
    parser.add_argument("--no-color", action="store_true", help="disable terminal colour (human output is currently unstyled)")


def _human_ascii_only() -> bool:
    """Use the terminal UX ASCII fallback when stdout cannot encode its symbols."""
    encoding = getattr(sys.stdout, "encoding", None) or "ascii"
    try:
        "🛡✓⚠🔥💨▓░".encode(encoding)
    except (LookupError, UnicodeEncodeError):
        return True
    return False


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
    output = contextlib.nullcontext() if args.verbose else contextlib.redirect_stdout(details)
    with output:
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
    install.print_consumer_install_summary(report, detected)


def _routing_show(products: Sequence[str], profile_name: str) -> None:
    config = routing.load_config()
    profile = config["profiles"][profile_name]
    print(f"profile: {profile_name}: {profile['description']}")
    parallel = profile["parallelism"]
    print(f"parallelism: {parallel['maximum_read_only_agents']} read-only, 1 writing, no parallel writers")
    for product in products:
        models = routing.resolved_models(product, config, None)
        print(f"{product}: " + ", ".join(f"{tier}={model}" for tier, model in models.items()))
        print("  availability: unverified; main-session model unchanged")


def _packs_list() -> None:
    for identifier, data in packs.load_packs().items():
        print(f"{identifier}\t{data['type']}\t{data['description']}")


def _packs_detect(repo: Path, explain: bool) -> None:
    result = packs.detect_packs(repo)
    print("detected packs: " + (", ".join(result.active_packs) if result.active_packs else "none"))
    if result.package_manager:
        print(f"Node package manager: {result.package_manager}")
    if result.build_root:
        print(f"configured build root: {result.build_root}")
    if explain:
        for evidence in result.evidence:
            print(f"{evidence.pack_id}: {evidence.kind} {evidence.path} matched {evidence.detector}")
        for warning in result.warnings:
            print(f"warning: {warning}")
        available = packs.load_packs()
        for identifier in result.active_packs:
            guidance = packs.pack_guidance(available[identifier])
            print(f"{identifier}: on-demand policy: {'; '.join(guidance['policy'])}")
            print(f"{identifier}: verification: {'; '.join(guidance['verification'])}")
            print(f"{identifier}: routing hints: {'; '.join(guidance['routing'])}")


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
        print(f"decision: {value['decision']}")
        print(f"rollout mode: {value['rollout_mode']}")
        print(f"rule: {value['rule_id'] or 'none'}")
        print(f"operation class: {value['operation_class'] or 'unclassified'}")
        if value["matched_tokens"]:
            print("matched tokens: " + ", ".join(value["matched_tokens"]))
        if value["matched_fields"]:
            print("matched fields: " + ", ".join(value["matched_fields"]))
        print(f"target: {value['target'] or 'unknown/protected'}")
        print(f"lifecycle: {value['target_lifecycle']}")
        print(f"policy source: {value['policy_source'] or 'none'}")
        print(f"reason: {value['reason'] or 'no deterministic match'}")
        print(f"waiver: {value['applicable_waiver'] or 'none'}")
        print(f"safety profile: {value['safety_profile']}; trust mode: {value['trust_mode']}")
        print("simulation only: no command or tool call was executed")
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
    print(f"created {value['id']} with {value['remaining_uses']} use(s); raw command/tool arguments were not stored")


def _waiver_list(args: argparse.Namespace) -> None:
    values = state.list_waivers(args.home.expanduser().resolve(strict=False))
    if not values:
        print("no local waivers")
    for value in values:
        print(
            f"{value['id']}: rule={value['rule_id']} expires={value['expires_at']} "
            f"remaining={value['remaining_uses']}/{value['maximum_uses']} change={value['change_reference']}"
        )


def _policy_source_label(value: object) -> str:
    source = str(value or "bundled")
    if "/packs/" in source or source.startswith("packs/"):
        return "pack"
    return "local" if source == "local policy overlay" else "bundled"


def _policy_list(args: argparse.Namespace) -> None:
    effective = policy.validate_local_overlay(args.home.expanduser().resolve(strict=False))["policy"]
    for group in ("rules", "classifications", "structured_tool_rules"):
        for rule in effective[group]:
            mode = str(rule.get("rollout_mode", "n/a"))
            print(
                f"{rule['id']}\tsource={_policy_source_label(rule.get('policy_source'))}\t"
                f"operation={rule.get('operation_class', 'unclassified')}\tmode={mode}"
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
    print(f"id: {rule['id']}")
    print(f"description: {rule.get('description', 'operation classification')}")
    print(f"source: {_policy_source_label(rule.get('policy_source'))}")
    print(f"risk category: {rule.get('risk_category', 'not applicable')}")
    print(f"operation class: {rule.get('operation_class', 'unclassified')}")
    print(f"effective rollout mode: {rule.get('rollout_mode', 'n/a')}")
    print(f"local mode strengthening: {'yes' if rule.get('local_mode_strengthening') else 'no'}")
    strategy = rule.get("matching_strategy")
    if isinstance(strategy, Mapping):
        print(f"matching strategy: {strategy.get('type', 'unknown')}")


def _policy_validate(args: argparse.Namespace) -> None:
    result = policy.validate_local_overlay(args.home.expanduser().resolve(strict=False))
    print(
        "local policy validation passed: "
        f"{len(result['fragments'])} behavioural fragment(s), "
        f"{len(result['overlay']['rule_modes'])} mode strengthening(s), "
        f"{len(result['overlay']['additional_rules'])} additional deterministic rule(s)"
    )


def _policy_diff(args: argparse.Namespace) -> None:
    diff = policy.local_policy_diff(args.home.expanduser().resolve(strict=False))
    print("Local policy differences from the bundled baseline")
    for label, values in diff.items():
        print(f"- {label.replace('_', ' ')}: {', '.join(values) if values else 'none'}")


def _policy_apply(args: argparse.Namespace) -> None:
    home = args.home.expanduser().resolve(strict=False)
    policy.validate_local_overlay(home)
    products = install.installed_products(home)
    if not products:
        raise GuardrailsError("no managed installation was found; install a product before applying local policy")
    install.update(products, home, force=args.force, dry_run=args.dry_run)


def _policy_audit(args: argparse.Namespace) -> bool:
    result = evidence.audit_registry(policy.load_manifest(), generated_artifacts=build.build_artifacts())
    if args.format == "json":
        print(json.dumps(result, indent=2, sort_keys=True))
        return not result["errors"]
    print(
        "Policy evidence audit: "
        + ("structural checks passed" if not result["errors"] else "structural issues found")
        + f"; {result['sources']} sources, {result['policy_records']} policy records"
    )
    for item in result["errors"]:
        print(f"error: {item['id']}: {item['detail']}")
    for item in result["reviews"]:
        print(f"review: {item['id']}: {item['detail']}")
    if not result["errors"] and not result["reviews"]:
        print("No evidence review dates are overdue.")
    return not result["errors"]


def _policy_evidence(args: argparse.Namespace) -> None:
    result = evidence.evidence_for_policy(args.policy_id, policy.load_manifest())
    if args.format == "json":
        print(json.dumps(result, indent=2, sort_keys=True))
        return
    metadata = result["policy"]
    print(f"policy: {metadata['id']}")
    print(f"polarity: {metadata['polarity']}; scope: {metadata['scope']}")
    print(f"rationale: {metadata['rationale']}")
    print(f"confidence: {metadata['confidence']}; review after: {metadata['review_after']}")
    for source in result["sources"]:
        print(f"evidence: {source['id']}: {source['title']} ({source['url']})")
    for item in result["review_findings"]:
        print(f"review: {item['detail']}")


def _task_result(args: argparse.Namespace, *, receipt: bool) -> bool:
    result = assurance.task_receipt(args.repo, home=args.home) if receipt else assurance.task_status(args.repo, home=args.home)
    task_result = result["task_assurance"] if receipt else result
    if args.format == "json":
        print(json.dumps(result, indent=2, sort_keys=True))
    else:
        title = "Task receipt" if receipt else "Task status"
        print(f"{title}: {task_result['effective_status']}")
        scope = task_result["scope"]
        if scope["available"]:
            print(
                "  Scope: "
                f"{scope['files_changed']} file(s), {scope['lines_added']} added, {scope['lines_removed']} removed, "
                f"{scope['directories_changed']} directories changed"
            )
        else:
            print("  Scope: unavailable")
        print("  Evidence: " + (", ".join(f"{item['id']}={item['state']}" for item in task_result["evidence"]) or "none required"))
        print(f"  Contract continuity: {task_result['contract_continuity']}")
        coverage = task_result.get("coverage")
        if isinstance(coverage, Mapping):
            print(f"  Coverage line-rate delta: {coverage['line_rate_delta']:+.4f}")
        for invariant in task_result.get("invariants", []):
            if isinstance(invariant, Mapping) and invariant.get("state") != "declared-evidence-fresh":
                print(f"  invariant: {invariant.get('id')}={invariant.get('state')}")
        for item in task_result.get("contract_violations", []):
            print(f"  violation: {item['detail']}")
        for item in task_result.get("evidence_gaps", []):
            print(f"  evidence gap: {item['detail']}")
        for item in task_result.get("warnings", []):
            print(f"  warning: {item['detail']}")
        if task_result.get("safe_halt", {}).get("required") or task_result.get("halt_reasons"):
            print("  Safe halt: preserve work; refresh or supply the named evidence before claiming completion.")
    return bool(task_result["completed"] or task_result["contract_status"] != "completed")


def _task_init(args: argparse.Namespace) -> None:
    paths = assurance.initialise_task(args.repo, force=args.force, dry_run=args.dry_run)
    prefix = "would create" if args.dry_run else "created"
    print(f"{prefix} task contract: {paths['contract']}")
    print(f"evidence ledger example: {paths['evidence_example']}")


def _task_establish(args: argparse.Namespace) -> None:
    result = assurance.establish_contract(args.repo, args.home, dry_run=args.dry_run)
    if args.format == "json":
        print(json.dumps(result, indent=2, sort_keys=True))
        return
    action = "would establish" if args.dry_run else "established"
    print(f"Task contract {action}: {result['contract_digest']}")
    if not args.dry_run:
        print(
            "Interactive confirmation completed. Supported agent-issued establishment commands are blocked by deterministic command policy; local filesystem control remains outside this boundary."
        )


def _component_inspect(args: argparse.Namespace) -> bool:
    result = components.inspect(args.path)
    if args.format == "json":
        print(json.dumps(result, indent=2, sort_keys=True))
        return not any(item["level"] == "error" for item in result["findings"])
    print(f"Component: {result['component_type']}; digest={result['component_digest']}")
    print(f"Files inspected: {result['files_inspected']}; entry: {result['entry_document'] or 'not found'}")
    if not result["findings"]:
        print("No structural or high-confidence indicators found; this is not a safety guarantee.")
    for item in result["findings"]:
        print(f"{item['level']}: {item['id']}: {item['path']}:{item['line']}: {item['message']}")
    return not any(item["level"] == "error" for item in result["findings"])


def _component_audit(args: argparse.Namespace) -> bool:
    result = components.audit(args.home, repo=args.repo)
    if args.format == "json":
        print(json.dumps(result, indent=2, sort_keys=True))
        return not any("error" in item for item in result["components"])
    print("Component audit")
    if not result["components"]:
        print("  No known component locations were present beneath the selected home.")
    for item in result["components"]:
        detail = item.get("component_type", item.get("error", "component"))
        print(f"  {item['state']}: {item['path']} ({detail})")
    print("  " + result["limitation"])
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
    print(("Trust preview" if args.dry_run else "Trusted component") + f": {record['component_digest']}")
    print(f"  expires: {record['expires_at']}; tier: {record['permission_tier']}")


def _component_list(args: argparse.Namespace) -> None:
    values = components.list_trust(args.home)
    if args.format == "json":
        print(json.dumps({"schema_version": 1, "components": values}, indent=2, sort_keys=True))
        return
    if not values:
        print("No local component trust records.")
        return
    for value in values:
        print(f"{value['trust_status']}: {value['component_digest']} ({value['component_type']}); expires={value['expires_at']}")


def _component_revoke(args: argparse.Namespace) -> None:
    changed = components.revoke(args.digest, args.home, dry_run=args.dry_run)
    value = {"schema_version": 1, "digest": args.digest, "revoked": changed, "dry_run": args.dry_run}
    if args.format == "json":
        print(json.dumps(value, indent=2, sort_keys=True))
        return
    print(("would revoke" if args.dry_run else "revoked") if changed else "trust record not found or already revoked")


def _skills_audit(args: argparse.Namespace) -> bool:
    result = components.skills_audit(args.path)
    if args.format == "json":
        print(json.dumps(result, indent=2, sort_keys=True))
        return bool(result["audit_complete"]) and not any(item["level"] == "error" for item in result["findings"])
    print("Skills audit")
    print("  Estimated tokens use " + result["token_estimate_method"] + ".")
    catalogue = result["catalogue"]
    pressure = catalogue["estimated_catalogue_pressure"]
    print(
        f"  Catalogue ({catalogue['scope']}): {catalogue['skill_count']} skill(s), "
        f"{catalogue['total_description_characters']} description characters; "
        f"estimated pressure={pressure['level']} ({pressure['description_only_percent_of_reference']}% description-only reference)"
    )
    exposure_key = "fresh_default" if "fresh_default" in catalogue else "selected_installation"
    exposure = catalogue[exposure_key]
    print(
        f"  {'Fresh default exposure' if exposure_key == 'fresh_default' else 'Selected installation'}: "
        f"{exposure['skill_count']} skill(s), {exposure['description_characters']} description characters; "
        f"estimated pressure={exposure['estimated_pressure']['level']}"
    )
    print("  Catalogue pressure is an estimate; model context and other installed/plugin skills change the actual budget.")
    print("  Tiers: " + ", ".join(f"{name}={count}" for name, count in catalogue["tier_counts"].items()))
    if catalogue["longest_descriptions"]:
        print(
            "  Longest descriptions: "
            + ", ".join(f"{item['name']}={item['characters']}" for item in catalogue["longest_descriptions"])
        )
    for skill in result["skills"]:
        print(
            f"  {skill['name']}: estimated tokens={skill['estimated_tokens']}; "
            f"references={skill['reference_file_count']} ({skill['reference_estimated_tokens']} estimated tokens)"
        )
    for item in result["findings"]:
        print(f"  {item['level']}: {item['id']}: {item['message']}")
    if not result["audit_complete"]:
        print("  Audit incomplete; no clean result is asserted.")
    return bool(result["audit_complete"]) and not any(item["level"] == "error" for item in result["findings"])


def _statusline_products(value: str) -> tuple[str, ...]:
    return terminal_ux.STATUSLINE_PRODUCTS if value == "all" else (value,)


def _print_value(value: Mapping[str, Any], output_format: str) -> None:
    if output_format == "json":
        print(json.dumps(value, indent=2, sort_keys=True))
        return
    for product, details in value.get("products", value).items():
        if isinstance(details, Mapping):
            state_value = details.get("state", details.get("integration", "configured"))
            profile = details.get("profile")
            suffix = f"; profile={profile}" if isinstance(profile, str) else ""
            print(f"{product}: {state_value}{suffix}")
            note = details.get("note") or details.get("manual_step") or details.get("capability")
            if isinstance(note, str):
                print(f"  {note}")


def _statusline_capabilities(args: argparse.Namespace) -> None:
    value = {
        "schema_version": 1,
        "products": {
            "claude": {"integration": "managed", "capability": "documented command-based statusLine; activation requires workspace trust and is disabled by disableAllHooks"},
            "codex": {"integration": "managed-native", "capability": "documented tui.status_line edit with current exact item IDs; no documented arbitrary external renderer"},
            "cursor": {"integration": "native-manual", "capability": "documented /status-indicators terminal-title control; programmable usage bar unsupported"},
        },
    }
    _print_value(value, args.format)


def _statusline_preview(args: argparse.Namespace) -> None:
    products = _statusline_products(args.product)
    values = {
        product: terminal_ux.statusline_preview(product, args.profile, ascii_only=args.format != "json" and _human_ascii_only())
        for product in products
    }
    if args.format == "json":
        print(json.dumps({"schema_version": 1, "products": values}, indent=2, sort_keys=True))
        return
    for product, value in values.items():
        print(f"{product}: {value['integration']}")
        if isinstance(value.get("example"), str):
            print("  " + value["example"])
        if isinstance(value.get("native_fields"), list):
            print("  native fields: " + ", ".join(value["native_fields"]))
        print("  " + value["note"])


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
        install.prepare_installation(dry_run=args.dry_run, home=args.home)
        report = install.statusline_install(
            _statusline_products(args.product), args.home, profile=args.profile, force=args.force, dry_run=args.dry_run
        )
    if args.format == "json":
        print(json.dumps(report, indent=2, sort_keys=True))
        return
    print("Terminal UX preview" if args.dry_run else "Terminal UX installed")
    for product, entry in report["products"].items():
        print(f"{product}: {entry['integration']}; profile={entry['profile']}")
        if entry["integration"] == "native-manual":
            print("  " + entry["manual_step"].splitlines()[0])
    if args.dry_run:
        print("No changes were made")


def _statusline_status(args: argparse.Namespace) -> None:
    _print_value({"products": install.statusline_status(_statusline_products(args.product), args.home)}, args.format)


def _events_summary(args: argparse.Namespace) -> None:
    summary = terminal_ux.audit_summary(args.home, window=args.window, product=args.product)
    terminal_ux.refresh_audit_summary_cache(args.home)
    if args.format == "json":
        print(json.dumps(summary, indent=2, sort_keys=True))
    else:
        print(f"{summary['window']}: {summary['warnings']} warning(s), {summary['denials']} denial(s)")
        if summary["last_event_at"]:
            print(f"last recorded event: {summary['last_event_at']}")


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
    print(f"Activity ({summary['window']})")
    print(f"  Observed {summary['observed']}; warnings {summary['warnings']}; denials {summary['denials']}")
    if summary["operation_classes"]:
        print("  Operation classes " + ", ".join(f"{name}={count}" for name, count in summary["operation_classes"].items()))
    if summary["rule_ids"]:
        print("  Rules " + ", ".join(f"{name}={count}" for name, count in summary["rule_ids"].items()))
    if summary["last_event_at"] is None:
        print("  No recorded hook events in this window")
    print("  Visual Studio and JetBrains have no deterministic hook events.")


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
        print("Maintainability evidence comparison")
        sarif = result["reports"].get("sarif")
        if isinstance(sarif, Mapping):
            print(
                "  SARIF: "
                f"{sarif['new_findings']} new, {sarif['resolved_findings']} resolved, {sarif['unchanged_findings']} unchanged"
            )
        coverage = result["reports"].get("cobertura")
        if isinstance(coverage, Mapping):
            print(f"  Coverage line-rate delta: {coverage['line_rate_delta']:+.4f}")
        junit = result["reports"].get("junit")
        if isinstance(junit, Mapping):
            print(f"  JUnit: {junit['tests']} tests, {junit['failures']} failures, {junit['errors']} errors")
        for finding in result["findings"]:
            print(f"  {finding['id']}: {finding['evidence']}")
        return
    result = complexity.analyse(args.repo, base=args.base, staged=args.staged)
    if args.write_snapshot:
        complexity.write_cache(args.home, result, dry_run=False)
    if args.format == "json":
        print(json.dumps(result, indent=2, sort_keys=True))
        return
    clear_label = "OK" if _human_ascii_only() else "✓"
    label = "KISS " + ({"clear": clear_label, "review": "review", "high-change": "high-change"}[result["classification"]])
    print(label)
    if not result.get("available"):
        print("  " + result["limitation"])
    for signal in result.get("signals", []):
        if isinstance(signal, Mapping):
            print("  - " + str(signal.get("evidence", signal.get("id", "signal"))))
        else:
            print("  - " + str(signal))


def _receipt(args: argparse.Namespace) -> None:
    receipt = scan.session_receipt(args.home, args.repo, selected_products(args.product))
    output_format = args.format or ("compact" if args.compact else ("human" if args.fun else "json"))
    if output_format == "json":
        print(json.dumps(receipt, indent=2, sort_keys=True))
        return
    if output_format == "compact":
        events = receipt["guardrail_events"]
        print(("[G] Change summary" if _human_ascii_only() else "🛡 Change summary") if args.fun else "Change summary")
        print(f"  Repository          {receipt['repository_identifier_hash'][:12]}")
        print("  Products            " + ", ".join(receipt["products"]))
        print(f"  Files changed       {receipt['files_modified_count']}")
        print(f"  Guardrails          {events['warnings']} warning(s), {events['denials']} denial(s) in {events['window']}")
        print(f"  Complexity          {receipt['complexity']['classification']}")
        print("  Routing             " + ", ".join(f"{name}={profile}" for name, profile in receipt["model_routing_profiles"].items()))
        print(f"  Policy              {str(receipt['policy_digest'])[:12]}")
        print("  Verification gaps   " + "; ".join(receipt["unverified_checks"]))
        return
    print(("[G] Repository/change receipt" if _human_ascii_only() else "🛡 Repository/change receipt") if args.fun else "Repository/change receipt")
    print(json.dumps(receipt, indent=2, sort_keys=True))


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
    header = "[G] Synthetic demonstration - no displayed command was executed" if _human_ascii_only() else "🛡 Synthetic demonstration — no displayed command was executed"
    print(header if args.fun else "Synthetic demonstration - no displayed command was executed")
    for name, section in rendered.items():
        print(name + ":")
        for item in section:
            if "decision" in item:
                label = item.get("command", item.get("operation", "synthetic"))
                print(f"  {label:<36} {item['decision'].upper() if item['decision'] != 'no-decision' else 'ALLOW'}")
            elif "line" in item:
                print(f"  {item['profile']:<36} {item['line']}")
            else:
                print(f"  KISS {item['classification']:<31} {', '.join(item['signal_ids']) or 'no signals'}")


def create_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Vendor-neutral AI engineering guardrails")
    parser.add_argument("--version", action="version", version=f"ai-engineering-guardrails {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    build_parser = sub.add_parser("build", help="build deterministic generated adapters")
    add_product(build_parser)
    validate_parser = sub.add_parser("validate", help="validate canonical and generated data")
    add_product(validate_parser)

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

    doctor_parser = sub.add_parser("doctor", help="check repository and installation consistency")
    add_product(doctor_parser)
    add_home(doctor_parser)

    effective_parser = sub.add_parser("effective", help="show effective profiles, packs, and runtime digests")
    add_product(effective_parser)
    add_home(effective_parser)
    effective_parser.add_argument("--repo", type=Path)

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

    waiver_parser = sub.add_parser("waiver", help="manage local, expiring, human-confirmed waivers")
    waiver_sub = waiver_parser.add_subparsers(dest="waiver_command", required=True)
    waiver_create = waiver_sub.add_parser("create")
    add_home(waiver_create)
    waiver_create.add_argument("--rule-id", required=True)
    waiver_create.add_argument("--repo", type=Path, default=Path.cwd())
    waiver_create.add_argument("--target-scope", required=True)
    waiver_create.add_argument("--digest", required=True)
    waiver_create.add_argument("--reason", required=True)
    waiver_create.add_argument("--change-reference", required=True)
    waiver_create.add_argument("--expires-minutes", type=int, default=15)
    waiver_create.add_argument("--maximum-uses", type=int, default=1)
    waiver_list = waiver_sub.add_parser("list")
    add_home(waiver_list)
    waiver_revoke = waiver_sub.add_parser("revoke")
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
    policy_init = policy_sub.add_parser("init")
    add_home(policy_init)
    add_mutation_flags(policy_init)
    policy_apply = policy_sub.add_parser("apply")
    add_home(policy_apply)
    add_mutation_flags(policy_apply)
    policy_audit = policy_sub.add_parser("audit", help="audit canonical policy evidence metadata offline")
    policy_audit.add_argument("--format", choices=("human", "json"), default="human")
    policy_evidence = policy_sub.add_parser("evidence", help="show evidence metadata for one canonical policy fragment")
    policy_evidence.add_argument("policy_id")
    policy_evidence.add_argument("--format", choices=("human", "json"), default="human")

    task_parser = sub.add_parser("task", help="validate bounded task contracts and declared evidence")
    task_sub = task_parser.add_subparsers(dest="task_command", required=True)
    task_init = task_sub.add_parser("init", help="create a minimal repository task contract")
    task_init.add_argument("--repo", type=Path, default=Path.cwd())
    add_mutation_flags(task_init)
    task_establish = task_sub.add_parser("establish", help="explicitly establish the reviewed task contract as the local baseline")
    task_establish.add_argument("--repo", type=Path, default=Path.cwd())
    add_home(task_establish)
    task_establish.add_argument("--dry-run", action="store_true")
    task_establish.add_argument("--format", choices=("human", "json"), default="human")
    for name in ("validate", "status", "receipt"):
        task_command = task_sub.add_parser(name)
        task_command.add_argument("--repo", type=Path, default=Path.cwd())
        add_home(task_command)
        task_command.add_argument("--format", choices=("human", "json"), default="human")

    component_parser = sub.add_parser("component", help="inspect local instruction, skill, agent, hook, or MCP components without executing them")
    component_sub = component_parser.add_subparsers(dest="component_command", required=True)
    component_inspect = component_sub.add_parser("inspect")
    component_inspect.add_argument("path", type=Path)
    component_inspect.add_argument("--format", choices=("human", "json"), default="human")
    component_audit = component_sub.add_parser("audit")
    add_home(component_audit)
    component_audit.add_argument("--repo", type=Path)
    component_audit.add_argument("--format", choices=("human", "json"), default="human")
    component_trust = component_sub.add_parser("trust")
    component_trust.add_argument("path", type=Path)
    add_home(component_trust)
    component_trust.add_argument("--expires-at", required=True, help="future ISO-8601 timestamp, at most one year away")
    component_trust.add_argument("--source", required=True, help="operator-provided provenance label")
    component_trust.add_argument("--version-reference", default="local", help="operator-provided version or reference")
    component_trust.add_argument("--reviewed-by", default=None, help="reviewer label (defaults to the local account name)")
    component_trust.add_argument("--permission-tier", default="review-only", help="operator-provided review classification; it grants no authority")
    component_trust.add_argument("--dry-run", action="store_true")
    component_trust.add_argument("--format", choices=("human", "json"), default="human")
    component_list = component_sub.add_parser("list")
    add_home(component_list)
    component_list.add_argument("--format", choices=("human", "json"), default="human")
    component_revoke = component_sub.add_parser("revoke")
    component_revoke.add_argument("digest")
    add_home(component_revoke)
    component_revoke.add_argument("--dry-run", action="store_true")
    component_revoke.add_argument("--format", choices=("human", "json"), default="human")

    skills_parser = sub.add_parser("skills", help="audit portable skill structure and estimated context size")
    skills_sub = skills_parser.add_subparsers(dest="skills_command", required=True)
    skills_audit = skills_sub.add_parser("audit")
    skills_audit.add_argument("--path", type=Path)
    skills_audit.add_argument("--format", choices=("human", "json"), default="human")

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
    args = create_parser().parse_args(argv)
    try:
        if args.command == "build":
            build.build(selected_products(args.product))
        elif args.command == "validate":
            output_root = repository_output_root()
            build.validate(
                selected_products(args.product),
                require_current=output_root is not None,
                output_root=output_root,
            )
        elif args.command == "install":
            if args.product == "visualstudio" and sys.platform != "win32":
                raise GuardrailsError(
                    "Visual Studio installation is supported only on Windows; build and validation remain cross-platform"
                )
            products, detected = _resolve_consumer_products(args.product, args.home, "install")
            if args.product == "all" and sys.platform != "win32" and "visualstudio" in products:
                products = tuple(product for product in products if product != "visualstudio")
                print("Visual Studio was skipped: its user-level adapter is supported only on Windows")
            _run_consumer_install(args, products, detected, updating=False)
        elif args.command == "update":
            products, detected = _resolve_consumer_products(args.product, args.home, "update")
            _run_consumer_install(args, products, detected, updating=True)
        elif args.command == "uninstall":
            products, _ = _resolve_consumer_products(args.product, args.home, "uninstall")
            install.uninstall(products, args.home, force=args.force, dry_run=args.dry_run)
        elif args.command == "status":
            products, _ = _resolve_consumer_products(args.product, args.home, "status")
            install.status(
                products, args.home, show_routing_details=args.show_routing, repo=args.repo
            )
        elif args.command == "doctor":
            report = install.doctor(selected_products(args.product), args.home)
            if any(check["outcome"] == "fail" for check in report["checks"]):
                return 1
        elif args.command == "effective":
            install.effective_configuration(selected_products(args.product), args.home, args.repo)
        elif args.command == "diff-installed":
            install.diff_installed(selected_products(args.product), args.home)
        elif args.command in {"explain", "simulate"}:
            _explain(args)
        elif args.command == "scan":
            findings, _ = scan.run_scan(args.repo, args.format, args.output)
            if any(item.level == "error" for item in findings):
                return 1
        elif args.command == "packs":
            if args.packs_command == "list":
                _packs_list()
            elif args.packs_command in {"detect", "explain"}:
                _packs_detect(args.repo, args.packs_command == "explain")
            else:
                count, examples = packs.validate_packs()
                print(f"pack validation passed: {count} packs, {examples} fixtures")
        elif args.command == "routing":
            if args.routing_command == "show":
                _routing_show(selected_products(args.product), args.profile)
            elif args.routing_command == "validate":
                config = routing.load_config()
                print(f"routing validation passed: {len(config['agents'])} agents, {len(config['profiles'])} profiles")
            else:
                install.set_routing(
                    selected_products(args.product),
                    args.home,
                    args.profile,
                    model_overrides=parse_model_overrides(args.model_override) or None,
                    force=args.force,
                    dry_run=args.dry_run,
                )
        elif args.command == "print-cursor-rules":
            install.print_cursor_rules(clipboard=args.clipboard, home=args.home)
        elif args.command == "jetbrains":
            if args.jetbrains_command == "print-chat-instructions":
                install.print_jetbrains_chat_instructions(clipboard=args.clipboard, home=args.home)
            else:
                install.export_jetbrains_project_rules(
                    args.repo, dry_run=args.dry_run, force=args.force, home=args.home
                )
        elif args.command == "waiver":
            if args.waiver_command == "create":
                _waiver_create(args)
            elif args.waiver_command == "list":
                _waiver_list(args)
            else:
                print("revoked" if state.revoke_waiver(args.home, args.id) else "waiver not found")
        elif args.command == "policy":
            if args.policy_command == "list":
                _policy_list(args)
            elif args.policy_command == "show":
                _policy_show(args)
            elif args.policy_command == "init":
                policy.initialise_local_overlay(args.home, force=args.force, dry_run=args.dry_run)
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
                    print("Task contract validation passed.")
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
                    report = install.statusline_uninstall(_statusline_products(args.product), args.home, force=args.force, dry_run=args.dry_run)
                    outcomes = report["products"]
                    retained = [product for product, outcome in outcomes.items() if outcome == "retained-modified"]
                    removed = [product for product, outcome in outcomes.items() if outcome in {"removed", "would-remove"}]
                    if args.dry_run:
                        print("Terminal UX uninstall preview complete; no changes were made")
                    elif retained:
                        print("Terminal UX uninstall partially complete; retained modified configuration: " + ", ".join(retained))
                    elif removed:
                        print("Terminal UX uninstalled")
                    else:
                        print("No managed terminal UX configuration was found")
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
        print(f"error: {exc}", file=sys.stderr)
        return 1
    return 0
