"""Offline policy-evidence lifecycle checks.

This module deliberately validates metadata and traceability only.  It does not
fetch sources, judge policy prose, or change any policy rule.
"""

from __future__ import annotations

import datetime as dt
import re
from pathlib import Path
from typing import Any, Mapping
from urllib.parse import urlsplit

from .resources import RESOURCE_ROOT
from .util import NAME_RE, GuardrailsError, read_json


REGISTRY_PATH = RESOURCE_ROOT / "evidence" / "registry.json"
SOURCE_TYPES = {
    "research-preprint",
    "peer-reviewed",
    "official-engineering-report",
    "incident-study",
    "project-design-decision",
}
POLARITIES = {
    "negative-constraint",
    "positive-guidance",
    "principle",
    "deterministic-enforcement-explanation",
}
# Scope is intentionally a small closed vocabulary.  It makes the audit able
# to distinguish a meaningful lifecycle boundary from a free-form label while
# keeping the policy prose itself in its canonical Markdown fragment.
POLICY_SCOPES = {
    "always-loaded-behavioural-policy",
    "change-safety",
    "source-control",
    "security-and-secrets",
    "dependency-and-supply-chain",
    "infrastructure-posture",
}


def _finding(identifier: str, severity: str, detail: str) -> dict[str, str]:
    return {"id": identifier, "severity": severity, "detail": detail}


def _date(value: object) -> dt.date | None:
    if not isinstance(value, str):
        return None
    try:
        return dt.date.fromisoformat(value)
    except ValueError:
        return None


def _url_is_syntactically_valid(value: object) -> bool:
    if not isinstance(value, str) or not value or any(character.isspace() for character in value):
        return False
    try:
        parsed = urlsplit(value)
        return parsed.scheme in {"https", "http"} and bool(parsed.hostname)
    except ValueError:
        return False


def load_registry(path: Path = REGISTRY_PATH) -> dict[str, Any]:
    value = read_json(path, default={})
    if not isinstance(value, dict):
        raise GuardrailsError("policy evidence registry must be a JSON object")
    return value


def audit_registry(
    manifest: Mapping[str, Any],
    *,
    registry_path: Path = REGISTRY_PATH,
    today: dt.date | None = None,
    generated_artifacts: Mapping[Path, bytes] | None = None,
) -> dict[str, Any]:
    """Return deterministic structural errors and non-blocking review findings."""
    registry = load_registry(registry_path)
    today = today or dt.date.today()
    errors: list[dict[str, str]] = []
    reviews: list[dict[str, str]] = []
    if registry.get("schema_version") != 1:
        errors.append(_finding("unsupported-schema", "error", "registry schema_version must be 1"))

    known_fixtures = registry.get("known_fixture_ids")
    if not isinstance(known_fixtures, list) or not all(isinstance(item, str) and NAME_RE.fullmatch(item) for item in known_fixtures):
        errors.append(_finding("invalid-fixture-registry", "error", "known_fixture_ids must contain portable identifiers"))
        fixture_ids: set[str] = set()
    else:
        fixture_ids = set(known_fixtures)
        if len(fixture_ids) != len(known_fixtures):
            errors.append(_finding("duplicate-fixture-id", "error", "known_fixture_ids contains a duplicate identifier"))

    raw_sources = registry.get("sources")
    sources = raw_sources if isinstance(raw_sources, list) else []
    if not isinstance(raw_sources, list) or not sources:
        errors.append(_finding("missing-evidence-sources", "error", "registry must contain a non-empty sources list"))
    source_ids: set[str] = set()
    valid_sources: set[str] = set()
    required_source = {
        "id",
        "title",
        "url",
        "publication_date",
        "evidence_type",
        "relevance",
        "confidence",
        "last_reviewed",
        "review_after",
    }
    for index, source in enumerate(sources):
        label = f"source[{index}]"
        if not isinstance(source, Mapping):
            errors.append(_finding("invalid-evidence-source", "error", f"{label} must be an object"))
            continue
        identifier = source.get("id")
        if not isinstance(identifier, str) or not NAME_RE.fullmatch(identifier):
            errors.append(_finding("missing-evidence-id", "error", f"{label} has no portable id"))
            continue
        if identifier in source_ids:
            errors.append(_finding("duplicate-evidence-id", "error", f"duplicate evidence source id: {identifier}"))
            continue
        source_ids.add(identifier)
        missing = required_source - set(source)
        if missing:
            errors.append(_finding("incomplete-evidence-source", "error", f"{identifier} lacks {sorted(missing)[0]}"))
            continue
        if not all(isinstance(source.get(field), str) and str(source[field]).strip() for field in ("title", "relevance")):
            errors.append(_finding("invalid-evidence-text", "error", f"{identifier} needs title and relevance text"))
        if "limitations" in source and (
            not isinstance(source.get("limitations"), str) or not str(source["limitations"]).strip() or len(str(source["limitations"])) > 1000
        ):
            errors.append(_finding("invalid-evidence-limitations", "error", f"{identifier} limitations must be concise text when supplied"))
        if not _url_is_syntactically_valid(source.get("url")):
            errors.append(_finding("invalid-evidence-url", "error", f"{identifier} has a malformed source URL"))
        if source.get("evidence_type") not in SOURCE_TYPES:
            errors.append(_finding("unknown-evidence-type", "error", f"{identifier} has an unsupported evidence_type"))
        confidence = source.get("confidence")
        if not isinstance(confidence, int) or isinstance(confidence, bool) or not 0 <= confidence <= 100:
            errors.append(_finding("invalid-evidence-confidence", "error", f"{identifier} confidence must be an integer from 0 to 100"))
        publication = _date(source.get("publication_date"))
        reviewed = _date(source.get("last_reviewed"))
        review_after = _date(source.get("review_after"))
        if publication is None or reviewed is None or review_after is None:
            errors.append(_finding("invalid-evidence-date", "error", f"{identifier} needs ISO-8601 publication and review dates"))
        else:
            date_errors = False
            if publication > today:
                errors.append(_finding("future-evidence-publication", "error", f"{identifier} publication_date is in the future"))
                date_errors = True
            if reviewed > today:
                errors.append(_finding("future-evidence-review", "error", f"{identifier} last_reviewed is in the future"))
                date_errors = True
            if reviewed < publication:
                errors.append(_finding("evidence-review-before-publication", "error", f"{identifier} was reviewed before publication"))
                date_errors = True
            if review_after < reviewed:
                errors.append(_finding("invalid-evidence-review-window", "error", f"{identifier} review_after precedes last_reviewed"))
                date_errors = True
            if not date_errors and review_after < today:
                reviews.append(_finding("evidence-review-overdue", "review", f"{identifier} review date passed on {review_after.isoformat()}"))
        valid_sources.add(identifier)

    raw_policies = registry.get("policies")
    policies = raw_policies if isinstance(raw_policies, list) else []
    if not isinstance(raw_policies, list) or not policies:
        errors.append(_finding("missing-policy-evidence", "error", "registry must contain policy metadata"))
    policy_ids: set[str] = set()
    required_policy = {
        "id",
        "polarity",
        "scope",
        "evidence_source_ids",
        "rationale",
        "confidence",
        "introduced_date",
        "last_reviewed",
        "review_after",
    }
    for index, metadata in enumerate(policies):
        label = f"policy[{index}]"
        if not isinstance(metadata, Mapping):
            errors.append(_finding("invalid-policy-evidence", "error", f"{label} must be an object"))
            continue
        identifier = metadata.get("id")
        if not isinstance(identifier, str) or not NAME_RE.fullmatch(identifier):
            errors.append(_finding("missing-policy-id", "error", f"{label} has no portable id"))
            continue
        if identifier in policy_ids:
            errors.append(_finding("duplicate-policy-id", "error", f"duplicate policy metadata id: {identifier}"))
            continue
        policy_ids.add(identifier)
        missing = required_policy - set(metadata)
        if missing:
            errors.append(_finding("incomplete-policy-evidence", "error", f"{identifier} lacks {sorted(missing)[0]}"))
            continue
        polarity = metadata.get("polarity")
        if polarity not in POLARITIES:
            errors.append(_finding("unknown-policy-polarity", "error", f"{identifier} has an unsupported polarity"))
        scope = metadata.get("scope")
        if not isinstance(scope, str) or not scope.strip():
            errors.append(_finding("missing-policy-scope", "error", f"{identifier} needs a bounded scope"))
        elif scope not in POLICY_SCOPES:
            errors.append(_finding("unknown-policy-scope", "error", f"{identifier} has an unsupported scope"))
        rationale = metadata.get("rationale")
        source_references = metadata.get("evidence_source_ids")
        if not isinstance(source_references, list) or not all(isinstance(item, str) and item for item in source_references):
            errors.append(_finding("invalid-policy-evidence-reference", "error", f"{identifier} evidence_source_ids must be a string list"))
            source_references = []
        if polarity == "positive-guidance" and (
            not isinstance(rationale, str) or not rationale.strip() or not source_references
        ):
            errors.append(_finding("positive-guidance-unjustified", "error", f"{identifier} needs rationale and evidence"))
        if polarity == "negative-constraint" and (not isinstance(scope, str) or scope not in POLICY_SCOPES):
            errors.append(_finding("negative-constraint-unbounded", "error", f"{identifier} needs a bounded scope"))
        if not isinstance(rationale, str) or not rationale.strip():
            errors.append(_finding("missing-policy-rationale", "error", f"{identifier} needs a rationale"))
        for source_id in source_references:
            if source_id not in valid_sources:
                errors.append(_finding("unknown-evidence-reference", "error", f"{identifier} references unknown evidence source {source_id}"))
        confidence = metadata.get("confidence")
        if not isinstance(confidence, int) or isinstance(confidence, bool) or not 0 <= confidence <= 100:
            errors.append(_finding("invalid-policy-confidence", "error", f"{identifier} confidence must be an integer from 0 to 100"))
        introduced = _date(metadata.get("introduced_date"))
        reviewed = _date(metadata.get("last_reviewed"))
        review_after = _date(metadata.get("review_after"))
        if introduced is None or reviewed is None or review_after is None:
            errors.append(_finding("invalid-policy-date", "error", f"{identifier} needs ISO-8601 lifecycle dates"))
        else:
            date_errors = False
            if introduced > today:
                errors.append(_finding("future-policy-introduction", "error", f"{identifier} introduced_date is in the future"))
                date_errors = True
            if reviewed > today:
                errors.append(_finding("future-policy-review", "error", f"{identifier} last_reviewed is in the future"))
                date_errors = True
            if reviewed < introduced:
                errors.append(_finding("policy-review-before-introduction", "error", f"{identifier} was reviewed before introduction"))
                date_errors = True
            if review_after < reviewed:
                errors.append(_finding("invalid-policy-review-window", "error", f"{identifier} review_after precedes last_reviewed"))
                date_errors = True
            if not date_errors and review_after < today:
                reviews.append(_finding("policy-review-overdue", "review", f"{identifier} review date passed on {review_after.isoformat()}"))
        fixtures = metadata.get("fixture_ids", [])
        if not isinstance(fixtures, list) or not all(isinstance(item, str) and NAME_RE.fullmatch(item) for item in fixtures):
            errors.append(_finding("invalid-policy-fixtures", "error", f"{identifier} fixture_ids must be a string list"))
        else:
            if len(set(fixtures)) != len(fixtures):
                errors.append(_finding("duplicate-policy-fixture", "error", f"{identifier} repeats a fixture identifier"))
            for fixture in fixtures:
                if fixture not in fixture_ids:
                    errors.append(_finding("missing-policy-fixture", "error", f"{identifier} references missing fixture {fixture}"))

    manifest_fragments = manifest.get("fragments") if isinstance(manifest, Mapping) else None
    manifest_ids: set[str] = set()
    if not isinstance(manifest_fragments, list):
        errors.append(_finding("missing-canonical-policy-fragments", "error", "policy manifest must contain a fragments list"))
    else:
        for index, fragment in enumerate(manifest_fragments):
            label = f"fragment[{index}]"
            identifier = fragment.get("id") if isinstance(fragment, Mapping) else None
            if not isinstance(identifier, str) or not NAME_RE.fullmatch(identifier):
                errors.append(_finding("missing-canonical-policy-id", "error", f"{label} has no portable stable id"))
                continue
            if identifier in manifest_ids:
                errors.append(_finding("duplicate-canonical-policy-id", "error", f"duplicate canonical policy id: {identifier}"))
                continue
            manifest_ids.add(identifier)
    for identifier in sorted(manifest_ids - policy_ids):
        errors.append(_finding("generated-policy-untraceable", "error", f"canonical fragment {identifier} has no evidence metadata"))
    for identifier in sorted(policy_ids - manifest_ids):
        errors.append(_finding("unknown-policy-metadata", "error", f"policy metadata {identifier} has no canonical fragment"))

    # The audit normally operates on canonical metadata alone.  The CLI passes
    # freshly rendered in-memory artifacts as an additional deterministic check
    # that generated policy comments still identify every canonical fragment.
    if generated_artifacts is not None:
        generated_ids: set[str] = set()
        marker = re.compile(r"<!-- Canonical policy IDs?: ([a-z0-9, -]+) -->")
        for path, data in generated_artifacts.items():
            if not isinstance(path, Path) or not path.as_posix().startswith("dist/"):
                continue
            try:
                text = data.decode("utf-8")
            except UnicodeDecodeError:
                continue
            for match in marker.finditer(text):
                generated_ids.update(item.strip() for item in match.group(1).split(",") if item.strip())
        if not generated_ids:
            errors.append(_finding("generated-policy-untraceable", "error", "generated policy contains no canonical policy identifiers"))
        for identifier in sorted(manifest_ids - generated_ids):
            errors.append(_finding("generated-policy-untraceable", "error", f"generated policy does not identify canonical fragment {identifier}"))
        for identifier in sorted(generated_ids - manifest_ids):
            errors.append(_finding("generated-policy-untraceable", "error", f"generated policy identifies unknown fragment {identifier}"))

    def ordered(values: list[dict[str, str]]) -> list[dict[str, str]]:
        return sorted(values, key=lambda item: (item["severity"], item["id"], item["detail"]))

    return {
        "schema_version": 1,
        "sources": len(sources),
        "policy_records": len(policies),
        "canonical_policy_ids": sorted(manifest_ids),
        "errors": ordered(errors),
        "reviews": ordered(reviews),
        "valid": not errors,
    }


def validate_registry(manifest: Mapping[str, Any], *, registry_path: Path = REGISTRY_PATH) -> None:
    result = audit_registry(manifest, registry_path=registry_path)
    errors = result["errors"]
    if errors:
        raise GuardrailsError("policy evidence registry is invalid: " + errors[0]["detail"])


def evidence_for_policy(identifier: str, manifest: Mapping[str, Any], *, registry_path: Path = REGISTRY_PATH) -> dict[str, Any]:
    """Return one canonical policy record and its local source metadata."""
    result = audit_registry(manifest, registry_path=registry_path)
    if result["errors"]:
        raise GuardrailsError("policy evidence registry is invalid: " + result["errors"][0]["detail"])
    registry = load_registry(registry_path)
    metadata = next(
        (item for item in registry["policies"] if isinstance(item, Mapping) and item.get("id") == identifier),
        None,
    )
    if not isinstance(metadata, Mapping):
        raise GuardrailsError(f"unknown policy evidence identifier: {identifier}")
    sources = {
        item["id"]: dict(item)
        for item in registry["sources"]
        if isinstance(item, Mapping) and isinstance(item.get("id"), str)
    }
    reviewed_ids = {identifier, *metadata["evidence_source_ids"]}
    return {
        "schema_version": 1,
        "policy": dict(metadata),
        "sources": [sources[source_id] for source_id in metadata["evidence_source_ids"]],
        "review_findings": [
            item
            for item in result["reviews"]
            if any(reviewed_id in item["detail"] for reviewed_id in reviewed_ids)
        ],
    }
