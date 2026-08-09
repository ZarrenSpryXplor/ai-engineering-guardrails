---
name: workstation-python
description: Inspect, change, test, lint, type-check, and package Python projects with their existing environment and lock tooling. Never alter system Python, publish packages, bypass TLS, migrate lock managers, or apply database migrations.
---

# Python repository workflow

1. Identify the project root, Python constraint, package/environment manager, lockfile, virtual environment convention, and repository scripts.
2. Read the relevant pytest, tox/nox, formatter, linter, and type-check configuration.
3. Make a bounded source or manifest change. Preserve the manager and generated migration history.
4. Run the smallest test node or configured session, then applicable lint/type/format checks and broader tests.
5. Review dependency and lock diffs. Report environment, commands, outcomes, and skipped checks without exposing registry credentials.

Complete only after observed verification and with no system install, publication, global suppression, or unrequested lock migration.
