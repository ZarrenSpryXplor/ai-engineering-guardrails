"""Small, standalone Claude Code status-line renderer.

This module deliberately imports only the standard library so the installer can
copy it into the immutable runtime without importing a source checkout.
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import math
import os
import sys
from pathlib import Path
from typing import Any, Mapping


SEGMENTS = frozenset({"shield", "model", "effort", "context", "heat", "rate_limits", "cost_duration", "branch", "audit", "complexity"})


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _text(value: Any, limit: int = 40) -> str | None:
    if not isinstance(value, str):
        return None
    cleaned = "".join(character for character in value if character.isprintable() and character not in "\r\n\t").strip()
    return cleaned[:limit] if cleaned else None


def _percent(value: Any) -> int | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    try:
        number = float(value)
    except OverflowError:
        return None
    if not math.isfinite(number):
        return None
    return max(0, min(100, round(number)))


def _number(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    try:
        number = float(value)
    except OverflowError:
        return None
    return number if math.isfinite(number) else None


def _cache(candidate: Path) -> Mapping[str, Any]:
    if candidate.is_symlink() or not candidate.is_file() or candidate.stat().st_size > 16_384:
        return {}
    try:
        value = _mapping(json.loads(candidate.read_text(encoding="utf-8")))
        generated_at = value.get("generated_at")
        if not isinstance(generated_at, str):
            return {}
        generated = dt.datetime.fromisoformat(generated_at.replace("Z", "+00:00"))
        now = dt.datetime.now(dt.timezone.utc)
        if generated.tzinfo is None or generated > now or generated < now - dt.timedelta(hours=24):
            return {}
        return value
    except (OSError, UnicodeError, ValueError, json.JSONDecodeError):
        return {}


def _bar(percent: int, ascii_only: bool) -> str:
    width = 10
    filled = round(percent * width / 100)
    return ("#" * filled + "-" * (width - filled)) if ascii_only else ("▓" * filled + "░" * (width - filled))


def _duration(milliseconds: float) -> str:
    seconds = max(0, int(milliseconds // 1000))
    minutes, seconds = divmod(seconds, 60)
    hours, minutes = divmod(minutes, 60)
    return f"{hours}h{minutes:02d}m" if hours else f"{minutes}m{seconds:02d}s"


def _profile(value: Mapping[str, Any], profile: str) -> Mapping[str, Any] | None:
    profiles = _mapping(value.get("profiles"))
    selected = _mapping(profiles.get(profile))
    segments = selected.get("segments")
    priorities = _mapping(selected.get("priorities"))
    if not isinstance(segments, list) or any(segment not in SEGMENTS for segment in segments):
        return None
    if set(priorities) != set(segments) or any(not isinstance(priority, int) for priority in priorities.values()):
        return None
    if selected.get("fallback") != "omit":
        return None
    return selected


def render_status_line(
    payload: Mapping[str, Any],
    profiles: Mapping[str, Any],
    profile: str,
    safety_profile: str,
    cache_dir: Path | None = None,
    *,
    ascii_only: bool = False,
    columns: int | None = None,
) -> str:
    """Render one bounded, content-free-derived status line or an empty string."""
    selected = _profile(profiles, profile)
    if selected is None:
        return ""
    segments = selected["segments"]
    priorities = _mapping(selected["priorities"])
    unicode = not ascii_only
    model = _text(_mapping(payload.get("model")).get("display_name"))
    effort = _text(_mapping(payload.get("effort")).get("level"), 16)
    context_window = _mapping(payload.get("context_window"))
    context = _percent(context_window.get("used_percentage"))
    if context is None:
        remaining = _percent(context_window.get("remaining_percentage"))
        context = 100 - remaining if remaining is not None else None
    rate = _mapping(payload.get("rate_limits"))
    five_hour = _percent(_mapping(rate.get("five_hour")).get("used_percentage"))
    seven_day = _percent(_mapping(rate.get("seven_day")).get("used_percentage"))
    cost = _mapping(payload.get("cost"))
    estimated_cost = _number(cost.get("total_cost_usd"))
    duration = _number(cost.get("total_duration_ms"))
    branch = _text(_mapping(payload.get("worktree")).get("branch"))
    audit = _cache(cache_dir / "status/audit-summary.json") if cache_dir is not None else {}
    workspace = _mapping(payload.get("workspace"))
    project = _text(workspace.get("project_dir"), 4096) or _text(workspace.get("current_dir"), 4096)
    complexity = _cache(cache_dir / "complexity" / (hashlib.sha256(project.encode("utf-8")).hexdigest() + ".json")) if cache_dir is not None and project else {}
    rendered: dict[str, str] = {}
    if "shield" in segments:
        posture = safety_profile.removeprefix("infrastructure-")
        rendered["shield"] = ("🛡" if unicode else "[G]") + " " + posture
    if model:
        rendered["model"] = model
    if effort:
        rendered["effort"] = effort
    if context is not None:
        rendered["context"] = f"ctx {_bar(context, ascii_only)} {context}%"
    if "heat" in segments and context is not None and context >= 70:
        heat = "caution" if context < 85 else "hot" if context < 95 else "critical"
        rendered["heat"] = {"caution": "⚠", "hot": "🔥", "critical": "💨"}[heat] if unicode else heat.upper()
    rate_parts = []
    if five_hour is not None:
        rate_parts.append(f"5h:{five_hour}%")
    if seven_day is not None:
        rate_parts.append(f"7d:{seven_day}%")
    if rate_parts:
        rendered["rate_limits"] = " ".join(rate_parts)
    cost_parts = []
    if estimated_cost is not None:
        cost_parts.append(f"est ${estimated_cost:.2f}")
    if duration is not None:
        cost_parts.append(_duration(duration))
    if cost_parts:
        rendered["cost_duration"] = " ".join(cost_parts)
    if branch:
        rendered["branch"] = branch
    warnings = audit.get("warnings")
    denials = audit.get("denials")
    if audit.get("window") == "24h" and isinstance(warnings, int) and isinstance(denials, int):
        rendered["audit"] = f"24h {warnings}W {denials}D"
    classification = _text(complexity.get("classification"), 20)
    if classification:
        rendered["complexity"] = f"KISS {classification}"
    active = [segment for segment in segments if segment in rendered]
    limit = columns if isinstance(columns, int) and columns > 0 else 120
    separator = " | "
    while active and len(separator.join(rendered[segment] for segment in active)) > limit:
        removable = sorted(active, key=lambda segment: (int(priorities[segment]), -active.index(segment)))
        active.remove(removable[0])
    return separator.join(rendered[segment] for segment in active)


def _load_profiles(path: Path) -> Mapping[str, Any]:
    if path.is_symlink() or not path.is_file() or path.stat().st_size > 65_536:
        return {}
    try:
        return _mapping(json.loads(path.read_text(encoding="utf-8")))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return {}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--profiles", type=Path, required=True)
    parser.add_argument("--profile", required=True)
    parser.add_argument("--safety-profile", required=True)
    parser.add_argument("--cache-dir", type=Path)
    parser.add_argument("--ascii", action="store_true")
    parser.add_argument("--debug", action="store_true")
    args = parser.parse_args(argv)
    try:
        payload = json.load(sys.stdin)
        if not isinstance(payload, dict):
            return 0
        profiles = _load_profiles(args.profiles)
        try:
            columns = int(os.environ.get("COLUMNS", "120"))
        except ValueError:
            columns = 120
        encoding = (sys.stdout.encoding or "").lower()
        line = render_status_line(
            payload,
            profiles,
            args.profile,
            args.safety_profile,
            args.cache_dir,
            ascii_only=args.ascii or "utf" not in encoding,
            columns=columns,
        )
        if line:
            print(line)
    except (OSError, UnicodeError, ValueError, json.JSONDecodeError, TypeError):
        if args.debug:
            print("ai-guardrails status line input was unavailable", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
