---
name: workstation-observability
description: Collect and summarise observability metrics, logs, traces, dashboards, and alerts for read-only incident diagnosis. Never mute alerts, change dashboards or retention, delete logs, create tokens, or mutate production.
---

# Observability workflow

1. State the hypothesis, system, time window, identifiers, data source, and smallest query needed to test it.
2. Query read-only metadata or bounded results. Preserve timestamps and provenance while removing credentials, personal data, and irrelevant sensitive fields.
3. Summarise deterministically before sharing output: counts, time bounds, representative error classes, and evidence references rather than raw unbounded logs.
4. Build a timeline, separate symptoms from causes, record conflicting evidence and uncertainty, and stop after two failed bounded diagnoses for escalation.
5. Report evidence, query scope, redactions, limitations, and proposed remediation without applying operational changes.

Complete when the evidence supports a bounded conclusion or an explicit uncertainty statement, with no alert, dashboard, retention, token, log, or production mutation.
