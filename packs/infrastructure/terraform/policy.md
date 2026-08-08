# Terraform capability policy

- Treat fmt/validate/providers/plan and local plan-file show as validate; treat apply/import/taint/untaint/force-unlock/workspace changes/state movement as mutate.
- Deny destroy, destroy-plan apply, auto-approved apply, state rm/push, and unverified broad force-unlock. Treat state, plans, machine-readable output, and crash logs as sensitive.
- Never commit state, saved plans, secret-bearing crash logs, or generated credentials. For Spacelift-managed stacks, prefer source changes, local validation, proposed runs, and plan inspection over local apply.
