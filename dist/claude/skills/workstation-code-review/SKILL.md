---
name: workstation-code-review
description: Review code changes for evidence-backed defects and regressions. Use only for review, not when implementation is the primary request.
---

<!-- GENERATED — DO NOT EDIT
Canonical source: skills/workstation-code-review/SKILL.md
-->

# Workstation code review

## When to use

Use this skill for a diff, pull request, commit range, or bounded repository review. Do not invoke it as a substitute for implementing a requested change.

## Procedure

1. Establish the review boundary and read repository instructions. For a diff, pull request, or commit range, start with the changed files and lines; search for affected callers, tests, and interfaces, then read only the focused ranges needed as evidence. Do not explore the repository broadly merely to get oriented. If a targeted search is empty, retry once with simpler terms and treat the absence as evidence rather than guessing neighbouring paths.
2. Trace changed behavior through callers, state transitions, persistence, interfaces, and failure paths.
3. Prioritise correctness, regressions, security, concurrency, failure behaviour, operability, missing tests, compatibility, and material maintainability.
4. For maintainability, flag an unjustified dependency or language, duplicate source of truth, abstraction without three concrete consumers, speculative configurability, unused layer, or scope beyond the accepted task. Do not report a subjective style preference as a defect.
5. Validate each candidate finding against concrete lines and a plausible triggering scenario.
6. Run focused read-only checks when they materially strengthen or disprove a finding.

## Output and completion

Report findings before any general summary, ordered by severity. Each finding must identify the location, impact, trigger, and a concise remediation direction. If there are no findings, say so and identify residual testing or scope limitations. Complete when every reported issue is evidence-backed and the reviewed boundary is explicit.
