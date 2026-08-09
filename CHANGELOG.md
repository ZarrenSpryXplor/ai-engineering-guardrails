# Changelog

All notable user-facing changes are recorded here. This project follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) principles and uses [Semantic Versioning](https://semver.org/spec/v2.0.0.html) once tagged releases begin.

## Unreleased

### Added

- Optional terminal UX: Claude Code status line, Codex native status-line configuration, Cursor native guidance, local activity summaries, complexity signals, compact receipts, and synthetic demo mode.
- Documentation hub, security-reporting policy, contribution guide, code of conduct, and repository ownership map.
- For v1.2.0: offline policy-evidence lifecycle metadata and audit, evidence-bound task contracts and safe-halt receipts, local SARIF/Cobertura/JUnit comparison, static component inspection with digest-bound local trust, and portable skill-efficiency audit.

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

Tagged release history and published artifacts are available through the repository's [GitHub Releases](https://github.com/ZarrenSpryXplor/ai-engineering-guardrails/releases) and [PyPI project page](https://pypi.org/project/ai-engineering-guardrails/). This changelog records unreleased work without retroactively inventing release notes.
