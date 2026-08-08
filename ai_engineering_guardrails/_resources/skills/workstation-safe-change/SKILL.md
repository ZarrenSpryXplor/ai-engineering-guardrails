---
name: workstation-safe-change
description: Plan and implement a bounded repository change safely. Use for code or configuration changes; do not use for read-only explanation or incident response.
---

# Workstation safe change

## When to use

Use this skill when a request requires editing a repository while preserving existing work and behaviour. Do not invoke it for a read-only answer, a pure review, or active incident analysis.

## Procedure

1. Inspect repository instructions, status, relevant implementation, tests, and recent conventions.
2. Define the requested outcome, observable acceptance criteria, affected surfaces, and any evidence gaps.
3. Choose the smallest change that addresses the root cause. Identify compatibility and rollback implications before editing.
4. Preserve unrelated and uncommitted work. Change canonical sources before generated outputs.
5. Add or update focused tests, then run targeted checks followed by broader applicable checks.
6. Review the final diff for scope, accidental generated changes, secrets, and behavioural changes.

## Verification and completion

Complete only when the requested behaviour is demonstrated, relevant checks have observed results, and remaining uncertainty is reported. The handoff must list material changes, commands and outcomes, assumptions, and checks not run.
