---
name: workstation-terraform
description: Inspect, format, validate, and plan Terraform source while protecting state, plans, locks, targets, and remote execution. Never destroy/apply, remove or push state, auto-approve, force-unlock without evidence, or expose state/plan content.
---

# Terraform workflow

1. Identify the root module, version constraints, lockfile, backend, workspace convention, orchestration platform, and sensitive artifacts without reading credential values.
2. Make the smallest source change and preserve provider/version strategy.
3. Run format check and validate, then a suitably scoped plan only when backend access and target classification are safe. Prefer offline/local validation where remote access is unnecessary.
4. Summarise plan counts and relevant diagnostics without transmitting sensitive values or saving untracked plan/state artifacts.
5. Report root, workspace evidence, commands, outcomes, and remote steps not performed.

Complete after source validation and reviewed plan evidence, with no apply, destroy, unsafe state operation, or committed sensitive artifact.
