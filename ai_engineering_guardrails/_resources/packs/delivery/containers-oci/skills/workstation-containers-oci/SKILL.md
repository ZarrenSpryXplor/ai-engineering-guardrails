---
name: workstation-containers-oci
description: Review and change Dockerfile, Containerfile, Compose, and OCI workflows with bounded local builds and host-access checks. Use for container build definitions and image metadata; do not use to publish images, expose registry credentials, launch privileged containers, or prune unrelated state.
---

# Containers and OCI workflow

1. Identify the repository's container tool, build file, ignore file, Compose configuration, image provenance, and intended local context.
2. Inspect lifecycle commands, mounts, capabilities, namespaces, devices, user selection, secrets, and network assumptions before running a local build.
3. Prefer a reviewed local context and immutable or approved base images. Use existing SBOM or vulnerability tooling only when already available.
4. Validate configuration and build the smallest affected target. Do not log registry or build secrets.
5. Report the image source, context, commands, results, skipped validators, and any host-access or publication risk.

Complete when local configuration and the affected build are verified without publication, credential exposure, broad cleanup, or privileged execution.
