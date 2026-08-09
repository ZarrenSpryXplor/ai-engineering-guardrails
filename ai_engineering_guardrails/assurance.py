"""Task contracts and local report evidence, without executing repository code.

The module accepts small, repository-owned report files produced by existing
tools.  It does not invoke those tools, interpret source snippets, or retain
their raw output.
"""

from __future__ import annotations

import datetime as dt
import fnmatch
import json
import math
import re
import sys
import xml.etree.ElementTree as ET
from decimal import Decimal
from pathlib import Path, PureWindowsPath
from typing import Any, Mapping, Sequence
from urllib.parse import unquote, urlsplit

from . import complexity, state
from .resources import RESOURCE_ROOT
from .util import NAME_RE, GuardrailsError, atomic_write, file_hash, json_bytes, path_within, read_json, sha256


ASSURANCE_ROOT = RESOURCE_ROOT / "assurance"
TASK_SCHEMA_PATH = ASSURANCE_ROOT / "task-schema.json"
TASK_CONTRACT_NAME = ".ai-task.json"
TASK_EVIDENCE_NAME = ".ai-task.evidence.json"
TASK_EVIDENCE_EXAMPLE_NAME = ".ai-task.evidence.example.json"
TASK_SCHEMA_VERSION = 1
EVIDENCE_SCHEMA_VERSION = 1
PARSER_VERSION = 1
MAX_REPORT_BYTES = 2_000_000
MAX_REPORT_COUNT = 2_147_483_647
MAX_REPORT_SECONDS = 1_000_000_000_000.0
MAX_REPORT_TIMESTAMP = 10_000_000_000_000
TASK_METADATA_NAMES = {TASK_CONTRACT_NAME, TASK_EVIDENCE_NAME, TASK_EVIDENCE_EXAMPLE_NAME}


class EvidenceParseError(GuardrailsError):
    """Malformed bounded evidence supplied to an assurance parser."""


def _utc_now() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc).replace(microsecond=0)


def _iso(value: dt.datetime) -> str:
    return value.astimezone(dt.timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _parse_timestamp(value: object) -> dt.datetime | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo is not None else None


def _safe_text(value: object, *, maximum: int = 500) -> bool:
    return isinstance(value, str) and bool(value.strip()) and len(value) <= maximum and "\x00" not in value


def _load_json(path: Path, label: str) -> dict[str, Any]:
    if path.is_symlink() or not path.is_file():
        raise GuardrailsError(f"{label} must be a regular file: {path}")
    if path.stat().st_size > MAX_REPORT_BYTES:
        raise GuardrailsError(f"{label} exceeds the {MAX_REPORT_BYTES}-byte limit")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise GuardrailsError(f"{label} is not valid JSON") from exc
    if not isinstance(value, dict):
        raise GuardrailsError(f"{label} must contain a JSON object")
    return value


def load_task_schema(path: Path = TASK_SCHEMA_PATH) -> dict[str, Any]:
    value = read_json(path, default={})
    if not isinstance(value, dict) or value.get("schema_version") != TASK_SCHEMA_VERSION:
        raise GuardrailsError("task-contract schema has an unsupported version")
    required = value.get("required")
    statuses = value.get("statuses")
    types = value.get("evidence_types")
    optional = value.get("optional_fields")
    if not all(isinstance(item, list) and all(isinstance(entry, str) for entry in item) for item in (required, statuses, types, optional)):
        raise GuardrailsError("task-contract schema lists are invalid")
    if len(set(required)) != len(required) or len(set(statuses)) != len(statuses) or len(set(types)) != len(types):
        raise GuardrailsError("task-contract schema contains duplicate values")
    return value


def validate_resources() -> None:
    schema = load_task_schema()
    if set(schema["required"]) != {"schema_version", "objective", "observable_outcomes", "non_goals", "risk_class", "status"}:
        raise GuardrailsError("task-contract schema required fields are invalid")
    if set(schema["statuses"]) != {"planned", "in-progress", "partial", "completed", "blocked", "halted"}:
        raise GuardrailsError("task-contract schema statuses are invalid")
    expected_types = {
        "junit", "sarif", "cobertura", "manual-review", "security-review", "compatibility-review", "change-diff-review",
    }
    if set(schema["evidence_types"]) != expected_types:
        raise GuardrailsError("task-contract schema evidence types are invalid")


def _risk_classes() -> set[str]:
    data = read_json(RESOURCE_ROOT / "risk" / "path-classification.json", default={})
    entries = data.get("classifications", []) if isinstance(data, Mapping) else []
    return {"normal"} | {
        str(entry.get("risk_class"))
        for entry in entries
        if isinstance(entry, Mapping) and isinstance(entry.get("risk_class"), str)
    }


def _identifier_entries(values: object, label: str, *, allow_strings: bool = True) -> list[dict[str, Any]]:
    if not isinstance(values, list) or not values:
        raise GuardrailsError(f"task contract {label} must be a non-empty list")
    result: list[dict[str, Any]] = []
    identifiers: set[str] = set()
    descriptions: set[str] = set()
    for index, value in enumerate(values, start=1):
        if allow_strings and _safe_text(value, maximum=1000):
            identifier = f"{label}-{index}"
            description = str(value).strip()
        elif isinstance(value, Mapping) and set(value).issubset({"id", "description", "evidence_id"}):
            identifier = value.get("id")
            description = value.get("description")
            if not isinstance(identifier, str) or not NAME_RE.fullmatch(identifier) or not _safe_text(description, maximum=1000):
                raise GuardrailsError(f"task contract {label} item must have a portable id and description")
            evidence_id = value.get("evidence_id")
            if evidence_id is not None and (not isinstance(evidence_id, str) or not NAME_RE.fullmatch(evidence_id)):
                raise GuardrailsError(f"task contract {label} item has an invalid evidence_id")
        else:
            raise GuardrailsError(f"task contract {label} item is invalid")
        if identifier in identifiers:
            raise GuardrailsError(f"task contract has duplicate {label} id: {identifier}")
        if description in descriptions:
            raise GuardrailsError(f"task contract has duplicate {label} description")
        identifiers.add(identifier)
        descriptions.add(description)
        item: dict[str, Any] = {"id": identifier, "description": description}
        if isinstance(value, Mapping) and isinstance(value.get("evidence_id"), str):
            item["evidence_id"] = value["evidence_id"]
        result.append(item)
    return result


def _safe_relative(value: object, label: str) -> str:
    if (
        not isinstance(value, str)
        or not value
        or len(value) > 500
        or any(ord(character) < 32 or ord(character) == 127 for character in value)
    ):
        raise GuardrailsError(f"{label} must be a short repository-relative path")
    lexical = value.replace("\\", "/")
    if value.startswith("\\") or lexical.startswith("/") or re.match(r"^[A-Za-z]:", value):
        raise GuardrailsError(f"{label} must remain beneath the selected repository")
    path = Path(value)
    if path.is_absolute() or PureWindowsPath(value).is_absolute() or ".." in path.parts or path == Path("."):
        raise GuardrailsError(f"{label} must remain beneath the selected repository")
    return path.as_posix()


def _path_patterns(values: object, label: str) -> list[str]:
    if not isinstance(values, list) or not values or not all(isinstance(item, str) and item and len(item) <= 300 for item in values):
        raise GuardrailsError(f"task contract {label} must be a non-empty list of patterns")
    for pattern in values:
        _safe_relative(pattern.replace("*", "placeholder"), label)
    return list(values)


def _required_evidence(values: object, evidence_types: set[str]) -> list[dict[str, Any]]:
    if values is None:
        return []
    if not isinstance(values, list):
        raise GuardrailsError("task contract required_evidence must be a list")
    result: list[dict[str, Any]] = []
    identifiers: set[str] = set()
    for value in values:
        if (
            not isinstance(value, Mapping)
            or not {"id", "type"}.issubset(value)
            or set(value) - {"id", "type", "maximum_age_hours", "allow_external_ci_artifact"}
        ):
            raise GuardrailsError(
                "task contract evidence entries support id, type, maximum_age_hours, and allow_external_ci_artifact only"
            )
        identifier = value.get("id")
        kind = value.get("type")
        if not isinstance(identifier, str) or not NAME_RE.fullmatch(identifier) or identifier in identifiers:
            raise GuardrailsError("task contract evidence identifiers must be unique portable names")
        if kind not in evidence_types:
            raise GuardrailsError(f"task contract evidence {identifier} has an unsupported type")
        maximum_age = value.get("maximum_age_hours", 24)
        if not isinstance(maximum_age, int) or isinstance(maximum_age, bool) or not 1 <= maximum_age <= 24 * 31:
            raise GuardrailsError(f"task contract evidence {identifier} maximum_age_hours must be 1 through 744")
        external = value.get("allow_external_ci_artifact", False)
        if not isinstance(external, bool):
            raise GuardrailsError(f"task contract evidence {identifier} allow_external_ci_artifact must be true or false")
        identifiers.add(identifier)
        result.append(
            {
                "id": identifier,
                "type": kind,
                "maximum_age_hours": maximum_age,
                "allow_external_ci_artifact": external,
            }
        )
    return result


def _coverage_policy(value: object) -> dict[str, Any]:
    """Validate a deliberately small Cobertura regression allowance.

    A zero allowance means "no regression".  The paths remain repository
    relative so report ingestion keeps the same trust boundary as the other
    task evidence types.
    """
    permitted = {
        "baseline_path",
        "current_path",
        "maximum_line_rate_regression",
        "maximum_branch_rate_regression",
    }
    if not isinstance(value, Mapping) or not {"baseline_path", "current_path"}.issubset(value) or set(value) - permitted:
        raise GuardrailsError("task contract coverage_policy has unsupported fields")
    result = {
        "baseline_path": _safe_relative(value["baseline_path"], "coverage baseline_path"),
        "current_path": _safe_relative(value["current_path"], "coverage current_path"),
    }
    if result["baseline_path"] == result["current_path"]:
        raise GuardrailsError("task contract coverage_policy requires distinct baseline_path and current_path")
    allowances = 0
    for field in ("maximum_line_rate_regression", "maximum_branch_rate_regression"):
        if field not in value:
            continue
        allowance = value[field]
        if (
            not isinstance(allowance, (int, float))
            or isinstance(allowance, bool)
            or not math.isfinite(float(allowance))
            or not 0 <= float(allowance) <= 1
        ):
            raise GuardrailsError(f"task contract coverage_policy {field} must be a number from 0 through 1")
        result[field] = float(allowance)
        allowances += 1
    if not allowances:
        raise GuardrailsError("task contract coverage_policy needs at least one allowed regression value")
    return result


def validate_contract(value: object) -> dict[str, Any]:
    """Validate the intentionally small task-contract format without executing it."""
    schema = load_task_schema()
    if not isinstance(value, Mapping):
        raise GuardrailsError("task contract must be a JSON object")
    required = set(schema["required"])
    permitted = required | set(schema["optional_fields"])
    if set(value) - permitted or required - set(value):
        raise GuardrailsError("task contract fields do not match the supported schema")
    if value.get("schema_version") != TASK_SCHEMA_VERSION:
        raise GuardrailsError("task contract has an unsupported schema_version")
    if not _safe_text(value.get("objective"), maximum=1000):
        raise GuardrailsError("task contract objective must be concise non-empty text")
    outcomes = _identifier_entries(value.get("observable_outcomes"), "outcome")
    non_goals = value.get("non_goals")
    if not isinstance(non_goals, list) or not all(_safe_text(item, maximum=500) for item in non_goals):
        raise GuardrailsError("task contract non_goals must be a list of concise text")
    risk_class = value.get("risk_class")
    if risk_class not in _risk_classes():
        raise GuardrailsError("task contract risk_class is not recognised by the current risk model")
    if value.get("status") not in set(schema["statuses"]):
        raise GuardrailsError("task contract has an unsupported status")
    result: dict[str, Any] = {
        "schema_version": TASK_SCHEMA_VERSION,
        "objective": str(value["objective"]).strip(),
        "observable_outcomes": outcomes,
        "non_goals": [str(item).strip() for item in non_goals],
        "risk_class": risk_class,
        "status": value["status"],
    }
    for field in ("allowed_paths", "forbidden_paths"):
        if field in value:
            result[field] = _path_patterns(value[field], field)
    for field in ("maximum_files_changed", "maximum_lines_changed", "maximum_directories_changed"):
        if field in value:
            limit = value[field]
            if not isinstance(limit, int) or isinstance(limit, bool) or limit < 0:
                raise GuardrailsError(f"task contract {field} must be a non-negative integer")
            result[field] = limit
    if "dependency_policy" in value:
        if value["dependency_policy"] not in {"allow", "forbid-new-runtime-dependencies"}:
            raise GuardrailsError("task contract dependency_policy must be allow or forbid-new-runtime-dependencies")
        result["dependency_policy"] = value["dependency_policy"]
    result["required_evidence"] = _required_evidence(value.get("required_evidence"), set(schema["evidence_types"]))
    if "coverage_policy" in value:
        result["coverage_policy"] = _coverage_policy(value["coverage_policy"])
    if "invariants" in value:
        result["invariants"] = _identifier_entries(value["invariants"], "invariant")
    for field in ("review_checkpoints", "halt_conditions"):
        if field in value:
            entries = value[field]
            if not isinstance(entries, list) or not all(_safe_text(item, maximum=500) for item in entries):
                raise GuardrailsError(f"task contract {field} must be concise text")
            result[field] = [str(item).strip() for item in entries]
    if "notes" in value:
        if not _safe_text(value["notes"], maximum=2000):
            raise GuardrailsError("task contract notes must be concise text")
        result["notes"] = str(value["notes"]).strip()
    known_evidence = {item["id"] for item in result["required_evidence"]}
    for invariant in result.get("invariants", []):
        if invariant.get("evidence_id") and invariant["evidence_id"] not in known_evidence:
            raise GuardrailsError(f"task invariant references unknown evidence id: {invariant['evidence_id']}")
    return result


def _repository_root(repo: Path) -> Path:
    try:
        candidate = repo.expanduser()
        if not candidate.is_absolute():
            candidate = Path.cwd() / candidate
        if candidate.is_symlink():
            raise GuardrailsError("repository path must not be a symbolic link")
        root = candidate.resolve(strict=True)
    except OSError as exc:
        raise GuardrailsError(f"repository path cannot be resolved: {repo}") from exc
    if not root.is_dir():
        raise GuardrailsError("repository path must be a real directory")
    return root


def _safe_repo_path(repo: Path, relative: object, label: str, *, require_exists: bool = True) -> Path:
    rendered = _safe_relative(relative, label)
    candidate = repo / rendered
    if require_exists and not candidate.exists():
        raise GuardrailsError(f"{label} is missing: {rendered}")
    for parent in (candidate, *candidate.parents):
        if parent == repo.parent:
            break
        if parent.is_symlink():
            raise GuardrailsError(f"{label} must not traverse a symbolic link")
        if parent == repo:
            break
    resolved = candidate.resolve(strict=False)
    if not path_within(resolved, repo):
        raise GuardrailsError(f"{label} escapes the selected repository")
    return candidate


def _safe_external_report_path(value: object, label: str) -> Path:
    """Return one explicitly declared external CI artifact without following links.

    Ordinary evidence remains repository-relative.  This narrow exception is
    useful when CI has mounted an artifact outside a checkout, but it still
    rejects traversal, links, non-regular files, and oversized input.
    """
    if not isinstance(value, str) or not value or len(value) > 500 or any(ord(character) < 32 for character in value):
        raise GuardrailsError(f"{label} must be a short absolute external CI artifact path")
    candidate = Path(value)
    if not candidate.is_absolute() or ".." in candidate.parts:
        raise GuardrailsError(f"{label} must be an absolute path without parent traversal")
    if candidate.is_symlink() or not candidate.is_file():
        raise GuardrailsError(f"{label} must be a regular external CI artifact file")
    # An absolute CI mount can pass through a platform-owned alias such as
    # /var.  The artifact itself must be regular and non-symlinked; there is no
    # repository root for a parent link to escape once this explicit exception
    # has been declared in both contract and evidence ledger.
    try:
        return candidate.resolve(strict=True)
    except OSError as exc:
        raise GuardrailsError(f"{label} could not be resolved") from exc


def contract_path(repo: Path) -> Path:
    return _repository_root(repo) / TASK_CONTRACT_NAME


def evidence_path(repo: Path) -> Path:
    return _repository_root(repo) / TASK_EVIDENCE_NAME


def load_contract(repo: Path) -> tuple[Path, dict[str, Any]]:
    root = _repository_root(repo)
    path = _safe_repo_path(root, TASK_CONTRACT_NAME, "task contract")
    return path, validate_contract(_load_json(path, "task contract"))


def _contract_digest(path: Path) -> str:
    return file_hash(path)


def _repository_identifier(root: Path) -> str:
    return sha256(str(root).encode("utf-8"))


def _text_digest(value: object) -> str:
    return sha256(str(value).encode("utf-8"))


def _assurance_contract_summary(contract: Mapping[str, Any]) -> dict[str, Any]:
    """Keep assurance-critical metadata without retaining task prose."""
    return {
        "objective_digest": _text_digest(contract["objective"]),
        "outcomes": [
            {
                "id": item["id"],
                "description_digest": _text_digest(item["description"]),
                **({"evidence_id": item["evidence_id"]} if "evidence_id" in item else {}),
            }
            for item in contract["observable_outcomes"]
        ],
        "required_evidence": list(contract.get("required_evidence", [])),
        "invariants": [
            {
                "id": item["id"],
                "description_digest": _text_digest(item["description"]),
                **({"evidence_id": item["evidence_id"]} if "evidence_id" in item else {}),
            }
            for item in contract.get("invariants", [])
        ],
        "allowed_paths": list(contract.get("allowed_paths", [])),
        "forbidden_paths": list(contract.get("forbidden_paths", [])),
        "change_limits": {
            field: contract[field]
            for field in ("maximum_files_changed", "maximum_lines_changed", "maximum_directories_changed")
            if field in contract
        },
        "dependency_policy": contract.get("dependency_policy", "allow"),
        "coverage_policy": dict(contract["coverage_policy"]) if isinstance(contract.get("coverage_policy"), Mapping) else None,
        "risk_class": contract["risk_class"],
        "halt_condition_digests": [_text_digest(item) for item in contract.get("halt_conditions", [])],
    }


def _validate_contract_provenance(value: object) -> dict[str, Any]:
    required = {
        "schema_version",
        "repository_identifier_hash",
        "contract_digest",
        "assurance_summary",
        "established_at",
    }
    if not isinstance(value, Mapping) or set(value) != required or value.get("schema_version") != 1:
        raise GuardrailsError("task-contract provenance record has an unsupported schema")
    for field in ("repository_identifier_hash", "contract_digest"):
        if not isinstance(value.get(field), str) or re.fullmatch(r"[0-9a-f]{64}", value[field]) is None:
            raise GuardrailsError(f"task-contract provenance {field} is invalid")
    if not isinstance(value.get("assurance_summary"), Mapping):
        raise GuardrailsError("task-contract provenance assurance_summary is invalid")
    established = _parse_timestamp(value.get("established_at"))
    if established is None:
        raise GuardrailsError("task-contract provenance established_at is invalid")
    return dict(value)


def _contract_continuity(home: Path, root: Path, contract_digest: str) -> tuple[str, dict[str, Any] | None]:
    records = state.load_state(home).get("task_contracts", [])
    repository_identifier = _repository_identifier(root)
    selected: dict[str, Any] | None = None
    for raw in records:
        record = _validate_contract_provenance(raw)
        if record["repository_identifier_hash"] != repository_identifier:
            continue
        if selected is not None:
            raise GuardrailsError("installation state has duplicate task-contract provenance records")
        selected = record
    if selected is None:
        return "unavailable", None
    return ("current" if selected["contract_digest"] == contract_digest else "changed"), selected


def establish_contract(
    repo: Path,
    home: Path,
    *,
    dry_run: bool = False,
    now: dt.datetime | None = None,
    input_stream: Any = None,
    prompt_stream: Any = None,
) -> dict[str, Any]:
    """Explicitly establish or replace one repository's assurance contract baseline."""
    root = _repository_root(repo)
    contract_file, contract = load_contract(root)
    record = _validate_contract_provenance(
        {
            "schema_version": 1,
            "repository_identifier_hash": _repository_identifier(root),
            "contract_digest": _contract_digest(contract_file),
            "assurance_summary": _assurance_contract_summary(contract),
            "established_at": _iso(now or _utc_now()),
        }
    )
    if dry_run:
        return {**record, "established": False, "dry_run": True}
    input_stream = input_stream or sys.stdin
    prompt_stream = prompt_stream or sys.stderr
    if not input_stream.isatty() or not prompt_stream.isatty():
        raise GuardrailsError("task-contract establishment requires an interactive TTY confirmation")
    confirmation = f"ESTABLISH TASK CONTRACT {record['contract_digest']}"
    print(
        "Review the current contract before establishing it as the local assurance baseline. "
        "This interaction does not prove human identity.",
        file=prompt_stream,
    )
    print(f"Type exactly: {confirmation}", file=prompt_stream)
    if input_stream.readline().rstrip("\r\n") != confirmation:
        raise GuardrailsError("task-contract confirmation did not match; the baseline was not changed")
    current = state.load_state(home)
    records = []
    for item in current.get("task_contracts", []):
        validated = _validate_contract_provenance(item)
        if validated["repository_identifier_hash"] != record["repository_identifier_hash"]:
            records.append(validated)
    records.append(record)
    current["task_contracts"] = sorted(records, key=lambda item: item["repository_identifier_hash"])
    current["format_version"] = state.FORMAT_VERSION
    state.save_state(home, current, dry_run=False)
    return {**record, "established": True, "dry_run": False}


def _report_digest(path: Path) -> str:
    return file_hash(path)


def repository_state_digest(repo: Path) -> str | None:
    """Bind task evidence through the repository's existing Git-analysis owner."""
    return complexity.repository_state_digest(
        _repository_root(repo),
        excluded_paths=tuple(TASK_METADATA_NAMES),
    )


def _read_report(
    path: Path,
    repo: Path,
    label: str,
    *,
    external_ci_artifact: bool = False,
) -> tuple[bytes, Path]:
    target = (
        _safe_external_report_path(str(path), label)
        if external_ci_artifact
        else _safe_repo_path(repo, path.as_posix(), label)
    )
    if target.is_symlink() or not target.is_file():
        raise GuardrailsError(f"{label} must be a regular file")
    try:
        data = target.read_bytes()
    except OSError as exc:
        raise GuardrailsError(f"{label} could not be read") from exc
    if len(data) > MAX_REPORT_BYTES:
        raise GuardrailsError(f"{label} exceeds the {MAX_REPORT_BYTES}-byte limit")
    return data, target


def _safe_label(value: object, fallback: str = "unknown") -> str:
    if not isinstance(value, str):
        return fallback
    candidate = value.strip()
    return candidate if re.fullmatch(r"[A-Za-z0-9_.:-]{1,120}", candidate) else fallback


def _relative_artifact(value: object, repo: Path) -> str:
    if not isinstance(value, str) or not value:
        return "<unknown>"
    # URL parsers may discard ASCII newlines and tabs. Reject them before any
    # normalization so an untrusted report cannot turn an unsafe label into a
    # plausible repository path.
    if any(ord(character) < 32 or ord(character) == 127 for character in value):
        return "<external>"
    try:
        parsed = urlsplit(value)
    except ValueError:
        return "<external>"
    if parsed.scheme:
        if parsed.scheme.lower() != "file" or parsed.netloc not in {"", "localhost"}:
            return "<external>"
        candidate = unquote(parsed.path)
        if re.match(r"^/[A-Za-z]:/", candidate):
            candidate = candidate[1:]
    else:
        candidate = unquote(parsed.path or value)
    candidate = candidate.replace("\\", "/")
    raw_path = Path(candidate)
    host_mismatched_windows_absolute = PureWindowsPath(candidate).is_absolute() and not raw_path.is_absolute()
    if (
        len(candidate) > 500
        or any(ord(character) < 32 or ord(character) == 127 for character in candidate)
        or re.match(r"^[A-Za-z]:(?![\\/])", candidate)
        or host_mismatched_windows_absolute
        or ".." in raw_path.parts
    ):
        return "<external>"
    target = raw_path.resolve(strict=False) if raw_path.is_absolute() else (repo / raw_path).resolve(strict=False)
    if not path_within(target, repo):
        return "<external>"
    return target.relative_to(repo).as_posix()


def parse_sarif(path: Path, repo: Path, *, external_ci_artifact: bool = False) -> dict[str, Any]:
    root = _repository_root(repo)
    data, target = _read_report(path, root, "SARIF report", external_ci_artifact=external_ci_artifact)
    try:
        value = json.loads(data.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError, RecursionError) as exc:
        raise EvidenceParseError("SARIF report is malformed or exceeds supported JSON nesting") from exc
    if not isinstance(value, Mapping) or value.get("version") != "2.1.0" or not isinstance(value.get("runs"), list):
        raise EvidenceParseError("SARIF report must use version 2.1.0 with runs")
    findings: list[dict[str, Any]] = []
    malformed = 0
    for run_index, run in enumerate(value["runs"]):
        if not isinstance(run, Mapping):
            malformed += 1
            continue
        tool = run.get("tool")
        driver = tool.get("driver") if isinstance(tool, Mapping) else None
        raw_tool_name = driver.get("name") if isinstance(driver, Mapping) else None
        tool_name = _safe_label(raw_tool_name)
        tool_reliable = isinstance(raw_tool_name, str) and tool_name != "unknown"
        results = run.get("results", [])
        if not isinstance(results, list):
            malformed += 1
            continue
        for result_index, result in enumerate(results):
            if not isinstance(result, Mapping):
                malformed += 1
                continue
            rule = _safe_label(result.get("ruleId"))
            locations = result.get("locations")
            location = locations[0] if isinstance(locations, list) and locations and isinstance(locations[0], Mapping) else {}
            physical = location.get("physicalLocation") if isinstance(location, Mapping) else {}
            artifact = physical.get("artifactLocation") if isinstance(physical, Mapping) else {}
            region = physical.get("region") if isinstance(physical, Mapping) else {}
            artifact_path = _relative_artifact(artifact.get("uri") if isinstance(artifact, Mapping) else None, root)
            line = region.get("startLine") if isinstance(region, Mapping) else None
            column = region.get("startColumn") if isinstance(region, Mapping) else None
            line_value = line if isinstance(line, int) and not isinstance(line, bool) and line > 0 else 0
            column_value = column if isinstance(column, int) and not isinstance(column, bool) and column > 0 else 0
            fingerprints = result.get("partialFingerprints")
            fingerprint = ""
            if isinstance(fingerprints, Mapping):
                for key in sorted(item for item in fingerprints if isinstance(item, str)):
                    candidate = fingerprints.get(key)
                    if (
                        isinstance(candidate, str)
                        and candidate
                        and len(candidate) <= 256
                        and not any(ord(character) < 32 or ord(character) == 127 for character in candidate)
                    ):
                        fingerprint = sha256(f"{key}\0{candidate}".encode("utf-8"))[:24]
                        break
            level = str(result.get("level", "warning")).lower()
            if level not in {"error", "warning", "note", "none"}:
                level = "warning"
            stable_location = artifact_path not in {"<unknown>", "<external>"} and bool(line_value or column_value)
            identity_reliable = tool_reliable and bool(fingerprint or stable_location)
            if identity_reliable and fingerprint:
                identity = "|".join((tool_name, rule, "fingerprint", fingerprint))
            elif identity_reliable:
                identity = "|".join((tool_name, rule, "location", artifact_path, str(line_value), str(column_value)))
            else:
                identity = f"{tool_name}|identity-deficient|run-{run_index}|result-{result_index}"
            findings.append(
                {
                    "identity": identity,
                    "identity_reliable": identity_reliable,
                    "identity_limitation": None if identity_reliable else "insufficient tool/fingerprint/repository-location identity",
                    "tool": tool_name,
                    "rule_id": rule,
                    "level": level,
                    "path": artifact_path,
                    "_ordinal": f"{run_index}:{result_index}",
                }
            )
    identity_counts: dict[str, int] = {}
    for item in findings:
        if item["identity_reliable"]:
            identity_counts[item["identity"]] = identity_counts.get(item["identity"], 0) + 1
    for item in findings:
        if item["identity_reliable"] and identity_counts[item["identity"]] > 1:
            item["identity"] = f"{item['identity']}|identity-deficient|{item['_ordinal']}"
            item["identity_reliable"] = False
            item["identity_limitation"] = "analyzer identity collides within this report"
    findings.sort(key=lambda item: item["identity"])
    grouped: dict[str, int] = {}
    for item in findings:
        key = f"{item['tool']}:{item['rule_id']}"
        grouped[key] = grouped.get(key, 0) + 1
    return {
        "schema_version": PARSER_VERSION,
        "type": "sarif",
        "report_digest": _report_digest(target),
        "total_findings": len(findings),
        "error_findings": sum(item["level"] == "error" for item in findings),
        "findings_by_tool_rule": dict(sorted(grouped.items())),
        "malformed_portions": malformed,
        "identity_deficient_findings": sum(not item["identity_reliable"] for item in findings),
        "_findings": findings,
    }


def _safe_xml(data: bytes, label: str) -> ET.Element:
    lowered = data.lower()
    if b"<!doctype" in lowered or b"<!entity" in lowered:
        raise EvidenceParseError(f"{label} must not contain DTD or entity declarations")
    try:
        return ET.fromstring(data)
    except ET.ParseError as exc:
        raise EvidenceParseError(f"{label} is malformed XML") from exc


def _number(value: object) -> float | None:
    try:
        number = float(str(value))
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def parse_cobertura(path: Path, repo: Path, *, external_ci_artifact: bool = False) -> dict[str, Any]:
    root = _repository_root(repo)
    data, target = _read_report(path, root, "Cobertura report", external_ci_artifact=external_ci_artifact)
    document = _safe_xml(data, "Cobertura report")
    if document.tag.rsplit("}", 1)[-1] != "coverage":
        raise EvidenceParseError("Cobertura report must have a coverage root element")
    line = _number(document.attrib.get("line-rate"))
    branch = _number(document.attrib.get("branch-rate")) if "branch-rate" in document.attrib else None
    if (
        line is None
        or not 0 <= line <= 1
        or ("branch-rate" in document.attrib and (branch is None or not 0 <= branch <= 1))
    ):
        raise EvidenceParseError("Cobertura rates must be finite values from 0 through 1")
    counts: dict[str, int] = {}
    for field in ("lines-covered", "lines-valid", "branches-covered", "branches-valid", "timestamp"):
        if field not in document.attrib:
            continue
        raw = document.attrib[field].strip()
        limit = MAX_REPORT_TIMESTAMP if field == "timestamp" else MAX_REPORT_COUNT
        if re.fullmatch(r"(?:0|[1-9][0-9]*)", raw) is None or int(raw) > limit:
            raise EvidenceParseError(f"Cobertura {field} must be a bounded non-negative integer")
        counts[field] = int(raw)
    for covered, valid in (("lines-covered", "lines-valid"), ("branches-covered", "branches-valid")):
        if covered in counts and valid in counts and counts[covered] > counts[valid]:
            raise EvidenceParseError(f"Cobertura {covered} cannot exceed {valid}")
    for rate_field, covered, valid in (
        ("line-rate", "lines-covered", "lines-valid"),
        ("branch-rate", "branches-covered", "branches-valid"),
    ):
        if rate_field not in document.attrib or covered not in counts or valid not in counts or counts[valid] == 0:
            continue
        declared = Decimal(document.attrib[rate_field].strip())
        expected = Decimal(counts[covered]) / Decimal(counts[valid])
        # Reporters commonly round rates.  Permit at most one unit in the
        # declared last decimal place, while keeping exact zero/one aggregates
        # exact so contradictory pass/fail boundaries cannot be hidden.
        tolerance = Decimal(0) if expected in {Decimal(0), Decimal(1)} else Decimal(1).scaleb(min(0, declared.as_tuple().exponent))
        if abs(declared - expected) > tolerance:
            raise EvidenceParseError(f"Cobertura {rate_field} is inconsistent with {covered} and {valid}")
    if "complexity" in document.attrib:
        complexity_value = _number(document.attrib["complexity"])
        if complexity_value is None or not 0 <= complexity_value <= MAX_REPORT_SECONDS:
            raise EvidenceParseError("Cobertura complexity must be a bounded finite non-negative number")
    return {
        "schema_version": PARSER_VERSION,
        "type": "cobertura",
        "report_digest": _report_digest(target),
        "line_rate": line,
        "branch_rate": branch,
    }


def _junit_count(element: ET.Element, field: str) -> int:
    raw = element.attrib[field].strip()
    if re.fullmatch(r"(?:0|[1-9][0-9]*)", raw) is None:
        raise EvidenceParseError(f"JUnit {field} must be a non-negative integer")
    value = int(raw)
    if value > MAX_REPORT_COUNT:
        raise EvidenceParseError(f"JUnit {field} exceeds the supported count limit")
    return value


def _junit_seconds(element: ET.Element) -> float:
    if "time" not in element.attrib:
        return 0.0
    value = _number(element.attrib["time"])
    if value is None or not 0 <= value <= MAX_REPORT_SECONDS:
        raise EvidenceParseError("JUnit time must be a finite non-negative number")
    return value


def _junit_coherent(counts: Mapping[str, int]) -> None:
    if counts["failures"] + counts["errors"] + counts["skipped"] > counts["tests"]:
        raise EvidenceParseError("JUnit failure, error, and skipped counts exceed total tests")


def _junit_summary(element: ET.Element) -> tuple[dict[str, int], float, bool]:
    name = element.tag.rsplit("}", 1)[-1]
    if name == "testcase":
        outcomes = [
            child.tag.rsplit("}", 1)[-1]
            for child in element
            if child.tag.rsplit("}", 1)[-1] in {"failure", "error", "skipped"}
        ]
        if len(outcomes) > 1:
            raise EvidenceParseError("JUnit testcase has multiple terminal outcomes")
        return (
            {
                "tests": 1,
                "failures": int(outcomes == ["failure"]),
                "errors": int(outcomes == ["error"]),
                "skipped": int(outcomes == ["skipped"]),
            },
            _junit_seconds(element),
            True,
        )

    children = [
        _junit_summary(child)
        for child in element
        if child.tag.rsplit("}", 1)[-1] in {"testcase", "testsuite"}
    ]
    useful_children = any(useful for _, _, useful in children)
    derived = {
        field: sum(summary[field] for summary, _, _ in children)
        for field in ("tests", "failures", "errors", "skipped")
    }
    duration = sum(seconds for _, seconds, _ in children)
    present = {field: _junit_count(element, field) for field in derived if field in element.attrib}
    if useful_children:
        for field, value in present.items():
            if value != derived[field]:
                raise EvidenceParseError(f"JUnit {field} aggregate is inconsistent with child results")
        _junit_seconds(element)  # Validate a present aggregate duration without double-counting it.
        _junit_coherent(derived)
        return derived, duration, True

    if present:
        if not {"tests", "failures", "errors"}.issubset(present):
            raise EvidenceParseError("JUnit aggregate-only suites require tests, failures, and errors")
        counts = {**present, "skipped": present.get("skipped", 0)}
        _junit_coherent(counts)
        return counts, _junit_seconds(element), True
    _junit_seconds(element)
    return {"tests": 0, "failures": 0, "errors": 0, "skipped": 0}, 0.0, False


def parse_junit(path: Path, repo: Path, *, external_ci_artifact: bool = False) -> dict[str, Any]:
    root = _repository_root(repo)
    data, target = _read_report(path, root, "JUnit report", external_ci_artifact=external_ci_artifact)
    document = _safe_xml(data, "JUnit report")
    if document.tag.rsplit("}", 1)[-1] not in {"testsuite", "testsuites"}:
        raise EvidenceParseError("JUnit report must have testsuite or testsuites root")
    counts, duration, has_results = _junit_summary(document)
    sufficient = has_results and counts["tests"] > 0
    return {
        "schema_version": PARSER_VERSION,
        "type": "junit",
        "report_digest": _report_digest(target),
        "parsed": True,
        "valid": True,
        "sufficient_for_completion": sufficient,
        **counts,
        "duration_seconds": round(duration, 3),
    }


def _public_report(value: Mapping[str, Any]) -> dict[str, Any]:
    return {key: item for key, item in value.items() if not key.startswith("_")}


def compare_reports(
    repo: Path,
    *,
    baseline_sarif: Path | None = None,
    current_sarif: Path | None = None,
    baseline_coverage: Path | None = None,
    current_coverage: Path | None = None,
    junit: Path | None = None,
) -> dict[str, Any]:
    """Compare supplied local reports; callers own analyzer execution."""
    root = _repository_root(repo)
    result: dict[str, Any] = {"schema_version": 1, "reports": {}, "findings": []}
    if (baseline_sarif is None) != (current_sarif is None):
        raise GuardrailsError("SARIF comparison requires both --baseline-sarif and --current-sarif")
    if (baseline_coverage is None) != (current_coverage is None):
        raise GuardrailsError("coverage comparison requires both --baseline-coverage and --current-coverage")
    if baseline_sarif is not None and current_sarif is not None:
        before = parse_sarif(baseline_sarif, root)
        after = parse_sarif(current_sarif, root)
        before_reliable = [item for item in before["_findings"] if item["identity_reliable"]]
        after_reliable = [item for item in after["_findings"] if item["identity_reliable"]]
        before_deficient = [item for item in before["_findings"] if not item["identity_reliable"]]
        after_deficient = [item for item in after["_findings"] if not item["identity_reliable"]]
        before_ids = {item["identity"] for item in before_reliable}
        after_ids = {item["identity"] for item in after_reliable}
        new_ids = after_ids - before_ids
        new_count = len(new_ids) + len(after_deficient)
        resolved_count = len(before_ids - after_ids) + len(before_deficient)
        new_error = sum(item["identity"] in new_ids and item["level"] == "error" for item in after_reliable) + sum(
            item["level"] == "error" for item in after_deficient
        )
        result["reports"]["sarif"] = {
            "baseline": _public_report(before),
            "current": _public_report(after),
            "new_findings": new_count,
            "resolved_findings": resolved_count,
            "unchanged_findings": len(before_ids & after_ids),
            "identity_deficient_baseline": len(before_deficient),
            "identity_deficient_current": len(after_deficient),
            "new_error_or_high_severity_findings": new_error,
        }
        if new_count:
            result["findings"].append({"id": "new-static-analysis-findings", "level": "review", "evidence": f"{new_count} new or identity-deficient SARIF finding(s)"})
        if new_error:
            result["findings"].append({"id": "new-high-severity-findings", "level": "review", "evidence": f"{new_error} new SARIF error-level finding(s)"})
    if baseline_coverage is not None and current_coverage is not None:
        before = parse_cobertura(baseline_coverage, root)
        after = parse_cobertura(current_coverage, root)
        line_delta = round(after["line_rate"] - before["line_rate"], 6)
        branch_delta = (
            round(after["branch_rate"] - before["branch_rate"], 6)
            if before["branch_rate"] is not None and after["branch_rate"] is not None
            else None
        )
        result["reports"]["cobertura"] = {
            "baseline": before,
            "current": after,
            "line_rate_delta": line_delta,
            "branch_rate_delta": branch_delta,
        }
        if line_delta < 0 or (branch_delta is not None and branch_delta < 0):
            result["findings"].append({"id": "coverage-regression", "level": "review", "evidence": "coverage decreased in the supplied reports"})
    if junit is not None:
        summary = parse_junit(junit, root)
        result["reports"]["junit"] = summary
        if not summary["sufficient_for_completion"]:
            result["findings"].append(
                {"id": "verification-insufficient", "level": "review", "evidence": "JUnit report contains no completed tests"}
            )
        elif summary["failures"] or summary["errors"]:
            result["findings"].append({"id": "verification-failures", "level": "review", "evidence": f"{summary['failures']} failure(s), {summary['errors']} error(s)"})
    result["findings"].sort(key=lambda item: (item["id"], item["evidence"]))
    return result


def _load_evidence_ledger(repo: Path) -> dict[str, Any]:
    path = evidence_path(repo)
    if not path.exists():
        return {"schema_version": EVIDENCE_SCHEMA_VERSION, "evidence": []}
    value = _load_json(path, "task evidence ledger")
    if value.get("schema_version") != EVIDENCE_SCHEMA_VERSION or not isinstance(value.get("evidence"), list):
        raise GuardrailsError("task evidence ledger has an unsupported schema")
    return value


def _validate_ledger_entry(repo: Path, value: object) -> dict[str, Any]:
    if not isinstance(value, Mapping) or set(value) - {
        "id", "type", "path", "manual_review_id", "captured_at", "repository_state_digest", "contract_digest", "report_digest", "parser_version", "result", "external_ci_artifact"
    }:
        raise GuardrailsError("task evidence entry has unsupported fields")
    required = {"id", "type", "captured_at", "repository_state_digest", "contract_digest", "parser_version", "result"}
    if required - set(value):
        raise GuardrailsError("task evidence entry is missing required metadata")
    identifier = value.get("id")
    kind = value.get("type")
    if not isinstance(identifier, str) or not NAME_RE.fullmatch(identifier) or not isinstance(kind, str):
        raise GuardrailsError("task evidence entry id or type is invalid")
    captured = _parse_timestamp(value.get("captured_at"))
    if captured is None:
        raise GuardrailsError("task evidence captured_at must be a timezone-aware ISO-8601 timestamp")
    for field in ("repository_state_digest", "contract_digest"):
        digest = value.get(field)
        if not isinstance(digest, str) or re.fullmatch(r"[0-9a-f]{64}", digest) is None:
            raise GuardrailsError(f"task evidence {field} must be a SHA-256 digest")
    if value.get("parser_version") != PARSER_VERSION or value.get("result") not in {"passed", "failed"}:
        raise GuardrailsError("task evidence parser_version or result is invalid")
    manual = kind in {"manual-review", "security-review", "compatibility-review", "change-diff-review"}
    if manual:
        if set(value) - required - {"manual_review_id"} or not isinstance(value.get("manual_review_id"), str) or not NAME_RE.fullmatch(value["manual_review_id"]):
            raise GuardrailsError("manual task evidence requires a portable manual_review_id and no report path")
    else:
        if (
            set(value) - required - {"path", "report_digest", "external_ci_artifact"}
            or not isinstance(value.get("path"), str)
            or not isinstance(value.get("report_digest"), str)
            or re.fullmatch(r"[0-9a-f]{64}", value["report_digest"]) is None
        ):
            raise GuardrailsError("report task evidence requires a path and captured SHA-256 report digest")
        external = value.get("external_ci_artifact", False)
        if not isinstance(external, bool):
            raise GuardrailsError("task evidence external_ci_artifact must be true or false")
        if external:
            _safe_external_report_path(value["path"], "task evidence path")
        else:
            _safe_repo_path(repo, value["path"], "task evidence path")
    return dict(value)


def _evidence_summary(repo: Path, entry: Mapping[str, Any]) -> dict[str, Any]:
    kind = str(entry["type"])
    result: dict[str, Any] = {
        "id": entry["id"],
        "type": kind,
        "captured_at": entry["captured_at"],
        "repository_state_digest": entry["repository_state_digest"],
        "contract_digest": entry["contract_digest"],
        "parser_version": entry["parser_version"],
        "declared_result": entry["result"],
    }
    if kind in {"manual-review", "security-review", "compatibility-review", "change-diff-review"}:
        result["manual"] = True
        result["manual_review_id"] = entry["manual_review_id"]
        result["parsed_summary"] = {"result": entry["result"], "manual": True}
        return result
    relative_path = Path(entry["path"])
    external = bool(entry.get("external_ci_artifact", False))
    if external:
        _safe_external_report_path(entry["path"], "task evidence path")
    else:
        _safe_repo_path(repo, entry["path"], "task evidence path")
    if kind == "sarif":
        parsed = parse_sarif(relative_path, repo, external_ci_artifact=external)
        result["parsed_summary"] = _public_report(parsed)
        actual_passed = True
    elif kind == "cobertura":
        parsed = parse_cobertura(relative_path, repo, external_ci_artifact=external)
        result["parsed_summary"] = parsed
        actual_passed = True
    elif kind == "junit":
        parsed = parse_junit(relative_path, repo, external_ci_artifact=external)
        result["parsed_summary"] = parsed
        actual_passed = (
            parsed["valid"]
            and parsed["sufficient_for_completion"]
            and parsed["failures"] == 0
            and parsed["errors"] == 0
        )
    else:
        raise GuardrailsError(f"task evidence type is unsupported: {kind}")
    result["report_digest"] = parsed["report_digest"]
    result["captured_report_digest"] = entry["report_digest"]
    result["report_digest_matches_capture"] = parsed["report_digest"] == entry["report_digest"]
    result["path"] = "<external-ci-artifact>" if external else Path(entry["path"]).as_posix()
    result["external_ci_artifact"] = external
    result["parsed_passed"] = actual_passed
    return result


def _match_path(path: str, pattern: str) -> bool:
    return fnmatch.fnmatchcase(path, pattern) or (pattern.startswith("**/") and fnmatch.fnmatchcase(path, pattern[3:]))


def _scope_report(contract: Mapping[str, Any], complexity_result: Mapping[str, Any], paths: Sequence[str]) -> tuple[list[dict[str, str]], list[dict[str, str]]]:
    violations: list[dict[str, str]] = []
    warnings: list[dict[str, str]] = []
    allowed = contract.get("allowed_paths")
    if isinstance(allowed, list):
        outside = [path for path in paths if not any(_match_path(path, pattern) for pattern in allowed)]
        if outside:
            violations.append({"id": "paths-outside-allowed-set", "detail": f"{len(outside)} changed path(s) are outside allowed_paths"})
    forbidden = contract.get("forbidden_paths")
    if isinstance(forbidden, list):
        blocked = [path for path in paths if any(_match_path(path, pattern) for pattern in forbidden)]
        if blocked:
            violations.append({"id": "forbidden-path-changed", "detail": f"{len(blocked)} forbidden path(s) changed"})
    checks = (
        ("maximum_files_changed", "files_changed", "files-changed-limit"),
        ("maximum_lines_changed", None, "lines-changed-limit"),
        ("maximum_directories_changed", "directory_spread", "directories-changed-limit"),
    )
    for contract_field, result_field, identifier in checks:
        if contract_field not in contract:
            continue
        actual = (
            int(complexity_result.get("lines_added", 0)) + int(complexity_result.get("lines_removed", 0))
            if result_field is None
            else int(complexity_result.get(result_field, 0))
        )
        maximum = int(contract[contract_field])
        if actual > maximum:
            violations.append({"id": identifier, "detail": f"{actual} exceeds declared limit {maximum}"})
    if contract.get("dependency_policy") == "forbid-new-runtime-dependencies" and complexity_result.get("new_runtime_dependencies"):
        violations.append({"id": "new-dependency-violates-policy", "detail": "new runtime dependency evidence is present"})
    introduced = complexity_result.get("implementation_languages_introduced", [])
    if introduced:
        warnings.append({"id": "new-implementation-language", "detail": "new implementation language evidence is present"})
    high_risk = complexity_result.get("high_risk_paths", [])
    if high_risk:
        warnings.append({"id": "high-risk-paths", "detail": "high-risk path classes changed: " + ", ".join(sorted(map(str, high_risk)))})
        if contract.get("risk_class") == "normal":
            violations.append(
                {
                    "id": "unexpected-high-risk-paths",
                    "detail": "high-risk path classes changed while the task contract declares normal risk",
                }
            )
    if any(item.get("id") == "source-without-tests" for item in complexity_result.get("signals", []) if isinstance(item, Mapping)):
        warnings.append({"id": "source-without-tests", "detail": "source changed without a changed test file"})
    if any(item.get("id") == "generated-output-dominates" for item in complexity_result.get("signals", []) if isinstance(item, Mapping)):
        warnings.append({"id": "generated-output-dominance", "detail": "generated output dominates the changed-file surface"})
    return violations, warnings


def _changed_paths(repo: Path) -> list[str]:
    return [
        path
        for path in complexity.working_tree_paths(_repository_root(repo), excluded_paths=tuple(TASK_METADATA_NAMES))
        if complexity.in_scope_path(path, task_assurance=True)
    ]


def task_status(repo: Path, *, home: Path | None = None, now: dt.datetime | None = None) -> dict[str, Any]:
    root = _repository_root(repo)
    contract_file, contract = load_contract(root)
    now = now or _utc_now()
    repository_result = complexity.repository_state(root, excluded_paths=tuple(TASK_METADATA_NAMES))
    current_digest = repository_result["digest"]
    contract_digest = _contract_digest(contract_file)
    continuity, provenance = _contract_continuity(home or Path.home(), root, contract_digest)
    complexity_result = complexity.analyse(
        root,
        task_assurance=True,
        excluded_paths=tuple(TASK_METADATA_NAMES),
    )
    paths = _changed_paths(root)
    violations, warnings = _scope_report(contract, complexity_result, paths)
    ledger = _load_evidence_ledger(root)
    entries: dict[str, dict[str, Any]] = {}
    ledger_errors: list[dict[str, str]] = []
    for raw in ledger["evidence"]:
        try:
            entry = _validate_ledger_entry(root, raw)
        except GuardrailsError as exc:
            ledger_errors.append({"id": "malformed-evidence-entry", "detail": str(exc)})
            continue
        if entry["id"] in entries:
            ledger_errors.append({"id": "duplicate-evidence-entry", "detail": f"duplicate evidence id: {entry['id']}"})
            continue
        entries[entry["id"]] = entry
    evidence: list[dict[str, Any]] = []
    gaps: list[dict[str, str]] = list(ledger_errors)
    dependency_policy = contract.get("dependency_policy")
    ambiguous_dependencies = list(complexity_result.get("ambiguous_dependency_manifests", []))
    if dependency_policy == "forbid-new-runtime-dependencies" and ambiguous_dependencies:
        gaps.append(
            {
                "id": "dependency-assurance-unavailable",
                "detail": f"{len(ambiguous_dependencies)} recognised dependency file change(s) cannot be parsed deterministically",
            }
        )
    evidence_states: dict[str, str] = {}
    for required in contract["required_evidence"]:
        entry = entries.get(required["id"])
        if entry is None:
            evidence.append({"id": required["id"], "type": required["type"], "state": "missing"})
            evidence_states[required["id"]] = "missing"
            gaps.append({"id": "required-evidence-missing", "detail": f"{required['id']} is missing"})
            continue
        if entry["type"] != required["type"]:
            evidence.append({"id": required["id"], "type": required["type"], "state": "mismatched"})
            evidence_states[required["id"]] = "mismatched"
            gaps.append({"id": "evidence-type-mismatch", "detail": f"{required['id']} type does not match the contract"})
            continue
        if bool(entry.get("external_ci_artifact", False)) and not required["allow_external_ci_artifact"]:
            evidence.append({"id": required["id"], "type": required["type"], "state": "mismatched"})
            evidence_states[required["id"]] = "mismatched"
            gaps.append(
                {
                    "id": "external-ci-artifact-not-allowed",
                    "detail": f"{required['id']} uses an external CI artifact not allowed by the task contract",
                }
            )
            continue
        summary: dict[str, Any]
        try:
            summary = _evidence_summary(root, entry)
        except EvidenceParseError as exc:
            evidence.append({"id": required["id"], "type": required["type"], "state": "malformed"})
            evidence_states[required["id"]] = "malformed"
            gaps.append({"id": "evidence-malformed", "detail": f"{required['id']}: {exc}"})
            continue
        except GuardrailsError as exc:
            evidence.append({"id": required["id"], "type": required["type"], "state": "unavailable"})
            evidence_states[required["id"]] = "unavailable"
            gaps.append({"id": "evidence-unavailable", "detail": f"{required['id']}: {exc}"})
            continue
        captured = _parse_timestamp(entry["captured_at"])
        stale = captured is None or captured > now or captured < now - dt.timedelta(hours=required["maximum_age_hours"])
        insufficient = summary.get("parsed_summary", {}).get("sufficient_for_completion") is False
        failed = entry["result"] != "passed" or (summary.get("parsed_passed") is False and not insufficient)
        report_mismatch = summary.get("report_digest_matches_capture") is False
        state = "failed"
        gap: dict[str, str] | None = {"id": "evidence-failed", "detail": f"{required['id']} did not pass"} if failed else None
        if insufficient:
            state = "insufficient"
            gap = {"id": "evidence-insufficient", "detail": f"{required['id']} contains no completed test results"}
        elif not failed and current_digest is None:
            state = "unavailable"
            gap = {"id": "repository-state-unavailable", "detail": "Git state is unavailable for evidence binding"}
        elif not failed and report_mismatch:
            state = "report-mismatch"
            gap = {"id": "evidence-report-mismatch", "detail": f"{required['id']} report digest changed after capture"}
        elif not failed and entry["repository_state_digest"] != current_digest:
            state = "state-mismatch"
            gap = {"id": "evidence-state-mismatch", "detail": f"{required['id']} is bound to a different repository state"}
        elif not failed and entry["contract_digest"] != contract_digest:
            state = "contract-mismatch"
            gap = {"id": "evidence-contract-mismatch", "detail": f"{required['id']} is bound to a different task contract"}
        elif not failed and stale:
            state = "stale"
            gap = {"id": "evidence-stale", "detail": f"{required['id']} is outside its allowed freshness window"}
        elif not failed:
            state = "fresh"
        evidence.append({**summary, "state": state})
        evidence_states[required["id"]] = state
        if gap is not None:
            gaps.append(gap)

    coverage: dict[str, Any] | None = None
    coverage_policy = contract.get("coverage_policy")
    if isinstance(coverage_policy, Mapping):
        try:
            comparison = compare_reports(
                root,
                baseline_coverage=Path(str(coverage_policy["baseline_path"])),
                current_coverage=Path(str(coverage_policy["current_path"])),
            )
            coverage = dict(comparison["reports"]["cobertura"])
        except GuardrailsError as exc:
            gaps.append({"id": "coverage-evidence-unavailable", "detail": str(exc)})
        else:
            line_delta = float(coverage["line_rate_delta"])
            line_allowance = coverage_policy.get("maximum_line_rate_regression")
            if isinstance(line_allowance, (int, float)) and line_delta < -float(line_allowance):
                violations.append(
                    {
                        "id": "coverage-regression",
                        "detail": f"line-rate regression {-line_delta:.6f} exceeds declared allowance {float(line_allowance):.6f}",
                    }
                )
            branch_allowance = coverage_policy.get("maximum_branch_rate_regression")
            branch_delta = coverage.get("branch_rate_delta")
            if branch_allowance is not None and branch_delta is None:
                gaps.append(
                    {
                        "id": "coverage-branch-unavailable",
                        "detail": "branch-rate evidence is required by the task contract but absent from a supplied report",
                    }
                )
            elif isinstance(branch_allowance, (int, float)) and isinstance(branch_delta, (int, float)) and branch_delta < -float(branch_allowance):
                violations.append(
                    {
                        "id": "coverage-regression",
                        "detail": f"branch-rate regression {-branch_delta:.6f} exceeds declared allowance {float(branch_allowance):.6f}",
                    }
                )

    invariants: list[dict[str, str]] = []
    for invariant in contract.get("invariants", []):
        if not isinstance(invariant, Mapping):
            continue
        identifier = str(invariant.get("id", "unknown"))
        evidence_id = invariant.get("evidence_id")
        evidence_state = evidence_states.get(str(evidence_id)) if isinstance(evidence_id, str) else None
        if evidence_state == "fresh":
            invariants.append({"id": identifier, "evidence_id": str(evidence_id), "state": "declared-evidence-fresh"})
            continue
        invariants.append(
            {
                "id": identifier,
                "evidence_id": str(evidence_id) if isinstance(evidence_id, str) else "",
                "state": "unverified",
            }
        )
        detail = (
            f"{identifier} has no associated evidence id"
            if evidence_id is None
            else f"{identifier} is not backed by fresh evidence {evidence_id}"
        )
        gaps.append({"id": "contract-invariant-unverified", "detail": detail})

    effective_status = str(contract["status"])
    halt_reasons: list[dict[str, str]] = []
    if violations:
        halt_reasons.extend(violations)
    if contract["status"] == "completed" and continuity != "current":
        halt_reasons.append(
            {
                "id": "contract-continuity-" + continuity,
                "detail": (
                    "Review the current contract, then run ai-guardrails task establish --repo . directly outside the agent command-policy path"
                ),
            }
        )
    repository_available = bool(complexity_result.get("available")) and current_digest is not None
    if contract["status"] == "completed" and not repository_available and not any(
        item["id"] == "repository-state-unavailable" for item in (*gaps, *halt_reasons)
    ):
        halt_reasons.append(
            {
                "id": "repository-state-unavailable",
                "detail": "Git repository and change state are required before completed can be asserted",
            }
        )
    if gaps:
        halt_reasons.extend(gaps)
    if halt_reasons and effective_status not in {"blocked", "halted"}:
        effective_status = "halted" if contract["status"] == "completed" or violations else "partial"
    completed = effective_status == "completed" and not halt_reasons
    return {
        "schema_version": 1,
        "contract_status": contract["status"],
        "effective_status": effective_status,
        "completed": completed,
        "repository_state_digest": current_digest,
        "repository_state": "available" if repository_available else "unavailable",
        "nested_repository_state": repository_result["nested_repository_state"],
        "contract_digest": contract_digest,
        "contract_continuity": continuity,
        "contract_established_at": provenance.get("established_at") if provenance is not None else None,
        "scope": {
            "available": repository_available,
            "files_changed": complexity_result.get("files_changed") if repository_available else None,
            "lines_added": complexity_result.get("lines_added") if repository_available else None,
            "lines_removed": complexity_result.get("lines_removed") if repository_available else None,
            "directories_changed": complexity_result.get("directory_spread") if repository_available else None,
            "dependency_changes": list(complexity_result.get("new_runtime_dependencies", [])) if repository_available else None,
            "dependency_files_changed": list(complexity_result.get("dependency_files_changed", [])) if repository_available else None,
            "dependency_assurance": (
                "unavailable"
                if not repository_available
                else
                "not-required"
                if dependency_policy != "forbid-new-runtime-dependencies"
                else "unavailable"
                if ambiguous_dependencies
                else "violation"
                if complexity_result.get("new_runtime_dependencies")
                else "verified"
            ),
            "implementation_languages_introduced": (
                list(complexity_result.get("implementation_languages_introduced", [])) if repository_available else None
            ),
            "risk_classes": (["high"] if complexity_result.get("high_risk_paths") else ["normal"]) if repository_available else None,
            "risk_classifications": list(complexity_result.get("high_risk_paths", [])) if repository_available else None,
            "generated_output_share_percent": complexity_result.get("generated_file_share_percent", 0) if repository_available else None,
            "generated_output_dominance": any(
                item.get("id") == "generated-output-dominates"
                for item in complexity_result.get("signals", [])
                if isinstance(item, Mapping)
            ) if repository_available else None,
            "complexity_classification": complexity_result.get("classification", "clear") if repository_available else "unavailable",
        },
        "contract_violations": violations,
        "warnings": warnings,
        "evidence": evidence,
        "evidence_gaps": gaps,
        "coverage": coverage,
        "invariants": invariants,
        "safe_halt": {"required": bool(halt_reasons), "reasons": halt_reasons},
        "limitations": [
            "Task evidence is parsed from repository-owned reports; required checks are never executed by this command.",
            "Completed means the current task contract, repository state, scope checks, and required evidence satisfied the configured local assurance checks; it is not proof of business correctness or complete analyzer coverage.",
        ],
    }


def task_receipt(repo: Path, *, home: Path | None = None, now: dt.datetime | None = None) -> dict[str, Any]:
    """Add compact task assurance to the existing content-free receipt envelope."""
    from . import scan

    selected_home = home or Path.home()
    status = task_status(repo, home=selected_home, now=now)
    task_assurance = {
        "contract_digest": status["contract_digest"],
        "repository_state_digest": status["repository_state_digest"],
        "contract_status": status["contract_status"],
        "effective_status": status["effective_status"],
        "completed": status["completed"],
        "contract_continuity": status["contract_continuity"],
        "repository_state": status["repository_state"],
        "nested_repository_state": status["nested_repository_state"],
        "scope": dict(status["scope"]),
        "evidence": [
            {"id": item["id"], "type": item["type"], "state": item["state"]}
            for item in status["evidence"]
        ],
        "halt_reasons": [dict(item) for item in status["safe_halt"]["reasons"]],
    }
    installed = state.load_state(selected_home)
    products = tuple(sorted(str(item) for item in installed.get("products", {})))
    return scan.session_receipt(selected_home, _repository_root(repo), products, task_assurance=task_assurance)


def initialise_task(repo: Path, *, force: bool, dry_run: bool) -> dict[str, Path]:
    root = _repository_root(repo)
    contract = root / TASK_CONTRACT_NAME
    example = root / TASK_EVIDENCE_EXAMPLE_NAME
    for path in (contract, example):
        if path.is_symlink():
            raise GuardrailsError("task files must not be symbolic links")
    if contract.exists() and not force:
        raise GuardrailsError(f"task contract already exists: {contract}; use --force only after reviewing it")
    template = {
        "schema_version": TASK_SCHEMA_VERSION,
        "objective": "Describe the bounded objective before work begins.",
        "observable_outcomes": [{"id": "defined-outcome", "description": "Define at least one mechanically reviewable outcome."}],
        "non_goals": [],
        "risk_class": "normal",
        "status": "planned",
    }
    example_value = {
        "schema_version": EVIDENCE_SCHEMA_VERSION,
        "evidence": [
            {
                "id": "unit-tests",
                "type": "junit",
                "path": "test-results.xml",
                "captured_at": "2026-01-01T00:00:00Z",
                "repository_state_digest": "replace-with-ai-guardrails-task-status-digest",
                "contract_digest": "replace-with-contract-file-sha256",
                "report_digest": "replace-with-report-file-sha256",
                "parser_version": PARSER_VERSION,
                "result": "passed",
            }
        ],
    }
    if dry_run:
        return {"contract": contract, "evidence_example": example}
    if contract.exists():
        backup = contract.with_suffix(contract.suffix + ".bak")
        atomic_write(backup, contract.read_bytes(), mode=0o600)
    atomic_write(contract, json_bytes(template), mode=0o600)
    if not example.exists():
        atomic_write(example, json_bytes(example_value), mode=0o600)
    return {"contract": contract, "evidence_example": example}
