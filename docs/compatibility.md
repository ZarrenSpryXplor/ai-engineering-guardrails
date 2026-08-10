# Product compatibility

## Terminal UX capability verification (2026-08-09)

| Product | Documented native capability | This project’s integration | Minimum/version boundary |
| --- | --- | --- | --- |
| Codex CLI | `/statusline` picker persists ordered `tui.status_line` fields; `/status` and `/usage` expose native status/usage views. | Explicit narrow marker-owned `tui.status_line` edit using only the current exact documented sample IDs; no external renderer. | Current documented Codex CLI; unlisted rate/token item IDs remain product-controlled and are left to the picker. |
| Claude Code | `statusLine.type=command` runs a local command with session JSON on stdin; documented fields include model, context, rate limits, estimated cost, duration, and worktree data. | Managed immutable Python renderer and structural user-settings merge. | `COLUMNS` sizing requires Claude Code 2.1.153+; workspace trust is required; `disableAllHooks` disables custom status lines. |
| Cursor CLI | `/status-indicators` toggles terminal-title indicators. | Manual native guidance only. No documented programmable usage/status line or `/usage` command. | Current documented Cursor CLI; activation is user-controlled. |

Sources: [Codex developer commands](https://developers.openai.com/codex/developer-commands), [Codex configuration reference](https://developers.openai.com/codex/config-reference), [Codex sample configuration](https://developers.openai.com/codex/config-file/config-sample), [Claude Code status line](https://code.claude.com/docs/en/statusline), [Claude Code settings](https://code.claude.com/docs/en/settings), [Claude Code hooks](https://code.claude.com/docs/en/hooks), and [Cursor CLI slash commands](https://cursor.com/docs/cli/reference/slash-commands.md). These are capability documents, not proof of a user’s installed version, account entitlement, workspace trust, or active configuration.

Verified against current official documentation on **2026-08-09**. The linked vendor pages are the compatibility authority; repository behaviour below separates documented product behaviour, explicitly experimental behaviour, product limitations, and local design decisions.

| Product | Global behavioural guidance | Skills | Deterministic controls | Optional native routing agents |
| --- | --- | --- | --- | --- |
| OpenAI Codex | One effective non-empty global `AGENTS` file under `CODEX_HOME`; project `AGENTS.md` files layer by directory. | Personal skills from `~/.agents/skills/`. | User `~/.codex/hooks.json` `PreToolUse` covers shell, MCP, and most local function tools; experimental `.rules` remain defence in depth. | Standalone TOML under `~/.codex/agents/`; explicit model, effort, and read-only sandbox fields are supported. |
| Anthropic Claude Code | Personal modular rules from `~/.claude/rules/`; project `CLAUDE.md` supports `@` imports. | Personal skills from `~/.claude/skills/`. | Catch-all `PreToolUse` command hook structurally merged into `~/.claude/settings.json`. | Markdown with YAML frontmatter under `~/.claude/agents/`; model, effort, tool, and permission restrictions are supported. |
| Cursor | Project `AGENTS.md` is Git-backed; global User Rules are edited in Customize and apply to Agent Chat. | Personal skills from `~/.agents/skills/` (Cursor also documents compatibility locations). | Native catch-all user `~/.cursor/hooks.json`; separate CLI permission recommendation only. | Markdown with YAML frontmatter under `~/.cursor/agents/`; explicit model IDs and `readonly` are supported, subject to fallback. |
| GitHub Copilot in Visual Studio Code | User `.instructions.md` files under `~/.copilot/instructions/`; repository `AGENTS.md` also applies to Chat/Agent. | Shared personal skills from `~/.agents/skills/`. | `~/.copilot/hooks/` `PreToolUse` hooks are Preview and can be disabled by an organisation. | Personal `.agent.md` files under `~/.copilot/agents/`; model is inherited when omitted. |
| GitHub Copilot in Visual Studio | `%USERPROFILE%/copilot-instructions.md`; repository `.github/copilot-instructions.md` and `.github/instructions/**/*.instructions.md`. | `~/.agents/skills/` from Visual Studio 18.5+. | Unsupported. | Personal `.agent.md` files at `%USERPROFILE%\.github\agents` from Visual Studio 18.4+; user-selectable only, not subagents. |
| JetBrains AI Assistant and GitHub Copilot for JetBrains | Native Chat Instructions are a Prompt Library UI setting; project rules are `.aiassistant/rules/*.md`; hosted coding agents use their documented repository files. | `~/.agents/skills/` requires manual AI Assistant directory registration; support varies by agent. | Unsupported as a native JetBrains integration. | Copilot custom agents/subagents are Preview; this project emits a reviewable manual bundle rather than writing an undocumented path. |

## OpenAI Codex

Documented behaviour:

- [AGENTS.md discovery](https://developers.openai.com/codex/agent-configuration/agents-md) selects `AGENTS.override.md` from `CODEX_HOME` when it is the first non-empty global file, otherwise `AGENTS.md`; only one global file is used. Project files then layer from repository root toward the working directory. The documented combined project-instruction default is 32 KiB.
- [Skills](https://developers.openai.com/codex/build-skills) require `SKILL.md` with `name` and `description`; user skills load from `$HOME/.agents/skills`.
- [Hooks](https://developers.openai.com/codex/hooks) load from user `~/.codex/hooks.json` or inline `config.toml`, accept the nested `PreToolUse` denial used here, and observe shell calls as `Bash`, MCP tools as names such as `mcp__server__tool`, and most other local function tools. MCP arguments arrive as `tool_input`; hosted tools and specialised opt-out paths are not covered. Non-managed command hooks require review and trust, and hooks can be disabled in configuration.
- [Rules](https://developers.openai.com/codex/rules) are Starlark `prefix_rule` entries loaded from active `rules/` directories, support `forbidden`, and support inline `match` and `not_match` examples. `codex execpolicy check` is the documented validator.
- The [configuration reference](https://developers.openai.com/codex/config-reference) documents inline lifecycle hook tables and supported fields.
- [Subagents](https://developers.openai.com/codex/agent-configuration/subagents) document personal standalone TOML in `~/.codex/agents/`, required `name`, `description`, and `developer_instructions`, and optional `model`, `model_reasoning_effort`, and `sandbox_mode`. Current model guidance identifies Luna as narrow/fast, Terra as efficient general agent work, and Sol as the strongest general Codex tier.
- [Managed configuration](https://developers.openai.com/codex/enterprise/managed-configuration) documents enterprise `requirements.toml`, managed hooks, and precedence. Codex 0.138.0 and later support the preferred `allowed_permission_profiles` plus `default_permissions` form; older clients ignore those keys and require the legacy sandbox-mode form. Generated enterprise output targets 0.138+ clients, is example-only, and is never installed by the workstation command.

Experimental behaviour: Codex command rules are explicitly documented as experimental and may change. They control commands Codex requests to run outside the sandbox, not arbitrary workstation processes.

Product limitations: Codex describes standalone custom-agent authoring as a format that may evolve. Parent live permission and sandbox overrides can take precedence over custom-agent defaults. Product/account access to a configured model is not established by writing the TOML file.

Repository decisions: the installer compiles all applicable canonical fragments into one managed block in the effective global file because Codex does not automatically import arbitrary global Markdown fragments. It leaves an empty override untouched when a non-empty `AGENTS.md` is effective. It honours `CODEX_HOME` when that directory is inside the selected `--home`; an external location is deliberately rejected to preserve the installer's no-escape guarantee. It uses a catch-all entry in the selected Codex home's `hooks.json` so shell and supported structured calls reach one redacting engine. Core installation semantically merges JSON without rewriting `config.toml`; the separately opt-in terminal UX makes only a marker-owned, TOML-validated `tui.status_line` edit. Neither path changes approval, sandbox, network, or hooks feature settings. The generated `.rules` file covers only prefix forms that the rules engine can express reliably; the shared hook remains the broader high-confidence control.

Routing decision: the model map uses `gpt-5.6-luna`/`gpt-5.6-terra`/`gpt-5.6-sol` for economy/balanced/deep and writes those values only into custom-agent files. Read-only roles set `sandbox_mode = "read-only"`; writing roles inherit the parent's sandbox instead of silently broadening it. The installer does not edit `[agents]`, global concurrency, or the primary model in `config.toml`.

## Anthropic Claude Code

Documented behaviour:

- [Memory and rules](https://code.claude.com/docs/en/memory) document personal `~/.claude/rules/`, project `CLAUDE.md`, and `@path` imports. Claude Code reads `CLAUDE.md`, not `AGENTS.md`, so this repository's `CLAUDE.md` imports `@AGENTS.md`.
- [Skills](https://code.claude.com/docs/en/skills) document personal skills at `~/.claude/skills/<name>/SKILL.md`.
- [Hooks](https://code.claude.com/docs/en/hooks) document `PreToolUse`, `tool_name` and `tool_input`, Bash matching, and the nested `permissionDecision: deny` response. The older top-level shape is deprecated for this event.
- [Settings](https://code.claude.com/docs/en/settings) place user settings at `~/.claude/settings.json`; [permissions](https://code.claude.com/docs/en/permissions) remain independent and are not weakened by this installer.
- [Custom subagents](https://code.claude.com/docs/en/sub-agents) document personal Markdown agents at `~/.claude/agents/`, the `haiku`, `sonnet`, and `opus` aliases, `low`/`medium`/`high` effort, `permissionMode: plan`, and tool restrictions. The environment variable `CLAUDE_CODE_SUBAGENT_MODEL`, when set, has higher precedence than per-agent frontmatter.
- [Features overview](https://code.claude.com/docs/en/features-overview) distinguishes local Claude Code features and deployment surfaces; this repository does not claim local user files automatically govern every hosted experience.

Product limitations: personal skills are local Claude Code inputs and are not automatically available to remote Cowork or cloud sessions. Hooks cover Claude Code tool calls, not arbitrary user processes.

Routing limitations: organisation `availableModels` rules can substitute a permitted family version or fall back to the inherited model. Parent permission modes can take precedence over a subagent's mode. Model-family availability is therefore reported as unverified.

Repository decisions: behavioural fragments remain modular under `~/.claude/rules/`; the installer semantically merges one catch-all `PreToolUse` hook so supported shell and structured tools reach the redacting engine, preserves every unrelated key and hook, and backs up the existing settings file before its first mutation. The shared engine never returns an interactive `ask` decision.

Routing decision: economy/balanced/deep map to `haiku`/`sonnet`/`opus`. Generated read-only roles use plan mode and deny editing tools. The installer intentionally does not set `CLAUDE_CODE_SUBAGENT_MODEL` because doing so would override task-specific routing, and it does not change the main-session model.

## Cursor

Documented behaviour:

- [Rules](https://cursor.com/docs/rules.md) document Git-backed `.cursor/rules` and root or nested `AGENTS.md`, while global User Rules are defined through Customize. User Rules apply to Agent (Chat); the same page states they do not apply to Inline Edit and rules do not govern Cursor Tab or other AI features.
- [Skills](https://cursor.com/docs/skills.md) document the portable `SKILL.md` format and user discovery from `~/.agents/skills/` and `~/.cursor/skills/`, plus compatibility directories.
- [Hooks](https://cursor.com/docs/hooks.md) and [third-party hooks](https://cursor.com/docs/reference/third-party-hooks.md) document native user hooks at `~/.cursor/hooks.json`, regex tool matchers, `preToolUse` with shell tool name `Shell`, and compatibility with Claude's nested denial output. Cursor also documents native MCP hook surfaces, but payload/server identification and coverage have changed across releases.
- [Cursor CLI permissions](https://cursor.com/docs/cli/reference/permissions.md) document tokens in `~/.cursor/cli-config.json` or project `.cursor/cli.json`, with deny taking precedence over allow.
- [Subagents](https://cursor.com/docs/subagents.md) document personal Markdown agents at `~/.cursor/agents/`, `model: inherit` or an explicit model ID, model parameters such as `effort`, and the `readonly` restriction. The page explicitly documents fallback when an organisation blocks the model, a plan lacks it, or legacy Max Mode requirements are unmet.

Product limitations: there is no documented global User Rules file for this installer to edit, and User Rules have narrower scope than native hooks and repository instructions. Cursor CLI permissions describe CLI behaviour and must not be presented as a universal Cursor IDE policy.

Routing limitations: available model IDs and parameters vary by plan, provider, and organisation. `readonly` constrains supported subagent writes but does not turn the routing layer into a workstation security boundary. Cursor can substitute a compatible model, so a configured explicit ID is not proof of runtime use.

Repository decisions: the installer writes only the documented native hook file and shared skill directory. It prints the exact manual User Rules step and copies to a supported clipboard only with explicit `--clipboard`. The CLI permissions JSON is recommendation-only and is never merged automatically.

Structured-enforcement limitation: the catch-all native hook allows the shared engine to inspect MCP calls when Cursor emits them through `preToolUse`. The engine accepts Cursor's `beforeMCPExecution` payload shape as well, but the installer avoids duplicate registration. When Cursor supplies only a generic tool name without an MCP server name or recognisable URL, provider-specific matching may have to fail open; platform RBAC and read-scoped OAuth remain stronger controls.

Routing decision: all Cursor tiers default to `inherit`, preserving the main session when availability is unknown. `--model-override cursor:TIER=ID` supports explicit provider or family IDs and encodes portable reasoning as a supported model parameter when the ID has no parameters already. Status reports configuration and fallback caveats without claiming availability.

## GitHub Copilot in Visual Studio Code

Documented stable behaviour:

- [Custom instructions](https://code.visualstudio.com/docs/agent-customization/custom-instructions) document user instruction files under `~/.copilot/instructions/`, `.instructions.md` frontmatter including `name`, `description`, and `applyTo`, and `applyTo: "**"` for always-applied instructions. The same page documents repository `AGENTS.md` and makes clear that custom instructions do not govern inline suggestions.
- [Agent Skills](https://code.visualstudio.com/docs/agent-customization/agent-skills) document shared personal discovery from `~/.agents/skills/`.
- [Custom agents](https://code.visualstudio.com/docs/agent-customization/custom-agents) document personal `~/.copilot/agents/*.agent.md`, tool declarations, and model inheritance when `model` is omitted.
- [Hooks](https://code.visualstudio.com/docs/agent-customization/hooks) document `~/.copilot/hooks/`, Claude-compatible `~/.claude/settings.json` discovery, `PreToolUse`, `runTerminalCommand`, and nested deterministic denial responses.

Preview/version-gated behaviour: hooks are Preview and an organisation can disable them. A configured hook file proves only that it exists; runtime activation is reported as unverified.

Repository decisions: this project writes one generated `workstation-guardrails.instructions.md` with documented frontmatter and no VS Code `settings.json` change. It writes one native hook only when no project-managed Claude hook exists. When Claude is managed, VS Code records `shared-claude`; when Claude is later removed, the installer creates the VS Code native hook before removing the shared registration. This avoids duplicate project-owned enforcement and duplicate one-use-waiver consumption. Routing emits native agents only after an explicit non-`none` profile, omits `model`, and uses read-only tool subsets for read-only roles. No selected model, extension configuration, or organisation setting is changed.

## GitHub Copilot in Visual Studio

Documented stable behaviour:

- [Copilot Chat context](https://learn.microsoft.com/en-us/visualstudio/ide/copilot-chat-context?view=visualstudio) documents `%USERPROFILE%/copilot-instructions.md`, repository `.github/copilot-instructions.md`, and path-specific `.github/instructions/**/*.instructions.md`.
- [Specialized agents](https://learn.microsoft.com/en-us/visualstudio/ide/copilot-specialized-agents?view=visualstudio) documents personal `%USERPROFILE%\.github\agents` files and requires Visual Studio 18.4+.
- [Agent Skills](https://learn.microsoft.com/en-us/visualstudio/ide/copilot-agent-skills?view=visualstudio) documents Agent Skills from Visual Studio 18.5+ and shared personal `~/.agents/skills/` discovery.
- [Agent mode](https://learn.microsoft.com/en-us/visualstudio/ide/copilot-agent-mode?view=visualstudio) documents native approval/permission controls, which are deliberately not managed here.

Product limitations: Visual Studio does not support Copilot hooks or subagents. Its custom agents are user-selectable roles, not automatic routing workers. Version discovery can be unavailable, so status distinguishes files installed from actual IDE compatibility and reports `version-unverified` rather than inventing a result.

Repository decisions: the installer manages only a delimited block in the documented user instruction file, copies shared skills, and writes agents only when routing is explicit. It does not touch registry data, private settings storage, authentication, extension state, model selection, terminal profiles, or native tool approvals. An explicit real installation is rejected by the CLI outside Windows; build and validation remain cross-platform.

## JetBrains AI Assistant and GitHub Copilot for JetBrains

Documented stable behaviour:

- [Prompt Library](https://www.jetbrains.com/help/ai-assistant/prompt-library.html) documents the manual **Settings > Tools > AI Assistant > Prompt Library > General > Chat Instructions** surface; no documented global file is generated for native Chat.
- [Project rules](https://www.jetbrains.com/help/ai-assistant/configure-project-rules.html) document `.aiassistant/rules/*.md` and UI-selected rule type; this project therefore requires manual confirmation that an exported rule is `Always`.
- [Agent behaviour](https://www.jetbrains.com/help/ai-assistant/configure-agent-behavior.html) and [agents](https://www.jetbrains.com/help/ai-assistant/agents.html) document Junie/Codex use of `AGENTS.md`, Claude Agent use of `CLAUDE.md`, and different behaviour for hosted agents.
- [Agent Skills](https://www.jetbrains.com/help/ai-assistant/agent-skills.html) documents **Settings > Tools > AI Assistant > Skills > Manage Skill Directories**. Current tables list Codex and Claude Agent support, but not Junie or Copilot.
- GitHub's [customization cheat sheet](https://docs.github.com/en/copilot/reference/customization-cheat-sheet) marks Copilot custom instructions, custom agents, subagents, and skills in JetBrains as Preview and hooks as unsupported. [JetBrains Copilot instructions](https://docs.github.com/en/copilot/how-tos/configure-custom-instructions-in-your-ide/add-repository-instructions-in-your-ide) document `~/.config/github-copilot/intellij/global-copilot-instructions.md` on macOS and `%LOCALAPPDATA%\github-copilot\intellij\global-copilot-instructions.md` on Windows; no Linux global path is documented.

Product limitations: native Chat rules, hosted agents, and the Copilot plugin are separate surfaces. A repository instruction file does not prove a selected agent loaded it. Global Codex/Claude hooks must not be assumed active inside JetBrains-hosted agents. `.aiignore`, operation modes, approvals, and MCP/brave-mode behaviour vary by agent and remain user or administrator controls.

Repository decisions: installation records manual Chat Instructions and global skill-directory registration as outstanding steps. It never edits `.idea`, settings databases, launchers, operation modes, MCP configuration, or a plugin. A project rule is exported only by the explicit `jetbrains export-project-rules --repo` command and refuses a repository containing `.noai`. On macOS/Windows, Copilot global instructions are installed only beneath the selected home; Linux reports a manual Customizations step. Routing produces a manual Preview bundle rather than claiming activation. No JetBrains hook is generated.

## Usage and cost interpretation

The products expose different accounting models. API-token billing, included subscription use, product credits, third-party provider pools, and an estimate based on public list prices are not equivalent. Lower latency is not the same as lower cost, and extra subagent contexts can increase both tokens and elapsed time.

- OpenAI's [Codex pricing guidance](https://developers.openai.com/codex/pricing) distinguishes included ChatGPT plan usage and credits from API-key token billing.
- Claude Code documents session and plan information through [`/usage`](https://code.claude.com/docs/en/costs); its displayed currency value is a local estimate, while the Console or third-party provider is authoritative for billing.
- Cursor documents plan inclusion and token breakdowns in its [models and pricing guidance](https://cursor.com/docs/models-and-pricing.md); plan and organisation controls also affect model availability.

The repository's metrics schema is future-facing and content-free. It installs no collector and promises no exact currency saving.

## Polyglot and infrastructure compatibility

Language packs describe repository conventions rather than fixed tool releases. Maven/Gradle wrappers, `global.json`, Python manager locks, and Node `packageManager` declarations remain authoritative. Detection does not install a JDK, .NET SDK, Python environment manager, Node runtime, package manager, Ansible, kubectl, Helm, Kustomize, Terraform, OpenTofu, Terragrunt, spacectl, or OPA.

Ansible behaviour was verified from official documentation on 2026-08-08. The [configuration reference](https://docs.ansible.com/projects/ansible/latest/reference_appendices/config.html) documents first-match `ansible.cfg` discovery and warns about configuration in world-writable directories. The [check and diff guide](https://docs.ansible.com/projects/ansible/latest/playbook_guide/playbooks_checkmode.html) describes check mode as a simulation, permits tasks to force `check_mode: false`, and warns that diff can expose sensitive information. The [inventory guide](https://docs.ansible.com/projects/ansible/latest/inventory_guide/intro_inventory.html) documents inventory variables and precedence, while the [Vault guide](https://docs.ansible.com/projects/ansible/latest/vault_guide/vault.html) states that Vault protects only data at rest. The [ansible-galaxy CLI reference](https://docs.ansible.com/projects/ansible/latest/cli/ansible-galaxy.html) documents collection publication, role import, and certificate-ignore options. The core CLI references define [`ansible-pull`](https://docs.ansible.com/projects/ansible/latest/cli/ansible-pull.html) as fetching and executing playbooks and [`ansible-console`](https://docs.ansible.com/projects/ansible/latest/cli/ansible-console.html) as a task-execution REPL.

Repository decisions: detection uses distinctive Ansible metadata and never generic YAML alone. `ansible-playbook --syntax-check` and documented list-only modes are local validation/observation, while playbook, ad hoc, pull, and console execution—including `--check`—is classified as remote mutation and requires the existing safety-profile decision. An exact `-i`/`--inventory`/`--inventory-file` value can map through `ansible_inventories`; multiple, default, and unmapped inventories remain protected. Vault view/edit/decrypt is denied; broad inventory and active-configuration rendering warns; Galaxy publication, hosted mutation, and certificate/signature bypass are denied; and pull cannot discard/purge its checkout or automatically accept a new source host key. The engine does not parse playbooks, Jinja, inventory plugins, module semantics, `ansible-runner`, or automation-controller APIs, and tests never contact managed hosts. Installed ansible-core, collection, plugin, and execution-environment versions remain authoritative.

Helm matching is designed for stable Helm 3/4 command forms but does not assume one installed major. Terraform/OpenTofu/Terragrunt plan and state formats are treated as sensitive and are not parsed as a universal compatibility interface. Kubernetes version skew and API availability must be checked with the repository/platform; unit tests never contact an API server.

Current Spacelift behaviour was verified from official documentation on 2026-08-08:

- [`spacectl`](https://docs.spacelift.io/concepts/spacectl) wraps the GraphQL API and includes stack deployment plus profile token export, so those surfaces are not classified as read-only.
- The current [Spacelift MCP](https://docs.spacelift.io/concepts/intelligence/spacelift-mcp) uses the unified `/mcp` endpoint and exposes `discover`, `query`, and `provider` with read scope, while `mutate` and the whole `intent` tool require write scope. The repository therefore denies every `mutate` and `intent` call, including `intent` read/status verbs, rather than treating a write-scoped tool as read-only from one argument. The former `/intent/mcp` endpoint passed its documented removal date on 1 August 2026 and is never generated. Older names such as `trigger_stack_run`, `confirm_stack_run`, `discard_stack_run`, and `local_preview` are retained only as defensive compatibility aliases, not represented as the current hosted tool contract.
- [MCP connection guidance](https://docs.spacelift.io/concepts/intelligence/spacelift-mcp/connecting) states that OAuth `mcp:read` is narrower than `mcp:write`, while spacectl-token authentication is not narrowed by those OAuth scopes. The repository never modifies MCP configuration or Spacelift profiles.
- [Policy contracts](https://docs.spacelift.io/concepts/policy) currently define approval `approve`/`reject`, plan `deny`/`warn`, and push `track`/`propose`/`ignore` decisions. The example policies follow those returns and use the official [approval](https://docs.spacelift.io/concepts/policy/approval-policy), [plan](https://docs.spacelift.io/concepts/policy/terraform-plan-policy), and [push](https://docs.spacelift.io/concepts/policy/push-policy) input families.
- The [deprecated-policy page](https://docs.spacelift.io/concepts/policy/deprecated) replaces Access Policies with Spaces/login policies and Initialization/Task Policies with Approval Policies. Its Access Policy end-of-life date (30 May 2026) has passed, although the same page still contains a stale “still functional” status line. This repository does not resolve that documentation inconsistency by guessing runtime availability: it generates no Access, Task, or Initialization policy.

Spacelift policy examples are configuration-driven and structural validation is always local. Semantic evaluation runs only when an existing `opa` executable is available; otherwise validation reports that it was not performed. Availability of a tool, API field, organisation feature, plan, space, label, stack, or permission is never inferred from checked-in configuration.

## v1.1 command and schema references

The v1.1 packs use stable command categories verified from official project/vendor references, but they do not pin or install the tools. Exact flags remain subject to the repository's required version and must be verified locally.

| Area | Official compatibility references | Repository limitation/design |
| --- | --- | --- |
| Containers/OCI | [Docker CLI](https://docs.docker.com/reference/cli/docker/), [Podman commands](https://docs.podman.io/en/latest/Commands.html), [Buildah](https://github.com/containers/buildah/tree/main/docs), [Skopeo](https://github.com/containers/skopeo/tree/main/docs), [nerdctl](https://github.com/containerd/nerdctl) | High-confidence host access, prune, credential, insecure transport, and publication cases only; no tool/scanner installation. |
| Azure | [Azure CLI reference](https://learn.microsoft.com/en-us/cli/azure/reference-index) | Subscription/tenant mappings are local and unknown targets are protected; no authentication, token validation, or remote call. |
| GitHub and Azure DevOps | [GitHub CLI manual](https://cli.github.com/manual/), [GitHub Actions security](https://docs.github.com/en/actions/security-for-github-actions/security-guides/security-hardening-for-github-actions), [Azure DevOps CLI](https://learn.microsoft.com/en-us/azure/devops/cli/) | Static YAML checks are text heuristics; branch protection, environment approval, and platform RBAC remain authoritative. |
| Databases/migrations | [PostgreSQL psql](https://www.postgresql.org/docs/current/app-psql.html), [SQL Server sqlcmd](https://learn.microsoft.com/en-us/sql/tools/sqlcmd/sqlcmd-utility), [MySQL client](https://dev.mysql.com/doc/refman/8.4/en/mysql.html), [EF Core migrations](https://learn.microsoft.com/en-us/ef/core/managing-schemas/migrations/), [Alembic](https://alembic.sqlalchemy.org/en/latest/), [Prisma migrations](https://www.prisma.io/docs/orm/prisma-migrate) | No SQL parser; only client/framework arguments and conservative high-confidence SQL patterns. |
| Observability | [Prometheus API](https://prometheus.io/docs/prometheus/latest/querying/api/), [Grafana HTTP API](https://grafana.com/docs/grafana/latest/developers/http_api/), [Datadog API](https://docs.datadoghq.com/api/latest/), [Splunk REST API](https://docs.splunk.com/Documentation/Splunk/latest/RESTREF/RESTprolog), [Elastic API](https://www.elastic.co/guide/en/elasticsearch/reference/current/rest-apis.html), [Azure Monitor CLI](https://learn.microsoft.com/en-us/cli/azure/monitor) | Generic read-oriented guidance and named high-confidence mutation tools; logs remain potentially sensitive. |
| Contracts | [OpenAPI](https://spec.openapis.org/oas/latest.html), [JSON Schema](https://json-schema.org/specification), [Protocol Buffers](https://protobuf.dev/programming-guides/proto3/), [GraphQL specification](https://spec.graphql.org/), [AsyncAPI](https://www.asyncapi.com/docs/reference/specification/latest), [Avro](https://avro.apache.org/docs/current/specification/) | Uses repository-native compilers/diff tools when present; standard-library validation is JSON/metadata only and never claims semantic compatibility. |
| Secrets/PKI | [Azure Key Vault CLI](https://learn.microsoft.com/en-us/cli/azure/keyvault), [Kubernetes Secrets](https://kubernetes.io/docs/concepts/configuration/secret/), [OpenSSL commands](https://docs.openssl.org/master/man1/) | Metadata may be safe; secret values, tokens, private keys, decrypted material, credential kubeconfigs, and keystore passwords are denied from agent output. |

## Cross-product hook contract

Codex, Claude Code, Cursor, and VS Code currently accept the nested `hookSpecificOutput` `PreToolUse` denial structure used by the engine (VS Code support is Preview). Allowed and unrecognised operations produce no approval object and exit successfully. Malformed or unsupported payloads fail open with a redacted stderr diagnostic; a recognised dangerous command or structured call returns a deterministic deny containing a stable identifier and operation class. Arguments are not echoed. Visual Studio and JetBrains have no hook output here because the documented integrations are unsupported. Product updates may change these formats, so run validation after upgrades and re-verify this dated document.
