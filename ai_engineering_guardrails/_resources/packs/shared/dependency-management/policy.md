# Dependency management capability policy

- Inspect the repository's pinned toolchain, wrapper, manager, scripts, manifests, lockfiles, workspaces/modules, and verification before changing dependencies.
- Preserve the existing manager and lock format; avoid unrelated upgrades and full-lock rewrites for bounded changes unless the tool requires it and the reason is reported.
- Prefer existing dependencies and standard-library functionality. Consider maintenance, licence, supply-chain, runtime, signature, and TLS consequences.
- Never alter machine-global tooling or caches as a shortcut, disable integrity checks, or expose registry credentials.
