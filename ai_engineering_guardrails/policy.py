"""Canonical behavioural, skill, and deterministic policy loading."""

from __future__ import annotations

import copy
import re
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

from . import packs
from .resources import RESOURCE_ROOT
from .util import (
    NAME_RE,
    OPERATION_CLASSES,
    PRODUCTS,
    ROLLOUT_MODES,
    GuardrailsError,
    atomic_write,
    home_path,
    json_bytes,
    parse_simple_frontmatter,
    path_within,
    read_json,
    sha256,
    tree_hash,
    validate_install_target,
)


MANIFEST_PATH = RESOURCE_ROOT / "policy" / "manifest.json"
SKILLS_ROOT = RESOURCE_ROOT / "skills"
ENFORCEMENT_ROOT = RESOURCE_ROOT / "enforcement"
LOCAL_POLICY_RELATIVE = Path(".ai-guardrails/policy")
LOCAL_OVERLAY_RELATIVE = LOCAL_POLICY_RELATIVE / "overrides.json"
SKILL_NAME_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
LOCAL_FRAGMENT_ID_RE = re.compile(r"^local-[a-z0-9]+(?:[-_][a-z0-9]+)*$")
FORBIDDEN_LOCAL_DIRECTIVE_RE = re.compile(
    r"(?im)^\s*(?:disable|turn\s+off|bypass|ignore)\s+(?:deterministic\s+)?(?:workstation\s+)?(?:enforcement|guardrails|hooks?)\b"
)
CANONICAL_JSON_FILES = (
    "audit/redaction-policy.json",
    "audit/schema.json",
    "config/repository.example.json",
    "config/safety-profiles.json",
    "config/targets.example.json",
    "risk/path-classification.json",
    "risk/verification-requirements.json",
    "supply-chain/schema.json",
    "supply-chain/trusted-components.example.json",
    "trust/content-policy.json",
    "trust/modes.json",
    "waivers/schema.json",
)


def canonical_relative(path: Path) -> str:
    """Return a portable source label for a bundled canonical file."""
    try:
        return path.relative_to(RESOURCE_ROOT).as_posix()
    except ValueError as exc:
        raise GuardrailsError(f"canonical path is outside bundled resources: {path}") from exc


def load_manifest(path: Path = MANIFEST_PATH) -> dict[str, Any]:
    manifest = read_json(path, default={})
    if not isinstance(manifest, dict) or manifest.get("schema_version") != 1:
        raise GuardrailsError("policy manifest has an unsupported schema")
    if manifest.get("products") != list(PRODUCTS):
        raise GuardrailsError(f"policy manifest products must be {', '.join(PRODUCTS)}")
    limits = manifest.get("output_limits_bytes")
    if not isinstance(limits, dict) or any(
        not isinstance(limits.get(product), int) or limits[product] <= 0 for product in PRODUCTS
    ):
        raise GuardrailsError("policy manifest must define positive output limits for every product")
    fragments = manifest.get("fragments")
    if not isinstance(fragments, list) or not fragments:
        raise GuardrailsError("policy manifest must define at least one fragment")
    identifiers: set[str] = set()
    orders: set[int] = set()
    policy_root = path.parent.resolve(strict=False)
    required = {
        "id",
        "path",
        "order",
        "products",
        "description",
        "classification",
        "load",
        "enforcement_ids",
        "risk_ids",
    }
    for entry in fragments:
        if not isinstance(entry, dict) or required - entry.keys():
            raise GuardrailsError("policy manifest fragment is missing required fields")
        identifier = entry["id"]
        if not isinstance(identifier, str) or not identifier or not NAME_RE.fullmatch(identifier):
            raise GuardrailsError("policy fragment identifiers must be portable non-empty strings")
        if identifier in identifiers:
            raise GuardrailsError(f"duplicate policy fragment identifier: {identifier}")
        identifiers.add(identifier)
        order = entry["order"]
        if not isinstance(order, int) or order < 0 or order in orders:
            raise GuardrailsError(f"duplicate or invalid policy fragment order: {identifier}")
        orders.add(order)
        selected_products = entry["products"]
        if not isinstance(selected_products, list) or not selected_products:
            raise GuardrailsError(f"fragment {identifier} must select at least one product")
        unknown = sorted(set(selected_products) - set(PRODUCTS))
        if unknown:
            raise GuardrailsError(f"fragment {identifier} selects unknown product: {unknown[0]}")
        if entry["classification"] not in {
            "behavioural_guidance",
            "deterministic_enforcement_guidance",
        }:
            raise GuardrailsError(f"fragment {identifier} has an unknown classification")
        if entry["load"] not in {"always", "on-demand"}:
            raise GuardrailsError(f"fragment {identifier} has an unknown load mode")
        for field in ("enforcement_ids", "risk_ids"):
            if not isinstance(entry[field], list) or not all(isinstance(item, str) and item for item in entry[field]):
                raise GuardrailsError(f"fragment {identifier} has invalid {field}")
        relative = Path(str(entry["path"]))
        source = path.parent / relative
        if relative.is_absolute() or not path_within(source, policy_root):
            raise GuardrailsError(f"fragment {identifier} has an unsafe path")
        if source.is_symlink():
            raise GuardrailsError(f"manifest fragment must not be a symbolic link: {relative.as_posix()}")
        if not source.is_file():
            raise GuardrailsError(f"manifest fragment is missing: {relative.as_posix()}")
        if not source.read_text(encoding="utf-8").strip():
            raise GuardrailsError(f"manifest fragment is empty: {relative.as_posix()}")
    risk_documents = (
        read_json(RESOURCE_ROOT / "risk/path-classification.json", default={}).get("classifications", []),
        read_json(RESOURCE_ROOT / "risk/verification-requirements.json", default={}).get("requirements", []),
    )
    risk_identifiers = {
        entry.get("id")
        for entries in risk_documents
        if isinstance(entries, list)
        for entry in entries
        if isinstance(entry, Mapping) and isinstance(entry.get("id"), str)
    }
    enforcement_policy = load_enforcement_policy()
    enforcement_identifiers = {
        entry["id"]
        for collection in ("rules", "structured_tool_rules", "classifications")
        for entry in enforcement_policy[collection]
    }
    for entry in fragments:
        unknown_enforcement = sorted(set(entry["enforcement_ids"]) - enforcement_identifiers)
        if unknown_enforcement:
            raise GuardrailsError(
                f"fragment {entry['id']} references unknown enforcement identifier: {unknown_enforcement[0]}"
            )
        unknown_risks = sorted(set(entry["risk_ids"]) - risk_identifiers)
        if unknown_risks:
            raise GuardrailsError(f"fragment {entry['id']} references unknown risk identifier: {unknown_risks[0]}")
    manifest["fragments"] = sorted(fragments, key=lambda entry: (entry["order"], entry["id"]))
    return manifest


def parse_skill(skill_file: Path) -> tuple[dict[str, str], str]:
    fields, body = parse_simple_frontmatter(
        skill_file,
        required={"name", "description"},
        allowed={"name", "description"},
    )
    if fields["name"] != skill_file.parent.name or not SKILL_NAME_RE.fullmatch(fields["name"]):
        raise GuardrailsError(f"skill name must match its directory: {skill_file}")
    return fields, body


def discover_skills(skills_root: Path = SKILLS_ROOT) -> list[Path]:
    skill_files = sorted(skills_root.glob("*/SKILL.md"))
    if not skill_files:
        raise GuardrailsError("no portable skills found")
    names: set[str] = set()
    for skill_file in skill_files:
        if skill_file.parent.is_symlink() or any(path.is_symlink() for path in skill_file.parent.rglob("*")):
            raise GuardrailsError(f"portable skill contains a symbolic link: {skill_file.parent}")
        fields, _ = parse_skill(skill_file)
        if fields["name"] in names:
            raise GuardrailsError(f"duplicate skill name: {fields['name']}")
        names.add(fields["name"])
    return skill_files


def _load_policy_file(path: Path, *, structured_only: bool = False) -> dict[str, Any]:
    data = read_json(path, default={})
    if not isinstance(data, dict) or data.get("schema_version") != 1:
        raise GuardrailsError(f"unsupported policy schema: {path}")
    rules = data.get("rules")
    if not isinstance(rules, list):
        raise GuardrailsError(f"policy rules must be a list: {path}")
    settings = data.get("structured_tools", {})
    if not isinstance(settings, Mapping):
        raise GuardrailsError(f"structured tool settings must be an object: {path}")
    result = {
        "schema_version": 1,
        "rules": [],
        "classifications": [],
        "structured_tool_rules": [],
        "structured_tools": {"strict_allowlist": settings.get("strict_allowlist") is True},
    }
    destination = "structured_tool_rules" if structured_only else "rules"
    result[destination].extend(copy.deepcopy(rules))
    if not structured_only:
        classifications = data.get("classifications", [])
        if not isinstance(classifications, list):
            raise GuardrailsError(f"command classifications must be a list: {path}")
        result["classifications"].extend(copy.deepcopy(classifications))
        structured = data.get("structured_tool_rules", [])
        if not isinstance(structured, list):
            raise GuardrailsError(f"structured tool rules must be a list: {path}")
        result["structured_tool_rules"].extend(copy.deepcopy(structured))
    return result


def policy_source_paths(selected_packs: Iterable[str] | None = None) -> tuple[list[Path], list[Path]]:
    command_paths = [ENFORCEMENT_ROOT / "command-policy.json"]
    structured_paths = [ENFORCEMENT_ROOT / "structured-tool-policy.json"]
    available = packs.load_packs()
    identifiers = tuple(sorted(available)) if selected_packs is None else packs.selected_pack_closure(selected_packs, available)
    for identifier in identifiers:
        pack = available[identifier]
        root = Path(pack["_root"])
        command_paths.extend(root / item for item in pack["command_policy_fragments"])
        structured_paths.extend(root / item for item in pack["structured_tool_policy_fragments"])
    return command_paths, structured_paths


def merge_policy_data(policies: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    merged: dict[str, Any] = {
        "schema_version": 1,
        "rules": [],
        "classifications": [],
        "structured_tool_rules": [],
        "structured_tools": {"strict_allowlist": False},
    }
    identifiers: set[str] = set()
    for source in policies:
        for collection in ("rules", "classifications", "structured_tool_rules"):
            for raw_rule in source.get(collection, []):
                if not isinstance(raw_rule, Mapping):
                    raise GuardrailsError("policy rule must be an object")
                rule = copy.deepcopy(dict(raw_rule))
                identifier = rule.get("id")
                if not isinstance(identifier, str) or not identifier:
                    raise GuardrailsError("policy rule lacks a stable identifier")
                if identifier in identifiers:
                    raise GuardrailsError(f"duplicate deterministic policy identifier: {identifier}")
                identifiers.add(identifier)
                if rule.get("operation_class") not in OPERATION_CLASSES:
                    raise GuardrailsError(f"policy rule {identifier} has unknown operation class")
                if collection != "classifications":
                    mode = rule.setdefault("rollout_mode", "deny")
                    if mode not in ROLLOUT_MODES:
                        raise GuardrailsError(f"policy rule {identifier} has unsupported rollout mode: {mode}")
                rule.setdefault("policy_source", "canonical")
                merged[collection].append(rule)
        settings = source.get("structured_tools", {})
        if isinstance(settings, Mapping) and settings.get("strict_allowlist") is True:
            merged["structured_tools"]["strict_allowlist"] = True
    return merged


def load_enforcement_policy(selected_packs: Iterable[str] | None = None) -> dict[str, Any]:
    command_paths, structured_paths = policy_source_paths(selected_packs)
    sources: list[dict[str, Any]] = []
    for path in command_paths:
        source = _load_policy_file(path)
        for rule in (*source["rules"], *source["structured_tool_rules"]):
            rule["policy_source"] = canonical_relative(path)
        sources.append(source)
    for path in structured_paths:
        if not path.is_file():
            raise GuardrailsError(f"structured-tool policy is missing: {canonical_relative(path)}")
        source = _load_policy_file(path, structured_only=True)
        for rule in source["structured_tool_rules"]:
            rule["policy_source"] = canonical_relative(path)
        sources.append(source)
    merged = merge_policy_data(sources)
    from . import enforcement

    try:
        return enforcement.validate_policy_data(merged)
    except enforcement.PolicyError as exc:
        raise GuardrailsError(f"invalid deterministic policy: {exc}") from exc


def find_rule(identifier: str, selected_packs: Iterable[str] | None = None) -> dict[str, Any] | None:
    merged = load_enforcement_policy(selected_packs)
    for rule in (*merged["rules"], *merged["structured_tool_rules"]):
        if rule["id"] == identifier:
            return rule
    return None


def local_policy_root(home: Path) -> Path:
    return home_path(home.expanduser().resolve(strict=False), LOCAL_POLICY_RELATIVE)


def local_overlay_path(home: Path) -> Path:
    return home_path(home.expanduser().resolve(strict=False), LOCAL_OVERLAY_RELATIVE)


def empty_local_overlay() -> dict[str, Any]:
    return {
        "schema_version": 1,
        "behavioural_fragments": [],
        "rule_modes": {},
        "additional_rules": [],
    }


def load_local_overlay(home: Path) -> dict[str, Any]:
    path = local_overlay_path(home)
    validate_install_target(path, home)
    if not path.exists():
        return empty_local_overlay()
    if path.is_symlink():
        raise GuardrailsError("local policy overlay must not be a symbolic link")
    data = read_json(path, default={})
    if not isinstance(data, Mapping):
        raise GuardrailsError("local policy overlay must be a JSON object")
    return dict(data)


def _local_fragment_path(home: Path, relative: str) -> Path:
    root = local_policy_root(home)
    path = Path(relative)
    if path.is_absolute() or ".." in path.parts or path.parts[:1] != ("fragments",):
        raise GuardrailsError("local policy fragment path must remain beneath policy/fragments")
    candidate = root / path
    if root.is_symlink() or not path_within(candidate, root) or candidate.is_symlink():
        raise GuardrailsError("local policy fragment path is unsafe")
    validate_install_target(candidate, home)
    return candidate


def _validate_local_fragments(home: Path, values: Any) -> list[dict[str, Any]]:
    if not isinstance(values, list):
        raise GuardrailsError("local behavioural_fragments must be a list")
    validated: list[dict[str, Any]] = []
    identifiers: set[str] = set()
    for item in values:
        required = {"id", "path", "products", "description"}
        if not isinstance(item, Mapping) or set(item) != required:
            raise GuardrailsError("local behavioural fragment has unsupported fields")
        identifier = item["id"]
        if not isinstance(identifier, str) or not LOCAL_FRAGMENT_ID_RE.fullmatch(identifier) or identifier in identifiers:
            raise GuardrailsError("local behavioural fragment identifier must be a unique local-* value")
        identifiers.add(identifier)
        products = item["products"]
        if not isinstance(products, list) or not products or any(product not in PRODUCTS for product in products):
            raise GuardrailsError("local behavioural fragment selects an unknown product")
        if not isinstance(item["description"], str) or not item["description"].strip():
            raise GuardrailsError("local behavioural fragment requires a description")
        if not isinstance(item["path"], str):
            raise GuardrailsError("local behavioural fragment path must be a string")
        source = _local_fragment_path(home, item["path"])
        if not source.is_file():
            raise GuardrailsError(f"local behavioural fragment is missing: {item['path']}")
        try:
            content = source.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as exc:
            raise GuardrailsError(f"cannot read local behavioural fragment: {item['path']}") from exc
        if not content.strip():
            raise GuardrailsError(f"local behavioural fragment is empty: {item['path']}")
        if FORBIDDEN_LOCAL_DIRECTIVE_RE.search(content):
            raise GuardrailsError("local behavioural fragment cannot disable deterministic enforcement")
        validated.append({**dict(item), "content": content.strip()})
    return validated


def _validate_effective_policy(value: Mapping[str, Any]) -> dict[str, Any]:
    from . import enforcement

    try:
        checked = enforcement.validate_policy_data(value)
        enforcement.validate_policy_examples(checked)
        return checked
    except enforcement.PolicyError as exc:
        raise GuardrailsError(f"invalid local deterministic policy: {exc}") from exc


def validate_local_overlay(home: Path, selected_packs: Iterable[str] | None = None) -> dict[str, Any]:
    overlay = load_local_overlay(home)
    if set(overlay) != set(empty_local_overlay()):
        raise GuardrailsError("local policy overlay has unsupported top-level fields")
    if overlay.get("schema_version") != 1:
        raise GuardrailsError("local policy overlay has an unsupported schema")
    baseline = load_enforcement_policy(selected_packs)
    fragments = _validate_local_fragments(home, overlay.get("behavioural_fragments"))
    modes = overlay.get("rule_modes")
    if not isinstance(modes, Mapping) or any(not isinstance(key, str) or not isinstance(value, str) for key, value in modes.items()):
        raise GuardrailsError("local policy rule_modes must be a string mapping")
    strength = {"disabled": 0, "observe": 1, "warn": 2, "deny": 3}
    rules = {str(rule["id"]): rule for rule in baseline["rules"]}
    effective = copy.deepcopy(baseline)
    for identifier, requested in modes.items():
        rule = rules.get(identifier)
        if rule is None:
            raise GuardrailsError(f"local policy references an unknown bundled rule: {identifier}")
        current = str(rule.get("rollout_mode", "deny"))
        if requested not in strength or strength[requested] < strength[current]:
            raise GuardrailsError(f"local policy cannot weaken bundled rule {identifier}")
        for candidate in effective["rules"]:
            if candidate["id"] == identifier:
                candidate["rollout_mode"] = requested
                candidate["local_mode_strengthening"] = requested != current
                break
    additional = overlay.get("additional_rules")
    if not isinstance(additional, list):
        raise GuardrailsError("local policy additional_rules must be a list")
    existing_ids = {str(rule["id"]) for group in ("rules", "classifications", "structured_tool_rules") for rule in effective[group]}
    for raw in additional:
        if not isinstance(raw, Mapping):
            raise GuardrailsError("local additional rule must be an object")
        rule = copy.deepcopy(dict(raw))
        identifier = rule.get("id")
        if not isinstance(identifier, str) or not LOCAL_FRAGMENT_ID_RE.fullmatch(identifier):
            raise GuardrailsError("local additional rule identifier must use the local-* prefix")
        if identifier in existing_ids:
            raise GuardrailsError(f"local additional rule collides with existing rule: {identifier}")
        existing_ids.add(identifier)
        rule["policy_source"] = "local policy overlay"
        effective["rules"].append(rule)
    checked = _validate_effective_policy(effective)
    return {"overlay": overlay, "fragments": fragments, "policy": checked}


def load_effective_enforcement_policy(home: Path, selected_packs: Iterable[str] | None = None) -> dict[str, Any]:
    return validate_local_overlay(home, selected_packs)["policy"]


def local_policy_digest(home: Path, selected_packs: Iterable[str] | None = None) -> str:
    validated = validate_local_overlay(home, selected_packs)
    payload = json_bytes(validated["overlay"])
    for fragment in validated["fragments"]:
        payload += fragment["id"].encode("utf-8") + b"\0" + fragment["content"].encode("utf-8") + b"\0"
    return sha256(payload)


def initialise_local_overlay(home: Path, *, force: bool, dry_run: bool) -> Path:
    root = local_policy_root(home)
    target = local_overlay_path(home)
    validate_install_target(target, home)
    if target.exists() and not force:
        raise GuardrailsError(f"local policy overlay already exists: {target}")
    if target.exists() and force:
        # Reuse the installation backup path rather than silently discarding a
        # user-authored overlay during an explicit reinitialisation.
        from . import state

        state.backup_existing(home, target, dry_run=dry_run)
    print(f"{'would initialise' if dry_run else 'initialise'} local policy overlay {target}")
    if dry_run:
        return target
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    root.chmod(0o700)
    (root / "fragments").mkdir(exist_ok=True, mode=0o700)
    atomic_write(target, json_bytes(empty_local_overlay()), mode=0o600)
    readme = root / "README.md"
    if not readme.exists():
        atomic_write(
            readme,
            b"# Local policy overlay\n\nAdd local Markdown under `fragments/`, then list it in `overrides.json`. Local rules may add or strengthen enforcement but cannot permanently weaken bundled rules. Run `ai-guardrails policy validate` before `ai-guardrails policy apply`.\n",
            mode=0o600,
        )
    return target


def local_policy_diff(home: Path, selected_packs: Iterable[str] | None = None) -> dict[str, list[str]]:
    validated = validate_local_overlay(home, selected_packs)
    overlay = validated["overlay"]
    return {
        "behavioural_fragments": [fragment["id"] for fragment in validated["fragments"]],
        "strengthened_rule_modes": sorted(
            identifier
            for identifier, mode in overlay["rule_modes"].items()
            if any(
                rule["id"] == identifier and rule.get("local_mode_strengthening")
                for rule in validated["policy"]["rules"]
            )
        ),
        "additional_rules": [str(rule.get("id")) for rule in overlay["additional_rules"]],
    }


def supply_chain_findings(path: Path) -> list[str]:
    data = read_json(path, default={})
    components = data.get("components") if isinstance(data, Mapping) else None
    if not isinstance(components, list):
        raise GuardrailsError(f"trusted component registry must contain a components list: {path}")
    findings: list[str] = []
    identifiers: set[str] = set()
    required = {
        "id",
        "kind",
        "source",
        "version",
        "digest",
        "allowed_tools",
        "denied_tools",
        "credential_class",
        "expected_network_destinations",
    }
    executable_kinds = {"mcp-server", "plugin", "skill", "custom-agent", "external-validator"}
    for component in components:
        if not isinstance(component, Mapping) or required - component.keys():
            raise GuardrailsError("trusted component registry entry is missing required fields")
        identifier = component["id"]
        if not isinstance(identifier, str) or not NAME_RE.fullmatch(identifier) or identifier in identifiers:
            raise GuardrailsError("trusted component identifiers must be unique portable names")
        identifiers.add(identifier)
        kind = component["kind"]
        if kind not in executable_kinds | {"marketplace"}:
            raise GuardrailsError(f"trusted component {identifier} has an unknown kind")
        for field in ("allowed_tools", "denied_tools", "expected_network_destinations"):
            if not isinstance(component[field], list) or not all(isinstance(item, str) for item in component[field]):
                raise GuardrailsError(f"trusted component {identifier} has invalid {field}")
        for field in ("observed_tools", "executable_files"):
            if field in component and (
                not isinstance(component[field], list)
                or not all(isinstance(item, str) and item for item in component[field])
            ):
                raise GuardrailsError(f"trusted component {identifier} has invalid {field}")
        source = component["source"]
        version = component["version"]
        digest = component["digest"]
        if not isinstance(source, str) or not source:
            raise GuardrailsError(f"trusted component {identifier} has invalid source")
        mutable = re.search(r"(?:@latest\b|[?/#](?:main|master|head)\b)", source, re.IGNORECASE)
        if mutable or (isinstance(version, str) and version.lower() in {"latest", "main", "master", "head"}):
            findings.append(f"{identifier}: mutable or latest source/version")
        if kind in executable_kinds and version is None and digest is None and not source.startswith("https://app.spacelift.io/mcp"):
            findings.append(f"{identifier}: executable component is not pinned by version or digest")
        if digest is not None and (
            not isinstance(digest, str) or re.fullmatch(r"(?:sha256:)?[0-9a-f]{64}", digest) is None
        ):
            raise GuardrailsError(f"trusted component {identifier} has an invalid SHA-256 digest")
        if not source.startswith(("http://", "https://")):
            local = Path(source.removeprefix("file://"))
            if not local.is_absolute():
                local = path.parent / local
            if local.exists():
                actual = tree_hash(local) if local.is_dir() else sha256(local.read_bytes())
                if isinstance(digest, str) and actual != digest.removeprefix("sha256:"):
                    findings.append(f"{identifier}: local component digest changed")
                if kind == "skill" and local.is_dir():
                    declared = {str(item).replace("\\", "/") for item in component.get("executable_files", [])}
                    executable_suffixes = {".py", ".sh", ".ps1", ".bat", ".cmd", ".exe", ".js", ".ts", ".jar"}
                    for child in sorted(item for item in local.rglob("*") if item.is_file()):
                        relative = child.relative_to(local).as_posix()
                        if (child.suffix.lower() in executable_suffixes or child.stat().st_mode & 0o111) and relative not in declared:
                            findings.append(f"{identifier}: undeclared executable skill file {relative}")
        if "spacelift" in identifier and component["credential_class"] == "write-capable":
            findings.append(f"{identifier}: write-capable Spacelift credential scope declared")
        allowed = {str(item).lower() for item in component["allowed_tools"]}
        denied = {str(item).lower() for item in component["denied_tools"]}
        if allowed & denied:
            findings.append(f"{identifier}: tools appear in both allowed and denied sets")
        observed = {str(item).lower() for item in component.get("observed_tools", [])}
        unexpected = sorted(observed - allowed - denied)
        if unexpected:
            findings.append(f"{identifier}: unexpected expanded tool surface: {', '.join(unexpected)}")
        if "spacelift" in identifier and allowed & {"mutate", "intent"}:
            findings.append(f"{identifier}: write-capable Spacelift MCP tool allowed")
    return findings


def validate_canonical_data() -> None:
    documents = {relative: read_json(RESOURCE_ROOT / relative, default=None) for relative in CANONICAL_JSON_FILES}
    for relative, value in documents.items():
        if not isinstance(value, Mapping):
            raise GuardrailsError(f"canonical JSON must contain an object: {relative}")

    safety = documents["config/safety-profiles.json"]
    expected_safety = {
        "development",
        "infrastructure-observe",
        "infrastructure-nonprod",
        "infrastructure-strict",
    }
    profiles = safety.get("profiles")
    if not isinstance(profiles, Mapping) or set(profiles) != expected_safety:
        raise GuardrailsError("safety profiles must define exactly the supported profile identifiers")
    for identifier, value in profiles.items():
        if not isinstance(value, Mapping) or any(item not in OPERATION_CLASSES for item in value.get("allow", [])):
            raise GuardrailsError(f"safety profile {identifier} has invalid operation classes")

    trust = documents["trust/modes.json"].get("modes")
    if not isinstance(trust, Mapping) or set(trust) != {
        "trusted-workspace",
        "untrusted-workspace",
        "untrusted-external-input",
        "incident-observe",
    }:
        raise GuardrailsError("trust modes must define exactly the supported identifiers")

    targets = documents["config/targets.example.json"].get("classifications")
    if not isinstance(targets, Mapping):
        raise GuardrailsError("target example lacks classifications")
    for mapping_name, mapping in targets.items():
        if not isinstance(mapping, Mapping) or any(value not in {"dev", "tst", "int", "prd"} for value in mapping.values()):
            raise GuardrailsError(f"target mapping {mapping_name} contains an invalid lifecycle")

    path_classes = documents["risk/path-classification.json"].get("classifications")
    if not isinstance(path_classes, list) or not path_classes:
        raise GuardrailsError("risk path classification must not be empty")
    verification = documents["risk/verification-requirements.json"].get("requirements")
    if not isinstance(verification, list) or not verification:
        raise GuardrailsError("risk verification requirements must not be empty")
    for requirement in verification:
        if not isinstance(requirement, Mapping) or requirement.get("minimum_model_tier") not in {"economy", "balanced", "deep"}:
            raise GuardrailsError("risk verification requirement has an invalid model tier")

    audit = documents["audit/redaction-policy.json"]
    allowed = audit.get("allow_fields")
    denied = audit.get("deny_fields")
    if not isinstance(allowed, list) or not isinstance(denied, list) or set(allowed) & set(denied):
        raise GuardrailsError("audit redaction allow and deny fields are invalid")
    if not isinstance(audit.get("maximum_file_bytes"), int) or audit["maximum_file_bytes"] <= 0:
        raise GuardrailsError("audit redaction size limit is invalid")
    if not isinstance(audit.get("retained_rotations"), int) or not 1 <= audit["retained_rotations"] <= 10:
        raise GuardrailsError("audit redaction rotation count is invalid")
    if any(field in allowed for field in ("prompt", "source_code", "command", "arguments", "environment", "secret")):
        raise GuardrailsError("audit redaction policy permits sensitive content")
    runtime_redaction = read_json(RESOURCE_ROOT / "enforcement/redaction-policy.json", default={})
    patterns = runtime_redaction.get("never_log_field_patterns", []) if isinstance(runtime_redaction, Mapping) else []
    if (
        not isinstance(runtime_redaction, Mapping)
        or not isinstance(patterns, list)
        or not patterns
        or any(not isinstance(pattern, str) for pattern in patterns)
        or set(runtime_redaction.get("audit_value_fields", [])) != set(allowed)
        or runtime_redaction.get("maximum_file_bytes") != audit.get("maximum_file_bytes")
        or runtime_redaction.get("retained_rotations") != audit.get("retained_rotations")
    ):
        raise GuardrailsError("runtime and audit redaction policies are inconsistent")

    registry = RESOURCE_ROOT / "supply-chain/trusted-components.example.json"
    findings = supply_chain_findings(registry)
    if findings:
        raise GuardrailsError(f"trusted component example is unsafe: {findings[0]}")

    executable_suffixes = {".py", ".sh", ".ps1", ".bat", ".cmd", ".exe"}
    for root in (SKILLS_ROOT, RESOURCE_ROOT / "packs"):
        for skill_file in root.rglob("skills/*/SKILL.md") if root.name == "packs" else root.glob("*/SKILL.md"):
            for sibling in skill_file.parent.rglob("*"):
                if sibling.is_file() and sibling != skill_file and (
                    sibling.suffix.lower() in executable_suffixes or sibling.stat().st_mode & 0o111
                ):
                    raise GuardrailsError(f"undeclared executable content in portable skill: {canonical_relative(sibling)}")
