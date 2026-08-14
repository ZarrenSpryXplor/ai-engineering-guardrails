# Operator documentation

This is the documentation entry point for people who operate, extend, or review AI Engineering Guardrails. The root [README](../README.md) gives the first-run workflow. This directory contains the detailed procedures and design information.

## Documentation status

These documents describe the current `main` branch. If you use a released package, run `ai-guardrails --version` and read the documentation from the matching `v<version>` tag. Instructions on `main` can describe features that an older installation does not contain.

The [changelog](../CHANGELOG.md) is the release summary. Dated compatibility sections preserve the date of their source review. Change a verification date only after you review the linked authoritative sources.

## Choose your path

| Audience | Start here | Then use |
| --- | --- | --- |
| Engineer installing the guardrails | [Quick user guide](user-guide.md) | [Operations](operations.md), [compatibility](compatibility.md) |
| Engineer using installed guardrails day to day | [Quick user guide](user-guide.md#day-to-day-use) | [skills catalogue](skills.md), [capability packs](capability-packs.md) |
| Engineer writing or reviewing technical documentation | [Technical writing](technical-writing.md) | [skills catalogue](skills.md), [operations](operations.md#documentation-audit) |
| Engineer creating or reviewing architecture diagrams | [Architecture diagramming](architecture-diagramming.md) | [skills catalogue](skills.md#delivery-operations-and-cross-stack-work), [architecture](architecture.md) |
| Engineer enabling status, receipts, or demo mode | [Terminal UX](terminal-ux.md) | [compatibility](compatibility.md#terminal-ux-capability-verification-2026-08-09) |
| Engineer delegating bounded tasks | [Routing and cost](routing-and-cost.md) | [skills catalogue](skills.md) |
| Maintainer reviewing policy, task evidence, or a local component | [Evidence and assurance](evidence-and-assurance.md) | [policy authoring](policy-authoring.md), [operations](operations.md) |
| Contributor changing behaviour or generated output | [Policy authoring](policy-authoring.md) | [Architecture](architecture.md), [CONTRIBUTING.md](../CONTRIBUTING.md) |
| Release maintainer | [Releasing to PyPI](releasing.md) | [operations](operations.md#release-checklist), [changelog](../CHANGELOG.md), [security policy](../SECURITY.md) |
| Security or platform reviewer | [Threat model](threat-model.md) | [architecture](architecture.md), [compatibility](compatibility.md) |
| Enterprise or Spacelift reviewer | [Enterprise output](enterprise.md) | [Spacelift](spacelift.md) |

## Document map

- [Quick user guide](user-guide.md): install, product-specific manual steps, day-to-day commands, and removal.
- [Operations](operations.md): preflight, update, state, recovery, waivers, auditing, scanning, and risk evidence.
- [Compatibility](compatibility.md): dated vendor capability evidence, supported formats, version boundaries, and product limitations.
- [Terminal UX](terminal-ux.md): opt-in status-line profiles, activity, complexity signals, compact receipts, demo mode, privacy, and removal.
- [Routing and cost](routing-and-cost.md): profile selection, role use, escalation, native product boundaries, and measurement limits.
- [Capability packs](capability-packs.md) and [skills catalogue](skills.md): on-demand stack support, technical writing, architecture diagramming, and other portable workflows.
- [Architecture diagramming](architecture-diagramming.md): view selection, source ownership, repository conventions, validation levels, and maintained views.
- [Technical writing](technical-writing.md): ASD-STE100-informed guidance, applicability, provenance, and advisory documentation checks.
- [Architecture](architecture.md): canonical resources, build, installation, enforcement, and ownership boundaries.
- [Policy authoring](policy-authoring.md): how maintainers safely extend canonical policy, skills, packs, or command rules.
- [Evidence and assurance](evidence-and-assurance.md): policy evidence lifecycle, task contracts, imported report limits, component trust, skill audits, and guidance probes.
- [Threat model](threat-model.md): assumptions, non-goals, limitations, and operational mitigations.
- [Enterprise output](enterprise.md): reviewable Codex, Claude Code, Cursor, and Spacelift administrator examples that the installer never deploys.
- [Spacelift](spacelift.md): dated surface compatibility, read-only local enforcement, and Rego v1 policy examples.
- [Releasing to PyPI](releasing.md): Trusted Publishing setup, protected-environment approval, release-tag checks, and first-release procedure.

For reporting and contribution expectations, see the repository-level [security policy](../SECURITY.md), [contribution guide](../CONTRIBUTING.md), [code of conduct](../CODE_OF_CONDUCT.md), and [changelog](../CHANGELOG.md).

## Reading principles

Product documentation, local state, and a successful command are evidence of different things. A configured file is not proof that a product activated it; a detected model or tool is not proof of entitlement; and a clean scan is not proof that an arbitrary operation is safe. The guides label these limits rather than hiding them.
