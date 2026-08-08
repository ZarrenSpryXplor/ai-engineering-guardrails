# Kubernetes capability policy

- Treat get/describe/logs/events/top/explain/API discovery/auth checks/version/current-context/rollout status/history as observe; diff, kustomize, and supported dry-runs as validate; and all persistent changes plus exec/cp/port-forward as mutate or sensitive remote access.
- In strict mode, mutations require explicit context and namespace. Unknown targets are protected; only explicitly mapped dev/tst/int targets can qualify for non-production mutation. Direct prd mutation is denied.
- Deny namespace or CRD deletion, broad/all/all-namespace/forced/zero-grace deletion, replace `--force`, apply `--prune`, validation bypass, dynamic every-resource deletion, raw kubeconfig, and Secret value extraction.
- Prefer declarative source changes. Do not treat targeted non-production pod deletion as destructive solely because it is deletion, and never contact a real cluster from tests.
