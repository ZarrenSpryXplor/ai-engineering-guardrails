"""Command-line interface for AI engineering guardrails."""

from __future__ import annotations

import argparse
import contextlib
import io
import json
import sys
from pathlib import Path
from typing import Any, Mapping, Sequence

from . import __version__, build, enforcement, install, packs, policy, routing, scan, state
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
    repository_detection = packs.detect_packs(Path.cwd())
    details = io.StringIO()
    with contextlib.redirect_stdout(details):
        install.prepare_installation(dry_run=args.dry_run, home=args.home)
        if updating:
            report = install.update(products, args.home, force=args.force, dry_run=args.dry_run)
        else:
            report = install.install(
                products,
                args.home,
                force=args.force,
                dry_run=args.dry_run,
                pack_ids=args.pack,
                all_packs=args.all_packs,
                routing_profile=args.routing_profile,
                safety_profile=args.safety_profile,
                trust_mode=args.trust_mode,
                model_overrides=parse_model_overrides(args.model_override) or None,
            )
    if args.verbose:
        print(details.getvalue(), end="")
    install.print_consumer_install_summary(report, detected, repository_detection)


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

    receipt_parser = sub.add_parser("receipt", help="emit a content-free local session receipt")
    add_home(receipt_parser)
    add_product(receipt_parser)
    receipt_parser.add_argument("--repo", type=Path, default=Path.cwd())
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
            products, detected = _resolve_consumer_products(args.product, args.home, "install")
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
            else:
                _policy_apply(args)
        elif args.command == "receipt":
            print(json.dumps(scan.session_receipt(args.home, args.repo, selected_products(args.product)), indent=2, sort_keys=True))
        else:
            raise GuardrailsError(f"unsupported command: {args.command}")
    except (GuardrailsError, OSError, UnicodeError, enforcement.PolicyError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    return 0
