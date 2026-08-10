"""Data-driven capability-pack discovery and validation."""

from __future__ import annotations

import fnmatch
import json
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

from .resources import RESOURCE_ROOT
from .util import (
    CAPABILITY_TIERS,
    LIFECYCLES,
    OPERATION_CLASSES,
    REASONING_LEVELS,
    GuardrailsError,
    path_within,
)


PACKS_ROOT = RESOURCE_ROOT / "packs"
PACK_TYPES = ("language", "infrastructure", "delivery", "operations", "shared")
DEFAULT_IGNORED_DIRECTORIES = frozenset(
    {
        ".ansible",
        ".git",
        ".gradle",
        ".idea",
        ".mypy_cache",
        ".next",
        ".nox",
        ".pytest_cache",
        ".ruff_cache",
        ".terraform",
        ".tox",
        ".venv",
        ".yarn/cache",
        "__pycache__",
        "bin",
        "build",
        "coverage",
        "collections/ansible_collections",
        "dist",
        "generated",
        "node_modules",
        "obj",
        "out",
        "target",
        "tests/fixtures",
        "vendor",
        "vendored",
    }
)
PACK_ID_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
SENSITIVE_KEY_RE = re.compile(
    r"(?:password|passwd|secret|token|credential|private[_-]?key|api[_-]?key)", re.IGNORECASE
)


class PackError(GuardrailsError):
    """Invalid pack configuration or repository override."""


@dataclass(frozen=True)
class Evidence:
    pack_id: str
    path: str
    detector: str
    kind: str


@dataclass(frozen=True)
class DetectionResult:
    repo: Path
    active_packs: tuple[str, ...]
    evidence: tuple[Evidence, ...]
    disabled_packs: tuple[str, ...]
    warnings: tuple[str, ...]
    package_manager: str | None
    build_root: str | None

    def as_dict(self) -> dict[str, Any]:
        return {
            "repo": str(self.repo),
            "active_packs": list(self.active_packs),
            "evidence": [item.__dict__ for item in self.evidence],
            "disabled_packs": list(self.disabled_packs),
            "warnings": list(self.warnings),
            "package_manager": self.package_manager,
            "build_root": self.build_root,
        }


def _read_json(path: Path) -> Any:
    if path.is_symlink():
        raise PackError(f"refusing to read JSON through symbolic link: {path}")
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise PackError(f"cannot parse JSON file {path}: {exc}") from exc


def discover_pack_files(packs_root: Path = PACKS_ROOT) -> list[Path]:
    files = sorted(packs_root.glob("*/*/pack.json"), key=lambda path: path.as_posix())
    if not files:
        raise PackError(f"no capability packs found under {packs_root}")
    return files


def load_pack(pack_file: Path) -> dict[str, Any]:
    data = _read_json(pack_file)
    if not isinstance(data, dict) or data.get("schema_version") != 1:
        raise PackError(f"unsupported pack schema: {pack_file}")
    required = {
        "id",
        "type",
        "description",
        "file_detectors",
        "directory_detectors",
        "explicit_exclusions",
        "dependent_packs",
        "conflicting_packs",
        "policy_fragments",
        "skills",
        "command_policy_fragments",
        "verification_definitions",
        "routing_additions",
        "compatibility_notes",
    }
    missing = required - data.keys()
    if missing:
        raise PackError(f"pack {pack_file} is missing field: {sorted(missing)[0]}")
    data.setdefault("structured_tool_policy_fragments", [])
    data.setdefault("dependency_manifests", [])
    data.setdefault("dependency_lockfiles", [])
    identifier = data["id"]
    if not isinstance(identifier, str) or not PACK_ID_RE.fullmatch(identifier):
        raise PackError(f"pack has invalid identifier: {pack_file}")
    if pack_file.parent.name != identifier:
        raise PackError(f"pack identifier does not match directory: {pack_file}")
    if data["type"] not in PACK_TYPES:
        raise PackError(f"pack {identifier} has unknown type")
    declared_tier = data.get("catalogue_tier")
    if declared_tier is not None and declared_tier not in {"contextual", "specialist"}:
        raise PackError(f"pack {identifier} has invalid catalogue_tier")
    if not isinstance(data["description"], str) or not data["description"].strip():
        raise PackError(f"pack {identifier} has invalid description")
    list_fields = (
        "file_detectors",
        "directory_detectors",
        "explicit_exclusions",
        "dependent_packs",
        "conflicting_packs",
        "policy_fragments",
        "skills",
        "command_policy_fragments",
        "structured_tool_policy_fragments",
        "verification_definitions",
        "routing_additions",
        "compatibility_notes",
        "dependency_manifests",
        "dependency_lockfiles",
    )
    for field in list_fields:
        value = data[field]
        if not isinstance(value, list) or not all(isinstance(item, str) and item for item in value):
            raise PackError(f"pack {identifier} has invalid {field}")
    if not data["file_detectors"] and not data["directory_detectors"] and data["type"] != "shared":
        raise PackError(f"pack {identifier} lacks detection markers")
    for field in ("dependency_manifests", "dependency_lockfiles"):
        unknown = sorted(set(data[field]) - set(data["file_detectors"]))
        if unknown:
            raise PackError(f"pack {identifier} {field} references unknown file detector: {unknown[0]}")
    root = pack_file.parent.resolve(strict=False)
    references = (
        *data["policy_fragments"],
        *data["skills"],
        *data["command_policy_fragments"],
        *data["structured_tool_policy_fragments"],
        *data["verification_definitions"],
        *data["routing_additions"],
    )
    for relative_text in references:
        relative = Path(relative_text)
        target = pack_file.parent / relative
        if relative.is_absolute() or not path_within(target, root):
            raise PackError(f"pack {identifier} references unsafe path: {relative_text}")
        if not target.is_file():
            raise PackError(f"pack {identifier} references missing file: {relative_text}")
    return data


def catalogue_tier(pack: Mapping[str, Any]) -> str:
    """Map existing canonical pack types to their skill-catalogue role."""
    declared = pack.get("catalogue_tier")
    if declared in {"contextual", "specialist"}:
        return str(declared)
    return "contextual" if pack.get("type") in {"language", "shared"} else "specialist"


def default_pack_ids(available: Mapping[str, Mapping[str, Any]] | None = None) -> tuple[str, ...]:
    """Keep the complete stable deterministic capability policy enabled."""
    selected = available or load_packs()
    return tuple(sorted(selected))


def default_skill_pack_ids(available: Mapping[str, Mapping[str, Any]] | None = None) -> tuple[str, ...]:
    """Expose ordinary development skills without every specialist skill."""
    selected = available or load_packs()
    return tuple(sorted(identifier for identifier, pack in selected.items() if catalogue_tier(pack) == "contextual"))


def dependency_file_patterns(
    available: Mapping[str, Mapping[str, Any]] | None = None,
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """Return dependency classifications owned by existing capability packs."""
    selected = available or load_packs()
    manifests = {
        str(pattern)
        for pack in selected.values()
        for pattern in pack.get("dependency_manifests", [])
    }
    lockfiles = {
        str(pattern)
        for pack in selected.values()
        for pattern in pack.get("dependency_lockfiles", [])
    }
    return tuple(sorted(manifests)), tuple(sorted(lockfiles))


def load_packs(packs_root: Path = PACKS_ROOT) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for pack_file in discover_pack_files(packs_root):
        pack = load_pack(pack_file)
        identifier = str(pack["id"])
        if identifier in result:
            raise PackError(f"duplicate pack identifier: {identifier}")
        pack["_root"] = str(pack_file.parent)
        result[identifier] = pack
    identifiers = set(result)
    for identifier, pack in result.items():
        for relation in ("dependent_packs", "conflicting_packs"):
            unknown = sorted(set(pack[relation]) - identifiers)
            if unknown:
                raise PackError(f"pack {identifier} references unknown {relation}: {unknown[0]}")
        if identifier in pack["dependent_packs"] or identifier in pack["conflicting_packs"]:
            raise PackError(f"pack {identifier} cannot depend on or conflict with itself")
    return result


def _validate_override_value(value: Any, path: str = "") -> None:
    if isinstance(value, Mapping):
        for key, child in value.items():
            if not isinstance(key, str):
                raise PackError("repository override keys must be strings")
            if SENSITIVE_KEY_RE.search(key):
                raise PackError(f"repository override must not contain sensitive field: {path}{key}")
            _validate_override_value(child, f"{path}{key}.")
    elif isinstance(value, list):
        for child in value:
            _validate_override_value(child, path)


def load_repository_override(repo: Path) -> dict[str, Any]:
    path = repo / ".ai-guardrails.json"
    if not path.exists():
        return {}
    if path.is_symlink():
        raise PackError("repository override must not be a symbolic link")
    data = _read_json(path)
    if not isinstance(data, dict):
        raise PackError(f"repository override must be a JSON object: {path}")
    _validate_override_value(data)
    allowed = {
        "schema_version",
        "enable_packs",
        "disable_packs",
        "package_manager",
        "build_root",
        "generated_directories",
        "ambiguity_overrides",
        "target_classifications",
    }
    unknown = sorted(set(data) - allowed)
    if unknown:
        raise PackError(f"repository override has unknown field: {unknown[0]}")
    if data.get("schema_version", 1) != 1:
        raise PackError("repository override has unsupported schema_version")
    for field in ("enable_packs", "disable_packs", "generated_directories"):
        value = data.get(field, [])
        if not isinstance(value, list) or not all(isinstance(item, str) and item for item in value):
            raise PackError(f"repository override has invalid {field}")
    for relative_text in data.get("generated_directories", []):
        relative = Path(relative_text)
        if relative.is_absolute() or ".." in relative.parts:
            raise PackError("generated_directories must stay within the repository")
    build_root = data.get("build_root")
    if build_root is not None and (
        not isinstance(build_root, str) or Path(build_root).is_absolute() or ".." in Path(build_root).parts
    ):
        raise PackError("build_root must be a repository-relative path")
    configured_manager = data.get("package_manager")
    if configured_manager is not None and configured_manager not in {"npm", "pnpm", "yarn"}:
        raise PackError("package_manager must be npm, pnpm, or yarn")
    classifications = data.get("target_classifications", {})
    if not isinstance(classifications, dict):
        raise PackError("repository override target_classifications must be an object")
    for surface, targets in classifications.items():
        if not isinstance(surface, str) or not isinstance(targets, dict):
            raise PackError("repository target classifications are invalid")
        if any(value not in LIFECYCLES for value in targets.values()):
            raise PackError("repository target classifications must use dev, tst, int, or prd")
    return data


def _ignored(relative: Path, generated: Sequence[str]) -> bool:
    text = relative.as_posix()
    parts = relative.parts
    for ignored in DEFAULT_IGNORED_DIRECTORIES:
        ignored_parts = Path(ignored).parts
        if any(parts[index : index + len(ignored_parts)] == ignored_parts for index in range(len(parts))):
            return True
    return any(text == item.rstrip("/") or text.startswith(item.rstrip("/") + "/") for item in generated)


def _walk_markers(repo: Path, generated: Sequence[str]) -> tuple[list[str], list[str]]:
    files: list[str] = []
    directories: list[str] = []
    for current, names, filenames in os.walk(repo, followlinks=False):
        current_path = Path(current)
        relative_dir = current_path.relative_to(repo)
        names[:] = sorted(
            name
            for name in names
            if not (current_path / name).is_symlink() and not _ignored(relative_dir / name, generated)
        )
        directories.extend((relative_dir / name).as_posix() for name in names)
        for name in sorted(filenames):
            relative = relative_dir / name
            if not (current_path / name).is_symlink() and not _ignored(relative, generated):
                files.append(relative.as_posix())
    return files, directories


def matches_detector(value: str, pattern: str) -> bool:
    return fnmatch.fnmatchcase(value, pattern) or fnmatch.fnmatchcase(Path(value).name, pattern)


def _dependent_closure(active: set[str], packs: Mapping[str, Mapping[str, Any]], evidence: list[Evidence]) -> None:
    pending = list(sorted(active))
    while pending:
        identifier = pending.pop(0)
        for dependency in packs[identifier]["dependent_packs"]:
            if dependency not in active:
                active.add(dependency)
                evidence.append(Evidence(dependency, identifier, "dependent_packs", "dependency"))
                pending.append(dependency)


def select_java_tool(repo: Path, build_root: str | None = None) -> str | None:
    root = repo / build_root if build_root else repo
    if (root / "mvnw").is_file():
        return "./mvnw"
    if (root / "mvnw.cmd").is_file():
        return "mvnw.cmd"
    if (root / "gradlew").is_file():
        return "./gradlew"
    if (root / "gradlew.bat").is_file():
        return "gradlew.bat"
    if (root / "pom.xml").is_file():
        return "mvn"
    gradle_markers = ("build.gradle", "build.gradle.kts", "settings.gradle", "settings.gradle.kts")
    return "gradle" if any((root / name).is_file() for name in gradle_markers) else None


def select_node_package_manager(
    repo: Path, override: Mapping[str, Any], files: Sequence[str]
) -> tuple[str | None, list[str]]:
    warnings: list[str] = []
    declared: list[str] = []
    for relative in sorted(path for path in files if Path(path).name == "package.json"):
        data = _read_json(repo / relative)
        value = data.get("packageManager") if isinstance(data, Mapping) else None
        if isinstance(value, str) and value:
            manager = value.split("@", 1)[0].lower()
            if manager in {"npm", "pnpm", "yarn"}:
                declared.append(manager)
    if declared:
        unique = sorted(set(declared))
        if len(unique) > 1:
            warnings.append(f"conflicting packageManager declarations: {', '.join(unique)}")
            return None, warnings
        return unique[0], warnings
    configured = override.get("package_manager")
    if isinstance(configured, str) and configured in {"npm", "pnpm", "yarn"}:
        return configured, warnings
    lock_evidence: set[str] = set()
    for path in files:
        name = Path(path).name
        if name in {"package-lock.json", "npm-shrinkwrap.json"}:
            lock_evidence.add("npm")
        elif name in {"pnpm-lock.yaml", "pnpm-workspace.yaml"}:
            lock_evidence.add("pnpm")
        elif name in {"yarn.lock", ".yarnrc.yml"}:
            lock_evidence.add("yarn")
    if len(lock_evidence) == 1:
        return next(iter(lock_evidence)), warnings
    ambiguity = override.get("ambiguity_overrides", {})
    explicit = ambiguity.get("package_manager") if isinstance(ambiguity, Mapping) else None
    if isinstance(explicit, str) and explicit in {"npm", "pnpm", "yarn"}:
        return explicit, warnings
    if len(lock_evidence) > 1:
        warnings.append(f"ambiguous Node package-manager lockfiles: {', '.join(sorted(lock_evidence))}")
    return None, warnings


def detect_packs(repo: Path, packs_root: Path = PACKS_ROOT) -> DetectionResult:
    try:
        resolved = repo.expanduser().resolve(strict=True)
    except OSError as exc:
        raise PackError(f"repository path cannot be resolved: {repo}: {exc}") from exc
    if not resolved.is_dir():
        raise PackError(f"repository path is not a directory: {resolved}")
    packs = load_packs(packs_root)
    override = load_repository_override(resolved)
    files, directories = _walk_markers(resolved, list(override.get("generated_directories", [])))
    evidence: list[Evidence] = []
    active: set[str] = set()
    disabled = set(override.get("disable_packs", []))
    enabled = set(override.get("enable_packs", []))
    unknown_overrides = sorted((disabled | enabled) - set(packs))
    if unknown_overrides:
        raise PackError(f"repository override references unknown pack: {unknown_overrides[0]}")
    for identifier, pack in packs.items():
        # Cross-cutting shared packs without markers are dependency-only. Shared
        # packs with explicit build/config markers remain independently detectable.
        if pack["type"] == "shared" and not pack["file_detectors"] and not pack["directory_detectors"]:
            continue
        exclusions = tuple(pack["explicit_exclusions"])
        for pattern in pack["file_detectors"]:
            for path in files:
                if matches_detector(path, pattern) and not any(matches_detector(path, exclusion) for exclusion in exclusions):
                    active.add(identifier)
                    evidence.append(Evidence(identifier, path, pattern, "file"))
        for pattern in pack["directory_detectors"]:
            for path in directories:
                if matches_detector(path, pattern) and not any(matches_detector(path, exclusion) for exclusion in exclusions):
                    active.add(identifier)
                    evidence.append(Evidence(identifier, path, pattern, "directory"))
    for identifier in sorted(enabled):
        active.add(identifier)
        evidence.append(Evidence(identifier, ".ai-guardrails.json", "enable_packs", "override"))
    active -= disabled
    evidence = [item for item in evidence if item.pack_id not in disabled]
    _dependent_closure(active, packs, evidence)
    active -= disabled
    warnings: list[str] = []
    for identifier in sorted(active):
        conflicts = sorted(set(packs[identifier]["conflicting_packs"]) & active)
        if conflicts:
            warnings.append(f"{identifier} conflicts with {', '.join(conflicts)}")
    package_manager, manager_warnings = select_node_package_manager(resolved, override, files)
    warnings.extend(manager_warnings)
    evidence.sort(key=lambda item: (item.pack_id, item.path, item.kind, item.detector))
    return DetectionResult(
        repo=resolved,
        active_packs=tuple(sorted(active)),
        evidence=tuple(evidence),
        disabled_packs=tuple(sorted(disabled)),
        warnings=tuple(sorted(set(warnings))),
        package_manager=package_manager,
        build_root=override.get("build_root") if isinstance(override.get("build_root"), str) else None,
    )


def _load_json_object(path: Path, label: str) -> dict[str, Any]:
    data = _read_json(path)
    if not isinstance(data, dict):
        raise PackError(f"{label} must be a JSON object: {path}")
    return data


def _validate_policy_rule(rule: Any, identifier: str) -> int:
    required = {
        "id",
        "description",
        "risk_category",
        "operation_class",
        "reason",
        "matching_strategy",
        "must_match",
        "must_not_match",
    }
    if not isinstance(rule, dict) or required - rule.keys():
        raise PackError(f"pack {identifier} has invalid command rule")
    if rule.get("operation_class") not in OPERATION_CLASSES:
        raise PackError(f"pack {identifier} has invalid command operation class")
    if any(not isinstance(rule[field], str) or not rule[field].strip() for field in ("id", "description", "risk_category", "reason")):
        raise PackError(f"pack {identifier} command rule has invalid descriptive fields")
    strategy = rule["matching_strategy"]
    if not isinstance(strategy, dict) or not isinstance(strategy.get("type"), str):
        raise PackError(f"pack {identifier} command rule has invalid matching strategy")
    if rule.get("rollout_mode", "deny") not in {"disabled", "observe", "warn", "deny"}:
        raise PackError(f"pack {identifier} has invalid rollout mode")
    examples = 0
    for field in ("must_match", "must_not_match"):
        if not isinstance(rule.get(field), list) or not rule[field]:
            raise PackError(f"pack {identifier} command rule lacks {field}")
        if not all(isinstance(value, str) and value for value in rule[field]):
            raise PackError(f"pack {identifier} command rule has invalid {field}")
        examples += len(rule[field])
    return examples


def _validate_structured_rule(rule: Any, identifier: str) -> int:
    required = {
        "id",
        "provider_patterns",
        "tool_patterns",
        "operation_class",
        "target_fields",
        "never_log_fields",
        "reason",
        "positive_fixtures",
        "negative_fixtures",
    }
    if not isinstance(rule, dict) or required - rule.keys():
        raise PackError(f"pack {identifier} has invalid structured-tool rule")
    if rule["operation_class"] not in OPERATION_CLASSES:
        raise PackError(f"pack {identifier} structured-tool rule has invalid operation class")
    if rule.get("rollout_mode", "deny") not in {"disabled", "observe", "warn", "deny"}:
        raise PackError(f"pack {identifier} structured-tool rule has invalid rollout mode")
    for field in ("positive_fixtures", "negative_fixtures"):
        if not isinstance(rule[field], list):
            raise PackError(f"pack {identifier} structured-tool rule has invalid {field}")
    return len(rule["positive_fixtures"]) + len(rule["negative_fixtures"])


def _validate_verification_definition(value: dict[str, Any], identifier: str) -> None:
    checks = value.get("checks")
    if value.get("schema_version") != 1 or not isinstance(checks, list) or not checks:
        raise PackError(f"pack {identifier} has invalid verification definition")
    identifiers: set[str] = set()
    for check in checks:
        if not isinstance(check, Mapping) or {"id", "class", "selection", "commands"} - check.keys():
            raise PackError(f"pack {identifier} has invalid verification check")
        check_id = check["id"]
        if not isinstance(check_id, str) or not PACK_ID_RE.fullmatch(check_id) or check_id in identifiers:
            raise PackError(f"pack {identifier} has duplicate or invalid verification check")
        identifiers.add(check_id)
        if not all(isinstance(check[field], str) and check[field] for field in ("class", "selection")):
            raise PackError(f"pack {identifier} has invalid verification check metadata")
        commands = check["commands"]
        if (
            not isinstance(commands, list)
            or not commands
            or not all(isinstance(command, str) and command.strip() for command in commands)
        ):
            raise PackError(f"pack {identifier} has invalid verification commands")


def _validate_routing_addition(value: dict[str, Any], identifier: str) -> None:
    task_classes = value.get("task_classes")
    if value.get("schema_version") != 1 or not isinstance(task_classes, list) or not task_classes:
        raise PackError(f"pack {identifier} has invalid routing addition")
    identifiers: set[str] = set()
    for task in task_classes:
        if not isinstance(task, Mapping) or {"id", "tier", "reasoning", "write"} - task.keys():
            raise PackError(f"pack {identifier} has invalid routing task")
        task_id = task["id"]
        if not isinstance(task_id, str) or not PACK_ID_RE.fullmatch(task_id) or task_id in identifiers:
            raise PackError(f"pack {identifier} has duplicate or invalid routing task")
        identifiers.add(task_id)
        if (
            task["tier"] not in CAPABILITY_TIERS
            or task["reasoning"] not in REASONING_LEVELS
            or not isinstance(task["write"], bool)
        ):
            raise PackError(f"pack {identifier} has invalid routing task metadata")


def pack_guidance(pack: Mapping[str, Any]) -> dict[str, list[str]]:
    """Return concise, data-derived details for the existing ``packs explain`` command."""
    root = Path(str(pack["_root"]))
    policies: list[str] = []
    for relative in pack["policy_fragments"]:
        source = root / relative
        title = next(
            (
                line.removeprefix("# ").strip()
                for line in source.read_text(encoding="utf-8").splitlines()
                if line.startswith("# ")
            ),
            "policy guidance",
        )
        policies.append(f"{relative}: {title}")

    verification: list[str] = []
    for relative in pack["verification_definitions"]:
        data = _load_json_object(root / relative, "verification definition")
        for check in data["checks"]:
            verification.append(f"{check['id']} ({check['class']}; {check['selection']})")

    routing: list[str] = []
    for relative in pack["routing_additions"]:
        data = _load_json_object(root / relative, "routing addition")
        for task in data["task_classes"]:
            capability = "write" if task["write"] else "read-only"
            routing.append(f"{task['id']} -> {task['tier']}/{task['reasoning']} ({capability})")
    return {"policy": policies, "verification": verification, "routing": routing}


def validate_packs(packs_root: Path = PACKS_ROOT) -> tuple[int, int]:
    packs = load_packs(packs_root)
    skill_names = {
        skill_file.parent.name
        for skill_file in (RESOURCE_ROOT / "skills").glob("*/SKILL.md")
    }
    examples = 0
    for identifier, pack in packs.items():
        root = Path(pack["_root"])
        for source in root.rglob("*"):
            if source.is_symlink():
                raise PackError(f"pack {identifier} contains a symbolic link: {source}")
            if not source.is_file():
                continue
            text = source.read_text(encoding="utf-8")
            if str(Path.home()) in text or str(RESOURCE_ROOT) in text:
                raise PackError(f"pack {identifier} contains a machine-specific path: {source}")
        for relative in pack["policy_fragments"]:
            if not (root / relative).read_text(encoding="utf-8").strip():
                raise PackError(f"pack {identifier} has empty policy")
        for relative in pack["verification_definitions"]:
            verification = _load_json_object(root / relative, "verification definition")
            _validate_verification_definition(verification, identifier)
        for relative in pack["routing_additions"]:
            routing = _load_json_object(root / relative, "routing addition")
            _validate_routing_addition(routing, identifier)
        for relative in pack["command_policy_fragments"]:
            command = _load_json_object(root / relative, "command-policy fragment")
            if command.get("schema_version") != 1 or not isinstance(command.get("rules"), list):
                raise PackError(f"pack {identifier} has invalid command-policy fragment")
            examples += sum(_validate_policy_rule(rule, identifier) for rule in command["rules"])
            examples += sum(
                _validate_structured_rule(rule, identifier) for rule in command.get("structured_tool_rules", [])
            )
        for relative in pack["structured_tool_policy_fragments"]:
            structured = _load_json_object(root / relative, "structured-tool-policy fragment")
            if structured.get("schema_version") != 1 or not isinstance(structured.get("rules"), list):
                raise PackError(f"pack {identifier} has invalid structured-tool policy")
            examples += sum(_validate_structured_rule(rule, identifier) for rule in structured["rules"])
        for skill_relative in pack["skills"]:
            skill_file = root / skill_relative
            text = skill_file.read_text(encoding="utf-8")
            if not text.startswith("---\n"):
                raise PackError(f"pack skill lacks frontmatter: {skill_file}")
            frontmatter = text.split("---\n", 2)[1]
            fields = {
                key.strip(): value.strip()
                for line in frontmatter.splitlines()
                if ":" in line
                for key, value in [line.split(":", 1)]
            }
            if set(fields) != {"name", "description"}:
                raise PackError(f"pack skill has unsupported frontmatter: {skill_file}")
            if fields["name"] != skill_file.parent.name or fields["name"] in skill_names:
                raise PackError(f"pack skill name is duplicate or mismatched: {skill_file}")
            skill_names.add(fields["name"])
    return len(packs), examples


def pack_skill_files(pack: Mapping[str, Any]) -> list[Path]:
    root = Path(str(pack["_root"]))
    return [root / item for item in pack["skills"]]


def selected_pack_closure(selected: Iterable[str], packs: Mapping[str, Mapping[str, Any]]) -> tuple[str, ...]:
    active = set(selected)
    unknown = sorted(active - set(packs))
    if unknown:
        raise PackError(f"unknown capability pack: {unknown[0]}")
    evidence: list[Evidence] = []
    _dependent_closure(active, packs, evidence)
    return tuple(sorted(active))
