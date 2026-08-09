"""Optional local terminal UX helpers built on existing state and audit data."""

from __future__ import annotations

import datetime as dt
import json
import os
import shlex
import sys
from pathlib import Path
from typing import Any, Mapping

from . import terminal_renderer
from .resources import RESOURCE_ROOT
from .util import NAME_RE, OPERATION_CLASSES, PRODUCTS, GuardrailsError, atomic_write, home_path, json_bytes, sha256


UX_ROOT = RESOURCE_ROOT / "ux"
PROFILE_PATH = UX_ROOT / "statusline-profiles.json"
THRESHOLDS_PATH = UX_ROOT / "complexity-thresholds.json"
CACHE_RELATIVE = Path(".ai-guardrails/cache")
STATUSLINE_PROFILES = ("compact", "standard", "fun")
STATUSLINE_PRODUCTS = ("codex", "claude", "cursor")
CODEX_NATIVE_FIELDS = {
    "compact": ("model-with-reasoning", "context-remaining", "git-branch"),
    "standard": ("model-with-reasoning", "context-remaining", "git-branch", "current-dir"),
    "fun": ("model-with-reasoning", "context-remaining", "git-branch", "current-dir"),
}


def _load(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise GuardrailsError(f"terminal UX resource is invalid: {path.name}") from exc
    if not isinstance(value, dict):
        raise GuardrailsError(f"terminal UX resource must be an object: {path.name}")
    return value


def load_profiles() -> dict[str, Any]:
    return _load(PROFILE_PATH)


def load_thresholds() -> dict[str, Any]:
    return _load(THRESHOLDS_PATH)


def validate_resources() -> None:
    profiles = load_profiles()
    if profiles.get("schema_version") != 1 or not isinstance(profiles.get("profiles"), dict):
        raise GuardrailsError("status-line profile resource has an unsupported schema")
    if set(profiles["profiles"]) != set(STATUSLINE_PROFILES):
        raise GuardrailsError("status-line profiles must define compact, standard, and fun")
    for profile in STATUSLINE_PROFILES:
        selected = terminal_renderer._profile(profiles, profile)
        if selected is None or selected.get("fallback") != "omit":
            raise GuardrailsError(f"status-line profile is invalid: {profile}")
        segments = selected["segments"]
        if len(segments) != len(set(segments)):
            raise GuardrailsError(f"status-line profile repeats a segment: {profile}")
    thresholds = load_thresholds()
    required = {
        "review_files", "high_files", "review_lines", "high_lines", "review_directories", "high_directories",
        "review_generated_share_percent", "high_risk_paths", "new_runtime_dependencies",
    }
    values = thresholds.get("thresholds")
    if thresholds.get("schema_version") != 1 or not isinstance(values, dict) or set(values) != required:
        raise GuardrailsError("complexity threshold resource has an unsupported schema")
    if any(not isinstance(value, int) or value < 0 for value in values.values()):
        raise GuardrailsError("complexity thresholds must be non-negative integers")
    for review, high in (("review_files", "high_files"), ("review_lines", "high_lines"), ("review_directories", "high_directories")):
        if values[review] > values[high]:
            raise GuardrailsError("complexity review thresholds cannot exceed high-change thresholds")
    if any(not isinstance(thresholds.get(field), list) for field in ("generated_prefixes", "manifest_names", "lockfile_names")) or not isinstance(thresholds.get("language_extensions"), dict):
        raise GuardrailsError("complexity resource is missing classifications")
    if any(not isinstance(item, str) for field in ("generated_prefixes", "manifest_names", "lockfile_names", "ci_governance_prefixes", "ci_governance_names", "infrastructure_extensions") for item in thresholds.get(field, [])):
        raise GuardrailsError("complexity classifications must be strings")
    if any(not isinstance(key, str) or not isinstance(value, str) for key, value in thresholds["language_extensions"].items()):
        raise GuardrailsError("complexity language classifications must be strings")


def cache_directory(home: Path) -> Path:
    return home_path(home.expanduser().resolve(strict=False), CACHE_RELATIVE)


def audit_summary_path(home: Path) -> Path:
    return cache_directory(home) / "status/audit-summary.json"


def complexity_snapshot_path(home: Path, repository_identifier_hash: str) -> Path:
    if len(repository_identifier_hash) != 64 or any(character not in "0123456789abcdef" for character in repository_identifier_hash):
        raise GuardrailsError("complexity snapshot has an invalid repository identifier")
    return cache_directory(home) / "complexity" / f"{repository_identifier_hash}.json"


def cache_freshness(path: Path, *, now: dt.datetime | None = None) -> str:
    """Classify one small aggregate cache without exposing its contents."""
    if path.is_symlink() or not path.is_file():
        return "missing"
    try:
        if path.stat().st_size > 16_384:
            return "invalid"
        value = json.loads(path.read_text(encoding="utf-8"))
        generated_at = value.get("generated_at") if isinstance(value, dict) else None
        if not isinstance(generated_at, str):
            return "invalid"
        generated = dt.datetime.fromisoformat(generated_at.replace("Z", "+00:00"))
    except (OSError, UnicodeError, ValueError, json.JSONDecodeError):
        return "invalid"
    if generated.tzinfo is None:
        return "invalid"
    now = now or dt.datetime.now(dt.timezone.utc)
    return "fresh" if generated <= now and generated >= now - dt.timedelta(hours=24) else "stale"


def _audit_paths(home: Path) -> list[Path]:
    directory = home_path(home, ".ai-guardrails/audit")
    return [directory / "events.jsonl", *(directory / f"events.jsonl.{index}" for index in range(1, 4))]


def audit_summary(
    home: Path,
    *,
    window: str | None = "24h",
    product: str | None = None,
    now: dt.datetime | None = None,
) -> dict[str, Any]:
    """Read only bounded, redacted event metadata; never expose raw event values."""
    durations = {"1h": dt.timedelta(hours=1), "24h": dt.timedelta(hours=24), "7d": dt.timedelta(days=7)}
    if window not in {*durations, "today", None}:
        raise GuardrailsError("event summary window must be today, 1h, 24h, 7d, or recorded history")
    now = now or dt.datetime.now(dt.timezone.utc)
    start = (
        now.replace(hour=0, minute=0, second=0, microsecond=0)
        if window == "today" else now - durations[window]
        if window is not None else None
    )
    warnings = denials = observed = skipped = 0
    operation_classes: dict[str, int] = {}
    rule_ids: dict[str, int] = {}
    products: dict[str, int] = {}
    last_event: dt.datetime | None = None
    lines_remaining = 10_000
    for path in _audit_paths(home):
        if lines_remaining <= 0 or path.is_symlink() or not path.is_file() or path.stat().st_size > 1_048_576:
            continue
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except (OSError, UnicodeError):
            continue
        for line in lines[-lines_remaining:]:
            lines_remaining -= 1
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                skipped += 1
                continue
            if not isinstance(event, dict):
                skipped += 1
                continue
            if product is not None and event.get("product") != product:
                continue
            timestamp = event.get("timestamp")
            if not isinstance(timestamp, str):
                skipped += 1
                continue
            try:
                at = dt.datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
            except ValueError:
                skipped += 1
                continue
            if at.tzinfo is None:
                skipped += 1
                continue
            if window is not None and (at < start or at > now):
                continue
            decision = event.get("decision")
            operation = event.get("operation_class")
            rule = event.get("rule_id")
            event_product = event.get("product")
            if decision not in {"warn", "deny", "no-decision"}:
                skipped += 1
                continue
            if operation is not None and (not isinstance(operation, str) or operation not in OPERATION_CLASSES):
                skipped += 1
                continue
            if rule is not None and (not isinstance(rule, str) or len(rule) > 100 or not NAME_RE.fullmatch(rule)):
                skipped += 1
                continue
            if event_product is not None and (not isinstance(event_product, str) or event_product not in PRODUCTS):
                skipped += 1
                continue
            if decision == "warn":
                warnings += 1
            elif decision == "deny":
                denials += 1
            elif decision == "no-decision":
                observed += 1
            if isinstance(operation, str):
                operation_classes[operation] = operation_classes.get(operation, 0) + 1
            if isinstance(rule, str):
                rule_ids[rule] = rule_ids.get(rule, 0) + 1
            if isinstance(event_product, str):
                products[event_product] = products.get(event_product, 0) + 1
            if last_event is None or at > last_event:
                last_event = at
    return {
        "schema_version": 1,
        "window": window or "recorded-history",
        "window_start": start.replace(microsecond=0).isoformat().replace("+00:00", "Z") if start else None,
        "generated_at": now.replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "product": product,
        "warnings": warnings,
        "denials": denials,
        "observed": observed,
        "operation_classes": dict(sorted(operation_classes.items())),
        "rule_ids": dict(sorted(rule_ids.items())),
        "products": dict(sorted(products.items())),
        "last_event_at": last_event.astimezone(dt.timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z") if last_event else None,
        "skipped_malformed_events": skipped,
    }


def write_audit_summary_cache(home: Path, summary: Mapping[str, Any], *, dry_run: bool = False) -> Path:
    path = audit_summary_path(home)
    if dry_run:
        return path
    atomic_write(path, json_bytes(summary), mode=0o600)
    return path


def refresh_audit_summary_cache(home: Path) -> Path:
    """Refresh the renderer's one canonical, unfiltered rolling-24-hour summary."""
    return write_audit_summary_cache(home, audit_summary(home, window="24h", product=None))


def claude_command(runtime: Path, profile: str, safety_profile: str, home: Path, *, platform_name: str | None = None) -> str:
    executable = Path(sys.executable).resolve(strict=False)
    renderer = runtime / "terminal_renderer.py"
    profiles = runtime / "statusline-profiles.json"
    cache = cache_directory(home)
    arguments = [str(executable), str(renderer), "--profiles", str(profiles), "--profile", profile, "--safety-profile", safety_profile, "--cache-dir", str(cache)]
    if (platform_name or os.name) == "nt":
        quoted = " ".join("'" + value.replace("'", "''").replace("\\", "/") + "'" for value in arguments)
        return f"powershell -NoProfile -Command \"& {quoted}\""
    return " ".join(shlex.quote(value) for value in arguments)


def claude_status_line(runtime: Path, profile: str, safety_profile: str, home: Path) -> dict[str, Any]:
    return {"type": "command", "command": claude_command(runtime, profile, safety_profile, home)}


def statusline_preview(
    product: str, profile: str, safety_profile: str = "infrastructure-observe", *, ascii_only: bool = False
) -> dict[str, Any]:
    if product not in STATUSLINE_PRODUCTS:
        raise GuardrailsError("terminal UX supports codex, claude, and cursor")
    if profile not in STATUSLINE_PROFILES:
        raise GuardrailsError(f"unknown status-line profile: {profile}")
    if product == "codex":
        return {"product": product, "profile": profile, "integration": "managed-native", "native_fields": list(CODEX_NATIVE_FIELDS[profile]), "note": "Only exact IDs documented in the current sample configuration are managed. Use /statusline to add version-specific rate-limit or token items. Local guardrail counters and complexity signals are not added to the Codex footer."}
    if product == "cursor":
        return {"product": product, "profile": profile, "integration": "native-manual", "note": "Cursor CLI documents /status-indicators for terminal-title indicators. A programmable usage bar is not documented."}
    sample = {
        "model": {"display_name": "Claude"},
        "context_window": {"used_percentage": 72},
        "rate_limits": {"five_hour": {"used_percentage": 23}},
        "cost": {"total_cost_usd": 1.42, "total_duration_ms": 125000},
        "worktree": {"branch": "feature"},
    }
    sample["effort"] = {"level": "high"}
    return {"product": product, "profile": profile, "integration": "managed", "example": terminal_renderer.render_status_line(sample, load_profiles(), profile, safety_profile, ascii_only=ascii_only, columns=120), "note": "Example uses synthetic documented Claude fields; missing native fields are omitted."}


def codex_setup(profile: str) -> str:
    fields = CODEX_NATIVE_FIELDS[profile]
    rendered = ", ".join(f'"{field}"' for field in fields)
    return "\n".join((
        "In Codex, run /statusline and use the picker to choose and reorder native fields.",
        "The explicit status-line installer manages only this reviewable key:",
        "[tui]",
        f"status_line = [{rendered}]",
        "Use /status for the current model, approvals, roots, and token usage; use /usage for native account token activity.",
        "For fun, /pets is a separate optional native choice; this project never enables it.",
    ))


def cursor_setup() -> str:
    return "Run /status-indicators in Cursor CLI to toggle documented terminal-title indicators. Cursor currently documents no programmable status-line or /usage command, so this installer does not write a Cursor configuration file."


def profile_hash(value: Mapping[str, Any]) -> str:
    return sha256(json_bytes(value))
