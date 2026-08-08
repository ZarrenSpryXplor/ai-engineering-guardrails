"""Installation ownership, hashing, backups, and safe filesystem mutation."""

from __future__ import annotations

import hashlib
import datetime as dt
import getpass
import os
import re
import shutil
import tempfile
import uuid
from pathlib import Path
from typing import Any, Mapping, Sequence

from . import __version__
from .resources import PACKAGE_ROOT, RESOURCE_ROOT
from .util import (
    PRODUCTS,
    GuardrailsError,
    atomic_write,
    file_hash,
    home_path,
    json_bytes,
    path_within,
    read_json,
    relative_home,
    sha256,
    tree_hash,
    validate_install_target,
)


FORMAT_VERSION = 3
STATE_RELATIVE = Path(".ai-guardrails/state.json")
BACKUPS_RELATIVE = Path(".ai-guardrails/backups")
WAIVERS_RELATIVE = Path(".ai-guardrails/waivers")
MAX_WAIVER_MINUTES = 24 * 60
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
LEGACY_FORMAT_KEY = "_legacy_state_format"


def empty_state() -> dict[str, Any]:
    return {
        "format_version": FORMAT_VERSION,
        "source_digest": "",
        "overlay_digest": "",
        "policy_digest": "",
        "products": {},
        "installed_packs": [],
        "routing_profile": "none",
        "safety_profile": "infrastructure-observe",
        "trust_mode": "trusted-workspace",
        "runtime_digest": None,
        "runtime_path": None,
        "manual_steps": [],
    }


def load_state(home: Path) -> dict[str, Any]:
    path = home_path(home, STATE_RELATIVE)
    validate_install_target(path, home)
    data = read_json(path, default=empty_state())
    if not isinstance(data, dict):
        raise GuardrailsError(f"invalid installation state in {path}")
    if data.get("format_version") in {1, 2}:
        # Read pre-packaging state for update/uninstall; the next successful write
        # records the package and overlay identities in v3.
        upgraded = empty_state()
        for key in upgraded:
            if key in data:
                upgraded[key] = data[key]
        upgraded[LEGACY_FORMAT_KEY] = data["format_version"]
        return upgraded
    if data.get("format_version") != FORMAT_VERSION or not isinstance(data.get("products"), dict):
        raise GuardrailsError(f"unsupported installation state in {path}")
    return data


def save_state(home: Path, value: Mapping[str, Any], *, dry_run: bool) -> None:
    path = home_path(home, STATE_RELATIVE)
    validate_install_target(path, home)
    if dry_run:
        print(f"would write {path}")
        return
    # Migration markers are process-local compatibility details, not state data.
    atomic_write(path, json_bytes({key: item for key, item in value.items() if not key.startswith("_")}), mode=0o600)


def source_digest(overlay_digest: str = "") -> str:
    """Hash installed package code and bundled data without assuming a checkout."""
    digest = hashlib.sha256()
    digest.update(__version__.encode("utf-8"))
    digest.update(b"\0overlay\0")
    digest.update(overlay_digest.encode("ascii"))
    source_paths = [
        path
        for root in (PACKAGE_ROOT, RESOURCE_ROOT)
        for path in root.rglob("*")
        if path.is_file() and "__pycache__" not in path.parts and path.suffix != ".pyc"
    ]
    for path in sorted(set(source_paths), key=lambda value: value.relative_to(PACKAGE_ROOT).as_posix()):
        digest.update(path.relative_to(PACKAGE_ROOT).as_posix().encode("utf-8"))
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


def record(relative: str, kind: str, content_hash: str, backup: str | None = None, **metadata: Any) -> dict[str, Any]:
    result: dict[str, Any] = {"path": relative, "kind": kind, "sha256": content_hash}
    if backup:
        result["backup"] = backup
    result.update(metadata)
    return result


def product_records(state: Mapping[str, Any], product: str) -> list[dict[str, Any]]:
    product_data = state.get("products", {}).get(product, {})
    values = product_data.get("managed", []) if isinstance(product_data, Mapping) else []
    return [dict(value) for value in values if isinstance(value, Mapping)] if isinstance(values, list) else []


def all_records(state: Mapping[str, Any], product: str | None = None) -> list[dict[str, Any]]:
    selected = (product,) if product else PRODUCTS
    records: list[dict[str, Any]] = []
    for name in selected:
        records.extend(product_records(state, name))
    return records


def record_for_path(state: Mapping[str, Any], relative: str) -> dict[str, Any] | None:
    return next((item for item in all_records(state) if item.get("path") == relative), None)


def owners(state: Mapping[str, Any], relative: str, excluding: set[str] | None = None) -> set[str]:
    excluded = excluding or set()
    return {
        product
        for product in PRODUCTS
        if product not in excluded and any(item.get("path") == relative for item in product_records(state, product))
    }


def backup_path(home: Path, target: Path, content_hash: str, *, directory: bool) -> Path:
    relative = relative_home(target, home).replace("/", "__")
    suffix = ".dir" if directory else ".bak"
    return home_path(home, BACKUPS_RELATIVE / f"{relative}.{content_hash[:12]}{suffix}")


def backup_existing(home: Path, target: Path, *, dry_run: bool) -> str | None:
    if not target.exists():
        return None
    validate_install_target(target, home)
    directory = target.is_dir() and not target.is_symlink()
    content_hash = tree_hash(target) if directory else file_hash(target)
    backup = backup_path(home, target, content_hash, directory=directory)
    if not dry_run and not backup.exists():
        backup.parent.mkdir(parents=True, exist_ok=True)
        if directory:
            shutil.copytree(target, backup, symlinks=True)
        else:
            shutil.copy2(target, backup)
    return relative_home(backup, home)


def install_file_data(
    data: bytes,
    target: Path,
    home: Path,
    current_state: Mapping[str, Any],
    *,
    force: bool,
    dry_run: bool,
    collision_label: str = "file",
    mode: int = 0o644,
) -> dict[str, Any]:
    validate_install_target(target, home)
    relative = relative_home(target, home)
    expected_hash = sha256(data)
    previous = record_for_path(current_state, relative)
    backup: str | None = previous.get("backup") if previous else None
    if target.exists():
        if not target.is_file() or target.is_symlink():
            raise GuardrailsError(f"managed {collision_label} collides with a non-file: {target}")
        current_hash = file_hash(target)
        if current_hash == expected_hash:
            print(f"unchanged {target}")
            return record(relative, "file", expected_hash, backup)
        unmanaged_or_modified = previous is None or current_hash != previous.get("sha256")
        if unmanaged_or_modified and not force:
            qualifier = "unmanaged collision" if previous is None else "locally modified managed file"
            raise GuardrailsError(f"{qualifier}; refusing to overwrite without --force: {target}")
        backup = backup_existing(home, target, dry_run=dry_run) or backup
    print(f"{'would write' if dry_run else 'write'} {target}")
    if not dry_run:
        atomic_write(target, data, mode=mode)
    return record(relative, "file", expected_hash, backup)


def install_file(
    source: Path,
    target: Path,
    home: Path,
    current_state: Mapping[str, Any],
    *,
    force: bool,
    dry_run: bool,
) -> dict[str, Any]:
    return install_file_data(source.read_bytes(), target, home, current_state, force=force, dry_run=dry_run)


def install_directory(
    source: Path,
    target: Path,
    home: Path,
    current_state: Mapping[str, Any],
    *,
    force: bool,
    dry_run: bool,
    label: str,
) -> dict[str, Any]:
    validate_install_target(target, home)
    if any(path.is_symlink() for path in source.rglob("*")):
        raise GuardrailsError(f"managed {label} source contains a symbolic link: {source}")
    relative = relative_home(target, home)
    expected_hash = tree_hash(source)
    previous = record_for_path(current_state, relative)
    backup: str | None = previous.get("backup") if previous else None
    if target.exists():
        if target.is_symlink():
            raise GuardrailsError(f"managed {label} collides with a symbolic link: {target}")
        current_hash = tree_hash(target) if target.is_dir() else "not-a-directory"
        if current_hash == expected_hash:
            print(f"unchanged {target}")
            return record(relative, "directory", expected_hash, backup)
        if previous is None and not force:
            raise GuardrailsError(f"unmanaged {label} collision; refusing to overwrite without --force: {target}")
        if previous is not None and current_hash != previous.get("sha256") and not force:
            raise GuardrailsError(f"locally modified {label}; refusing to overwrite without --force: {target}")
        backup = backup_existing(home, target, dry_run=dry_run) or backup
    print(f"{'would copy' if dry_run else 'copy'} {source} -> {target}")
    if not dry_run:
        target.parent.mkdir(parents=True, exist_ok=True)
        temporary_parent = Path(tempfile.mkdtemp(prefix=f".{target.name}.", dir=target.parent))
        staged = temporary_parent / target.name
        try:
            shutil.copytree(source, staged)
            if target.exists():
                if not path_within(target, home):
                    raise GuardrailsError(f"refusing to replace directory outside selected home: {target}")
                if target.is_dir() and not target.is_symlink():
                    shutil.rmtree(target)
                else:
                    target.unlink()
            os.replace(staged, target)
        finally:
            if temporary_parent.exists():
                shutil.rmtree(temporary_parent)
    return record(relative, "directory", expected_hash, backup)


def record_status(item: Mapping[str, Any], home: Path) -> str:
    relative = item.get("path")
    if not isinstance(relative, str):
        return "missing"
    target = home_path(home, relative)
    if not target.exists():
        return "missing"
    if item.get("kind") in {"directory", "runtime-directory"}:
        actual = tree_hash(target) if target.is_dir() and not target.is_symlink() else "wrong-type"
    else:
        actual = file_hash(target) if target.is_file() and not target.is_symlink() else "wrong-type"
    return "installed" if actual == item.get("sha256") else "modified"


def remove_record(
    item: Mapping[str, Any],
    home: Path,
    *,
    force: bool,
    dry_run: bool,
) -> bool:
    relative = item.get("path")
    if not isinstance(relative, str):
        return False
    target = home_path(home, relative)
    if not target.exists():
        return True
    status = record_status(item, home)
    if status == "modified" and not force:
        print(f"retained modified managed path: {target}")
        return False
    validate_install_target(target, home)
    if status == "modified":
        backup_existing(home, target, dry_run=dry_run)
    print(f"{'would remove' if dry_run else 'remove'} {target}")
    if not dry_run:
        if target.is_dir() and not target.is_symlink():
            shutil.rmtree(target)
        else:
            target.unlink()
    return True


def remove_empty_parents(home: Path, candidates: Sequence[Path]) -> None:
    for candidate in candidates:
        current = candidate
        while current != home and path_within(current, home):
            if current.parent == home:
                break
            if not current.is_dir() or any(current.iterdir()):
                break
            current.rmdir()
            current = current.parent


def validate_waiver(value: Any) -> dict[str, Any]:
    required = {
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
    if not isinstance(value, dict) or set(value) != required:
        raise GuardrailsError("waiver fields do not match the supported schema")
    if not isinstance(value["id"], str) or not value["id"].startswith("waiver-"):
        raise GuardrailsError("waiver has an invalid identifier")
    if not isinstance(value["rule_id"], str) or not value["rule_id"]:
        raise GuardrailsError("waiver has an invalid rule identifier")
    if not isinstance(value["command_tool_call_digest"], str) or not SHA256_RE.fullmatch(value["command_tool_call_digest"]):
        raise GuardrailsError("waiver command/tool-call digest must be a lowercase SHA-256 value")
    for field in ("repository_scope", "target_scope", "reason", "change_reference", "created_by", "created_at", "expires_at"):
        if not isinstance(value[field], str) or not value[field].strip():
            raise GuardrailsError(f"waiver has invalid {field}")
    for field in ("maximum_uses", "remaining_uses"):
        if not isinstance(value[field], int) or value[field] < 0:
            raise GuardrailsError(f"waiver has invalid {field}")
    if value["maximum_uses"] < 1 or value["remaining_uses"] > value["maximum_uses"]:
        raise GuardrailsError("waiver use counts are inconsistent")
    try:
        created = dt.datetime.fromisoformat(value["created_at"].replace("Z", "+00:00"))
        expires = dt.datetime.fromisoformat(value["expires_at"].replace("Z", "+00:00"))
    except ValueError as exc:
        raise GuardrailsError("waiver timestamps must use ISO-8601 UTC format") from exc
    if expires <= created or expires - created > dt.timedelta(minutes=MAX_WAIVER_MINUTES):
        raise GuardrailsError("waiver expiry exceeds the documented 24-hour maximum")
    return dict(value)


def waiver_directory(home: Path) -> Path:
    return home_path(home, WAIVERS_RELATIVE)


def list_waivers(home: Path) -> list[dict[str, Any]]:
    directory = waiver_directory(home)
    values: list[dict[str, Any]] = []
    if directory.is_dir():
        for path in sorted(directory.glob("*.json")):
            values.append(validate_waiver(read_json(path, default={})))
    return values


def create_waiver(
    home: Path,
    *,
    rule: Mapping[str, Any],
    repository_scope: str,
    target_scope: str,
    request_digest: str,
    reason: str,
    change_reference: str,
    expiry_minutes: int = 15,
    maximum_uses: int = 1,
    input_stream: Any = None,
    output_stream: Any = None,
) -> dict[str, Any]:
    input_stream = input_stream or __import__("sys").stdin
    output_stream = output_stream or __import__("sys").stdout
    if not input_stream.isatty() or not output_stream.isatty():
        raise GuardrailsError("waiver creation requires an interactive TTY and exact human confirmation")
    if not 1 <= expiry_minutes <= MAX_WAIVER_MINUTES:
        raise GuardrailsError("waiver expiry must be between 1 minute and 24 hours")
    if not 1 <= maximum_uses <= 10:
        raise GuardrailsError("waiver maximum uses must be between 1 and 10")
    if not SHA256_RE.fullmatch(request_digest):
        raise GuardrailsError("waiver command/tool-call digest must be a lowercase SHA-256 value")
    operation = rule.get("operation_class")
    protected = {"destructive", "sensitive-read", "publish", "privilege-escalation", "guardrail-modification"}
    if operation in protected and (repository_scope == "*" or target_scope == "*"):
        raise GuardrailsError("broad wildcard waivers are prohibited for destructive, sensitive, publication, privilege, and guardrail rules")
    if not reason.strip() or not change_reference.strip():
        raise GuardrailsError("waiver reason and change reference are required")
    identifier = f"waiver-{uuid.uuid4().hex}"
    confirmation = f"CREATE WAIVER {identifier}"
    print(
        f"Rule {rule.get('id')} ({operation}) would be waived for {maximum_uses} use(s), expiring in {expiry_minutes} minute(s).",
        file=output_stream,
    )
    print(f"Type exactly: {confirmation}", file=output_stream)
    entered = input_stream.readline().rstrip("\r\n")
    if entered != confirmation:
        raise GuardrailsError("waiver confirmation did not match; no waiver was created")
    now = dt.datetime.now(dt.timezone.utc).replace(microsecond=0)
    value = validate_waiver(
        {
            "id": identifier,
            "rule_id": rule["id"],
            "repository_scope": repository_scope,
            "target_scope": target_scope,
            "command_tool_call_digest": request_digest,
            "reason": reason.strip(),
            "change_reference": change_reference.strip(),
            "created_by": getpass.getuser(),
            "created_at": now.isoformat().replace("+00:00", "Z"),
            "expires_at": (now + dt.timedelta(minutes=expiry_minutes)).isoformat().replace("+00:00", "Z"),
            "maximum_uses": maximum_uses,
            "remaining_uses": maximum_uses,
        }
    )
    target = waiver_directory(home) / f"{identifier}.json"
    validate_install_target(target, home)
    atomic_write(target, json_bytes(value), mode=0o600)
    return value


def revoke_waiver(home: Path, identifier: str) -> bool:
    if not re.fullmatch(r"waiver-[0-9a-f]{32}", identifier):
        raise GuardrailsError("invalid waiver identifier")
    target = waiver_directory(home) / f"{identifier}.json"
    validate_install_target(target, home)
    if not target.exists():
        return False
    validate_waiver(read_json(target, default={}))
    target.unlink()
    return True
