---
name: workstation-ansible
description: Inspect, change, and verify Ansible playbooks, roles, collections, inventories, and configuration while preserving repository conventions and remote safety. Use for Ansible source and bounded offline validation; do not use to expose Vault or inventory secrets, publish Galaxy content, or run against unknown or production targets.
---

# Ansible workflow

## When to use

Use for bounded changes to Ansible playbooks, roles, collections, inventory structure, and repository configuration. Use it for evidence-based review and local syntax or lint validation.

Do not use it to reveal Vault content or inventory variables, publish or remove Galaxy content, bypass transport validation, or execute playbooks and ad hoc commands against unknown or `prd` targets. Remote incident investigation should remain read-only.

## Procedure

1. Locate the effective `ansible.cfg`, execution environment, collection and role requirements, inventories, playbooks, roles, and existing lint or Molecule configuration. Record the evidence rather than assuming a default inventory or Ansible version.
2. Trace the affected play through imports, roles, variables, handlers, tags, delegation, `run_once`, `serial`, strategy, privilege escalation, and module fully qualified collection names. Treat dynamic inventory, plugins, lookup modules, `shell`/`command`, and lifecycle scripts as executable inputs.
3. Check secret boundaries before reading output. Preserve Vault encryption, `no_log`, protected variable files, and credential indirection. Do not request Vault passwords, decrypt content, or print inventory variables and diffs that may contain secrets.
4. Make the smallest source change. Preserve inventory layout, variable precedence, collection pins, idempotence, check-mode behavior, handlers, tags, and the repository's chosen execution environment.
5. Run the narrowest repository-provided validation first. Prefer `ansible-playbook --syntax-check` for the affected playbook; use `ansible-lint` or Molecule only when already configured and available. Do not install tools or collections globally.
6. Treat playbook, ad hoc, pull, and console commands—including `--check`—as remote execution, not proof of safety: tasks can opt out of check mode. Use them only with an inventory mapped to `dev`, `tst`, or `int` and an explicit bounded limit, after reviewing check-mode exceptions. Minimise or omit `--diff` when protected values could appear.
7. Report the effective configuration, inventory and limit evidence, changed behavior, commands and observed outcomes, and every remote or semantic check not performed.

## Verification and completion

Complete only when the affected source has passed the applicable local syntax, lint, and isolated tests; idempotence and secret handling have been reviewed; no publication or unapproved remote mutation occurred; and limitations are explicit.
