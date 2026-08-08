# AI engineering workstation guardrails (fewer sharp edges)

AI coding agents can inspect repositories, edit files, run commands, and call external tools. This project gives those agents one vendor-neutral set of engineering expectations and installs product-specific adapters for OpenAI Codex, Anthropic Claude Code, Cursor, GitHub Copilot in Visual Studio Code and Visual Studio, and JetBrains AI Assistant/Copilot for JetBrains. It is designed to make agent-assisted work more predictable: understand the repository first, preserve user changes, avoid secrets and destructive operations, verify the result, and report what actually happened.

In other words, this is a local policy and enforcement kit for AI engineering work—useful guardrails for clever agents, without a tiny committee living in your terminal. The v1 layer covers workstation installation, routing, polyglot development, Ansible, Kubernetes/Helm/Terraform/Spacelift, explainability, waivers, audit receipts, trust, scanning, and risk verification. The v1.1 layer adds containers/OCI, Azure, source control and CI/CD, databases, observability, API/schema compatibility, secrets/PKI, and enterprise examples.

<p align="center">
  <img src="https://raw.githubusercontent.com/ZarrenSpryXplor/ai-engineering-guardrails/main/assets/ai_comic_screen_only_corrected.png" width="720" alt="A comic about an AI agent denying over-engineering before a stack of resource monitors catches fire.">
</p>

## What you get

- A canonical policy that is compiled into six product adapters instead of being maintained six times.
- Deterministic command and structured-tool checks that deny a deliberately narrow set of high-confidence risks, such as destructive Git operations, publication, credential exposure, and dangerous infrastructure actions.
- Portable skills and capability packs for common application and platform stacks, including Java, .NET, Python, Node.js/TypeScript, Ansible, Kubernetes, Helm, Terraform, OpenTofu, Terragrunt, and Spacelift.
- A safe installer that detects supported products locally, preserves unrelated configuration, creates backups, and keeps an immutable runtime independent of the repository clone.
- Optional routing guidance for bounded subagent work, plus local policy overlays for workstation-specific additions or stronger rules.

The default installation is intentionally conservative: normal development and local validation remain available, while production changes, remote infrastructure mutation, package publication, credential reads, and unknown targets stay protected. Think of it as a seatbelt for agent-assisted engineering—not a replacement for operating-system permissions, product approvals, cloud IAM, Kubernetes RBAC, branch protection, or human release decisions.

## Coverage at a glance

| Product | What the installer can configure | Important boundary |
| --- | --- | --- |
| Codex | Global instructions, skills, custom agents, PreToolUse hook, and defence-in-depth command rules. | Rules and hooks are not a complete workstation boundary. |
| Claude Code | Modular rules, skills, custom agents, and a PreToolUse hook. | Product permissions and trust remain unchanged. |
| Cursor | Native hook, shared skills, custom agents, and generated User Rules text. | User Rules still require a manual paste and do not cover every Cursor mode. |
| GitHub Copilot in VS Code | User instructions, shared skills, optional custom agents, and a Preview PreToolUse hook. | Hooks may be disabled by an organisation and inline suggestions are not covered. |
| GitHub Copilot in Visual Studio | Managed user instructions, shared skills, and version-dependent user-selectable agents. | Visual Studio has no hook or subagent integration here. |
| JetBrains AI Assistant / Copilot | Shared skills, optional documented Copilot global instructions, manual Chat Instructions text, project-rule export, and a manual Preview agent bundle. | Native Chat, operation modes, approvals, MCP, and hooks remain outside this installer. |

Markdown guidance influences agent decisions. The shared `PreToolUse` engine deterministically denies a deliberately narrow set of high-confidence destructive commands. Neither mechanism is a complete workstation security boundary; keep operating-system least privilege, sandboxes, branch protection, cloud IAM, and production change controls in place.

## Quick start: three commands and a little peace of mind

Prefer snippets over detail? Start with the [quick user guide](https://github.com/ZarrenSpryXplor/ai-engineering-guardrails/blob/main/docs/user-guide.md).

Python 3.11 or later is the only requirement. Do not run the installer with `sudo`, as Administrator, or from an elevated shell. A quick preview is encouraged; it is cheaper than discovering a surprise configuration change later.

Install the versioned application with [pipx](https://pipx.pypa.io/) (recommended), then preview and install for the supported products detected locally:

```sh
git clone https://github.com/ZarrenSpryXplor/ai-engineering-guardrails.git
cd ai-engineering-guardrails
pipx install .

ai-guardrails install --dry-run
ai-guardrails install
ai-guardrails status
```

The distribution is `ai-engineering-guardrails`, its Python import package is `ai_engineering_guardrails`, and its installed command is `ai-guardrails`. Python 3.11+ is required. The module form `python -m ai_engineering_guardrails` is equivalent to the console command. No package is published by this repository change; install from a reviewed clone or built wheel.

For a direct Git install after reviewing a specific revision, pin a reviewed tag or full commit rather than a moving branch:

```sh
pipx install 'git+https://github.com/ZarrenSpryXplor/ai-engineering-guardrails.git@<reviewed-tag-or-full-commit>'
```

No product, pack, profile, target mapping, or waiver selection is required. Detection uses local commands, existing product configuration, and managed state without contacting the network. If nothing supported is found, the installer makes no changes and prints an exact explicit-product command. No wizard, no guessing game, no mysterious cloud login.

The default posture enables normal application development, all stable language and tool guidance as on-demand skills, infrastructure observation, and local render/lint/validate/plan work. It denies destructive Git operations, publication, credential exposure, remote infrastructure mutation, production operations, and mutation of unknown targets. It leaves the primary model, model routing, approval mode, sandbox, network access, permissions, credentials, and target mappings unchanged. Enterprise output is not installed, Spacelift policy is not deployed, and auditing is local and redacted.

The dry-run performs deterministic build computation, canonical validation, offline product and repository-capability detection, collision checks, backup planning, and installation planning without modifying files. Its default output lists product configuration, managed blocks, skills, agents, planned backups, unchanged settings, safety boundaries, and manual steps.

Update and removal use the products already recorded in installation state:

```sh
ai-guardrails update
ai-guardrails uninstall --dry-run
ai-guardrails uninstall
pipx uninstall ai-engineering-guardrails
```

`ai-guardrails uninstall` removes only the managed product configuration. `pipx uninstall ai-engineering-guardrails` removes the application itself after that configuration is no longer needed.

If Cursor is detected, complete its one manual User Rules step after installation:

```sh
ai-guardrails print-cursor-rules
```

Open **Cursor Settings / Customize / Rules / User Rules**, paste the complete output, and save it. This command prints authoritative text; it does not claim installation.

## Installed baseline and local policy

The installed baseline is immutable package data. It is never edited in `site-packages` or the pipx environment. To add local guidance or strengthen a deterministic rule, keep a small overlay outside the package:

```sh
ai-guardrails policy init
ai-guardrails policy list
ai-guardrails policy show git-reset-hard
ai-guardrails policy validate
ai-guardrails policy diff
ai-guardrails policy apply --dry-run
ai-guardrails policy apply
```

The overlay lives at `~/.ai-guardrails/policy/overrides.json`; Markdown fragments live under its `fragments/` directory. It can append product-scoped behaviour, strengthen an existing rollout mode, and add validated local shell rules. It cannot permanently weaken a bundled rule, edit matching logic for a bundled rule, or replace deterministic enforcement. Use an expiring waiver for a narrow temporary exception. `policy apply` reapplies the existing installation’s packs, routing, safety, and trust settings; it does not update the application itself. Local overlays survive application upgrades and uninstallation.

`pipx upgrade ai-engineering-guardrails` upgrades the application when an index or configured source provides a newer release. `ai-guardrails update` does not download software or contact a registry: it reapplies the already installed bundled baseline and valid local overlay.

## Repository model

- `ai_engineering_guardrails/_resources/` is the single canonical, read-only resource tree shipped in wheels and source distributions. It contains `policy/`, `skills/`, `enforcement/`, `routing/`, `packs/`, `config/`, `trust/`, `risk/`, `supply-chain/`, `waivers/`, `audit/`, `platform-policies/`, and `enterprise/`.
- `ai_engineering_guardrails/` contains the Python 3.11+ standard-library implementation. It consumes resources from the one bundled tree whether run from a checkout, editable install, or wheel.
- `enforcement/pre_tool_use.py` and `tools/guardrails.py` are thin repository development shims. The latter calls the same `ai_engineering_guardrails.cli:main` entry point as `ai-guardrails`.
- `adapters/` contains generated hook fragments, Codex defence-in-depth rules, and a Cursor CLI recommendation.
- `dist/` and `adapters/` are checked-in generated contributor output, not package inputs. Never edit them directly.

Behavioural guidance and deterministic controls are intentionally distinct. A fragment classified as `deterministic_enforcement_guidance` explains safe behaviour, while the command policy separately defines the precise operations the hook can deny.

The routing layer is distinct from both. It can make bounded delegation more economical and keep noisy work out of the main context, but it neither grants authority nor weakens safety rules. It does not promise lower latency or a specific monetary saving.

The always-loaded policy is deliberately capped at 8 KiB. Detailed stack workflows belong in on-demand skills and packs, where they arrive only when useful instead of turning every agent session into a filing cabinet.

## Installation details

The real install runs the deterministic build and full local validation before touching user configuration. It creates an immutable, content-addressed runtime under `~/.ai-guardrails/runtime/`, validates it, registers hooks using the absolute current Python interpreter, writes state atomically, and verifies every managed path afterwards. Live hooks never point back to the clone. State contains only non-sensitive paths, hashes, profiles, packs, and manual steps; backups are stored under `~/.ai-guardrails/backups/` before pre-existing configuration is first mutated.

Codex receives a managed block in its effective global `AGENTS` file, a dedicated `.rules` file, a structurally merged user hook, and skills under `~/.agents/skills/`. `CODEX_HOME` is honoured when it resolves inside the selected `--home`; an external value is rejected so an alternate-home test cannot escape into real configuration. Review and trust the installed user hook with `/hooks` in Codex if prompted. The installer does not alter `config.toml`, approval mode, sandbox mode, or network access.

Claude Code receives modular files under `~/.claude/rules/`, a structurally merged `~/.claude/settings.json` hook, and skills under `~/.claude/skills/`. Existing keys, permission rules, and unrelated hooks remain intact.

Cursor receives a native `~/.cursor/hooks.json` entry and shared skills under `~/.agents/skills/`. Cursor User Rules cannot be installed through a documented file interface. Clipboard copying remains an explicit advanced convenience; it never counts as installation. User Rules apply to Cursor Agent (Chat), not Inline Edit, Cursor Tab, or every other Cursor AI feature.

VS Code receives `~/.copilot/instructions/workstation-guardrails.instructions.md`, shared skills under `~/.agents/skills/`, optional agents under `~/.copilot/agents/`, and—where the project does not already own a compatible Claude hook—`~/.copilot/hooks/workstation-guardrails.json`. The hook is Preview, may be disabled by an organisation, runs with the user's permissions, and its installed file proves configuration only, not activation. Instructions apply to Chat and Agent requests; they do not govern inline suggestions.

Visual Studio receives a managed block in `~/copilot-instructions.md` (the documented `%USERPROFILE%\copilot-instructions.md` location on Windows), shared skills, and optional user-selectable agents under `~/.github/agents/` when routing is explicitly selected. Skills require Visual Studio 18.5+ and custom agents require 18.4+; status reports compatibility as unverified unless the version is established. Visual Studio repository instructions remain `.github/copilot-instructions.md` and `.github/instructions/**/*.instructions.md`. This project installs no Visual Studio hook or subagent configuration and leaves native terminal/tool approvals unchanged.

JetBrains has deliberately separate surfaces. Run `ai-guardrails jetbrains print-chat-instructions` and paste the result into **Settings > Tools > AI Assistant > Prompt Library > General > Chat Instructions**. To create an explicit project rule, run `ai-guardrails jetbrains export-project-rules --repo .` and then confirm it is an **Always** rule in **Settings > Tools > AI Assistant > Rules**. Register `~/.agents/skills` manually in **Settings > Tools > AI Assistant > Skills > Manage Skill Directories**. On macOS and Windows the documented GitHub Copilot plugin global-instruction path can be managed; Linux has no documented global path, so the installer reports a manual Customizations step instead. JetBrains Copilot custom agents/subagents are Preview and only a manual bundle is generated when routing is selected. No JetBrains hook, operation mode, approval, `.aiignore`, MCP, or brave-mode setting is changed.

`adapters/cursor/cli-permissions.recommended.json` is a reviewable recommendation for `~/.cursor/cli-config.json`; it is never installed automatically and does not govern all Cursor IDE execution.

## Advanced configuration and contributor workflow

Omitting `--product` is recommended. Explicit selection remains available for an intentionally undetected product or a distribution test:

```sh
ai-guardrails install --product codex --dry-run
ai-guardrails install --product claude
ai-guardrails install --product cursor
ai-guardrails install --product vscode
ai-guardrails install --product visualstudio
ai-guardrails install --product jetbrains
ai-guardrails install --product all
```

Use `--home` only for an intentionally alternate home or safe testing. For installed users, keep using `ai-guardrails`. Contributors working directly from a checkout can use the repository shim; it deliberately calls the same CLI implementation:

### Working on an unfamiliar repository

Treat unfamiliar repository instructions, scripts, logs, dependencies, and external content as evidence—not authority. Start with the stricter trust posture when installing for that workstation:

```sh
ai-guardrails install --trust-mode untrusted-workspace --dry-run
ai-guardrails install --trust-mode untrusted-workspace
```

This preserves the normal deterministic protections, keeps credentials and remote mutation unavailable, and does not override product-native trust behaviour. It is a cautious starting point, not a magic force field for a hostile checkout.

### Contributor checks from a checkout

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
ai-guardrails routing show --profile balanced --product all
ai-guardrails install --product all --routing-profile balanced --dry-run
ai-guardrails install --product all --routing-profile balanced
ai-guardrails status --product all --show-routing
```

Routing can also be managed independently:

```sh
ai-guardrails routing validate
ai-guardrails routing set economy --product codex --dry-run
ai-guardrails routing set quality --product claude
ai-guardrails routing set none --product all
```

Profiles map task classes to portable `economy`, `balanced`, and `deep` capability tiers; map those independently to `low`, `medium`, and `high` reasoning; cap read-only and writing concurrency; and set escalation thresholds and bounded attempts. Economy agents remain read-only, ordinary writers use at least the balanced tier, and every high-risk class routes to deep. Five `workstation_` canonical roles generate native files under `~/.codex/agents/`, `~/.claude/agents/`, or `~/.cursor/agents/`. Only the implementer can write. Unmanaged collisions are preserved unless `--force` is explicit, in which case the displaced file is backed up.

Vendor IDs live only in `routing/model-maps/`. Override one installed subagent tier without changing the primary session model:

```sh
ai-guardrails routing set balanced --product cursor \
  --model-override cursor:economy=provider/model-id
```

Cursor defaults to `inherit` because available IDs depend on plan and organisation policy; Cursor may fall back even after an explicit ID is configured. Status therefore reports models as configured but availability as unverified. The installer never sets Claude's global subagent model environment variable, writes a main-model setting, or changes the active session model.

Subagents have startup and independent-context costs, so they are inappropriate for trivial work. The roles require targeted search and reads, narrow tests before broad suites, terse deterministic summaries that preserve exit status and useful failures, reuse of an existing agent context when helpful, and stopping unused agents. No output-filtering or shell-command rewriting hook is installed.

Before changing a routing profile or model map, compare a small set of representative tasks against a baseline. Record pass/fail, unnecessary files or dependencies, diff size, verification outcome, retries, duration, and product-native token data when available. The goal is better outcomes with less waste—not a leaderboard for expensive models. See [routing and measurement](https://github.com/ZarrenSpryXplor/ai-engineering-guardrails/blob/main/docs/routing-and-cost.md) for the lightweight protocol.

### Capability packs and infrastructure safety

Packs are not added to the always-loaded global Markdown. Detection searches build manifests, wrappers, lockfiles, and infrastructure configuration in monorepositories, prunes dependency caches, build output, generated directories, and vendored code, and reports every evidence path. It never uses the network, runs a build tool, or modifies the inspected repository.

```sh
ai-guardrails packs list
ai-guardrails packs detect --repo /path/to/repository
ai-guardrails packs explain --repo /path/to/repository
ai-guardrails packs validate
```

An optional repository-local `.ai-guardrails.json` can enable/disable packs, select a package manager or build root, add generated-directory exclusions, resolve ambiguity, and classify targets. It must not contain credentials and does not need to be committed. Node manager selection respects `package.json#packageManager`, repository configuration, lockfile evidence, then an explicit ambiguity override. Java workflows prefer repository Maven or Gradle wrappers and never switch toolchains incidentally.

Fresh default installation makes every current stable pack available as an on-demand skill and compiles its deterministic controls into the immutable runtime. Repository detection identifies which guidance is relevant without making pack selection a consumer decision. `packs explain` also surfaces each detected pack's concise policy heading, named verification checks, and routing hints without loading that detail globally. Pack text is never concatenated into always-loaded global Markdown. Explicit pack options remain for distribution authoring and deliberately reduced advanced installations:

```sh
ai-guardrails install --product all --pack java --pack node --dry-run
ai-guardrails install --product all --pack kubernetes \
  --safety-profile infrastructure-observe
ai-guardrails install --product all --all-packs --dry-run
ai-guardrails status --product all --repo /path/to/repository
```

Safety profiles are separate from model-routing profiles. A fresh install defaults to `infrastructure-observe`; `development` is available and also denies remote mutation. Publication and production mutation are denied. `infrastructure-nonprod` permits only bounded mutations with explicit targets mapped to `dev`, `tst`, or `int` in `~/.ai-guardrails/targets.json`. `infrastructure-strict` permits observation and validation only. Unknown targets are protected, and the installer never enables infrastructure mutation implicitly.

Operation classes are `observe`, `validate`, `mutate`, `destructive`, `sensitive-read`, `publish`, `privilege-escalation`, and `guardrail-modification`. Deterministic denial reasons include the stable policy identifier and class without reproducing command/tool arguments. Ansible Vault and inventory output, Kubernetes Secret values, raw kubeconfig, Terraform/OpenTofu state and plans, Spacelift tokens, logs, database output, certificates, and cloud credentials receive sensitive handling. Supported tools do not imply that every cloud, database, observability, CI, container, or Kubernetes-adjacent CLI is protected; unknown tools require explicit assessment and rules.

Package publication stays human-controlled even when an agent is asked to finish a release. Packs permit local preparation and verification, never upload. Infrastructure approvals must come from platform RBAC, a human workflow, or another authority outside the agent; no self-issued bypass token exists.

The Spacelift pack defaults to read-only shell, GraphQL, and MCP use. It denies run control, tasks, token/profile mutation, GraphQL mutations, and every call to the write-scoped current MCP `mutate` and `intent` tools, plus legacy action-style mutators. The Rego v1 examples in `platform-policies/spacelift/` cover Approval, Plan, Push, Trigger, Notification, and Login policies with configurable identities, labels, metadata, resource types, branches, accounts, regions, and blast-radius thresholds. They are testable with OPA but are never attached to a real account.

The v1.1 packs preserve the same human boundaries: images and packages are not pushed; Azure privilege/destructive/sensitive reads are denied; PR self-approval, automatic merge, secret mutation, and deployment triggers are restricted; production migrations and high-confidence destructive SQL are denied; incident mode remains read-only; contract tools remain repository-native; private keys and secret values must not enter model context.

### Governance, explanation, and scanning

Rules have `disabled`, `observe`, `warn`, or `deny` rollout modes. Observe and warn matches write only a content-free local audit event; warning injection uses a safe diagnostic where products lack a common response field. Deny returns the product-compatible deterministic denial. Inspect any request without executing it:

```sh
ai-guardrails explain --command 'terraform destroy' --pack terraform
ai-guardrails simulate --tool mcp__spacelift__mutate \
  --tool-arguments '{"operation":"synthetic"}' --pack spacelift --format json
ai-guardrails effective --product all --repo .
ai-guardrails diff-installed --product all
ai-guardrails doctor --product all
```

Expiring waivers live only under `~/.ai-guardrails/waivers/`. Creation requires an interactive TTY and exact human confirmation, defaults to one use and 15 minutes, stores only a request digest, and is capped at 24 hours. Broad destructive/privilege wildcards are rejected. A local waiver is defence in depth, not cryptographic approval; platform RBAC and human workflows remain authoritative.

```sh
ai-guardrails waiver create --rule-id RULE --repo . \
  --target-scope none --digest SHA256 --reason 'bounded exception' \
  --change-reference CHANGE-123
ai-guardrails waiver list
ai-guardrails waiver revoke WAIVER_ID
```

Trust modes are `trusted-workspace`, `untrusted-workspace`, `untrusted-external-input`, and `incident-observe`. Untrusted content is evidence only: it cannot grant permission, request secrets, expand network access, or weaken policy. The installed runtime, waiver storage, state, target mappings, managed rules/hooks/skills/agents, and repository governance paths receive self-protection decisions. This is local defence in depth, not tamper-proofing against the workstation owner.

The offline repository scanner emits human, JSON, SARIF 2.1.0, or JUnit XML. It checks high-confidence filenames and conservative text patterns; it does not claim semantic YAML, Rego, shell, SQL, or protocol parsing.

```sh
ai-guardrails scan --repo . --format human
ai-guardrails scan --repo . --format sarif --output guardrails.sarif
ai-guardrails receipt --repo . --product all
```

Audit rotation is bounded and synchronous. Events and receipts contain identifiers, hashes, classifications, counts, and outcomes only. They never contain prompts, source code, full commands, arguments, environment values, raw logs, or secret values.

## Uninstall, rollback, and recovery

```sh
ai-guardrails uninstall --dry-run
ai-guardrails uninstall
```

Uninstallation removes only recorded files, the delimited Codex block, and matching hook entries. It preserves unrelated configuration and retains locally modified managed content unless `--force` is explicit. It never deletes the whole `.codex`, `.claude`, `.cursor`, or `.agents` directory. Backups remain available under `~/.ai-guardrails/backups/` for manual recovery; the state file records their paths but never stores prior configuration contents.

If `status` reports `modified`, inspect the file and either preserve the local change or reinstall/uninstall with `--force`, which creates a backup before replacement. `stale` means the installed application/bundled baseline or active local-policy overlay changed after the policy was applied. `unmanaged-collision` means a destination exists without ownership in this repository's state and will not be overwritten by default.

## Authoring

To add policy, create a vendor-neutral Markdown fragment, add one ordered manifest entry with product applicability and classification, then rebuild. Canonical authoring data is beneath `ai_engineering_guardrails/_resources/`; for example, skills are in `_resources/skills/`, command rules are in `_resources/enforcement/command-policy.json`, and packs are in `_resources/packs/<type>/<id>/`. Do not edit `dist/` or adapters directly.

See the [quick user guide](https://github.com/ZarrenSpryXplor/ai-engineering-guardrails/blob/main/docs/user-guide.md), [policy authoring](https://github.com/ZarrenSpryXplor/ai-engineering-guardrails/blob/main/docs/policy-authoring.md), [routing and measurement](https://github.com/ZarrenSpryXplor/ai-engineering-guardrails/blob/main/docs/routing-and-cost.md), [architecture](https://github.com/ZarrenSpryXplor/ai-engineering-guardrails/blob/main/docs/architecture.md), [compatibility](https://github.com/ZarrenSpryXplor/ai-engineering-guardrails/blob/main/docs/compatibility.md), and the [threat model](https://github.com/ZarrenSpryXplor/ai-engineering-guardrails/blob/main/docs/threat-model.md) for details.

Further operational references: [operations](https://github.com/ZarrenSpryXplor/ai-engineering-guardrails/blob/main/docs/operations.md), [routing and cost](https://github.com/ZarrenSpryXplor/ai-engineering-guardrails/blob/main/docs/routing-and-cost.md), [capability packs](https://github.com/ZarrenSpryXplor/ai-engineering-guardrails/blob/main/docs/capability-packs.md), [Spacelift](https://github.com/ZarrenSpryXplor/ai-engineering-guardrails/blob/main/docs/spacelift.md), and [enterprise output](https://github.com/ZarrenSpryXplor/ai-engineering-guardrails/blob/main/docs/enterprise.md).

## Compatibility limitations

Product formats and hook coverage can change. The shared parser handles common wrappers and simple command chains but is not a complete shell or PowerShell parser. Malformed or unsupported hook input fails open with a redacted diagnostic; recognised high-confidence dangerous commands return a deterministic denial. Codex command rules are experimental, apply to commands requested outside the sandbox, and are defence in depth rather than a universal execution boundary. See `docs/compatibility.md` for the dated official-documentation matrix.
