# Capability packs

Capability packs keep stack-specific policy, skills, verification, routing hints, and deterministic controls out of the always-loaded global policy. Pack detection is offline and marker-based. A detection result is evidence, not authority to install tools or contact infrastructure.

Every pack owns `pack.json`, `policy.md`, `verification.json`, `command-policy.json`, `routing.json`, portable skills, and local fixtures. The management CLI validates these files and installs only explicitly selected pack assets.
