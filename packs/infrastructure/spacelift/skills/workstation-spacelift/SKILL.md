---
name: workstation-spacelift
description: Collect and summarise read-only Spacelift evidence through spacectl, GraphQL queries, or read-scoped MCP tools while protecting tokens, logs, outputs, and run state. Use for stack/run/resource investigation and schema lookup; do not use for deploy, confirmation, tasks, cancellation, token export, GraphQL mutation, MCP writes, local preview, or profile changes.
---

# Spacelift read-only workflow

1. Define the question, required stack/run identifiers, and minimum read surface. Never inspect credential values.
2. Prefer `whoami`, version, listing/detail/log/change/resource/audit reads, schema discovery, GraphQL query, or current MCP `discover`/`query`/`provider` tools.
3. Treat log, output, state, and plan fields as sensitive; request only required fields and redact summaries.
4. Do not trigger, confirm, approve, discard, cancel, deploy, run tasks, export tokens, mutate profiles, invoke GraphQL mutation, or call either write-scoped MCP tool, `mutate` or `intent`.
5. Return concise conclusions, evidence identifiers, timeline when relevant, uncertainty, and recommended human-controlled follow-up.

Complete when the evidence question is answered or bounded as unresolved without changing Spacelift or exposing sensitive content.
