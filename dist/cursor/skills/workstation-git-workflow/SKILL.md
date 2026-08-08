---
name: workstation-git-workflow
description: Carry out an explicitly requested Git workflow while preserving user work. Use for staging, commits, branches, or history inspection; do not use without requested Git mutation.
---

<!-- GENERATED — DO NOT EDIT
Canonical source: skills/workstation-git-workflow/SKILL.md
-->

# Workstation Git workflow

## When to use

Use this skill when the user explicitly requests a Git operation or when read-only history investigation is central to the task. Do not invoke it to create commits, amend history, merge, rebase, tag, or push without explicit authority.

## Procedure

1. Inspect status, branch, remotes when relevant, and the precise diff or history in scope.
2. Separate pre-existing changes from task changes and identify shared-history or upstream consequences.
3. Select the least destructive Git operation. Avoid broad pathspecs and stage only reviewed files.
4. Before any remote or history-changing action, verify the exact branch, remote, commit range, and user authority.
5. After the operation, inspect status and the resulting diff or history.

## Verification and completion

Complete when the requested Git state is observed and unrelated work remains intact. Report the exact operation, affected refs or paths, resulting status, and any action deliberately not taken.
