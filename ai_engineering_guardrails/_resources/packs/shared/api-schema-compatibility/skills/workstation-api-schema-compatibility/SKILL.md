---
name: workstation-api-schema-compatibility
description: Review OpenAPI, JSON Schema, Protobuf, GraphQL, AsyncAPI, Avro, and event-contract changes against an explicit compatibility baseline. Use for contract evolution and generated-client review; do not use to claim semantic compatibility from text or JSON parsing alone.
---

# API and schema compatibility workflow

1. Locate the authoritative schema, consumer/version policy, compatibility direction, baseline, generated outputs, and repository-native validator.
2. Diff semantic contract elements: removal, requiredness/nullability, type or format, enum values, identifiers and field numbers, error behaviour, and event evolution.
3. Make the smallest authoritative-source change and regenerate through existing tooling only.
4. Run native lint/compiler and breaking-change checks when present, then review generated and consumer-facing diffs.
5. Lead with compatibility findings, including affected consumers, evidence, uncertainty, and semantic checks that could not run.

Complete only when the baseline and direction are explicit and supported checks pass; otherwise report compatibility as unverified.
