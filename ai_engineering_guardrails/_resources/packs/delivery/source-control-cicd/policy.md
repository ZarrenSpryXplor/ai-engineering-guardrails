# Source control and CI/CD capability policy

- Prepare reviewable commits or pull-request content only when requested; do not approve your own work, merge automatically, weaken branch protection or rulesets, retrieve or mutate secrets, or escalate CI identities.
- Treat workflow permissions, environment protection, untrusted-fork triggers, `pull_request_target`, reusable workflow trust, third-party action pins, and release/deploy separation as high-risk review areas.
- Do not trigger production deployment, delete runs/environments/history, publish releases or packages, or grant broad workflow permissions. Keep build/package/release identities distinct.
- Use native dry-run, lint, or repository validation where available. Static YAML heuristics are not a semantic parser, so report unresolved trigger and expression behaviour.
