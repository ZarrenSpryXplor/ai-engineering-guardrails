# Capability packs

Capability packs keep stack-specific material out of always-loaded global policy. One generic loader reads `pack.json`; there is no Python class or plugin module per pack.

## Supported packs

Language packs cover Java with Maven/Gradle, .NET, Python, and Node/JavaScript/TypeScript. Infrastructure packs cover Ansible, Kubernetes, Helm, Kustomize, Terraform, OpenTofu, Terragrunt, Spacelift, and Azure. Delivery/operations/shared packs cover containers/OCI, GitHub/Azure DevOps source control and CI/CD, databases and migrations, observability, API/schema compatibility, secrets/PKI, dependency management, package publication, and sensitive output.

This list is not universal protection for every adjacent CLI, cloud provider, controller, package plugin, database framework, or MCP server. Unknown tools must be assessed and added explicitly.

## Detection

```sh
python tools/guardrails.py packs list
python tools/guardrails.py packs detect --repo /path/to/repository
python tools/guardrails.py packs explain --repo /path/to/repository
python tools/guardrails.py packs validate
```

Detection uses manifests, wrappers, locks, configuration, and directories—not source extensions alone. It supports multiple roots in monorepositories and reports every evidence path. It prunes `.git`, dependency caches, build output, generated and vendored directories, makes no network call, runs no toolchain, and modifies nothing.

Optional `.ai-guardrails.json` can explicitly enable/disable packs, resolve package manager ambiguity, name a build root, add generated exclusions, and add credential-free target classifications. It is not required or automatically committed. Credentials and secret-shaped keys are rejected.

## Pack contents and installation

A pack uses only the files it needs: `pack.json`, concise `policy.md` or references, command/structured-tool policy, verification/routing data, a distinct portable skill, and synthetic fixtures. `pack.json` declares stable ID/type, description, detectors/exclusions, dependencies/conflicts, and referenced files.

Fresh default installation includes every current stable pack without asking the consumer to choose. Skills remain progressively discoverable; only selected task guidance is loaded by the product, enforcement compiles into the content-addressed runtime, and pack prose never becomes permanently resident global policy. Repository detection explains current relevance but does not limit future workstation guidance.

Explicit `--pack` and `--all-packs` options remain for advanced distribution authoring or deliberately reduced installations. Selected dependencies close deterministically. Collision and uninstallation rules are the same as base skills and agents.

## Toolchain preservation

Language packs inspect repository tooling first, prefer checked-in wrappers and pinned versions, preserve the dependency manager and lockfile, avoid unrelated upgrades, use project-local environments and binaries, retain compiler/linter/analyser settings, and run affected-module/workspace/project tests before broad suites. They deny publication and machine-global installation. Database migration generation is distinct from execution.

## Infrastructure treatment

Lifecycle values are exactly `dev`, `tst`, `int`, and `prd`; they are mappings, not names inferred from a context, subscription, namespace, stack, account, or workspace. Unknown targets are protected. Safety profiles control remote mutation independently from routing.

`observe` and `validate` are normally allowed. `mutate` is profile/lifecycle restricted. `destructive`, `sensitive-read`, `publish`, `privilege-escalation`, and `guardrail-modification` are denied by default. Production-capable credentials should not be exposed to coding agents because possession enables paths outside local hooks.

Kubernetes and Helm rules distinguish reads/rendering from mutation and high-confidence destructive/bypass/secret cases. Terraform-family rules allow format/validate/plan but deny destroy, dangerous state operations, auto-approved apply, and broad Terragrunt apply/destroy. Containers deny privileged host access, destructive prune, credential exposure, and push. Azure requires explicit mapped context for mutation and denies token/secret/key retrieval, privilege changes, destructive scopes, and protected targets.

Ansible detection uses distinctive configuration and metadata rather than generic YAML files. Local syntax checks are validation; playbook and ad hoc execution, including check mode, are remote mutation because tasks can opt out of check mode. Exact inventory paths can be lifecycle-mapped through `ansible_inventories`. Vault plaintext, broad inventory/configuration output, Galaxy publication/mutation, and transport or signature bypass receive deterministic protection.

## Adding a pack

Add a directory under the relevant category, declare markers and referenced files, use existing operation/matching strategies, add positive and nearby-safe counterexamples, and add offline fixtures. Abstract Python only if three concrete pack needs establish the same stable behavior. Run pack validation, explain detection, full build/validation/tests, and scan. See [policy authoring](policy-authoring.md) for schemas and examples.
