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

from . import build, packs, policy, routing, state, terminal_ux
from .resources import RESOURCE_ROOT
from .util import (
    LIFECYCLES,
    PRODUCTS,
    PRODUCT_LABELS,
    PRODUCT_CAPABILITIES,
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
TERMINAL_UX_KEY = "terminal_ux"
CODEX_STATUSLINE_BEGIN = "# BEGIN AI ENGINEERING GUARDRAILS STATUSLINE"
CODEX_STATUSLINE_END = "# END AI ENGINEERING GUARDRAILS STATUSLINE"
CODEX_STATUSLINE_BLOCK_RE = re.compile(
    re.escape(CODEX_STATUSLINE_BEGIN) + r"\r?\n.*?" + re.escape(CODEX_STATUSLINE_END), re.DOTALL
)
TUI_HEADER_RE = re.compile(r"(?m)^[ \t]*\[tui\][ \t]*(?:#[^\r\n]*)?(?:\r?\n|$)")
TOML_TABLE_RE = re.compile(r"(?m)^[ \t]*\[[^\r\n]+\]")
TUI_STATUSLINE_RE = re.compile(r"(?m)^[ \t]*status_line[ \t]*=")
MANAGED_HOOK_RE = re.compile(
    r"(?:^|[/\\])hook_runtime\.py[\"']?\s+--product\s+(codex|claude|cursor|vscode)\b",
    re.IGNORECASE,
)
PRODUCT_EXECUTABLES = {
    "codex": "codex",
    "claude": "claude",
    "cursor": "cursor",
    "vscode": "code",
}
PRODUCT_CONFIG_ROOTS = {
    "codex": ".codex",
    "claude": ".claude",
    "cursor": ".cursor",
}
CODEX_AGENTS_ARTIFACT = Path("dist/codex/AGENTS.md")
CODEX_RULES_ARTIFACT = Path("dist/codex/rules/workstation-guardrails.rules")
CLAUDE_RULES_ARTIFACT = Path("dist/claude/rules")
CURSOR_RULES_ARTIFACT = Path("dist/cursor/user-rules.md")
VSCODE_INSTRUCTIONS_ARTIFACT = Path("dist/vscode/instructions/workstation-guardrails.instructions.md")
VISUALSTUDIO_INSTRUCTIONS_ARTIFACT = Path("dist/visualstudio/copilot-instructions.md")
JETBRAINS_CHAT_ARTIFACT = Path("dist/jetbrains/ai-assistant/chat-instructions.md")
JETBRAINS_PROJECT_RULE_ARTIFACT = Path("dist/jetbrains/ai-assistant/project-rules/workstation-guardrails.md")
JETBRAINS_COPILOT_ARTIFACT = Path("dist/jetbrains/copilot/global-copilot-instructions.md")


def visualstudio_capabilities(version: str | None) -> dict[str, str]:
    """Return documented feature availability without pretending version discovery succeeded."""
    if version is None:
        return {"skills": "version-unverified", "agents": "version-unverified"}
    try:
        major, minor = (int(part) for part in version.split(".", 1))
    except ValueError:
        return {"skills": "version-unverified", "agents": "version-unverified"}
    release = (major, minor)
    return {
        "skills": "compatible" if release >= (18, 5) else "too-old",
        "agents": "compatible" if release >= (18, 4) else "too-old",
    }


def _jetbrains_evidence(home: Path) -> list[str]:
    launchers = ("idea", "pycharm", "webstorm", "rider", "goland", "clion", "datagrip", "rubymine", "rustrover")
    evidence = ["launcher" for launcher in launchers if shutil.which(launcher)]
    roots = (
        home / ".config" / "JetBrains",
        home / ".local" / "share" / "JetBrains",
        home / "Library" / "Application Support" / "JetBrains",
    )
    if any(root.is_dir() and not root.is_symlink() for root in roots):
        evidence.append("configuration-root")
    return evidence


def detect_products(home: Path) -> dict[str, tuple[str, ...]]:
    """Detect supported local products from commands, configuration, or managed state."""
    home = home.expanduser().resolve(strict=False)
    installed_state = state.load_state(home)
    detected: dict[str, tuple[str, ...]] = {}
    for product in PRODUCTS:
        evidence: list[str] = []
        if product in PRODUCT_EXECUTABLES and shutil.which(PRODUCT_EXECUTABLES[product]):
            evidence.append("executable")
        if product == "vscode" and shutil.which("code-insiders"):
            evidence.append("code-insiders")
        if product == "jetbrains":
            evidence.extend(_jetbrains_evidence(home))
        if product == "visualstudio":
            if sys.platform == "win32" and shutil.which("devenv.exe"):
                evidence.append("devenv.exe")
            if sys.platform == "win32" and shutil.which("vswhere.exe"):
                evidence.append("vswhere.exe")
            standard_root = Path(os.environ.get("ProgramFiles", r"C:\\Program Files")) / "Microsoft Visual Studio"
            if sys.platform == "win32" and standard_root.is_dir() and not standard_root.is_symlink():
                evidence.append("standard-installation-root")
        config_root = home_path(home, PRODUCT_CONFIG_ROOTS.get(product, ".ai-guardrails/unavailable"))
        if product == "codex" and os.environ.get("CODEX_HOME"):
            configured = Path(os.environ["CODEX_HOME"]).expanduser()
            candidate = configured if configured.is_absolute() else home / configured
            candidate = candidate.resolve(strict=False)
            if path_within(candidate, home):
                config_root = candidate
        if product in PRODUCT_CONFIG_ROOTS and config_root.is_dir() and not config_root.is_symlink():
            evidence.append("configuration")
        if product in installed_state.get("products", {}):
            evidence.append("managed-state")
        if evidence:
            detected[product] = tuple(evidence)
    return detected


def installed_products(home: Path) -> tuple[str, ...]:
    installed_state = state.load_state(home.expanduser().resolve(strict=False))
    return tuple(product for product in PRODUCTS if product in installed_state.get("products", {}))


def prepare_installation(*, dry_run: bool, home: Path | None = None) -> None:
    """Use the existing deterministic build and validation before user-home mutation."""
    # Consumer installation never refreshes contributor output or package data.
    build.validate(PRODUCTS, require_current=False, home=home)


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
    skill_packs: Sequence[str],
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
            if source.parent == CLAUDE_RULES_ARTIFACT
            and source.name.startswith("workstation-guardrails-")
            and source.suffix == ".md"
        )
    elif product == "cursor":
        paths = [home_path(home, ".cursor/hooks.json")]
    elif product == "vscode":
        paths = [home_path(home, ".copilot/instructions/workstation-guardrails.instructions.md")]
        paths.append(home_path(home, ".copilot/hooks/workstation-guardrails.json"))
    elif product == "visualstudio":
        paths = [home_path(home, "copilot-instructions.md")]
    else:
        paths = []
        if _jetbrains_copilot_target(home) is not None:
            paths.append(_jetbrains_copilot_target(home))

    skill_sources = [source.parent for source in policy.discover_skills()]
    available = packs.load_packs()
    for identifier in skill_packs:
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
    skill_packs: Sequence[str],
    routing_profile: str,
    safety_profile: str,
    trust_mode: str,
    model_overrides: Mapping[str, Mapping[str, str]] | None,
    generated_artifacts: Mapping[Path, bytes],
) -> tuple[str, dict[str, bytes]]:
    merged = policy.load_effective_enforcement_policy(home, selected_packs)
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
    redaction_path = RESOURCE_ROOT / "enforcement/redaction-policy.json"
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
                skill_packs,
                routing_profile,
                model_overrides,
                generated_artifacts,
            )
        ],
        "installed_packs": list(selected_packs),
        "installed_skill_packs": list(skill_packs),
    }
    payloads = {
        "hook_runtime.py": (Path(__file__).with_name("enforcement.py")).read_bytes(),
        "command-policy.json": json_bytes(command),
        "structured-tool-policy.json": json_bytes(structured),
        "redaction-policy.json": redaction,
        "metadata.json": json_bytes(metadata),
    }
    digest_input = b"".join(name.encode("utf-8") + b"\0" + payloads[name] + b"\0" for name in sorted(payloads))
    return sha256(digest_input), payloads


def _validate_runtime_payloads(payloads: Mapping[str, bytes]) -> None:
    try:
        if "hook_runtime.py" in payloads:
            compile(payloads["hook_runtime.py"].decode("utf-8"), "hook_runtime.py", "exec")
            json.loads(payloads["command-policy.json"])
            json.loads(payloads["structured-tool-policy.json"])
            json.loads(payloads["redaction-policy.json"])
            json.loads(payloads["metadata.json"])
        elif set(payloads) == {"terminal_renderer.py", "statusline-profiles.json"}:
            compile(payloads["terminal_renderer.py"].decode("utf-8"), "terminal_renderer.py", "exec")
            terminal_ux.validate_resources()
            json.loads(payloads["statusline-profiles.json"])
        else:
            raise GuardrailsError("installed runtime has an unknown payload shape")
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
            mode = 0o555 if name.endswith(".py") else 0o444
            atomic_write(staged / name, data, mode=mode)
        os.replace(staged, target)
    finally:
        if staged.exists():
            shutil.rmtree(staged)
    return target


def _terminal_ux_payloads() -> tuple[str, dict[str, bytes]]:
    """Return the small immutable Claude status-line runtime payload."""
    payloads = {
        "terminal_renderer.py": Path(__file__).with_name("terminal_renderer.py").read_bytes(),
        "statusline-profiles.json": terminal_ux.PROFILE_PATH.read_bytes(),
    }
    digest_input = b"".join(name.encode("utf-8") + b"\0" + payloads[name] + b"\0" for name in sorted(payloads))
    return sha256(digest_input), payloads


def _terminal_ux_products(value: Mapping[str, Any]) -> dict[str, Any]:
    terminal = value.setdefault(TERMINAL_UX_KEY, {})
    if not isinstance(terminal, dict):
        raise GuardrailsError("terminal UX installation state is invalid")
    products = terminal.setdefault("products", {})
    if not isinstance(products, dict):
        raise GuardrailsError("terminal UX product state is invalid")
    return products


def _selected_statusline_profiles(
    products: Sequence[str], current_state: Mapping[str, Any], explicit_profile: str | None
) -> tuple[tuple[str, tuple[str, ...]], ...]:
    """Return explicit UX work, or refresh only already-managed selected products."""
    selected = tuple(product for product in products if product in terminal_ux.STATUSLINE_PRODUCTS)
    if explicit_profile is not None:
        return ((explicit_profile, selected),) if selected else ()
    stored = current_state.get(TERMINAL_UX_KEY, {}).get("products", {})
    stored = stored if isinstance(stored, Mapping) else {}
    grouped: dict[str, list[str]] = {}
    for product in selected:
        entry = stored.get(product)
        profile = entry.get("profile") if isinstance(entry, Mapping) else None
        if isinstance(profile, str) and profile in terminal_ux.STATUSLINE_PROFILES:
            grouped.setdefault(profile, []).append(product)
    return tuple((profile, tuple(grouped[profile])) for profile in sorted(grouped))


def _codex_tui_bounds(text: str) -> tuple[int, int, int] | None:
    """Return header-end, section-end, and header-start for the one [tui] table."""
    matches = list(TUI_HEADER_RE.finditer(text))
    if len(matches) > 1:
        raise GuardrailsError("multiple [tui] tables in Codex configuration")
    if not matches:
        return None
    header = matches[0]
    next_table = TOML_TABLE_RE.search(text, header.end())
    return header.end(), next_table.start() if next_table else len(text), header.start()


def _toml_assignment_end(text: str, start: int) -> int:
    """Find one status_line assignment end without normalising unrelated TOML."""
    equal = text.find("=", start)
    if equal < 0:
        return start
    index = equal + 1
    depth = 0
    quote: str | None = None
    while index < len(text):
        character = text[index]
        if quote is not None:
            if character == "\\" and quote == '"':
                index += 2
                continue
            if character == quote:
                quote = None
        elif character in {"'", '"'}:
            quote = character
        elif character in "[{":
            depth += 1
        elif character in "]}":
            depth = max(0, depth - 1)
        elif character == "#" and depth == 0:
            newline = text.find("\n", index)
            return len(text) if newline < 0 else newline + 1
        elif character == "\n" and depth == 0:
            return index + 1
        index += 1
    return len(text)


def _codex_newline(text: str) -> str:
    """Use the file's existing line ending for our one narrow managed block."""
    return "\r\n" if "\r\n" in text else "\n"


def _render_codex_statusline_block(fields: Sequence[str], *, newline: str = "\n") -> str:
    rendered = ", ".join(json.dumps(field) for field in fields)
    return f"{CODEX_STATUSLINE_BEGIN}{newline}status_line = [{rendered}]{newline}{CODEX_STATUSLINE_END}"


def _update_codex_statusline_text(text: str, fields: Sequence[str], previous: Mapping[str, Any] | None, *, force: bool) -> tuple[str, bool]:
    """Change only our status_line block while preserving all other TOML text."""
    try:
        import tomllib

        parsed = tomllib.loads(text)
    except tomllib.TOMLDecodeError as exc:
        raise GuardrailsError("Codex config.toml is invalid; refusing to change it") from exc

    def verified(updated: str, created_tui: bool) -> tuple[str, bool]:
        try:
            candidate = tomllib.loads(updated)
        except tomllib.TOMLDecodeError as exc:
            raise GuardrailsError("managed Codex status-line update would produce invalid TOML") from exc
        configured = candidate.get("tui", {}).get("status_line") if isinstance(candidate.get("tui"), Mapping) else None
        if configured != list(fields):
            raise GuardrailsError("managed Codex status-line update did not produce the requested tui.status_line")
        return updated, created_tui

    bounds = _codex_tui_bounds(text)
    newline = _codex_newline(text)
    block = _render_codex_statusline_block(fields, newline=newline)
    blocks = list(CODEX_STATUSLINE_BLOCK_RE.finditer(text))
    if len(blocks) > 1:
        raise GuardrailsError("multiple managed Codex status-line blocks found")
    if blocks:
        current = blocks[0]
        if bounds is None or not (bounds[0] <= current.start() < bounds[1]):
            raise GuardrailsError("managed Codex status-line block is outside [tui]")
        expected = previous.get("managed_sha256") if previous else None
        if expected is None and not force:
            raise GuardrailsError("unmanaged Codex status-line block collision; refusing to replace without --force")
        if expected is not None and sha256(current.group(0).encode("utf-8")) != expected and not force:
            raise GuardrailsError("locally modified managed Codex status line; refusing to replace without --force")
        updated = text[:current.start()] + block + text[current.end():]
        return verified(updated, False)
    tui_value = parsed.get("tui")
    existing = tui_value.get("status_line") if isinstance(tui_value, Mapping) else None
    if existing is not None and not force:
        raise GuardrailsError("unmanaged Codex tui.status_line collision; refusing to replace without --force")
    if bounds is not None:
        section_start, section_end, _ = bounds
        assignment = TUI_STATUSLINE_RE.search(text, section_start, section_end)
        if assignment:
            assignment_end = _toml_assignment_end(text, assignment.start())
            updated = text[:assignment.start()] + block + newline + text[assignment_end:]
        else:
            updated = text[:section_start] + block + newline + text[section_start:]
        return verified(updated, False)
    separator = "" if not text or text.endswith(("\n", "\r")) else newline
    prefix = "" if not text.strip() else separator + newline
    return verified(text + prefix + "[tui]" + newline + block + newline, True)


def _install_codex_statusline(
    home: Path,
    profile: str,
    current_state: dict[str, Any],
    *,
    force: bool,
    dry_run: bool,
) -> dict[str, Any]:
    target = codex_home(home) / "config.toml"
    validate_install_target(target, home)
    text = target.read_bytes().decode("utf-8") if target.is_file() and not target.is_symlink() else ""
    if target.exists() and (target.is_symlink() or not target.is_file()):
        raise GuardrailsError(f"Codex configuration collides with a non-file: {target}")
    products = _terminal_ux_products(current_state)
    previous_value = products.get("codex")
    previous = previous_value if isinstance(previous_value, Mapping) else None
    fields = terminal_ux.CODEX_NATIVE_FIELDS[profile]
    updated, created_tui = _update_codex_statusline_text(text, fields, previous, force=force)
    if updated != text:
        backup = state.backup_existing(home, target, dry_run=dry_run) if target.exists() else None
        print(f"{'would update' if dry_run else 'update'} managed Codex status line in {target}")
        if not dry_run:
            atomic_write(target, updated.encode("utf-8"))
    else:
        backup = previous.get("backup") if previous else None
        print(f"unchanged {target}")
    block = _render_codex_statusline_block(fields, newline=_codex_newline(text))
    entry = {
        "profile": profile,
        "integration": "managed-native",
        "config_path": relative_home(target, home),
        "managed_sha256": sha256(block.encode("utf-8")),
        "backup": backup or (previous.get("backup") if previous else None),
        "created_tui": created_tui if previous is None else bool(previous.get("created_tui")),
        "activation": "native-configured-unverified",
        "native_fields": list(fields),
    }
    products["codex"] = entry
    return entry


def _statusline_config_status(entry: Mapping[str, Any], home: Path) -> str:
    target = home_path(home, ".claude/settings.json")
    if target.is_symlink() or not target.is_file():
        return "missing"
    try:
        data = read_json(target, default={})
    except GuardrailsError:
        return "modified"
    value = data.get("statusLine") if isinstance(data, Mapping) else None
    if not isinstance(value, Mapping):
        return "missing"
    if terminal_ux.profile_hash(value) != entry.get("managed_sha256"):
        return "modified"
    runtime_relative = entry.get("runtime_path")
    runtime = home_path(home, runtime_relative) if isinstance(runtime_relative, str) else None
    if runtime is None or runtime.is_symlink() or not runtime.is_dir() or any(
        not (runtime / name).is_file() or (runtime / name).is_symlink()
        for name in ("terminal_renderer.py", "statusline-profiles.json")
    ):
        return "stale"
    return "configured"


def _preflight_claude_statusline(home: Path, profile: str, safety_profile: str, current_state: Mapping[str, Any], *, force: bool) -> None:
    digest, _ = _terminal_ux_payloads()
    runtime = home_path(home, RUNTIME_RELATIVE / digest)
    target = home_path(home, ".claude/settings.json")
    validate_install_target(target, home)
    products = current_state.get(TERMINAL_UX_KEY, {}).get("products", {})
    previous_value = products.get("claude") if isinstance(products, Mapping) else None
    previous = previous_value if isinstance(previous_value, Mapping) else None
    data = read_json(target, default={})
    if not isinstance(data, dict):
        raise GuardrailsError(f"Claude settings must be a JSON object: {target}")
    existing = data.get("statusLine")
    if existing is None:
        return
    existing_hash = terminal_ux.profile_hash(existing) if isinstance(existing, Mapping) else "invalid"
    managed_hash = previous.get("managed_sha256") if previous else None
    if managed_hash is None and not force:
        raise GuardrailsError(f"unmanaged Claude statusLine collision; refusing to replace without --force: {target}")
    if managed_hash is not None and existing_hash != managed_hash and not force:
        raise GuardrailsError(f"locally modified managed Claude statusLine; refusing to replace without --force: {target}")


def _install_claude_statusline(
    home: Path,
    profile: str,
    safety_profile: str,
    current_state: dict[str, Any],
    *,
    force: bool,
    dry_run: bool,
) -> dict[str, Any]:
    digest, payloads = _terminal_ux_payloads()
    runtime = home_path(home, RUNTIME_RELATIVE / digest)
    target = home_path(home, ".claude/settings.json")
    validate_install_target(target, home)
    products = _terminal_ux_products(current_state)
    previous = products.get("claude")
    previous = previous if isinstance(previous, Mapping) else None
    original_exists = target.is_file()
    data = read_json(target, default={})
    if not isinstance(data, dict):
        raise GuardrailsError(f"Claude settings must be a JSON object: {target}")
    desired = terminal_ux.claude_status_line(runtime, profile, safety_profile, home)
    _preflight_claude_statusline(home, profile, safety_profile, current_state, force=force)
    # Detect all collisions before creating a runtime directory or cache entry.
    runtime = _install_runtime(home, digest, payloads, dry_run=dry_run)
    desired = terminal_ux.claude_status_line(runtime, profile, safety_profile, home)
    backup = previous.get("backup") if previous else None
    rendered = json_bytes({**data, "statusLine": desired})
    if target.is_file() and target.read_bytes() == rendered:
        print(f"unchanged {target}")
    else:
        if target.exists():
            backup = state.backup_existing(home, target, dry_run=dry_run) or backup
        print(f"{'would merge' if dry_run else 'merge'} managed Claude statusLine into {target}")
        if not dry_run:
            atomic_write(target, rendered)
    summary = terminal_ux.audit_summary(home)
    terminal_ux.write_audit_summary_cache(home, summary, dry_run=dry_run)
    entry = {
        "profile": profile,
        "integration": "managed",
        "runtime_digest": digest,
        "runtime_path": relative_home(runtime, home),
        "settings_path": relative_home(target, home),
        "managed_sha256": terminal_ux.profile_hash(desired),
        "backup": backup,
        "created": bool(previous.get("created")) if previous else not original_exists,
        "activation": "workspace-trust-required",
        "cache_schema_version": 1,
    }
    products["claude"] = entry
    return entry


def _install_statusline_into_state(
    products: Sequence[str],
    home: Path,
    profile: str,
    current_state: dict[str, Any],
    *,
    force: bool,
    dry_run: bool,
) -> dict[str, Any]:
    if profile not in terminal_ux.STATUSLINE_PROFILES:
        raise GuardrailsError(f"unknown status-line profile: {profile}")
    selected = tuple(dict.fromkeys(products))
    if any(product not in terminal_ux.STATUSLINE_PRODUCTS for product in selected):
        raise GuardrailsError("terminal UX supports only codex, claude, and cursor")
    entries = _terminal_ux_products(current_state)
    report: dict[str, Any] = {}
    for product in selected:
        if product == "claude":
            safety = str(current_state.get("products", {}).get("claude", {}).get("safety_profile", "infrastructure-observe"))
            report[product] = _install_claude_statusline(home, profile, safety, current_state, force=force, dry_run=dry_run)
        elif product == "codex":
            report[product] = _install_codex_statusline(home, profile, current_state, force=force, dry_run=dry_run)
        else:
            entry = {
                "profile": profile,
                "integration": "native-manual",
                "manual_step": terminal_ux.codex_setup(profile) if product == "codex" else terminal_ux.cursor_setup(),
                "activation": "user-controlled",
            }
            entries[product] = entry
            report[product] = entry
    return {"profile": profile, "products": report, "no_mutation": False}


def _preflight_statusline(products: Sequence[str], home: Path, profile: str, current_state: Mapping[str, Any], *, force: bool) -> None:
    """Reject collisions for every selected product before any status-line write."""
    entries = current_state.get(TERMINAL_UX_KEY, {}).get("products", {})
    entries = entries if isinstance(entries, Mapping) else {}
    for product in products:
        if product == "claude":
            safety = str(current_state.get("products", {}).get("claude", {}).get("safety_profile", "infrastructure-observe"))
            _preflight_claude_statusline(home, profile, safety, current_state, force=force)
        elif product == "codex":
            target = codex_home(home) / "config.toml"
            validate_install_target(target, home)
            if target.exists() and (target.is_symlink() or not target.is_file()):
                raise GuardrailsError(f"Codex configuration collides with a non-file: {target}")
            text = target.read_bytes().decode("utf-8") if target.is_file() else ""
            previous_value = entries.get("codex")
            previous = previous_value if isinstance(previous_value, Mapping) else None
            _update_codex_statusline_text(text, terminal_ux.CODEX_NATIVE_FIELDS[profile], previous, force=force)


def statusline_install(products: Sequence[str], home: Path, *, profile: str, force: bool, dry_run: bool) -> dict[str, Any]:
    home = home.expanduser().resolve(strict=False)
    terminal_ux.validate_resources()
    if profile not in terminal_ux.STATUSLINE_PROFILES:
        raise GuardrailsError(f"unknown status-line profile: {profile}")
    current = state.load_state(home)
    new_state = json.loads(json.dumps(current))
    _preflight_statusline(products, home, profile, new_state, force=force)
    report = _install_statusline_into_state(products, home, profile, new_state, force=force, dry_run=dry_run)
    if not report["no_mutation"]:
        state.save_state(home, new_state, dry_run=dry_run)
        if not dry_run:
            _cleanup_runtimes(home, new_state)
    return report


def _uninstall_claude_statusline(entry: Mapping[str, Any], home: Path, *, force: bool, dry_run: bool) -> bool:
    target = home_path(home, ".claude/settings.json")
    if target.is_symlink():
        print(f"retained symbolic-link Claude settings: {target}")
        return False
    if not target.is_file():
        return True
    try:
        data = read_json(target, default={})
    except GuardrailsError:
        print(f"retained modified Claude settings: {target}")
        return False
    if not isinstance(data, dict) or "statusLine" not in data:
        return True
    current = data["statusLine"]
    if not isinstance(current, Mapping) or terminal_ux.profile_hash(current) != entry.get("managed_sha256"):
        if not force:
            print(f"retained modified Claude statusLine: {target}")
            return False
        state.backup_existing(home, target, dry_run=dry_run)
    data.pop("statusLine", None)
    print(f"{'would remove' if dry_run else 'remove'} managed Claude statusLine from {target}")
    if not dry_run:
        atomic_write(target, json_bytes(data))
    return True


def _remove_empty_owned_tui(text: str) -> str:
    bounds = _codex_tui_bounds(text)
    if bounds is None:
        return text
    section_start, section_end, header_start = bounds
    if text[section_start:section_end].strip():
        return text
    return text[:header_start] + text[section_end:].lstrip("\r\n")


def _uninstall_codex_statusline(entry: Mapping[str, Any], home: Path, *, force: bool, dry_run: bool) -> bool:
    target = codex_home(home) / "config.toml"
    if target.is_symlink():
        print(f"retained symbolic-link Codex configuration: {target}")
        return False
    if not target.is_file():
        return True
    try:
        text = target.read_bytes().decode("utf-8")
        import tomllib

        tomllib.loads(text)
    except (OSError, UnicodeError, tomllib.TOMLDecodeError):
        print(f"retained modified Codex status line: {target}")
        return False
    blocks = list(CODEX_STATUSLINE_BLOCK_RE.finditer(text))
    if len(blocks) != 1:
        print(f"retained modified Codex status line: {target}")
        return False
    block = blocks[0]
    if sha256(block.group(0).encode("utf-8")) != entry.get("managed_sha256") and not force:
        print(f"retained modified Codex status line: {target}")
        return False
    updated = text[:block.start()] + text[block.end():]
    if entry.get("created_tui"):
        updated = _remove_empty_owned_tui(updated)
    try:
        tomllib.loads(updated)
    except tomllib.TOMLDecodeError:
        print(f"retained modified Codex status line: {target}")
        return False
    if sha256(block.group(0).encode("utf-8")) != entry.get("managed_sha256"):
        state.backup_existing(home, target, dry_run=dry_run)
    print(f"{'would remove' if dry_run else 'remove'} managed Codex status line from {target}")
    if not dry_run:
            atomic_write(target, updated.encode("utf-8"))
    return True


def _uninstall_statusline_from_state(
    products: Sequence[str], home: Path, current_state: dict[str, Any], *, force: bool, dry_run: bool
) -> dict[str, str]:
    entries = _terminal_ux_products(current_state)
    report: dict[str, str] = {}
    for product in products:
        entry = entries.get(product)
        if not isinstance(entry, Mapping):
            report[product] = "not-managed"
            continue
        removed = True
        if product == "claude" and entry.get("integration") == "managed":
            removed = _uninstall_claude_statusline(entry, home, force=force, dry_run=dry_run)
        elif product == "codex" and entry.get("integration") == "managed-native":
            removed = _uninstall_codex_statusline(entry, home, force=force, dry_run=dry_run)
        if removed:
            entries.pop(product, None)
            report[product] = "would-remove" if dry_run else "removed"
            if product == "claude":
                cache = terminal_ux.audit_summary_path(home)
                if cache.is_file() and not cache.is_symlink():
                    print(f"{'would remove' if dry_run else 'remove'} managed terminal UX audit cache: {cache}")
                    if not dry_run:
                        cache.unlink()
        else:
            report[product] = "retained-modified"
    return report


def statusline_uninstall(products: Sequence[str], home: Path, *, force: bool, dry_run: bool) -> dict[str, Any]:
    home = home.expanduser().resolve(strict=False)
    current = state.load_state(home)
    current_entries = current.get(TERMINAL_UX_KEY, {}).get("products", {})
    if not isinstance(current_entries, Mapping) or not any(product in current_entries for product in products):
        return {"products": {product: "not-managed" for product in products}, "dry_run": dry_run}
    new_state = json.loads(json.dumps(current))
    report = _uninstall_statusline_from_state(products, home, new_state, force=force, dry_run=dry_run)
    state.save_state(home, new_state, dry_run=dry_run)
    if not dry_run:
        _cleanup_runtimes(home, new_state)
    return {"products": report, "dry_run": dry_run}


def statusline_status(products: Sequence[str], home: Path) -> dict[str, Any]:
    home = home.expanduser().resolve(strict=False)
    current = state.load_state(home)
    entries = current.get(TERMINAL_UX_KEY, {}).get("products", {})
    entries = entries if isinstance(entries, Mapping) else {}
    report: dict[str, Any] = {}
    for product in products:
        entry = entries.get(product)
        if not isinstance(entry, Mapping):
            if product == "claude":
                target = home_path(home, ".claude/settings.json")
                try:
                    data = read_json(target, default={}) if target.is_file() and not target.is_symlink() else {}
                except GuardrailsError:
                    data = None
                report[product] = {"state": "unmanaged-collision" if isinstance(data, Mapping) and "statusLine" in data else "not-configured"}
            elif product == "codex":
                config = codex_home(home) / "config.toml"
                native_status_line, native_state = _codex_status_line(config)
                report[product] = {"state": "native-user-controlled", "config_path": str(config), "native_status_line": native_status_line, "native_status_line_state": native_state}
            else:
                report[product] = {"state": "native-user-controlled", "native_title_indicators": "user controlled", "programmable_usage_bar": "unsupported"}
            continue
        if product == "claude":
            report[product] = {
                "state": _statusline_config_status(entry, home),
                "audit_cache": terminal_ux.cache_freshness(terminal_ux.audit_summary_path(home)),
                "complexity_cache": "repository-keyed; checked by the renderer only when Claude supplies a workspace",
                **dict(entry),
            }
        elif product == "codex":
            configured, native_state = _codex_status_line(codex_home(home) / "config.toml")
            expected = list(terminal_ux.CODEX_NATIVE_FIELDS.get(str(entry.get("profile")), ()))
            marker_owned = _codex_marker_is_owned(codex_home(home) / "config.toml", entry)
            report[product] = {
                "state": "configured-native" if configured == expected and marker_owned else "modified-or-stale-native-config",
                "native_status_line": configured,
                "native_status_line_state": native_state,
                "matches_selected_profile": configured == expected and marker_owned if configured is not None else None,
                **dict(entry),
            }
        else:
            report[product] = {
                "state": "manual-native-step-required",
                "native_title_indicators": "user controlled",
                "programmable_usage_bar": "unsupported",
                **dict(entry),
            }
    return report


def _codex_status_line(path: Path) -> tuple[list[str] | None, str]:
    if path.is_symlink() or not path.is_file():
        return None, "not-configured"
    try:
        import tomllib

        value = tomllib.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, tomllib.TOMLDecodeError):
        return None, "invalid-config"
    status_line = value.get("tui", {}).get("status_line") if isinstance(value.get("tui"), Mapping) else None
    if isinstance(status_line, list) and all(isinstance(item, str) for item in status_line):
        return list(status_line), "configured"
    return None, "not-configured"


def _codex_marker_is_owned(path: Path, entry: Mapping[str, Any]) -> bool:
    """Check the marker and exact managed bytes before claiming native ownership."""
    if path.is_symlink() or not path.is_file():
        return False
    try:
        text = path.read_bytes().decode("utf-8")
        blocks = list(CODEX_STATUSLINE_BLOCK_RE.finditer(text))
        bounds = _codex_tui_bounds(text)
    except (OSError, UnicodeError, GuardrailsError):
        return False
    if len(blocks) != 1 or bounds is None:
        return False
    block = blocks[0]
    return bounds[0] <= block.start() < bounds[1] and sha256(block.group(0).encode("utf-8")) == entry.get("managed_sha256")


def _skill_root(home: Path, product: str) -> Path:
    return home_path(home, ".claude/skills" if product == "claude" else ".agents/skills")


def _agent_root(home: Path, product: str) -> Path:
    if product == "codex":
        return codex_home(home) / "agents"
    relative = {
        "claude": ".claude/agents",
        "cursor": ".cursor/agents",
        "vscode": ".copilot/agents",
        "visualstudio": ".github/agents",
        # GitHub marks JetBrains Copilot agent customisation Preview and does not
        # document a personal import path.  This is a reviewable manual bundle.
        "jetbrains": ".ai-guardrails/manual/jetbrains/agents",
    }[product]
    return home_path(home, relative)


def known_component_paths(home: Path) -> tuple[Path, ...]:
    """Return only product locations relevant to static component inspection.

    This deliberately shares the installer's product-path knowledge so the
    component auditor does not grow its own product registry.  Callers decide
    whether an existing file or a child of an existing directory is inspected.
    """
    selected = home.expanduser().resolve(strict=False)
    paths = {
        *(_skill_root(selected, product) for product in PRODUCTS),
        *(_agent_root(selected, product) for product in PRODUCTS),
        codex_home(selected) / "AGENTS.md",
        codex_home(selected) / "config.toml",
        home_path(selected, ".claude/settings.json"),
        home_path(selected, ".claude/rules"),
        home_path(selected, ".cursor/hooks.json"),
        home_path(selected, ".copilot/instructions"),
        home_path(selected, ".copilot/hooks"),
    }
    return tuple(sorted(paths, key=lambda item: str(item)))


def _jetbrains_copilot_target(home: Path) -> Path | None:
    """Return only the documented platform destination, always below --home."""
    if sys.platform == "darwin":
        return home_path(home, ".config/github-copilot/intellij/global-copilot-instructions.md")
    if sys.platform == "win32":
        return home_path(home, "AppData/Local/github-copilot/intellij/global-copilot-instructions.md")
    return None


def _install_skills(
    product: str,
    home: Path,
    current_state: Mapping[str, Any],
    skill_packs: Sequence[str],
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
    for identifier in skill_packs:
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
            generated_artifacts[CODEX_AGENTS_ARTIFACT].decode("utf-8"),
            target,
            home,
            current_state,
            force=force,
            dry_run=dry_run,
        ),
        state.install_file_data(
            generated_artifacts[CODEX_RULES_ARTIFACT],
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
        if source.parent == CLAUDE_RULES_ARTIFACT
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


def _install_vscode(
    home: Path,
    runtime: Path | None,
    current_state: Mapping[str, Any],
    generated_artifacts: Mapping[Path, bytes],
    *,
    force: bool,
    dry_run: bool,
) -> list[dict[str, Any]]:
    records = [
        state.install_file_data(
            generated_artifacts[VSCODE_INSTRUCTIONS_ARTIFACT],
            home_path(home, ".copilot/instructions/workstation-guardrails.instructions.md"),
            home,
            current_state,
            force=force,
            dry_run=dry_run,
        )
    ]
    if runtime is not None:
        records.append(
            _install_json_hook(
                "vscode",
                runtime,
                home_path(home, ".copilot/hooks/workstation-guardrails.json"),
                home,
                current_state,
                force=force,
                dry_run=dry_run,
            )
        )
    return records


def _install_visualstudio(
    home: Path,
    current_state: Mapping[str, Any],
    generated_artifacts: Mapping[Path, bytes],
    *,
    force: bool,
    dry_run: bool,
) -> list[dict[str, Any]]:
    return [
        _install_managed_block(
            generated_artifacts[VISUALSTUDIO_INSTRUCTIONS_ARTIFACT].decode("utf-8"),
            home_path(home, "copilot-instructions.md"),
            home,
            current_state,
            force=force,
            dry_run=dry_run,
        )
    ]


def _install_jetbrains(
    home: Path,
    current_state: Mapping[str, Any],
    generated_artifacts: Mapping[Path, bytes],
    *,
    install_copilot_instructions: bool,
    force: bool,
    dry_run: bool,
) -> list[dict[str, Any]]:
    target = _jetbrains_copilot_target(home)
    if target is None or not install_copilot_instructions:
        return []
    return [
        _install_managed_block(
            generated_artifacts[JETBRAINS_COPILOT_ARTIFACT].decode("utf-8"),
            target,
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
    skill_packs: Sequence[str],
    routing_profile: str,
    model_overrides: Mapping[str, Mapping[str, str]] | None,
    generated_artifacts: Mapping[Path, bytes],
    *,
    force: bool,
    vscode_hook_mode: str = "native-vscode",
) -> None:
    """Reject collisions and modified managed content before the first write."""
    for product in products:
        for target in _managed_paths_for_product(
            home,
            product,
            skill_packs,
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
            "vscode": (
                home_path(home, ".copilot/instructions/workstation-guardrails.instructions.md"),
                home_path(home, ".copilot/hooks/workstation-guardrails.json"),
            ),
            "visualstudio": (home_path(home, "copilot-instructions.md"),),
            "jetbrains": tuple(path for path in (_jetbrains_copilot_target(home),) if path is not None),
        }[product]
        if product == "vscode" and vscode_hook_mode == "shared-claude":
            configuration_files = tuple(
                path
                for path in configuration_files
                if path.name != "workstation-guardrails.json"
            )
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
            "vscode": home_path(home, ".copilot/hooks/workstation-guardrails.json"),
        }.get(product)
        if product == "vscode" and vscode_hook_mode == "shared-claude":
            hook_target = None
        if hook_target is None:
            continue
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
        for identifier in skill_packs:
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
            for source in sorted(generated_artifacts, key=lambda path: path.as_posix()):
                if source.parent != CLAUDE_RULES_ARTIFACT or not source.name.startswith("workstation-guardrails-"):
                    continue
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
    terminal_products = installed_state.get(TERMINAL_UX_KEY, {}).get("products", {})
    if isinstance(terminal_products, Mapping):
        referenced.update(
            str(entry.get("runtime_digest"))
            for entry in terminal_products.values()
            if isinstance(entry, Mapping) and isinstance(entry.get("runtime_digest"), str)
        )
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
            state.remove_owned_tree(path)


def _selected_installation_is_current(
    current: Mapping[str, Any],
    products: Sequence[str],
    product_settings: Mapping[str, Mapping[str, Any]],
    home: Path,
) -> bool:
    overlay_digest = policy.local_policy_digest(home)
    source = state.source_digest(overlay_digest)
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
        existing_skill_packs = existing.get("installed_skill_packs", existing.get("installed_packs", []))
        if tuple(existing_skill_packs) != tuple(expected["installed_skill_packs"]):
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
    skill_catalogue: str | None = None,
    routing_profile: str | None = None,
    statusline_profile: str | None = None,
    safety_profile: str | None = None,
    trust_mode: str | None = None,
    model_overrides: Mapping[str, Mapping[str, str]] | None = None,
    explicit_product: bool = True,
    prefer_native_vscode: bool = False,
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
    if statusline_profile is not None and statusline_profile not in terminal_ux.STATUSLINE_PROFILES:
        raise GuardrailsError(f"unknown status-line profile: {statusline_profile}")
    if skill_catalogue not in {None, "contextual", "all"}:
        raise GuardrailsError(f"unknown skill catalogue: {skill_catalogue}")
    if model_overrides and sorted(set(model_overrides) - set(selected_products)):
        raise GuardrailsError("model override references a product outside the selected installation")
    # Validate the overlay before collision detection or any user-home mutation.
    generated_artifacts = build.build_artifacts(selected_products, home=home)
    current = state.load_state(home)
    packs_were_selected = bool(pack_ids) or all_packs
    available_packs = packs.load_packs()
    requested_packs = _selected_packs(pack_ids, all_packs)
    default_policy_packs = packs.default_pack_ids(available_packs)
    contextual_skill_packs = packs.default_skill_pack_ids(available_packs)
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
            selected_packs = default_policy_packs
        selected_packs = packs.selected_pack_closure(selected_packs, available_packs)
        existing_runtime_packs = tuple(str(value) for value in existing.get("installed_packs", []))
        if skill_catalogue == "all":
            skill_packs = selected_packs
        elif skill_catalogue == "contextual":
            skill_packs = tuple(identifier for identifier in selected_packs if identifier in contextual_skill_packs)
        elif existing and existing_runtime_packs == selected_packs:
            skill_packs = tuple(
                str(value)
                for value in existing.get("installed_skill_packs", existing.get("installed_packs", []))
            )
        elif packs_were_selected:
            skill_packs = selected_packs
        else:
            skill_packs = tuple(identifier for identifier in selected_packs if identifier in contextual_skill_packs)
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
            "installed_skill_packs": skill_packs,
            "safety_profile": selected_safety,
            "trust_mode": selected_trust,
            "model_overrides": selected_overrides,
            "hook_mode": (
                "shared-claude"
                if product == "vscode" and not prefer_native_vscode and (
                    "claude" in current.get("products", {}) or "claude" in selected_products
                )
                else "native-vscode" if product == "vscode" else "not-applicable"
            ),
        }
        # A local mode change may refer to a pack rule. Validate the policy for
        # the precise runtime pack set before any installation path is touched.
        policy.validate_local_overlay(home, selected_packs)
        product_overrides = {product: selected_overrides} if selected_overrides else None
        _preflight_collisions(
            (product,),
            home,
            current,
            skill_packs,
            profile,
            product_overrides,
            generated_artifacts,
            force=force,
            vscode_hook_mode=str(product_settings[product]["hook_mode"]),
        )
    already_current = _selected_installation_is_current(
        current,
        selected_products,
        product_settings,
        home,
    )
    new_state = json.loads(json.dumps(current))
    statusline_profiles = _selected_statusline_profiles(selected_products, current, statusline_profile)
    # Surface every optional terminal-UX collision before ordinary installation
    # creates any managed product files.  The later merge still uses new_state so
    # the renderer reflects the selected product safety profile.
    for selected_profile, terminal_products in statusline_profiles:
        _preflight_statusline(terminal_products, home, selected_profile, current, force=force)
    overlay_digest = policy.local_policy_digest(home)
    source_digest = state.source_digest(overlay_digest)
    indicators = _managed_enterprise_indicators()
    if indicators:
        print("managed configuration detected: " + ", ".join(indicators))
        print("higher-precedence enterprise policy may limit or ignore user-level hooks; no managed file was changed")
    for product in selected_products:
        settings = product_settings[product]
        profile = settings["routing_profile"]
        selected_packs = settings["installed_packs"]
        skill_packs = settings["installed_skill_packs"]
        selected_safety = settings["safety_profile"]
        selected_trust = settings["trust_mode"]
        selected_overrides = settings["model_overrides"]
        product_overrides = {product: selected_overrides} if selected_overrides else None
        product_state = new_state
        needs_native_hook = product in {"codex", "claude", "cursor"} or (
            product == "vscode" and settings["hook_mode"] == "native-vscode"
        )
        digest, payloads = _runtime_payloads(
            home,
            product,
            selected_packs,
            skill_packs,
            profile,
            selected_safety,
            selected_trust,
            product_overrides,
            generated_artifacts,
        )
        runtime = _install_runtime(home, digest, payloads, dry_run=dry_run) if needs_native_hook else None
        product_records: list[dict[str, Any]] = (
            [_runtime_record(runtime, home, digest)] if runtime is not None else []
        )
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
        elif product == "cursor":
            product_records.extend(_install_cursor(home, runtime, product_state, force=force, dry_run=dry_run))
        elif product == "vscode":
            product_records.extend(
                _install_vscode(
                    home,
                    runtime,
                    product_state,
                    generated_artifacts,
                    force=force,
                    dry_run=dry_run,
                )
            )
        elif product == "visualstudio":
            product_records.extend(
                _install_visualstudio(
                    home,
                    product_state,
                    generated_artifacts,
                    force=force,
                    dry_run=dry_run,
                )
            )
        else:
            copilot_target = _jetbrains_copilot_target(home)
            product_records.extend(
                _install_jetbrains(
                    home,
                    product_state,
                    generated_artifacts,
                    install_copilot_instructions=(
                        copilot_target is not None
                        and (explicit_product or copilot_target.parent.exists())
                    ),
                    force=force,
                    dry_run=dry_run,
                )
            )
        product_records.extend(
            _install_skills(product, home, product_state, skill_packs, force=force, dry_run=dry_run)
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
            "runtime_digest": digest if runtime is not None else None,
            "routing_profile": profile,
            "safety_profile": selected_safety,
            "trust_mode": selected_trust,
            "installed_packs": list(selected_packs),
            "installed_skill_packs": list(skill_packs),
            "model_overrides": selected_overrides,
            "managed": product_records,
            "model_availability": "unverified",
            "hook_mode": settings["hook_mode"],
            "capabilities": dict(PRODUCT_CAPABILITIES[product]),
            "platform": sys.platform,
        }
        if product == "codex":
            new_state["products"][product]["product_home"] = relative_home(codex_home(home), home)
    # VS Code loads Claude-compatible user hooks.  Once the managed Claude hook
    # exists, remove an older project-owned VS Code registration only after the
    # Claude registration has been written, so there is never a no-hook window.
    if "claude" in selected_products and "vscode" in new_state.get("products", {}):
        vscode_data = new_state["products"]["vscode"]
        if isinstance(vscode_data, dict):
            retained_records: list[dict[str, Any]] = []
            for record in state.product_records(new_state, "vscode"):
                if record.get("kind") == "json-hook":
                    if not _remove_json_hook(record, "vscode", home, force=force, dry_run=dry_run):
                        retained_records.append(record)
                    continue
                if record.get("kind") == "runtime-directory":
                    continue
                retained_records.append(record)
            if any(record.get("kind") == "json-hook" for record in retained_records):
                vscode_data["hook_mode"] = "native-vscode; possible-duplicate-unmanaged"
            else:
                vscode_data["managed"] = retained_records
                vscode_data["hook_mode"] = "shared-claude"
                vscode_data["runtime_digest"] = None
                vscode_data["source_digest"] = source_digest
    new_state["format_version"] = state.FORMAT_VERSION
    new_state["source_digest"] = source_digest
    new_state["overlay_digest"] = overlay_digest
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
    runtime_records = [
        record
        for product_data in new_state["products"].values()
        if isinstance(product_data, Mapping)
        for record in product_data.get("managed", [])
        if isinstance(record, Mapping) and record.get("kind") == "runtime-directory"
    ]
    new_state["runtime_digest"] = runtime_records[-1].get("runtime_digest") if runtime_records else None
    new_state["runtime_path"] = runtime_records[-1].get("path") if runtime_records else None
    manual_steps = [
        step
        for step in new_state.get("manual_steps", [])
        if step.get("product") not in {"cursor", "vscode", "visualstudio", "jetbrains"}
    ]
    if "cursor" in new_state["products"]:
        manual_steps.append(
            {
                "product": "cursor",
                "id": "cursor-user-rules",
                "status": "outstanding",
                "instruction": "Paste print-cursor-rules output into Cursor Settings / Customize / Rules / User Rules.",
            }
        )
    if "vscode" in new_state["products"]:
        manual_steps.append(
            {
                "product": "vscode",
                "id": "vscode-hook-activation",
                "status": "unverified",
                "instruction": "VS Code Copilot hooks are Preview and may be disabled by an organisation; hook activation is not proven by the installed file.",
            }
        )
    if "visualstudio" in new_state["products"]:
        manual_steps.append(
            {
                "product": "visualstudio",
                "id": "visualstudio-version-compatibility",
                "status": "unverified",
                "instruction": "Confirm Visual Studio 18.5+ for skills and 18.4+ for custom agents when routing is selected.",
            }
        )
    if "jetbrains" in new_state["products"]:
        manual_steps.extend(
            [
                {
                    "product": "jetbrains",
                    "id": "jetbrains-chat-instructions",
                    "status": "outstanding",
                    "instruction": "Paste ai-guardrails jetbrains print-chat-instructions output in Settings > Tools > AI Assistant > Prompt Library > General > Chat Instructions.",
                },
                {
                    "product": "jetbrains",
                    "id": "jetbrains-skills-directory",
                    "status": "outstanding",
                    "instruction": "Register ~/.agents/skills in Settings > Tools > AI Assistant > Skills > Manage Skill Directories.",
                },
            ]
        )
        if _jetbrains_copilot_target(home) is None:
            manual_steps.append(
                {
                    "product": "jetbrains",
                    "id": "jetbrains-copilot-instructions",
                    "status": "manual",
                    "instruction": "GitHub Copilot for JetBrains has no documented Linux global instruction path; use its Customizations UI.",
                }
            )
        if product_settings.get("jetbrains", {}).get("routing_profile") != "none":
            manual_steps.append(
                {
                    "product": "jetbrains",
                    "id": "jetbrains-copilot-routing",
                    "status": "manual-activation-required",
                    "instruction": "JetBrains Copilot custom agents are Preview; import the generated manual bundle through the documented Customizations editor.",
                }
            )
    new_state["manual_steps"] = manual_steps
    statusline_report: dict[str, Any] | None = None
    for selected_profile, terminal_products in statusline_profiles:
        refreshed = _install_statusline_into_state(
            terminal_products,
            home,
            selected_profile,
            new_state,
            force=force,
            dry_run=dry_run,
        )
        if statusline_report is None:
            statusline_report = {"products": {}, "profiles": []}
        statusline_report["products"].update(refreshed["products"])
        statusline_report["profiles"].append(selected_profile)
        already_current = False
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
            "statusline": statusline_report,
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
        "installed pack skills: "
        + "; ".join(
            f"{product}={','.join(product_settings[product]['installed_skill_packs']) or 'none'}"
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
        print("manual step required: paste `ai-guardrails print-cursor-rules` output into Cursor Settings / Customize / Rules / User Rules")
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
        "statusline": statusline_report,
    }


def update(
    products: Sequence[str],
    home: Path,
    *,
    force: bool,
    dry_run: bool,
    statusline_profile: str | None = None,
) -> dict[str, Any]:
    current = state.load_state(home)
    installed = [product for product in products if product in current.get("products", {})]
    if not installed:
        raise GuardrailsError("no selected product is installed; use install first")
    return install(tuple(installed), home, force=force, dry_run=dry_run, statusline_profile=statusline_profile)


def print_consumer_install_summary(
    report: Mapping[str, Any],
    detected: Mapping[str, Sequence[str]],
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
    print("Repository capability detection: not run by install/update")
    print("Repository capability command: ai-guardrails packs detect --repo <path>")
    stable_pack_count = len({pack for product in products for pack in settings[product]["installed_packs"]})
    skill_pack_count = len({pack for product in products for pack in settings[product]["installed_skill_packs"]})
    print(f"Capability policy: {stable_pack_count} selected pack(s)")
    print(f"Global skill catalogue: {skill_pack_count} pack skill(s), plus six core skills")

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
            "Manual step after install: run `ai-guardrails print-cursor-rules`, then paste the "
            "complete output into Cursor Settings / Customize / Rules / User Rules"
        )
    if "vscode" in products:
        print("VS Code: PreToolUse hooks are Preview, may be disabled by an organisation, and do not cover inline suggestions")
    if "visualstudio" in products:
        print("Visual Studio: hooks and subagents are unsupported; native tool approvals remain unchanged")
    if "jetbrains" in products:
        print("JetBrains manual step: run `ai-guardrails jetbrains print-chat-instructions`, then paste it in Settings > Tools > AI Assistant > Prompt Library > General > Chat Instructions")
        print("JetBrains manual step: register ~/.agents/skills in Settings > Tools > AI Assistant > Skills > Manage Skill Directories")
    if not {"cursor", "jetbrains"} & set(products):
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
    legacy_state = state.LEGACY_FORMAT_KEY in installed_state
    detected_local = detect_products(home)
    overlay_digest = policy.local_policy_digest(home)
    source = state.source_digest(overlay_digest)
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
            elif not legacy_state and (
                product_data.get("source_digest") != source
                or product_data.get("overlay_digest", installed_state.get("overlay_digest", "")) != overlay_digest
            ):
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
            product_result["installed_skill_packs"] = product_data.get(
                "installed_skill_packs", product_data.get("installed_packs", [])
            )
            if legacy_state:
                product_result["state_format"] = "legacy; will migrate on the next successful install or update"
            product_result["shell_enforcement"] = "configured" if any(
                record.get("kind") == "json-hook" for record in state.product_records(installed_state, product)
            ) else "missing"
            if product == "vscode" and product_data.get("hook_mode") == "shared-claude":
                product_result["shell_enforcement"] = "shared-claude"
            if product in {"visualstudio", "jetbrains"}:
                product_result["shell_enforcement"] = "unsupported"
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
        if product == "vscode":
            product_result.update(
                {
                    "hook_maturity": "Preview",
                    "hook_activation": "unverified",
                    "organisation_may_disable_hooks": True,
                    "inline_suggestions": "not covered",
                }
            )
        if product == "visualstudio":
            product_result.update(
                {
                    "skills_compatibility": visualstudio_capabilities(None)["skills"],
                    "agents_compatibility": visualstudio_capabilities(None)["agents"],
                    "subagents": "unsupported",
                    "native_approvals": "unchanged",
                }
            )
        if product == "jetbrains":
            product_result.update(
                {
                    "chat_instructions": "manual outstanding" if isinstance(product_data, Mapping) else "not-applicable",
                    "project_rules": "explicit repository export",
                    "skills_registration": "manual directory registration required",
                    "copilot_instructions": "platform/evidence dependent",
                    "native_approvals": "unchanged",
                }
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
        if product == "vscode":
            hook_status = product_result.get("shell_enforcement", "missing")
            suffix = " (shared Claude-compatible registration)" if hook_status == "shared-claude" else ""
            print("  hook configuration: installed" + suffix if hook_status != "missing" else "  hook configuration: missing")
            print("  hook maturity: Preview; runtime activation: unverified; organisation may disable hooks: yes")
            print("  inline suggestions: not covered; main model: unchanged")
        if product == "visualstudio":
            print("  skills: installed; version compatibility unverified")
            print("  custom agents: user-selectable; version-dependent")
            print("  subagents: unsupported; deterministic hook: unsupported; native approvals: unchanged")
        if product == "jetbrains":
            print("  native AI Chat guidance: manual Chat Instructions step; project rules: explicit repository export")
            print("  skills: installed; manual directory registration required; Copilot instructions: platform/evidence dependent")
            print("  deterministic hook: unsupported; native approvals/operation modes: unchanged")
        if product_result.get("installed_packs") is not None:
            installed = product_result.get("installed_packs") or []
            print(f"  packs: {', '.join(installed) if installed else 'none'}")
            skill_packs = product_result.get("installed_skill_packs") or []
            print(f"  globally exposed pack skills: {', '.join(skill_packs) if skill_packs else 'none'}")
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
        output_root = build.repository_output_root()
        if output_root is None:
            build.validate(PRODUCTS, require_current=False, home=home)
            add("generated-output", "pass", "bundled artifacts generated in memory")
        else:
            build.assert_generated_current(PRODUCTS, output_root=output_root)
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
            registry_data = read_json(registry, default={})
            components = registry_data.get("components", []) if isinstance(registry_data, Mapping) else []
            mcp_components = [
                component
                for component in components
                if isinstance(component, Mapping) and component.get("kind") == "mcp-server"
            ]
            observed_tools = {
                tool
                for component in mcp_components
                for tool in component.get("observed_tools", [])
                if isinstance(tool, str)
            }
            add(
                "mcp-tool-inventory",
                "pass",
                f"{len(mcp_components)} declared MCP server(s); {len(observed_tools)} observed tool name(s) in the local registry",
            )
        except GuardrailsError as exc:
            add("supply-chain-registry", "fail", str(exc))
            add("mcp-tool-inventory", "skip", "trusted component registry is invalid")
    else:
        add("supply-chain-registry", "skip", "no workstation-local trusted component registry")
        add("mcp-tool-inventory", "skip", "no workstation-local trusted component registry")
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
    if "vscode" in installed_state.get("products", {}):
        add("vscode-hook", "warn", "Preview hook configuration exists only when native mode is selected; activation and organisation policy are unverified")
    if "visualstudio" in installed_state.get("products", {}):
        add("visualstudio-hooks", "skip", "Visual Studio Copilot does not support hooks; native tool approvals remain unchanged")
    if "jetbrains" in installed_state.get("products", {}):
        add("jetbrains-hooks", "skip", "JetBrains AI Assistant and Copilot for JetBrains do not have a managed deterministic hook")
        add("jetbrains-manual-chat", "warn", "Chat Instructions and Skills directory registration require manual confirmation")
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
    # A managed VS Code installation may intentionally rely on the compatible
    # Claude hook. Install its native hook before removing Claude so the shared
    # runtime is not lost. This remains a normal managed install path.
    if (
        "claude" in products
        and "vscode" not in products
        and isinstance(installed_state.get("products", {}).get("vscode"), Mapping)
        and installed_state["products"]["vscode"].get("hook_mode") == "shared-claude"
    ):
        vscode_data = installed_state["products"]["vscode"]
        print("reconciling VS Code to a native Preview hook before removing Claude")
        install(
            ("vscode",),
            home,
            force=force,
            dry_run=dry_run,
            pack_ids=tuple(vscode_data.get("installed_packs", [])),
            routing_profile=str(vscode_data.get("routing_profile", "none")),
            safety_profile=str(vscode_data.get("safety_profile", "infrastructure-observe")),
            trust_mode=str(vscode_data.get("trust_mode", "trusted-workspace")),
            model_overrides={"vscode": dict(vscode_data.get("model_overrides", {}))},
            explicit_product=True,
            prefer_native_vscode=True,
        )
        if not dry_run:
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
    terminal_ux_report = _uninstall_statusline_from_state(
        tuple(product for product in selected if product in terminal_ux.STATUSLINE_PRODUCTS),
        home,
        new_state,
        force=force,
        dry_run=dry_run,
    )
    retained_any = retained_any or any(outcome == "retained-modified" for outcome in terminal_ux_report.values())
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
            home_path(home, ".copilot/instructions"),
            home_path(home, ".copilot/hooks"),
            home_path(home, ".copilot/agents"),
            home_path(home, ".github/agents"),
            home_path(home, ".ai-guardrails/manual/jetbrains/agents"),
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


def print_cursor_rules(*, clipboard: bool, home: Path | None = None) -> None:
    content = build.build_artifacts(("cursor",), home=home)[CURSOR_RULES_ARTIFACT].decode("utf-8")
    print(content, end="")
    if clipboard:
        _copy_to_clipboard(content, "Cursor User Rules")


def _copy_to_clipboard(content: str, label: str) -> None:
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
            print(f"\n{label} copied with {executable}; clipboard copy is not installation")
            return
    raise GuardrailsError("no supported clipboard command is available")


def print_jetbrains_chat_instructions(*, clipboard: bool, home: Path | None = None) -> None:
    content = build.build_artifacts(("jetbrains",), home=home)[JETBRAINS_CHAT_ARTIFACT].decode("utf-8")
    print(content, end="")
    if clipboard:
        _copy_to_clipboard(content, "JetBrains AI Assistant Chat Instructions")


def _validate_repository_export_target(repo: Path, target: Path) -> None:
    if not repo.is_dir() or repo.is_symlink():
        raise GuardrailsError(f"repository must be a non-symbolic-link directory: {repo}")
    if not path_within(target, repo):
        raise GuardrailsError(f"refusing project-rule path outside the selected repository: {target}")
    current = repo.resolve(strict=False)
    for part in target.resolve(strict=False).relative_to(current).parts[:-1]:
        current /= part
        if current.is_symlink():
            raise GuardrailsError(f"project-rule parent is a symbolic link: {current}")
        if current.exists() and not current.is_dir():
            raise GuardrailsError(f"project-rule parent is not a directory: {current}")


def export_jetbrains_project_rules(repo: Path, *, dry_run: bool, force: bool, home: Path | None = None) -> Path:
    """Explicitly export a native JetBrains project rule; workstation install never calls this."""
    selected_repo = repo.expanduser().resolve(strict=False)
    if (selected_repo / ".noai").exists():
        raise GuardrailsError(".noai disables JetBrains AI Assistant for this repository; project rule was not exported")
    target = selected_repo / ".aiassistant" / "rules" / "workstation-guardrails.md"
    _validate_repository_export_target(selected_repo, target)
    content = build.build_artifacts(("jetbrains",), home=home)[JETBRAINS_PROJECT_RULE_ARTIFACT]
    if target.exists():
        if target.is_symlink() or not target.is_file():
            raise GuardrailsError(f"project-rule target is not a regular file: {target}")
        if target.read_bytes() == content:
            print(f"unchanged {target}")
        elif not force:
            raise GuardrailsError(f"unmanaged JetBrains project-rule collision; refusing to overwrite without --force: {target}")
        else:
            backup = target.with_name(target.name + ".ai-guardrails.bak")
            if backup.exists() and backup.is_symlink():
                raise GuardrailsError(f"project-rule backup path is a symbolic link: {backup}")
            if dry_run:
                print(f"would back up {target} to {backup}")
            else:
                atomic_write(backup, target.read_bytes())
    if not target.exists() or target.read_bytes() != content:
        print(f"{'would export' if dry_run else 'export'} JetBrains project rule to {target}")
        if not dry_run:
            atomic_write(target, content)
    print("Manual verification: Settings > Tools > AI Assistant > Rules; open the generated rule and confirm it is active as an Always rule.")
    if dry_run:
        print("dry run complete; no files were changed")
    return target
