---
name: workstation-azure
description: Review Azure infrastructure source and collect bounded Azure metadata with explicit subscription and tenant evidence. Use for Bicep, Azure CLI planning, and read-only diagnosis; do not use for token or secret retrieval, role changes, destructive cloud operations, or direct production mutation.
---

# Azure workflow

1. Establish whether work is source-only or remote, then identify the subscription, tenant, target resource, and lifecycle from explicit mappings.
2. Treat unknown targets as protected. Separate metadata reads from sensitive reads, mutation, destruction, and privilege escalation.
3. Prefer source changes, local validation, and a what-if or platform plan over imperative mutation. Inspect output for secret-bearing deployment values before sharing it.
4. Do not retrieve access tokens, secret values, keys, service-principal credentials, kubeconfigs, or admin credentials.
5. Report target evidence, lifecycle, operation class, commands, observed results, redactions, and skipped native validation.

Complete only when the source or read-only investigation is verified without cloud mutation or credential exposure.
