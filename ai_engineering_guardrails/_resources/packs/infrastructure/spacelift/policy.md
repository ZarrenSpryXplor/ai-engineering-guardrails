# Spacelift capability policy

- Default all spacectl, GraphQL, and MCP access to read-only. Logs, outputs, resource data, and plan changes may be sensitive.
- Allow identity/version, stack/run/resource/module/audit reads and GraphQL schema/query operations. Deny deploy, confirmation, task execution, discard/cancel, token export, profile mutation, GraphQL mutations, every call to the write-scoped current MCP `mutate` and `intent` tools, and legacy mutating tool aliases.
- Treat local preview/proposed-run creation as remote mutation because it transfers workspace content. Before any future externally approved preview, inspect untracked/ignored environment files, credentials, keys, state, plans, and generated sensitive files.
- Never print/store Spacelift tokens or profile contents. Approval and confirmation are distinct; agents do not confirm tracked runs. Tests must never modify profiles or contact Spacelift.
