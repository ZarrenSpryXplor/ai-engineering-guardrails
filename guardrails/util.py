"""Small, shared filesystem and serialization helpers."""

from __future__ import annotations

import copy
import hashlib
import json
import os
import re
import stat
import tempfile
from pathlib import Path, PureWindowsPath
from typing import Any, Mapping


ROOT = Path(__file__).resolve().parents[1]
PRODUCTS = ("codex", "claude", "cursor")
CAPABILITY_TIERS = ("economy", "balanced", "deep")
REASONING_LEVELS = ("low", "medium", "high")
ROUTING_PROFILES = ("none", "economy", "balanced", "quality")
SAFETY_PROFILES = (
    "development",
    "infrastructure-observe",
    "infrastructure-nonprod",
    "infrastructure-strict",
)
TRUST_MODES = (
    "trusted-workspace",
    "untrusted-workspace",
    "untrusted-external-input",
    "incident-observe",
)
LIFECYCLES = ("dev", "tst", "int", "prd")
OPERATION_CLASSES = (
    "observe",
    "validate",
    "mutate",
    "destructive",
    "sensitive-read",
    "publish",
    "privilege-escalation",
    "guardrail-modification",
)
ROLLOUT_MODES = ("disabled", "observe", "warn", "deny")
NAME_RE = re.compile(r"^[a-z0-9]+(?:[-_][a-z0-9]+)*$")


class GuardrailsError(RuntimeError):
    """A user-actionable guardrails management failure."""


def json_bytes(value: Any) -> bytes:
    return (json.dumps(value, indent=2, ensure_ascii=False, sort_keys=True) + "\n").encode("utf-8")


def one_newline(text: str) -> str:
    return text.rstrip() + "\n"


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def file_hash(path: Path) -> str:
    return sha256(path.read_bytes())


def tree_hash(path: Path) -> str:
    digest = hashlib.sha256()
    for child in sorted(path.rglob("*")):
        if child.is_symlink():
            digest.update(child.relative_to(path).as_posix().encode("utf-8"))
            digest.update(b"\0link\0")
            digest.update(os.readlink(child).encode("utf-8", errors="surrogateescape"))
            digest.update(b"\0")
            continue
        if not child.is_file():
            continue
        digest.update(child.relative_to(path).as_posix().encode("utf-8"))
        digest.update(b"\0file\0")
        digest.update(child.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


def path_within(path: Path, parent: Path) -> bool:
    try:
        path.resolve(strict=False).relative_to(parent.resolve(strict=False))
        return True
    except ValueError:
        return False


def home_path(home: Path, relative: str | Path) -> Path:
    relative_path = Path(relative)
    candidate = home / relative_path
    if relative_path.is_absolute() or PureWindowsPath(str(relative)).is_absolute() or not path_within(candidate, home):
        raise GuardrailsError(f"refusing path outside selected home: {relative}")
    return candidate


def relative_home(path: Path, home: Path) -> str:
    try:
        return path.resolve(strict=False).relative_to(home.resolve(strict=False)).as_posix()
    except ValueError as exc:
        raise GuardrailsError(f"managed path is outside selected home: {path}") from exc


def validate_install_target(target: Path, home: Path) -> None:
    if not path_within(target, home):
        raise GuardrailsError(f"installation target is outside selected home: {target}")
    if target.is_symlink():
        raise GuardrailsError(f"installation target is a symbolic link: {target}")
    relative = target.resolve(strict=False).relative_to(home.resolve(strict=False))
    current = home.resolve(strict=False)
    for part in relative.parts[:-1]:
        current /= part
        if current.is_symlink():
            raise GuardrailsError(f"installation parent is a symbolic link: {current}")
        if current.exists() and not current.is_dir():
            raise GuardrailsError(f"installation parent is not a directory: {current}")


def atomic_write(path: Path, data: bytes, mode: int | None = None) -> bool:
    if path.is_symlink():
        raise GuardrailsError(f"refusing atomic write through symbolic link: {path}")
    if path.exists() and path.is_file() and path.read_bytes() == data:
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    existing_mode = stat.S_IMODE(path.stat().st_mode) if path.exists() and path.is_file() else None
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temporary, mode if mode is not None else (existing_mode or 0o644))
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()
    return True


def read_json(path: Path, *, default: Any | None = None) -> Any:
    if path.is_symlink():
        raise GuardrailsError(f"refusing to read JSON through symbolic link: {path}")
    if not path.exists() and default is not None:
        return copy.deepcopy(default)
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise GuardrailsError(f"cannot parse JSON file {path}: {exc}") from exc


def parse_simple_frontmatter(
    path: Path,
    *,
    required: set[str],
    allowed: set[str],
) -> tuple[dict[str, str], str]:
    if path.is_symlink():
        raise GuardrailsError(f"refusing to read frontmatter through symbolic link: {path}")
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        raise GuardrailsError(f"cannot read frontmatter file {path}: {exc}") from exc
    lines = text.splitlines()
    if not lines or lines[0] != "---":
        raise GuardrailsError(f"file lacks frontmatter: {path}")
    try:
        end = lines.index("---", 1)
    except ValueError as exc:
        raise GuardrailsError(f"file has unterminated frontmatter: {path}") from exc
    fields: dict[str, str] = {}
    for line in lines[1:end]:
        if not line.strip() or ":" not in line:
            raise GuardrailsError(f"file has unsupported portable frontmatter: {path}")
        key, value = (part.strip() for part in line.split(":", 1))
        if key not in allowed or key in fields or not value:
            raise GuardrailsError(f"file has unsupported portable frontmatter field: {key or '<empty>'}")
        fields[key] = value.strip('"')
    missing = required - fields.keys()
    if missing:
        raise GuardrailsError(f"file is missing required field: {sorted(missing)[0]}")
    body = "\n".join(lines[end + 1 :]).strip()
    if not body:
        raise GuardrailsError(f"file body is empty: {path}")
    return fields, body


def require_object(value: Any, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise GuardrailsError(f"{label} must be a JSON object")
    return value


def generated_header(source: str, comment: str = "#") -> str:
    return f"{comment} GENERATED — DO NOT EDIT\n{comment} Canonical source: {source}\n"


def redact_mapping(mapping: Mapping[str, Any], never_log: set[str]) -> dict[str, Any]:
    """Return field names and harmless scalar types without argument values."""
    return {
        key: "<redacted>" if key.lower() in never_log else f"<{type(value).__name__}>"
        for key, value in sorted(mapping.items())
    }
