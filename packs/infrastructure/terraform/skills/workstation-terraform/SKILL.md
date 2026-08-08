---
name: workstation-terraform
description: Inspect, format, validate, and plan Terraform source while protecting state, plans, locks, targets, and remote execution boundaries. Use for local source and plan analysis; do not use for destroy, apply, state removal or push, auto-approval, unverified force-unlock, or exposing state and plan content.
---

# Terraform workflow

1. Identify the root module, version constraints, lockfile, backend, workspace convention, orchestration platform, and sensitive artifacts without reading credential values.
2. Make the smallest source change and preserve provider/version strategy.
3. Run format check and validate, then a suitably scoped plan only when backend access and target classification are safe. Prefer offline/local validation where remote access is unnecessary.
4. Summarise plan counts and relevant diagnostics without transmitting sensitive values or saving untracked plan/state artifacts.
5. Report root, workspace evidence, commands, outcomes, and remote steps not performed.

Complete after source validation and reviewed plan evidence, with no apply, destroy, unsafe state operation, or committed sensitive artifact.
