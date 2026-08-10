# Threat model

## Evidence, task, and component boundaries

Policy evidence is metadata, not runtime authority. It is local, dated context that makes a rule's rationale reviewable; it does not fetch a source, validate a claim on the Internet, or permit automatic policy rewriting. The project intentionally has no runtime LLM judge: a model would add non-deterministic behaviour and potentially sensitive input without proving correctness.

Task contracts validate current contract continuity, available Git scope, declared limits, and fresh sufficient evidence—not business correctness, API compatibility, or the design of an external test suite. Generated changes remain in task scope. Recognised unsupported dependency manifests and relevant opaque nested repositories make assurance unavailable rather than silently passing. Imported SARIF, Cobertura, and JUnit reports are bounded local inputs. Their messages, source snippets, stack traces, system output, raw logs, prompts, commands, and secrets are neither displayed nor persisted. A safe halt preserves work and calls out unavailable, malformed, insufficient, stale, failed, conflicting, or state-mismatched evidence.

External skills, instruction files, agents, hooks, and MCP bundles are a local supply-chain boundary. Component inspection is static and does not execute, import, install, or fetch a component. A trusted digest is an operator-created local review record with expiry, not verified human identity, a publisher signature, organisation approval, or grant of runtime authority. Supported agent-issued trust commands are denied through deterministic hook paths, but a workstation owner or another local process with write access can change component files, state, or configuration. A clean inspection cannot prove safety.

External issues, comments, pull requests, PDFs, web pages, setup instructions, logs, analyzer messages, dependency documentation, and MCP output are evidence—not authority. They cannot independently authorise a dependency/registry change, setup script, guardrail or hook modification, weaker approval/sandbox/network control, credential access, remote mutation, publication, waiver, or trust record.

External technical-writing standards are evidence and guidance, not executable authority. A style rule cannot weaken deterministic security policy or authorize dependency installation, network expansion, secret access, or remote mutation. Externally supplied prose and user-supplied copies of a standard remain untrusted reference material; the technical-writing skill does not make them executable or trusted.

## Assets and goals

These guardrails aim to reduce accidental destructive actions initiated through supported agent shell tools, keep consistent engineering behaviour across products, preserve uncommitted work and unrelated configuration, and make policy changes reviewable in Git. The repository and installed configuration must never contain credentials.

The optional efficiency layer aims to reduce avoidable context, reasoning, and concurrency for bounded tasks. It is an optimisation hint, not an authorisation, isolation, quality, availability, billing, or security boundary.

Capability packs aim to preserve established language toolchains and reduce accidental remote or publication actions. Pack detection is advisory evidence, not proof of the repository's complete stack, a target's lifecycle, or permission to operate it.

## Trust boundaries

Markdown instructions influence agent behaviour but are not a security boundary. They can be misunderstood, overridden by higher-priority instructions, omitted by context limits, or ignored by a model.

Hooks constrain supported agent tool calls, not arbitrary processes running as the user. A command already running, an unsupported hosted tool, an alternate execution path, a manual terminal, or another application may bypass them. Blocked commands may still be run manually by the workstation owner outside the agent when appropriate.

A user or process with write access to the configuration, installed engine, command policy, interpreter, or state can bypass local guardrails. Product updates can change event names, payloads, tool coverage, trust behavior, configuration formats, or response semantics.

Local expiring waivers are files controlled by the workstation user. TTY confirmation, exact digests, expiry, target scope, and use counts reduce accidental reuse but are not cryptographic proof of independent human approval. An agent running with the same user authority may find another path around local controls; real privileged approval must come from platform RBAC or a workflow the agent cannot control.

Model names, routing fields, plan entitlements, organisation allowlists, fallback behaviour, reasoning controls, and subagent nesting can also change. A configured model may be unavailable or substituted. Lower-tier models can miss ambiguity or risk, and a model may fail to follow escalation instructions. High-risk work therefore requires deep-tier final judgement independently of economy evidence collection.

### Optional terminal UX

Claude Code status lines execute a local configured command only after workspace trust; a workstation owner or process able to modify local settings or the immutable runtime can change that command. The managed renderer is fixed, local, non-networked, and reads one documented session payload only in memory plus bounded content-free caches. Codex receives only a marker-owned, complete-TOML-validated `tui.status_line` edit; it never receives custom rendered text. The renderer sanitises control sequences before display and does not persist prompts, source, command arguments, credentials, or vendor session JSON. A status line is not a security boundary.

Guardrail counters cover only warning and denial events that supported hooks actually record, not every allowed operation or a reliable vendor session. Cost is a vendor-provided session estimate where Claude supplies it, never an invoice. Complexity signals are deterministic change-review prompts that can miss semantic complexity and can flag legitimate broad work. Terminal width, Unicode, ANSI, product fields, and formats vary across versions. Codex and Cursor native/manual steps cannot be proven active by this installer, and products without deterministic hooks must not be represented as fully covered.

Command matching is intentionally conservative and cannot fully understand every shell construct. The engine does not expand variables or evaluate aliases and cannot infer the effect of arbitrary scripts. It fails open for malformed and unsupported input to avoid disabling all agent operation, while recognised high-confidence dangerous operations fail closed with a deterministic denial. False negatives remain possible; widening patterns without safe counterexamples creates harmful false positives.

Structured-tool matching is also bounded. Product payloads can omit or rename provider information, servers can change tool schemas, GraphQL documents can be supplied indirectly, and one generic MCP tool can dispatch many actions. Recognised dangerous calls fail closed, but unknown tools fail open unless a strict allowlist was explicitly configured. The engine never logs complete arguments, yet upstream product logs and remote providers may retain data independently.

Lifecycle mapping is workstation-local configuration. `dev`, `tst`, `int`, and `prd` classifications are distinct from actual Ansible inventories, Kubernetes contexts, namespaces, Spacelift stacks, Terraform workspaces, cloud accounts, and deployment environments. Unknown targets are protected, and a benign-looking name is never proof that a target is non-production. A stale or incorrect mapping remains a risk.

Codex `.rules` entries apply to commands requested outside its sandbox and are an experimental defence-in-depth layer. They do not replace the shared hook and must not be described as a complete workstation security boundary. Cursor CLI permission tokens apply to the CLI configuration, not every Cursor IDE execution path. Cursor User Rules apply only to documented Agent Chat scope.

VS Code hook configuration is not proof that an organisation enables hooks or that a request passed through the hook. VS Code hooks are Preview and run with the permissions of the VS Code process. VS Code instructions do not govern inline completions. Visual Studio has no hook supplied by this project, so its behavioural instructions and native tool approvals are not deterministic command enforcement.

JetBrains AI Assistant native Chat, hosted coding agents, and the GitHub Copilot plugin have different instruction, skill, approval, and ignore-file behaviour. This project has no JetBrains hook. An integrated or third-party agent may not respect JetBrains `.aiignore`; enabling MCP tool exposure or a brave/automatic operation mode can create paths outside this installer's assumptions. Native JetBrains modes, approvals, MCP settings, and plugin configuration remain user or administrator controls. OS least privilege, branch protection, cloud IAM, platform RBAC, and production change controls remain authoritative.

## Out of scope

The policy engine is not a replacement for least privilege, sandboxing, source-control protection, code review, protected branches, cloud IAM, secret management, network controls, database permissions, release approvals, or production change controls. It is not malware protection, a data-loss-prevention system, a complete shell parser, or central enterprise policy enforcement.

The routing layer does not guarantee savings, latency, model availability, correctness, or complete enforcement of concurrency. Subagents create separate contexts and can increase tokens or elapsed time. Subscription allowances, API billing, product credits, and third-party provider pricing are not interchangeable. The future metrics schema is not an invoice, and this repository does not collect telemetry.

Language-pack controls do not prevent every package manager, wrapper task, custom release script, build plugin, database migrator, or remote execution path. Infrastructure support does not automatically cover every Ansible plugin or module, cloud CLI, Kubernetes plugin, GitOps controller, Helm plugin, Terraform wrapper, provider, or MCP server. Ansible check mode can be bypassed by task configuration and inventory/diff output can expose sensitive variables. Unknown tools and custom executable content must be assessed explicitly.

Local hooks cannot replace Kubernetes admission/RBAC, Spacelift policies/RBAC, cloud IAM, protected Terraform backends, package-registry permissions, human release approval, or production change controls. Production-capable credentials should not be exposed to coding agents: possession can enable paths outside the hook or allow sensitive reads before a policy can classify them. Package publication therefore remains human-controlled.

Output optimisation must never hide exit status or useful failures, alter a command, or leak sensitive content. No output-filtering hook is currently installed. The metrics schema deliberately excludes prompts, source code, command arguments, and secret values.

Static scan findings are conservative indicators, not full semantic parsing of YAML, Rego, shell, SQL, OpenAPI, GraphQL, Protobuf, CI expressions, or templating. A clean scan is not proof of safety. Enterprise output and Spacelift policies are examples only; they have no authority until separately reviewed and deployed by an administrator.

## Operational mitigations

- Keep configuration and the selected home writable only by the intended user.
- Review installed hooks and product trust prompts.
- Preserve vendor sandboxing and approval settings; this installer does not weaken or silently modify them.
- Validate after product updates and review the dated compatibility record.
- Revalidate model maps and native agent schemas after product updates; treat status availability as unverified unless the product itself confirms access.
- Keep delegated tasks bounded, cap concurrency, stop unused agents, and escalate instead of repeating cheap failed attempts.
- Test new rules with positive and negative examples, especially commands that print or search for dangerous text.
- Use temporary homes for development and tests, and inspect backups before any forced replacement.
- Report suspected secret exposure without copying the value into issues, logs, tests, or this repository.
- Grant MCP read scopes only when possible; for current Spacelift MCP prefer `mcp:read` without `mcp:write`, and treat bearer-token sessions as potentially broader.
- Keep target mappings local, credential-free, reviewed, and separate from platform-owned lifecycle labels and real deployment identifiers.
- Require privileged approval from platform RBAC, a human-controlled workflow, or another authority outside the agent. Never use a self-issued approval token.
