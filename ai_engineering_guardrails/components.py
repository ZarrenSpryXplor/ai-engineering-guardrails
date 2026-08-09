"""Read-only component inspection and local digest-bound trust records.

Components are never imported, executed, installed, or fetched.  The scanner is
deliberately conservative: it reports structural facts and a small set of
high-confidence indicators, not a semantic safety verdict.
"""

from __future__ import annotations

import datetime as dt
import getpass
import hashlib
import os
import re
import stat
import sys
from pathlib import Path
from typing import Any, Iterable, Mapping
from urllib.parse import urlsplit

from . import packs, policy, state
from .resources import RESOURCE_ROOT
from .scan import DOWNLOAD_EXECUTE_RE, EXTERNAL_AUTHORITY_MATCHERS, POWERSHELL_DOWNLOAD_EXECUTE_RE, locally_negated
from .util import GuardrailsError, is_link_or_reparse, path_within, read_json, sha256


ASSURANCE_ROOT = RESOURCE_ROOT / "assurance"
THRESHOLDS_PATH = ASSURANCE_ROOT / "audit-thresholds.json"
COMPONENT_SCHEMA_VERSION = 1
TRUST_SCHEMA_VERSION = 1
EXECUTABLE_SUFFIXES = {".py", ".sh", ".ps1", ".bat", ".cmd", ".exe", ".js", ".ts", ".jar"}
INSTRUCTION_NAMES = {"AGENTS.md", "CLAUDE.md", "SKILL.md"}
ENTRY_NAMES = ("SKILL.md", "AGENTS.md", "CLAUDE.md", "README.md")
REFERENCE_RE = re.compile(r"\[[^\]]+\]\(([^)#]+)\)|`([^`\n]+\.(?:py|sh|ps1|bat|cmd|json|md|toml))`", re.IGNORECASE)
PLAIN_REFERENCE_RE = re.compile(
    r"(?<![A-Za-z0-9_.-])((?:\./)?(?:scripts|tools|bin|resources?)/[A-Za-z0-9_./-]+\.(?:py|sh|ps1|bat|cmd|js|ts|json|toml|md))(?=$|[\s),.;:])",
    re.IGNORECASE,
)
URL_RE = re.compile(r"https?://([^/\s'\"`?#]+)", re.IGNORECASE)
PATTERNS = (
    ("download-piped-to-shell", DOWNLOAD_EXECUTE_RE, "Direct download-and-execute instruction or script."),
    ("powershell-download-iex", POWERSHELL_DOWNLOAD_EXECUTE_RE, "PowerShell download piped to Invoke-Expression."),
    (
        "credential-file-access",
        re.compile(
            r"(?:\.aws[\\/](?:credentials|config)|\.azure(?:[\\/]|\b)|\.config[\\/]gcloud|"
            r"\.kube[\\/]config|\.ssh[\\/](?:id_[^\s/'\"`]+|config)|(?:^|[/'\"`])\.env(?:\b|[./]))",
            re.I,
        ),
        "Credential, cloud-credential, kubeconfig, SSH key, or environment file access appears.",
    ),
    (
        "raw-secret-or-token-access",
        re.compile(
            r"(?:[\\/]var[\\/]run[\\/]secrets(?:[\\/]|\b)|\bkubectl\s+(?:get|describe)\s+secrets?\b|"
            r"\b(?:cat|type|Get-Content)\b[^\n]{0,160}\b(?:secret|token)[A-Za-z0-9_./-]*)",
            re.I,
        ),
        "Raw secret, service-account token, or Kubernetes secret access appears.",
    ),
    ("environment-dump", re.compile(r"(?:^|[;&|\s])(?:env|printenv|set(?:\s*$|\s+[A-Za-z_][A-Za-z0-9_]*)|Get-ChildItem\s+Env:)\b", re.I | re.M), "Environment-dumping command appears."),
    ("clipboard-access", re.compile(r"\b(?:pbpaste|pbcopy|xclip|xsel|Get-Clipboard|Set-Clipboard)\b", re.I), "Clipboard access appears."),
    ("browser-session-access", re.compile(r"(?:Cookies|Login Data|Local Storage|Web Data|Session Storage)", re.I), "Browser or session-store access appears."),
    ("destructive-command", re.compile(r"(?:\brm\s+-[A-Za-z]*r[A-Za-z]*f|\bgit\s+(?:reset\s+--hard|clean\s+-[A-Za-z]*f|push\s+--force)\b|\b(?:terraform|tofu)\s+destroy\b|\bkubectl\s+delete\b|\bhelm\s+(?:uninstall|delete)\b|\bdrop\s+(?:database|table|schema)\b)", re.I), "Destructive filesystem, Git, infrastructure, or database command appears."),
    ("package-publication", re.compile(r"\b(?:npm|pnpm|cargo)\s+publish\b|\btwine\s+upload\b|\bgh\s+release\s+create\b", re.I), "Package or release publication command appears."),
    (
        "untrusted-package-registry",
        re.compile(r"(?:--(?:extra-)?index-url\b|npm\s+config\s+set\s+registry\b|(?:npm|pnpm|yarn)\s+config\s+set\s+registry\b)", re.I),
        "A package registry override appears and needs explicit supply-chain review.",
    ),
    (
        "package-installation-steering",
        re.compile(r"\b(?:pip(?:3)?|uv|npm|pnpm|yarn)\s+(?:install|add)\s+[^\s]+", re.I),
        "Package-installation instruction appears and needs task-specific authority.",
    ),
    (
        "mutable-component-reference",
        re.compile(
            r"(?:@(?:latest|main|master|head)\b|\b(?:uses|ref|branch)\s*[:=]\s*['\"]?(?:main|master|head)\b|"
            r"(?:git\+)?https?://[^\s'\"]+/(?:tree|blob)/(?:main|master)\b)",
            re.I,
        ),
        "Mutable component or branch reference appears.",
    ),
    (
        "global-instruction-or-hook-change",
        re.compile(r"\b(?:modify|replace|overwrite|rewrite|delete|disable)\b.{0,100}\b(?:AGENTS\.md|CLAUDE\.md|global\s+(?:instruction|hook)|user\s+(?:instruction|hook))\b", re.I),
        "Instruction or hook modification appears and needs explicit authority.",
    ),
    ("guardrail-weakening", re.compile(r"(?:ignore|disable|bypass|turn\s+off|weaken).{0,80}(?:guardrail|hook|approval|sandbox|permission|network|instruction)", re.I), "Instruction appears to weaken a guardrail, approval, sandbox, or network boundary."),
    *(
        ("external-content-authority", pattern, "External content is presented as authority rather than evidence.")
        for pattern in EXTERNAL_AUTHORITY_MATCHERS
    ),
    ("absolute-local-path", re.compile(r"(?:[A-Za-z]:[\\/](?:Users|home)[\\/]|/(?:Users|home)/)[^\s'\"`]+"), "Machine-specific absolute path appears; use a portable relative path or documented variable."),
)


def _now() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc).replace(microsecond=0)


def _iso(value: dt.datetime) -> str:
    return value.astimezone(dt.timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _timestamp(value: object) -> dt.datetime | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo is not None else None


def load_thresholds(path: Path = THRESHOLDS_PATH) -> dict[str, Any]:
    value = read_json(path, default={})
    if not isinstance(value, dict) or value.get("schema_version") != 1:
        raise GuardrailsError("component-audit threshold resource has an unsupported schema")
    component = value.get("component")
    skills = value.get("skills")
    if not isinstance(component, Mapping) or not isinstance(skills, Mapping):
        raise GuardrailsError("component-audit threshold resource is incomplete")
    expected_component = {"maximum_files", "maximum_depth", "maximum_file_bytes", "maximum_total_bytes", "maximum_line_length"}
    expected_skills = {"description_characters", "body_characters", "reference_characters", "reference_file_characters", "always_loaded_characters", "characters_per_estimated_token", "catalogue_reference_budget_characters"}
    if set(component) != expected_component or set(skills) != expected_skills:
        raise GuardrailsError("component-audit threshold resource has unsupported fields")
    if any(not isinstance(item, int) or isinstance(item, bool) or item <= 0 for item in (*component.values(), *skills.values())):
        raise GuardrailsError("component-audit thresholds must be positive integers")
    return {"schema_version": 1, "component": dict(component), "skills": dict(skills)}


def validate_resources() -> None:
    load_thresholds()


def _root(path: Path) -> Path:
    try:
        candidate = path.expanduser()
        if not candidate.is_absolute():
            candidate = Path.cwd() / candidate
        if is_link_or_reparse(candidate):
            raise GuardrailsError("component root must not be a symbolic link")
        candidate = candidate.resolve(strict=True)
    except OSError as exc:
        raise GuardrailsError(f"component path cannot be resolved: {path}") from exc
    if not candidate.is_dir() and not candidate.is_file():
        raise GuardrailsError("component path must be a regular file or directory")
    return candidate


def _is_executable(path: Path, mode: int | None = None) -> bool:
    try:
        current_mode = mode if mode is not None else path.stat().st_mode
    except OSError:
        return False
    return path.suffix.lower() in EXECUTABLE_SUFFIXES or bool(current_mode & 0o111)


def _component_files(root: Path, limits: Mapping[str, int]) -> tuple[list[Path], list[dict[str, Any]], int]:
    """Enumerate regular files without following links or device nodes."""
    findings: list[dict[str, Any]] = []
    if root.is_file():
        try:
            metadata = root.lstat()
        except OSError as exc:
            raise GuardrailsError("component file cannot be inspected") from exc
        if is_link_or_reparse(root) or not stat.S_ISREG(metadata.st_mode):
            raise GuardrailsError("component file must be regular")
        size = metadata.st_size
        if size > limits["maximum_file_bytes"]:
            findings.append(
                _finding(
                    "oversized-file",
                    "warning",
                    root.name,
                    1,
                    "File exceeds the configured inspection size limit.",
                )
            )
            return [], findings, size
        return [root], findings, size
    files: list[Path] = []
    total = 0

    def walk_error(error: OSError) -> None:
        failed = Path(error.filename) if error.filename else root
        try:
            relative = failed.relative_to(root).as_posix() or "."
        except ValueError:
            relative = "."
        findings.append(
            {
                "id": "unreadable-directory",
                "level": "warning",
                "path": relative,
                "line": 1,
                "message": "Directory contents could not be enumerated.",
            }
        )

    for current, directories, names in os.walk(root, followlinks=False, onerror=walk_error):
        current_path = Path(current)
        relative_dir = current_path.relative_to(root)
        if len(relative_dir.parts) > limits["maximum_depth"]:
            findings.append({"id": "excessive-directory-depth", "level": "warning", "path": relative_dir.as_posix(), "line": 1, "message": "Directory depth exceeds the configured inspection limit."})
            directories[:] = []
            continue
        for name in list(directories):
            candidate = current_path / name
            try:
                mode = candidate.lstat().st_mode
            except OSError:
                findings.append(
                    {
                        "id": "unreadable-directory",
                        "level": "warning",
                        "path": candidate.relative_to(root).as_posix(),
                        "line": 1,
                        "message": "Directory metadata could not be read.",
                    }
                )
                directories.remove(name)
                continue
            if stat.S_ISLNK(mode) or is_link_or_reparse(candidate):
                findings.append({"id": "symbolic-link", "level": "error", "path": candidate.relative_to(root).as_posix(), "line": 1, "message": "Symbolic links are not inspected."})
                directories.remove(name)
            elif not stat.S_ISDIR(mode):
                findings.append({"id": "non-directory-entry", "level": "warning", "path": candidate.relative_to(root).as_posix(), "line": 1, "message": "Non-directory filesystem entry was not inspected."})
                directories.remove(name)
        for name in names:
            candidate = current_path / name
            relative = candidate.relative_to(root).as_posix()
            try:
                metadata = candidate.lstat()
            except OSError:
                findings.append({"id": "unreadable-file", "level": "warning", "path": relative, "line": 1, "message": "File metadata could not be read."})
                continue
            mode = metadata.st_mode
            if stat.S_ISLNK(mode) or is_link_or_reparse(candidate):
                findings.append({"id": "symbolic-link", "level": "error", "path": relative, "line": 1, "message": "Symbolic links are not inspected."})
                continue
            if not stat.S_ISREG(mode):
                findings.append({"id": "non-regular-file", "level": "warning", "path": relative, "line": 1, "message": "Device, socket, or other non-regular file was not inspected."})
                continue
            size = metadata.st_size
            total += size
            if size > limits["maximum_file_bytes"]:
                findings.append({"id": "oversized-file", "level": "warning", "path": relative, "line": 1, "message": "File exceeds the configured inspection size limit."})
                continue
            files.append(candidate)
            if len(files) > limits["maximum_files"]:
                findings.append({"id": "excessive-file-count", "level": "warning", "path": ".", "line": 1, "message": "Component exceeds the configured file-count limit."})
                return files[:limits["maximum_files"]], findings, total
            if total > limits["maximum_total_bytes"]:
                findings.append({"id": "excessive-tree-size", "level": "warning", "path": ".", "line": 1, "message": "Component exceeds the configured total-size limit."})
                return files, findings, total
    return sorted(files), findings, total


def _text(path: Path) -> str | None:
    try:
        data = path.read_bytes()
    except OSError:
        return None
    if b"\0" in data:
        return None
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        return None


def _relative(root: Path, path: Path) -> str:
    return path.name if root.is_file() else path.relative_to(root).as_posix()


def _line(text: str, position: int) -> int:
    return text.count("\n", 0, position) + 1


def _safe_counterexample(text: str, position: int) -> bool:
    """Keep only locally negated or explicitly fenced examples out of hits."""
    if locally_negated(text, position):
        return True
    fences = list(re.finditer(r"(?m)^(?:```|~~~)", text[:position]))
    if len(fences) % 2 == 0:
        return False
    prefix = text[max(0, fences[-1].start() - 160) : fences[-1].start()]
    return bool(
        re.search(
            r"(?i)(?:do\s+not|never|must\s+not|unsafe|non-executable)[^\n]{0,100}(?:run|execute|example)[^\n]*\n?$",
            prefix,
        )
    )


def _references(root: Path, path: Path, text: str) -> tuple[set[str], list[tuple[str, int]]]:
    references: set[str] = set()
    unsafe: list[tuple[str, int]] = []
    base = path.parent if root.is_dir() else root.parent
    matches = sorted(
        [*REFERENCE_RE.finditer(text), *PLAIN_REFERENCE_RE.finditer(text)],
        key=lambda match: match.start(),
    )
    for match in matches:
        raw = next((item for item in match.groups() if item), "").strip()
        if not raw or "://" in raw or raw.startswith("#"):
            continue
        portable = raw.replace("\\", "/")
        relative = Path(portable)
        line = _line(text, match.start())
        if relative.is_absolute() or portable.startswith("~"):
            unsafe.append(("absolute-reference", line))
            continue
        if ".." in relative.parts:
            unsafe.append(("parent-traversal-reference", line))
            continue
        candidate = (base / relative).resolve(strict=False)
        if not path_within(candidate, root if root.is_dir() else root.parent):
            unsafe.append(("parent-traversal-reference", line))
            continue
        try:
            rendered = candidate.relative_to(root if root.is_dir() else root.parent).as_posix()
        except ValueError:
            unsafe.append(("parent-traversal-reference", line))
            continue
        references.add(rendered)
    return references, unsafe


def _digest(root: Path, files: Iterable[Path]) -> str:
    digest = hashlib.sha256()
    base = root if root.is_dir() else root.parent
    for path in sorted(files, key=lambda item: _relative(root, item)):
        relative = _relative(root, path)
        digest.update(relative.encode("utf-8", errors="surrogateescape"))
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


def _finding(identifier: str, level: str, path: str, line: int, message: str) -> dict[str, Any]:
    return {"id": identifier, "level": level, "path": path, "line": line, "message": message}


def _instruction_context(path: Path) -> bool:
    name = path.name.lower()
    return (
        path.name in INSTRUCTION_NAMES
        or name.endswith((".agent.md", ".instructions.md", ".rules"))
        or "hook" in name
        or "mcp" in name
        or path.suffix.lower() in EXECUTABLE_SUFFIXES
    )


def _component_type(root: Path, files: Iterable[Path]) -> str:
    names = {path.name for path in files}
    if "SKILL.md" in names:
        return "skill"
    if names & {"AGENTS.md", "CLAUDE.md"}:
        return "instruction-bundle"
    if any(path.name.endswith(".agent.md") for path in files):
        return "custom-agent"
    if any("mcp" in path.name.lower() or "hook" in path.name.lower() for path in files):
        return "hook-or-mcp-bundle"
    return "local-component"


def inspect(path: Path) -> dict[str, Any]:
    """Inspect a local component tree without evaluating any of its content."""
    root = _root(path)
    thresholds = load_thresholds()["component"]
    files, findings, total_bytes = _component_files(root, thresholds)
    relative_files = {_relative(root, item): item for item in files}
    texts: dict[str, str] = {}
    references: set[str] = set()
    hashes: dict[str, list[str]] = {}
    entry = next((name for name in ENTRY_NAMES if name in relative_files), None)
    if entry is None:
        findings.append(_finding("missing-entry-document", "warning", ".", 1, "No conventional entry instruction document was found."))
    declared_instruction_references: set[str] = set()
    if entry is not None:
        entry_text = _text(relative_files[entry])
        if entry_text is not None:
            entry_references, _ = _references(root, relative_files[entry], entry_text)
            declared_instruction_references = {
                reference
                for reference in entry_references
                if Path(reference).suffix.lower() in {".md", ".rst", ".txt"}
                and re.search(r"(?:^|[-_/])(readme|setup|install|instruction|usage)(?:[-_.]|$)", reference, re.I)
            }
    for relative, file in relative_files.items():
        content = _text(file)
        if content is None:
            findings.append(_finding("binary-or-undecodable-file", "warning", relative, 1, "Binary or non-UTF-8 content was not interpreted."))
        else:
            texts[relative] = content
            file_references, unsafe_references = _references(root, file, content)
            references.update(file_references)
            for identifier, line in unsafe_references:
                findings.append(
                    _finding(
                        identifier,
                        "warning",
                        relative,
                        line,
                        "Local component references must remain beneath the inspected root.",
                    )
                )
            for line_number, line in enumerate(content.splitlines(), start=1):
                if len(line) > thresholds["maximum_line_length"]:
                    findings.append(_finding("oversized-line", "warning", relative, line_number, "Line exceeds the configured inspection length."))
                if re.fullmatch(r"[A-Za-z0-9+/=_-]{400,}", line.strip()):
                    findings.append(_finding("obfuscated-looking-content", "warning", relative, line_number, "Long encoded-looking content requires review."))
            instruction_context = _instruction_context(file) or relative == entry or relative in declared_instruction_references
            for identifier, pattern, message in PATTERNS:
                if not instruction_context and identifier not in {
                    "guardrail-weakening",
                    "external-content-authority",
                    "absolute-local-path",
                    "mutable-component-reference",
                }:
                    continue
                for match in pattern.finditer(content):
                    match_position = (
                        match.start("authority")
                        if identifier == "external-content-authority" and "authority" in match.re.groupindex
                        else match.start()
                    )
                    if _safe_counterexample(content, match_position):
                        continue
                    findings.append(_finding(identifier, "error" if identifier in {"download-piped-to-shell", "powershell-download-iex", "guardrail-weakening"} else "warning", relative, _line(content, match.start()), message))
            if instruction_context:
                for match in URL_RE.finditer(content):
                    try:
                        host = urlsplit(match.group(0)).hostname
                    except ValueError:
                        host = None
                    if host:
                        findings.append(
                            _finding(
                                "network-destination",
                                "note",
                                relative,
                                _line(content, match.start()),
                                f"Network destination declared: {host.lower()}",
                            )
                        )
        content_hash = sha256(file.read_bytes())
        hashes.setdefault(content_hash, []).append(relative)
        mode = file.stat().st_mode
        if _is_executable(file, mode):
            if file.name.startswith("."):
                findings.append(_finding("hidden-executable", "warning", relative, 1, "Hidden executable content requires explicit review."))
            if relative not in references:
                findings.append(_finding("unreferenced-executable", "warning", relative, 1, "Executable resource is not referenced by an inspected instruction file."))
    root_prefix = root if root.is_dir() else root.parent
    for reference in sorted(references):
        target = root_prefix / reference
        if reference not in relative_files or not target.exists():
            findings.append(_finding("missing-referenced-file", "warning", reference, 1, "Referenced local file is missing or outside the inspected set."))
    for digest, paths in sorted(hashes.items()):
        if len(paths) > 1:
            findings.append(_finding("duplicate-content", "note", paths[0], 1, f"Exact duplicate content appears in {len(paths)} files."))
    nested = [relative for relative in relative_files if Path(relative).name in INSTRUCTION_NAMES and relative != entry]
    for relative in sorted(nested):
        findings.append(_finding("nested-instruction-file", "note", relative, 1, "Nested instruction file can change local authority and should be reviewed."))
    return {
        "schema_version": COMPONENT_SCHEMA_VERSION,
        "component_type": _component_type(root, files),
        "component_digest": _digest(root, files),
        "entry_document": entry,
        "files_inspected": len(files),
        "total_bytes_inspected": total_bytes,
        "referenced_files": sorted(references),
        "unreferenced_files": sorted(relative for relative in relative_files if relative not in references and relative != entry),
        "executable_files": sorted(relative for relative, file in relative_files.items() if _is_executable(file)),
        "findings": sorted(findings, key=lambda item: (item["level"], item["path"], item["line"], item["id"])),
        "limitations": [
            "Inspection is static and local. It does not execute, import, install, or fetch the component.",
            "A clean result is not proof of safety, publisher identity, or runtime behaviour.",
        ],
    }


def _trust_records(home: Path) -> list[dict[str, Any]]:
    selected = home.expanduser().resolve(strict=False)
    values = state.load_state(selected).get("component_trust", [])
    return [dict(value) for value in values if isinstance(value, Mapping)] if isinstance(values, list) else []


def _trust_location_records(home: Path) -> list[dict[str, str]]:
    """Read opaque locator metadata separately from human trust records."""
    selected = home.expanduser().resolve(strict=False)
    values = state.load_state(selected).get("component_trust_locations", [])
    result: list[dict[str, str]] = []
    if not isinstance(values, list):
        return result
    for value in values:
        if not isinstance(value, Mapping):
            continue
        digest = value.get("component_digest")
        locator = value.get("component_locator_digest")
        if (
            isinstance(digest, str)
            and isinstance(locator, str)
            and re.fullmatch(r"[0-9a-f]{64}", digest)
            and re.fullmatch(r"[0-9a-f]{64}", locator)
        ):
            result.append({"component_digest": digest, "component_locator_digest": locator})
    return result


def _validate_trust_record(value: object) -> dict[str, Any]:
    required = {
        "schema_version", "component_digest", "component_type", "source", "version_reference", "reviewed_by", "permission_tier", "reviewed_at", "expires_at", "finding_summary", "state",
    }
    if not isinstance(value, Mapping) or set(value) != required:
        raise GuardrailsError("component trust record fields do not match the supported schema")
    digest = value.get("component_digest")
    if not isinstance(digest, str) or re.fullmatch(r"[0-9a-f]{64}", digest) is None:
        raise GuardrailsError("component trust record has an invalid digest")
    if not isinstance(value.get("component_type"), str) or not _safe_label(value["component_type"]):
        raise GuardrailsError("component trust record has an invalid component type")
    for field in ("source", "version_reference", "reviewed_by", "permission_tier"):
        if not _safe_metadata_text(value.get(field)):
            raise GuardrailsError(f"component trust record has an invalid {field}")
    if _timestamp(value.get("reviewed_at")) is None or _timestamp(value.get("expires_at")) is None:
        raise GuardrailsError("component trust record has invalid timestamps")
    if _timestamp(value["expires_at"]) <= _timestamp(value["reviewed_at"]):
        raise GuardrailsError("component trust expiry must follow review time")
    if not isinstance(value.get("finding_summary"), Mapping) or any(not isinstance(item, int) or item < 0 for item in value["finding_summary"].values()):
        raise GuardrailsError("component trust record finding summary is invalid")
    if value.get("schema_version") != TRUST_SCHEMA_VERSION or value.get("state") not in {"active", "revoked"}:
        raise GuardrailsError("component trust record has unsupported state")
    return dict(value)


def _safe_label(value: str) -> bool:
    return bool(re.fullmatch(r"[A-Za-z0-9_.:-]{1,120}", value))


def _safe_metadata_text(value: object) -> bool:
    """Keep human trust labels useful without retaining likely secret values."""
    if (
        not isinstance(value, str)
        or not value.strip()
        or len(value) > 300
        or any(ord(character) < 32 or ord(character) == 127 for character in value)
    ):
        return False
    secret_value = re.compile(
        r"(?:\b(?:api[_-]?key|access[_-]?token|secret|password|credential)\b\s*(?:=|:)\s*\S+|"
        r"https?://[^/\s:@]+:[^/\s@]+@|\b(?:ghp|github_pat|sk|AKIA)[A-Za-z0-9_-]{16,}\b)",
        re.I,
    )
    return secret_value.search(value) is None


def _locator_digest(path: Path) -> str:
    """Return a local-only opaque locator; never persist the component path."""
    return sha256(str(_root(path)).encode("utf-8", errors="surrogateescape"))


def trust(
    path: Path,
    home: Path,
    *,
    expires_at: str,
    source: str,
    version_reference: str = "local",
    reviewed_by: str | None = None,
    permission_tier: str = "review-only",
    dry_run: bool,
    input_stream: Any | None = None,
    output_stream: Any | None = None,
) -> dict[str, Any]:
    """Record interactively confirmed local trust for one content digest."""
    component = inspect(path)
    incomplete = {
        "symbolic-link",
        "oversized-file",
        "excessive-file-count",
        "excessive-tree-size",
        "excessive-directory-depth",
        "unreadable-directory",
        "unreadable-file",
        "non-directory-entry",
        "non-regular-file",
    }
    if any(item["id"] in incomplete for item in component["findings"]):
        raise GuardrailsError("component inspection was incomplete; it cannot receive a digest-bound trust record")
    expiry = _timestamp(expires_at)
    now = _now()
    if expiry is None or expiry <= now or expiry > now + dt.timedelta(days=366):
        raise GuardrailsError("component trust expiry must be a future ISO-8601 timestamp within one year")
    for field, value in (("source", source), ("version_reference", version_reference), ("reviewed_by", reviewed_by or getpass.getuser()), ("permission_tier", permission_tier)):
        if not _safe_metadata_text(value):
            raise GuardrailsError(f"component trust {field} must be concise non-empty text")
    finding_summary: dict[str, int] = {}
    for item in component["findings"]:
        finding_summary[item["level"]] = finding_summary.get(item["level"], 0) + 1
    record = _validate_trust_record(
        {
            "schema_version": TRUST_SCHEMA_VERSION,
            "component_digest": component["component_digest"],
            "component_type": component["component_type"],
            "source": source.strip(),
            "version_reference": version_reference.strip(),
            "reviewed_by": (reviewed_by or getpass.getuser()).strip(),
            "permission_tier": permission_tier.strip(),
            "reviewed_at": _iso(now),
            "expires_at": _iso(expiry),
            "finding_summary": dict(sorted(finding_summary.items())),
            "state": "active",
        }
    )
    if dry_run:
        return record
    input_stream = input_stream or sys.stdin
    output_stream = output_stream or sys.stderr
    if not input_stream.isatty() or not output_stream.isatty():
        raise GuardrailsError("component trust requires an interactive TTY confirmation")
    confirmation = f"TRUST COMPONENT {record['component_digest']}"
    print("Trust is local, digest-bound, and does not grant runtime authority.", file=output_stream)
    print(f"Type exactly: {confirmation}", file=output_stream)
    if input_stream.readline().rstrip("\r\n") != confirmation:
        raise GuardrailsError("component trust confirmation did not match; no trust record was written")
    selected_home = home.expanduser().resolve(strict=False)
    current = state.load_state(selected_home)
    values = [_validate_trust_record(item) for item in current.get("component_trust", []) if isinstance(item, Mapping)]
    values = [item for item in values if item["component_digest"] != record["component_digest"]]
    values.append(record)
    current["component_trust"] = sorted(values, key=lambda item: item["component_digest"])
    locator = _locator_digest(path)
    locations = _trust_location_records(selected_home)
    locations = [
        item
        for item in locations
        if item["component_locator_digest"] != locator and item["component_digest"] != record["component_digest"]
    ]
    locations.append({"component_digest": record["component_digest"], "component_locator_digest": locator})
    current["component_trust_locations"] = sorted(
        locations,
        key=lambda item: (item["component_locator_digest"], item["component_digest"]),
    )
    state.save_state(selected_home, current, dry_run=False)
    return record


def revoke(digest: str, home: Path, *, dry_run: bool) -> bool:
    if re.fullmatch(r"[0-9a-f]{64}", digest) is None:
        raise GuardrailsError("component digest must be a lowercase SHA-256 value")
    selected_home = home.expanduser().resolve(strict=False)
    current = state.load_state(selected_home)
    values = [_validate_trust_record(item) for item in current.get("component_trust", []) if isinstance(item, Mapping)]
    changed = False
    for value in values:
        if value["component_digest"] == digest and value["state"] != "revoked":
            value["state"] = "revoked"
            changed = True
    if changed and not dry_run:
        current["component_trust"] = values
        state.save_state(selected_home, current, dry_run=False)
    return changed


def list_trust(home: Path, *, now: dt.datetime | None = None) -> list[dict[str, Any]]:
    now = now or _now()
    values = [_validate_trust_record(item) for item in _trust_records(home)]
    result: list[dict[str, Any]] = []
    for value in values:
        expiry = _timestamp(value["expires_at"])
        current_state = "revoked" if value["state"] == "revoked" else "expired" if expiry is not None and expiry <= now else "trusted"
        result.append({**value, "trust_status": current_state})
    return sorted(result, key=lambda item: item["component_digest"])


def _known_entries(candidate: Path) -> list[Path]:
    """Select one known component file or one immediate child without links."""
    if candidate.is_symlink() or candidate.is_file():
        return [candidate]
    if not candidate.is_dir():
        return []
    try:
        return [child for child in sorted(candidate.iterdir()) if child.is_symlink() or child.is_dir() or child.is_file()]
    except OSError:
        return [candidate]


def _known_paths(home: Path, repo: Path | None = None) -> list[Path]:
    # Keep product path discovery in install.py; this command only chooses
    # bounded local instruction/skill/agent/hook candidates from those paths.
    from . import install

    selected = home.expanduser().resolve(strict=False)
    paths = [child for candidate in install.known_component_paths(selected) for child in _known_entries(candidate)]
    if repo is not None:
        root = _root(repo)
        candidates = [
            *(root / name for name in ("AGENTS.md", "CLAUDE.md", "SKILL.md")),
            *(root / relative for relative in (".agents/skills", ".claude/skills", ".cursor/skills", ".codex/agents", ".github/agents")),
        ]
        paths.extend(child for candidate in candidates for child in _known_entries(candidate))
    return sorted(set(paths), key=lambda item: str(item))


def audit(home: Path, *, repo: Path | None = None, now: dt.datetime | None = None) -> dict[str, Any]:
    records = {item["component_digest"]: item for item in list_trust(home, now=now)}
    locators = {item["component_locator_digest"]: item for item in _trust_location_records(home)}
    values: list[dict[str, Any]] = []
    for path in _known_paths(home, repo):
        try:
            result = inspect(path)
        except GuardrailsError as exc:
            values.append({"path": path.name, "state": "unmanaged", "error": str(exc)})
            continue
        record = records.get(result["component_digest"])
        locator = locators.get(_locator_digest(path))
        component_state = record["trust_status"] if record else "modified" if locator else "untrusted"
        values.append({
            "path": path.name,
            "component_type": result["component_type"],
            "component_digest": result["component_digest"],
            "state": component_state,
            "finding_counts": {level: sum(item["level"] == level for item in result["findings"]) for level in ("error", "warning", "note")},
        })
    return {"schema_version": 1, "components": sorted(values, key=lambda item: (item["state"], item["path"])), "limitation": "Known product instruction, skill, and agent locations only; unrelated user files were not inspected."}


def _skill_files(path: Path | None) -> list[Path]:
    if path is None:
        core = policy.discover_skills()
        packed = sorted((RESOURCE_ROOT / "packs").rglob("skills/*/SKILL.md"))
        return sorted({*core, *packed})
    root = _root(path)
    if root.is_file():
        if root.name != "SKILL.md":
            raise GuardrailsError("selected skill path must be SKILL.md or a directory containing skills")
        return [root]
    direct = root / "SKILL.md"
    if direct.is_file():
        return [direct]
    return sorted(item for item in root.glob("*/SKILL.md") if item.is_file() and not item.is_symlink())


GENERIC_ROUTING_PREFIX_RE = re.compile(
    r"^(?:this\s+skill\s+(?:provides|offers)|a\s+comprehensive\s+workflow\s+for|use\s+this\s+skill\s+when\s+you\s+need\s+to)\b",
    re.IGNORECASE,
)
ROUTING_STOP_WORDS = {
    "workstation", "and", "or", "the", "for", "with", "from", "into", "without", "while", "using",
    "never", "change", "changes", "review", "verify", "inspect", "bounded", "local", "source", "project",
}


def _skill_catalogue_tier(skill_file: Path) -> str:
    try:
        skill_file.relative_to(RESOURCE_ROOT / "skills")
        return "core"
    except ValueError:
        pass
    for parent in skill_file.parents:
        manifest = parent / "pack.json"
        if manifest.is_file() and path_within(manifest, RESOURCE_ROOT / "packs"):
            return packs.catalogue_tier(packs.load_pack(manifest))
    return "contextual"


def _routing_description_issue(name: str, description: str) -> str | None:
    stripped = description.strip()
    if GENERIC_ROUTING_PREFIX_RE.match(stripped):
        return "Description starts with generic boilerplate instead of its primary task and trigger terms."
    terms = {
        token
        for token in re.findall(r"[a-z0-9]+", name.lower().removeprefix("workstation-"))
        if token not in ROUTING_STOP_WORDS and len(token) > 2
    }
    front = stripped[:120].lower()
    if terms and not any(term in front for term in terms):
        return "Description does not front-load a task-specific name or trigger term."
    return None


def _routing_terms(description: str) -> set[str]:
    return {
        token
        for token in re.findall(r"[a-z0-9]+", description.lower())
        if len(token) > 2 and token not in ROUTING_STOP_WORDS
    }


def skills_audit(path: Path | None = None) -> dict[str, Any]:
    """Bound skill reads and estimate routing-catalogue pressure without rewriting."""
    configured = load_thresholds()
    thresholds = configured["skills"]
    component_limits = configured["component"]
    files = _skill_files(path)
    if not files:
        raise GuardrailsError("no SKILL.md files found")
    findings: list[dict[str, Any]] = []
    items: list[dict[str, Any]] = []
    duplicate_hashes: dict[str, list[str]] = {}
    descriptions: dict[str, str] = {}
    incomplete_reasons: list[dict[str, str]] = []
    audit_complete = True
    absolute_path_pattern = next(pattern for identifier, pattern, _ in PATTERNS if identifier == "absolute-local-path")
    for skill_file in files:
        label = skill_file.parent.name
        bounded_files, boundary_findings, _total_bytes = _component_files(skill_file.parent, component_limits)
        if boundary_findings:
            audit_complete = False
            for boundary in boundary_findings:
                identifier = "skill-symbolic-link" if boundary["id"] == "symbolic-link" else boundary["id"]
                relative = boundary["path"]
                detail = f"Audit incomplete: {boundary['message']}"
                findings.append(_finding(identifier, "error", f"{label}/{relative}", 1, detail))
                incomplete_reasons.append({"skill": label, "id": identifier, "path": relative, "detail": detail})
            continue
        texts: dict[Path, str] = {}
        invalid_text: Path | None = None
        for child in bounded_files:
            child_text = _text(child)
            if child_text is None:
                invalid_text = child
                break
            texts[child] = child_text
        if invalid_text is not None or skill_file not in texts:
            audit_complete = False
            relative = (
                invalid_text.relative_to(skill_file.parent).as_posix()
                if invalid_text is not None
                else "SKILL.md"
            )
            detail = "Audit incomplete: binary, undecodable, or unavailable skill content was not interpreted."
            findings.append(_finding("invalid-skill-text", "error", f"{label}/{relative}", 1, detail))
            incomplete_reasons.append({"skill": label, "id": "invalid-skill-text", "path": relative, "detail": detail})
            continue
        content = texts[skill_file]
        name_line = re.search(r"(?m)^name\s*:\s*(\S.*?)\s*$", content)
        if name_line is None:
            findings.append(
                _finding(
                    "missing-skill-name",
                    "warning",
                    label,
                    1,
                    "Add a portable name field matching the skill directory.",
                )
            )
        try:
            fields, body = policy.parse_skill(skill_file)
        except GuardrailsError as exc:
            findings.append(_finding("invalid-skill-frontmatter", "error", label, 1, str(exc)))
            fields, body = {}, content
        description = fields.get("description", "")
        if description:
            descriptions[str(fields.get("name", label))] = description
        if len(description.strip()) < 20:
            findings.append(_finding("weak-routing-description", "warning", label, 1, "Skill description is missing or too short to route work reliably."))
        routing_issue = _routing_description_issue(str(fields.get("name", label)), description)
        if routing_issue is not None:
            findings.append(_finding("routing-description-not-front-loaded", "warning", label, 1, routing_issue))
        if len(description) > thresholds["description_characters"]:
            findings.append(_finding("oversized-description", "warning", label, 1, "Skill description exceeds the configured concise-routing limit."))
        if len(body) > thresholds["body_characters"]:
            findings.append(_finding("oversized-skill-body", "warning", label, 1, "SKILL.md body exceeds the configured always-loaded guidance limit."))
        for match in absolute_path_pattern.finditer(content):
            if not _safe_counterexample(content, match.start()):
                findings.append(_finding("absolute-skill-path", "warning", label, _line(content, match.start()), "Skill contains a machine-specific absolute path."))
        references, unsafe_references = _references(skill_file.parent, skill_file, content)
        for identifier, line in unsafe_references:
            findings.append(
                _finding(
                    identifier,
                    "warning",
                    label,
                    line,
                    "Skill references must remain beneath the selected skill root.",
                )
            )
        reference_characters = 0
        for reference in sorted(references):
            target = skill_file.parent / reference
            if target not in texts:
                findings.append(_finding("missing-skill-reference", "warning", f"{label}/{reference}", 1, "Referenced skill resource is missing."))
                continue
            text = texts[target]
            reference_characters += len(text)
            duplicate_hashes.setdefault(sha256(text.encode("utf-8")), []).append(f"{label}/{reference}")
            if len(text) > thresholds["reference_file_characters"]:
                findings.append(_finding("oversized-skill-reference", "warning", f"{label}/{reference}", 1, "Reference exceeds the per-file context estimate limit."))
        if reference_characters > thresholds["reference_characters"]:
            findings.append(_finding("oversized-skill-references", "warning", label, 1, "Referenced material exceeds the total context estimate limit."))
        if len(body) > thresholds["always_loaded_characters"] and not references:
            findings.append(_finding("missing-progressive-disclosure", "warning", label, 1, "Large always-loaded skill content has no referenced detail to defer."))
        for child in bounded_files:
            if child == skill_file:
                continue
            relative = child.relative_to(skill_file.parent).as_posix()
            if _is_executable(child) and relative not in references:
                findings.append(_finding("undeclared-skill-executable", "warning", f"{label}/{relative}", 1, "Executable skill resource is not referenced by SKILL.md."))
            if relative not in references and not _is_executable(child):
                findings.append(_finding("unreferenced-skill-resource", "note", f"{label}/{relative}", 1, "Resource is not referenced by SKILL.md."))
        content_hash = sha256(content.encode("utf-8"))
        duplicate_hashes.setdefault(content_hash, []).append(f"{label}/SKILL.md")
        characters = len(content) + reference_characters
        items.append({
            "name": fields.get("name", label),
            "catalogue_tier": _skill_catalogue_tier(skill_file),
            "description_characters": len(description),
            "body_characters": len(body),
            "reference_file_count": len(references),
            "reference_characters": reference_characters,
            "reference_estimated_tokens": (reference_characters + thresholds["characters_per_estimated_token"] - 1) // thresholds["characters_per_estimated_token"],
            "estimated_tokens": (characters + thresholds["characters_per_estimated_token"] - 1) // thresholds["characters_per_estimated_token"],
        })
    for labels in duplicate_hashes.values():
        if len(labels) > 1:
            findings.append(_finding("duplicate-skill-content", "warning", labels[0], 1, f"Exact duplicate skill content appears in {len(labels)} files."))
    overlaps: list[dict[str, Any]] = []
    names = sorted(descriptions)
    for index, first in enumerate(names):
        first_terms = _routing_terms(descriptions[first])
        for second in names[index + 1 :]:
            second_terms = _routing_terms(descriptions[second])
            union = first_terms | second_terms
            similarity = len(first_terms & second_terms) / len(union) if union else 0.0
            exact = descriptions[first].casefold() == descriptions[second].casefold()
            if exact or similarity >= 0.6:
                overlap = {
                    "skills": [first, second],
                    "kind": "exact" if exact else "near",
                    "similarity_percent": round(similarity * 100),
                }
                overlaps.append(overlap)
                findings.append(
                    _finding(
                        "duplicate-routing-description" if exact else "overlapping-routing-description",
                        "warning",
                        first,
                        1,
                        f"Routing purpose overlaps {second}; confirm that their boundaries remain distinct.",
                    )
                )
    total_description_characters = sum(len(description) for description in descriptions.values())
    reference_budget = thresholds["catalogue_reference_budget_characters"]
    pressure_percent = round(100 * total_description_characters / reference_budget) if reference_budget else 0
    pressure = "low" if pressure_percent < 50 else "moderate" if pressure_percent < 75 else "high" if pressure_percent < 100 else "exceeds-reference"
    sorted_items = sorted(items, key=lambda item: item["name"])
    default_items = [item for item in sorted_items if item["catalogue_tier"] in {"core", "contextual"}] if path is None else []
    default_description_characters = sum(item["description_characters"] for item in default_items)
    default_pressure_percent = round(100 * default_description_characters / reference_budget) if reference_budget else 0
    default_pressure = "low" if default_pressure_percent < 50 else "moderate" if default_pressure_percent < 75 else "high" if default_pressure_percent < 100 else "exceeds-reference"
    tier_counts = {
        tier: sum(item["catalogue_tier"] == tier for item in sorted_items)
        for tier in ("core", "contextual", "specialist")
    }
    return {
        "schema_version": 1,
        "audit_complete": audit_complete,
        "incomplete_reasons": incomplete_reasons,
        "token_estimate_method": f"characters divided by {thresholds['characters_per_estimated_token']}, rounded up; not a vendor tokenizer",
        "catalogue": {
            "scope": "bundled" if path is None else "selected-local",
            "skill_count": len(files),
            "parsed_skill_count": len(sorted_items),
            "tier_counts": tier_counts,
            "total_description_characters": total_description_characters,
            "longest_descriptions": [
                {"name": item["name"], "characters": item["description_characters"]}
                for item in sorted(sorted_items, key=lambda item: (-item["description_characters"], item["name"]))[:5]
            ],
            "estimated_catalogue_pressure": {
                "label": "estimate",
                "level": pressure,
                "description_only_percent_of_reference": pressure_percent,
                "reference_characters": reference_budget,
                "limitation": "Actual Codex skill metadata capacity depends on model context plus other installed and plugin skills; names and paths are not included in this description-only estimate.",
            },
            "fresh_default" if path is None else "selected_installation": {
                "skill_count": len(default_items) if path is None else len(sorted_items),
                "description_characters": default_description_characters if path is None else total_description_characters,
                "estimated_pressure": {
                    "label": "estimate",
                    "level": default_pressure if path is None else pressure,
                    "description_only_percent_of_reference": default_pressure_percent if path is None else pressure_percent,
                },
            },
            "routing_overlap_warnings": overlaps,
        },
        "skills": sorted_items,
        "findings": sorted(findings, key=lambda item: (item["level"], item["path"], item["id"])),
    }
