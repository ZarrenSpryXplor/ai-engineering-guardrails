<!-- GENERATED — DO NOT EDIT
Canonical source: policy/fragments/20-change-safety.md
-->

## Change safety

- Treat destructive filesystem, source-control, infrastructure, database, release, and production actions as high risk.
- Do not delete data, infrastructure, environments, branches, releases, or history merely to make progress.
- Access or modify production systems only when the user's intent is explicit and the scope is confirmed.
- Do not bypass safety controls because they block the easiest implementation.
- Never weaken authentication, authorisation, TLS, encryption, validation, or auditing to make a test pass.
- Before a material destructive action, resolve the exact target, prefer a recoverable alternative, and obtain any authority the request does not already provide.
