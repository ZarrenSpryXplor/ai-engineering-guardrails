# Spacelift platform-policy examples

These Rego v1 examples are organisation-level starting points. They are never installed or attached by the workstation CLI. Adapt `fixtures/guardrails.json` to the organisation's spaces, labels, reviewer teams, metadata keys, protected resource types, branches, and change thresholds before evaluating the policies in Spacelift's policy workbench.

The examples follow the current Spacelift contracts: Approval policies expose `approve`/`reject`; Plan policies expose `deny`/`warn` sets; Push policies expose `track`/`propose`/`ignore`; Trigger policies expose a `trigger` set of stack IDs; Notification policies emit an `inbox` set; Login policies expose `allow`/`admin`/`deny`. Approval is not run confirmation, and a proposed run cannot apply infrastructure while a tracked run can.

The configuration fixture owns every organisation-specific label, space, team, subject, resource type, region, account, branch, event, threshold, downstream stack, and notification state. Replace all unmistakably synthetic examples before use. Use Spaces/RBAC as the primary access boundary and stack dependencies instead of Trigger Policies when the simpler dependency model is sufficient.

Run `python tools/guardrails.py validate` from the repository root. When OPA is installed, repository validation tests each policy type independently with the shared fixture data; otherwise it clearly reports that semantic Rego execution was skipped. Build, validation, and tests never call Spacelift or attach policy.

Official references:

- https://docs.spacelift.io/concepts/policy
- https://docs.spacelift.io/concepts/policy/approval-policy
- https://docs.spacelift.io/concepts/policy/terraform-plan-policy
- https://docs.spacelift.io/concepts/policy/push-policy
- https://docs.spacelift.io/concepts/policy/trigger-policy
- https://docs.spacelift.io/concepts/policy/notification-policy
- https://docs.spacelift.io/concepts/policy/login-policy
