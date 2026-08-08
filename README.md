# AI engineering workstation guardrails

This repository is a vendor-neutral source of behavioural guidance, reusable Agent Skills, deterministic shell and structured-tool controls, optional execution-efficiency routing, modular capability packs, local governance, and generated adapters for OpenAI Codex, Anthropic Claude Code, and Cursor. The v1 layer covers workstation installation, routing, polyglot development, Kubernetes/Helm/Terraform/Spacelift, explainability, waivers, audit receipts, trust, scanning, and risk verification. The v1.1 layer adds containers/OCI, Azure, source control and CI/CD, databases, observability, API/schema compatibility, secrets/PKI, and enterprise examples.

Markdown guidance influences agent decisions. The shared `PreToolUse` engine deterministically denies a deliberately narrow set of high-confidence destructive commands. Neither mechanism is a complete workstation security boundary; keep operating-system least privilege, sandboxes, branch protection, cloud IAM, and production change controls in place.

## Quick start

Python 3.11 or later is the only requirement. Do not run the installer with `sudo`, as Administrator, or from an elevated shell.

Preview the complete plan, then install for the supported products detected locally:

```sh
python tools/guardrails.py install --dry-run
python tools/guardrails.py install
python tools/guardrails.py status
```

No product, pack, profile, target mapping, or waiver selection is required. Detection uses local commands, existing product configuration, and managed state without contacting the network. If nothing supported is found, the installer makes no changes and prints an exact explicit-product command.

The default posture enables normal application development, all stable language and tool guidance as on-demand skills, infrastructure observation, and local render/lint/validate/plan work. It denies destructive Git operations, publication, credential exposure, remote infrastructure mutation, production operations, and mutation of unknown targets. It leaves the primary model, model routing, approval mode, sandbox, network access, permissions, credentials, and target mappings unchanged. Enterprise output is not installed, Spacelift policy is not deployed, and auditing is local and redacted.

The dry-run performs deterministic build computation, canonical validation, offline product and repository-capability detection, collision checks, backup planning, and installation planning without modifying files. Its default output lists product configuration, managed blocks, skills, agents, planned backups, unchanged settings, safety boundaries, and manual steps.

Update and removal use the products already recorded in installation state:

```sh
python tools/guardrails.py update
python tools/guardrails.py uninstall --dry-run
python tools/guardrails.py uninstall
```

If Cursor is detected, complete its one manual User Rules step after installation:

```sh
python tools/guardrails.py print-cursor-rules
```

Open **Cursor Settings / Customize / Rules / User Rules**, paste the complete output, and save it. This command prints authoritative text; it does not claim installation.

## Repository model

- `policy/manifest.json` orders and scopes the authoritative fragments in `policy/fragments/`.
- `skills/` contains portable, task-specific Agent Skills. Detailed procedures belong here rather than in always-loaded policy.
- `enforcement/command-policy.json` contains matching policy and test examples; `enforcement/pre_tool_use.py` is the non-executing parser and hook engine.
- `routing/` contains optional task classes, portable capability and reasoning tiers, profiles, escalation rules, vendor model maps, role definitions, and a content-free metrics schema.
- `packs/` contains on-demand language, infrastructure, and shared capability packs. Each pack owns detectors, stack policy, verification, command rules, routing additions, skills, and fixtures.
- `config/` defines lifecycle-aware safety profiles and a credential-free target-mapping example. `platform-policies/spacelift/` contains example organisation policies that are never installed.
- `trust/`, `risk/`, `supply-chain/`, `waivers/`, and `audit/` contain governance schemas and policy data. Local events are redacted and never contain prompts, source, full commands, arguments, or secret values.
- `enterprise/` is canonical source for generated enterprise examples. These artifacts are reviewable output, never automatic deployment.
- `adapters/` contains generated hook fragments, Codex defence-in-depth rules, and a Cursor CLI recommendation.
- `dist/` contains generated policy, skill, and native subagent artifacts. Never edit generated files directly.
- `tools/guardrails.py` builds, validates, installs, reports status, prints Cursor rules, and uninstalls managed content.

Behavioural guidance and deterministic controls are intentionally distinct. A fragment classified as `deterministic_enforcement_guidance` explains safe behaviour, while the command policy separately defines the precise operations the hook can deny.

The routing layer is distinct from both. It can make bounded delegation more economical and keep noisy work out of the main context, but it neither grants authority nor weakens safety rules. It does not promise lower latency or a specific monetary saving.

## Installation details

The real install runs the deterministic build and full local validation before touching user configuration. It creates an immutable, content-addressed runtime under `~/.ai-guardrails/runtime/`, validates it, registers hooks using the absolute current Python interpreter, writes state atomically, and verifies every managed path afterwards. Live hooks never point back to the clone. State contains only non-sensitive paths, hashes, profiles, packs, and manual steps; backups are stored under `~/.ai-guardrails/backups/` before pre-existing configuration is first mutated.

Codex receives a managed block in its effective global `AGENTS` file, a dedicated `.rules` file, a structurally merged user hook, and skills under `~/.agents/skills/`. `CODEX_HOME` is honoured when it resolves inside the selected `--home`; an external value is rejected so an alternate-home test cannot escape into real configuration. Review and trust the installed user hook with `/hooks` in Codex if prompted. The installer does not alter `config.toml`, approval mode, sandbox mode, or network access.

Claude Code receives modular files under `~/.claude/rules/`, a structurally merged `~/.claude/settings.json` hook, and skills under `~/.claude/skills/`. Existing keys, permission rules, and unrelated hooks remain intact.

Cursor receives a native `~/.cursor/hooks.json` entry and shared skills under `~/.agents/skills/`. Cursor User Rules cannot be installed through a documented file interface. Clipboard copying remains an explicit advanced convenience; it never counts as installation. User Rules apply to Cursor Agent (Chat), not Inline Edit, Cursor Tab, or every other Cursor AI feature.

`adapters/cursor/cli-permissions.recommended.json` is a reviewable recommendation for `~/.cursor/cli-config.json`; it is never installed automatically and does not govern all Cursor IDE execution.

## Advanced configuration

Omitting `--product` is recommended. Explicit selection remains available for an intentionally undetected product or a distribution test:

```sh
python tools/guardrails.py install --product codex --dry-run
python tools/guardrails.py install --product claude
python tools/guardrails.py install --product cursor
python tools/guardrails.py install --product all
```

Use `--home` only for an intentionally alternate home or safe testing. Contributors and CI can run the component commands independently:

```sh
python tools/guardrails.py build
python tools/guardrails.py validate
python tools/guardrails.py routing validate
python tools/guardrails.py packs validate
python -m unittest discover -s tests -v
```

Builds are deterministic: stable manifest order, no timestamp, and exactly one terminal newline. Validation rejects missing, stale, malformed, oversized, unsafe, non-portable, or inconsistent canonical and generated data. When available, it also runs `codex execpolicy check` and OPA policy tests.

Add `--verbose` to install or update only when troubleshooting internal build, validator, runtime, and adapter details. Default human output deliberately hides content digests and repository-local source paths.

### Optional execution routing

Safety-only installation is the default. Omitting `--routing-profile` installs no new routing agents and preserves existing managed routing. The recommended profile is `balanced`, but installation requires explicit intent:

```sh
python tools/guardrails.py routing show --profile balanced --product all
python tools/guardrails.py install --product all --routing-profile balanced --dry-run
python tools/guardrails.py install --product all --routing-profile balanced
python tools/guardrails.py status --product all --show-routing
```

Routing can also be managed independently:

```sh
python tools/guardrails.py routing validate
python tools/guardrails.py routing set economy --product codex --dry-run
python tools/guardrails.py routing set quality --product claude
python tools/guardrails.py routing set none --product all
```

Profiles map task classes to portable `economy`, `balanced`, and `deep` capability tiers; map those independently to `low`, `medium`, and `high` reasoning; cap read-only and writing concurrency; and set escalation thresholds and bounded attempts. Economy agents remain read-only, ordinary writers use at least the balanced tier, and every high-risk class routes to deep. Five `workstation_` canonical roles generate native files under `~/.codex/agents/`, `~/.claude/agents/`, or `~/.cursor/agents/`. Only the implementer can write. Unmanaged collisions are preserved unless `--force` is explicit, in which case the displaced file is backed up.

Vendor IDs live only in `routing/model-maps/`. Override one installed subagent tier without changing the primary session model:

```sh
python tools/guardrails.py routing set balanced --product cursor \
  --model-override cursor:economy=provider/model-id
```

Cursor defaults to `inherit` because available IDs depend on plan and organisation policy; Cursor may fall back even after an explicit ID is configured. Status therefore reports models as configured but availability as unverified. The installer never sets Claude's global subagent model environment variable, writes a main-model setting, or changes the active session model.

Subagents have startup and independent-context costs, so they are inappropriate for trivial work. The roles require targeted search and reads, narrow tests before broad suites, terse deterministic summaries that preserve exit status and useful failures, reuse of an existing agent context when helpful, and stopping unused agents. No output-filtering or shell-command rewriting hook is installed.

### Capability packs and infrastructure safety

Packs are not added to the always-loaded global Markdown. Detection searches build manifests, wrappers, lockfiles, and infrastructure configuration in monorepositories, prunes dependency caches, build output, generated directories, and vendored code, and reports every evidence path. It never uses the network, runs a build tool, or modifies the inspected repository.

```sh
python tools/guardrails.py packs list
python tools/guardrails.py packs detect --repo /path/to/repository
python tools/guardrails.py packs explain --repo /path/to/repository
python tools/guardrails.py packs validate
```

An optional repository-local `.ai-guardrails.json` can enable/disable packs, select a package manager or build root, add generated-directory exclusions, resolve ambiguity, and classify targets. It must not contain credentials and does not need to be committed. Node manager selection respects `package.json#packageManager`, repository configuration, lockfile evidence, then an explicit ambiguity override. Java workflows prefer repository Maven or Gradle wrappers and never switch toolchains incidentally.

Fresh default installation makes every current stable pack available as an on-demand skill and compiles its deterministic controls into the immutable runtime. Repository detection identifies which guidance is relevant without making pack selection a consumer decision. Pack text is never concatenated into always-loaded global Markdown. Explicit pack options remain for distribution authoring and deliberately reduced advanced installations:

```sh
python tools/guardrails.py install --product all --pack java --pack node --dry-run
python tools/guardrails.py install --product all --pack kubernetes \
  --safety-profile infrastructure-observe
python tools/guardrails.py install --product all --all-packs --dry-run
python tools/guardrails.py status --product all --repo /path/to/repository
```

Safety profiles are separate from model-routing profiles. A fresh install defaults to `infrastructure-observe`; `development` is available and also denies remote mutation. Publication and production mutation are denied. `infrastructure-nonprod` permits only bounded mutations with explicit targets mapped to `dev`, `tst`, or `int` in `~/.ai-guardrails/targets.json`. `infrastructure-strict` permits observation and validation only. Unknown targets are protected, and the installer never enables infrastructure mutation implicitly.

Operation classes are `observe`, `validate`, `mutate`, `destructive`, `sensitive-read`, `publish`, `privilege-escalation`, and `guardrail-modification`. Deterministic denial reasons include the stable policy identifier and class without reproducing command/tool arguments. Kubernetes Secret values, raw kubeconfig, Terraform/OpenTofu state and plans, Spacelift tokens, logs, database output, certificates, and cloud credentials receive sensitive handling. Supported tools do not imply that every cloud, database, observability, CI, container, or Kubernetes-adjacent CLI is protected; unknown tools require explicit assessment and rules.

Package publication stays human-controlled even when an agent is asked to finish a release. Packs permit local preparation and verification, never upload. Infrastructure approvals must come from platform RBAC, a human workflow, or another authority outside the agent; no self-issued bypass token exists.

The Spacelift pack defaults to read-only shell, GraphQL, and MCP use. It denies run control, tasks, token/profile mutation, GraphQL mutations, and every call to the write-scoped current MCP `mutate` and `intent` tools, plus legacy action-style mutators. The Rego v1 examples in `platform-policies/spacelift/` cover Approval, Plan, Push, Trigger, Notification, and Login policies with configurable identities, labels, metadata, resource types, branches, accounts, regions, and blast-radius thresholds. They are testable with OPA but are never attached to a real account.

The v1.1 packs preserve the same human boundaries: images and packages are not pushed; Azure privilege/destructive/sensitive reads are denied; PR self-approval, automatic merge, secret mutation, and deployment triggers are restricted; production migrations and high-confidence destructive SQL are denied; incident mode remains read-only; contract tools remain repository-native; private keys and secret values must not enter model context.

### Governance, explanation, and scanning

Rules have `disabled`, `observe`, `warn`, or `deny` rollout modes. Observe and warn matches write only a content-free local audit event; warning injection uses a safe diagnostic where products lack a common response field. Deny returns the product-compatible deterministic denial. Inspect any request without executing it:

```sh
python tools/guardrails.py explain --command 'terraform destroy' --pack terraform
python tools/guardrails.py simulate --tool mcp__spacelift__mutate \
  --tool-arguments '{"operation":"synthetic"}' --pack spacelift --format json
python tools/guardrails.py effective --product all --repo .
python tools/guardrails.py diff-installed --product all
python tools/guardrails.py doctor --product all
```

Expiring waivers live only under `~/.ai-guardrails/waivers/`. Creation requires an interactive TTY and exact human confirmation, defaults to one use and 15 minutes, stores only a request digest, and is capped at 24 hours. Broad destructive/privilege wildcards are rejected. A local waiver is defence in depth, not cryptographic approval; platform RBAC and human workflows remain authoritative.

```sh
python tools/guardrails.py waiver create --rule-id RULE --repo . \
  --target-scope none --digest SHA256 --reason 'bounded exception' \
  --change-reference CHANGE-123
python tools/guardrails.py waiver list
python tools/guardrails.py waiver revoke WAIVER_ID
```

Trust modes are `trusted-workspace`, `untrusted-workspace`, `untrusted-external-input`, and `incident-observe`. Untrusted content is evidence only: it cannot grant permission, request secrets, expand network access, or weaken policy. The installed runtime, waiver storage, state, target mappings, managed rules/hooks/skills/agents, and repository governance paths receive self-protection decisions. This is local defence in depth, not tamper-proofing against the workstation owner.

The offline repository scanner emits human, JSON, SARIF 2.1.0, or JUnit XML. It checks high-confidence filenames and conservative text patterns; it does not claim semantic YAML, Rego, shell, SQL, or protocol parsing.

```sh
python tools/guardrails.py scan --repo . --format human
python tools/guardrails.py scan --repo . --format sarif --output guardrails.sarif
python tools/guardrails.py receipt --repo . --product all
```

Audit rotation is bounded and synchronous. Events and receipts contain identifiers, hashes, classifications, counts, and outcomes only. They never contain prompts, source code, full commands, arguments, environment values, raw logs, or secret values.

## Uninstall, rollback, and recovery

```sh
python tools/guardrails.py uninstall --product all --dry-run
python tools/guardrails.py uninstall --product all
```

Uninstallation removes only recorded files, the delimited Codex block, and matching hook entries. It preserves unrelated configuration and retains locally modified managed content unless `--force` is explicit. It never deletes the whole `.codex`, `.claude`, `.cursor`, or `.agents` directory. Backups remain available under `~/.ai-guardrails/backups/` for manual recovery; the state file records their paths but never stores prior configuration contents.

If `status` reports `modified`, inspect the file and either preserve the local change or reinstall/uninstall with `--force`, which creates a backup before replacement. `stale` means the repository's canonical source digest changed after installation. `unmanaged-collision` means a destination exists without ownership in this repository's state and will not be overwritten by default.

## Authoring

To add policy, create a vendor-neutral Markdown fragment, add one ordered manifest entry with product applicability and classification, then rebuild. To add a skill, create `skills/workstation-<name>/SKILL.md` with only portable `name` and `description` frontmatter and an evidence-driven procedure. To add a command denial, add a stable rule to `enforcement/command-policy.json` with a supported matching strategy plus positive and safe counterexamples, then extend the table-driven tests. To add routing, define a bounded task class or canonical role, update all profiles and model maps as applicable, then run routing and full validation. To add a stack without enlarging global policy, create a validated pack under `packs/<type>/<id>/` and add marker-based fixtures.

See [policy authoring](docs/policy-authoring.md), [routing and measurement](docs/routing-and-cost.md), [architecture](docs/architecture.md), [compatibility](docs/compatibility.md), and the [threat model](docs/threat-model.md) for details.

Further operational references: [operations](docs/operations.md), [routing and cost](docs/routing-and-cost.md), [capability packs](docs/capability-packs.md), [Spacelift](docs/spacelift.md), and [enterprise output](docs/enterprise.md).

## Compatibility limitations

Product formats and hook coverage can change. The shared parser handles common wrappers and simple command chains but is not a complete shell or PowerShell parser. Malformed or unsupported hook input fails open with a redacted diagnostic; recognised high-confidence dangerous commands return a deterministic denial. Codex command rules are experimental, apply to commands requested outside the sandbox, and are defence in depth rather than a universal execution boundary. See `docs/compatibility.md` for the dated official-documentation matrix.
