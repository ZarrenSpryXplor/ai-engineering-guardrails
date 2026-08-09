# Spacelift

The Spacelift controls cover three surfaces: `spacectl`, GraphQL supplied through supported API/CLI or MCP fields, and the current unified MCP endpoint. Workstation defaults are read-only; platform Spaces/RBAC and policies remain authoritative.

## Current compatibility assumptions

Verified on 2026-08-08 against current official documentation:

- the unified MCP endpoint is `/mcp`; the former `/intent/mcp` endpoint passed its documented 1 August 2026 removal date and is never generated;
- current MCP tools are `discover`, `query`, and `provider` for read-oriented access, plus write-scoped `mutate` and `intent`;
- GraphQL mutation definitions are write operations even when sent through a generic `query` or `spacectl api` surface;
- Access Policies are deprecated with a documented 30 May 2026 end-of-life date; the official page also retains an inconsistent “still functional” line, so this repository makes no runtime-availability claim and generates none. Spaces/RBAC plus Login Policies are the supported replacement;
- deprecated Task and Initialization policy patterns are not generated; current Approval Policies govern one-off task/run approval where applicable;
- new examples use Rego v1.

Official references: [spacectl](https://docs.spacelift.io/concepts/spacectl), [MCP](https://docs.spacelift.io/concepts/intelligence/spacelift-mcp), [policies](https://docs.spacelift.io/concepts/policy), [Approval](https://docs.spacelift.io/concepts/policy/approval-policy), [Plan](https://docs.spacelift.io/concepts/policy/terraform-plan-policy), [Push](https://docs.spacelift.io/concepts/policy/push-policy), [Trigger](https://docs.spacelift.io/concepts/policy/trigger-policy), [Login](https://docs.spacelift.io/concepts/policy/login-policy), [deprecated policies](https://docs.spacelift.io/concepts/policy/deprecated), and [audit trail](https://docs.spacelift.io/integrations/audit-trail).

## Local enforcement

Identity/version/list/read/log/change/resource/module/audit operations are read-oriented, but logs and outputs may still be sensitive. Deployment, confirmation, tasks, cancel/discard, profile selection/login/logout, token export, generic GraphQL mutations, and every invocation of the write-scoped MCP `mutate` and `intent` tools are denied or restricted. This includes `intent` requests whose argument names sound read-only because access is granted at the tool scope. Defensive aliases cover older action-style tool names such as `trigger_stack_run`, `confirm_stack_run`, `discard_stack_run`, and `local_preview`; those aliases are not presented as the current hosted contract.

`local_preview` is treated as remote mutation because it creates a proposed run and transfers workspace content. No future enablement is safe without checking untracked and ignored content, environment files, credentials, private keys, state, plans, and generated sensitive configuration. Run approval and run confirmation are not equivalent. Agents do not confirm tracked runs by default.

Never print or store API tokens, API-key secrets, exported session tokens, or profile credential contents. Prefer OAuth/read scopes when possible. A spacectl profile token can have broader authority than an OAuth read-scoped connection; the CLI never edits or tests real profiles.

## Rego v1 examples

`platform-policies/spacelift/` contains configuration-driven Approval, Plan, Push, Trigger, Notification, and Login examples. They cover prd human approval, self-approval prevention where inputs support identity, approver teams, change metadata, deletion/replacement, blast radius, critical types, IAM/public exposure, regions/accounts, proposed versus tracked runs, branch/event behavior, task/run governance, downstream triggers, and notification conditions.

Organisation identities, labels, spaces, branches, accounts, regions, types, and thresholds live in synthetic fixture data and must be replaced. Build and tests never attach or deploy policies. `python tools/guardrails.py validate` tests each policy type independently with the shared fixture data when an existing `opa` executable is available; otherwise structural validation reports semantic execution skipped. This repository does not implement a Rego interpreter.
