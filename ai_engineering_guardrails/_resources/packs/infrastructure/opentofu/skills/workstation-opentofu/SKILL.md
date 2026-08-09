---
name: workstation-opentofu
description: Inspect, format, validate, and plan OpenTofu source while protecting state, plans, locks, and targets. Preserve the selected engine; never substitute Terraform, destroy/apply, mutate state, auto-approve, or expose sensitive output.
---

# OpenTofu workflow

1. Confirm OpenTofu from explicit repository evidence and locate root, version, backend, locks, and workspace convention.
2. Change authoritative source only and preserve provider constraints.
3. Run the repository-compatible OpenTofu format/validate checks, then a scoped plan only when target access is safe.
4. Summarise rather than reproduce sensitive plan/state values.
5. Report engine evidence, root, commands, results, and unperformed remote work.

Complete without applying, destroying, mutating state, or replacing OpenTofu with Terraform.
