---
name: workstation-azure
description: Review Azure Bicep/infrastructure source and collect bounded metadata with explicit subscription and tenant evidence. Never retrieve tokens or secrets, change roles, run destructive cloud operations, or mutate production.
---

# Azure workflow

1. Establish whether work is source-only or remote, then identify the subscription, tenant, target resource, and lifecycle from explicit mappings.
2. Treat unknown targets as protected. Separate metadata reads from sensitive reads, mutation, destruction, and privilege escalation.
3. Prefer source changes, local validation, and a what-if or platform plan over imperative mutation. Inspect output for secret-bearing deployment values before sharing it.
4. Do not retrieve access tokens, secret values, keys, service-principal credentials, kubeconfigs, or admin credentials.
5. Report target evidence, lifecycle, operation class, commands, observed results, redactions, and skipped native validation.

Complete only when the source or read-only investigation is verified without cloud mutation or credential exposure.
