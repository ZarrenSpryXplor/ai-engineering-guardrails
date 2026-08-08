# OpenTofu capability policy

- Preserve the repository's choice of OpenTofu and its provider lock/version constraints. Do not silently substitute Terraform.
- Treat fmt/validate/providers/plan and local plan-file show as validate. Deny destroy, destroy-plan apply, auto-approved apply, state rm/push, and unverified force-unlock.
- Protect state, saved plans, JSON outputs, crash logs, and credentials. Prefer source/local validation and governed proposed runs over local apply.
