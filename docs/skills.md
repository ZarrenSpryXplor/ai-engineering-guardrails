# Skills catalogue

Skills are short, on-demand procedures for a bounded work category. They are not a second global policy, a command runner, or a permission grant. They tell a compatible agent how to investigate, change, verify, and report work safely. Deterministic hooks and product-native approvals remain separate controls.

The distribution contains 30 portable skills: six core workstation skills and one skill for each of 24 capability packs. Canonical pack type supplies the default catalogue tier: the six base skills are **core**, language/shared pack skills are normally **contextual**, and infrastructure/delivery/operations skills are **specialist**. A cross-cutting pack can explicitly remain specialist when default exposure would waste catalogue budget. The canonical `SKILL.md` files under `ai_engineering_guardrails/_resources/` remain authoritative.

## How skills become available

Fresh default installation copies the six core and ten contextual skills while retaining deterministic enforcement from every stable pack. It keeps ordinary language and cross-stack development guidance discoverable without globally exposing all fourteen specialist skills. Use `ai-guardrails install --skill-catalogue all` to expose all selected pack skills, or `--skill-catalogue contextual` to return managed exposure to the smaller set without weakening pack enforcement. Repeatable `--pack ID` remains a deliberately reduced policy/skill installation. Existing installations keep their prior selections during update, and validation never edits Codex configuration or disables user-owned skills.

| Product or surface | Installed location | Important activation boundary |
| --- | --- | --- |
| Codex, Cursor, and GitHub Copilot in VS Code | `~/.agents/skills/` | Product discovery and skill selection are product-controlled. |
| Claude Code | `~/.claude/skills/` | This is a separate copy because Claude Code uses its documented personal-skill directory. |
| GitHub Copilot in Visual Studio | `~/.agents/skills/` | Agent Skills require Visual Studio 18.5+; installation on disk is not proof of activation. |
| JetBrains AI Assistant | `~/.agents/skills/` | Register the directory manually in **Settings > Tools > AI Assistant > Skills > Manage Skill Directories**. Current JetBrains documentation lists Codex and Claude Agent support, not Junie or Copilot. |

GitHub Copilot in JetBrains treats skills as a Preview customization surface. Registering this directory for the native JetBrains AI Assistant does not demonstrate that the Copilot plugin loaded it.

Where a product supports explicit skill invocation, ask for a skill by its exact `workstation-…` name, or select it through that product's interface. The precise discovery and invocation experience differs by product and version. `ai-guardrails` does not claim that copying a directory proves a particular session loaded a skill.

Skills are shared where products use the same directory. State tracks every managed owner, so uninstalling one product does not remove a skill still needed by another. An existing unmanaged directory with the same name is preserved unless an explicit `--force` replacement is requested and backed up.

## Core workstation skills

These six skills apply across stacks and are useful even when no capability pack is detected.

| Skill | Use it for | Do not use it for |
| --- | --- | --- |
| `workstation-safe-change` | A bounded implementation or configuration change. | Purely read-only explanation or incident investigation. |
| `workstation-code-review` | Evidence-backed review of a diff, pull request, or bounded change. | Implementing the requested change itself. |
| `workstation-git-workflow` | An explicitly requested Git workflow or history investigation. | Unauthorised commits, rebases, force-pushes, or other Git mutation. |
| `workstation-incident-analysis` | Read-only evidence collection, timeline building, and causal analysis. | Deploying or applying production remediation. |
| `workstation-infrastructure-review` | Review of infrastructure source or a proposed remote operation. | Executing remote mutations or revealing sensitive output. |
| `workstation-guardrail-maintenance` | Explicit maintenance of this guardrails platform or a selected local installation. | Bypassing controls or weakening tests for a desired command. |

## Capability-pack skills

Use `ai-guardrails packs detect --repo .` to see which packs have evidence in a repository, and `ai-guardrails packs explain --repo .` to see that evidence plus concise verification and routing hints. Detection is offline and advisory: it helps identify relevant skills, but does not execute tools, make network calls, or grant authority.

### Languages

| Skill | Focus |
| --- | --- |
| `workstation-java` | Maven or Gradle projects, wrappers, modules, toolchains, and targeted build verification. |
| `workstation-dotnet` | C#, F#, solutions, `global.json`, central packages, analyzers, and targeted project verification. |
| `workstation-python` | Existing Python environment/package manager, locks, tests, formatters, linters, and type checks. |
| `workstation-node` | npm, pnpm, or Yarn workspaces; JavaScript/TypeScript scripts, locks, and targeted workspace checks. |

### Infrastructure and platform

| Skill | Focus |
| --- | --- |
| `workstation-ansible` | Playbooks, roles, collections, inventories, and offline syntax/source validation. |
| `workstation-kubernetes` | Kubernetes manifests, safe `kubectl` classification, local render/diff, and read-only diagnosis. |
| `workstation-helm` | Chart source, linting, rendering, values precedence, hooks, CRDs, and release analysis. |
| `workstation-kustomize` | Bases, components, overlays, generators, patches, and local rendering. |
| `workstation-terraform` | Terraform source, format, validation, bounded plans, and state/plan protection. |
| `workstation-opentofu` | OpenTofu source and plans while preserving the chosen engine and protecting state. |
| `workstation-terragrunt` | Terragrunt units, includes, dependencies, and bounded validation/plan work. |
| `workstation-spacelift` | Read-only Spacelift CLI, GraphQL, and read-scoped MCP evidence. |
| `workstation-azure` | Azure source review, CLI planning, and bounded metadata with explicit subscription/tenant evidence. |

### Delivery, operations, and cross-stack work

| Skill | Focus |
| --- | --- |
| `workstation-containers-oci` | Dockerfile, Containerfile, Compose, OCI build definitions, and safe local image inspection. |
| `workstation-source-control-cicd` | GitHub Actions, Azure Pipelines, and source-control automation with trust-boundary review. |
| `workstation-observability` | Bounded read-only metrics, logs, traces, dashboards, and alert evidence. |
| `workstation-api-schema-compatibility` | OpenAPI, JSON Schema, Protobuf, GraphQL, AsyncAPI, Avro, and event-contract compatibility. |
| `workstation-database-migrations` | Migration-source authoring and isolated verification, separate from execution. |
| `workstation-dependency-management` | Bounded dependency changes while preserving manager, wrappers, lockfiles, and integrity controls. |
| `workstation-package-publication` | Local release-candidate preparation and verification without upload or publication. |
| `workstation-secrets-pki` | Secret/certificate metadata, expiry, issuer, fingerprint, rotation, and access-policy review without values. |
| `workstation-sensitive-output` | Minimising, redacting, and summarising sensitive logs, plans, state, and configuration evidence. |
| `workstation-architecture-diagramming` | Visual software and cloud architecture models with evidence-based C4-informed, UML-informed, ERD, Mermaid, and diagrams.net source. |
| `workstation-technical-writing` | Prose-only READMEs, runbooks, procedures, architecture documents, troubleshooting, and CLI/help text with ASD-STE100-informed clarity. |

## Skills, packs, rules, and routing are different things

| Thing | Purpose | What it does not do |
| --- | --- | --- |
| Global behavioural policy | Sets concise engineering expectations for every supported product. | Provide detailed procedure for every stack. |
| Skill | Gives an agent a repeatable, evidence-driven workflow for one task class. | Grant permission, execute commands by itself, or replace review. |
| Capability pack | Groups stack detectors, a skill, verification hints, and relevant deterministic rules. | Mean a detected repository is safe to mutate. |
| Deterministic rule | Matches a narrow, high-confidence command or structured-tool request. | Understand every shell construct or protect arbitrary user processes. |
| Routing role | Optional product-native custom-agent role for bounded delegation or explicit selection. | Replace a skill, alter the main model, or weaken safety controls. |

Routing remains off by default. Its five `workstation_` roles are deliberately different from skills: they describe who performs a bounded delegated task, while a skill describes how to perform a category of work. See [profile selection](routing-and-cost.md#choose-a-profile) for limits and [using roles in an engineering session](routing-and-cost.md#use-roles-in-an-engineering-session) for the role catalogue and prompt examples.

## Adding or changing a skill

For contributors, canonical skills live in the package resource tree. Do not edit generated copies under `dist/`. New skills need portable `name` and `description` frontmatter, an explicit use/not-use boundary, an evidence-driven procedure, and observable completion criteria. See [policy authoring](policy-authoring.md#add-a-portable-skill) for the minimal format and validation workflow.

## Inspecting skill efficiency and external skills

Run `ai-guardrails skills audit` for bundled skills, or `ai-guardrails skills audit --path PATH` for one local skill or directory. It bounds the component tree before reading content, then reports installed/bundled count, description characters, longest descriptions, front-loading quality, catalogue tiers, exact/near routing overlap, body/reference size, undeclared executables, and estimated tokens. The catalogue-pressure value is explicitly a description-only estimate: the actual Codex metadata budget varies with model context and other installed/plugin skills. The audit only suggests changes; it never rewrites a skill, edits product configuration, or disables user-owned content.

Codex initially discovers a skill from its name, description, and path before loading the selected `SKILL.md`, so descriptions put the task and trigger terms first. OpenAI documents that descriptions are shortened first under metadata pressure and that a sufficiently large catalogue can omit later entries from initial discovery; full content remains available after selection. See [OpenAI's skill documentation](https://developers.openai.com/codex/skills).

Before using an external skill or instruction bundle, run `ai-guardrails component inspect PATH`. The inspection covers the complete bounded tree and flags links, missing references, scripts, binary/oversized content, selected high-confidence risk patterns, and content digest facts without executing anything. A clean result is not a safety proof. Local `component trust` is an operator-created, digest-bound, expiring review record—not verified human identity, an installer, marketplace, permission grant, or signature verification system. See [evidence and assurance](evidence-and-assurance.md) for the trust boundary and external-content authority limits.

For users, use a local policy overlay to add workstation-specific behavioural guidance. It can strengthen deterministic rules but cannot permanently weaken bundled enforcement; use an expiring waiver for a narrow temporary exception. See [operations](operations.md#waivers-and-audit) for the safe lifecycle.
