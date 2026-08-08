# Kustomize capability policy

- Treat `kustomize build` and `kubectl kustomize` as validation and inspect rendered changes without editing rendered output.
- Preserve base/overlay/component boundaries, resource identity, transformers, generators, patches, and repository tool versions.
- Treat `kubectl apply -k` as mutation and deny `kubectl delete -k`. Never render Secrets into logs.
