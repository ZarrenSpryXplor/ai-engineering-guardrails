# Policy authoring

Execution-efficiency task routing is not behavioural policy. Canonical authoring data is shipped under `ai_engineering_guardrails/_resources/`; this document omits that prefix below for readability. Author model tiers, profiles, escalation, and subagent roles under `routing/` as described in [routing and measurement](routing-and-cost.md); do not put vendor model IDs in policy fragments.

## Add and order a fragment

Create a concise vendor-neutral Markdown file under `policy/fragments/`, for example `policy/fragments/35-database-changes.md`. Add an entry at the intended position in `policy/manifest.json`:

```json
{
  "id": "database-changes",
  "path": "fragments/35-database-changes.md",
  "order": 35,
  "products": ["codex", "claude", "cursor"],
  "description": "Review and rollback expectations for database changes.",
  "classification": "behavioural_guidance",
  "load": "always",
  "enforcement_ids": ["destructive-database-client"],
  "risk_ids": ["persistent-data"]
}
```

Numeric `order` followed by identifier is output order. Identifiers and orders must be unique, paths must remain under `policy/`, selected products must be known, association IDs must resolve to canonical enforcement or risk data, and the generated aggregate must remain within its configured byte limit. Use `load: on-demand` when material belongs in a skill or pack rather than the always-loaded policy.

For a product-specific fragment, narrow `products`, for example:

```json
"products": ["cursor"]
```

Use product-specific content only when the requirement cannot be expressed portably. Prefer putting configuration details in the adapter or compatibility documentation instead.

## Add a portable skill

Create `skills/workstation-example/SKILL.md`:

```markdown
---
name: workstation-example
description: Perform a bounded example workflow. Use for example tasks; do not use for unrelated work.
---

# Workstation example

## When to use

State both triggers and exclusions.

## Procedure

1. Collect evidence.
2. Perform the bounded work.

## Verification and completion

Define observable success and reporting criteria.
```

The canonical format permits only the portable `name` and `description` fields. The name must match the directory and use lowercase letters, numbers, and hyphens. Reference supporting assets only with relative paths from the skill root.

## Add a deterministic command rule

Add a stable entry to `enforcement/command-policy.json`. Choose an existing conservative `matching_strategy` or implement and test a focused new strategy in `pre_tool_use.py`. Every entry must include description, risk category, user-facing reason, positive examples, and safe counterexamples:

```json
{
  "id": "example-destructive-command",
  "description": "Block one precisely identified operation.",
  "risk_category": "data_loss",
  "reason": "Blocked because the operation destroys reviewed data.",
  "matching_strategy": {"type": "example_strategy"},
  "must_match": ["example destroy --confirmed"],
  "must_not_match": ["example plan", "echo 'example destroy --confirmed'"]
}
```

Positive examples should cover supported wrappers and meaningful flag orderings. Negative examples must include normal nearby workflows plus print, search, and source-text cases when applicable. Do not compensate for parser uncertainty with an indiscriminate substring rule.

## Add a capability pack

Use a pack when guidance is specific to a language, build ecosystem, infrastructure tool, or cross-stack concern and should not be permanently resident in global instructions. Create `packs/<type>/<id>/` with:

- `pack.json` containing stable markers, exclusions, dependencies/conflicts, and references;
- concise `policy.md`;
- `verification.json`, `routing.json`, and `command-policy.json`;
- one or more portable `skills/workstation-*/SKILL.md` files;
- positive and negative local fixtures under `tests/fixtures/`.

Detectors should match authoritative manifests, wrappers, locks, and configuration, not ordinary source extensions alone. Add evidence-based monorepository fixtures and prove that build output, dependency caches, vendor trees, and configured generated paths are ignored. Never execute a detector or contact a network.

Add pack command rules with an `operation_class` and both dangerous and nearby-safe examples:

```json
{
  "id": "example-remote-destroy",
  "description": "Block one high-confidence destructive operation.",
  "risk_category": "remote_destruction",
  "operation_class": "destructive",
  "reason": "The operation requires a human-controlled platform workflow.",
  "matching_strategy": {
    "type": "command_regex",
    "executables": ["examplectl"],
    "pattern": "^destroy(?:\\s|$)"
  },
  "must_match": ["examplectl destroy"],
  "must_not_match": ["examplectl plan", "echo 'examplectl destroy'"]
}
```

Structured-tool rules additionally declare provider/tool patterns, target fields, fields that must never be logged, denial reason, and complete positive/negative payload fixtures. Inspect structured fields rather than serialising the whole argument object. A GraphQL rule should distinguish a real `mutation` definition from a `query` or documentation string.

Validate and explain detection before installation:

```sh
python tools/guardrails.py packs validate
python tools/guardrails.py packs explain --repo tests/fixtures/packs/polyglot
python tools/guardrails.py install --home "$temporary_home" --product all \
  --pack example --safety-profile infrastructure-observe --dry-run
```

Adding a pack must not change global policy generation. Product adapters consume only selected pack skills and enforcement fragments progressively.

## Rebuild and verify

```sh
python tools/guardrails.py build
python tools/guardrails.py validate
python -m unittest discover -s tests -v
python tools/guardrails.py build
git diff --check
git diff
```

The second build should report every file unchanged and produce no new diff.

Validate installation without touching the real home:

```sh
temporary_home="$(mktemp -d)"
python tools/guardrails.py install --home "$temporary_home" --product all --dry-run
python tools/guardrails.py install --home "$temporary_home" --product all
python tools/guardrails.py status --home "$temporary_home" --product all
python tools/guardrails.py uninstall --home "$temporary_home" --product all
```

Remove the temporary directory only after confirming it is the expected generated path.

## Local workstation overlay

End users do not edit package resources. A workstation-local overlay is deliberately small and survives package upgrades:

```sh
ai-guardrails policy init
ai-guardrails policy validate
ai-guardrails policy diff
ai-guardrails policy apply --dry-run
ai-guardrails policy apply
```

`~/.ai-guardrails/policy/overrides.json` has `behavioural_fragments`, `rule_modes`, and `additional_rules`. Local fragments are non-empty UTF-8 Markdown beneath `~/.ai-guardrails/policy/fragments/` and use `local-` identifiers. A local `rule_modes` entry may only keep or strengthen an existing rollout mode (`disabled < observe < warn < deny`). Additional shell rules use the existing command-rule schema, a supported matcher, and both dangerous and safe examples. Overlays cannot permanently weaken bundled policy; use a short, human-confirmed waiver for a bounded exception.
