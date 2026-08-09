---
name: workstation-infrastructure-review
description: Review infrastructure source/operations across Kubernetes, Helm, Kustomize, Terraform/OpenTofu/Terragrunt, Azure, containers, databases, and Spacelift for target, blast radius, secrets, rollback, and platform controls. Never mutate remote systems or reveal sensitive output.
---

# Workstation infrastructure review

Use this skill for a read-only review of infrastructure source, plans, rendered manifests, or a proposed command/tool call. Do not invoke it as authority to deploy, publish, approve, confirm, destroy, or mutate a remote target.

## Workflow

1. Identify the authoritative source, repository toolchain, applicable capability packs, and whether the request is source-only or remote.
2. Classify the operation as `observe`, `validate`, `mutate`, `destructive`, `sensitive-read`, `publish`, or `privilege-escalation`.
3. Establish target evidence independently from naming: actual context, namespace, subscription, account, stack, workspace, release, or database, plus its explicit `dev`, `tst`, `int`, or `prd` mapping. Treat unknown targets as protected.
4. Inspect rendered or planned effects, ownership, dependencies, permissions, secrets exposure, state handling, failure behaviour, rollback, and platform RBAC/approval controls.
5. Prefer local validation, declarative source changes, and platform-proposed plans. Do not turn missing evidence into permission.
6. Report findings first, ordered by impact, with precise source references. Separate blocked actions, assumptions, unknowns, and verification gaps.

## Completion criteria

Complete only when the operation class, target/lifecycle evidence, material blast radius, sensitive-output risk, required human/platform controls, and verification status are explicit. No real remote operation may be run as part of this skill.
