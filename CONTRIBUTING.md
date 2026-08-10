# Contributing

Thanks for helping make agent-assisted engineering a little less exciting in the bad way.

## Before opening a change

- Read the [operator documentation](docs/README.md), [architecture](docs/architecture.md), [threat model](docs/threat-model.md), and repository `AGENTS.md`.
- Discuss a material behaviour, policy, product-format, or release-process change in an issue before investing in a large patch.
- Report vulnerabilities through [SECURITY.md](SECURITY.md), not a public issue.
- Keep changes focused. Do not combine a policy change with unrelated refactoring, dependency upgrades, or generated-file edits.

## Development rules

- Use Python 3.11+ and the standard library for domain logic. Rich is the sole approved direct runtime dependency and stays confined to human CLI presentation; do not add another direct runtime dependency without an explicit, reviewed need.
- Treat `ai_engineering_guardrails/_resources/` as canonical. Do not hand-edit `dist/` or `adapters/`; run the build instead.
- Use temporary homes for installer tests. Never test against a real `~/.codex`, `~/.claude`, `~/.cursor`, or `~/.ai-guardrails` directory.
- Do not add credential values, prompts, source excerpts from private repositories, command arguments, raw audit events, or vendor session data to tests, fixtures, logs, or documentation.
- Preserve user configuration and model/product boundaries. A status file or managed path is not proof of product activation.

## Verify a change

Run the narrow tests that cover your change, then the project checks from the repository root:

```sh
python tools/guardrails.py build
python tools/guardrails.py validate
python tools/guardrails.py docs audit --repo .
python -m unittest discover -s tests -v
python tools/guardrails.py build
git diff --check
git diff -- adapters dist
```

The documentation audit is advisory. The second build should leave generated output unchanged. Run package and temporary-home checks when changing package resources, installation, state, product adapters, or runtime behaviour. State the observed commands, skipped optional validators, compatibility limits, and any documentation change in the pull request.

The full contributor suite expects OPA 1.19.0 on `PATH`. Hosted CI installs the pinned binary; local contributors can use the [official OPA installation guidance](https://www.openpolicyagent.org/docs/latest/#running-opa). End-user CLI validation still reports a structural-only skip when OPA is unavailable.

## Review expectations

Changes to policy, enforcement, installation ownership, audit/redaction, product adapters, supply-chain controls, or CI need focused tests and independent review. Include positive and nearby-safe negative examples for a deterministic rule; do not weaken a legitimate test merely to allow a desired command.

The [policy authoring guide](docs/policy-authoring.md) gives the canonical-resource workflow. The [operations guide](docs/operations.md) explains the user-facing lifecycle that a change must preserve.
