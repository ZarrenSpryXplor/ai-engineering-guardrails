# Containers and OCI capability policy

- Inspect the Dockerfile or Containerfile, ignore rules, Compose configuration, base-image provenance, build context, and lifecycle scripts before building untrusted content.
- Permit local metadata inspection and reviewed local builds. Prefer immutable digests or organisation-approved images for sensitive use, and use existing vulnerability or SBOM tools when already installed.
- Deny privileged containers, Docker socket mounts, host root/network/PID/IPC, device access, credential-directory mounts, broad prune, registry publication, insecure registry/TLS bypass, unreviewed remote build contexts, and secrets passed through build arguments.
- Do not put registry credentials in command arguments or output, automatically install a scanner, or treat a local successful build as approval to push an image.
