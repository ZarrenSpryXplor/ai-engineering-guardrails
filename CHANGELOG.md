# Changelog

All notable user-facing changes are recorded here. This project follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) principles and uses [Semantic Versioning](https://semver.org/spec/v2.0.0.html) for tagged releases.

## Unreleased

### Added

- A specialist `workstation-architecture-diagramming` skill provides standards-informed software and cloud diagram guidance with Mermaid and diagrams.net source, without claiming formal conformance or bundling vendor assets.


## [1.3.1] - 2026-08-10

### Fixed

- Corrected the package version after the v1.3.0 tag retained version `1.2.2`.
- Finalised the 1.3.0 changelog section while preserving an empty `Unreleased` section.

## [1.3.0] - 2026-08-10

### Added

- A specialist `workstation-technical-writing` skill provides ASD-STE100-informed guidance without redistributing the standard or claiming formal compliance.
- `docs audit` adds offline advisory checks for very long procedural sentences and explicit filler prefaces.

### Changed

- Rich presentation now covers all human-facing CLI help, errors, reports, and operation logs with an 80-column ceiling and folded exact values. Machine formats and pasteable setup payloads remain plain.
- Hosted test and release validation now use pinned OPA 1.19.0 semantic Rego execution instead of accepting a structural-only skip.

### Fixed

- Help output no longer emits terminal colour that `--no-color` and `NO_COLOR` cannot suppress on Python 3.14, where `argparse` colours help itself and propagates that choice to every subcommand parser.
- Mixed `diff-installed` reports retain selected products with no managed paths, and synthetic demos use ASCII-safe separators on legacy terminals.

## [1.2.2] - 2026-08-09

### Added

- Rich-backed, terminal-aware tables make validation, installation status, and skill audits easier to scan without changing their underlying decisions.
- `validate` and `status` now support deterministic `--format json` output for scripts, matching the existing machine-output convention used by other reporting commands.

### Changed

- Rich 15 is now the sole direct runtime dependency and is isolated to human CLI presentation; machine formats continue to emit plain structured data without styling.

## [1.2.1] - 2026-08-09

### Fixed

- Spacelift's Rego v1 checks now test each policy type in its own lane with the shared fixture data, so semantic validation no longer trips over unrelated policy entrypoints.

## [1.2.0] - 2026-08-09

### Added

- Optional terminal UX: Claude Code status line, Codex native status-line configuration, Cursor native guidance, local activity summaries, complexity signals, compact receipts, and synthetic demo mode.
- Documentation hub, security-reporting policy, contribution guide, code of conduct, and repository ownership map.
- Offline policy-evidence lifecycle metadata and audit, evidence-bound task contracts and safe-halt receipts, local SARIF/Cobertura/JUnit comparison, static component inspection with digest-bound local trust, portable skill-efficiency audit, and optional manual guidance probes.

### Changed

- README now focuses on the first-run journey and routes operational and maintainer detail to the documentation hub.
- Codex status-line guidance explains that `[tui]` is TOML configuration, not a `/statusline` picker item.
- Fresh installs preserve deterministic enforcement from all stable packs while exposing only core and contextual language/shared skills by default; `--skill-catalogue` changes managed exposure without weakening that policy. Skill audit now reports bounded catalogue counts, front-loading, overlap, tiers, description size, and clearly labelled pressure estimates.
- Task assurance records explicit contract continuity and adds compact assurance results to the existing schema-v2 receipt envelope.

### Fixed

- Spacelift URL inference accepts only the documented hostname and subdomains.
- Terminal UX uses an ASCII fallback for legacy Windows console encodings.
- Release-blocking assurance gaps now fail safely for unsupported repository/nested-repository state, generated changes, uncertain dependency manifests, malformed or insufficient JUnit/Cobertura/SARIF evidence, and weakened task contracts.
- Supported guardrails CLI entry points share deterministic self-modification coverage; component/authority inspection uses bounded local negation and bounded skill reads.

## Release history

Tagged release history and published artifacts are available through the repository's [GitHub Releases](https://github.com/ZarrenSpryXplor/ai-engineering-guardrails/releases) and [PyPI project page](https://pypi.org/project/ai-engineering-guardrails/). Release sections here describe changes supported by the tagged repository history; they do not invent notes for older releases that were not recorded at the time.
