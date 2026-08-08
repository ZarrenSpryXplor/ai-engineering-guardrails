---
name: workstation-package-publication
description: Prepare and verify a package or release candidate without uploading, publishing, creating a hosted release, or exposing registry credentials. Use for local packaging and release-readiness evidence; do not use to execute any publication command even when asked to finish a release.
---

# Release-candidate preparation

1. Identify the repository's release metadata, versioning, packaging, changelog, signing, and verification conventions.
2. Prepare the smallest requested source and metadata changes without changing publication credentials or destinations.
3. Build/package locally and inspect archive contents, checksums, metadata, tests, and reproducibility where supported.
4. Stop before every upload, publish, deploy, hosted-release creation, or registry mutation. Provide the exact human-controlled next step only as documentation when useful.
5. Report artifacts, hashes, commands, outcomes, and the explicit fact that publication was not performed.

Complete when the release candidate is locally verified and no external publication occurred.
