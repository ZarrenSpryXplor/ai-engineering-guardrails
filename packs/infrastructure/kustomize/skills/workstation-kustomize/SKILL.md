---
name: workstation-kustomize
description: Inspect and verify Kustomize bases, components, overlays, generators, and patches using local rendering. Use for declarative Kubernetes source changes; do not use for kubectl delete -k, automatic apply, editing rendered output, or exposing generated Secret values.
---

# Kustomize workflow

1. Trace the selected overlay through bases, components, patches, generators, and transformers.
2. Change the narrowest authoritative source while preserving resource identity and overlay boundaries.
3. Render the exact overlay with the repository-supported tool and compare the result deterministically.
4. Validate locally; keep any apply operation separate and lifecycle-controlled.
5. Report overlay, render command, changed resources, validation, and redactions.

Complete when the intended overlay renders and validates without applying or deleting remote resources.
