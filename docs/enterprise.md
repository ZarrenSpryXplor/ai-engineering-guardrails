# Enterprise output

`dist/enterprise/` contains generated, reviewable examples only. The workstation installer does not deploy them, edit an enterprise control plane, or compete with higher-precedence managed configuration. Administrators must review formats against current product versions, distribute the immutable runtime separately, and test precedence before rollout.

## Codex

The generated `requirements.toml` demonstrates the Codex 0.138+ permission-profile allowlist, managed approval requirements, and managed hook placement. Older clients ignore managed permission-profile keys and require the separately documented legacy sandbox-mode form. Requirements do not distribute the Python runtime. Endpoint management must provide a stable absolute interpreter/runtime path for every supported OS. Codex experimental command rules remain defence in depth.

## Claude Code

The managed-settings example contains only the guardrail hook shape. Merge it with organisation permissions and existing hooks; never replace unrelated managed settings or weaken deny rules. Do not set a global subagent model variable that defeats role-specific routing.

## Cursor

Generated Team Rule text and hook guidance use documented administrative surfaces. The project intentionally does not fabricate a managed local settings file. Team Rules, User Rules, project rules, native hooks, subagents, and CLI permissions have different scopes; model availability remains plan/organisation dependent.

## Spacelift

Enterprise guidance points to Spaces/RBAC, Login, Approval, Plan, Push, Trigger, and Notification policy bundles. Rego v1 sources and tests remain in `platform-policies/spacelift/`; generated enterprise output includes review copies/pointers, never deployment logic. Organisation-specific configuration remains data.

## Higher-precedence management

Status and doctor report managed configuration when detectable but do not attempt to bypass it. Enterprise policy is authoritative when it has higher precedence. The project does not implement automatic distribution, signing, hosted analytics, compliance reporting, credential brokerage, or policy deployment.
