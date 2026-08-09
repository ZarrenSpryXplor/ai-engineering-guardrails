---
name: workstation-terragrunt
description: Inspect and validate Terragrunt units, stacks, includes, dependencies, and bounded plans while protecting remote state. Never run-all apply/destroy, perform broad unreviewed run-all operations, mutate state, or disclose sensitive output.
---

# Terragrunt workflow

1. Map the affected unit, include chain, dependency graph, engine, backend, and intended lifecycle.
2. Bound the run scope before changing source; avoid cache/generated files.
3. Run format/validate for the unit and a targeted plan when safe. Treat run-all plan as remote, broad access requiring explicit review.
4. Summarise dependency and plan results without copying sensitive output.
5. Report units, engine, target evidence, commands, outcomes, and excluded scope.

Complete after bounded validation with no run-all apply/destroy or state-changing action.
