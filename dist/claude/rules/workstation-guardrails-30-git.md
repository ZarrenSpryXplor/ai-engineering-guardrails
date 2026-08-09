<!-- GENERATED — DO NOT EDIT
Canonical source: policy/fragments/30-git.md
-->
<!-- Canonical policy ID: git -->

## Git safety

- Inspect the working tree before editing and review the final diff before reporting completion.
- Never discard uncommitted work. Never run `git reset --hard` or destructive `git clean` operations.
- Never force-push or rewrite shared history.
- Do not amend, commit, tag, merge, rebase, or push unless explicitly requested.
- Do not stage unrelated files, and do not use `git add .` blindly.
