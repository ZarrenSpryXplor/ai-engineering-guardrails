"""User-scoped installation, update, status, doctor, and uninstallation."""

from __future__ import annotations

import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any, Mapping, Sequence

from . import build, packs, policy, routing, state
from .util import (
    LIFECYCLES,
    PRODUCTS,
    ROOT,
    SAFETY_PROFILES,
    TRUST_MODES,
    GuardrailsError,
    atomic_write,
    home_path,
    json_bytes,
    path_within,
    read_json,
    relative_home,
    sha256,
    tree_hash,
    validate_install_target,
)


BEGIN_MARKER = "<!-- BEGIN WORKSTATION AI GUARDRAILS -->"
END_MARKER = "<!-- END WORKSTATION AI GUARDRAILS -->"
RUNTIME_RELATIVE = Path(".ai-guardrails/runtime")
AUDIT_RELATIVE = Path(".ai-guardrails/audit")
WAIVERS_RELATIVE = Path(".ai-guardrails/waivers")
TARGETS_RELATIVE = Path(".ai-guardrails/targets.json")
RUNTIME_RETENTION = 3
MANAGED_HOOK_RE = re.compile(
    r"(?:^|[/\\])hook_runtime\.py[\"']?\s+--product\s+(codex|claude|cursor)\b",
    re.IGNORECASE,
)
PRODUCT_LABELS = {
    "codex": "OpenAI Codex",
    "claude": "Claude Code",
    "cursor": "Cursor",
}
PRODUCT_EXECUTABLES = {
    "codex": "codex",
    "claude": "claude",
    "cursor": "cursor",
}
PRODUCT_CONFIG_ROOTS = {
    "codex": ".codex",
    "claude": ".claude",
    "cursor": ".cursor",
}


def detect_products(home: Path) -> dict[str, tuple[str, ...]]:
    """Detect supported local products from commands, configuration, or managed state."""
    home = home.expanduser().resolve(strict=False)
    installed_state = state.load_state(home)
    detected: dict[str, tuple[str, ...]] = {}
    for product in PRODUCTS:
        evidence: list[str] = []
        if shutil.which(PRODUCT_EXECUTABLES[product]):
            evidence.append("executable")
        config_root = home_path(home, PRODUCT_CONFIG_ROOTS[product])
        if product == "codex" and os.environ.get("CODEX_HOME"):
            configured = Path(os.environ["CODEX_HOME"]).expanduser()
            candidate = configured if configured.is_absolute() else home / configured
            candidate = candidate.resolve(strict=False)
            if path_within(candidate, home):
                config_root = candidate
        if config_root.is_dir() and not config_root.is_symlink():
            evidence.append("configuration")
        if product in installed_state.get("products", {}):
            evidence.append("managed-state")
        if evidence:
            detected[product] = tuple(evidence)
    return detected


def installed_products(home: Path) -> tuple[str, ...]:
    installed_state = state.load_state(home.expanduser().resolve(strict=False))
    return tuple(product for product in PRODUCTS if product in installed_state.get("products", {}))


def prepare_installation(*, dry_run: bool) -> None:
    """Use the existing deterministic build and validation before user-home mutation."""
    if dry_run:
        build.validate(PRODUCTS, require_current=False)
        return
    build.build(PRODUCTS)
    build.validate(PRODUCTS)


def codex_home(home: Path) -> Path:
    """Resolve CODEX_HOME without allowing installation outside --home."""
    configured = os.environ.get("CODEX_HOME")
    if not configured:
        return home_path(home, ".codex")
    candidate = Path(configured).expanduser()
    if not candidate.is_absolute():
        candidate = home / candidate
    candidate = candidate.resolve(strict=False)
    if not path_within(candidate, home):
        raise GuardrailsError(f"CODEX_HOME is outside the selected home: {candidate}")
    return candidate


def effective_codex_policy(home: Path) -> Path:
    codex_root = codex_home(home)
    override = codex_root / "AGENTS.override.md"
    normal = codex_root / "AGENTS.md"
    if override.is_file() and override.stat().st_size > 0:
        return override
    if normal.is_file() and normal.stat().st_size > 0:
        return normal
    return normal


def _managed_block(content: str) -> str:
    return f"{BEGIN_MARKER}\n{content.rstrip()}\n{END_MARKER}"


def _block_pattern() -> re.Pattern[str]:
    return re.compile(re.escape(BEGIN_MARKER) + r".*?" + re.escape(END_MARKER), re.DOTALL)


def _install_managed_block(
    content: str,
    target: Path,
    home: Path,
    current_state: Mapping[str, Any],
    *,
    force: bool,
    dry_run: bool,
) -> dict[str, Any]:
    validate_install_target(target, home)
    relative = relative_home(target, home)
    previous = state.record_for_path(current_state, relative)
    original_exists = target.exists()
    original = target.read_text(encoding="utf-8") if target.is_file() else ""
    pattern = _block_pattern()
    matches = list(pattern.finditer(original))
    if len(matches) > 1:
        raise GuardrailsError(f"multiple managed guardrail blocks found: {target}")
    block = _managed_block(content)
    block_hash = sha256(block.encode("utf-8"))
    backup = previous.get("backup") if previous else None
    if matches:
        if previous is None and not force:
            raise GuardrailsError(f"unmanaged guardrail block collision; refusing to overwrite without --force: {target}")
        existing_block = matches[0].group(0)
        if previous and sha256(existing_block.encode("utf-8")) != previous.get("managed_sha256") and not force:
            raise GuardrailsError(f"locally modified managed block; refusing to overwrite without --force: {target}")
        updated = pattern.sub(block, original, count=1)
    else:
        updated = original.rstrip()
        updated = f"{updated}\n\n{block}" if updated else block
    updated = updated.rstrip() + "\n"
    if updated.encode("utf-8") == (target.read_bytes() if target.is_file() else b""):
        print(f"unchanged {target}")
    else:
        if target.exists():
            backup = state.backup_existing(home, target, dry_run=dry_run) or backup
        print(f"{'would update' if dry_run else 'update'} managed block in {target}")
        if not dry_run:
            atomic_write(target, updated.encode("utf-8"))
    return state.record(
        relative,
        "managed-block",
        sha256(updated.encode("utf-8")),
        backup,
        managed_sha256=block_hash,
        created=bool(previous.get("created")) if previous else not original_exists,
    )


def _hook_event(product: str) -> str:
    return "preToolUse" if product == "cursor" else "PreToolUse"


def _runtime_command(runtime: Path, product: str) -> str:
    executable = Path(sys.executable).resolve(strict=False)
    script = runtime / "hook_runtime.py"
    if os.name == "nt":
        return f'"{executable}" "{script}" --product {product}'
    return f"{shlex.quote(str(executable))} {shlex.quote(str(script))} --product {product}"


def _hook_group(product: str, runtime: Path) -> dict[str, Any]:
    command = _runtime_command(runtime, product)
    if product == "cursor":
        return {"command": command, "matcher": ".*"}
    return {
        "matcher": ".*",
        "hooks": [
            {
                "type": "command",
                "command": command,
                "timeout": 10,
                "statusMessage": "Checking tool request against workstation guardrails",
            }
        ],
    }


def _hook_commands(group: Any) -> list[str]:
    if not isinstance(group, Mapping):
        return []
    commands: list[str] = []
    direct = group.get("command")
    if isinstance(direct, str):
        commands.append(direct)
    hooks = group.get("hooks")
    if isinstance(hooks, list):
        commands.extend(
            str(item["command"])
            for item in hooks
            if isinstance(item, Mapping) and isinstance(item.get("command"), str)
        )
    return commands


def _is_managed_hook(group: Any, product: str | None = None) -> bool:
    for command in _hook_commands(group):
        match = MANAGED_HOOK_RE.search(command)
        if match is not None and (product is None or match.group(1).lower() == product):
            return True
    return False


def _managed_hook_groups(data: Mapping[str, Any], product: str) -> list[dict[str, Any]]:
    hooks = data.get("hooks", {})
    groups = hooks.get(_hook_event(product), []) if isinstance(hooks, Mapping) else []
    return [dict(group) for group in groups if _is_managed_hook(group, product)] if isinstance(groups, list) else []


def _remove_managed_hook_groups(data: dict[str, Any], product: str) -> list[dict[str, Any]]:
    hooks = data.get("hooks")
    if not isinstance(hooks, dict):
        return []
    event = _hook_event(product)
    groups = hooks.get(event)
    if not isinstance(groups, list):
        return []
    removed = [dict(group) for group in groups if isinstance(group, Mapping) and _is_managed_hook(group, product)]
    hooks[event] = [group for group in groups if not _is_managed_hook(group, product)]
    if not hooks[event]:
        hooks.pop(event)
    if not hooks:
        data.pop("hooks", None)
    return removed


def _install_json_hook(
    product: str,
    runtime: Path,
    target: Path,
    home: Path,
    current_state: Mapping[str, Any],
    *,
    force: bool,
    dry_run: bool,
) -> dict[str, Any]:
    validate_install_target(target, home)
    relative = relative_home(target, home)
    previous = state.record_for_path(current_state, relative)
    original_exists = target.is_file()
    data = read_json(target, default={})
    if not isinstance(data, dict):
        raise GuardrailsError(f"hook configuration must be a JSON object: {target}")
    hooks = data.get("hooks")
    if hooks is not None and not isinstance(hooks, dict):
        raise GuardrailsError(f"hook configuration hooks must be an object: {target}")
    event_groups = hooks.get(_hook_event(product)) if isinstance(hooks, dict) else None
    if event_groups is not None and not isinstance(event_groups, list):
        raise GuardrailsError(f"hook event configuration must be a list: {target}")
    existing_managed = _managed_hook_groups(data, product)
    if len(existing_managed) > 1:
        raise GuardrailsError(f"duplicate managed hook entries found: {target}")
    if existing_managed and previous is None and not force:
        raise GuardrailsError(f"unmanaged guardrail hook collision; refusing to overwrite without --force: {target}")
    if existing_managed and previous:
        existing_hash = sha256(json_bytes(existing_managed[0]))
        if existing_hash != previous.get("managed_sha256") and not force:
            raise GuardrailsError(f"locally modified managed hook; refusing to overwrite without --force: {target}")
    _remove_managed_hook_groups(data, product)
    data.setdefault("hooks", {}).setdefault(_hook_event(product), []).append(_hook_group(product, runtime))
    if product == "cursor":
        data.setdefault("version", 1)
    rendered = json_bytes(data)
    managed_hash = sha256(json_bytes(_hook_group(product, runtime)))
    backup = previous.get("backup") if previous else None
    if target.is_file() and target.read_bytes() == rendered:
        print(f"unchanged {target}")
    else:
        if target.exists():
            backup = state.backup_existing(home, target, dry_run=dry_run) or backup
        print(f"{'would merge' if dry_run else 'merge'} guardrails hook into {target}")
        if not dry_run:
            atomic_write(target, rendered)
    return state.record(
        relative,
        "json-hook",
        sha256(rendered),
        backup,
        managed_sha256=managed_hash,
        product=product,
        created=bool(previous.get("created")) if previous else not original_exists,
    )


def _managed_paths_for_product(
    home: Path,
    product: str,
    selected_packs: Sequence[str],
    routing_profile: str,
    model_overrides: Mapping[str, Mapping[str, str]] | None,
    generated_artifacts: Mapping[Path, bytes],
) -> list[Path]:
    if product == "codex":
        codex_root = codex_home(home)
        paths = [
            effective_codex_policy(home),
            codex_root / "hooks.json",
            codex_root / "rules/workstation-guardrails.rules",
        ]
    elif product == "claude":
        paths = [
            home_path(home, ".claude/settings.json"),
        ]
        paths.extend(
            home_path(home, ".claude/rules") / source.name
            for source in sorted(generated_artifacts, key=lambda path: path.as_posix())
            if source.parent == ROOT / "dist/claude/rules"
            and source.name.startswith("workstation-guardrails-")
            and source.suffix == ".md"
        )
    else:
        paths = [home_path(home, ".cursor/hooks.json")]

    skill_sources = [source.parent for source in policy.discover_skills()]
    available = packs.load_packs()
    for identifier in selected_packs:
        skill_sources.extend(source.parent for source in packs.pack_skill_files(available[identifier]))
    paths.extend(_skill_root(home, product) / source.name for source in skill_sources)

    if routing_profile != "none":
        paths.extend(
            _agent_root(home, product) / filename
            for filename in routing.render_agents(product, routing_profile, model_overrides=model_overrides)
        )
    return paths


def _runtime_payloads(
    home: Path,
    product: str,
    selected_packs: Sequence[str],
    routing_profile: str,
    safety_profile: str,
    trust_mode: str,
    model_overrides: Mapping[str, Mapping[str, str]] | None,
    generated_artifacts: Mapping[Path, bytes],
) -> tuple[str, dict[str, bytes]]:
    merged = policy.load_enforcement_policy(selected_packs)
    command = {
        "schema_version": 1,
        "rules": merged["rules"],
        "classifications": merged["classifications"],
        "structured_tools": merged.get("structured_tools", {"strict_allowlist": False}),
    }
    structured = {
        "schema_version": 1,
        "rules": merged["structured_tool_rules"],
        "structured_tools": merged.get("structured_tools", {"strict_allowlist": False}),
    }
    redaction_path = ROOT / "enforcement/redaction-policy.json"
    redaction = redaction_path.read_bytes()
    policy_digest = sha256(json_bytes(command) + json_bytes(structured) + redaction)
    metadata: dict[str, Any] = {
        "format_version": 1,
        "product": product,
        "policy_digest": policy_digest,
        "safety_profile": safety_profile,
        "trust_mode": trust_mode,
        "home_directory": str(home),
        "audit_directory": str(home_path(home, AUDIT_RELATIVE)),
        "waiver_directory": str(home_path(home, WAIVERS_RELATIVE)),
        "targets_path": str(home_path(home, TARGETS_RELATIVE)),
        "state_path": str(home_path(home, state.STATE_RELATIVE)),
        "managed_paths": [
            str(path.resolve(strict=False))
            for path in _managed_paths_for_product(
                home,
                product,
                selected_packs,
                routing_profile,
                model_overrides,
                generated_artifacts,
            )
        ],
        "installed_packs": list(selected_packs),
    }
    payloads = {
        "hook_runtime.py": (ROOT / "guardrails/enforcement.py").read_bytes(),
        "command-policy.json": json_bytes(command),
        "structured-tool-policy.json": json_bytes(structured),
        "redaction-policy.json": redaction,
        "metadata.json": json_bytes(metadata),
    }
    digest_input = b"".join(name.encode("utf-8") + b"\0" + payloads[name] + b"\0" for name in sorted(payloads))
    return sha256(digest_input), payloads


def _validate_runtime_payloads(payloads: Mapping[str, bytes]) -> None:
    try:
        compile(payloads["hook_runtime.py"].decode("utf-8"), "hook_runtime.py", "exec")
        json.loads(payloads["command-policy.json"])
        json.loads(payloads["structured-tool-policy.json"])
        json.loads(payloads["redaction-policy.json"])
        json.loads(payloads["metadata.json"])
    except (UnicodeDecodeError, SyntaxError, json.JSONDecodeError) as exc:
        raise GuardrailsError(f"installed runtime validation failed: {exc.__class__.__name__}") from exc


def _install_runtime(home: Path, digest: str, payloads: Mapping[str, bytes], *, dry_run: bool) -> Path:
    runtime_root = home_path(home, RUNTIME_RELATIVE)
    target = runtime_root / digest
    validate_install_target(target, home)
    _validate_runtime_payloads(payloads)
    if target.is_dir():
        entries = {path.name: path for path in target.iterdir()}
        if set(entries) != set(payloads) or any(not path.is_file() or path.is_symlink() for path in entries.values()):
            raise GuardrailsError(f"immutable runtime digest collision: {target}")
        actual = {name: path.read_bytes() for name, path in entries.items()}
        if actual != dict(payloads):
            raise GuardrailsError(f"immutable runtime digest collision: {target}")
        print(f"unchanged immutable runtime {target}")
        return target
    if target.exists():
        raise GuardrailsError(f"immutable runtime path is not a directory: {target}")
    print(f"{'would install' if dry_run else 'install'} immutable runtime {target}")
    if dry_run:
        return target
    runtime_root.mkdir(parents=True, exist_ok=True)
    staged = Path(tempfile.mkdtemp(prefix=f".{digest}.", dir=runtime_root))
    try:
        for name, data in payloads.items():
            mode = 0o555 if name == "hook_runtime.py" else 0o444
            atomic_write(staged / name, data, mode=mode)
        os.replace(staged, target)
    finally:
        if staged.exists():
            shutil.rmtree(staged)
    return target


def _skill_root(home: Path, product: str) -> Path:
    return home_path(home, ".claude/skills" if product == "claude" else ".agents/skills")


def _agent_root(home: Path, product: str) -> Path:
    if product == "codex":
        return codex_home(home) / "agents"
    relative = {"claude": ".claude/agents", "cursor": ".cursor/agents"}[product]
    return home_path(home, relative)


def _install_skills(
    product: str,
    home: Path,
    current_state: Mapping[str, Any],
    selected_packs: Sequence[str],
    *,
    force: bool,
    dry_run: bool,
) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    destination = _skill_root(home, product)
    for skill_file in policy.discover_skills():
        records.append(
            state.install_directory(
                skill_file.parent,
                destination / skill_file.parent.name,
                home,
                current_state,
                force=force,
                dry_run=dry_run,
                label="skill",
            )
        )
    available = packs.load_packs()
    for identifier in selected_packs:
        for skill_file in packs.pack_skill_files(available[identifier]):
            records.append(
                state.install_directory(
                    skill_file.parent,
                    destination / skill_file.parent.name,
                    home,
                    current_state,
                    force=force,
                    dry_run=dry_run,
                    label="pack skill",
                )
            )
    return records


def _install_agents(
    product: str,
    home: Path,
    current_state: Mapping[str, Any],
    profile_name: str,
    model_overrides: Mapping[str, Mapping[str, str]] | None,
    *,
    force: bool,
    dry_run: bool,
) -> list[dict[str, Any]]:
    if profile_name == "none":
        return []
    records: list[dict[str, Any]] = []
    for filename, data in routing.render_agents(product, profile_name, model_overrides=model_overrides).items():
        records.append(
            state.install_file_data(
                data,
                _agent_root(home, product) / filename,
                home,
                current_state,
                force=force,
                dry_run=dry_run,
                collision_label="agent",
            )
        )
    return records


def _install_codex(
    home: Path,
    runtime: Path,
    current_state: Mapping[str, Any],
    generated_artifacts: Mapping[Path, bytes],
    *,
    force: bool,
    dry_run: bool,
) -> list[dict[str, Any]]:
    codex_root = codex_home(home)
    target = effective_codex_policy(home)
    print(f"effective Codex global instruction file: {target}")
    records = [
        _install_managed_block(
            generated_artifacts[ROOT / "dist/codex/AGENTS.md"].decode("utf-8"),
            target,
            home,
            current_state,
            force=force,
            dry_run=dry_run,
        ),
        state.install_file_data(
            generated_artifacts[ROOT / "dist/codex/rules/workstation-guardrails.rules"],
            codex_root / "rules/workstation-guardrails.rules",
            home,
            current_state,
            force=force,
            dry_run=dry_run,
        ),
        _install_json_hook(
            "codex",
            runtime,
            codex_root / "hooks.json",
            home,
            current_state,
            force=force,
            dry_run=dry_run,
        ),
    ]
    return records


def _install_claude(
    home: Path,
    runtime: Path,
    current_state: Mapping[str, Any],
    generated_artifacts: Mapping[Path, bytes],
    *,
    force: bool,
    dry_run: bool,
) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    sources = [
        source
        for source in sorted(generated_artifacts, key=lambda path: path.as_posix())
        if source.parent == ROOT / "dist/claude/rules"
        and source.name.startswith("workstation-guardrails-")
        and source.suffix == ".md"
    ]
    for source in sources:
        records.append(
            state.install_file_data(
                generated_artifacts[source],
                home_path(home, ".claude/rules") / source.name,
                home,
                current_state,
                force=force,
                dry_run=dry_run,
            )
        )
    records.append(
        _install_json_hook(
            "claude",
            runtime,
            home_path(home, ".claude/settings.json"),
            home,
            current_state,
            force=force,
            dry_run=dry_run,
        )
    )
    return records


def _install_cursor(
    home: Path,
    runtime: Path,
    current_state: Mapping[str, Any],
    *,
    force: bool,
    dry_run: bool,
) -> list[dict[str, Any]]:
    return [
        _install_json_hook(
            "cursor",
            runtime,
            home_path(home, ".cursor/hooks.json"),
            home,
            current_state,
            force=force,
            dry_run=dry_run,
        )
    ]


def _managed_enterprise_indicators() -> list[str]:
    indicators: list[str] = []
    candidates = {
        "Codex system requirements": Path("/etc/codex/requirements.toml"),
        "Claude macOS managed settings": Path("/Library/Application Support/ClaudeCode/managed-settings.json"),
        "Claude Linux managed settings": Path("/etc/claude-code/managed-settings.json"),
    }
    for label, path in candidates.items():
        try:
            if path.is_file():
                indicators.append(label)
        except OSError:
            continue
    return indicators


def _selected_packs(values: Sequence[str], all_packs: bool) -> tuple[str, ...]:
    available = packs.load_packs()
    selected = tuple(sorted(available)) if all_packs else packs.selected_pack_closure(values, available)
    return selected


def _uniform_product_setting(
    products: Mapping[str, Any], field: str, default: str
) -> str:
    values = {
        str(data.get(field, default))
        for data in products.values()
        if isinstance(data, Mapping)
    }
    if not values:
        return default
    return next(iter(values)) if len(values) == 1 else "per-product"


def _aggregate_policy_digest(products: Mapping[str, Any]) -> str:
    digests = {
        product: data.get("policy_digest")
        for product, data in sorted(products.items())
        if isinstance(data, Mapping) and isinstance(data.get("policy_digest"), str)
    }
    return sha256(json_bytes(digests)) if digests else ""


def _preflight_collisions(
    products: Sequence[str],
    home: Path,
    current_state: Mapping[str, Any],
    selected_packs: Sequence[str],
    routing_profile: str,
    model_overrides: Mapping[str, Mapping[str, str]] | None,
    generated_artifacts: Mapping[Path, bytes],
    *,
    force: bool,
) -> None:
    """Reject collisions and modified managed content before the first write."""
    for product in products:
        for target in _managed_paths_for_product(
            home,
            product,
            selected_packs,
            routing_profile,
            model_overrides,
            generated_artifacts,
        ):
            validate_install_target(target, home)
        configuration_files = {
            "codex": (
                effective_codex_policy(home),
                codex_home(home) / "hooks.json",
                codex_home(home) / "rules/workstation-guardrails.rules",
            ),
            "claude": (home_path(home, ".claude/settings.json"),),
            "cursor": (home_path(home, ".cursor/hooks.json"),),
        }[product]
        for target in configuration_files:
            if target.exists() and not target.is_file():
                raise GuardrailsError(f"managed configuration collides with a non-file: {target}")
        if product == "codex":
            policy_target = effective_codex_policy(home)
            if policy_target.is_file():
                try:
                    policy_text = policy_target.read_text(encoding="utf-8")
                except (OSError, UnicodeError) as exc:
                    raise GuardrailsError(f"Codex instruction file must be UTF-8 text: {policy_target}") from exc
                blocks = list(_block_pattern().finditer(policy_text))
                if len(blocks) > 1:
                    raise GuardrailsError(f"multiple managed guardrail blocks found: {policy_target}")
                previous = state.record_for_path(current_state, relative_home(policy_target, home))
                if blocks and previous is None and not force:
                    raise GuardrailsError(
                        f"unmanaged guardrail block collision; refusing to overwrite without --force: {policy_target}"
                    )
        hook_target = {
            "codex": codex_home(home) / "hooks.json",
            "claude": home_path(home, ".claude/settings.json"),
            "cursor": home_path(home, ".cursor/hooks.json"),
        }[product]
        if hook_target.is_file():
            hook_data = read_json(hook_target, default={})
            if not isinstance(hook_data, dict):
                raise GuardrailsError(f"hook configuration must be a JSON object: {hook_target}")
            hook_sections = hook_data.get("hooks")
            if hook_sections is not None and not isinstance(hook_sections, dict):
                raise GuardrailsError(f"hook configuration hooks must be an object: {hook_target}")
            event_groups = hook_sections.get(_hook_event(product)) if isinstance(hook_sections, dict) else None
            if event_groups is not None and not isinstance(event_groups, list):
                raise GuardrailsError(f"hook event configuration must be a list: {hook_target}")
            managed_groups = _managed_hook_groups(hook_data, product)
            if len(managed_groups) > 1:
                raise GuardrailsError(f"duplicate managed hook entries found: {hook_target}")
            previous = state.record_for_path(current_state, relative_home(hook_target, home))
            if managed_groups and previous is None and not force:
                raise GuardrailsError(
                    f"unmanaged guardrail hook collision; refusing to overwrite without --force: {hook_target}"
                )
        if force:
            continue
        for record in state.product_records(current_state, product):
            if _managed_record_status(record, home, product) == "modified":
                relative = record.get("path", "unknown")
                raise GuardrailsError(
                    f"locally modified managed path; refusing to update without --force: {home_path(home, str(relative))}"
                )
        skill_sources = [path.parent for path in policy.discover_skills()]
        available = packs.load_packs()
        for identifier in selected_packs:
            skill_sources.extend(path.parent for path in packs.pack_skill_files(available[identifier]))
        for source in skill_sources:
            target = _skill_root(home, product) / source.name
            relative = relative_home(target, home)
            if target.exists() and state.record_for_path(current_state, relative) is None:
                raise GuardrailsError(f"unmanaged skill collision; refusing to overwrite without --force: {target}")
        if routing_profile != "none":
            for filename in routing.render_agents(product, routing_profile):
                target = _agent_root(home, product) / filename
                relative = relative_home(target, home)
                if target.exists() and state.record_for_path(current_state, relative) is None:
                    raise GuardrailsError(f"unmanaged agent collision; refusing to overwrite without --force: {target}")
        if product == "codex":
            rules = codex_home(home) / "rules/workstation-guardrails.rules"
            if rules.exists() and state.record_for_path(current_state, relative_home(rules, home)) is None:
                raise GuardrailsError(f"unmanaged collision; refusing to overwrite without --force: {rules}")
        if product == "claude":
            for source in sorted((ROOT / "dist/claude/rules").glob("workstation-guardrails-*.md")):
                target = home_path(home, ".claude/rules") / source.name
                if target.exists() and state.record_for_path(current_state, relative_home(target, home)) is None:
                    raise GuardrailsError(f"unmanaged collision; refusing to overwrite without --force: {target}")


def _runtime_record(runtime: Path, home: Path, digest: str) -> dict[str, Any]:
    return state.record(
        relative_home(runtime, home),
        "runtime-directory",
        tree_hash(runtime) if runtime.is_dir() else digest,
        runtime_digest=digest,
    )


def _remove_obsolete_product_records(
    product: str,
    desired: Sequence[Mapping[str, Any]],
    home: Path,
    current_state: Mapping[str, Any],
    *,
    force: bool,
    dry_run: bool,
) -> None:
    desired_paths = {record.get("path") for record in desired}
    for old in state.product_records(current_state, product):
        relative = old.get("path")
        if not isinstance(relative, str) or relative in desired_paths or old.get("kind") == "runtime-directory":
            continue
        if state.owners(current_state, relative, excluding={product}):
            continue
        if _managed_record_status(old, home, product) == "modified" and not force:
            label = "agent" if "/agents/" in relative else "managed path"
            raise GuardrailsError(f"locally modified managed {label}; refusing to remove without --force: {home_path(home, relative)}")
        kind = old.get("kind")
        if kind == "managed-block":
            _remove_managed_block(old, home, force=force, dry_run=dry_run)
        elif kind == "json-hook":
            _remove_json_hook(old, product, home, force=force, dry_run=dry_run)
        else:
            state.remove_record(old, home, force=True, dry_run=dry_run)


def _cleanup_runtimes(home: Path, installed_state: Mapping[str, Any]) -> None:
    runtime_root = home_path(home, RUNTIME_RELATIVE)
    if not runtime_root.is_dir():
        return
    referenced = {
        str(record.get("runtime_digest"))
        for product in PRODUCTS
        for record in state.product_records(installed_state, product)
        if record.get("kind") == "runtime-directory"
    }
    unreferenced = sorted(
        [path for path in runtime_root.iterdir() if path.is_dir() and re.fullmatch(r"[0-9a-f]{64}", path.name)],
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )
    retained = 0
    for path in unreferenced:
        if path.name in referenced:
            continue
        if retained < RUNTIME_RETENTION:
            retained += 1
            continue
        if path_within(path, runtime_root):
            shutil.rmtree(path)


def _selected_installation_is_current(
    current: Mapping[str, Any],
    products: Sequence[str],
    product_settings: Mapping[str, Mapping[str, Any]],
    home: Path,
) -> bool:
    source = state.source_digest()
    for product in products:
        existing = current.get("products", {}).get(product)
        if not isinstance(existing, Mapping) or existing.get("source_digest") != source:
            return False
        expected = product_settings[product]
        for field in ("routing_profile", "safety_profile", "trust_mode"):
            if existing.get(field) != expected[field]:
                return False
        if tuple(existing.get("installed_packs", [])) != tuple(expected["installed_packs"]):
            return False
        if dict(existing.get("model_overrides", {})) != dict(expected["model_overrides"]):
            return False
        records = state.product_records(current, product)
        if not records or any(_managed_record_status(record, home, product) != "installed" for record in records):
            return False
    return True


def _post_install_integrity(installed_state: Mapping[str, Any], products: Sequence[str], home: Path) -> None:
    failures: list[str] = []
    for product in products:
        records = state.product_records(installed_state, product)
        if not records:
            failures.append(f"{product}: no managed paths")
            continue
        for record in records:
            status_value = _managed_record_status(record, home, product)
            if status_value != "installed":
                failures.append(f"{product}: {record.get('path', 'unknown')} is {status_value}")
    reloaded = state.load_state(home)
    for product in products:
        if product not in reloaded.get("products", {}):
            failures.append(f"{product}: missing from installation state")
    if failures:
        raise GuardrailsError("post-install integrity check failed: " + "; ".join(failures))


def install(
    products: Sequence[str],
    home: Path,
    *,
    force: bool,
    dry_run: bool,
    pack_ids: Sequence[str] = (),
    all_packs: bool = False,
    routing_profile: str | None = None,
    safety_profile: str | None = None,
    trust_mode: str | None = None,
    model_overrides: Mapping[str, Mapping[str, str]] | None = None,
) -> dict[str, Any]:
    home = home.expanduser().resolve(strict=False)
    selected_products = tuple(dict.fromkeys(products))
    if not selected_products or any(product not in PRODUCTS for product in selected_products):
        raise GuardrailsError("install requires one or more supported products")
    if safety_profile is not None and safety_profile not in SAFETY_PROFILES:
        raise GuardrailsError(f"unknown safety profile: {safety_profile}")
    if trust_mode is not None and trust_mode not in TRUST_MODES:
        raise GuardrailsError(f"unknown trust mode: {trust_mode}")
    if routing_profile is not None and routing_profile not in {"none", "economy", "balanced", "quality"}:
        raise GuardrailsError(f"unknown routing profile: {routing_profile}")
    if model_overrides and sorted(set(model_overrides) - set(selected_products)):
        raise GuardrailsError("model override references a product outside the selected installation")
    generated_artifacts = build.build_artifacts(selected_products)
    current = state.load_state(home)
    packs_were_selected = bool(pack_ids) or all_packs
    available_packs = packs.load_packs()
    requested_packs = _selected_packs(pack_ids, all_packs)
    stable_default_packs = tuple(sorted(available_packs))
    product_settings: dict[str, dict[str, Any]] = {}
    for product in selected_products:
        existing = current.get("products", {}).get(product, {})
        existing = existing if isinstance(existing, Mapping) else {}
        profile = routing_profile if routing_profile is not None else str(existing.get("routing_profile", "none"))
        if packs_were_selected:
            selected_packs = requested_packs
        elif existing:
            selected_packs = tuple(str(value) for value in existing.get("installed_packs", []))
        else:
            selected_packs = stable_default_packs
        selected_packs = packs.selected_pack_closure(selected_packs, available_packs)
        selected_safety = safety_profile or str(existing.get("safety_profile", "infrastructure-observe"))
        selected_trust = trust_mode or str(existing.get("trust_mode", "trusted-workspace"))
        if selected_safety not in SAFETY_PROFILES or selected_trust not in TRUST_MODES:
            raise GuardrailsError(f"existing {product} installation contains an unsupported safety or trust profile")
        if model_overrides is not None and product in model_overrides:
            selected_overrides = dict(model_overrides[product])
        else:
            selected_overrides = dict(existing.get("model_overrides", {}))
        if profile == "none" and selected_overrides:
            raise GuardrailsError(f"model overrides for {product} require a non-none routing profile")
        product_settings[product] = {
            "routing_profile": profile,
            "installed_packs": selected_packs,
            "safety_profile": selected_safety,
            "trust_mode": selected_trust,
            "model_overrides": selected_overrides,
        }
        product_overrides = {product: selected_overrides} if selected_overrides else None
        _preflight_collisions(
            (product,),
            home,
            current,
            selected_packs,
            profile,
            product_overrides,
            generated_artifacts,
            force=force,
        )
    already_current = _selected_installation_is_current(
        current,
        selected_products,
        product_settings,
        home,
    )
    new_state = json.loads(json.dumps(current))
    source_digest = state.source_digest()
    indicators = _managed_enterprise_indicators()
    if indicators:
        print("managed configuration detected: " + ", ".join(indicators))
        print("higher-precedence enterprise policy may limit or ignore user-level hooks; no managed file was changed")
    for product in selected_products:
        settings = product_settings[product]
        profile = settings["routing_profile"]
        selected_packs = settings["installed_packs"]
        selected_safety = settings["safety_profile"]
        selected_trust = settings["trust_mode"]
        selected_overrides = settings["model_overrides"]
        product_overrides = {product: selected_overrides} if selected_overrides else None
        product_state = new_state
        digest, payloads = _runtime_payloads(
            home,
            product,
            selected_packs,
            profile,
            selected_safety,
            selected_trust,
            product_overrides,
            generated_artifacts,
        )
        runtime = _install_runtime(home, digest, payloads, dry_run=dry_run)
        product_records: list[dict[str, Any]] = [_runtime_record(runtime, home, digest)]
        if product == "codex":
            product_records.extend(
                _install_codex(
                    home,
                    runtime,
                    product_state,
                    generated_artifacts,
                    force=force,
                    dry_run=dry_run,
                )
            )
        elif product == "claude":
            product_records.extend(
                _install_claude(
                    home,
                    runtime,
                    product_state,
                    generated_artifacts,
                    force=force,
                    dry_run=dry_run,
                )
            )
        else:
            product_records.extend(_install_cursor(home, runtime, product_state, force=force, dry_run=dry_run))
        product_records.extend(
            _install_skills(product, home, product_state, selected_packs, force=force, dry_run=dry_run)
        )
        product_records.extend(
            _install_agents(
                product,
                home,
                product_state,
                profile,
                product_overrides,
                force=force,
                dry_run=dry_run,
            )
        )
        _remove_obsolete_product_records(
            product,
            product_records,
            home,
            product_state,
            force=force,
            dry_run=dry_run,
        )
        new_state.setdefault("products", {})[product] = {
            "source_digest": source_digest,
            "policy_digest": json.loads(payloads["metadata.json"])["policy_digest"],
            "runtime_digest": digest,
            "routing_profile": profile,
            "safety_profile": selected_safety,
            "trust_mode": selected_trust,
            "installed_packs": list(selected_packs),
            "model_overrides": selected_overrides,
            "managed": product_records,
            "model_availability": "unverified",
        }
        if product == "codex":
            new_state["products"][product]["product_home"] = relative_home(codex_home(home), home)
    new_state["format_version"] = state.FORMAT_VERSION
    new_state["source_digest"] = source_digest
    new_state["policy_digest"] = _aggregate_policy_digest(new_state["products"])
    new_state["installed_packs"] = sorted(
        {identifier for data in new_state["products"].values() for identifier in data.get("installed_packs", [])}
    )
    for field, default in (
        ("routing_profile", "none"),
        ("safety_profile", "infrastructure-observe"),
        ("trust_mode", "trusted-workspace"),
    ):
        new_state[field] = _uniform_product_setting(new_state["products"], field, default)
    new_state["runtime_digest"] = new_state["products"][selected_products[-1]]["runtime_digest"]
    new_state["runtime_path"] = next(
        record["path"]
        for record in new_state["products"][selected_products[-1]]["managed"]
        if record["kind"] == "runtime-directory"
    )
    manual_steps = [step for step in new_state.get("manual_steps", []) if step.get("product") != "cursor"]
    if "cursor" in new_state["products"]:
        manual_steps.append(
            {
                "product": "cursor",
                "id": "cursor-user-rules",
                "status": "outstanding",
                "instruction": "Paste print-cursor-rules output into Cursor Settings / Customize / Rules / User Rules.",
            }
        )
    new_state["manual_steps"] = manual_steps
    if dry_run:
        print("dry run complete; no files were changed")
        return {
            "home": str(home),
            "products": selected_products,
            "product_settings": product_settings,
            "records": {product: state.product_records(new_state, product) for product in selected_products},
            "changed_records": {
                product: [
                    record
                    for record in state.product_records(new_state, product)
                    if _managed_record_status(record, home, product) != "installed"
                ]
                for product in selected_products
            },
            "already_current": already_current,
            "dry_run": True,
            "integrity": "not-run",
            "manual_steps": list(new_state["manual_steps"]),
        }
    state.save_state(home, new_state, dry_run=False)
    _post_install_integrity(new_state, selected_products, home)
    _cleanup_runtimes(home, new_state)
    print(f"installation state written to {home_path(home, state.STATE_RELATIVE)}")
    print(
        "installed packs: "
        + "; ".join(
            f"{product}={','.join(product_settings[product]['installed_packs']) or 'none'}"
            for product in selected_products
        )
    )
    print(
        "routing profiles: "
        + ", ".join(f"{product}={product_settings[product]['routing_profile']}" for product in selected_products)
        + "; model availability: unverified; main-session model unchanged"
    )
    print(
        "safety/trust: "
        + ", ".join(
            f"{product}={product_settings[product]['safety_profile']}/{product_settings[product]['trust_mode']}"
            for product in selected_products
        )
    )
    if "cursor" in selected_products:
        print("manual step required: paste `python tools/guardrails.py print-cursor-rules` output into Cursor Settings / Customize / Rules / User Rules")
    return {
        "home": str(home),
        "products": selected_products,
        "product_settings": product_settings,
        "records": {product: state.product_records(new_state, product) for product in selected_products},
        "changed_records": {},
        "already_current": already_current,
        "dry_run": False,
        "integrity": "passed",
        "manual_steps": list(new_state["manual_steps"]),
    }


def update(
    products: Sequence[str],
    home: Path,
    *,
    force: bool,
    dry_run: bool,
) -> dict[str, Any]:
    current = state.load_state(home)
    installed = [product for product in products if product in current.get("products", {})]
    if not installed:
        raise GuardrailsError("no selected product is installed; use install first")
    return install(tuple(installed), home, force=force, dry_run=dry_run)


def print_consumer_install_summary(
    report: Mapping[str, Any],
    detected: Mapping[str, Sequence[str]],
    repository_detection: packs.DetectionResult,
) -> None:
    home = Path(str(report["home"]))
    products = tuple(str(product) for product in report["products"])
    settings = report["product_settings"]
    detected_labels = [PRODUCT_LABELS[product] for product in PRODUCTS if product in detected]
    selected_labels = [PRODUCT_LABELS[product] for product in products]
    print("Installation preview" if report["dry_run"] else "Installation summary")
    print("Detected products: " + (", ".join(detected_labels) if detected_labels else "none"))
    if tuple(product for product in PRODUCTS if product in detected) != products:
        print("Selected products: " + ", ".join(selected_labels) + " (explicit selection)")
    print("Build and local compatibility validation: passed")
    print(
        "Repository capability detection: complete "
        f"({len(repository_detection.active_packs)} currently relevant capability area(s))"
    )
    stable_pack_count = len({pack for product in products for pack in settings[product]["installed_packs"]})
    print(f"Capability guidance: {stable_pack_count} stable pack(s), installed as on-demand skills")

    print("\nDefault safety posture")
    print("- Normal application development: enabled")
    print("- Infrastructure observation and local validation/planning: enabled")
    safety_profiles = {str(settings[product]["safety_profile"]) for product in products}
    if safety_profiles == {"infrastructure-nonprod"}:
        print("- Remote infrastructure mutation: mapped dev/tst/int targets only; production denied")
    else:
        print("- Remote infrastructure and production mutation: denied")
    print("- Unknown remote targets: protected; no target mapping required")
    routing_profiles = {str(settings[product]["routing_profile"]) for product in products}
    if routing_profiles == {"none"}:
        print("- Model/subagent routing: disabled; primary model unchanged")
    else:
        print("- Model/subagent routing: explicitly configured; primary model unchanged")
    print("- Audit: local and redacted; no prompts, source, full commands, arguments, or secrets")
    print(
        "- Denied operation classes: destructive, sensitive-read, publish, "
        "privilege-escalation, guardrail-modification"
    )
    print("- Examples denied: destructive Git, package/release publication, credential reads, and unsafe infrastructure changes")

    changed_by_path: dict[str, Mapping[str, Any]] = {}
    for product in products:
        for record in report.get("changed_records", {}).get(product, []):
            relative = record.get("path")
            if isinstance(relative, str):
                changed_by_path.setdefault(relative, record)
    skills = sorted(
        Path(relative).name
        for relative, record in changed_by_path.items()
        if record.get("kind") == "directory" and "/skills/" in f"/{relative}"
    )
    agents = sorted(
        Path(relative).name
        for relative in changed_by_path
        if "/agents/" in f"/{relative}"
    )
    configuration = [
        (relative, record)
        for relative, record in changed_by_path.items()
        if record.get("kind") != "runtime-directory"
        and not (record.get("kind") == "directory" and "/skills/" in f"/{relative}")
        and "/agents/" not in f"/{relative}"
    ]

    if report["dry_run"]:
        print("\nPlanned managed changes")
        if report.get("already_current"):
            print("- Installation is already current; no managed content would change")
        else:
            print(f"- Runtime: {home / '.ai-guardrails/runtime/<content-addressed-version>'}")
            print(f"- Installation state: {home_path(home, state.STATE_RELATIVE)}")
            for relative, record in configuration:
                label = {
                    "managed-block": "Managed block",
                    "json-hook": "Hook configuration",
                    "file": "File",
                }.get(str(record.get("kind")), "Managed path")
                print(f"- {label}: {home_path(home, relative)}")
        print("Skills to install: " + (", ".join(skills) if skills else "none (already current)"))
        print(
            "Agents to install: "
            + (", ".join(agents) if agents else "none (model/subagent routing disabled)")
        )
        backup_targets = sorted(
            home_path(home, relative)
            for relative, record in changed_by_path.items()
            if record.get("backup")
        )
        print("Backups planned for: " + (", ".join(str(path) for path in backup_targets) if backup_targets else "none"))
    elif report.get("already_current"):
        print("\nInstallation is already current; managed files were verified and left unchanged")
    else:
        print("\nManaged configuration and on-demand skills were installed")

    print(
        "Left unchanged: primary model, approval/sandbox/network settings, existing permission rules, "
        "credentials, target mappings, enterprise configuration, and remote services"
    )
    if "cursor" in products:
        print(
            "Manual step after install: run `python tools/guardrails.py print-cursor-rules`, then paste the "
            "complete output into Cursor Settings / Customize / Rules / User Rules"
        )
    else:
        print("Manual steps after install: none")
    if report["dry_run"]:
        print("No changes were made")
    else:
        print(f"Installation integrity: {report['integrity']}")


def _managed_record_status(record: Mapping[str, Any], home: Path, product: str) -> str:
    relative = record.get("path")
    if not isinstance(relative, str):
        return "missing"
    target = home_path(home, relative)
    kind = record.get("kind")
    if kind == "managed-block":
        if target.is_symlink():
            return "modified"
        if not target.is_file():
            return "missing"
        try:
            text = target.read_text(encoding="utf-8")
        except (OSError, UnicodeError):
            return "modified"
        matches = list(_block_pattern().finditer(text))
        if len(matches) != 1:
            return "missing" if not matches else "modified"
        return "installed" if sha256(matches[0].group(0).encode("utf-8")) == record.get("managed_sha256") else "modified"
    if kind == "json-hook":
        if target.is_symlink():
            return "modified"
        if not target.is_file():
            return "missing"
        try:
            data = read_json(target, default={})
        except GuardrailsError:
            return "modified"
        if not isinstance(data, Mapping):
            return "modified"
        groups = _managed_hook_groups(data, product)
        if not groups:
            return "missing"
        if len(groups) > 1:
            return "modified"
        return "installed" if sha256(json_bytes(groups[0])) == record.get("managed_sha256") else "modified"
    return state.record_status(record, home)


def _credential_indicators() -> list[str]:
    groups = {
        "Azure": {"AZURE_CLIENT_SECRET", "AZURE_CLIENT_CERTIFICATE_PATH"},
        "Spacelift": {"SPACELIFT_API_TOKEN", "SPACELIFT_API_KEY_SECRET"},
        "Kubernetes": {"KUBECONFIG"},
        "cloud": {"AWS_SECRET_ACCESS_KEY", "GOOGLE_APPLICATION_CREDENTIALS"},
        "package registry": {"NPM_TOKEN", "TWINE_PASSWORD", "NUGET_API_KEY"},
    }
    return sorted(label for label, names in groups.items() if any(name in os.environ for name in names))


def _target_mapping_status(home: Path) -> tuple[str, str]:
    target_path = home_path(home, TARGETS_RELATIVE)
    if not target_path.exists():
        return "missing", "missing; unknown remote targets are protected"
    try:
        target_data = read_json(target_path, default={})
        classifications = target_data.get("classifications") if isinstance(target_data, Mapping) else None
        valid = (
            isinstance(target_data, Mapping)
            and target_data.get("schema_version") == 1
            and isinstance(classifications, Mapping)
            and all(
                isinstance(name, str)
                and isinstance(mapping, Mapping)
                and all(isinstance(key, str) and lifecycle in LIFECYCLES for key, lifecycle in mapping.items())
                for name, mapping in classifications.items()
            )
        )
        if not valid:
            raise GuardrailsError("target mapping has an invalid schema or lifecycle")
    except GuardrailsError as exc:
        return "invalid", f"invalid; unknown remote targets are protected ({exc})"
    return "configured", "configured and structurally valid"


def _unmanaged_collisions(product: str, home: Path, installed_state: Mapping[str, Any]) -> list[Path]:
    managed = {record.get("path") for record in state.all_records(installed_state)}
    collisions: list[Path] = []
    for skill_file in policy.discover_skills():
        target = _skill_root(home, product) / skill_file.parent.name
        if target.exists() and relative_home(target, home) not in managed:
            collisions.append(target)
    for filename in routing.render_agents(product):
        target = _agent_root(home, product) / filename
        if target.exists() and relative_home(target, home) not in managed:
            collisions.append(target)
    return collisions


def status(
    products: Sequence[str],
    home: Path,
    *,
    show_routing_details: bool = False,
    repo: Path | None = None,
) -> dict[str, Any]:
    home = home.expanduser().resolve(strict=False)
    installed_state = state.load_state(home)
    detected_local = detect_products(home)
    source = state.source_digest()
    _, target_mapping = _target_mapping_status(home)
    result: dict[str, Any] = {
        "home": str(home),
        "products": {},
        "safety_profile": None,
        "trust_mode": None,
        "installed_packs": installed_state.get("installed_packs", []),
        "target_mapping": target_mapping,
        "credential_capability_detected": bool(_credential_indicators()),
        "credential_classes": _credential_indicators(),
    }
    for product in products:
        product_data = installed_state.get("products", {}).get(product)
        product_result: dict[str, Any] = {}
        if not isinstance(product_data, Mapping):
            collisions = _unmanaged_collisions(product, home, installed_state)
            product_result["state"] = "unmanaged-collision" if collisions else "missing"
            product_result["collisions"] = [str(path) for path in collisions]
        else:
            record_states = [
                _managed_record_status(record, home, product)
                for record in state.product_records(installed_state, product)
            ]
            if "modified" in record_states:
                product_result["state"] = "modified"
            elif "missing" in record_states:
                product_result["state"] = "missing"
            elif product_data.get("source_digest") != source:
                product_result["state"] = "stale"
            else:
                product_result["state"] = "installed"
            if (
                product == "codex"
                and product_result["state"] == "installed"
                and product_data.get("product_home", ".codex") != relative_home(codex_home(home), home)
            ):
                product_result["state"] = "stale"
            product_result["managed_paths"] = len(record_states)
            product_result["runtime_digest"] = product_data.get("runtime_digest")
            product_result["routing_profile"] = product_data.get("routing_profile", "none")
            product_result["safety_profile"] = product_data.get("safety_profile", "infrastructure-observe")
            product_result["trust_mode"] = product_data.get("trust_mode", "trusted-workspace")
            product_result["model_availability"] = "unverified"
            product_result["installed_packs"] = product_data.get("installed_packs", [])
            product_result["shell_enforcement"] = "configured" if any(
                record.get("kind") == "json-hook" for record in state.product_records(installed_state, product)
            ) else "missing"
            product_result["structured_tool_enforcement"] = product_result["shell_enforcement"]
            product_result["spacelift_mcp_enforcement"] = (
                "read-only tools allowed; mutate/intent denied"
                if "spacelift" in product_data.get("installed_packs", [])
                else "pack not installed"
            )
        product_result["product_availability"] = "available" if product in detected_local else "unavailable"
        if product == "codex":
            product_result["effective_global_instruction_file"] = str(effective_codex_policy(home))
            product_result["hook_trust"] = (
                "unverified; changed user hooks may require Codex trust review"
                if isinstance(product_data, Mapping)
                else "not installed"
            )
        if product == "cursor":
            product_result["manual_user_rules"] = (
                "outstanding" if isinstance(product_data, Mapping) else "not-applicable"
            )
        result["products"][product] = product_result
    installed_products = {
        product: data
        for product, data in installed_state.get("products", {}).items()
        if isinstance(data, Mapping)
    }
    if installed_products:
        result["safety_profile"] = _uniform_product_setting(
            installed_products, "safety_profile", "infrastructure-observe"
        )
        result["trust_mode"] = _uniform_product_setting(
            installed_products, "trust_mode", "trusted-workspace"
        )
    if repo is not None:
        detection = packs.detect_packs(repo)
        result["repository"] = detection.as_dict()
    print(f"selected home: {home}")
    for product, product_result in result["products"].items():
        print(f"{product}: state: {product_result['state']}; product: {product_result['product_availability']}")
        if product == "codex":
            print(f"  effective global instruction file: {product_result['effective_global_instruction_file']}")
            print(f"  hook activation: {product_result['hook_trust']}")
        if isinstance(product_result.get("routing_profile"), str):
            print(f"  routing: configured ({product_result['routing_profile']}); availability: unverified")
            print(
                f"  safety/trust: {product_result['safety_profile']}/{product_result['trust_mode']}"
            )
            if show_routing_details and isinstance(installed_state.get("products", {}).get(product), Mapping):
                overrides = installed_state["products"][product].get("model_overrides", {})
                models = routing.resolved_models(product, routing.load_config(), {product: overrides})
                print("  model mappings: " + ", ".join(f"{tier}={model}" for tier, model in models.items()))
                print("  selected models may be unavailable; product fallback may apply; main-session model unchanged")
        if product == "cursor":
            if product_result["manual_user_rules"] == "outstanding":
                print("  manual step outstanding: paste generated User Rules in Cursor Settings / Customize / Rules / User Rules")
        if product_result.get("installed_packs") is not None:
            installed = product_result.get("installed_packs") or []
            print(f"  packs: {', '.join(installed) if installed else 'none'}")
            print(f"  shell enforcement: {product_result.get('shell_enforcement', 'missing')}")
            print(f"  structured-tool enforcement: {product_result.get('structured_tool_enforcement', 'missing')}")
            print(f"  Spacelift MCP: {product_result.get('spacelift_mcp_enforcement', 'pack not installed')}")
    print(f"active safety profile: {result['safety_profile'] or 'not installed'}")
    print(f"active trust mode: {result['trust_mode'] or 'not installed'}")
    print(f"target mapping: {result['target_mapping']}")
    print("package publication policy: denied")
    indicators = result["credential_classes"]
    print(f"production-capable credential indicators: {'detected (' + ', '.join(indicators) + ')' if indicators else 'not detected'}; values were not inspected")
    return result


def diff_installed(products: Sequence[str], home: Path) -> dict[str, Any]:
    installed_state = state.load_state(home)
    report: dict[str, Any] = {"products": {}}
    for product in products:
        records = state.product_records(installed_state, product)
        statuses = [
            {"path": record.get("path"), "state": _managed_record_status(record, home, product)}
            for record in records
        ]
        report["products"][product] = statuses
        print(f"{product}:")
        if not statuses:
            print("  not installed")
        for item in statuses:
            print(f"  {item['state']}: {item['path']}")
    return report


def effective_configuration(products: Sequence[str], home: Path, repo: Path | None = None) -> dict[str, Any]:
    home = home.expanduser().resolve(strict=False)
    installed_state = state.load_state(home)
    installed_products = {
        product: data
        for product, data in installed_state.get("products", {}).items()
        if isinstance(data, Mapping)
    }
    result: dict[str, Any] = {
        "products": {},
        "safety_profile": _uniform_product_setting(
            installed_products, "safety_profile", "infrastructure-observe"
        ),
        "trust_mode": _uniform_product_setting(
            installed_products, "trust_mode", "trusted-workspace"
        ),
        "target_mapping": relative_home(home_path(home, TARGETS_RELATIVE), home),
        "unknown_targets": "protected",
    }
    for product in products:
        data = installed_state.get("products", {}).get(product, {})
        if not isinstance(data, Mapping):
            data = {}
        product_result: dict[str, Any] = {
            "installed": bool(data),
            "packs": data.get("installed_packs", []),
            "routing_profile": data.get("routing_profile", "none"),
            "safety_profile": data.get("safety_profile", "infrastructure-observe"),
            "trust_mode": data.get("trust_mode", "trusted-workspace"),
            "model_availability": "unverified",
            "runtime_digest": data.get("runtime_digest"),
            "main_session_model_unchanged": True,
        }
        runtime_record = next(
            (
                record
                for record in state.product_records(installed_state, product)
                if record.get("kind") == "runtime-directory"
            ),
            None,
        )
        if runtime_record is not None and isinstance(runtime_record.get("path"), str):
            from . import enforcement

            runtime = home_path(home, str(runtime_record["path"]))
            active = enforcement.load_installed_policy(
                runtime / "command-policy.json", runtime / "structured-tool-policy.json"
            )
            rollout_counts = {mode: 0 for mode in ("disabled", "observe", "warn", "deny")}
            for rule in (*active["rules"], *active["structured_tool_rules"]):
                rollout_counts[str(rule.get("rollout_mode", "deny"))] += 1
            product_result["effective_policy"] = {
                "digest": data.get("policy_digest"),
                "command_rules": len(active["rules"]),
                "classifications": len(active["classifications"]),
                "structured_tool_rules": len(active["structured_tool_rules"]),
                "rollout_modes": rollout_counts,
            }
        else:
            product_result["effective_policy"] = None
        result["products"][product] = product_result
    if repo is not None:
        result["repository_detection"] = packs.detect_packs(repo).as_dict()
    print(json.dumps(result, indent=2, sort_keys=True))
    return result


def doctor(products: Sequence[str], home: Path) -> dict[str, Any]:
    home = home.expanduser().resolve(strict=False)
    checks: list[dict[str, str]] = []

    def add(identifier: str, outcome: str, detail: str) -> None:
        checks.append({"id": identifier, "outcome": outcome, "detail": detail})

    version_ok = sys.version_info >= (3, 11)
    add("python-version", "pass" if version_ok else "fail", sys.version.split()[0])
    try:
        build.assert_generated_current(PRODUCTS)
        add("generated-output", "pass", "current")
    except GuardrailsError as exc:
        add("generated-output", "fail", str(exc))
    try:
        policy.load_manifest()
        policy.validate_canonical_data()
        packs.validate_packs()
        routing.load_config()
        add("canonical-data", "pass", "valid")
    except GuardrailsError as exc:
        add("canonical-data", "fail", str(exc))
    registry = home_path(home, ".ai-guardrails/trusted-components.json")
    if registry.is_file():
        try:
            supply_findings = policy.supply_chain_findings(registry)
            add(
                "supply-chain-registry",
                "warn" if supply_findings else "pass",
                "; ".join(supply_findings) if supply_findings else "declared components are structurally valid and pinned",
            )
        except GuardrailsError as exc:
            add("supply-chain-registry", "fail", str(exc))
    else:
        add("supply-chain-registry", "skip", "no workstation-local trusted component registry")
    try:
        installed_state = state.load_state(home)
        add("installation-state", "pass", "valid")
    except GuardrailsError as exc:
        installed_state = state.empty_state()
        add("installation-state", "fail", str(exc))
    for product in products:
        data = installed_state.get("products", {}).get(product)
        if not isinstance(data, Mapping):
            add(f"{product}-installation", "skip", "not installed")
            continue
        statuses = [_managed_record_status(item, home, product) for item in state.product_records(installed_state, product)]
        add(
            f"{product}-installation",
            "pass" if statuses and set(statuses) == {"installed"} else "fail",
            ", ".join(statuses) if statuses else "no managed paths",
        )
        if product == "codex":
            add("codex-effective-policy", "pass", str(effective_codex_policy(home)))
    target_state, target_detail = _target_mapping_status(home)
    target_outcome = {"configured": "pass", "missing": "warn", "invalid": "fail"}[target_state]
    add("target-mapping", target_outcome, target_detail)
    for executable in ("codex", "opa"):
        add(f"optional-{executable}", "pass" if shutil.which(executable) else "skip", "available" if shutil.which(executable) else "not installed")
    if "cursor" in installed_state.get("products", {}):
        add("cursor-user-rules", "warn", "manual User Rules paste remains outstanding")
    for check in checks:
        print(f"{check['outcome']}: {check['id']}: {check['detail']}")
    return {"checks": checks}


def _remove_managed_block(record: Mapping[str, Any], home: Path, *, force: bool, dry_run: bool) -> bool:
    target = home_path(home, str(record["path"]))
    if target.is_symlink():
        print(f"retained symbolic-link managed block path: {target}")
        return False
    if not target.is_file():
        return True
    try:
        text = target.read_text(encoding="utf-8")
    except (OSError, UnicodeError):
        if not force:
            print(f"retained modified managed block: {target}")
            return False
        return state.remove_record(record, home, force=True, dry_run=dry_run)
    matches = list(_block_pattern().finditer(text))
    if not matches:
        return True
    modified = len(matches) > 1 or sha256(matches[0].group(0).encode("utf-8")) != record.get("managed_sha256")
    if modified:
        if not force:
            print(f"retained modified managed block: {target}")
            return False
        state.backup_existing(home, target, dry_run=dry_run)
    updated = _block_pattern().sub("", text, count=1).strip()
    print(f"{'would remove' if dry_run else 'remove'} managed block from {target}")
    if not dry_run:
        if not updated and record.get("created"):
            target.unlink()
        else:
            atomic_write(target, (updated + "\n").encode("utf-8") if updated else b"")
    return True


def _remove_json_hook(record: Mapping[str, Any], product: str, home: Path, *, force: bool, dry_run: bool) -> bool:
    target = home_path(home, str(record["path"]))
    if not target.is_file():
        return True
    try:
        data = read_json(target, default={})
    except GuardrailsError:
        if target.is_symlink():
            print(f"retained symbolic-link hook configuration: {target}")
            return False
        if not force:
            print(f"retained modified hook configuration: {target}")
            return False
        return state.remove_record(record, home, force=True, dry_run=dry_run)
    if not isinstance(data, dict):
        if not force:
            print(f"retained modified hook configuration: {target}")
            return False
        return state.remove_record(record, home, force=True, dry_run=dry_run)
    groups = _managed_hook_groups(data, product)
    if not groups:
        return True
    modified = len(groups) != 1 or sha256(json_bytes(groups[0])) != record.get("managed_sha256")
    if modified:
        if not force:
            print(f"retained modified managed hook: {target}")
            return False
        state.backup_existing(home, target, dry_run=dry_run)
    _remove_managed_hook_groups(data, product)
    print(f"{'would remove' if dry_run else 'remove'} managed hook from {target}")
    if not dry_run:
        only_installer_scaffold = not data or (product == "cursor" and data == {"version": 1})
        if only_installer_scaffold and record.get("created"):
            target.unlink()
        else:
            atomic_write(target, json_bytes(data))
    return True


def uninstall(products: Sequence[str], home: Path, *, force: bool, dry_run: bool) -> None:
    home = home.expanduser().resolve(strict=False)
    installed_state = state.load_state(home)
    new_state = json.loads(json.dumps(installed_state))
    retained_any = False
    selected = set(products)
    handled_paths: set[str] = set()
    codex_empty_parents = {
        home_path(home, str(record["path"])).parent
        for record in state.product_records(installed_state, "codex")
        if isinstance(record.get("path"), str)
        and home_path(home, str(record["path"])).parent.name in {"agents", "rules"}
    }
    for product in products:
        records = sorted(
            state.product_records(installed_state, product),
            key=lambda item: item.get("kind") == "runtime-directory",
        )
        retained: list[dict[str, Any]] = []
        retained_hook = False
        for record in records:
            relative = record.get("path")
            if not isinstance(relative, str):
                continue
            if relative in handled_paths:
                continue
            if state.owners(installed_state, relative, excluding=selected):
                print(f"retained shared managed path: {home_path(home, relative)}")
                continue
            kind = record.get("kind")
            if kind == "runtime-directory" and retained_hook and not force:
                print(f"retained runtime required by modified managed hook: {home_path(home, relative)}")
                removed = False
            elif kind == "managed-block":
                removed = _remove_managed_block(record, home, force=force, dry_run=dry_run)
            elif kind == "json-hook":
                removed = _remove_json_hook(record, product, home, force=force, dry_run=dry_run)
            else:
                removed = state.remove_record(record, home, force=force, dry_run=dry_run)
            if not removed:
                retained.append(record)
                retained_any = True
                retained_hook = retained_hook or kind == "json-hook"
            else:
                handled_paths.add(relative)
        if retained:
            product_data = dict(new_state["products"][product])
            product_data["managed"] = retained
            product_data["partial_uninstall"] = True
            new_state["products"][product] = product_data
        else:
            new_state.get("products", {}).pop(product, None)
    new_state["installed_packs"] = sorted(
        {identifier for data in new_state.get("products", {}).values() for identifier in data.get("installed_packs", [])}
    )
    new_state["policy_digest"] = _aggregate_policy_digest(new_state.get("products", {}))
    for field, default in (
        ("routing_profile", "none"),
        ("safety_profile", "infrastructure-observe"),
        ("trust_mode", "trusted-workspace"),
    ):
        new_state[field] = _uniform_product_setting(new_state.get("products", {}), field, default)
    new_state["manual_steps"] = [
        step for step in new_state.get("manual_steps", []) if step.get("product") not in selected
    ]
    runtime_products = [
        data
        for data in new_state.get("products", {}).values()
        if isinstance(data, Mapping)
        and any(item.get("kind") == "runtime-directory" for item in data.get("managed", []))
    ]
    if runtime_products:
        new_state["runtime_digest"] = runtime_products[-1].get("runtime_digest")
        runtime_record = next(
            item for item in runtime_products[-1]["managed"] if item.get("kind") == "runtime-directory"
        )
        new_state["runtime_path"] = runtime_record.get("path")
    else:
        new_state["runtime_digest"] = None
        new_state["runtime_path"] = None
    if dry_run:
        print("dry run complete; no files were changed")
        return
    state.save_state(home, new_state, dry_run=False)
    _cleanup_runtimes(home, new_state)
    state.remove_empty_parents(
        home,
        [
            *sorted(codex_empty_parents),
            home_path(home, ".claude/rules"),
            home_path(home, ".claude/skills"),
            home_path(home, ".claude/agents"),
            home_path(home, ".cursor/agents"),
            home_path(home, ".agents/skills"),
        ],
    )
    print("uninstallation complete" + ("; modified managed paths were retained" if retained_any else ""))


def set_routing(
    products: Sequence[str],
    home: Path,
    profile_name: str,
    *,
    model_overrides: Mapping[str, Mapping[str, str]] | None,
    force: bool,
    dry_run: bool,
) -> None:
    installed_state = state.load_state(home)
    if profile_name not in {"none", "economy", "balanced", "quality"}:
        raise GuardrailsError(f"unknown routing profile: {profile_name}")
    for product in products:
        data = installed_state.get("products", {}).get(product, {})
        if not isinstance(data, Mapping) or not data:
            raise GuardrailsError(f"{product} is not installed; use install with --routing-profile")
    for product in products:
        product_data = installed_state["products"][product]
        overrides = (
            model_overrides.get(product, product_data.get("model_overrides", {}))
            if model_overrides is not None
            else product_data.get("model_overrides", {})
        )
        install(
            (product,),
            home,
            force=force,
            dry_run=dry_run,
            pack_ids=product_data.get("installed_packs", []),
            routing_profile=profile_name,
            safety_profile=product_data.get("safety_profile", "infrastructure-observe"),
            trust_mode=product_data.get("trust_mode", "trusted-workspace"),
            model_overrides={product: overrides},
        )


def print_cursor_rules(*, clipboard: bool) -> None:
    content = (ROOT / "dist/cursor/user-rules.md").read_text(encoding="utf-8")
    print(content, end="")
    if not clipboard:
        return
    candidates = [
        (["pbcopy"], "pbcopy"),
        (["wl-copy"], "wl-copy"),
        (["xclip", "-selection", "clipboard"], "xclip"),
        (["xsel", "--clipboard", "--input"], "xsel"),
        (["clip"], "clip"),
    ]
    for command, executable in candidates:
        if shutil.which(executable):
            result = subprocess.run(command, input=content, text=True, check=False, capture_output=True)
            if result.returncode != 0:
                raise GuardrailsError(f"clipboard command failed: {executable}")
            print(f"\nCursor User Rules copied with {executable}; clipboard copy is not installation")
            return
    raise GuardrailsError("no supported clipboard command is available")
