"""Deterministic repository-change complexity signals; never execute repository code."""

from __future__ import annotations

import datetime as dt
import fnmatch
import json
import re
import subprocess
import tomllib
from pathlib import Path
from typing import Any, Mapping, Sequence

from .scan import IGNORED_PARTS
from . import terminal_ux
from .resources import RESOURCE_ROOT
from .util import GuardrailsError, atomic_write, json_bytes, sha256


def _git(repo: Path, arguments: Sequence[str]) -> bytes:
    try:
        result = subprocess.run(["git", "-C", str(repo), *arguments], capture_output=True, check=False, timeout=10)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise GuardrailsError("Git is unavailable or did not respond while collecting complexity signals") from exc
    if result.returncode:
        raise GuardrailsError(result.stderr.decode("utf-8", errors="replace").strip() or "Git could not inspect the selected baseline")
    return result.stdout


def _inside_git(repo: Path) -> bool:
    try:
        return _git(repo, ("rev-parse", "--is-inside-work-tree")).strip() == b"true"
    except GuardrailsError:
        return False


def _has_head(repo: Path) -> bool:
    try:
        result = subprocess.run(
            ["git", "-C", str(repo), "rev-parse", "--verify", "--quiet", "HEAD^{commit}"],
            capture_output=True,
            check=False,
            timeout=10,
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    return result.returncode == 0


def _split_z(value: bytes) -> list[str]:
    return [part.decode("utf-8", errors="surrogateescape") for part in value.split(b"\0") if part]


def _name_status(repo: Path, diff_args: Sequence[str]) -> list[tuple[str, str]]:
    parts = _split_z(_git(repo, ("diff", "--name-status", "-z", *diff_args)))
    result: list[tuple[str, str]] = []
    index = 0
    while index < len(parts):
        status = parts[index]
        index += 1
        if index >= len(parts):
            break
        path = parts[index]
        index += 1
        if status.startswith(("R", "C")) and index < len(parts):
            path = parts[index]
            index += 1
        result.append((status[:1], path))
    return result


def _numstat(repo: Path, diff_args: Sequence[str]) -> list[tuple[int, int, str]]:
    result: list[tuple[int, int, str]] = []
    for row in _split_z(_git(repo, ("diff", "--numstat", "-z", *diff_args))):
        try:
            added, removed, path = row.split("\t", 2)
        except ValueError:
            continue
        result.append((int(added) if added.isdigit() else 0, int(removed) if removed.isdigit() else 0, path))
    return result


def _untracked(repo: Path) -> list[str]:
    return [entry[3:] for entry in _split_z(_git(repo, ("status", "--porcelain=v1", "-z", "--untracked-files=all"))) if entry.startswith("?? ")]


def _line_count(path: Path) -> int:
    if path.is_symlink() or not path.is_file() or path.stat().st_size > 1_048_576:
        return 0
    try:
        return len(path.read_bytes().splitlines())
    except OSError:
        return 0


def _matches(relative: str, pattern: str) -> bool:
    return fnmatch.fnmatchcase(relative, pattern) or (pattern.startswith("**/") and fnmatch.fnmatchcase(relative, pattern[3:]))


def _in_scope_path(path: str) -> bool:
    """Match repository scanning's exclusions without interpreting file content."""
    return not bool(set(Path(path).parts) & IGNORED_PARTS)


def _paths_by_kind(paths: Sequence[str], config: Mapping[str, Any]) -> dict[str, Any]:
    generated_prefixes = tuple(str(item) for item in config["generated_prefixes"])
    manifest_names = tuple(str(item) for item in config["manifest_names"])
    lockfile_names = set(str(item) for item in config["lockfile_names"])
    ci_prefixes = tuple(str(item) for item in config["ci_governance_prefixes"])
    ci_names = set(str(item) for item in config["ci_governance_names"])
    infra_extensions = set(str(item) for item in config["infrastructure_extensions"])
    language_extensions = {str(key): str(value) for key, value in config["language_extensions"].items()}
    generated = [path for path in paths if path.startswith(generated_prefixes)]
    manifests = [path for path in paths if any(fnmatch.fnmatchcase(Path(path).name, pattern) for pattern in manifest_names)]
    lockfiles = [path for path in paths if Path(path).name in lockfile_names]
    ci_governance = [path for path in paths if path.startswith(ci_prefixes) or Path(path).name in ci_names]
    infrastructure = [path for path in paths if Path(path).suffix in infra_extensions or "/terraform/" in f"/{path}"]
    tests = [path for path in paths if _is_test(path)]
    docs = [path for path in paths if Path(path).suffix.lower() in {".md", ".rst", ".adoc"} or path.startswith("docs/")]
    source = [path for path in paths if Path(path).suffix in language_extensions]
    return {
        "generated": generated,
        "manifests": manifests,
        "lockfiles": lockfiles,
        "ci_governance": ci_governance,
        "infrastructure": infrastructure,
        "tests": tests,
        "documentation": docs,
        "source": source,
        "languages": sorted({language_extensions[Path(path).suffix] for path in source}),
        "extension_map": language_extensions,
    }


def _is_test(path: str) -> bool:
    name = Path(path).name.lower()
    return "/tests/" in f"/{path.lower()}" or name.startswith("test_") or name.endswith(("_test.py", ".test.js", ".spec.js", ".test.ts", ".spec.ts"))


def _base_text(repo: Path, base: str, relative: str, *, from_index: bool) -> bytes | None:
    spec = f":{relative}" if from_index else f"{base}:{relative}"
    try:
        return _git(repo, ("show", spec))
    except GuardrailsError:
        return None


def _dependencies_for(path: str, data: bytes) -> set[str] | None:
    try:
        if Path(path).name == "package.json":
            value = json.loads(data)
            if not isinstance(value, dict):
                return None
            result: set[str] = set()
            for key in ("dependencies", "optionalDependencies"):
                section = value.get(key)
                if section is not None and not isinstance(section, dict):
                    return None
                if isinstance(section, dict):
                    result.update(str(name) for name in section if isinstance(name, str))
            return result
        if Path(path).name == "pyproject.toml":
            value = tomllib.loads(data.decode("utf-8"))
            project = value.get("project")
            dependencies = project.get("dependencies") if isinstance(project, dict) else None
            if dependencies is None:
                return set()
            if not isinstance(dependencies, list) or not all(isinstance(item, str) for item in dependencies):
                return None
            return {re.split(r"[<>=!~;\[ ]", item, 1)[0].strip().lower() for item in dependencies if item.strip()}
    except (UnicodeError, json.JSONDecodeError, tomllib.TOMLDecodeError):
        return None
    return None


def _new_runtime_dependencies(repo: Path, changes: Sequence[tuple[str, str]], base: str, *, staged: bool) -> tuple[list[str], list[str]]:
    added: list[str] = []
    ambiguous: list[str] = []
    for status, relative in changes:
        if status == "D" or Path(relative).name not in {"package.json", "pyproject.toml"}:
            continue
        current_path = repo / relative
        current = _base_text(repo, "", relative, from_index=True) if staged else (current_path.read_bytes() if current_path.is_file() and not current_path.is_symlink() else None)
        before = _base_text(repo, base, relative, from_index=False)
        if current is None:
            ambiguous.append(relative)
            continue
        now_deps = _dependencies_for(relative, current)
        old_deps = _dependencies_for(relative, before or b"{}")
        if now_deps is None or old_deps is None:
            ambiguous.append(relative)
        else:
            added.extend(f"{relative}:{item}" for item in sorted(now_deps - old_deps))
    return added, ambiguous


def _risk_classes(paths: Sequence[str]) -> list[str]:
    try:
        entries = json.loads((RESOURCE_ROOT / "risk/path-classification.json").read_text(encoding="utf-8")).get("classifications", [])
    except (OSError, UnicodeError, json.JSONDecodeError):
        return []
    return sorted({str(entry.get("id")) for entry in entries if isinstance(entry, dict) and any(_matches(path, str(pattern)) for path in paths for pattern in entry.get("patterns", []))})


def analyse(repo: Path, *, base: str | None = None, staged: bool = False) -> dict[str, Any]:
    root = repo.expanduser().resolve(strict=False)
    repository_identifier_hash = sha256(str(root).encode("utf-8"))
    if not root.is_dir() or not _inside_git(root):
        return {"schema_version": 1, "available": False, "repository_identifier_hash": repository_identifier_hash, "classification": "clear", "signals": [], "limitation": "Git repository unavailable; no change baseline was inspected."}
    if base is not None and staged:
        raise GuardrailsError("--base and --staged cannot be combined")
    has_head = _has_head(root)
    if base is None and not staged and not has_head:
        return {"schema_version": 1, "available": False, "repository_identifier_hash": repository_identifier_hash, "classification": "clear", "signals": [], "limitation": "Git HEAD is unavailable; no committed change baseline was inspected."}
    baseline = base or "HEAD"
    diff_args = ("--cached",) if staged else (baseline,)
    changes = [(status, path) for status, path in _name_status(root, diff_args) if _in_scope_path(path)]
    numstat = _numstat(root, diff_args)
    additions = sum(added for added, _, path in numstat if _in_scope_path(path))
    removals = sum(removed for _, removed, path in numstat if _in_scope_path(path))
    if not staged and base is None:
        for relative in _untracked(root):
            if _in_scope_path(relative) and relative not in {path for _, path in changes}:
                changes.append(("A", relative))
                additions += _line_count(root / relative)
    paths = sorted({path for _, path in changes})
    config = terminal_ux.load_thresholds()
    groups = _paths_by_kind(paths, config)
    if staged:
        previous_paths = _split_z(_git(root, ("ls-tree", "-r", "-z", "--name-only", baseline))) if has_head else []
    else:
        previous_paths = _split_z(_git(root, ("ls-tree", "-r", "-z", "--name-only", baseline)))
    old_paths = [path for path in previous_paths if _in_scope_path(path)]
    old_languages = {groups["extension_map"].get(Path(path).suffix) for path in old_paths} - {None}
    new_languages = sorted(set(groups["languages"]) - old_languages)
    new_dependencies, ambiguous_dependencies = _new_runtime_dependencies(root, changes, baseline, staged=staged)
    deleted_tests = sorted(path for status, path in changes if status == "D" and _is_test(path))
    directories = {str(Path(path).parent) for path in paths if Path(path).parent != Path(".")}
    high_risk = _risk_classes(paths)
    thresholds = config["thresholds"]
    generated_share = round(100 * len(groups["generated"]) / len(paths)) if paths else 0
    signals: list[dict[str, Any]] = []
    severity = "clear"
    def trigger(identifier: str, level: str, evidence: str, threshold: int | None, reason: str) -> None:
        nonlocal severity
        signals.append({
            "id": identifier,
            "level": level,
            "evidence": evidence,
            "threshold": threshold,
            "reason": reason,
        })
        if level == "high-change":
            severity = "high-change"
        elif severity == "clear":
            severity = "review"
    if len(paths) >= thresholds["high_files"]:
        trigger("large-change-surface", "high-change", f"{len(paths)} files changed", thresholds["high_files"], "Broad changes deserve an explicit review plan.")
    elif len(paths) >= thresholds["review_files"]:
        trigger("large-change-surface", "review", f"{len(paths)} files changed", thresholds["review_files"], "Broad changes deserve an explicit review plan.")
    if additions + removals >= thresholds["high_lines"]:
        trigger("high-line-churn", "high-change", f"{additions + removals} changed lines", thresholds["high_lines"], "Large diffs are harder to inspect exhaustively.")
    elif additions + removals >= thresholds["review_lines"]:
        trigger("high-line-churn", "review", f"{additions + removals} changed lines", thresholds["review_lines"], "Large diffs are harder to inspect exhaustively.")
    if len(directories) >= thresholds["high_directories"]:
        trigger("broad-directory-spread", "high-change", f"{len(directories)} directories touched", thresholds["high_directories"], "Cross-cutting work benefits from subsystem review.")
    elif len(directories) >= thresholds["review_directories"]:
        trigger("broad-directory-spread", "review", f"{len(directories)} directories touched", thresholds["review_directories"], "Cross-cutting work benefits from subsystem review.")
    if generated_share >= thresholds["review_generated_share_percent"] and paths:
        trigger("generated-output-dominates", "review", f"{generated_share}% generated-file share", thresholds["review_generated_share_percent"], "Review canonical sources as well as generated output.")
    if len(high_risk) >= thresholds["high_risk_paths"]:
        trigger("high-risk-governance-files", "high-change", "high-risk paths changed: " + ", ".join(high_risk), thresholds["high_risk_paths"], "Safety-sensitive changes need focused verification.")
    if len(new_dependencies) >= thresholds["new_runtime_dependencies"]:
        trigger("runtime-dependencies-added", "review", f"{len(new_dependencies)} runtime dependencies added", thresholds["new_runtime_dependencies"], "New runtime dependencies increase maintenance and supply-chain scope.")
    if new_languages:
        trigger("new-implementation-language", "review", "implementation languages introduced: " + ", ".join(new_languages), 1, "A new language adds tooling and review surface.")
    if deleted_tests:
        trigger("tests-deleted", "review", f"{len(deleted_tests)} test files deleted", 1, "Deleted tests deserve an explicit coverage review.")
    if groups["ci_governance"] and groups["infrastructure"]:
        trigger("ci-and-infrastructure", "review", "CI/governance and infrastructure changed together", 1, "Coupled delivery and infrastructure changes broaden operational review.")
    if groups["source"] and not groups["tests"]:
        trigger("source-without-tests", "review", f"{len(groups['source'])} source files changed and no test files changed", 1, "Consider whether existing or new tests cover the source change.")
    if len(groups["languages"]) > 1:
        trigger("multiple-implementation-languages", "review", ", ".join(groups["languages"]) + " touched", 2, "Multiple implementation languages broaden the review surface.")
    new_manifests = sorted(path for status, path in changes if status == "A" and path in groups["manifests"])
    if new_manifests:
        trigger("new-build-system", "review", f"new manifest files: {len(new_manifests)}", 1, "A new build or package manifest may introduce a new toolchain.")
    return {
        "schema_version": 1,
        "available": True,
        "repository_identifier_hash": repository_identifier_hash,
        "scope": "staged" if staged else f"working tree against {baseline}",
        "classification": severity,
        "signals": signals,
        "files_changed": len(paths),
        "lines_added": additions,
        "lines_removed": removals,
        "source_files_changed": len(groups["source"]),
        "test_files_changed": len(groups["tests"]),
        "documentation_files_changed": len(groups["documentation"]),
        "generated_file_share_percent": generated_share,
        "manifest_files_changed": sorted(groups["manifests"]),
        "lockfiles_changed": sorted(groups["lockfiles"]),
        "ci_governance_files_changed": sorted(groups["ci_governance"]),
        "infrastructure_files_changed": sorted(groups["infrastructure"]),
        "implementation_languages": groups["languages"],
        "implementation_languages_introduced": new_languages,
        "new_runtime_dependencies": new_dependencies,
        "ambiguous_dependency_manifests": ambiguous_dependencies,
        "deleted_test_files": deleted_tests,
        "new_files_added": len([path for status, path in changes if status == "A"]),
        "directory_spread": len(directories),
        "high_risk_paths": high_risk,
    }


def write_cache(home: Path, result: Mapping[str, Any], *, dry_run: bool = False) -> Path:
    repository_identifier_hash = result.get("repository_identifier_hash")
    if not isinstance(repository_identifier_hash, str):
        raise GuardrailsError("complexity result has no repository identifier")
    path = terminal_ux.complexity_snapshot_path(home, repository_identifier_hash)
    value = {
        "schema_version": 1,
        "repository_identifier_hash": repository_identifier_hash,
        "classification": result.get("classification", "clear"),
        "signals": list(result.get("signals", [])),
        "generated_at": dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
    }
    if not dry_run:
        atomic_write(path, json_bytes(value), mode=0o600)
    return path
