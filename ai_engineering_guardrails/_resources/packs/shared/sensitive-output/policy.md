# Sensitive output capability policy

- Treat credentials, environment files, kubeconfigs, Secret data, cloud identity material, registry configuration, Terraform/OpenTofu state and plans, Spacelift tokens/logs/outputs, and generated credentials as sensitive.
- Request the minimum fields required, summarise deterministically, redact values, and preserve diagnostically relevant failure information plus exit status.
- Never log complete structured-tool arguments, command arguments, prompts, source, or secrets. Report suspected exposure without reproducing the value.
