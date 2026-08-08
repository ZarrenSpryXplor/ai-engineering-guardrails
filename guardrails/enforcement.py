#!/usr/bin/env python3
"""Standalone deterministic hook runtime.

This file deliberately imports only the Python standard library so an immutable
copy can run independently of the repository clone. Payload content is treated as
data and is never executed.
"""

from __future__ import annotations

import argparse
import copy
import datetime as dt
import fnmatch
import hashlib
import json
import os
import re
import shlex
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence


POLICY_PATH = Path(__file__).with_name("command-policy.json")
STRUCTURED_POLICY_PATH = Path(__file__).with_name("structured-tool-policy.json")
METADATA_PATH = Path(__file__).with_name("metadata.json")
OPERATION_CLASSES = {
    "observe",
    "validate",
    "mutate",
    "destructive",
    "sensitive-read",
    "publish",
    "privilege-escalation",
    "guardrail-modification",
}
ROLLOUT_MODES = {"disabled", "observe", "warn", "deny"}
SHELL_TOOLS = {
    "bash",
    "shell",
    "sh",
    "zsh",
    "powershell",
    "pwsh",
    "cmd",
    "exec_command",
    "execute",
    "run_terminal_cmd",
    "terminal",
}
FILE_WRITE_TOOLS = {"write", "edit", "apply_patch", "write_file", "edit_file", "notebookedit"}
CHAIN_OPERATORS = {"&&", "||", ";", "&", "|"}
ASSIGNMENT_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=.*$", re.DOTALL)
DRIVE_ROOT_RE = re.compile(r"^[A-Za-z]:[\\/]*$")
GRAPHQL_MUTATION_RE = re.compile(
    r"(?:^|[\s{])mutation(?:\s+[A-Za-z_][A-Za-z0-9_]*)?\s*[({]", re.IGNORECASE
)
ISO_Z = "%Y-%m-%dT%H:%M:%SZ"
AUDIT_MAX_BYTES = 1_048_576
AUDIT_ROTATIONS = 3
AUDIT_FIELDS = (
    "timestamp",
    "product",
    "session_id_hash",
    "event_type",
    "tool_category",
    "rule_id",
    "decision",
    "operation_class",
    "target_lifecycle",
    "request_digest",
    "waiver_id",
    "policy_digest",
)
WAIVER_FIELDS = {
    "id",
    "rule_id",
    "repository_scope",
    "target_scope",
    "command_tool_call_digest",
    "reason",
    "change_reference",
    "created_by",
    "created_at",
    "expires_at",
    "maximum_uses",
    "remaining_uses",
}


class PolicyError(ValueError):
    """Invalid deterministic policy or runtime metadata."""


@dataclass(frozen=True)
class ParsedScript:
    commands: tuple[tuple[str, ...], ...]
    operators: tuple[str, ...]


@dataclass(frozen=True)
class Decision:
    decision: str
    rollout_mode: str
    rule_id: str | None
    operation_class: str | None
    reason: str | None
    policy_source: str | None
    matched_tokens: tuple[str, ...]
    matched_fields: tuple[str, ...]
    target: str | None
    target_lifecycle: str | None
    waiver_id: str | None
    safety_profile: str
    trust_mode: str
    request_digest: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "decision": self.decision,
            "rollout_mode": self.rollout_mode,
            "rule_id": self.rule_id,
            "operation_class": self.operation_class,
            "matched_tokens": list(self.matched_tokens),
            "matched_fields": list(self.matched_fields),
            "target": self.target,
            "target_lifecycle": self.target_lifecycle or "protected-unknown",
            "policy_source": self.policy_source,
            "reason": self.reason,
            "applicable_waiver": self.waiver_id,
            "safety_profile": self.safety_profile,
            "trust_mode": self.trust_mode,
            "request_digest": self.request_digest,
        }


def _diagnostic(message: str) -> None:
    # Never include payload values, command text, or arguments here.
    print(f"workstation guardrails: {message}", file=sys.stderr)


def _read_json(path: Path, default: Any | None = None) -> Any:
    if path.is_symlink():
        raise PolicyError("refusing policy data through a symbolic link")
    if not path.exists() and default is not None:
        return copy.deepcopy(default)
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise PolicyError(f"cannot load policy data ({exc.__class__.__name__})") from exc


def _validate_rule(rule: Any, seen: set[str], *, structured: bool) -> dict[str, Any]:
    if not isinstance(rule, dict):
        raise PolicyError("policy rule must be an object")
    identifier = rule.get("id")
    if not isinstance(identifier, str) or not identifier or identifier in seen:
        raise PolicyError("policy rule identifiers must be unique strings")
    seen.add(identifier)
    operation = rule.get("operation_class", "destructive")
    if operation not in OPERATION_CLASSES:
        raise PolicyError(f"rule {identifier} has an invalid operation class")
    mode = rule.get("rollout_mode", "deny")
    if mode not in ROLLOUT_MODES:
        raise PolicyError(f"rule {identifier} has an invalid rollout mode")
    if not isinstance(rule.get("reason"), str) or not rule["reason"].strip():
        raise PolicyError(f"rule {identifier} has an invalid reason")
    if structured:
        required = {
            "provider_patterns",
            "tool_patterns",
            "target_fields",
            "never_log_fields",
            "positive_fixtures",
            "negative_fixtures",
        }
        if required - rule.keys() or any(not isinstance(rule[field], list) for field in required):
            raise PolicyError(f"structured-tool rule {identifier} is invalid")
    else:
        required = {"matching_strategy", "must_match", "must_not_match"}
        if required - rule.keys():
            raise PolicyError(f"command rule {identifier} is missing required fields")
        strategy = rule["matching_strategy"]
        if not isinstance(strategy, dict) or not isinstance(strategy.get("type"), str):
            raise PolicyError(f"rule {identifier} has an invalid matching strategy")
        for field in ("must_match", "must_not_match"):
            if not isinstance(rule[field], list) or not all(isinstance(value, str) and value for value in rule[field]):
                raise PolicyError(f"rule {identifier} has invalid {field} examples")
    result = copy.deepcopy(rule)
    result["operation_class"] = operation
    result["rollout_mode"] = mode
    return result


def validate_policy_data(raw: Any) -> dict[str, Any]:
    if not isinstance(raw, dict) or raw.get("schema_version") != 1:
        raise PolicyError("unsupported policy schema")
    rules = raw.get("rules")
    if not isinstance(rules, list):
        raise PolicyError("command policy rules must be a list")
    classifications = raw.get("classifications", [])
    structured = raw.get("structured_tool_rules", [])
    if not isinstance(classifications, list) or not isinstance(structured, list):
        raise PolicyError("policy classifications and structured rules must be lists")
    seen: set[str] = set()
    validated_rules = [_validate_rule(rule, seen, structured=False) for rule in rules]
    validated_classifications: list[dict[str, Any]] = []
    for entry in classifications:
        if not isinstance(entry, dict) or not isinstance(entry.get("id"), str):
            raise PolicyError("operation classification is invalid")
        if entry["id"] in seen:
            raise PolicyError(f"duplicate policy identifier: {entry['id']}")
        seen.add(entry["id"])
        if entry.get("operation_class") not in OPERATION_CLASSES:
            raise PolicyError(f"classification {entry['id']} has an invalid operation class")
        strategy = entry.get("matching_strategy")
        if not isinstance(strategy, dict) or not isinstance(strategy.get("type"), str):
            raise PolicyError(f"classification {entry['id']} has an invalid matching strategy")
        validated_classifications.append(copy.deepcopy(entry))
    validated_structured = [_validate_rule(rule, seen, structured=True) for rule in structured]
    settings = raw.get("structured_tools", {})
    return {
        "schema_version": 1,
        "rules": validated_rules,
        "classifications": validated_classifications,
        "structured_tool_rules": validated_structured,
        "structured_tools": {
            "strict_allowlist": isinstance(settings, Mapping) and settings.get("strict_allowlist") is True
        },
    }


def load_policy(path: Path = POLICY_PATH) -> dict[str, Any]:
    return validate_policy_data(_read_json(path))


def load_structured_policy(path: Path = STRUCTURED_POLICY_PATH) -> dict[str, Any]:
    raw = _read_json(path, default={"schema_version": 1, "rules": []})
    if not isinstance(raw, dict) or raw.get("schema_version") != 1 or not isinstance(raw.get("rules"), list):
        raise PolicyError("unsupported structured-tool policy schema")
    return validate_policy_data(
        {
            "schema_version": 1,
            "rules": [],
            "structured_tool_rules": raw["rules"],
            "structured_tools": raw.get("structured_tools", {}),
        }
    )


def merge_policies(policies: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    merged: dict[str, Any] = {
        "schema_version": 1,
        "rules": [],
        "classifications": [],
        "structured_tool_rules": [],
        "structured_tools": {"strict_allowlist": False},
    }
    identifiers: set[str] = set()
    for raw_policy in policies:
        active = validate_policy_data(dict(raw_policy))
        for collection in ("rules", "classifications", "structured_tool_rules"):
            for entry in active[collection]:
                if entry["id"] in identifiers:
                    raise PolicyError(f"duplicate policy identifier: {entry['id']}")
                identifiers.add(entry["id"])
                merged[collection].append(entry)
        if active["structured_tools"]["strict_allowlist"]:
            merged["structured_tools"]["strict_allowlist"] = True
    return merged


def load_installed_policy(
    command_path: Path = POLICY_PATH,
    structured_path: Path = STRUCTURED_POLICY_PATH,
) -> dict[str, Any]:
    policies = [load_policy(command_path)]
    if structured_path.is_file():
        policies.append(load_structured_policy(structured_path))
    legacy_pack_dir = command_path.with_name("packs")
    if legacy_pack_dir.is_dir():
        policies.extend(load_policy(path) for path in sorted(legacy_pack_dir.glob("*.json")))
    return merge_policies(policies)


def _lex(command: str) -> list[str]:
    try:
        lexer = shlex.shlex(command, posix=True, punctuation_chars=";&|")
        lexer.whitespace_split = True
        lexer.commenters = ""
        return list(lexer)
    except ValueError:
        try:
            return shlex.split(command, posix=False)
        except ValueError:
            return command.split()


def _split_commands(tokens: Sequence[str]) -> ParsedScript:
    commands: list[tuple[str, ...]] = []
    operators: list[str] = []
    current: list[str] = []
    for token in tokens:
        if token in CHAIN_OPERATORS:
            if current:
                commands.append(tuple(current))
                current = []
            if commands and len(operators) < len(commands):
                operators.append(token)
        else:
            current.append(token)
    if current:
        commands.append(tuple(current))
    while len(operators) >= len(commands):
        operators.pop()
    while len(operators) < max(0, len(commands) - 1):
        operators.append(";")
    return ParsedScript(tuple(commands), tuple(operators))


def _basename(token: str) -> str:
    value = token.strip('"\'').replace("\\", "/").rsplit("/", 1)[-1].lower()
    return value[:-4] if value.endswith(".exe") else value


def _strip_prefix_wrappers(tokens: Sequence[str]) -> list[str]:
    remaining = list(tokens)
    while remaining:
        while remaining and ASSIGNMENT_RE.match(remaining[0]):
            remaining.pop(0)
        if not remaining:
            return remaining
        executable = _basename(remaining[0])
        if executable == "command":
            remaining.pop(0)
            continue
        if executable == "env":
            remaining.pop(0)
            while remaining and (remaining[0].startswith("-") or ASSIGNMENT_RE.match(remaining[0])):
                remaining.pop(0)
            continue
        if executable == "sudo":
            remaining.pop(0)
            options_with_values = {"-u", "--user", "-g", "--group", "-h", "--host", "-p", "--prompt", "-C"}
            while remaining and remaining[0].startswith("-"):
                option = remaining.pop(0)
                if option in options_with_values and remaining:
                    remaining.pop(0)
            continue
        break
    return remaining


def _wrapper_payload(tokens: Sequence[str]) -> str | None:
    if not tokens:
        return None
    executable = _basename(tokens[0])
    if executable in {"bash", "sh", "zsh"}:
        for index, token in enumerate(tokens[1:], start=1):
            if token.startswith("-") and "c" in token[1:] and index + 1 < len(tokens):
                return " ".join(tokens[index + 1 :])
    if executable in {"powershell", "pwsh"}:
        for index, token in enumerate(tokens[1:], start=1):
            if token.lower() in {"-command", "-c"} and index + 1 < len(tokens):
                return " ".join(tokens[index + 1 :])
    if executable == "cmd":
        for index, token in enumerate(tokens[1:], start=1):
            if token.lower() in {"/c", "/k"} and index + 1 < len(tokens):
                return " ".join(tokens[index + 1 :])
    return None


def parse_command(command: str, depth: int = 0) -> ParsedScript:
    if depth > 4:
        return ParsedScript((), ())
    parsed = _split_commands(_lex(command))
    commands: list[tuple[str, ...]] = []
    operators: list[str] = []
    for index, raw_tokens in enumerate(parsed.commands):
        tokens = _strip_prefix_wrappers(raw_tokens)
        payload = _wrapper_payload(tokens)
        nested = parse_command(payload, depth + 1) if payload is not None else None
        replacement = nested.commands if nested and nested.commands else (tuple(tokens),)
        replacement_operators = nested.operators if nested and nested.commands else ()
        if commands and index > 0:
            operators.append(parsed.operators[index - 1])
        commands.extend(replacement)
        operators.extend(replacement_operators)
    return ParsedScript(tuple(command for command in commands if command), tuple(operators))


def _lower_tokens(tokens: Sequence[str]) -> list[str]:
    return [token.lower() for token in tokens]


def _protected_target(token: str, cwd: Path | None, home: Path | None = None) -> bool:
    value = token.strip().strip('"\'')
    normalised = value.replace("\\", "/")
    if normalised.rstrip("/") in {"", "~", "$HOME", "${HOME}", "%USERPROFILE%", "$PWD", "${PWD}", "%CD%", "."}:
        return True
    if normalised in {"./*", "$PWD/*", "${PWD}/*", "$HOME/*", "${HOME}/*", "~/*"}:
        return True
    if DRIVE_ROOT_RE.fullmatch(value):
        return True
    try:
        candidate = Path(value).expanduser()
        if candidate.is_absolute():
            resolved = candidate.resolve(strict=False)
            if resolved == Path(resolved.anchor):
                return True
            effective_home = home or Path.home()
            if resolved == effective_home.resolve(strict=False):
                return True
            if cwd is not None and resolved == cwd.resolve(strict=False):
                return True
    except (OSError, RuntimeError):
        return False
    return False


def _is_git(tokens: Sequence[str], subcommand: str) -> bool:
    return len(tokens) >= 2 and _basename(tokens[0]) == "git" and tokens[1].lower() == subcommand


def _match_git_reset_hard(script: ParsedScript, _: Mapping[str, Any], cwd: Path | None) -> bool:
    del cwd
    return any(_is_git(command, "reset") and "--hard" in _lower_tokens(command[2:]) for command in script.commands)


def _match_git_clean(script: ParsedScript, _: Mapping[str, Any], cwd: Path | None) -> bool:
    del cwd
    for command in script.commands:
        if not _is_git(command, "clean"):
            continue
        flags = _lower_tokens(command[2:])
        dry_run = any(flag in {"-n", "--dry-run"} or (flag.startswith("-") and not flag.startswith("--") and "n" in flag[1:]) for flag in flags)
        force = "--force" in flags or any(flag.startswith("-") and not flag.startswith("--") and "f" in flag[1:] for flag in flags)
        directories = "--directories" in flags or any(flag.startswith("-") and not flag.startswith("--") and "d" in flag[1:] for flag in flags)
        if force and directories and not dry_run:
            return True
    return False


def _match_git_force_push(script: ParsedScript, _: Mapping[str, Any], cwd: Path | None) -> bool:
    del cwd
    for command in script.commands:
        if _is_git(command, "push") and any(
            token.lower() in {"-f", "--force"} or token.lower().startswith("--force-with-lease")
            for token in command[2:]
        ):
            return True
    return False


def _match_recursive_delete(script: ParsedScript, _: Mapping[str, Any], cwd: Path | None) -> bool:
    for command in script.commands:
        executable = _basename(command[0])
        lowered = _lower_tokens(command[1:])
        if executable == "rm":
            recursive = "--recursive" in lowered or any(token.startswith("-") and not token.startswith("--") and "r" in token[1:] for token in lowered)
            targets = [token for token in command[1:] if not token.startswith("-")]
            if recursive and any(_protected_target(target, cwd) for target in targets):
                return True
        if executable in {"rmdir", "rd"}:
            recursive = any(token.lower() in {"/s", "-s"} for token in command[1:])
            targets = [token for token in command[1:] if not token.startswith(("/", "-")) or DRIVE_ROOT_RE.fullmatch(token)]
            if recursive and any(_protected_target(target, cwd) for target in targets):
                return True
    return False


def _match_powershell_delete(script: ParsedScript, _: Mapping[str, Any], cwd: Path | None) -> bool:
    for command in script.commands:
        if _basename(command[0]) not in {"remove-item", "ri"}:
            continue
        recursive = any(token.lower() in {"-recurse", "-r"} for token in command[1:])
        targets = [token for token in command[1:] if not token.startswith("-")]
        if recursive and any(_protected_target(target, cwd) for target in targets):
            return True
    return False


def _match_subcommand(script: ParsedScript, strategy: Mapping[str, Any], cwd: Path | None) -> bool:
    del cwd
    executables = {str(item).lower() for item in strategy.get("executables", [])}
    subcommands = {str(item).lower() for item in strategy.get("subcommands", [])}
    return any(
        command and _basename(command[0]) in executables and any(token.lower() in subcommands for token in command[1:])
        for command in script.commands
    )


def _match_kubernetes_namespace(script: ParsedScript, _: Mapping[str, Any], cwd: Path | None) -> bool:
    del cwd
    for command in script.commands:
        if _basename(command[0]) != "kubectl":
            continue
        lowered = _lower_tokens(command[1:])
        if "delete" in lowered:
            index = lowered.index("delete")
            if any(token in {"namespace", "namespaces", "ns"} for token in lowered[index + 1 :]):
                return True
    return False


def _match_kubernetes_all(script: ParsedScript, _: Mapping[str, Any], cwd: Path | None) -> bool:
    del cwd
    for command in script.commands:
        lowered = _lower_tokens(command[1:])
        if _basename(command[0]) == "kubectl" and "delete" in lowered and any(
            token == "--all" or token.startswith("--all=") for token in lowered
        ):
            return True
    return False


def _match_publication(script: ParsedScript, strategy: Mapping[str, Any], cwd: Path | None) -> bool:
    del cwd
    prefixes = [tuple(str(item).lower() for item in prefix) for prefix in strategy.get("command_prefixes", [])]
    modules = {str(item).lower() for item in strategy.get("python_modules", [])}
    for command in script.commands:
        lowered = tuple([_basename(command[0]), *[token.lower() for token in command[1:]]])
        if any(lowered[: len(prefix)] == prefix for prefix in prefixes):
            return True
        if lowered[0] in {"python", "python3", "py"} and len(lowered) >= 4 and lowered[1] == "-m" and lowered[2] in modules and lowered[3] == "upload":
            return True
    return False


def _match_download_pipeline(script: ParsedScript, strategy: Mapping[str, Any], cwd: Path | None) -> bool:
    del cwd
    downloaders = {str(item).lower() for item in strategy.get("downloaders", [])}
    interpreters = {str(item).lower() for item in strategy.get("interpreters", [])}
    for index, operator in enumerate(script.operators):
        if operator == "|" and index + 1 < len(script.commands):
            left, right = script.commands[index], script.commands[index + 1]
            if _basename(left[0]) in downloaders and _basename(right[0]) in interpreters:
                return True
    return False


def _match_powershell_download(script: ParsedScript, _: Mapping[str, Any], cwd: Path | None) -> bool:
    del cwd
    downloaders = {"invoke-webrequest", "invoke-restmethod", "iwr", "irm"}
    evaluators = {"invoke-expression", "iex"}
    for index, operator in enumerate(script.operators):
        if operator == "|" and index + 1 < len(script.commands):
            left, right = script.commands[index], script.commands[index + 1]
            if _basename(left[0]) in downloaders and _basename(right[0]) in evaluators:
                return True
    return any(
        _basename(command[0]) in evaluators
        and ("downloadstring" in " ".join(command[1:]).lower() or "invoke-webrequest" in " ".join(command[1:]).lower())
        for command in script.commands
    )


def _match_database(script: ParsedScript, strategy: Mapping[str, Any], cwd: Path | None) -> bool:
    del cwd
    executables = {str(item).lower() for item in strategy.get("executables", [])}
    flags = {str(item).lower() for item in strategy.get("statement_flags", [])}
    patterns = [str(item).lower() for item in strategy.get("destructive_patterns", [])]
    predicate_patterns = [str(item) for item in strategy.get("unsafe_without_predicate_patterns", [])]
    for command in script.commands:
        if _basename(command[0]) not in executables:
            continue
        lowered = _lower_tokens(command)
        for index, token in enumerate(lowered[1:], start=1):
            statement = command[index + 1].lower() if token in flags and index + 1 < len(command) else ""
            if not statement:
                for flag in flags:
                    if token.startswith(flag + "="):
                        statement = token[len(flag) + 1 :]
                        break
            if statement:
                normalised = " ".join(statement.lower().split())
                if any(pattern in normalised for pattern in patterns):
                    return True
                try:
                    if " where " not in f" {normalised} " and any(
                        re.search(pattern, normalised, re.IGNORECASE) for pattern in predicate_patterns
                    ):
                        return True
                except re.error as exc:
                    raise PolicyError("destructive database strategy has invalid predicate pattern") from exc
    return False


def _match_command_regex(script: ParsedScript, strategy: Mapping[str, Any], cwd: Path | None) -> bool:
    del cwd
    executables = {str(item).lower() for item in strategy.get("executables", [])}
    pattern = strategy.get("pattern")
    patterns_by_executable = strategy.get("patterns_by_executable", {})
    if not executables or ((not isinstance(pattern, str) or not pattern) and not isinstance(patterns_by_executable, Mapping)):
        raise PolicyError("command_regex strategy requires executables and a pattern")
    flags = re.IGNORECASE | (re.DOTALL if "dotall" in strategy.get("flags", []) else 0)
    for command in script.commands:
        executable = _basename(command[0])
        selected = patterns_by_executable.get(executable, pattern) if isinstance(patterns_by_executable, Mapping) else pattern
        if executable in executables and isinstance(selected, str):
            try:
                if re.search(selected, " ".join(command[1:]), flags):
                    return True
            except re.error as exc:
                raise PolicyError("command_regex strategy has invalid pattern") from exc
    return False


MATCHERS = {
    "git_reset_hard": _match_git_reset_hard,
    "git_clean_force_directories": _match_git_clean,
    "git_force_push": _match_git_force_push,
    "recursive_delete_protected_root": _match_recursive_delete,
    "powershell_recursive_delete_protected_root": _match_powershell_delete,
    "subcommand": _match_subcommand,
    "kubernetes_namespace_delete": _match_kubernetes_namespace,
    "kubernetes_delete_all": _match_kubernetes_all,
    "configured_publication": _match_publication,
    "download_execute_pipeline": _match_download_pipeline,
    "powershell_download_execute": _match_powershell_download,
    "destructive_database_client": _match_database,
    "command_regex": _match_command_regex,
}


def _command_text(command: str | Sequence[str]) -> str:
    if isinstance(command, str):
        return command
    if isinstance(command, Sequence) and all(isinstance(item, str) for item in command):
        return shlex.join(command)
    raise TypeError("command must be a string or a sequence of strings")


def evaluate_command(
    command: str | Sequence[str],
    policy: Mapping[str, Any] | None = None,
    cwd: Path | None = None,
) -> Mapping[str, Any] | None:
    command_text = _command_text(command)
    if not command_text.strip():
        return None
    active = policy if policy is not None else load_installed_policy()
    script = parse_command(command_text)
    for rule in active["rules"]:
        strategy = rule["matching_strategy"]
        matcher = MATCHERS.get(strategy["type"])
        if matcher is None:
            raise PolicyError(f"unknown matching strategy in rule {rule['id']}")
        if matcher(script, strategy, cwd):
            return rule
    return None


def classify_command(
    command: str | Sequence[str],
    policy: Mapping[str, Any] | None = None,
    cwd: Path | None = None,
) -> Mapping[str, Any] | None:
    denied = evaluate_command(command, policy=policy, cwd=cwd)
    if denied is not None:
        return denied
    active = policy if policy is not None else load_installed_policy()
    script = parse_command(_command_text(command))
    for rule in active.get("classifications", []):
        strategy = rule["matching_strategy"]
        matcher = MATCHERS.get(strategy["type"])
        if matcher is None:
            raise PolicyError(f"unknown matching strategy in classification {rule['id']}")
        if matcher(script, strategy, cwd):
            return rule
    return None


def _normalise_tool_name(tool_name: str) -> tuple[str, str]:
    value = tool_name.strip()
    if value.startswith("mcp__"):
        parts = value.split("__", 2)
        return parts[1], parts[2] if len(parts) > 2 else ""
    if "__" in value:
        return tuple(value.split("__", 1))  # type: ignore[return-value]
    if "." in value:
        return tuple(value.rsplit(".", 1))  # type: ignore[return-value]
    if "/" in value:
        return tuple(value.rsplit("/", 1))  # type: ignore[return-value]
    return "", value


def _field_values(arguments: Mapping[str, Any], fields: Sequence[str]) -> list[str]:
    values: list[str] = []
    for field in fields:
        value: Any = arguments
        for component in field.split("."):
            if not isinstance(value, Mapping) or component not in value:
                value = None
                break
            value = value[component]
        if isinstance(value, str):
            values.append(value)
    return values


def _structured_conditions_match(rule: Mapping[str, Any], arguments: Mapping[str, Any]) -> bool:
    conditions = rule.get("argument_conditions")
    if isinstance(conditions, Mapping):
        operation_fields = conditions.get("operation_fields", [])
        deny_values = {str(value).lower() for value in conditions.get("deny_values", [])}
        if operation_fields:
            operations = {value.lower() for value in _field_values(arguments, operation_fields)}
            if not operations & deny_values:
                return False
        graphql_fields = conditions.get("graphql_fields", [])
        if graphql_fields:
            documents = _field_values(arguments, graphql_fields)
            if not any(GRAPHQL_MUTATION_RE.search(document) for document in documents):
                return False
    direct = rule.get("conditions")
    if isinstance(direct, Mapping):
        prefixes = direct.get("target_path_prefixes", [])
        if prefixes:
            values = _field_values(arguments, rule.get("target_fields", []))
            normalised = [value.replace("\\", "/") for value in values]
            normalised = [value[2:] if value.startswith("./") else value for value in normalised]
            if not any(
                value == str(prefix).rstrip("/") or value.startswith(str(prefix).rstrip("/") + "/")
                for value in normalised
                for prefix in prefixes
            ):
                return False
        equals = direct.get("field_equals", {})
        if isinstance(equals, Mapping):
            for field, accepted in equals.items():
                values = _field_values(arguments, [str(field)])
                accepted_values = accepted if isinstance(accepted, list) else [accepted]
                if not any(value.lower() in {str(item).lower() for item in accepted_values} for value in values):
                    return False
    return True


def evaluate_structured_tool(
    tool_name: str,
    arguments: Mapping[str, Any],
    policy: Mapping[str, Any] | None = None,
) -> Mapping[str, Any] | None:
    active = policy if policy is not None else load_installed_policy()
    provider, name = _normalise_tool_name(tool_name)
    for rule in active.get("structured_tool_rules", []):
        provider_match = any(
            fnmatch.fnmatchcase(provider.lower(), str(pattern).lower())
            for pattern in rule.get("provider_patterns", [])
        )
        tool_match = any(
            fnmatch.fnmatchcase(name.lower(), str(pattern).lower())
            for pattern in rule.get("tool_patterns", [])
        )
        if provider_match and tool_match and _structured_conditions_match(rule, arguments):
            return rule
    if active.get("structured_tools", {}).get("strict_allowlist") is True:
        return {
            "id": "structured-tool-strict-allowlist",
            "operation_class": "destructive",
            "rollout_mode": "deny",
            "policy_source": "runtime strict allowlist",
            "reason": "Unknown structured tools are denied by the configured strict allowlist.",
            "never_log_fields": list(arguments),
        }
    return None


def _mapping_value(container: Mapping[str, Any], keys: Iterable[str]) -> Any:
    for key in keys:
        if key in container:
            return container[key]
    return None


def _event_supported(payload: Mapping[str, Any]) -> bool:
    event = _mapping_value(payload, ("hook_event_name", "hookEventName", "event", "eventName"))
    return not isinstance(event, str) or event.lower() in {
        "pretooluse",
        "pre_tool_use",
        "beforeshellexecution",
        "before_shell_execution",
        "beforemcpexecution",
        "before_mcp_execution",
    }


def extract_tool(payload: Mapping[str, Any]) -> tuple[str | None, Mapping[str, Any] | None, str | None]:
    if not _event_supported(payload):
        return None, None, "unsupported hook event; allowing request"
    event = _mapping_value(payload, ("hook_event_name", "hookEventName", "event", "eventName"))
    tool_name: Any = _mapping_value(payload, ("tool_name", "toolName", "tool"))
    if isinstance(tool_name, Mapping):
        tool_name = _mapping_value(tool_name, ("name", "type"))
    if not isinstance(tool_name, str) or not tool_name:
        if isinstance(event, str) and event.lower() in {"beforeshellexecution", "before_shell_execution"}:
            tool_name = "shell"
        else:
            return None, None, "missing tool name; allowing request"
    if not any(separator in tool_name for separator in ("__", ".", "/")):
        provider_hint = _mapping_value(payload, ("mcp_server_name", "mcpServerName", "server_name", "serverName"))
        url_hint = payload.get("url")
        if isinstance(provider_hint, str):
            tool_name = f"{provider_hint}.{tool_name}"
        elif isinstance(url_hint, str) and "spacelift.io" in url_hint.lower():
            tool_name = f"spacelift.{tool_name}"
    arguments: Any = None
    for key in ("tool_input", "toolInput", "input", "arguments", "args"):
        if isinstance(payload.get(key), Mapping):
            arguments = payload[key]
            break
    return tool_name, arguments if isinstance(arguments, Mapping) else {}, None


def extract_command(payload: Mapping[str, Any]) -> tuple[str | Sequence[str] | None, Path | None, str | None]:
    if not _event_supported(payload):
        return None, None, "unsupported hook event; allowing request"
    tool_name, _, diagnostic = extract_tool(payload)
    if diagnostic:
        return None, None, diagnostic
    _, normalised = _normalise_tool_name(tool_name or "")
    if _basename(normalised) not in SHELL_TOOLS:
        return None, None, "unsupported tool type; allowing request"
    containers: list[Mapping[str, Any]] = []
    for key in ("tool_input", "toolInput", "input", "arguments", "args"):
        value = payload.get(key)
        if isinstance(value, Mapping):
            containers.append(value)
    containers.append(payload)
    command: Any = None
    for container in containers:
        command = _mapping_value(container, ("command", "cmd", "script", "commandLine"))
        if command is not None:
            break
    if not isinstance(command, str) and not (
        isinstance(command, list) and all(isinstance(item, str) for item in command)
    ):
        return None, None, "missing or unsupported command input; allowing request"
    cwd_value = _mapping_value(payload, ("cwd", "working_directory", "workingDirectory"))
    if cwd_value is None:
        for container in containers:
            cwd_value = _mapping_value(container, ("cwd", "working_directory", "workingDirectory"))
            if cwd_value is not None:
                break
    cwd = Path(cwd_value) if isinstance(cwd_value, str) and cwd_value else None
    return command, cwd, None


def _option_value(tokens: Sequence[str], names: set[str]) -> str | None:
    for index, token in enumerate(tokens):
        lowered = token.lower()
        if lowered in names and index + 1 < len(tokens):
            return tokens[index + 1]
        for name in names:
            if lowered.startswith(name + "="):
                return token.split("=", 1)[1]
    return None


def _target_maps(targets: Mapping[str, Any]) -> Mapping[str, Any]:
    classifications = targets.get("classifications", {})
    return classifications if isinstance(classifications, Mapping) else {}


def classify_target(
    command: str | Sequence[str] | None,
    classification: Mapping[str, Any] | None,
    targets: Mapping[str, Any],
    arguments: Mapping[str, Any] | None = None,
) -> tuple[str | None, str | None, str]:
    maps = _target_maps(targets)
    if command is not None:
        script = parse_command(_command_text(command))
        for tokens in script.commands:
            executable = _basename(tokens[0])
            if executable == "kubectl":
                context = _option_value(tokens[1:], {"--context"})
                namespace = _option_value(tokens[1:], {"--namespace", "-n"})
                if not context:
                    return None, None, "Kubernetes target lacks explicit context"
                if classification and classification.get("operation_class") == "mutate" and not namespace:
                    return context, None, "namespaced Kubernetes mutation lacks explicit namespace"
                key = f"{context}/{namespace}" if namespace else context
                namespace_map = maps.get("kubernetes_namespaces", {})
                context_map = maps.get("kubernetes_contexts", {})
                if namespace and isinstance(namespace_map, Mapping) and namespace_map.get(key) in {"dev", "tst", "int", "prd"}:
                    return key, str(namespace_map[key]), "mapped Kubernetes namespace"
                if isinstance(context_map, Mapping) and context_map.get(context) in {"dev", "tst", "int", "prd"}:
                    return key, str(context_map[context]), "mapped Kubernetes context"
                return key, None, "Kubernetes target is not mapped"
            if executable == "az":
                subscription = _option_value(tokens[1:], {"--subscription", "-s"})
                tenant = _option_value(tokens[1:], {"--tenant"})
                if not subscription:
                    return tenant, None, "Azure target lacks explicit subscription"
                subscription_map = maps.get("azure_subscriptions", {})
                if isinstance(subscription_map, Mapping) and subscription_map.get(subscription) in {"dev", "tst", "int", "prd"}:
                    return subscription, str(subscription_map[subscription]), "mapped Azure subscription"
                return subscription, None, "Azure subscription is not mapped"
            if executable in {"terraform", "tofu", "terragrunt"}:
                workspace = _option_value(tokens[1:], {"--workspace", "-workspace"})
                workspace_map = maps.get("terraform_workspaces", {})
                if workspace and isinstance(workspace_map, Mapping) and workspace_map.get(workspace) in {"dev", "tst", "int", "prd"}:
                    return workspace, str(workspace_map[workspace]), "mapped Terraform workspace"
                return workspace, None, "Terraform target is not mapped"
            if executable == "spacectl":
                stack = _option_value(tokens[1:], {"--stack", "--stack-id"})
                stack_map = maps.get("spacelift_stacks", {})
                if stack and isinstance(stack_map, Mapping) and stack_map.get(stack) in {"dev", "tst", "int", "prd"}:
                    return stack, str(stack_map[stack]), "mapped Spacelift stack"
                return stack, None, "Spacelift target is not mapped"
    if arguments is not None:
        for field, mapping_name in (
            ("stack_id", "spacelift_stacks"),
            ("stack", "spacelift_stacks"),
            ("subscription", "azure_subscriptions"),
            ("context", "kubernetes_contexts"),
            ("workspace", "terraform_workspaces"),
        ):
            value = arguments.get(field)
            mapping = maps.get(mapping_name, {})
            if isinstance(value, str):
                lifecycle = mapping.get(value) if isinstance(mapping, Mapping) else None
                return value, str(lifecycle) if lifecycle in {"dev", "tst", "int", "prd"} else None, f"target field {field}"
    return None, None, "no target classification available"


def _is_remote_classification(classification: Mapping[str, Any] | None) -> bool:
    if classification is None:
        return False
    if classification.get("remote") is True:
        return True
    identifier = str(classification.get("id", ""))
    return identifier.startswith(
        ("kubernetes-", "helm-", "terraform-", "opentofu-", "terragrunt-", "spacelift-", "azure-", "database-")
    )


def safety_decision(
    classification: Mapping[str, Any] | None,
    *,
    safety_profile: str,
    trust_mode: str,
    target_lifecycle: str | None,
    target_evidence: str,
) -> Mapping[str, Any] | None:
    if classification is None or classification.get("operation_class") != "mutate":
        return None
    if not _is_remote_classification(classification):
        return None
    if trust_mode in {"untrusted-workspace", "untrusted-external-input", "incident-observe"}:
        return {
            "id": "trust-mode-remote-mutation",
            "operation_class": "mutate",
            "rollout_mode": "deny",
            "policy_source": "trust/modes.json",
            "reason": f"The {trust_mode} trust mode does not permit remote mutation.",
        }
    if safety_profile == "infrastructure-strict":
        return {
            "id": "safety-profile-infrastructure-strict",
            "operation_class": "mutate",
            "rollout_mode": "deny",
            "policy_source": "config/safety-profiles.json",
            "reason": "The infrastructure-strict profile permits observation and validation only.",
        }
    if target_lifecycle == "prd":
        return {
            "id": "safety-profile-production-mutation",
            "operation_class": "mutate",
            "rollout_mode": "deny",
            "policy_source": "config/safety-profiles.json",
            "reason": "Direct prd mutation is denied; use an externally controlled human/platform workflow.",
        }
    if safety_profile == "infrastructure-nonprod" and target_lifecycle in {"dev", "tst", "int"}:
        return None
    if safety_profile == "infrastructure-nonprod":
        return {
            "id": "safety-profile-protected-target",
            "operation_class": "mutate",
            "rollout_mode": "deny",
            "policy_source": "config/safety-profiles.json",
            "reason": f"Remote mutation requires an explicitly mapped dev, tst, or int target; {target_evidence}.",
        }
    return {
        "id": "safety-profile-infrastructure-observe",
        "operation_class": "mutate",
        "rollout_mode": "deny",
        "policy_source": "config/safety-profiles.json",
        "reason": "The active safety profile permits infrastructure observation and validation, not remote mutation.",
    }


def load_runtime_metadata(path: Path = METADATA_PATH) -> dict[str, Any]:
    defaults = {
        "format_version": 1,
        "product": "unknown",
        "policy_digest": "0" * 64,
        "safety_profile": "infrastructure-observe",
        "trust_mode": "trusted-workspace",
        "home_directory": None,
        "audit_directory": None,
        "waiver_directory": None,
        "targets_path": None,
        "state_path": None,
        "managed_paths": [],
    }
    raw = _read_json(path, default=defaults)
    if not isinstance(raw, dict):
        raise PolicyError("runtime metadata must be an object")
    result = dict(defaults)
    result.update(raw)
    if result["safety_profile"] not in {
        "development",
        "infrastructure-observe",
        "infrastructure-nonprod",
        "infrastructure-strict",
    }:
        raise PolicyError("runtime metadata has invalid safety profile")
    if result["trust_mode"] not in {
        "trusted-workspace",
        "untrusted-workspace",
        "untrusted-external-input",
        "incident-observe",
    }:
        raise PolicyError("runtime metadata has invalid trust mode")
    for field in ("home_directory", "audit_directory", "waiver_directory", "targets_path", "state_path"):
        if result[field] is not None and not isinstance(result[field], str):
            raise PolicyError(f"runtime metadata has invalid {field.replace('_', ' ')}")
    if not isinstance(result["managed_paths"], list) or any(
        not isinstance(value, str) for value in result["managed_paths"]
    ):
        raise PolicyError("runtime metadata has invalid managed paths")
    return result


def load_redaction_policy(path: Path) -> dict[str, Any]:
    raw = _read_json(path, default={})
    if not isinstance(raw, dict):
        raise PolicyError("redaction policy must be an object")
    fields = raw.get("audit_value_fields")
    patterns = raw.get("never_log_field_patterns")
    maximum = raw.get("maximum_file_bytes")
    rotations = raw.get("retained_rotations")
    if not isinstance(fields, list) or set(fields) != set(AUDIT_FIELDS):
        raise PolicyError("redaction policy has an invalid audit field allowlist")
    if not isinstance(patterns, list) or not patterns or any(not isinstance(item, str) for item in patterns):
        raise PolicyError("redaction policy has invalid protected field patterns")
    if not isinstance(maximum, int) or maximum <= 0:
        raise PolicyError("redaction policy has an invalid audit size limit")
    if not isinstance(rotations, int) or not 1 <= rotations <= 10:
        raise PolicyError("redaction policy has an invalid audit rotation count")
    return raw


def _runtime_path_allowed(path: Path, metadata: Mapping[str, Any]) -> bool:
    home_value = metadata.get("home_directory")
    if not isinstance(home_value, str) or not home_value:
        return False
    try:
        path.expanduser().resolve(strict=False).relative_to(Path(home_value).resolve(strict=False))
        return True
    except (OSError, RuntimeError, ValueError):
        return False


def load_targets(metadata: Mapping[str, Any]) -> Mapping[str, Any]:
    path = metadata.get("targets_path")
    if not isinstance(path, str) or not path:
        return {}
    if not _runtime_path_allowed(Path(path), metadata):
        _diagnostic("target mapping path is outside the selected home; remote targets remain protected")
        return {}
    try:
        raw = _read_json(Path(path), default={})
    except PolicyError:
        _diagnostic("target mapping could not be read; remote targets remain protected")
        return {}
    return raw if isinstance(raw, Mapping) else {}


def _digest_command(command: str | Sequence[str]) -> str:
    return hashlib.sha256(_command_text(command).encode("utf-8", errors="replace")).hexdigest()


def _digest_tool(tool_name: str, arguments: Mapping[str, Any]) -> str:
    try:
        encoded = json.dumps([tool_name, arguments], sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
    except (TypeError, ValueError):
        encoded = tool_name.encode("utf-8", errors="replace")
    return hashlib.sha256(encoded).hexdigest()


def _repository_scope(cwd: Path | None) -> tuple[str, str | None]:
    if cwd is None:
        return "unknown", None
    resolved = cwd.resolve(strict=False)
    digest = hashlib.sha256(str(resolved).encode("utf-8", errors="replace")).hexdigest()
    return digest, str(resolved)


def _parse_time(value: Any) -> dt.datetime | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=dt.timezone.utc)
    return parsed.astimezone(dt.timezone.utc)


def _waiver_matches(
    waiver: Mapping[str, Any],
    *,
    rule: Mapping[str, Any],
    request_digest: str,
    repo_digest: str,
    repo_path: str | None,
    target: str | None,
    now: dt.datetime,
) -> bool:
    if set(waiver) != WAIVER_FIELDS:
        return False
    identifier = waiver.get("id")
    if not isinstance(identifier, str) or re.fullmatch(r"waiver-[0-9a-f]{32}", identifier) is None:
        return False
    if waiver.get("rule_id") != rule.get("id") or waiver.get("command_tool_call_digest") != request_digest:
        return False
    created = _parse_time(waiver.get("created_at"))
    expires = _parse_time(waiver.get("expires_at"))
    if (
        created is None
        or expires is None
        or expires <= created
        or expires - created > dt.timedelta(hours=24)
        or expires <= now
    ):
        return False
    maximum = waiver.get("maximum_uses")
    remaining = waiver.get("remaining_uses")
    if (
        not isinstance(maximum, int)
        or not 1 <= maximum <= 10
        or not isinstance(remaining, int)
        or not 0 < remaining <= maximum
    ):
        return False
    repository_scope = waiver.get("repository_scope")
    target_scope = waiver.get("target_scope")
    if rule.get("operation_class") in {
        "destructive",
        "sensitive-read",
        "publish",
        "privilege-escalation",
        "guardrail-modification",
    } and (repository_scope == "*" or target_scope == "*"):
        return False
    if repository_scope not in {"*", repo_digest, repo_path}:
        return False
    accepted_target_scopes = {"*", target}
    if target is None:
        accepted_target_scopes.update({None, "none"})
    if target_scope not in accepted_target_scopes:
        return False
    return all(
        isinstance(waiver.get(field), str) and bool(str(waiver[field]).strip())
        for field in ("reason", "change_reference", "created_by")
    )


def find_waiver(
    metadata: Mapping[str, Any],
    rule: Mapping[str, Any],
    request_digest: str,
    cwd: Path | None,
    target: str | None,
    *,
    consume: bool,
) -> str | None:
    directory_value = metadata.get("waiver_directory")
    if not isinstance(directory_value, str) or not directory_value:
        return None
    directory = Path(directory_value)
    if not _runtime_path_allowed(directory, metadata) or not directory.is_dir():
        return None
    repo_digest, repo_path = _repository_scope(cwd)
    now = dt.datetime.now(dt.timezone.utc)
    for path in sorted(directory.glob("*.json")):
        if not _runtime_path_allowed(path, metadata):
            _diagnostic("waiver path outside selected home ignored; contents redacted")
            continue
        try:
            waiver = _read_json(path)
        except PolicyError:
            _diagnostic("invalid waiver file ignored; contents redacted")
            continue
        if not isinstance(waiver, dict) or not _waiver_matches(
            waiver,
            rule=rule,
            request_digest=request_digest,
            repo_digest=repo_digest,
            repo_path=repo_path,
            target=target,
            now=now,
        ):
            continue
        if not consume:
            return str(waiver["id"])
        lock_path = path.with_suffix(path.suffix + ".lock")
        if not _runtime_path_allowed(lock_path, metadata):
            continue
        try:
            descriptor = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        except FileExistsError:
            continue
        except OSError:
            _diagnostic("waiver use lock could not be acquired; request remains protected")
            continue
        try:
            os.close(descriptor)
            current = _read_json(path)
            if not isinstance(current, dict) or not _waiver_matches(
                current,
                rule=rule,
                request_digest=request_digest,
                repo_digest=repo_digest,
                repo_path=repo_path,
                target=target,
                now=now,
            ):
                continue
            current["remaining_uses"] -= 1
            _atomic_json(path, current, mode=0o600)
            return str(current["id"])
        except (OSError, PolicyError):
            _diagnostic("waiver changed or could not be consumed; request remains protected")
        finally:
            try:
                lock_path.unlink()
            except OSError:
                _diagnostic("waiver use lock could not be removed; later use remains protected")
    return None


def _atomic_json(path: Path, value: Mapping[str, Any], mode: int = 0o600) -> None:
    data = (json.dumps(value, indent=2, sort_keys=True) + "\n").encode("utf-8")
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        with temporary.open("xb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temporary, mode)
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()


def _safe_tokens(command: str | Sequence[str]) -> tuple[str, ...]:
    script = parse_command(_command_text(command))
    # Executable basenames provide useful matching context without risking
    # disclosure of positional targets, inline statements, or credential values.
    return tuple(dict.fromkeys(_basename(tokens[0]) for tokens in script.commands if tokens))


def _managed_path_rule(
    tool_name: str,
    arguments: Mapping[str, Any],
    metadata: Mapping[str, Any],
    cwd: Path | None,
) -> tuple[Mapping[str, Any] | None, tuple[str, ...]]:
    _, name = _normalise_tool_name(tool_name)
    if _basename(name) not in FILE_WRITE_TOOLS:
        return None, ()
    field_names = ("path", "file_path", "target", "filename")
    values = [(field, arguments.get(field)) for field in field_names if isinstance(arguments.get(field), str)]
    managed = [Path(value).resolve(strict=False) for value in metadata.get("managed_paths", []) if isinstance(value, str)]
    runtime = Path(__file__).resolve(strict=False).parent
    protected_roots = [runtime]
    for metadata_field in ("waiver_directory", "targets_path", "state_path"):
        protected_value = metadata.get(metadata_field)
        if isinstance(protected_value, str) and protected_value:
            protected_roots.append(Path(protected_value).resolve(strict=False))
    for field, value in values:
        raw_target = Path(str(value)).expanduser()
        if not raw_target.is_absolute() and cwd is not None:
            raw_target = cwd / raw_target
        target = raw_target.resolve(strict=False)
        if any(target == root or root in target.parents for root in (*protected_roots, *managed)):
            return {
                "id": "guardrail-self-protection",
                "operation_class": "guardrail-modification",
                "rollout_mode": "deny",
                "policy_source": "enforcement/structured-tool-policy.json",
                "reason": "Installed guardrail runtime, waivers, state, target mappings, and managed configuration require the explicit maintenance workflow.",
                "never_log_fields": list(arguments),
            }, (field,)
        candidates = [str(value).replace("\\", "/")]
        if cwd is not None:
            try:
                candidates.append(target.relative_to(cwd.resolve(strict=False)).as_posix())
            except ValueError:
                pass
        normalised = [candidate[2:] if candidate.startswith("./") else candidate for candidate in candidates]
        high_risk = any(
            candidate in {"AGENTS.md", "CLAUDE.md", ".ai-guardrails.json", "CODEOWNERS"}
            or candidate.startswith(
                (".cursor/", ".codex/", ".claude/", ".github/workflows/", "platform-policies/spacelift/")
            )
            for candidate in normalised
        )
        if high_risk:
            return {
                "id": "repository-governance-file-change",
                "operation_class": "guardrail-modification",
                "rollout_mode": "warn",
                "policy_source": "risk/path-classification.json",
                "reason": "This path controls agent, CI, release, security, or governance behaviour; require explicit intent and full validation.",
                "never_log_fields": list(arguments),
            }, (field,)
    return None, tuple(field for field, _ in values)


def _decision_for_rule(
    rule: Mapping[str, Any],
    *,
    metadata: Mapping[str, Any],
    request_digest: str,
    cwd: Path | None,
    target: str | None,
    lifecycle: str | None,
    matched_tokens: tuple[str, ...] = (),
    matched_fields: tuple[str, ...] = (),
    consume_waiver: bool,
) -> Decision:
    mode = str(rule.get("rollout_mode", "deny"))
    waiver = None
    if mode == "deny":
        waiver = find_waiver(
            metadata,
            rule,
            request_digest,
            cwd,
            target,
            consume=consume_waiver,
        )
    if waiver:
        internal = "no-decision"
    elif mode in {"disabled", "observe"}:
        internal = "no-decision"
    elif mode == "warn":
        internal = "warn"
    else:
        internal = "deny"
    return Decision(
        decision=internal,
        rollout_mode=mode,
        rule_id=str(rule.get("id")),
        operation_class=str(rule.get("operation_class")),
        reason=str(rule.get("reason")),
        policy_source=str(rule.get("policy_source", "canonical policy")),
        matched_tokens=matched_tokens,
        matched_fields=matched_fields,
        target=target,
        target_lifecycle=lifecycle,
        waiver_id=waiver,
        safety_profile=str(metadata.get("safety_profile", "infrastructure-observe")),
        trust_mode=str(metadata.get("trust_mode", "trusted-workspace")),
        request_digest=request_digest,
    )


def evaluate_request(
    payload: Mapping[str, Any],
    *,
    policy_data: Mapping[str, Any],
    metadata: Mapping[str, Any],
    consume_waiver: bool = False,
) -> Decision:
    tool_name, arguments, diagnostic = extract_tool(payload)
    safety_profile = str(metadata.get("safety_profile", "infrastructure-observe"))
    trust_mode = str(metadata.get("trust_mode", "trusted-workspace"))
    if diagnostic or tool_name is None:
        return Decision("no-decision", "disabled", None, None, diagnostic, None, (), (), None, None, None, safety_profile, trust_mode, hashlib.sha256(b"unsupported").hexdigest())
    _, normalised_tool = _normalise_tool_name(tool_name)
    is_shell = _basename(normalised_tool) in SHELL_TOOLS
    targets = load_targets(metadata)
    if is_shell:
        command, cwd, command_diagnostic = extract_command(payload)
        if command_diagnostic or command is None:
            return Decision("no-decision", "disabled", None, None, command_diagnostic, None, (), (), None, None, None, safety_profile, trust_mode, hashlib.sha256(b"unsupported-command").hexdigest())
        digest = _digest_command(command)
        matched = evaluate_command(command, policy=policy_data, cwd=cwd)
        classification = matched or classify_command(command, policy=policy_data, cwd=cwd)
        target, lifecycle, evidence = classify_target(command, classification, targets)
        if matched is None:
            matched = safety_decision(
                classification,
                safety_profile=safety_profile,
                trust_mode=trust_mode,
                target_lifecycle=lifecycle,
                target_evidence=evidence,
            )
        if matched is None:
            operation = str(classification.get("operation_class")) if classification else None
            return Decision("no-decision", "disabled", None, operation, None, None, _safe_tokens(command), (), target, lifecycle, None, safety_profile, trust_mode, digest)
        return _decision_for_rule(
            matched,
            metadata=metadata,
            request_digest=digest,
            cwd=cwd,
            target=target,
            lifecycle=lifecycle,
            matched_tokens=_safe_tokens(command),
            consume_waiver=consume_waiver,
        )
    args = arguments or {}
    cwd_value = _mapping_value(payload, ("cwd", "working_directory", "workingDirectory"))
    cwd = Path(cwd_value) if isinstance(cwd_value, str) and cwd_value else None
    digest = _digest_tool(tool_name, args)
    matched, path_fields = _managed_path_rule(tool_name, args, metadata, cwd)
    if matched is None:
        matched = evaluate_structured_tool(tool_name, args, policy_data)
    target, lifecycle, evidence = classify_target(None, matched, targets, args)
    if matched is not None and matched.get("operation_class") == "mutate":
        safety = safety_decision(
            matched,
            safety_profile=safety_profile,
            trust_mode=trust_mode,
            target_lifecycle=lifecycle,
            target_evidence=evidence,
        )
        # Preserve a rule's stable identifier when it already makes the
        # strongest decision. A safety profile may only tighten an allow,
        # observe, or warning rule; it must not obscure the matched deny.
        if safety is not None and matched.get("rollout_mode", "deny") != "deny":
            matched = safety
    if matched is None:
        return Decision("no-decision", "disabled", None, None, None, None, (), tuple(sorted(args)), target, lifecycle, None, safety_profile, trust_mode, digest)
    never_log = {str(value).lower() for value in matched.get("never_log_fields", [])}
    safe_fields = tuple(sorted(field for field in args if field.lower() not in never_log))
    if path_fields:
        safe_fields = path_fields
    return _decision_for_rule(
        matched,
        metadata=metadata,
        request_digest=digest,
        cwd=cwd,
        target=target,
        lifecycle=lifecycle,
        matched_fields=safe_fields,
        consume_waiver=consume_waiver,
    )


def _rotate_audit(path: Path, maximum_bytes: int, rotations: int) -> None:
    if not path.exists() or path.stat().st_size < maximum_bytes:
        return
    oldest = path.with_suffix(path.suffix + f".{rotations}")
    if oldest.exists():
        oldest.unlink()
    for index in range(rotations - 1, 0, -1):
        source = path.with_suffix(path.suffix + f".{index}")
        if source.exists():
            os.replace(source, path.with_suffix(path.suffix + f".{index + 1}"))
    os.replace(path, path.with_suffix(path.suffix + ".1"))


def write_audit(
    decision: Decision,
    *,
    metadata: Mapping[str, Any],
    product: str,
    payload: Mapping[str, Any],
    redaction_policy: Mapping[str, Any] | None = None,
) -> None:
    directory_value = metadata.get("audit_directory")
    if not isinstance(directory_value, str) or not directory_value:
        return
    directory = Path(directory_value)
    if not _runtime_path_allowed(directory, metadata):
        _diagnostic("audit path outside selected home; audit event was not written")
        return
    try:
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / "events.jsonl"
        if not _runtime_path_allowed(path, metadata):
            _diagnostic("audit event path outside selected home; audit event was not written")
            return
        redaction = redaction_policy or {}
        maximum_bytes = int(redaction.get("maximum_file_bytes", AUDIT_MAX_BYTES))
        rotations = int(redaction.get("retained_rotations", AUDIT_ROTATIONS))
        allowed_fields = set(redaction.get("audit_value_fields", AUDIT_FIELDS))
        _rotate_audit(path, maximum_bytes, rotations)
        session = _mapping_value(payload, ("session_id", "sessionId", "conversation_id", "conversationId"))
        session_hash = hashlib.sha256(str(session).encode("utf-8")).hexdigest() if session is not None else None
        tool_name, _, _ = extract_tool(payload)
        normalised_tool = _normalise_tool_name(tool_name or "")[1]
        event = {
            "timestamp": dt.datetime.now(dt.timezone.utc).replace(microsecond=0).strftime(ISO_Z),
            "product": product,
            "session_id_hash": session_hash,
            "event_type": "pre-tool-use",
            "tool_category": "shell" if _basename(normalised_tool) in SHELL_TOOLS else "structured",
            "rule_id": decision.rule_id,
            "decision": decision.decision,
            "operation_class": decision.operation_class,
            "target_lifecycle": decision.target_lifecycle or "unknown",
            "request_digest": decision.request_digest,
            "waiver_id": decision.waiver_id,
            "policy_digest": metadata.get("policy_digest", "unknown"),
        }
        event = {field: value for field, value in event.items() if field in allowed_fields}
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(event, sort_keys=True, separators=(",", ":")) + "\n")
        os.chmod(path, 0o600)
    except OSError:
        _diagnostic("redacted audit event could not be written")


def denial(reason: str) -> dict[str, Any]:
    return {
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": reason,
        }
    }


def denial_reason(decision: Decision) -> str:
    return f"Blocked by {decision.rule_id} ({decision.operation_class}): {decision.reason}"


def response_for_product(decision: Decision, product: str) -> Mapping[str, Any] | None:
    # Current Codex, Claude, and Cursor third-party hook adapters accept this
    # documented PreToolUse denial shape. Warnings are intentionally diagnostic
    # only because the products do not share a stable warning injection field.
    if decision.decision == "deny":
        return denial(denial_reason(decision))
    if decision.decision == "warn":
        _diagnostic(f"warning from {decision.rule_id} ({decision.operation_class}); request allowed")
    return None


def validate_policy_examples(policy_data: Mapping[str, Any]) -> int:
    checked = 0
    for rule in policy_data.get("rules", []):
        isolated = {
            "schema_version": 1,
            "rules": [rule],
            "classifications": [],
            "structured_tool_rules": [],
            "structured_tools": {"strict_allowlist": False},
        }
        for command in rule.get("must_match", []):
            matched = evaluate_command(command, isolated)
            if matched is None or matched.get("id") != rule.get("id"):
                actual = "no rule" if matched is None else str(matched.get("id"))
                raise PolicyError(f"example for {rule.get('id')} matched {actual}")
            checked += 1
        for command in rule.get("must_not_match", []):
            matched = evaluate_command(command, isolated)
            if matched is not None:
                raise PolicyError(f"safe example for {rule.get('id')} matched {matched.get('id')}")
            checked += 1
    for rule in policy_data.get("structured_tool_rules", []):
        isolated = {
            "schema_version": 1,
            "rules": [],
            "classifications": [],
            "structured_tool_rules": [rule],
            "structured_tools": {"strict_allowlist": False},
        }
        for fixture in rule.get("positive_fixtures", []):
            if not isinstance(fixture, Mapping):
                raise PolicyError(f"structured positive fixture is invalid: {rule.get('id')}")
            tool_value = fixture.get("tool_name", fixture.get("toolName", fixture.get("tool", "")))
            if isinstance(tool_value, Mapping):
                tool_value = tool_value.get("name", tool_value.get("type", ""))
            name = str(tool_value)
            arguments = fixture.get(
                "arguments", fixture.get("tool_input", fixture.get("toolInput", {}))
            )
            if not isinstance(arguments, Mapping):
                arguments = {}
            matched = evaluate_structured_tool(name, arguments, isolated)
            if matched is None or matched.get("id") != rule.get("id"):
                raise PolicyError(f"structured fixture for {rule.get('id')} did not match")
            checked += 1
        for fixture in rule.get("negative_fixtures", []):
            if not isinstance(fixture, Mapping):
                raise PolicyError(f"structured negative fixture is invalid: {rule.get('id')}")
            tool_value = fixture.get("tool_name", fixture.get("toolName", fixture.get("tool", "")))
            if isinstance(tool_value, Mapping):
                tool_value = tool_value.get("name", tool_value.get("type", ""))
            name = str(tool_value)
            arguments = fixture.get(
                "arguments", fixture.get("tool_input", fixture.get("toolInput", {}))
            )
            if not isinstance(arguments, Mapping):
                arguments = {}
            matched = evaluate_structured_tool(name, arguments, isolated)
            if matched is not None:
                raise PolicyError(f"safe structured fixture for {rule.get('id')} matched {matched.get('id')}")
            checked += 1
    return checked


def create_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--product", choices=("codex", "claude", "cursor"), default="codex")
    parser.add_argument("--policy", type=Path, default=POLICY_PATH)
    parser.add_argument("--structured-policy", type=Path, default=STRUCTURED_POLICY_PATH)
    parser.add_argument("--redaction-policy", type=Path, default=Path(__file__).with_name("redaction-policy.json"))
    parser.add_argument("--metadata", type=Path, default=METADATA_PATH)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = create_parser().parse_args(argv)
    try:
        payload = json.load(sys.stdin)
    except (json.JSONDecodeError, UnicodeDecodeError):
        _diagnostic("malformed JSON input; allowing request")
        return 0
    if not isinstance(payload, dict):
        _diagnostic("hook input is not an object; allowing request")
        return 0
    try:
        policy_data = load_installed_policy(args.policy, args.structured_policy)
        metadata = load_runtime_metadata(args.metadata)
        decision = evaluate_request(payload, policy_data=policy_data, metadata=metadata, consume_waiver=True)
        if decision.rule_id is None:
            tool_name, _, diagnostic = extract_tool(payload)
            if decision.reason:
                _diagnostic(decision.reason)
            elif diagnostic:
                _diagnostic(diagnostic)
            elif tool_name and _basename(_normalise_tool_name(tool_name)[1]) not in SHELL_TOOLS:
                _diagnostic("unrecognised structured tool; allowing request with arguments redacted")
        try:
            redaction = load_redaction_policy(args.redaction_policy)
        except PolicyError:
            _diagnostic("invalid redaction policy; using safe audit defaults")
            redaction = {}
        write_audit(
            decision,
            metadata=metadata,
            product=args.product,
            payload=payload,
            redaction_policy=redaction,
        )
        response = response_for_product(decision, args.product)
    except (OSError, PolicyError, TypeError) as exc:
        _diagnostic(f"policy evaluation failed ({exc.__class__.__name__}); allowing request")
        return 0
    if response is not None:
        json.dump(response, sys.stdout, separators=(",", ":"))
        sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
