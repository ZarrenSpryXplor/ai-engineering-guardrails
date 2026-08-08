---
name: workstation-dependency-management
description: Plan, implement, and verify bounded dependency changes while preserving the repository's manager, wrapper, lockfiles, module boundaries, and integrity controls. Use when a dependency change is necessary; do not use for unrelated upgrades, manager migration, global tooling changes, cache destruction, publication, or integrity bypass.
---

# Dependency change workflow

1. Establish the existing manager, pinned version, wrapper, manifests, locks, modules/workspaces, repositories, and update scripts.
2. Justify the dependency and exact version/range change, including runtime, maintenance, licence, and supply-chain effects.
3. Change the narrowest authoritative manifest and regenerate only the required lock scope with the repository tool.
4. Review manifest and lock diffs for unrelated movement; run affected compile/test/security checks before broader checks.
5. Report rationale, changed resolution, commands, results, and any registry/network limitation without exposing credentials.

Complete only with a bounded reviewed lock diff and observed verification.
