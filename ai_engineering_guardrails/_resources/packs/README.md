# Capability packs

Capability packs keep stack-specific policy, skills, verification, routing hints, and deterministic controls out of the always-loaded global policy. Pack detection, when declared, is offline and marker-based. A detection result is evidence, not authority to install tools or contact infrastructure.

Every pack owns `pack.json`. Policy, verification, routing, command or structured-tool controls, detectors, portable skills, and local fixtures are included only when the capability needs them. The management CLI validates declared files and installs only explicitly selected pack assets.
