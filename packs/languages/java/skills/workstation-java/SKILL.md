---
name: workstation-java
description: Inspect, change, and verify Maven or Gradle Java projects while preserving wrappers, modules, toolchains, dependency semantics, and publication boundaries. Use for bounded Java implementation, debugging, dependency, or build work; do not use it to publish artifacts, upgrade wrappers incidentally, or clear machine-global caches.
---

# Java repository workflow

1. Locate the affected build root and module. Record whether Maven, Gradle, or both are present and which wrapper applies.
2. Read the relevant manifest, parent/settings files, toolchain and compiler configuration, dependency scopes/configurations, and repository scripts.
3. Make the smallest source or build change without changing build systems or generated output.
4. Run the affected module's existing compile/test/check target through its wrapper. Broaden only after the targeted result is understood.
5. Compare relevant manifests and lockfiles before and after. Report wrapper used, module scope, commands, results, and checks not run.

Complete only when the change is source-backed, targeted verification passed, broader applicable checks were run or explicitly deferred, and no deploy/publication task ran.
