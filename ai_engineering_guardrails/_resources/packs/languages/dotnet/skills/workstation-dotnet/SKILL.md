---
name: workstation-dotnet
description: Inspect, change, and verify .NET/dotnet, C#, and F# projects with solutions, global.json, central package management, analyzers, and safe builds. Never publish packages, change global tools/workloads, or apply database migrations.
---

# .NET repository workflow

1. Identify the solution/build root, affected project, pinned SDK, shared build properties, central package file, and local tools.
2. Establish target frameworks, nullable/language settings, analyzers, warnings, and existing test/format commands.
3. Make the smallest change at the repository's established configuration level.
4. Restore/build/test the affected project first, then the relevant solution. Keep migration creation separate from execution.
5. Report the SDK evidence, project scope, commands, results, lock/package changes, and unverified items.

Complete only when targeted verification succeeds and no global tooling, package source, workload, publication, or database state was changed.
