---
name: workstation-sensitive-output
description: Collect, minimise, redact, and summarise potentially sensitive logs, plans, state, configuration, or remote-tool output while preserving diagnostic meaning. Use when evidence may contain secrets or operational data; do not use to retrieve raw credentials, Secret values, tokens, private keys, or unnecessary full outputs.
---

# Sensitive evidence workflow

1. Define the diagnostic question and minimum source/fields needed. Identify sensitive field classes before reading.
2. Prefer metadata, counts, identifiers, exit status, and bounded error context over complete output.
3. Redact credential-like values and avoid copying command or tool arguments. Keep enough non-sensitive context to explain failure behavior.
4. Summarise deterministically with source identifiers, relevant timestamps, counts, and uncertainty.
5. Report suspected exposure without reproducing it and recommend credential-owner response when needed.

Complete when the question is answered with no sensitive value retained in output, state, telemetry, or repository files.
