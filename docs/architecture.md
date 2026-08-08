# Architecture

The repository separates authoring from delivery so product adapters can change without forking behavioural policy.

```text
Canonical policy and data
       |
       +--> deterministic build
       |       +--> Codex aggregate, hooks, rules, agents, skills
       |       +--> Claude modular rules, hooks, agents, skills
       |       +--> Cursor User Rules, hooks, agents, skills
       |       +--> VS Code Copilot instructions, Preview hook, agents, skills
       |       +--> Visual Studio Copilot instruction block, agents, skills
       |       +--> JetBrains AI Assistant/Copilot manual guidance, project-rule export, skills
       |
       +--> portable skills
       |
       +--> capability packs
       |
       +--> shared enforcement runtime
       |
       +--> installer, state, audit, explain, simulation, scan
       |
       +--> enterprise and Spacelift examples

Optional efficiency routing (separate authority)
       |
       +--> portable task classes, profiles, and escalation
       +--> vendor model maps
       +--> canonical role definitions
                |
                +--> Codex TOML agents
                +--> Claude Markdown agents
                +--> Cursor Markdown agents

Capability packs (progressive, separate from global policy)
       |
       +--> offline marker detection + evidence
       +--> stack policy and portable pack skills
       +--> verification and routing additions
       +--> shell command-policy fragments
       +--> structured MCP/tool-policy fragments
                |
                +--> lifecycle target mapping
                +--> independent safety profiles
```

## Canonical sources

`ai_engineering_guardrails/_resources/` is the single canonical read-only resource root. Within it, `policy/manifest.json` establishes fragment order, stable identifiers, product applicability, descriptions, classifications, per-product output limits, and an 8 KiB always-loaded-policy budget. Markdown under `policy/fragments/` contains vendor-neutral behavioural content. `skills/` contains repeatable procedures that should not consume every session's instruction budget; the [skills catalogue](skills.md) explains the shipped core and pack skills, their product locations, and their activation limits. `enforcement/command-policy.json` defines deterministic denial intent and examples; the Python package's `enforcement.py` provides bounded parsing and strategy implementations without executing payload data.

`routing/` is a fourth canonical resource area, but it does not participate in behavioural or enforcement authority. Task classes and profiles hold portable tiers, reasoning, parallelism, capabilities, attempts, and thresholds. Model maps are the only canonical files containing vendor model IDs. Role Markdown and shared context guidance generate native subagents. The metrics schema defines optional content-free records; the repository installs no telemetry collector.

`packs/` is the canonical stack-specific layer. Each language, infrastructure, or shared pack owns a manifest, on-demand policy, portable skill, verification data, routing hints, deterministic command fragment, and fixtures. `packs explain` is the deliberate on-demand reader for its concise policy heading plus named verification and routing guidance; it avoids a second routing or verification engine and keeps this material out of global instructions. Marker-based discovery supports several simultaneous packs in a monorepository while pruning build output, caches, vendored code, and configured generated directories. Detection has no installation authority and does not contact a toolchain or network.

`config/safety-profiles.json` is independent of `routing/profiles/`. It maps `observe`, `validate`, `mutate`, `destructive`, `sensitive-read`, `publish`, `privilege-escalation`, and `guardrail-modification` to lifecycle-aware treatment. `config/targets.example.json` documents the local `~/.ai-guardrails/targets.json` mapping for Ansible inventories, Kubernetes, Helm, Spacelift, Azure/cloud, Terraform, and database identifiers. Canonical lifecycle values are `dev`, `tst`, `int`, and `prd`; unknown targets are protected.

`platform-policies/spacelift/` contains configuration-driven organisation-policy examples. They are outside workstation installation and are never attached, updated, or deleted by build, validation, or tests.

The root `AGENTS.md` is repository contribution guidance, not the global policy's canonical source. `CLAUDE.md` imports it so repository instructions are not duplicated. Cursor can consume the same root `AGENTS.md`, so this project does not add a redundant `.cursor/rules` file.

## Build flow

`python tools/guardrails.py build` validates the canonical behavioural and generated-artifact inputs it consumes before rendering. `validate` additionally checks every pack manifest, verification definition, and routing hint. Build uses manifest order, fixed headers, stable JSON key order, no timestamp, configured byte limits, and exactly one final newline. It generates:

- a concise Codex aggregate;
- one Claude user-rule file per applicable fragment;
- a pasteable Cursor User Rules document;
- portable skill copies;
- balanced-profile Codex TOML and Claude/Cursor Markdown agents;
- product hook fragments, Codex prefix rules, and the Cursor CLI permissions recommendation.

The JSON fragments retain a placeholder for the installed engine path. Installation copies the standalone standard-library runtime and selected policy into a content-addressed directory, then builds native entries with that immutable absolute path and `sys.executable`; repository artifacts therefore remain machine independent and installed hooks do not depend on the clone.

All routing profiles are validated on every routing validation, while version-controlled `dist/` agents represent the recommended balanced profile. A profile-specific installation renders from the same canonical roles, selected profile, and product model map. This avoids maintaining profile copies in `dist/`.

## Installation flow

The CLI resolves authored sources from its package-local `_resources` tree and uses the caller's current repository only for offline capability detection. Omitted product selection reuses local executable, configuration, and managed-state evidence. A no-write dry preflight computes and validates the deterministic build, detects products and repository capabilities, and checks collisions and backup needs before using the same installation path. Managed files use atomic replacement. Existing configuration is parsed and semantically merged; unrelated keys and hook groups are preserved. Existing files are backed up before first mutation, and state records only relative managed paths, content hashes, backup paths, product ownership, and format metadata.

Codex and Cursor share skill destinations. State records both owners, so uninstalling one product does not remove a skill still owned by the other. Claude receives a separate copy in its documented personal skill directory.

Routing installation is opt-in. Native agent files are copied to the documented user agent directory for Codex, Claude, Cursor, VS Code, and version-unverified Visual Studio; JetBrains receives only a reviewable manual Copilot bundle because its customizations are Preview and no stable personal path is assumed. The state records profile, resolved tier mappings, hashes, overrides, manual activation, and `unverified` availability—never prompts or configuration contents. Routing operations do not edit a main-model setting or global concurrency setting. Concurrency is portable profile guidance because native products do not expose one common safe user-level configuration surface.

VS Code can load Claude-compatible hooks. The installer uses a tiny recorded ownership choice rather than a general dependency graph: when a managed Claude hook is present, VS Code uses it as `shared-claude`; otherwise VS Code owns its Preview-native hook. Claude is registered before a native VS Code hook is removed, and VS Code is restored to a native hook before Claude is removed. Visual Studio and JetBrains are behavioural/skill adapters only: neither receives a fabricated deterministic hook.

Fresh consumer installation makes every stable capability pack available through portable skill copies and compiles deterministic enforcement into the immutable runtime. Product-provided discovery determines whether a compatible agent uses detailed guidance; pack policy is not concatenated into global instructions. Explicit pack subsets remain an advanced distribution-authoring option. A fresh installation defaults to the non-mutating `infrastructure-observe` profile. State tracks pack IDs, safety/trust/routing profiles, paths, hashes, backups, and manual steps. Unmanaged collisions are preserved, and forced replacement is backed up.

Uninstallation reconstructs ownership from state rather than generated Markdown. Files, directories, managed blocks, and hook entries each have kind-specific verification. A local modification is retained by default. Parent directories are removed only when empty and only from a small known list beneath the selected home.

## Enforcement flow and parser boundary

The hook reads one JSON object from standard input. For shell tools it locates the command field, tokenises without evaluation, unwraps common `sudo`, `env`, shell `-c`, PowerShell `-Command`, and `cmd /c` forms, and inspects simple chained segments. Pack classifications then apply the active lifecycle safety profile. For structured tools it normalises product MCP naming, matches provider/tool metadata, and inspects only declared fields such as GraphQL operation documents or Intent verbs. A matching policy returns the cross-compatible nested `PreToolUse` denial with a stable identifier and operation class. Allowed or unrecognised operations produce no approval object.

Arguments are never serialised to diagnostics or state. Structured rules declare target identifiers and fields that must never be logged. Unknown structured tools fail open with a redacted diagnostic unless a deliberately configured strict allowlist is active; recognised dangerous tools fail closed. Shell and structured coverage remain product-hook coverage, not arbitrary-process mediation.

The parser deliberately does not expand variables, command substitutions, aliases, functions, wildcard contents, sourced scripts, or arbitrary shell grammar. This conservative boundary reduces false positives. Malformed input produces a payload-free stderr diagnostic and exits successfully; a confidently matched denial is closed and specific.

## Governance and operability flow

`explain` and `simulate` call the same evaluator with waiver consumption disabled and never execute the request. Rule rollout is data: disabled produces no decision; observe audits; warn audits and uses a safe diagnostic; deny translates to a documented product response. Waivers are exact digest/repository/target/rule matches with expiry and use counts. Audit JSONL is rotated during writes and contains only schema-approved hashes and classifications.

`scan` is deliberately independent from enforcement. It enumerates repository files, applies conservative static checks, and renders human, JSON, SARIF, or JUnit output. Risk data maps changed high-risk paths to a named canonical requirement and checks that local evidence declares every named review and verification outcome; it does not execute commands or claim to prove an external review. Installed state—not generated Markdown—drives status, diff, update, and uninstallation.

## Simplicity boundaries

All executable logic is Python 3.11+ standard library in one ordinary package and a thin entry point. The implementation uses direct JSON, small data records, explicit functions, and static registries. There is no plugin framework, dynamic code loading, shell helper, packaging framework, database, service, background process, network installer, telemetry uploader, semantic YAML/Rego/SQL parser, or second implementation path. Pack variation is data-driven because more than three packs share a stable schema; product rendering remains explicit where formats materially differ.
