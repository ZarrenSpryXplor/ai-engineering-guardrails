"""Deterministic generation and repository validation."""

from __future__ import annotations

import json
import shlex
import shutil
import subprocess
import tomllib
from pathlib import Path
from typing import Any, Mapping, Sequence

from . import packs, policy, routing
from .resources import RESOURCE_ROOT, repository_output_root
from .util import PRODUCT_CAPABILITIES, PRODUCT_LABELS, PRODUCTS, GuardrailsError, atomic_write, json_bytes, one_newline, path_within


HOOK_PLACEHOLDER = "__WORKSTATION_GUARDRAILS_COMMAND__"
GENERATED_ROOTS = (
    Path("dist/codex"),
    Path("dist/claude"),
    Path("dist/cursor"),
    Path("dist/vscode"),
    Path("dist/visualstudio"),
    Path("dist/jetbrains"),
    Path("dist/skills"),
    Path("dist/enterprise"),
)


def markdown_header(source: str) -> str:
    return f"<!-- GENERATED — DO NOT EDIT\nCanonical source: {source}\n-->\n"


def adapter_json(source: str, payload: Mapping[str, Any]) -> bytes:
    value: dict[str, Any] = {
        "_generated": f"GENERATED — DO NOT EDIT. Canonical source: {source}."
    }
    value.update(payload)
    return json_bytes(value)


def _check_always_loaded_budget(product: str, size: int, manifest: Mapping[str, Any]) -> None:
    budget = manifest["always_loaded_budget_bytes"]
    if size > budget:
        raise GuardrailsError(
            f"generated {product} policy exceeds the configured {budget}-byte always-loaded budget"
        )


def render_policy(
    product: str,
    manifest: Mapping[str, Any],
    manifest_path: Path,
    local_fragments: Sequence[Mapping[str, Any]] = (),
) -> str:
    entries = [
        entry
        for entry in manifest["fragments"]
        if product in entry["products"] and entry["load"] == "always"
    ]
    sections = [
        (manifest_path.parent / entry["path"]).read_text(encoding="utf-8").strip()
        for entry in entries
    ]
    sections.extend(
        str(fragment["content"]).strip()
        for fragment in local_fragments
        if product in fragment["products"]
    )
    if not sections:
        raise GuardrailsError(f"generated {product} policy would be empty")
    output = one_newline(
        markdown_header("policy/manifest.json and policy/fragments/")
        + "<!-- Canonical policy IDs: "
        + ", ".join(str(entry["id"]) for entry in entries)
        + " -->\n"
        + "\n# Workstation AI Guardrails\n\n"
        + "\n\n".join(sections)
    )
    limit = manifest["output_limits_bytes"][product]
    if len(output.encode("utf-8")) > limit:
        raise GuardrailsError(f"generated {product} policy exceeds configured {limit}-byte limit")
    _check_always_loaded_budget(product, len(output.encode("utf-8")), manifest)
    return output


def render_claude_rule(entry: Mapping[str, Any], manifest_path: Path) -> str:
    source = manifest_path.parent / entry["path"]
    return one_newline(
        markdown_header(f"policy/{entry['path']}")
        + f"<!-- Canonical policy ID: {entry['id']} -->\n\n"
        + source.read_text(encoding="utf-8").strip()
    )


def render_local_claude_rule(fragment: Mapping[str, Any]) -> str:
    return one_newline(
        markdown_header(f"local policy overlay fragment {fragment['id']}") + "\n" + str(fragment["content"]).strip()
    )


def render_skill(skill_file: Path, canonical_prefix: str = "skills") -> str:
    fields, body = policy.parse_skill(skill_file)
    return one_newline(
        "---\n"
        f"name: {fields['name']}\n"
        f"description: {fields['description']}\n"
        "---\n\n"
        "<!-- GENERATED — DO NOT EDIT\n"
        f"Canonical source: {canonical_prefix}/{fields['name']}/SKILL.md\n"
        "-->\n\n"
        f"{body}"
    )


def _matches_codex_prefix(command: str, pattern: Sequence[Any]) -> bool:
    try:
        tokens = shlex.split(command)
    except ValueError:
        return False
    if len(tokens) < len(pattern):
        return False
    for token, expected in zip(tokens, pattern):
        if isinstance(expected, str) and token != expected:
            return False
        if isinstance(expected, list) and token not in expected:
            return False
        if not isinstance(expected, (str, list)):
            raise GuardrailsError("invalid codex_prefixes pattern in command policy")
    return True


def _starlark_list(values: Sequence[str], indent: str) -> str:
    return "[\n" + "".join(f"{indent}{json.dumps(value, ensure_ascii=False)},\n" for value in values) + indent[:-4] + "]"


def codex_rules(command_policy: Mapping[str, Any]) -> str:
    sections = [
        "# GENERATED — DO NOT EDIT",
        "# Canonical sources: enforcement/command-policy.json and pack command-policy fragments.",
        "# These experimental prefix rules are defence in depth. The shared hook handles",
        "# wrappers and flag orderings that prefix matching cannot safely express.",
    ]
    generated = 0
    for rule in command_policy["rules"]:
        if rule.get("rollout_mode", "deny") != "deny":
            continue
        prefixes = rule.get("codex_prefixes", [])
        if not isinstance(prefixes, list):
            raise GuardrailsError(f"rule {rule['id']} has invalid codex_prefixes")
        for pattern in prefixes:
            if not isinstance(pattern, list) or not pattern:
                raise GuardrailsError(f"rule {rule['id']} has an empty Codex prefix")
            matches = [example for example in rule["must_match"] if _matches_codex_prefix(example, pattern)]
            non_matches = [example for example in rule["must_not_match"] if not _matches_codex_prefix(example, pattern)]
            if not matches or not non_matches:
                raise GuardrailsError(f"rule {rule['id']} lacks Codex prefix match or non-match examples")
            sections.extend(
                [
                    "",
                    f"# {rule['id']}: {rule['description']}",
                    "prefix_rule(",
                    f"    pattern = {json.dumps(pattern, ensure_ascii=False)},",
                    '    decision = "forbidden",',
                    f"    justification = {json.dumps(rule['reason'], ensure_ascii=False)},",
                    f"    match = {_starlark_list(matches, '        ')},",
                    f"    not_match = {_starlark_list(non_matches, '        ')},",
                    ")",
                ]
            )
            generated += 1
    if generated == 0:
        raise GuardrailsError("Codex defence-in-depth rules would be empty")
    return one_newline("\n".join(sections))


def _hook_payload(product: str) -> dict[str, Any]:
    if product == "cursor":
        return {
            "version": 1,
            "hooks": {"preToolUse": [{"command": HOOK_PLACEHOLDER, "matcher": ".*"}]},
        }
    event = "PreToolUse"
    hook = {
        "type": "command",
        "command": HOOK_PLACEHOLDER,
        "timeout": 10,
        "statusMessage": "Checking tool request against workstation guardrails",
    }
    return {"hooks": {event: [{"matcher": ".*", "hooks": [hook]}]}}


def _vscode_instructions(manifest: Mapping[str, Any], manifest_path: Path, local_fragments: Sequence[Mapping[str, Any]]) -> bytes:
    body = render_policy("vscode", manifest, manifest_path, local_fragments)
    # VS Code reads the YAML frontmatter before the generated marker.
    return one_newline(
        "---\n"
        "name: Workstation AI Guardrails\n"
        "description: Workstation-wide engineering and safety guidance\n"
        'applyTo: "**"\n'
        "---\n\n"
        + body
        + "\nDeterministic command denials, when hooks are enabled, are separate from these behavioural instructions."
    ).encode("utf-8")


def _enterprise_artifacts(selected: set[str]) -> dict[Path, bytes]:
    artifacts: dict[Path, bytes] = {}
    if "codex" in selected:
        artifacts[Path("dist/enterprise/codex/requirements.toml")] = one_newline(
            "# GENERATED — DO NOT EDIT\n"
            "# Canonical source: enterprise/codex/README.md and official Codex managed-configuration schema.\n"
            "# Example for Codex 0.138.0 or later; test every managed client version before deployment.\n"
            'allowed_approval_policies = ["untrusted", "on-request"]\n'
            'default_permissions = ":workspace"\n'
            "allow_managed_hooks_only = true\n\n"
            "[allowed_permission_profiles]\n"
            '":read-only" = true\n'
            '":workspace" = true\n\n'
            "[features]\n"
            "hooks = true\n\n"
            "[hooks]\n"
            'managed_dir = "/enterprise/hooks"\n'
            "windows_managed_dir = 'C:\\enterprise\\hooks'\n\n"
            "[[hooks.PreToolUse]]\n"
            'matcher = ".*"\n'
            "[[hooks.PreToolUse.hooks]]\n"
            'type = "command"\n'
            'command = "/enterprise/python/bin/python3 /enterprise/hooks/hook_runtime.py --product codex"\n'
            "command_windows = 'C:\\Python311\\python.exe C:\\enterprise\\hooks\\hook_runtime.py --product codex'\n"
            "timeout = 10\n"
            'statusMessage = "Checking managed workstation guardrails"\n'
        ).encode("utf-8")
        artifacts[Path("dist/enterprise/codex/README.md")] = one_newline(
            markdown_header("enterprise/codex/ and official Codex managed-configuration documentation")
            + "\n# Codex enterprise template\n\n"
            "This Codex 0.138+ example uses managed permission profiles. Endpoint management must distribute the immutable runtime to the absolute managed directory; `requirements.toml` does not distribute scripts. Legacy fleets that still configure `sandbox_mode` require the separately documented `allowed_sandbox_modes` form. Test keys and precedence across the managed client fleet."
        ).encode("utf-8")
    if "claude" in selected:
        artifacts[Path("dist/enterprise/claude/managed-settings.json")] = adapter_json(
            "enterprise/claude/README.md and official Claude managed-settings documentation",
            {
                "hooks": {
                    "PreToolUse": [
                        {
                            "matcher": ".*",
                            "hooks": [
                                {
                                    "type": "command",
                                    "command": "/enterprise/python /enterprise/ai-guardrails/hook_runtime.py --product claude",
                                    "timeout": 10,
                                }
                            ],
                        }
                    ]
                }
            },
        )
        artifacts[Path("dist/enterprise/claude/README.md")] = one_newline(
            markdown_header("enterprise/claude/ and official Claude settings documentation")
            + "\n# Claude Code enterprise template\n\n"
            "Deploy through the documented managed-settings mechanism and an endpoint-managed absolute runtime path. Merge with organisation permissions; do not weaken existing deny rules or set a global subagent model environment variable."
        ).encode("utf-8")
    if "cursor" in selected:
        artifacts[Path("dist/enterprise/cursor/team-rules.md")] = one_newline(
            markdown_header("enterprise/cursor/ and official Cursor Team Rules documentation")
            + "\n# Workstation AI Guardrails team-rule text\n\n"
            "Use the generated global behavioural policy as organisation-reviewed Team Rule text. Native hooks remain the deterministic control. This file is guidance for the documented administration UI, not a fabricated managed settings format."
        ).encode("utf-8")
        artifacts[Path("dist/enterprise/cursor/README.md")] = one_newline(
            markdown_header("enterprise/cursor/ and official Cursor rules and hooks documentation")
            + "\n# Cursor enterprise guidance\n\n"
            "Configure Team Rules and native hooks through documented enterprise administration. Confirm plan and organisation model availability. Cursor User Rules, CLI permissions, project rules, and IDE hooks have different scopes."
        ).encode("utf-8")
    artifacts[Path("dist/enterprise/spacelift/README.md")] = one_newline(
        markdown_header("enterprise/spacelift/ and platform-policies/spacelift/")
        + "\n# Spacelift enterprise examples\n\n"
        "Use Spaces/RBAC and Login, Approval, Plan, Push, Trigger, and Notification Policies. Review copies of the Rego v1 source, tests, and synthetic configuration are generated under `policies/`; they are never attached or deployed by this repository. The unified MCP endpoint is `/mcp`; no removed `/intent/mcp` endpoint is generated."
    ).encode("utf-8")
    spacelift_root = RESOURCE_ROOT / "platform-policies/spacelift"
    for source in sorted(spacelift_root.rglob("*.rego")):
        if source.is_symlink():
            raise GuardrailsError(f"Spacelift policy source must not be a symbolic link: {source}")
        relative = source.relative_to(spacelift_root)
        artifacts[Path("dist/enterprise/spacelift/policies") / relative] = one_newline(
            "# GENERATED — DO NOT EDIT\n"
            f"# Canonical source: platform-policies/spacelift/{relative.as_posix()}\n\n"
            + source.read_text(encoding="utf-8").strip()
        ).encode("utf-8")
    fixture = json.loads((spacelift_root / "fixtures/guardrails.json").read_text(encoding="utf-8"))
    fixture["_generated"] = (
        "GENERATED — DO NOT EDIT. Canonical source: "
        "platform-policies/spacelift/fixtures/guardrails.json."
    )
    artifacts[Path("dist/enterprise/spacelift/policies/fixtures/guardrails.json")] = json_bytes(fixture)
    return artifacts


def build_artifacts(
    products: Sequence[str] = PRODUCTS,
    *,
    manifest_path: Path = policy.MANIFEST_PATH,
    skills_root: Path | None = None,
    home: Path | None = None,
) -> dict[Path, bytes]:
    selected = set(products)
    unknown = sorted(selected - set(PRODUCTS))
    if unknown:
        raise GuardrailsError(f"unknown product: {unknown[0]}")
    manifest = policy.load_manifest(manifest_path)
    skills = policy.discover_skills(skills_root or policy.SKILLS_ROOT)
    routing.load_config()
    local = policy.validate_local_overlay(home) if home is not None else None
    local_fragments: Sequence[Mapping[str, Any]] = local["fragments"] if local else ()
    command_policy = local["policy"] if local else policy.load_enforcement_policy()
    artifacts: dict[Path, bytes] = {}
    if "codex" in selected:
        artifacts[Path("dist/codex/AGENTS.md")] = render_policy(
            "codex", manifest, manifest_path, local_fragments
        ).encode("utf-8")
        rules = codex_rules(command_policy).encode("utf-8")
        artifacts[Path("dist/codex/rules/workstation-guardrails.rules")] = rules
        artifacts[Path("adapters/codex/workstation-guardrails.rules")] = rules
        hooks = adapter_json("enforcement policies and adapters/codex/", _hook_payload("codex"))
        artifacts[Path("dist/codex/hooks.json")] = hooks
        artifacts[Path("adapters/codex/hooks.fragment.json")] = hooks
    if "claude" in selected:
        total = 0
        for entry in manifest["fragments"]:
            if "claude" not in entry["products"] or entry["load"] != "always":
                continue
            rendered = render_claude_rule(entry, manifest_path).encode("utf-8")
            total += len(rendered)
            name = Path(entry["path"]).name
            artifacts[Path("dist/claude/rules") / f"workstation-guardrails-{name}"] = rendered
        for fragment in local_fragments:
            if "claude" not in fragment["products"]:
                continue
            rendered = render_local_claude_rule(fragment).encode("utf-8")
            total += len(rendered)
            artifacts[Path("dist/claude/rules") / f"workstation-guardrails-{fragment['id']}.md"] = rendered
        if total == 0 or total > manifest["output_limits_bytes"]["claude"]:
            raise GuardrailsError("generated claude policy is empty or exceeds configured limit")
        _check_always_loaded_budget("claude", total, manifest)
        settings = adapter_json("enforcement policies and adapters/claude/", _hook_payload("claude"))
        artifacts[Path("dist/claude/settings.fragment.json")] = settings
        artifacts[Path("adapters/claude/settings.fragment.json")] = settings
    if "cursor" in selected:
        artifacts[Path("dist/cursor/user-rules.md")] = render_policy(
            "cursor", manifest, manifest_path, local_fragments
        ).encode("utf-8")
        hooks = adapter_json("enforcement policies and adapters/cursor/", _hook_payload("cursor"))
        artifacts[Path("dist/cursor/hooks.json")] = hooks
        artifacts[Path("adapters/cursor/hooks.fragment.json")] = hooks
        permissions = adapter_json(
            "adapters/cursor/cli-permissions.recommended.json",
            {
                "description": "Recommendation for Cursor CLI only; not an automatically installed IDE-wide policy.",
                "permissions": {
                    "allow": ["Shell(git status)", "Shell(git diff)", "Read(**/*.md)"],
                    "deny": ["Read(.env*)", "Write(**/*.key)", "Write(**/.env*)", "Shell(rm:-rf /)"],
                },
            },
        )
        artifacts[Path("dist/cursor/cli-permissions.recommended.json")] = permissions
        artifacts[Path("adapters/cursor/cli-permissions.recommended.json")] = permissions
    if "vscode" in selected:
        artifacts[Path("dist/vscode/instructions/workstation-guardrails.instructions.md")] = _vscode_instructions(
            manifest, manifest_path, local_fragments
        )
        artifacts[Path("dist/vscode/hooks/workstation-guardrails.json")] = adapter_json(
            "enforcement policies and official VS Code hooks documentation", _hook_payload("vscode")
        )
    if "visualstudio" in selected:
        artifacts[Path("dist/visualstudio/copilot-instructions.md")] = render_policy(
            "visualstudio", manifest, manifest_path, local_fragments
        ).encode("utf-8")
    if "jetbrains" in selected:
        rendered = render_policy("jetbrains", manifest, manifest_path, local_fragments).encode("utf-8")
        artifacts[Path("dist/jetbrains/ai-assistant/chat-instructions.md")] = rendered
        artifacts[Path("dist/jetbrains/ai-assistant/project-rules/workstation-guardrails.md")] = rendered
        artifacts[Path("dist/jetbrains/copilot/global-copilot-instructions.md")] = rendered
    for product_name in sorted(selected):
        for filename, data in routing.render_agents(product_name).items():
            agent_root = (
                Path("dist/jetbrains/copilot/agents")
                if product_name == "jetbrains"
                else Path("dist") / product_name / "agents"
            )
            artifacts[agent_root / filename] = data
    for skill_file in skills:
        rendered = render_skill(skill_file).encode("utf-8")
        skill_name = skill_file.parent.name
        artifacts[Path("dist/skills") / skill_name / "SKILL.md"] = rendered
        for product_name in sorted(selected):
            artifacts[Path("dist") / product_name / "skills" / skill_name / "SKILL.md"] = rendered
    artifacts.update(_enterprise_artifacts(selected))
    for path, data in artifacts.items():
        if not data.strip():
            raise GuardrailsError(f"generated output would be empty: {path.as_posix()}")
        if not data.endswith(b"\n") or data.endswith(b"\n\n"):
            raise GuardrailsError(f"generated output must end with exactly one newline: {path.as_posix()}")
        if b"GENERATED \xe2\x80\x94 DO NOT EDIT" not in data:
            raise GuardrailsError(f"generated output lacks generated header: {path.as_posix()}")
    return artifacts


def write_artifacts(artifacts: Mapping[Path, bytes], output_root: Path) -> int:
    """Write logical artifacts beneath an explicit contributor-controlled root."""
    changed = 0
    root = output_root.expanduser().resolve(strict=False)
    for relative, data in sorted(artifacts.items(), key=lambda item: item[0].as_posix()):
        if relative.is_absolute() or ".." in relative.parts:
            raise GuardrailsError(f"generated artifact path is unsafe: {relative}")
        target = root / relative
        if not path_within(target, root):
            raise GuardrailsError(f"generated artifact escapes output root: {relative}")
        if atomic_write(target, data):
            print(f"built {relative.as_posix()}")
            changed += 1
    return changed


def _remove_stale_generated(output_root: Path, expected: set[Path]) -> int:
    removed = 0
    for relative_root in GENERATED_ROOTS:
        root = output_root / relative_root
        if not root.exists():
            continue
        for path in sorted((item for item in root.rglob("*") if item.is_file()), reverse=True):
            if path.relative_to(output_root) in expected:
                continue
            try:
                content = path.read_bytes()
            except OSError as exc:
                raise GuardrailsError(f"cannot inspect stale generated file {path}: {exc}") from exc
            if b"GENERATED \xe2\x80\x94 DO NOT EDIT" not in content:
                continue
            path.unlink()
            removed += 1
        for directory in sorted((item for item in root.rglob("*") if item.is_dir()), reverse=True):
            if not any(directory.iterdir()):
                directory.rmdir()
    return removed


def build(products: Sequence[str] = PRODUCTS, *, output_root: Path | None = None) -> None:
    root = output_root or repository_output_root()
    if root is None:
        raise GuardrailsError("build requires an explicit output root outside the installed package")
    artifacts = build_artifacts(products)
    changed = write_artifacts(artifacts, root)
    removed = _remove_stale_generated(root, set(artifacts))
    print(f"build complete: {changed} changed, {len(artifacts) - changed} unchanged, {removed} stale removed")


def validate_codex_rules(rules: bytes | None = None) -> str:
    executable = shutil.which("codex")
    if executable is None:
        return "skipped (codex executable not available)"
    if rules is None:
        root = repository_output_root()
        rules_path = root / "dist/codex/rules/workstation-guardrails.rules" if root else None
        if rules_path is None or not rules_path.is_file():
            return "skipped (generated Codex rules are not available)"
        arguments = [executable, "execpolicy", "check", "--rules", str(rules_path), "--", "git", "reset", "--hard"]
        result = subprocess.run(arguments, capture_output=True, text=True, timeout=30, check=False)
    else:
        import tempfile

        with tempfile.TemporaryDirectory() as temporary:
            rules_path = Path(temporary) / "workstation-guardrails.rules"
            atomic_write(rules_path, rules)
            result = subprocess.run(
                [executable, "execpolicy", "check", "--rules", str(rules_path), "--", "git", "reset", "--hard"],
                capture_output=True,
                text=True,
                timeout=30,
                check=False,
            )
    if result.returncode != 0 or "forbidden" not in result.stdout.lower():
        raise GuardrailsError("codex execpolicy check did not report the expected forbidden decision")
    return "passed"


def validate_spacelift_policies() -> str:
    from .scan import validate_spacelift_policy_structure

    spacelift_root = RESOURCE_ROOT / "platform-policies/spacelift"
    validate_spacelift_policy_structure(spacelift_root)
    executable = shutil.which("opa")
    if executable is None:
        return "skipped semantic Rego execution (opa executable not available); structural checks passed"

    fixture = spacelift_root / "fixtures/guardrails.json"
    policy_directories = sorted(
        path.parent for path in spacelift_root.glob("*/guardrails.rego")
    )
    for policy_directory in policy_directories:
        result = subprocess.run(
            [executable, "test", str(fixture), str(policy_directory)],
            capture_output=True,
            text=True,
            timeout=60,
            check=False,
        )
        if result.returncode != 0:
            command = shlex.join([executable, "test", str(fixture), str(policy_directory)])
            raise GuardrailsError(
                f"OPA semantic policy tests failed for {policy_directory.name}; "
                f"run {command} for details"
            )
    return "passed"


def validate(
    products: Sequence[str] = PRODUCTS,
    *,
    check_codex: bool = True,
    require_current: bool = False,
    output_root: Path | None = None,
    home: Path | None = None,
) -> dict[str, Any]:
    if set(PRODUCT_LABELS) != set(PRODUCTS) or set(PRODUCT_CAPABILITIES) != set(PRODUCTS):
        raise GuardrailsError("product labels and capability mappings must cover every supported product exactly once")
    required_capabilities = {
        "instructions", "repository_instructions", "skills", "agents", "subagents",
        "deterministic_hook", "hook_maturity", "version_requirement", "manual_steps",
        "platform_restriction", "model_availability",
    }
    if any(required_capabilities - set(PRODUCT_CAPABILITIES[product]) for product in PRODUCTS):
        raise GuardrailsError("product capability mapping is missing a required compatibility claim")
    artifacts = build_artifacts(products, home=home)
    root = output_root.expanduser().resolve(strict=False) if output_root is not None else None
    if require_current and root is None:
        raise GuardrailsError("generated-output validation requires an explicit output root")
    for path, expected in artifacts.items():
        actual = expected
        if require_current:
            target = root / path
            if not target.is_file():
                raise GuardrailsError(f"generated file is missing; run build: {path.as_posix()}")
            actual = target.read_bytes()
            if actual != expected:
                raise GuardrailsError(f"generated file is stale; run build: {path.as_posix()}")
        text = actual.decode("utf-8")
        if str(Path.home()) in text or str(RESOURCE_ROOT) in text:
            raise GuardrailsError(f"generated output contains a workstation path: {path.as_posix()}")
        if path.suffix == ".json":
            try:
                json.loads(text)
            except json.JSONDecodeError as exc:
                raise GuardrailsError(f"generated JSON is invalid: {path.as_posix()}: {exc}") from exc
        if path.suffix == ".toml":
            try:
                tomllib.loads(text)
            except tomllib.TOMLDecodeError as exc:
                raise GuardrailsError(f"generated TOML is invalid: {path.as_posix()}: {exc}") from exc
        relative = path
        if relative.parts and relative.parts[0] == "dist" and "agents" in relative.parts:
            if path.suffix == ".md":
                fields = routing.frontmatter_fields(text, relative.as_posix())
                if {"name", "description"} - fields.keys():
                    raise GuardrailsError(f"generated agent lacks required frontmatter: {relative}")
        if path == Path("dist/vscode/instructions/workstation-guardrails.instructions.md"):
            fields = routing.frontmatter_fields(text, path.as_posix())
            if fields.get("applyTo") != "**" or {"name", "description"} - fields.keys():
                raise GuardrailsError("generated VS Code instructions have invalid frontmatter")
    pack_count, _ = packs.validate_packs()
    policy.validate_canonical_data()
    from . import enforcement

    policy_data = policy.load_effective_enforcement_policy(home) if home is not None else policy.load_enforcement_policy()
    examples = enforcement.validate_policy_examples(policy_data)
    routing_agent_count = len(routing.load_config()["agents"])
    codex = "not requested"
    if check_codex and "codex" in products:
        rules_path = Path("dist/codex/rules/workstation-guardrails.rules")
        rules_are_current = root is not None and (root / rules_path).is_file() and (root / rules_path).read_bytes() == artifacts[rules_path]
        codex = (
            validate_codex_rules(artifacts[rules_path])
            if require_current or rules_are_current
            else "skipped (computed rules are not written during a dry-run)"
        )
    spacelift = validate_spacelift_policies()
    checks: list[dict[str, str]] = [
        {
            "id": "generated-output",
            "label": "Generated output",
            "outcome": "passed",
            "detail": f"{len(artifacts)} files",
        },
        {
            "id": "policy-fixtures",
            "label": "Policy fixtures",
            "outcome": "passed",
            "detail": f"{examples} examples",
        },
        {
            "id": "capability-packs",
            "label": "Capability packs",
            "outcome": "passed",
            "detail": f"{pack_count} packs",
        },
        {
            "id": "routing-agents",
            "label": "Routing agents",
            "outcome": "passed",
            "detail": f"{routing_agent_count} agents",
        },
    ]
    if check_codex and "codex" in products:
        checks.append(
            {
                "id": "codex-execpolicy",
                "label": "Codex execpolicy",
                "outcome": "skipped" if codex.startswith("skipped") else "passed",
                "detail": codex,
            }
        )
    checks.append(
        {
            "id": "spacelift-rego",
            "label": "Spacelift Rego",
            "outcome": "skipped" if spacelift.startswith("skipped") else "passed",
            "detail": spacelift,
        }
    )
    report = {"schema_version": 1, "status": "passed", "checks": checks}
    print(
        f"validation passed: {len(artifacts)} generated files, {examples} policy fixtures, "
        f"{pack_count} packs, {routing_agent_count} routing agents"
    )
    if check_codex and "codex" in products:
        print(f"codex execpolicy check: {codex}")
    print(f"Spacelift policy validation: {spacelift}")
    return report


def assert_generated_current(products: Sequence[str] = PRODUCTS, *, output_root: Path | None = None) -> None:
    root = output_root or repository_output_root()
    if root is None:
        raise GuardrailsError("generated-output validation requires an explicit output root")
    for path, expected in build_artifacts(products).items():
        target = root / path
        if not target.is_file() or target.read_bytes() != expected:
            raise GuardrailsError(f"generated output is stale: {path.as_posix()}")
