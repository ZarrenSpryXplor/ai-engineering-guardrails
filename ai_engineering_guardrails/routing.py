"""Portable task routing data and native custom-agent generation."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Mapping, Sequence

from .resources import RESOURCE_ROOT
from .util import (
    CAPABILITY_TIERS,
    PRODUCTS,
    REASONING_LEVELS,
    GuardrailsError,
    one_newline,
    parse_simple_frontmatter,
    read_json,
)


ROUTING_ROOT = RESOURCE_ROOT / "routing"
DEFAULT_ROUTING_PROFILE = "balanced"
PROFILE_NAMES = ("economy", "balanced", "quality")
MODEL_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/:+-]*(?:\[[A-Za-z0-9._=,/:+-]+\])?$")
CANONICAL_AGENT_NAMES = {
    "workstation_explorer",
    "workstation_test_analyst",
    "workstation_implementer",
    "workstation_reviewer",
    "workstation_verifier",
}


def parse_agent(path: Path) -> tuple[dict[str, str], str]:
    allowed = {"name", "description", "task-class", "capability"}
    fields, body = parse_simple_frontmatter(path, required=allowed, allowed=allowed)
    if fields["name"] != path.stem:
        raise GuardrailsError(f"routing agent name must match its filename: {path}")
    if fields["capability"] not in {"read-only", "write"}:
        raise GuardrailsError(f"routing agent has unknown capability: {path}")
    return fields, body


def discover_agents(routing_root: Path = ROUTING_ROOT) -> list[Path]:
    files = sorted((routing_root / "agents").glob("*.md"))
    names: set[str] = set()
    for path in files:
        fields, _ = parse_agent(path)
        if fields["name"] in names:
            raise GuardrailsError(f"duplicate routing agent name: {fields['name']}")
        names.add(fields["name"])
    if names != CANONICAL_AGENT_NAMES:
        missing = sorted(CANONICAL_AGENT_NAMES - names)
        unexpected = sorted(names - CANONICAL_AGENT_NAMES)
        detail = f"missing {missing}" if missing else f"unexpected {unexpected}"
        raise GuardrailsError(f"canonical routing agents are invalid: {detail}")
    return files


def _load_tasks(routing_root: Path) -> tuple[dict[str, Any], dict[str, dict[str, Any]]]:
    task_data = read_json(routing_root / "task-classes.json", default={})
    if not isinstance(task_data, dict) or task_data.get("schema_version") != 1:
        raise GuardrailsError("routing task classes have an unsupported schema")
    if task_data.get("capability_tiers") != list(CAPABILITY_TIERS):
        raise GuardrailsError("routing capability tiers must be economy, balanced, and deep")
    levels = task_data.get("reasoning_levels", task_data.get("reasoning_tiers"))
    if levels != list(REASONING_LEVELS):
        raise GuardrailsError("routing reasoning levels must be low, medium, and high")
    if not isinstance(task_data.get("agent_output_limit_bytes"), int) or task_data["agent_output_limit_bytes"] <= 0:
        raise GuardrailsError("routing agent output limit must be positive")
    entries = task_data.get("task_classes")
    if not isinstance(entries, list) or not entries:
        raise GuardrailsError("routing must define task classes")
    tasks: dict[str, dict[str, Any]] = {}
    required = {"id", "description", "risk", "baseline_tier", "read_only"}
    for entry in entries:
        if not isinstance(entry, dict) or required - entry.keys():
            raise GuardrailsError("routing task class is missing required fields")
        identifier = entry["id"]
        if not isinstance(identifier, str) or not identifier or identifier in tasks:
            raise GuardrailsError(f"duplicate or invalid routing task class: {identifier}")
        if entry["risk"] not in {"low", "ordinary", "high"}:
            raise GuardrailsError(f"routing task class has unknown risk: {identifier}")
        if entry["baseline_tier"] not in CAPABILITY_TIERS or not isinstance(entry["read_only"], bool):
            raise GuardrailsError(f"routing task class has invalid tier or capability: {identifier}")
        if entry["risk"] == "high" and entry["baseline_tier"] != "deep":
            raise GuardrailsError(f"high-risk task class must use deep: {identifier}")
        tasks[identifier] = entry
    return task_data, tasks


def _load_escalation(routing_root: Path) -> dict[str, Any]:
    escalation = read_json(routing_root / "escalation-policy.json", default={})
    if not isinstance(escalation, dict) or escalation.get("schema_version") != 1:
        raise GuardrailsError("routing escalation policy has an unsupported schema")
    if escalation.get("from_tiers") != {"economy": "balanced", "balanced": "deep"}:
        raise GuardrailsError("routing escalation chain must be economy to balanced to deep")
    triggers = escalation.get("triggers")
    if not isinstance(triggers, list) or not triggers:
        raise GuardrailsError("routing escalation policy must define triggers")
    identifiers: set[str] = set()
    for trigger in triggers:
        if not isinstance(trigger, dict) or not isinstance(trigger.get("id"), str) or not trigger.get("description"):
            raise GuardrailsError("routing escalation trigger is invalid")
        if trigger["id"] in identifiers:
            raise GuardrailsError(f"duplicate routing escalation trigger: {trigger['id']}")
        identifiers.add(trigger["id"])
    constraints = escalation.get("constraints")
    if not isinstance(constraints, dict) or constraints.get("high_risk_minimum_tier") != "deep":
        raise GuardrailsError("routing escalation policy must require deep for high-risk work")
    if constraints.get("economy_may_make_high_risk_final_decision") is not False:
        raise GuardrailsError("economy routing must not make high-risk final decisions")
    if constraints.get("retry_instead_of_escalation_limit") not in {0, 1}:
        raise GuardrailsError("routing may not repeat cheap attempts instead of escalating")
    return escalation


def _load_profiles(routing_root: Path, tasks: Mapping[str, Mapping[str, Any]]) -> dict[str, dict[str, Any]]:
    profiles: dict[str, dict[str, Any]] = {}
    expected_concurrency = {"economy": 1, "balanced": 2, "quality": 3}
    task_names = set(tasks)
    for name in PROFILE_NAMES:
        profile = read_json(routing_root / "profiles" / f"{name}.json", default={})
        if not isinstance(profile, dict) or profile.get("schema_version") != 1 or profile.get("name") != name:
            raise GuardrailsError(f"routing profile is invalid: {name}")
        tiers = profile.get("task_tiers")
        if not isinstance(tiers, dict) or set(tiers) != task_names:
            raise GuardrailsError(f"routing profile must map every task class exactly once: {name}")
        if any(tier not in CAPABILITY_TIERS for tier in tiers.values()):
            raise GuardrailsError(f"routing profile has an unknown tier: {name}")
        for identifier, task in tasks.items():
            if task["risk"] == "high" and tiers[identifier] != "deep":
                raise GuardrailsError(f"high-risk task cannot route below deep in {name}: {identifier}")
        reasoning = profile.get("reasoning_by_tier")
        if not isinstance(reasoning, dict) or set(reasoning) != set(CAPABILITY_TIERS):
            raise GuardrailsError(f"routing profile must map reasoning for every tier: {name}")
        if any(level not in REASONING_LEVELS for level in reasoning.values()):
            raise GuardrailsError(f"routing profile has an unknown reasoning level: {name}")
        parallel = profile.get("parallelism")
        if not isinstance(parallel, dict) or parallel.get("maximum_read_only_agents") != expected_concurrency[name]:
            raise GuardrailsError(f"routing profile has invalid read-only concurrency: {name}")
        if parallel.get("maximum_writing_agents") != 1 or parallel.get("parallel_writing_agents") is not False:
            raise GuardrailsError(f"routing profile must limit writing agents to one: {name}")
        write = profile.get("write_capability_by_tier")
        if not isinstance(write, dict) or set(write) != set(CAPABILITY_TIERS) or write.get("economy") is not False:
            raise GuardrailsError(f"routing profile must keep economy read-only: {name}")
        thresholds = profile.get("escalation")
        if not isinstance(thresholds, dict):
            raise GuardrailsError(f"routing profile lacks escalation thresholds: {name}")
        for field in ("maximum_bounded_attempts", "file_scope_threshold", "subsystem_scope_threshold"):
            if not isinstance(thresholds.get(field), int) or thresholds[field] <= 0:
                raise GuardrailsError(f"routing profile has invalid {field}: {name}")
        if thresholds["maximum_bounded_attempts"] > 2:
            raise GuardrailsError(f"routing profile permits wasteful retries: {name}")
        if "main_model" in profile or "environment" in profile:
            raise GuardrailsError(f"routing profile must not change the main-session model: {name}")
        profiles[name] = profile
    return profiles


def _load_model_maps(routing_root: Path) -> dict[str, dict[str, Any]]:
    maps: dict[str, dict[str, Any]] = {}
    for product in PRODUCTS:
        model_map = read_json(routing_root / "model-maps" / f"{product}.json", default={})
        if not isinstance(model_map, dict) or model_map.get("schema_version") != 1 or model_map.get("product") != product:
            raise GuardrailsError(f"routing model map is invalid: {product}")
        tiers = model_map.get("tiers")
        if not isinstance(tiers, dict) or set(tiers) != set(CAPABILITY_TIERS):
            raise GuardrailsError(f"routing model map must define every tier: {product}")
        for tier, entry in tiers.items():
            model = entry.get("model") if isinstance(entry, dict) else None
            if model is not None and (not isinstance(model, str) or MODEL_ID_RE.fullmatch(model) is None):
                raise GuardrailsError(f"routing model mapping is invalid: {product}:{tier}")
            if not isinstance(entry, dict) or entry.get("availability") != "unverified":
                raise GuardrailsError(f"routing model availability must remain unverified: {product}:{tier}")
        if model_map.get("main_session_unchanged") is not True:
            raise GuardrailsError(f"routing model map must preserve the main-session model: {product}")
        if product == "claude" and model_map.get("global_subagent_model_environment_variable") is not False:
            raise GuardrailsError("Claude routing must not set a global subagent model environment variable")
        maps[product] = model_map
    return maps


def load_config(routing_root: Path = ROUTING_ROOT) -> dict[str, Any]:
    for source in routing_root.rglob("*"):
        if source.is_symlink():
            raise GuardrailsError(f"routing source must not be a symbolic link: {source}")
    task_data, tasks = _load_tasks(routing_root)
    escalation = _load_escalation(routing_root)
    profiles = _load_profiles(routing_root, tasks)
    model_maps = _load_model_maps(routing_root)
    agents: list[dict[str, Any]] = []
    for path in discover_agents(routing_root):
        fields, body = parse_agent(path)
        if fields["task-class"] not in tasks:
            raise GuardrailsError(f"routing agent references unknown task class: {fields['name']}")
        if fields["capability"] == "write":
            for name, profile in profiles.items():
                tier = profile["task_tiers"][fields["task-class"]]
                if profile["write_capability_by_tier"][tier] is not True:
                    raise GuardrailsError(f"writing agent routes to read-only tier in {name}: {fields['name']}")
        agents.append({"path": path, "fields": fields, "body": body})
    write_agents = [agent for agent in agents if agent["fields"]["capability"] == "write"]
    if len(write_agents) != 1 or write_agents[0]["fields"]["name"] != "workstation_implementer":
        raise GuardrailsError("routing must define exactly one writing agent")
    for name in ("workstation_explorer", "workstation_reviewer", "workstation_verifier"):
        agent = next(item for item in agents if item["fields"]["name"] == name)
        if agent["fields"]["capability"] != "read-only":
            raise GuardrailsError(f"routing agent must be read-only: {name}")
    metrics = read_json(routing_root / "metrics-schema.json", default={})
    if not isinstance(metrics, dict) or metrics.get("type") != "object" or metrics.get("additionalProperties") is not False:
        raise GuardrailsError("routing metrics schema is invalid")
    prohibited = {"prompt", "source_code", "command", "command_arguments", "secret", "tool_output"}
    if prohibited & set(metrics.get("properties", {})):
        raise GuardrailsError("routing metrics schema contains sensitive content fields")
    context_path = routing_root / "context-guidance.md"
    if not context_path.is_file() or not context_path.read_text(encoding="utf-8").strip():
        raise GuardrailsError("routing context guidance is missing or empty")
    return {
        "tasks": tasks,
        "task_data": task_data,
        "escalation": escalation,
        "profiles": profiles,
        "model_maps": model_maps,
        "agents": agents,
        "context_guidance": context_path.read_text(encoding="utf-8").strip(),
        "metrics": metrics,
    }


def normalise_model_overrides(
    overrides: Mapping[str, Mapping[str, str]] | None,
    *,
    selected_products: Sequence[str] = PRODUCTS,
) -> dict[str, dict[str, str]]:
    normalised: dict[str, dict[str, str]] = {}
    if overrides is None:
        return normalised
    for product, tiers in overrides.items():
        if product not in PRODUCTS or product not in selected_products or not isinstance(tiers, Mapping):
            raise GuardrailsError(f"model override selects unsupported product: {product}")
        for tier, model in tiers.items():
            if tier not in CAPABILITY_TIERS:
                raise GuardrailsError(f"model override selects unsupported tier: {product}:{tier}")
            if not isinstance(model, str) or len(model) > 200 or MODEL_ID_RE.fullmatch(model) is None:
                raise GuardrailsError(f"model override has an invalid model ID: {product}:{tier}")
            normalised.setdefault(product, {})[tier] = model
    return normalised


def resolved_models(
    product: str,
    config: Mapping[str, Any],
    overrides: Mapping[str, Mapping[str, str]] | None,
) -> dict[str, str]:
    selected = normalise_model_overrides(overrides, selected_products=(product,)).get(product, {})
    model_map = config["model_maps"][product]
    return {
        tier: selected.get(tier, model_map["tiers"][tier].get("model") or "inherit")
        for tier in CAPABILITY_TIERS
    }


def _native_name(product: str, canonical: str) -> str:
    return canonical if product == "codex" else canonical.replace("_", "-")


def _instructions(agent: Mapping[str, Any], config: Mapping[str, Any], profile: Mapping[str, Any]) -> str:
    fields = agent["fields"]
    parallel = profile["parallelism"]
    return one_newline(
        f"{agent['body']}\n\n{config['context_guidance']}\n\n"
        "## Profile controls\n\n"
        f"- Portable capability: {fields['capability']}.\n"
        f"- Maximum concurrent read-only agents: {parallel['maximum_read_only_agents']}; "
        "maximum writing agents: 1; never run writing agents in parallel.\n"
        "- Escalate on conflicting evidence, material ambiguity, more than two viable paths, security or public-contract risk, production or persistent data, inconsistent verification, exhausted bounded attempts, scope thresholds, or insufficient capability/context.\n"
        "- Resume a useful existing subagent rather than spawning a replacement, and stop agents that are no longer useful."
    )


def render_agents(
    product: str,
    profile_name: str = DEFAULT_ROUTING_PROFILE,
    *,
    model_overrides: Mapping[str, Mapping[str, str]] | None = None,
    routing_root: Path = ROUTING_ROOT,
) -> dict[str, bytes]:
    if product not in PRODUCTS:
        raise GuardrailsError(f"unknown product: {product}")
    if profile_name == "none":
        return {}
    config = load_config(routing_root)
    if profile_name not in config["profiles"]:
        raise GuardrailsError(f"unknown routing profile: {profile_name}")
    profile = config["profiles"][profile_name]
    models = resolved_models(product, config, model_overrides)
    rendered: dict[str, bytes] = {}
    for agent in config["agents"]:
        fields = agent["fields"]
        tier = profile["task_tiers"][fields["task-class"]]
        reasoning = profile["reasoning_by_tier"][tier]
        native = _native_name(product, fields["name"])
        description = (
            f"{fields['description']} Profile {profile_name}: tier {tier}, reasoning {reasoning}; "
            "main-session model unchanged."
        )
        instructions = _instructions(agent, config, profile)
        source = f"routing/agents/{fields['name']}.md, routing/profiles/{profile_name}.json"
        model_source = f"routing/model-maps/{product}.json"
        if product == "codex":
            lines = [
                "# GENERATED — DO NOT EDIT",
                f"# Canonical sources: {source}, {model_source}",
                f"name = {json.dumps(native)}",
                f"description = {json.dumps(description, ensure_ascii=False)}",
                f"model = {json.dumps(models[tier])}",
                f"model_reasoning_effort = {json.dumps(reasoning)}",
            ]
            if fields["capability"] == "read-only":
                lines.append('sandbox_mode = "read-only"')
            lines.append(f"developer_instructions = {json.dumps(instructions, ensure_ascii=False)}")
            text = one_newline("\n".join(lines))
            filename = f"{native}.toml"
        elif product == "claude":
            frontmatter = [
                "---",
                f"name: {native}",
                f"description: {json.dumps(description, ensure_ascii=False)}",
                f"model: {models[tier]}",
                f"effort: {reasoning}",
            ]
            if fields["capability"] == "read-only":
                frontmatter.extend(["permissionMode: plan", "disallowedTools: Write, Edit, NotebookEdit"])
            frontmatter.append("---")
            text = one_newline(
                "\n".join(frontmatter)
                + f"\n\n<!-- GENERATED — DO NOT EDIT\nCanonical sources: {source}, {model_source}\n-->\n\n"
                + instructions
            )
            filename = f"{native}.md"
        else:
            cursor_model = models[tier]
            if cursor_model != "inherit" and "[" not in cursor_model:
                cursor_model = f"{cursor_model}[effort={reasoning}]"
            text = one_newline(
                "---\n"
                f"name: {native}\n"
                f"description: {json.dumps(description, ensure_ascii=False)}\n"
                f"model: {cursor_model}\n"
                f"readonly: {'true' if fields['capability'] == 'read-only' else 'false'}\n"
                "---\n\n"
                f"<!-- GENERATED — DO NOT EDIT\nCanonical sources: {source}, {model_source}\n"
                "Cursor may fall back when the plan or organisation policy does not provide the selected model.\n-->\n\n"
                f"Portable reasoning level: {reasoning}. Preserve the parent setting when model inheritance prevents an explicit effort setting.\n\n"
                f"{instructions}"
            )
            filename = f"{native}.md"
        data = text.encode("utf-8")
        if len(data) > config["task_data"]["agent_output_limit_bytes"]:
            raise GuardrailsError(f"generated routing agent exceeds configured limit: {product}/{filename}")
        if not data.strip() or not data.endswith(b"\n") or data.endswith(b"\n\n"):
            raise GuardrailsError(f"generated routing agent has invalid terminal newline: {product}/{filename}")
        rendered[filename] = data
    return rendered


def frontmatter_fields(text: str, label: str) -> dict[str, str]:
    lines = text.splitlines()
    if not lines or lines[0] != "---":
        raise GuardrailsError(f"generated agent lacks frontmatter: {label}")
    try:
        end = lines.index("---", 1)
    except ValueError as exc:
        raise GuardrailsError(f"generated agent has unterminated frontmatter: {label}") from exc
    fields: dict[str, str] = {}
    for line in lines[1:end]:
        if ":" not in line:
            raise GuardrailsError(f"generated agent has invalid frontmatter: {label}")
        key, value = (part.strip() for part in line.split(":", 1))
        if not key or not value or key in fields:
            raise GuardrailsError(f"generated agent has invalid field: {label}")
        fields[key] = value.strip('"')
    return fields
