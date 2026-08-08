---
name: workstation-source-control-cicd
description: Review and change GitHub Actions, Azure Pipelines, and source-control automation with trust-boundary and permission analysis. Use for workflow source and read-only run evidence; do not use to self-approve, merge, weaken protections, retrieve secrets, deploy production, or publish releases.
---

# Source control and CI/CD workflow

1. Identify the workflow engine, event trust boundary, identity, permissions, environments, third-party references, and build/package/release stages.
2. Inspect untrusted-fork and reusable-workflow data flow, especially `pull_request_target`, scripts, artifact consumption, expressions, and secret reachability.
3. Make the smallest source change while preserving independent approval, branch/environment protection, and least privilege.
4. Run repository-native lint or validation when available, then review the complete workflow diff. Treat text-only scanning as incomplete semantic validation.
5. Report findings first, followed by changed permissions, triggers, pins, commands, outcomes, and unverified platform behaviour.

Complete only when the source is reviewable and verified without merge, self-approval, secret access, deployment, or publication.
