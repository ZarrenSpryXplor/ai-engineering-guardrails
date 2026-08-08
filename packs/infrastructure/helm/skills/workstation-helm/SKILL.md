---
name: workstation-helm
description: Inspect, lint, render, diff, and verify Helm charts while preserving values precedence, hooks, CRDs, and version compatibility. Use for chart source and read-only release analysis; do not use for uninstall, unreviewed plugins, insecure repository access, secret-bearing command flags, or automatic deployment.
---

# Helm workflow

1. Identify chart root, dependencies, Helm constraints, values layers, hooks, and CRDs.
2. Make source changes only; never edit rendered output or encode secrets in command arguments.
3. Run existing dependency checks, `helm lint`, and `helm template`; inspect the rendered delta with existing tooling.
4. Keep remote release operations separate and subject to lifecycle/safety controls. Do not install missing tools automatically.
5. Report Helm version evidence, values order, render/lint outcomes, and deployment work not performed.

Complete after local render and lint evidence is reviewed and no release, repository, registry, or plugin mutation occurred.
