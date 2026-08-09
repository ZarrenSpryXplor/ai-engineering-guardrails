---
name: workstation-node
description: Inspect, change, and verify Node.js, JavaScript, and TypeScript workspaces with the repository's npm, pnpm, or Yarn version and scripts. Never publish packages, install globally, execute unpinned remotes, force audit fixes, or update snapshots blindly.
---

# Node repository workflow

1. Resolve the workspace root and package manager from `packageManager`, repository configuration, and lockfiles; record ambiguity rather than mixing tools.
2. Read affected workspace scripts, lifecycle hooks, TypeScript/ESLint/test configuration, and workspace dependency boundaries.
3. Make the smallest source or manifest change and preserve the existing lock format and manager major.
4. Run the affected workspace's narrow script first, then applicable type, lint, build, and broader test commands.
5. Review manifest, lockfile, and snapshot diffs. Report commands and observed outcomes.

Complete only when verification is observed and no global install, remote unpinned execution, publication, forced audit rewrite, or unrelated workspace upgrade occurred.
