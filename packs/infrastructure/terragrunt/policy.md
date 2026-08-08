# Terragrunt capability policy

- Determine the underlying Terraform/OpenTofu engine, units, includes, dependencies, and run scope before choosing commands.
- Treat local formatting/validation and bounded plan as validation; treat apply/import/state/workspace operations as mutation. Deny run-all apply/destroy and all destroy operations.
- `run-all plan` can touch many remote backends and is classified mutate for access control even though it does not persist infrastructure changes. Protect downloaded cache, plans, state, and outputs.
