#!/usr/bin/env python3
"""Content-free GitHub Actions test and job summaries."""

from __future__ import annotations

import os
import platform
import subprocess
import sys
import time
import unittest
from pathlib import Path
from typing import Sequence


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))


OUTCOME_LABELS = {
    "success": "Passed",
    "failure": "Failed",
    "cancelled": "Cancelled",
    "skipped": "Skipped",
    "unknown": "Unknown",
}


def _summary_path() -> Path | None:
    value = os.environ.get("GITHUB_STEP_SUMMARY")
    return Path(value) if value else None


def _escape_cell(value: object) -> str:
    return str(value).replace("\\", "\\\\").replace("|", "\\|").replace("\r", " ").replace("\n", " ")


def _run_url() -> str | None:
    server = os.environ.get("GITHUB_SERVER_URL")
    repository = os.environ.get("GITHUB_REPOSITORY")
    run_id = os.environ.get("GITHUB_RUN_ID")
    if not server or not repository or not run_id:
        return None
    return f"{server.rstrip('/')}/{repository}/actions/runs/{run_id}"


def _append_summary(lines: Sequence[str]) -> None:
    target = _summary_path()
    if target is None:
        return
    with target.open("a", encoding="utf-8", newline="\n") as handle:
        handle.write("\n".join(lines) + "\n")


def _platform_label() -> str:
    configured = os.environ.get("CI_SUMMARY_PLATFORM")
    if configured:
        return configured
    return f"{platform.system()} / Python {sys.version_info.major}.{sys.version_info.minor}"


def run_tests(arguments: Sequence[str]) -> int:
    """Run unittest arguments and append aggregate, content-free results."""
    started = time.monotonic()
    program = unittest.main(module=None, argv=["unittest", *arguments], exit=False)
    result = program.result
    if result is None:
        return 2
    passed = result.wasSuccessful()
    title = _escape_cell(os.environ.get("CI_TEST_SUMMARY_TITLE", "Unit tests"))
    lines = [
        f"### {title}",
        "",
        f"Platform: {_escape_cell(_platform_label())}",
        "",
        "| Result | Tests | Failures | Errors | Skipped | Expected failures | Unexpected successes | Duration |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
        "| "
        + " | ".join(
            (
                "Passed" if passed else "Failed",
                str(result.testsRun),
                str(len(result.failures)),
                str(len(result.errors)),
                str(len(result.skipped)),
                str(len(result.expectedFailures)),
                str(len(result.unexpectedSuccesses)),
                f"{time.monotonic() - started:.1f}s",
            )
        )
        + " |",
    ]
    run_url = _run_url()
    if run_url:
        lines.extend(("", f"[Open workflow run]({run_url})"))
    _append_summary(lines)
    return 0 if passed else 1


def run_validation() -> int:
    """Run repository validation and summarize its fixed, content-free outcomes."""
    result = subprocess.run(
        [sys.executable, str(REPOSITORY_ROOT / "tools/guardrails.py"), "validate"],
        cwd=REPOSITORY_ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    sys.stdout.write(result.stdout)
    sys.stderr.write(result.stderr)
    codex = next(
        (line.partition(":")[2].strip() for line in result.stdout.splitlines() if line.startswith("codex execpolicy check:")),
        None,
    )
    spacelift = next(
        (
            line.partition(":")[2].strip()
            for line in result.stdout.splitlines()
            if line.startswith("Spacelift policy validation:")
        ),
        None,
    )
    if result.returncode == 0 and (codex is None or spacelift is None):
        print("error: validation output did not contain expected fixed outcome lines", file=sys.stderr)
        return 1
    checks = [
        ("Repository validation", "Passed" if result.returncode == 0 else "Failed"),
        ("Codex execpolicy", "Skipped" if codex and "skipped" in codex else "Passed" if codex else "Unknown"),
        ("Spacelift policy structure", "Passed" if spacelift else "Unknown"),
        (
            "OPA semantic Rego",
            "Skipped" if spacelift and "skipped semantic" in spacelift else "Passed" if spacelift else "Unknown",
        ),
    ]
    lines = [
        f"### {_escape_cell(os.environ.get('CI_VALIDATION_SUMMARY_TITLE', 'Repository validation'))}",
        "",
        f"Platform: {_escape_cell(_platform_label())}",
        "",
        "| Check | Outcome |",
        "| --- | --- |",
        *(f"| {_escape_cell(label)} | {outcome} |" for label, outcome in checks),
    ]
    run_url = _run_url()
    if run_url:
        lines.extend(("", f"[Open workflow run]({run_url})"))
    _append_summary(lines)
    return result.returncode


def write_job_summary() -> int:
    """Append a content-free table of fixed workflow step outcomes."""
    title = _escape_cell(os.environ.get("CI_SUMMARY_TITLE", "CI job"))
    platform_label = _escape_cell(_platform_label())
    job_result = os.environ.get("CI_SUMMARY_RESULT", "unknown").lower()
    if job_result not in OUTCOME_LABELS:
        job_result = "unknown"
    lines = [
        f"### {title}",
        "",
        f"Result: **{_escape_cell(OUTCOME_LABELS.get(job_result, job_result.title()))}**  ",
        f"Platform: {platform_label}",
        "",
        "| Check | Outcome |",
        "| --- | --- |",
    ]
    for raw_line in os.environ.get("CI_SUMMARY_CHECKS", "").splitlines():
        if not raw_line.strip():
            continue
        label, separator, outcome = raw_line.partition("=")
        if not separator or not label.strip() or not outcome.strip():
            raise ValueError("CI_SUMMARY_CHECKS entries must use label=outcome")
        normalised = outcome.strip().lower()
        if normalised not in OUTCOME_LABELS or normalised == "unknown":
            raise ValueError(f"unsupported CI check outcome: {outcome.strip()}")
        lines.append(
            f"| {_escape_cell(label.strip())} | "
            f"{_escape_cell(OUTCOME_LABELS.get(normalised, normalised.title()))} |"
        )
    run_url = _run_url()
    if run_url:
        lines.extend(("", f"[Open workflow run]({run_url})"))
    _append_summary(lines)
    return 0


def main(arguments: Sequence[str] | None = None) -> int:
    values = list(sys.argv[1:] if arguments is None else arguments)
    if not values:
        print("usage: ci.py {test|validate|summary} [...]", file=sys.stderr)
        return 2
    command = values.pop(0)
    if command == "test":
        return run_tests(values)
    if command == "validate" and not values:
        return run_validation()
    if command == "summary" and not values:
        return write_job_summary()
    print("usage: ci.py {test|validate|summary} [...]", file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
