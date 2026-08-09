#!/usr/bin/env python3
"""Content-free GitHub Actions test and job summaries."""

from __future__ import annotations

from email.parser import BytesParser
import os
import platform
import re
import subprocess
import sys
import tarfile
import time
import tomllib
import unittest
import zipfile
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


def _normalise_distribution_name(value: str) -> str:
    """Return the filename form of a Python distribution name."""
    return re.sub(r"[-_.]+", "_", value).lower()


def _package_metadata() -> tuple[str, str]:
    """Read the package name and its existing single-sourced version."""
    data = tomllib.loads((REPOSITORY_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    name = data.get("project", {}).get("name")
    if not isinstance(name, str) or not name:
        raise ValueError("pyproject.toml does not contain a project name")
    from ai_engineering_guardrails import __version__

    if not isinstance(__version__, str) or not __version__:
        raise ValueError("package version is not a non-empty string")
    return name, __version__


def validate_release_tag(tag: str, package_version: str | None = None) -> str:
    """Require the project's documented ``v<version>`` release-tag convention."""
    _, version = _package_metadata()
    expected_version = package_version or version
    expected_tag = f"v{expected_version}"
    if tag != expected_tag:
        raise ValueError(f"release tag must be {expected_tag!r}; received {tag!r}")
    return expected_version


def _metadata_from_bytes(content: bytes, label: str) -> tuple[str, str]:
    parsed = BytesParser().parsebytes(content)
    name = parsed.get("Name")
    version = parsed.get("Version")
    if not isinstance(name, str) or not name or not isinstance(version, str) or not version:
        raise ValueError(f"{label} does not contain required Name and Version metadata")
    return name, version


def _validate_distribution_metadata(content: bytes, label: str, project_name: str, version: str) -> None:
    name, artifact_version = _metadata_from_bytes(content, label)
    if _normalise_distribution_name(name) != _normalise_distribution_name(project_name):
        raise ValueError(f"{label} metadata project name does not match {project_name!r}")
    if artifact_version != version:
        raise ValueError(f"{label} metadata version does not match {version!r}")


def validate_release_artifacts(
    directory: Path,
    project_name: str | None = None,
    package_version: str | None = None,
) -> tuple[Path, Path]:
    """Validate the exact wheel and sdist set a release workflow may publish."""
    configured_name, configured_version = _package_metadata()
    name = project_name or configured_name
    version = package_version or configured_version
    if not directory.is_dir():
        raise ValueError(f"release directory does not exist: {directory}")

    paths = sorted(directory.iterdir(), key=lambda path: path.name)
    if any(not path.is_file() for path in paths):
        raise ValueError("release directory must contain files only")
    unexpected = [path.name for path in paths if not (path.name.endswith(".whl") or path.name.endswith(".tar.gz"))]
    if unexpected:
        raise ValueError("release directory contains unexpected files: " + ", ".join(unexpected))

    wheels = [path for path in paths if path.name.endswith(".whl")]
    sdists = [path for path in paths if path.name.endswith(".tar.gz")]
    if len(wheels) != 1 or len(sdists) != 1:
        raise ValueError("release directory must contain exactly one wheel and one source distribution")

    wheel, sdist = wheels[0], sdists[0]
    normalised_name = _normalise_distribution_name(name)
    if not wheel.name.startswith(f"{normalised_name}-{version}-"):
        raise ValueError(f"wheel filename does not match {name!r} version {version!r}")
    expected_sdist = f"{name}-{version}.tar.gz"
    if sdist.name != expected_sdist:
        raise ValueError(f"source distribution filename must be {expected_sdist!r}")

    with zipfile.ZipFile(wheel) as archive:
        metadata_paths = [item for item in archive.namelist() if item.endswith(".dist-info/METADATA")]
        if len(metadata_paths) != 1:
            raise ValueError("wheel must contain exactly one dist-info/METADATA file")
        _validate_distribution_metadata(archive.read(metadata_paths[0]), wheel.name, name, version)

    with tarfile.open(sdist, mode="r:gz") as archive:
        try:
            metadata_member = archive.getmember(f"{name}-{version}/PKG-INFO")
        except KeyError as error:
            raise ValueError("source distribution does not contain root PKG-INFO") from error
        if not metadata_member.isfile():
            raise ValueError("source distribution root PKG-INFO is not a regular file")
        handle = archive.extractfile(metadata_member)
        if handle is None:
            raise ValueError("source distribution PKG-INFO cannot be read")
        _validate_distribution_metadata(handle.read(), sdist.name, name, version)

    return wheel, sdist


def _required_option(arguments: Sequence[str], option: str, usage: str) -> str:
    if len(arguments) != 2 or arguments[0] != option or not arguments[1]:
        raise ValueError(f"usage: {usage}")
    return arguments[1]


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


def run_release_tag_check(arguments: Sequence[str]) -> int:
    """Check that a published GitHub Release tag matches the package version."""
    try:
        tag = _required_option(arguments, "--tag", "ci.py release-tag --tag v<package-version>")
        version = validate_release_tag(tag)
    except ValueError as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
    print(f"release tag matches package version: {tag} ({version})")
    return 0


def run_release_artifact_check(arguments: Sequence[str]) -> int:
    """Check the narrow artifact set supplied to the privileged publish job."""
    try:
        directory = Path(_required_option(arguments, "--directory", "ci.py release-artifacts --directory release"))
        wheel, sdist = validate_release_artifacts(directory)
    except (OSError, ValueError, tarfile.TarError, zipfile.BadZipFile) as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
    print(f"release artifacts validated: {wheel.name}, {sdist.name}")
    return 0


def main(arguments: Sequence[str] | None = None) -> int:
    values = list(sys.argv[1:] if arguments is None else arguments)
    if not values:
        print("usage: ci.py {test|validate|summary|release-tag|release-artifacts} [...]", file=sys.stderr)
        return 2
    command = values.pop(0)
    if command == "test":
        return run_tests(values)
    if command == "validate" and not values:
        return run_validation()
    if command == "summary" and not values:
        return write_job_summary()
    if command == "release-tag":
        return run_release_tag_check(values)
    if command == "release-artifacts":
        return run_release_artifact_check(values)
    print("usage: ci.py {test|validate|summary|release-tag|release-artifacts} [...]", file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
