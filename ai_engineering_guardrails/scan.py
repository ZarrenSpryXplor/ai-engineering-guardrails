"""Conservative repository scanning and redacted session receipts."""

from __future__ import annotations

import fnmatch
import json
import re
import subprocess
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

from .resources import RESOURCE_ROOT, repository_output_root
from .util import GuardrailsError, atomic_write, home_path, json_bytes, read_json, sha256


MAX_SCAN_BYTES = 2_000_000
IGNORED_PARTS = {
    ".git",
    ".idea",
    ".venv",
    "__pycache__",
    "node_modules",
    "vendor",
    "vendored",
    "dist",
    "build",
    "target",
}
DOWNLOAD_EXECUTE_RE = re.compile(
    r"\b(?:curl|wget)\b[^\n|]{0,400}\|\s*(?:(?:sudo|env|command)\s+)*(?:[^\s|]+[\\/])?(?:bash|sh|zsh|python(?:3)?|pwsh|powershell)\b",
    re.IGNORECASE,
)
POWERSHELL_DOWNLOAD_EXECUTE_RE = re.compile(
    r"\b(?:invoke-webrequest|iwr|invoke-restmethod|irm)\b[^\n|]{0,400}\|\s*(?:invoke-expression|iex)\b",
    re.IGNORECASE,
)
EXTERNAL_AUTHORITY_RE = re.compile(
    r"\b(?:external\s+(?:issue|comment|pull\s+request|web\s+page|content)|"
    r"issue(?:\s+instructions?)?|comment|pull\s+request|web\s+(?:page|content)|mcp\s+output|readme(?:\s+instructions?)?)\b"
    r".{0,160}?\b(?P<authority>is\s+authoritative|overrides?|supersedes?|must\s+obey|authori[sz]es?)\b",
    re.IGNORECASE | re.DOTALL,
)
FOLLOW_EXTERNAL_OVER_LOCAL_RE = re.compile(
    r"\bfollow\b.{0,80}\b(?:web\s+page|website|readme|issue|comment)\b.{0,100}\b"
    r"(?:even\s+if|despite)\b.{0,80}\b(?:local|trusted|workstation|guardrail|policy)\b.{0,60}\b(?:disagrees?|conflicts?)\b",
    re.IGNORECASE | re.DOTALL,
)


def locally_negated(text: str, position: int) -> bool:
    """Recognise only a nearby, same-clause denial of the matched action."""
    start = max(0, position - 120)
    prefix = text[start:position]
    boundaries = list(re.finditer(r"(?:[.!?](?=\s|$)|[;,\n])", prefix))
    clause = prefix[boundaries[-1].end() :] if boundaries else prefix
    negator = r"(?:do\s+not|does\s+not|don't|doesn't|must\s+not|must\s+never|should\s+not|cannot|can't|never)"
    action = r"(?:run|execute|invoke|use|read|access|authorize|allow|follow|obey|override|supersede|grant|pipe)"
    return bool(
        re.search(rf"\b{negator}\s*$", clause, re.IGNORECASE)
        or re.search(rf"\b{negator}\s+{action}\b.{{0,100}}$", clause, re.IGNORECASE)
    )


@dataclass(frozen=True)
class Finding:
    rule_id: str
    level: str
    path: str
    line: int
    message: str
    limitation: str | None = None

    def as_dict(self) -> dict[str, Any]:
        result = {
            "rule_id": self.rule_id,
            "level": self.level,
            "path": self.path,
            "line": self.line,
            "message": self.message,
        }
        if self.limitation:
            result["limitation"] = self.limitation
        return result


def _repository_files(repo: Path) -> list[Path]:
    try:
        result = subprocess.run(
            ["git", "-C", str(repo), "ls-files", "-z", "--cached", "--others", "--exclude-standard"],
            capture_output=True,
            check=False,
            timeout=15,
        )
    except (OSError, subprocess.TimeoutExpired):
        result = None
    paths: list[Path] = []
    if result is not None and result.returncode == 0:
        for raw in result.stdout.split(b"\0"):
            if not raw:
                continue
            try:
                relative = Path(raw.decode("utf-8"))
            except UnicodeDecodeError:
                continue
            if relative.is_absolute() or ".." in relative.parts:
                continue
            target = repo / relative
            if (target.is_file() or target.is_symlink()) and not (IGNORED_PARTS & set(relative.parts)):
                paths.append(target)
        return sorted(set(paths))
    for path in repo.rglob("*"):
        if (path.is_file() or path.is_symlink()) and not (IGNORED_PARTS & set(path.relative_to(repo).parts)):
            paths.append(path)
    return sorted(paths)


def _text(path: Path) -> str | None:
    try:
        if path.is_symlink():
            return None
        if path.stat().st_size > MAX_SCAN_BYTES:
            return None
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return None


def _finding(rule_id: str, level: str, repo: Path, path: Path, line: int, message: str, limitation: str | None = None) -> Finding:
    return Finding(rule_id, level, path.relative_to(repo).as_posix(), line, message, limitation)


def _line_number(text: str, match: re.Match[str]) -> int:
    return text.count("\n", 0, match.start()) + 1


def _scan_lockfiles(repo: Path, files: Sequence[Path]) -> list[Finding]:
    by_directory: dict[Path, set[str]] = {}
    manager_by_name = {
        "package-lock.json": "npm",
        "npm-shrinkwrap.json": "npm",
        "pnpm-lock.yaml": "pnpm",
        "yarn.lock": "yarn",
    }
    for path in files:
        manager = manager_by_name.get(path.name)
        if manager:
            by_directory.setdefault(path.parent, set()).add(manager)
    findings: list[Finding] = []
    for directory, managers in sorted(by_directory.items()):
        if len(managers) > 1:
            findings.append(
                _finding(
                    "conflicting-package-managers",
                    "error",
                    repo,
                    directory / sorted(name for name in manager_by_name if (directory / name).exists())[0],
                    1,
                    f"This package root contains conflicting lockfiles for {', '.join(sorted(managers))}.",
                )
            )
    return findings


def _scan_sensitive_filenames(repo: Path, files: Sequence[Path]) -> list[Finding]:
    findings: list[Finding] = []
    for path in files:
        relative = path.relative_to(repo)
        if relative.parts[:2] == ("tests", "fixtures"):
            continue
        name = path.name.lower()
        sensitive = (
            name == ".env"
            or (name.startswith(".env.") and not name.endswith((".example", ".sample", ".template")))
            or name in {"id_rsa", "id_ed25519", "credentials.json", "service-account.json"}
            or name.endswith((".tfstate", ".tfstate.backup", ".pfx", ".p12", ".jks"))
            or (name.endswith((".key", ".pem")) and not any(word in name for word in ("example", "sample", "public", "certificate")))
        )
        if sensitive:
            findings.append(
                _finding(
                    "sensitive-artifact-filename",
                    "error",
                    repo,
                    path,
                    1,
                    "A credential-, private-key-, environment-, state-, or plan-like filename is present; inspect without reproducing values.",
                )
            )
        if name.endswith((".tfplan", ".plan")) or name in {"crash.log", "crash.json"}:
            findings.append(
                _finding(
                    "terraform-plan-or-crash-artifact",
                    "error",
                    repo,
                    path,
                    1,
                    "Saved plans and crash artifacts may contain sensitive state and should not be committed.",
                )
            )
    return findings


def _scan_ci_configuration(repo: Path, path: Path, text: str) -> list[Finding]:
    relative = path.relative_to(repo).as_posix()
    github = ".github/workflows/" in relative
    azure = (
        fnmatch.fnmatchcase(path.name.lower(), "azure-pipelines*.yml")
        or fnmatch.fnmatchcase(path.name.lower(), "azure-pipelines*.yaml")
        or relative.startswith(".azure-pipelines/")
    )
    if not github and not azure:
        return []
    findings: list[Finding] = []
    if github:
        for match in re.finditer(r"(?m)^\s*-?\s*uses:\s*([^\s#]+)@([^\s#]+)", text):
            source, ref = match.groups()
            if source.startswith("./"):
                continue
            if re.fullmatch(r"[0-9a-fA-F]{40}", ref) is None:
                findings.append(
                    _finding(
                        "unpinned-github-action",
                        "warning",
                        repo,
                        path,
                        _line_number(text, match),
                        "A third-party action reference is not pinned to a full commit digest.",
                        "Line scanning does not resolve reusable workflow provenance.",
                    )
                )
    patterns = {
        "package-publication-in-ci": r"(?mi)\b(?:npm\s+publish|twine\s+upload|dotnet\s+nuget\s+push|docker\s+push|helm\s+push)\b",
        "ci-secret-mutation": r"(?mi)\bgh\s+(?:secret|variable)\s+(?:set|delete)\b",
    }
    if github:
        patterns.update(
            {
                "broad-ci-permissions": r"(?mi)^\s*permissions:\s*write-all\s*$",
                "pull-request-target-boundary": r"(?mi)^\s*pull_request_target\s*:",
            }
        )
    if azure:
        patterns["azure-pipeline-persistent-credentials"] = r"(?mi)^\s*persistCredentials:\s*true\s*$"
    for identifier, pattern in patterns.items():
        for match in re.finditer(pattern, text):
            level = "error" if identifier in {"package-publication-in-ci", "ci-secret-mutation"} else "warning"
            findings.append(
                _finding(
                    identifier,
                    level,
                    repo,
                    path,
                    _line_number(text, match),
                    {
                        "broad-ci-permissions": "Workflow-level write-all permissions broaden the CI identity unnecessarily.",
                        "pull-request-target-boundary": "pull_request_target crosses an untrusted-code trust boundary and requires careful checkout/input review.",
                        "package-publication-in-ci": "Package or image publication appears in an ordinary workflow and requires a human-controlled release boundary.",
                        "ci-secret-mutation": "Repository or environment secret mutation appears in CI automation.",
                        "azure-pipeline-persistent-credentials": "Azure Pipelines checkout persists its credential for later steps; scope and necessity require review.",
                    }[identifier],
                    "YAML is scanned conservatively as text; this is not semantic workflow analysis.",
                )
            )
    return findings


def _scan_package_scripts(repo: Path, path: Path, text: str) -> list[Finding]:
    if path.name != "package.json" or path.relative_to(repo).parts[:2] == ("tests", "fixtures"):
        return []
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return [_finding("invalid-package-json", "error", repo, path, 1, "package.json is invalid JSON.")]
    scripts = data.get("scripts", {}) if isinstance(data, Mapping) else {}
    if not isinstance(scripts, Mapping):
        return []
    findings: list[Finding] = []
    for name, value in scripts.items():
        if not isinstance(name, str) or not isinstance(value, str):
            continue
        dangerous = name in {"preinstall", "install", "postinstall"} and (
            DOWNLOAD_EXECUTE_RE.search(value) or POWERSHELL_DOWNLOAD_EXECUTE_RE.search(value)
        )
        publication = name in {"publish", "prepublish", "prepublishOnly", "postpublish"} and re.search(
            r"\b(?:npm|pnpm|yarn)\s+publish\b", value, re.I
        )
        if dangerous or publication:
            findings.append(
                _finding(
                    "dangerous-package-lifecycle-script" if dangerous else "package-publication-script",
                    "error" if dangerous else "warning",
                    repo,
                    path,
                    1,
                    "A package lifecycle script downloads/executes content or publishes a package; review before any install or release action.",
                )
            )
    return findings


def _scan_yaml_like(repo: Path, path: Path, text: str) -> list[Finding]:
    if path.suffix.lower() not in {".yaml", ".yml"}:
        return []
    findings: list[Finding] = []
    patterns = {
        "kubernetes-privileged": r"(?mi)^\s*privileged:\s*true\s*$",
        "kubernetes-host-namespace": r"(?mi)^\s*host(?:Network|PID|IPC):\s*true\s*$",
        "kubernetes-hostpath": r"(?mi)^[ \t]*(?:-[ \t]*)?hostPath:[ \t]*$",
        "validation-bypass-flag": r"(?:--validate(?:=|\s+)false|--disable-openapi-validation|--insecure-skip-tls-verify)",
    }
    messages = {
        "kubernetes-privileged": "A privileged container setting materially expands host access.",
        "kubernetes-host-namespace": "A host namespace setting crosses the container isolation boundary.",
        "kubernetes-hostpath": "A hostPath volume requires explicit path, ownership, and threat review.",
        "validation-bypass-flag": "A Kubernetes or Helm validation/TLS bypass flag appears in configuration.",
    }
    for identifier, pattern in patterns.items():
        for match in re.finditer(pattern, text):
            findings.append(
                _finding(
                    identifier,
                    "warning" if identifier != "validation-bypass-flag" else "error",
                    repo,
                    path,
                    _line_number(text, match),
                    messages[identifier],
                    "YAML is scanned as text; anchors, templates, and merged values are not evaluated.",
                )
            )
    return findings


def _scan_unknown_remote_targets(repo: Path, path: Path, text: str) -> list[Finding]:
    relative = path.relative_to(repo).as_posix()
    if path.suffix.lower() not in {".yaml", ".yml"} and ".github/workflows/" not in relative:
        return []
    patterns = (
        (
            "kubernetes-target-not-explicit",
            r"(?mi)^\s*(?:-\s*)?(?:run:\s*)?kubectl\b(?=[^\n]*(?:apply|create|patch|replace|delete|scale|rollout\s+(?:restart|undo))\b)(?![^\n]*--context(?:=|\s+))[^\n]*$",
            "A remote Kubernetes mutation does not identify an explicit context; unknown targets are protected.",
        ),
        (
            "azure-target-not-explicit",
            r"(?mi)^\s*(?:-\s*)?(?:run:\s*)?az\b(?=[^\n]*\b(?:create|update|delete|set|deploy)\b)(?![^\n]*(?:--subscription|-s)(?:=|\s+))[^\n]*$",
            "An Azure mutation does not identify an explicit subscription; unknown targets are protected.",
        ),
    )
    findings: list[Finding] = []
    for identifier, pattern, message in patterns:
        for match in re.finditer(pattern, text):
            findings.append(
                _finding(
                    identifier,
                    "warning",
                    repo,
                    path,
                    _line_number(text, match),
                    message,
                    "Text scanning does not evaluate shell variables, aliases, workflow expressions, or target mapping at runtime.",
                )
            )
    return findings


def _scan_hook_and_mcp(repo: Path, path: Path, text: str) -> list[Finding]:
    relative = path.relative_to(repo).as_posix()
    if not any(part in relative.lower() for part in ("hook", "mcp", "settings", "trusted-components")):
        return []
    findings: list[Finding] = []
    patterns = {
        "unpinned-executable-mcp": re.compile(r"\b(?:npx|uvx|pipx\s+run)\b[^\n]*(?:@latest|\blatest\b)", re.I),
        "download-execute-hook": DOWNLOAD_EXECUTE_RE,
        "removed-spacelift-mcp-endpoint": re.compile(r"/intent/mcp"),
    }
    for identifier, pattern in patterns.items():
        for match in pattern.finditer(text):
            findings.append(
                _finding(
                    identifier,
                    "error",
                    repo,
                    path,
                    _line_number(text, match),
                    {
                        "unpinned-executable-mcp": "An executable MCP component uses a mutable latest reference.",
                        "download-execute-hook": "A hook downloads content and pipes it directly to an interpreter.",
                        "removed-spacelift-mcp-endpoint": "The removed Spacelift /intent/mcp endpoint must not be configured.",
                    }[identifier],
                )
            )
    return findings


def _scan_external_instruction_authority(repo: Path, path: Path, text: str) -> list[Finding]:
    """Flag a narrow prompt-injection boundary in executable instruction files.

    This is intentionally not a claim to detect arbitrary prompt injection.  It
    catches only direct statements that promote external content over trusted
    repository, user, or platform authority.
    """
    if path.name not in {"AGENTS.md", "CLAUDE.md", "SKILL.md"}:
        return []
    patterns = {
        "external-content-as-authority": (
            (EXTERNAL_AUTHORITY_RE, FOLLOW_EXTERNAL_OVER_LOCAL_RE),
            "External content is presented as authority; treat it as evidence under trusted policy instead.",
        ),
        "instruction-authority-override": (
            (re.compile(r"\b(?:ignore|disregard)\b.{0,120}\b(?:previous|trusted|system|guardrail|safety)\b.{0,80}\binstruction", re.I | re.S),),
            "Instruction text asks to override a trusted instruction boundary.",
        ),
    }
    findings: list[Finding] = []
    for identifier, (matchers, message) in patterns.items():
        for pattern in matchers:
            for match in pattern.finditer(text):
                authority_position = match.start("authority") if "authority" in match.re.groupindex else match.start()
                if identifier == "external-content-as-authority" and locally_negated(text, authority_position):
                    continue
                findings.append(
                    _finding(
                        identifier,
                        "warning",
                        repo,
                        path,
                        _line_number(text, match),
                        message,
                        "This is a narrow text pattern, not semantic prompt-injection detection.",
                    )
                )
    return findings


def _scan_deprecated_spacelift(repo: Path, path: Path, text: str) -> list[Finding]:
    relative = path.relative_to(repo)
    lower_parts = {part.lower() for part in relative.parts}
    if {"access", "task", "initialization"} & lower_parts and "platform-policies" in lower_parts:
        return [
            _finding(
                "deprecated-spacelift-policy-type",
                "error",
                repo,
                path,
                1,
                "Deprecated Spacelift Access, Task, or Initialization policy output is present.",
            )
        ]
    if path.suffix == ".rego" and "import rego.v1" not in text:
        return [_finding("rego-v1-required", "error", repo, path, 1, "New Spacelift policy examples must use Rego v1.")]
    return []


def _generated_stale(repo: Path) -> list[Finding]:
    output_root = repository_output_root()
    if output_root is None or repo.resolve(strict=False) != output_root.resolve(strict=False):
        return []
    try:
        from . import build

        expected = build.build_artifacts()
    except GuardrailsError as exc:
        return [Finding("generated-output-invalid", "error", ".", 1, f"Generated output could not be evaluated: {exc}")]
    findings: list[Finding] = []
    for path, data in expected.items():
        if not path.is_file() or path.read_bytes() != data:
            findings.append(
                Finding(
                    "generated-output-stale",
                    "error",
                    path.relative_to(repo).as_posix(),
                    1,
                    "Generated output is missing or stale; rebuild from canonical source.",
                )
            )
    return findings


def _changed_repository_paths(repo: Path) -> list[Path]:
    try:
        result = subprocess.run(
            ["git", "-C", str(repo), "status", "--porcelain=v1", "-z", "--untracked-files=all"],
            capture_output=True,
            check=False,
            timeout=15,
        )
    except (OSError, subprocess.TimeoutExpired):
        return []
    if result.returncode != 0:
        return []
    changed: list[Path] = []
    for item in result.stdout.split(b"\0"):
        if len(item) < 4:
            continue
        try:
            value = item[3:].decode("utf-8")
        except UnicodeDecodeError:
            continue
        if " -> " in value:
            value = value.split(" -> ", 1)[1]
        candidate = repo / value
        if candidate.exists():
            changed.append(candidate)
    return sorted(set(changed))


def _changed_risk_matches(repo: Path) -> list[tuple[Path, str, str]]:
    config = read_json(RESOURCE_ROOT / "risk/path-classification.json", default={})
    entries = config.get("classifications", []) if isinstance(config, Mapping) else []
    changed = _changed_repository_paths(repo)
    matches: list[tuple[Path, str, str]] = []
    for path in changed:
        relative = path.relative_to(repo).as_posix()
        for entry in entries:
            if not isinstance(entry, Mapping):
                continue
            if any(
                fnmatch.fnmatchcase(relative, str(pattern))
                or (
                    str(pattern).startswith("**/")
                    and fnmatch.fnmatchcase(relative, str(pattern)[3:])
                )
                for pattern in entry.get("patterns", [])
            ):
                matches.append((path, str(entry.get("id")), str(entry.get("risk_class", "unknown"))))
    return matches


def _risk_verification_requirements() -> dict[str, Mapping[str, Any]]:
    """Load the small, canonical risk-to-evidence mapping for static scan."""
    data = read_json(RESOURCE_ROOT / "risk/verification-requirements.json", default={})
    requirements = data.get("requirements") if isinstance(data, Mapping) else []
    result: dict[str, Mapping[str, Any]] = {}
    if not isinstance(requirements, list):
        return result
    for requirement in requirements:
        if not isinstance(requirement, Mapping):
            continue
        risk_class = requirement.get("risk_class")
        identifier = requirement.get("id")
        if isinstance(risk_class, str) and isinstance(identifier, str) and risk_class not in result:
            result[risk_class] = requirement
    return result


def _outcome_gaps(values: Any, expected: Any, category: str, requirement_id: str) -> list[str]:
    if not isinstance(values, Mapping) or not isinstance(expected, list):
        return [f"{requirement_id}: {category} metadata"]
    gaps: list[str] = []
    for name in expected:
        if not isinstance(name, str):
            continue
        if values.get(name) not in {"passed", "not-applicable"}:
            gaps.append(f"{requirement_id}: {category} {name}")
    return gaps


def _verification_evidence_gaps(evidence: Any, risk_classes: set[str]) -> list[str]:
    """Return missing declared evidence categories without echoing user input."""
    outcomes = evidence.get("verification_outcomes") if isinstance(evidence, Mapping) else None
    entries: dict[str, Mapping[str, Any]] = {}
    if isinstance(outcomes, list):
        for outcome in outcomes:
            if isinstance(outcome, Mapping) and isinstance(outcome.get("requirement_id"), str):
                entries.setdefault(outcome["requirement_id"], outcome)

    requirements = _risk_verification_requirements()
    gaps: list[str] = []
    for risk_class in sorted(risk_classes):
        requirement = requirements.get(risk_class)
        if requirement is None:
            gaps.append(f"{risk_class}: no canonical verification requirement")
            continue
        identifier = str(requirement["id"])
        outcome = entries.get(identifier)
        if outcome is None:
            gaps.append(f"{identifier}: missing outcome")
            continue
        gaps.extend(_outcome_gaps(outcome.get("reviews"), requirement.get("required_reviews"), "review", identifier))
        gaps.extend(
            _outcome_gaps(
                outcome.get("verification"), requirement.get("required_verification"), "verification",
                identifier,
            )
        )
    return gaps


def _scan_changed_high_risk_paths(repo: Path) -> list[Finding]:
    matched_paths: dict[Path, tuple[str, str]] = {}
    for path, identifier, risk_class in _changed_risk_matches(repo):
        if risk_class == "high":
            matched_paths.setdefault(path, (identifier, risk_class))
    matches = list(matched_paths.items())
    if not matches:
        return []
    evidence_path = repo / ".ai-guardrails-verification.json"
    evidence: Any = None
    if evidence_path.is_file():
        try:
            evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            evidence = None
    gaps = _verification_evidence_gaps(evidence, {risk_class for _, (_, risk_class) in matches})
    if not gaps:
        return []
    path, (classification, _) = matches[0]
    detail = "; ".join(gaps[:3])
    return [
        _finding(
            "high-risk-change-verification-unavailable",
            "warning",
            repo,
            path,
            1,
            f"{len(matches)} changed high-risk path(s) include class {classification}, but declared verification evidence is incomplete: {detail}.",
            "External CI and review evidence may exist; static scan only checks named outcome categories. A local verification file is optional and must contain no prompts, source, commands, or secrets.",
        )
    ]


def scan_repository(repo: Path) -> list[Finding]:
    try:
        resolved = repo.expanduser().resolve(strict=True)
    except OSError as exc:
        raise GuardrailsError(f"repository path cannot be resolved: {repo}: {exc}") from exc
    if not resolved.is_dir():
        raise GuardrailsError(f"repository path is not a directory: {resolved}")
    files = _repository_files(resolved)
    findings = _scan_lockfiles(resolved, files) + _scan_sensitive_filenames(resolved, files)
    for path in files:
        text = _text(path)
        if text is None:
            continue
        findings.extend(_scan_ci_configuration(resolved, path, text))
        findings.extend(_scan_package_scripts(resolved, path, text))
        findings.extend(_scan_yaml_like(resolved, path, text))
        findings.extend(_scan_unknown_remote_targets(resolved, path, text))
        findings.extend(_scan_hook_and_mcp(resolved, path, text))
        findings.extend(_scan_external_instruction_authority(resolved, path, text))
        findings.extend(_scan_deprecated_spacelift(resolved, path, text))
    findings.extend(_generated_stale(resolved))
    findings.extend(_scan_changed_high_risk_paths(resolved))
    return sorted(findings, key=lambda item: (item.level, item.path, item.line, item.rule_id))


def _json_report(repo: Path, findings: Sequence[Finding]) -> bytes:
    return json_bytes(
        {
            "schema_version": 1,
            "repository": str(repo.resolve(strict=False)),
            "semantic_analysis": False,
            "limitations": [
                "YAML, Rego, shell, SQL, and API schemas receive conservative structural or text checks only.",
                "Installed official validators are not invoked by scan unless a repository command explicitly does so.",
            ],
            "summary": {
                "error": sum(item.level == "error" for item in findings),
                "warning": sum(item.level == "warning" for item in findings),
                "note": sum(item.level == "note" for item in findings),
            },
            "findings": [item.as_dict() for item in findings],
        }
    )


def _sarif_report(repo: Path, findings: Sequence[Finding]) -> bytes:
    rules = {
        item.rule_id: {
            "id": item.rule_id,
            "shortDescription": {"text": item.message},
            "help": {"text": item.limitation or "Review the finding using repository-native semantic tools where available."},
        }
        for item in findings
    }
    level_map = {"error": "error", "warning": "warning", "note": "note"}
    return json_bytes(
        {
            "$schema": "https://json.schemastore.org/sarif-2.1.0.json",
            "version": "2.1.0",
            "runs": [
                {
                    "tool": {"driver": {"name": "ai-engineering-guardrails", "rules": list(rules.values())}},
                    "results": [
                        {
                            "ruleId": item.rule_id,
                            "level": level_map[item.level],
                            "message": {"text": item.message},
                            "locations": [
                                {
                                    "physicalLocation": {
                                        "artifactLocation": {"uri": item.path},
                                        "region": {"startLine": item.line},
                                    }
                                }
                            ],
                        }
                        for item in findings
                    ],
                }
            ],
        }
    )


def _junit_report(findings: Sequence[Finding]) -> bytes:
    suite = ET.Element(
        "testsuite",
        name="ai-engineering-guardrails-scan",
        tests=str(max(1, len(findings))),
        failures=str(sum(item.level == "error" for item in findings)),
        skipped=str(sum(item.level != "error" for item in findings)),
    )
    if not findings:
        ET.SubElement(suite, "testcase", name="repository-scan")
    for item in findings:
        case = ET.SubElement(suite, "testcase", name=item.rule_id, classname=item.path)
        if item.level == "error":
            failure = ET.SubElement(case, "failure", message=item.message, type=item.rule_id)
            failure.text = f"{item.path}:{item.line}: {item.message}"
        else:
            skipped = ET.SubElement(case, "skipped", message=item.level)
            skipped.text = item.message
    return ET.tostring(suite, encoding="utf-8", xml_declaration=True) + b"\n"


def render_scan(repo: Path, findings: Sequence[Finding], output_format: str) -> bytes:
    if output_format == "json":
        return _json_report(repo, findings)
    if output_format == "sarif":
        return _sarif_report(repo, findings)
    if output_format == "junit":
        return _junit_report(findings)
    if output_format != "human":
        raise GuardrailsError(f"unsupported scan output format: {output_format}")
    lines = [
        f"repository scan: {repo.resolve(strict=False)}",
        "scope: conservative static checks; no YAML, Rego, shell, SQL, or schema semantic parser is claimed",
    ]
    if not findings:
        lines.append("no findings")
    for item in findings:
        lines.append(f"{item.level}: {item.rule_id}: {item.path}:{item.line}: {item.message}")
        if item.limitation:
            lines.append(f"  limitation: {item.limitation}")
    lines.append(
        f"summary: {sum(item.level == 'error' for item in findings)} error, "
        f"{sum(item.level == 'warning' for item in findings)} warning, "
        f"{sum(item.level == 'note' for item in findings)} note"
    )
    return ("\n".join(lines) + "\n").encode("utf-8")


def run_scan(repo: Path, output_format: str, output: Path | None = None) -> tuple[list[Finding], bytes]:
    findings = scan_repository(repo)
    rendered = render_scan(repo, findings, output_format)
    if output is None:
        print(rendered.decode("utf-8"), end="")
    else:
        target = output.expanduser().resolve(strict=False)
        atomic_write(target, rendered)
        print(f"scan report written to {target}")
    return findings, rendered


def validate_spacelift_policy_structure(root: Path) -> None:
    if not root.is_dir():
        raise GuardrailsError("Spacelift policy examples are missing")
    deprecated = {"access", "task", "initialization"}
    for path in root.rglob("*"):
        if path.is_symlink():
            raise GuardrailsError(f"Spacelift policy source must not be a symbolic link: {path}")
        if path.is_dir() and path.name.lower() in deprecated:
            raise GuardrailsError(f"deprecated Spacelift policy directory: {path.name}")
        if path.suffix == ".rego":
            text = path.read_text(encoding="utf-8")
            if "import rego.v1" not in text or not re.search(r"(?m)^package\s+[A-Za-z0-9_.]+\s*$", text):
                raise GuardrailsError(f"Spacelift policy lacks Rego v1 structure: {path.relative_to(root)}")
            if re.search(r"(?mi)\b(?:access|task|initialization)\s+policy\b", text):
                raise GuardrailsError(f"deprecated Spacelift policy contract appears in {path.relative_to(root)}")
    required = {"approval", "login", "notification", "plan", "push", "trigger"}
    missing = sorted(name for name in required if not (root / name).is_dir())
    if missing:
        raise GuardrailsError(f"Spacelift policy example directory is missing: {missing[0]}")


def changed_file_count(repo: Path) -> int:
    try:
        result = subprocess.run(
            ["git", "-C", str(repo), "status", "--porcelain=v1", "-z"],
            capture_output=True,
            check=False,
            timeout=10,
        )
    except (OSError, subprocess.TimeoutExpired):
        return 0
    return len([entry for entry in result.stdout.split(b"\0") if entry]) if result.returncode == 0 else 0


def session_receipt(
    home: Path,
    repo: Path,
    products: Sequence[str],
    *,
    task_assurance: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    from . import complexity, state, terminal_ux

    selected_home = home.expanduser().resolve(strict=False)
    installed = state.load_state(selected_home)
    policy_digest = installed.get("policy_digest") or "unknown"
    summary = terminal_ux.audit_summary(selected_home, window=None)
    # Hooks do not comprehensively record allowed operations.  Do not turn that
    # absence into a deceptively precise zero in a receipt.
    counts = {"warned": summary["warnings"], "denied": summary["denials"]}
    receipt = {
        "schema_version": 2,
        "repository_identifier_hash": sha256(str(repo.resolve(strict=False)).encode("utf-8")),
        "products": list(products),
        "files_modified_count": changed_file_count(repo),
        "risk_classes": sorted({identifier for _, identifier, _ in _changed_risk_matches(repo)}),
        "decision_counts": counts,
        "allowed_operation_count": "unavailable; supported hooks do not comprehensively record allowed operations",
        "guardrail_events": summary,
        "complexity": complexity.analyse(repo),
        "verification_outcomes": [],
        "model_routing_profiles": {
            product: installed.get("products", {}).get(product, {}).get("routing_profile", "none")
            for product in products
        },
        "policy_digest": policy_digest,
        "unverified_checks": ["product model availability", "semantic YAML/Rego/API compatibility unless separately validated"],
    }
    if task_assurance is not None:
        receipt["task_assurance"] = dict(task_assurance)
    return receipt
