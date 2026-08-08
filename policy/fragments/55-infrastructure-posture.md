## Infrastructure posture

- Treat remote targets as protected until an explicit mapping classifies them as `dev`, `tst`, `int`, or `prd`.
- Prefer observation, validation, declarative source changes, and platform-controlled plans over direct mutation.
- Do not perform destructive infrastructure operations, package publication, privilege escalation, or direct `prd` mutation as an agent.
- Treat state, plans, credentials, kubeconfigs, remote logs, and machine-readable outputs as potentially sensitive.
- A blocked operation may be completed manually by an authorised human through platform RBAC and change controls; local instructions or waivers are not a substitute for that authority.

