"""Deterministic repository-change complexity signals; never execute repository code."""

from __future__ import annotations

import datetime as dt
import fnmatch
import hashlib
import json
import os
import re
import stat
import subprocess
import tomllib
from pathlib import Path
from typing import Any, Mapping, Sequence

from .scan import IGNORED_PARTS
from . import packs, terminal_ux
from .resources import RESOURCE_ROOT
from .util import GuardrailsError, atomic_write, is_reparse_point, json_bytes, path_within, sha256


# Scanner pruning is useful for ordinary complexity signals.  Task assurance
# instead accounts for every Git change except its explicit metadata paths.
TASK_ASSURANCE_IGNORED_PARTS: frozenset[str] = frozenset()
# Cargo.lock was already part of complexity reporting before capability packs;
# keep that narrow compatibility case without inventing an unowned Rust pack.
UNPACKED_DEPENDENCY_MANIFEST_PATTERNS = ("Cargo.toml",)
UNPACKED_DEPENDENCY_LOCKFILE_PATTERNS = ("Cargo.lock",)


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


def _porcelain_entries(value: bytes) -> list[tuple[bytes, list[bytes]]]:
    """Return status records while preserving both sides of renames and copies."""
    records = [item for item in value.split(b"\0") if item]
    result: list[tuple[bytes, list[bytes]]] = []
    index = 0
    while index < len(records):
        raw = records[index]
        index += 1
        if len(raw) < 4:
            continue
        status = raw[:2]
        paths = [raw[3:]]
        if (b"R" in status or b"C" in status) and index < len(records):
            paths.append(records[index])
            index += 1
        result.append((status, paths))
    return result


def _gitlink_paths(repo: Path) -> set[str] | None:
    try:
        records = [record for record in _git(repo, ("ls-files", "--stage", "-z")).split(b"\0") if record]
    except GuardrailsError:
        return None
    paths: set[str] = set()
    for record in records:
        try:
            metadata, raw_path = record.split(b"\t", 1)
        except ValueError:
            continue
        if metadata.startswith(b"160000 "):
            paths.add(raw_path.decode("utf-8", errors="surrogateescape").replace("\\", "/"))
    return paths


def _nested_repository_issue(repo: Path, records: Sequence[tuple[bytes, Sequence[bytes]]]) -> str | None:
    """Identify changed paths whose contents are opaque to the outer Git state."""
    gitlinks = _gitlink_paths(repo)
    if gitlinks is None:
        return "Git link state could not be inspected."
    for status_code, candidates in records:
        for raw_path in candidates:
            relative = raw_path.decode("utf-8", errors="surrogateescape").replace("\\", "/").rstrip("/")
            if any(relative == gitlink or relative.startswith(gitlink + "/") for gitlink in gitlinks):
                return f"changed Git link or dirty submodule: {relative}"
            if status_code != b"??" or not relative:
                continue
            candidate = repo / relative
            if is_reparse_point(candidate):
                return f"untracked reparse-point directory is opaque: {relative}"
            probes = [candidate] if candidate.is_dir() else list(candidate.parents)
            for probe in probes:
                if probe == repo or not path_within(probe.resolve(strict=False), repo):
                    break
                marker = probe / ".git"
                try:
                    marker_status = marker.lstat()
                except FileNotFoundError:
                    continue
                except OSError:
                    return f"nested repository marker could not be inspected: {probe.relative_to(repo).as_posix()}"
                del marker_status
                nested = probe.relative_to(repo).as_posix()
                return f"untracked nested Git repository: {nested}"
    return None


def working_tree_paths(repo: Path, *, excluded_paths: Sequence[str] = ()) -> list[str]:
    """Return changed and untracked paths using the complexity module's Git view."""
    excluded = set(excluded_paths)
    try:
        records = _porcelain_entries(_git(repo, ("status", "--porcelain=v1", "-z", "--untracked-files=all")))
    except GuardrailsError:
        return []
    paths: set[str] = set()
    for _status, candidates in records:
        for candidate in candidates:
            path = candidate.decode("utf-8", errors="surrogateescape").replace("\\", "/")
            if path and path not in excluded:
                paths.add(path)
    return sorted(paths)


def _untracked_content_binding(
    repo: Path,
    records: Sequence[tuple[bytes, Sequence[bytes]]],
    excluded: set[str],
) -> tuple[bytes, str | None]:
    """Hash untracked content without retaining it in a state record."""
    binding = hashlib.sha256()
    binding.update(b"untracked-content-v1\0")
    for status, candidates in records:
        if status != b"??":
            continue
        for raw_path in candidates:
            rendered = raw_path.decode("utf-8", errors="surrogateescape")
            if rendered in excluded:
                continue
            candidate = repo / rendered
            binding.update(raw_path)
            binding.update(b"\0")
            try:
                mode = candidate.lstat().st_mode
            except OSError:
                return b"", f"untracked path metadata could not be inspected: {rendered}"
            if stat.S_ISLNK(mode):
                binding.update(b"symbolic-link\0")
                try:
                    binding.update(os.readlink(candidate).encode("utf-8", errors="surrogateescape"))
                except OSError:
                    return b"", f"untracked symbolic link could not be inspected: {rendered}"
                binding.update(b"\0")
                continue
            if not path_within(candidate.resolve(strict=False), repo):
                return b"", f"untracked path resolves outside the repository: {rendered}"
            if not stat.S_ISREG(mode):
                return b"", f"untracked non-regular path cannot be bound to repository state: {rendered}"
            binding.update(b"regular\0")
            content = hashlib.sha256()
            try:
                with candidate.open("rb") as handle:
                    while chunk := handle.read(64 * 1024):
                        content.update(chunk)
            except OSError:
                return b"", f"untracked file content could not be inspected: {rendered}"
            binding.update(content.digest())
            binding.update(b"\0")
    return binding.digest(), None


def repository_state(repo: Path, *, excluded_paths: Sequence[str] = ()) -> dict[str, Any]:
    """Return a bounded Git-state digest and explicit opacity status."""
    root = repo.expanduser().resolve(strict=False)
    if not root.is_dir() or not _inside_git(root) or not _has_head(root):
        return {
            "available": False,
            "digest": None,
            "nested_repository_state": "unavailable",
            "limitation": "Git repository or committed baseline is unavailable.",
        }
    excluded = set(excluded_paths)
    excludes = tuple(f":(exclude){path}" for path in sorted(excluded))
    try:
        head = _git(root, ("rev-parse", "--verify", "HEAD^{commit}"))
        diff = _git(root, ("diff", "--no-ext-diff", "--binary", "HEAD", "--", ".", *excludes))
        status = _git(root, ("status", "--porcelain=v1", "-z", "--untracked-files=all"))
    except GuardrailsError:
        return {
            "available": False,
            "digest": None,
            "nested_repository_state": "unavailable",
            "limitation": "Git state calculation failed.",
        }
    records = _porcelain_entries(status)
    nested_issue = _nested_repository_issue(root, records)
    if nested_issue is not None:
        return {
            "available": False,
            "digest": None,
            "nested_repository_state": "unsupported",
            "limitation": nested_issue,
        }
    accumulator = hashlib.sha256()
    accumulator.update(b"task-state-v1\0")
    accumulator.update(head)
    accumulator.update(b"\0")
    accumulator.update(diff)
    accumulator.update(b"\0")
    for status_code, candidates in records:
        selected = [
            path
            for path in candidates
            if path.decode("utf-8", errors="surrogateescape") not in excluded
        ]
        if not selected:
            continue
        accumulator.update(status_code)
        accumulator.update(b"\0")
        for path in selected:
            accumulator.update(path)
            accumulator.update(b"\0")
    untracked_binding, untracked_issue = _untracked_content_binding(root, records, excluded)
    if untracked_issue is not None:
        return {
            "available": False,
            "digest": None,
            "nested_repository_state": "unavailable",
            "limitation": untracked_issue,
        }
    accumulator.update(untracked_binding)
    return {
        "available": True,
        "digest": accumulator.hexdigest(),
        "nested_repository_state": "supported",
        "limitation": None,
    }


def repository_state_digest(repo: Path, *, excluded_paths: Sequence[str] = ()) -> str | None:
    """Hash the current supported Git state for evidence binding."""
    digest = repository_state(repo, excluded_paths=excluded_paths).get("digest")
    return digest if isinstance(digest, str) else None


def committed_baseline(repo: Path) -> str | None:
    """Return the current commit identifier for task-scope comparison."""
    try:
        value = _git(repo, ("rev-parse", "--verify", "HEAD^{commit}")).decode("ascii").strip()
    except (GuardrailsError, UnicodeError):
        return None
    return value if re.fullmatch(r"[0-9a-f]{40,64}", value) else None


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
    return [
        path.decode("utf-8", errors="surrogateescape")
        for status, paths in _porcelain_entries(_git(repo, ("status", "--porcelain=v1", "-z", "--untracked-files=all")))
        if status == b"??"
        for path in paths
    ]


def _line_count(path: Path) -> int | None:
    try:
        if path.is_symlink() or not path.is_file() or path.stat().st_size > 1_048_576:
            return None
    except OSError:
        return None
    try:
        return len(path.read_bytes().splitlines())
    except OSError:
        return None


def _matches(relative: str, pattern: str) -> bool:
    return fnmatch.fnmatchcase(relative, pattern) or (pattern.startswith("**/") and fnmatch.fnmatchcase(relative, pattern[3:]))


def in_scope_path(path: str, *, task_assurance: bool = False, excluded_paths: set[str] | None = None) -> bool:
    """Apply scanner pruning or the narrower task-assurance boundary."""
    if excluded_paths and path.replace("\\", "/") in excluded_paths:
        return False
    ignored = TASK_ASSURANCE_IGNORED_PARTS if task_assurance else IGNORED_PARTS
    return not bool(set(Path(path).parts) & ignored)


def _paths_by_kind(paths: Sequence[str], config: Mapping[str, Any]) -> dict[str, Any]:
    generated_prefixes = tuple(str(item) for item in config["generated_prefixes"])
    pack_manifests, pack_lockfiles = packs.dependency_file_patterns()
    manifest_patterns = (*pack_manifests, *UNPACKED_DEPENDENCY_MANIFEST_PATTERNS)
    lockfile_patterns = (*pack_lockfiles, *UNPACKED_DEPENDENCY_LOCKFILE_PATTERNS)
    ci_prefixes = tuple(str(item) for item in config["ci_governance_prefixes"])
    ci_names = set(str(item) for item in config["ci_governance_names"])
    infra_extensions = set(str(item) for item in config["infrastructure_extensions"])
    language_extensions = {str(key): str(value) for key, value in config["language_extensions"].items()}
    generated = [path for path in paths if path.startswith(generated_prefixes)]
    manifests = [path for path in paths if any(packs.matches_detector(path, pattern) for pattern in manifest_patterns)]
    lockfiles = [path for path in paths if any(packs.matches_detector(path, pattern) for pattern in lockfile_patterns)]
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
            peers = value.get("peerDependencies")
            peer_metadata = value.get("peerDependenciesMeta", {})
            if peers is not None and not isinstance(peers, dict):
                return None
            if not isinstance(peer_metadata, dict):
                return None
            for name in peers or {}:
                metadata = peer_metadata.get(name, {})
                if not isinstance(metadata, dict):
                    return None
                if metadata.get("optional") is not True:
                    result.add(str(name))
            return result
        if Path(path).name == "pyproject.toml":
            value = tomllib.loads(data.decode("utf-8"))
            project = value.get("project")
            if not isinstance(project, dict):
                return None
            dynamic = project.get("dynamic", [])
            if not isinstance(dynamic, list) or not all(isinstance(item, str) for item in dynamic):
                return None
            if {"dependencies", "optional-dependencies"} & set(dynamic):
                return None
            dependencies = project.get("dependencies")
            optional = project.get("optional-dependencies", {})
            if dependencies is not None and (not isinstance(dependencies, list) or not all(isinstance(item, str) for item in dependencies)):
                return None
            if not isinstance(optional, dict) or not all(
                isinstance(items, list) and all(isinstance(item, str) for item in items)
                for items in optional.values()
            ):
                return None
            entries = list(dependencies or []) + [item for items in optional.values() for item in items]
            return {re.split(r"[<>=!~;\[ ]", item, 1)[0].strip().lower() for item in entries if item.strip()}
    except (UnicodeError, json.JSONDecodeError, tomllib.TOMLDecodeError):
        return None
    return None


def _new_runtime_dependencies(
    repo: Path,
    changes: Sequence[tuple[str, str]],
    base: str,
    *,
    staged: bool,
    manifests: set[str],
    lockfiles: set[str],
) -> tuple[list[str], list[str]]:
    added: list[str] = []
    ambiguous: list[str] = []
    for status, relative in changes:
        if relative in lockfiles:
            ambiguous.append(relative)
            continue
        if relative not in manifests:
            continue
        supported = Path(relative).name in {"package.json", "pyproject.toml"}
        if not supported:
            ambiguous.append(relative)
            continue
        current_path = repo / relative
        current = (
            b"{}"
            if status == "D"
            else _base_text(repo, "", relative, from_index=True)
            if staged
            else current_path.read_bytes()
            if current_path.is_file() and not current_path.is_symlink()
            else None
        )
        before = _base_text(repo, base, relative, from_index=False)
        if current is None:
            ambiguous.append(relative)
            continue
        now_deps = set() if status == "D" else _dependencies_for(relative, current)
        old_deps = set() if before is None else _dependencies_for(relative, before)
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


def analyse(
    repo: Path,
    *,
    base: str | None = None,
    staged: bool = False,
    task_assurance: bool = False,
    excluded_paths: Sequence[str] = (),
) -> dict[str, Any]:
    root = repo.expanduser().resolve(strict=False)
    repository_identifier_hash = sha256(str(root).encode("utf-8"))
    if not root.is_dir() or not _inside_git(root):
        return {"schema_version": 1, "available": False, "repository_identifier_hash": repository_identifier_hash, "classification": "clear", "signals": [], "limitation": "Git repository unavailable; no change baseline was inspected."}
    if base is not None and staged:
        raise GuardrailsError("--base and --staged cannot be combined")
    has_head = _has_head(root)
    if base is None and not staged and not has_head:
        return {"schema_version": 1, "available": False, "repository_identifier_hash": repository_identifier_hash, "classification": "clear", "signals": [], "limitation": "Git HEAD is unavailable; no committed change baseline was inspected."}
    if not staged:
        records = _porcelain_entries(_git(root, ("status", "--porcelain=v1", "-z", "--untracked-files=all")))
        nested_issue = _nested_repository_issue(root, records)
        if nested_issue is not None:
            return {
                "schema_version": 1,
                "available": False,
                "repository_identifier_hash": repository_identifier_hash,
                "classification": "clear",
                "signals": [],
                "nested_repository_state": "unsupported",
                "limitation": nested_issue,
            }
    baseline = base or "HEAD"
    diff_args = ("--cached",) if staged else (baseline,)
    excluded = {path.replace("\\", "/") for path in excluded_paths}
    is_in_scope = lambda path: in_scope_path(path, task_assurance=task_assurance, excluded_paths=excluded)
    changes = [(status, path) for status, path in _name_status(root, diff_args) if is_in_scope(path)]
    numstat = _numstat(root, diff_args)
    additions = sum(added for added, _, path in numstat if is_in_scope(path))
    removals = sum(removed for _, removed, path in numstat if is_in_scope(path))
    if not staged:
        for relative in _untracked(root):
            if is_in_scope(relative) and relative not in {path for _, path in changes}:
                line_count = _line_count(root / relative)
                if line_count is None and task_assurance:
                    return {
                        "schema_version": 1,
                        "available": False,
                        "repository_identifier_hash": repository_identifier_hash,
                        "classification": "clear",
                        "signals": [],
                        "nested_repository_state": "supported",
                        "limitation": f"untracked file line count is unavailable: {relative}",
                    }
                changes.append(("A", relative))
                additions += line_count or 0
    paths = sorted({path for _, path in changes})
    config = terminal_ux.load_thresholds()
    groups = _paths_by_kind(paths, config)
    if staged:
        previous_paths = _split_z(_git(root, ("ls-tree", "-r", "-z", "--name-only", baseline))) if has_head else []
    else:
        previous_paths = _split_z(_git(root, ("ls-tree", "-r", "-z", "--name-only", baseline)))
    old_paths = [path for path in previous_paths if is_in_scope(path)]
    old_languages = {groups["extension_map"].get(Path(path).suffix) for path in old_paths} - {None}
    new_languages = sorted(set(groups["languages"]) - old_languages)
    new_dependencies, ambiguous_dependencies = _new_runtime_dependencies(
        root,
        changes,
        baseline,
        staged=staged,
        manifests=set(groups["manifests"]),
        lockfiles=set(groups["lockfiles"]),
    )
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
    result = {
        "schema_version": 1,
        "available": True,
        "nested_repository_state": "supported",
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
        "dependency_files_changed": sorted(set(groups["manifests"]) | set(groups["lockfiles"])),
        "deleted_test_files": deleted_tests,
        "new_files_added": len([path for status, path in changes if status == "A"]),
        "directory_spread": len(directories),
        "high_risk_paths": high_risk,
    }
    if task_assurance:
        result["changed_paths"] = paths
    return result


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
