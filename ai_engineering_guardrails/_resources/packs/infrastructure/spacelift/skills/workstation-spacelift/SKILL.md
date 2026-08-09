---
name: workstation-spacelift
description: Collect read-only Spacelift stack, run, resource, and schema evidence through spacectl, GraphQL, or read-scoped MCP tools. Never deploy, confirm, run tasks, cancel, export tokens, mutate GraphQL/MCP state, preview locally, or change profiles.
---

# Spacelift read-only workflow

1. Define the question, required stack/run identifiers, and minimum read surface. Never inspect credential values.
2. Prefer `whoami`, version, listing/detail/log/change/resource/audit reads, schema discovery, GraphQL query, or current MCP `discover`/`query`/`provider` tools.
3. Treat log, output, state, and plan fields as sensitive; request only required fields and redact summaries.
4. Do not trigger, confirm, approve, discard, cancel, deploy, run tasks, export tokens, mutate profiles, invoke GraphQL mutation, or call either write-scoped MCP tool, `mutate` or `intent`.
5. Return concise conclusions, evidence identifiers, timeline when relevant, uncertainty, and recommended human-controlled follow-up.

Complete when the evidence question is answered or bounded as unresolved without changing Spacelift or exposing sensitive content.
