---
name: workstation-kubernetes
description: Inspect Kubernetes source, classify kubectl operations, render or diff changes, and collect read-only evidence with explicit target handling. Use for manifests and bounded cluster diagnosis; do not use for direct production mutation, namespace or CRD deletion, broad deletion, secret extraction, or tests against a real cluster.
---

# Kubernetes workflow

1. Establish whether the task is source-only or remote, classify it as observe, validate, mutate, destructive, or sensitive-read, and identify context plus namespace from explicit evidence.
2. Treat an unmapped target as protected. Prefer repository manifests and declarative changes over edit or long-lived imperative state.
3. For source changes, render and validate locally, then inspect a diff. For observation, request only fields required for diagnosis and redact sensitive output.
4. Do not perform a remote mutation unless the active external safety policy permits the mapped lifecycle. Never make a production decision from naming heuristics.
5. Report target evidence, lifecycle classification, operation class, commands, results, and uncertainty.

Complete only when the source or read-only investigation is verified without exposing Secrets or contacting a cluster in tests.
