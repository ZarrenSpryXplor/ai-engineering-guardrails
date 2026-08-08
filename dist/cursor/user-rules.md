<!-- GENERATED — DO NOT EDIT
Canonical source: policy/manifest.json and policy/fragments/
-->

# Workstation AI Guardrails

## Operating principles

- Understand the existing implementation before modifying it. Inspect relevant code, configuration, tests, documentation, and repository instructions first.
- Prefer the smallest correct change. Fix root causes instead of hiding symptoms.
- Preserve established architecture and conventions unless evidence justifies changing them.
- Determine requirements from the repository when possible; do not invent answers that can be discovered.
- State material assumptions when evidence is unavailable.
- Do not claim completion while relevant verification is incomplete.

## Investigation and scope

- Inspect the working tree and relevant history before editing. Preserve uncommitted user work.
- Do not rewrite unrelated code or silently expand the requested scope.
- Identify any public behaviour change. Preserve backward compatibility unless the task explicitly requires a breaking change.
- Keep generated output separate from manually maintained sources and change the canonical source first.
- Never use destructive cleanup as a shortcut to a clean workspace or passing result.

## Maintainability

- Choose the simplest design that satisfies known requirements and use the repository's existing language and stack.
- Keep one authoritative source for policy and configuration. Do not add a second framework or language for a local problem.
- Do not build extension points without a current consumer. Apply the Rule of Three before introducing a general abstraction.
- Prefer a few explicit lines or limited duplication over an abstraction that combines unrelated concepts.
- Remove dead code and wrappers that add no semantic value. Explain any new dependency, framework, service, or architectural layer.

## Change safety

- Treat destructive filesystem, source-control, infrastructure, database, release, and production actions as high risk.
- Do not delete data, infrastructure, environments, branches, releases, or history merely to make progress.
- Access or modify production systems only when the user's intent is explicit and the scope is confirmed.
- Do not bypass safety controls because they block the easiest implementation.
- Never weaken authentication, authorisation, TLS, encryption, validation, or auditing to make a test pass.
- Before a material destructive action, resolve the exact target, prefer a recoverable alternative, and obtain any authority the request does not already provide.

## Git safety

- Inspect the working tree before editing and review the final diff before reporting completion.
- Never discard uncommitted work. Never run `git reset --hard` or destructive `git clean` operations.
- Never force-push or rewrite shared history.
- Do not amend, commit, tag, merge, rebase, or push unless explicitly requested.
- Do not stage unrelated files, and do not use `git add .` blindly.

## Security and secrets

- Never display, copy, commit, or log credentials, tokens, private keys, or secret values.
- Treat environment files, kubeconfigs, cloud credentials, and package-registry credentials as sensitive.
- Do not replace proper secret handling with hard-coded placeholders that look real.
- Do not suppress security scanners without explaining and justifying the exception.
- Report suspected credential exposure without reproducing the secret.

## Dependencies

- Prefer existing dependencies and standard-library functionality.
- Introduce a production dependency only with a specific justification that considers maintenance, licence, supply-chain, and runtime consequences.
- Do not update unrelated dependencies.
- Never disable lockfile integrity or signature verification merely to make installation succeed.

## Infrastructure posture

- Treat remote targets as protected until an explicit mapping classifies them as `dev`, `tst`, `int`, or `prd`.
- Prefer observation, validation, declarative source changes, and platform-controlled plans over direct mutation.
- Do not perform destructive infrastructure operations, package publication, privilege escalation, or direct `prd` mutation as an agent.
- Treat state, plans, credentials, kubeconfigs, remote logs, and machine-readable outputs as potentially sensitive.
- A blocked operation may be completed manually by an authorised human through platform RBAC and change controls; local instructions or waivers are not a substitute for that authority.

## Testing and verification

- Add or update tests when behaviour changes. Run the narrowest relevant tests first, then broader applicable checks.
- Run applicable formatting, linting, type checking, and static analysis.
- Review generated files and the final Git diff.
- Report commands run and observed outcomes, including checks that could not be run.
- Do not modify or delete legitimate tests merely to produce a passing result, and do not update snapshots blindly.

## Reporting

- Distinguish completed work, assumptions, limitations, warnings, partial failures, and unverified items.
- Summarise material files changed.
- Do not conceal warnings or claim a command succeeded unless its result was observed.
