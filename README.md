# AI Engineering Guardrails

[![PyPI version](https://img.shields.io/pypi/v/ai-engineering-guardrails?cacheSeconds=300)](https://pypi.org/project/ai-engineering-guardrails/)
[![Python requirement](https://img.shields.io/badge/python-%3E%3D3.11-blue)](https://pypi.org/project/ai-engineering-guardrails/)
[![Tests](https://github.com/ZarrenSpryXplor/ai-engineering-guardrails/actions/workflows/tests.yml/badge.svg?branch=main)](https://github.com/ZarrenSpryXplor/ai-engineering-guardrails/actions/workflows/tests.yml)
[![License](https://img.shields.io/pypi/l/ai-engineering-guardrails?cacheSeconds=300)](https://github.com/ZarrenSpryXplor/ai-engineering-guardrails/blob/main/LICENSE)

AI Engineering Guardrails is a local, vendor-neutral toolkit for applying consistent guidance, skills and narrow checks across OpenAI Codex, Claude Code, Cursor, GitHub Copilot in VS Code and Visual Studio, and JetBrains AI Assistant/Copilot.

It renders one canonical policy for each supported product. It helps agents inspect first, preserve user work, avoid secrets and destructive operations, verify changes, and report outcomes.

## The short version

- One canonical policy, rendered for six product surfaces rather than copied six times.
- Narrow deterministic checks for high-confidence risks: destructive Git operations, publication, credential exposure, and dangerous infrastructure actions.
- Portable, on-demand skills and capability packs for application, delivery, and infrastructure work.
- A local installer that preserves unrelated configuration, creates backups, and uses an immutable runtime independent of the source clone.
- Optional offline assurance for policy evidence, bounded task contracts, imported test/report summaries, and local instruction or skill review.
- Optional routing and terminal UX—both off unless you explicitly enable them.

This is defence in depth, not a replacement for product approvals, sandboxing, operating-system permissions, branch protection, cloud IAM, Kubernetes RBAC, or a human release decision.

<p align="center">
  <img src="https://raw.githubusercontent.com/ZarrenSpryXplor/ai-engineering-guardrails/main/assets/ai_comic_screen_only_corrected.png" width="720" alt="A comic about an AI agent denying over-engineering before a stack of resource monitors catches fire.">
</p>

## Start here

Python 3.11+ is required. Install the published package with [pipx](https://pipx.pypa.io/) and preview before writing anything. Do not use `sudo`, Administrator, or an elevated shell.

```sh
pipx install ai-engineering-guardrails

ai-guardrails install --dry-run
ai-guardrails install
ai-guardrails status
```

For contributor work or a reviewed local checkout instead:

```sh
git clone https://github.com/ZarrenSpryXplor/ai-engineering-guardrails.git
cd ai-engineering-guardrails
pipx install .
```

The default install detects local supported products, uses no cloud login, and changes no main model, approval setting, sandbox, network setting, routing profile, or terminal decoration. If no product is detected, it makes no change and prints the explicit command to use.

For a direct Git install, pin a reviewed tag or full commit rather than a moving branch:

```sh
pipx install 'git+https://github.com/ZarrenSpryXplor/ai-engineering-guardrails.git@<reviewed-tag-or-full-commit>'
```

The package is published on [PyPI](https://pypi.org/project/ai-engineering-guardrails/) through Trusted Publishing. Maintainers should follow the [release guide](https://github.com/ZarrenSpryXplor/ai-engineering-guardrails/blob/main/docs/releasing.md) for protected approvals, version/tag checks, and provenance.

## Optional features

**Terminal visibility** is opt-in. Claude Code can use a managed local status line; Codex uses its native `/statusline` fields; Cursor CLI keeps its documented `/status-indicators` control.

```sh
ai-guardrails statusline preview --product all --profile standard
ai-guardrails statusline install --product all --profile standard --dry-run
ai-guardrails statusline install --product all --profile standard
ai-guardrails activity --since 24h
ai-guardrails receipt --compact
```

**Routing** is also opt-in. It installs static, bounded roles; it does not classify prompts, choose a model at runtime, or grant authority.

```sh
ai-guardrails routing show --profile balanced --product codex
ai-guardrails routing set balanced --product codex --dry-run
ai-guardrails routing set balanced --product codex
```

**Assurance tools** stay local and offline. They inspect metadata, repository state, supplied reports, and bounded component files. They do not run analyzers, execute downloaded instructions, or prove that a system has no defects.

```sh
ai-guardrails policy audit
ai-guardrails task init --repo . --dry-run
ai-guardrails component inspect ./reviewed-skill
ai-guardrails skills audit
ai-guardrails docs audit --path README.md
```

See [evidence and assurance](https://github.com/ZarrenSpryXplor/ai-engineering-guardrails/blob/main/docs/evidence-and-assurance.md) for task setup, report comparison, trust records, and the limits of each result.

## Find the right detail

The [operator documentation hub](https://github.com/ZarrenSpryXplor/ai-engineering-guardrails/blob/main/docs/README.md) is the durable entry point. It gives each audience one place to start instead of making this README do every job.

| If you need to… | Read… |
| --- | --- |
| Install, update, recover, inspect state, or use waivers | [Quick user guide](https://github.com/ZarrenSpryXplor/ai-engineering-guardrails/blob/main/docs/user-guide.md) and [operations](https://github.com/ZarrenSpryXplor/ai-engineering-guardrails/blob/main/docs/operations.md) |
| Understand product versions, paths, and limitations | [Compatibility](https://github.com/ZarrenSpryXplor/ai-engineering-guardrails/blob/main/docs/compatibility.md) |
| Enable terminal UX, activity, complexity, receipts, or demo mode | [Terminal UX](https://github.com/ZarrenSpryXplor/ai-engineering-guardrails/blob/main/docs/terminal-ux.md) |
| Audit policy evidence, use a task contract, or inspect an external skill/instruction | [Evidence and assurance](https://github.com/ZarrenSpryXplor/ai-engineering-guardrails/blob/main/docs/evidence-and-assurance.md) |
| Delegate bounded work safely | [Routing and cost](https://github.com/ZarrenSpryXplor/ai-engineering-guardrails/blob/main/docs/routing-and-cost.md) |
| Use or extend language and infrastructure support | [Capability packs](https://github.com/ZarrenSpryXplor/ai-engineering-guardrails/blob/main/docs/capability-packs.md) and [skills catalogue](https://github.com/ZarrenSpryXplor/ai-engineering-guardrails/blob/main/docs/skills.md) |
| Create or review software and cloud architecture diagrams | [Architecture diagramming](https://github.com/ZarrenSpryXplor/ai-engineering-guardrails/blob/main/docs/architecture-diagramming.md) and [skills catalogue](https://github.com/ZarrenSpryXplor/ai-engineering-guardrails/blob/main/docs/skills.md#delivery-operations-and-cross-stack-work) |
| Write or review substantive technical documentation | [Technical writing](https://github.com/ZarrenSpryXplor/ai-engineering-guardrails/blob/main/docs/technical-writing.md) and [skills catalogue](https://github.com/ZarrenSpryXplor/ai-engineering-guardrails/blob/main/docs/skills.md) |
| Change canonical policy or understand the design | [Policy authoring](https://github.com/ZarrenSpryXplor/ai-engineering-guardrails/blob/main/docs/policy-authoring.md) and [architecture](https://github.com/ZarrenSpryXplor/ai-engineering-guardrails/blob/main/docs/architecture.md) |
| Review threat boundaries and enterprise examples | [Threat model](https://github.com/ZarrenSpryXplor/ai-engineering-guardrails/blob/main/docs/threat-model.md), [enterprise output](https://github.com/ZarrenSpryXplor/ai-engineering-guardrails/blob/main/docs/enterprise.md), and [Spacelift](https://github.com/ZarrenSpryXplor/ai-engineering-guardrails/blob/main/docs/spacelift.md) |

## Contribute and report safely

- Read [CONTRIBUTING.md](https://github.com/ZarrenSpryXplor/ai-engineering-guardrails/blob/main/CONTRIBUTING.md) before changing canonical policy, generated output, or product integration.
- Report vulnerabilities privately using [SECURITY.md](https://github.com/ZarrenSpryXplor/ai-engineering-guardrails/blob/main/SECURITY.md); do not put exploit details or secrets in a public issue.
- See [CHANGELOG.md](https://github.com/ZarrenSpryXplor/ai-engineering-guardrails/blob/main/CHANGELOG.md) for release-facing changes and [CODE_OF_CONDUCT.md](https://github.com/ZarrenSpryXplor/ai-engineering-guardrails/blob/main/CODE_OF_CONDUCT.md) for community expectations.

The project is MIT licensed. It makes no claim to be a universal security boundary or to save a particular amount of money, time, or tokens.
