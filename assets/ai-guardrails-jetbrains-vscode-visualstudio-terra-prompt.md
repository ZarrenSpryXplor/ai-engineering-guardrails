# Terra implementation prompt: JetBrains, VS Code, and Visual Studio adapters

You are working at the root of the existing repository:

    ai-engineering-guardrails

Implement one focused compatibility milestone that adds first-class support for:

1. JetBrains IDEs:
   - JetBrains AI Assistant native Chat mode
   - coding agents hosted by JetBrains AI Assistant, including Junie, Codex,
     Claude Agent, and GitHub Copilot where supported
   - the standalone GitHub Copilot plugin for JetBrains IDEs
2. GitHub Copilot in Visual Studio Code
3. GitHub Copilot in Visual Studio

This is an incremental extension of the current installable application.

The repository already has:

- the `ai-engineering-guardrails` Python distribution;
- the `ai_engineering_guardrails` Python package;
- the `ai-guardrails` console command;
- package-local immutable resources;
- deterministic generated adapters;
- installation state and shared skill ownership;
- a content-addressed hook runtime;
- local policy overlays;
- routing profiles;
- Codex, Claude Code, and Cursor adapters.

Reuse that implementation. Do not recreate any of it.

Do not commit, tag, push, publish, create a release, install an IDE extension,
authenticate to GitHub or JetBrains, contact cloud services, or modify my real
workstation configuration while developing or testing.

Run all installation and mutation tests against temporary homes and temporary
repositories.

======================================================================
1. NON-NEGOTIABLE SIMPLICITY CONSTRAINTS
======================================================================

Apply KISS, DRY, YAGNI, and the Rule of Three throughout this task.

KISS:

- Add three product adapters to the current application.
- Preserve the current CLI, packaging, resource, build, installation, state,
  routing, and enforcement architecture.
- Prefer explicit product-specific functions over a speculative general IDE
  framework.
- Prefer a small validated capability mapping over inheritance or a class hierarchy.
- Prefer generated files and documented manual steps over reverse-engineering IDE
  settings databases.
- Prefer an honest unsupported capability over a fake or fragile implementation.
- Keep default installation and status output understandable to an ordinary user.

DRY:

- Canonical behavioural policy remains in the existing policy source.
- Canonical skills remain in the existing skills source.
- Canonical routing roles remain in the existing routing source.
- Deterministic command and structured-tool rules remain in the existing
  enforcement policy.
- Product adapters render those canonical sources into native formats.
- Do not create manually maintained copies of the same policy for the three IDEs.
- Do not create another hook engine.
- Do not create another installer.
- Do not create another state file or routing system.

DRY applies to authoritative knowledge, not every repeated line:

- two small product adapters may contain similar explicit code where a shared
  abstraction would make either adapter harder to understand;
- do not generalise after observing only two similar cases;
- use the Rule of Three;
- prefer five obvious lines over a clever registry framework.

YAGNI:

- Do not create a VS Code extension.
- Do not create a Visual Studio extension.
- Do not create a JetBrains plugin.
- Do not add a daemon, background updater, web service, TUI, GUI, or remote policy
  service.
- Do not add a generic "IDE SDK".
- Do not add a plugin system.
- Do not add dependency injection.
- Do not modify undocumented settings storage.
- Do not add another implementation language.
- Do not add runtime dependencies.
- Do not add telemetry.
- Do not automate GitHub or JetBrains authentication.
- Do not install or update Copilot, AI Assistant, Junie, Codex, or Claude.
- Do not change the user's selected model, reasoning level, approval mode,
  operation mode, sandbox, network access, or MCP configuration.
- Do not add support for unrelated Copilot surfaces such as Eclipse, Xcode,
  GitHub.com, or Copilot CLI as a side effect.

Implementation constraints:

- Keep all executable application logic in Python 3.11+.
- Continue to use the Python standard library only at runtime.
- Keep `argparse`.
- Use the existing package-resource abstraction.
- Use the existing atomic-write, backup, managed-block, state, and collision
  semantics.
- Work serially.
- Do not spawn implementation subagents or parallel writing agents.
- Preserve every pre-existing uncommitted change.

======================================================================
2. INSPECT THE CURRENT REPOSITORY BEFORE EDITING
======================================================================

Before changing anything:

1. Run:

       git status --short

2. Read:

   - AGENTS.md
   - CLAUDE.md
   - README.md
   - pyproject.toml
   - docs/architecture.md
   - docs/compatibility.md
   - docs/threat-model.md
   - docs/user-guide.md
   - the complete current CLI
   - product constants and validation
   - deterministic build/rendering code
   - installation, update, status, doctor, effective, and uninstall code
   - product detection code
   - state schema and shared-path ownership code
   - hook-runtime generation and enforcement input normalisation
   - routing generation and model maps
   - package resources and generated output layout
   - all existing product, packaging, installation, routing, and hook tests
   - current CI workflows

3. Identify every assumption that the supported product set is exactly:

       codex
       claude
       cursor

4. Identify every loop that expects:

   - one model map per product;
   - one rendered instruction artifact per product;
   - one installation destination per product;
   - one hook mechanism per product;
   - one routing-agent format per product;
   - deterministic enforcement to be available for every product.

5. Identify shared managed paths, especially:

       ~/.agents/skills
       ~/.claude/rules
       ~/.claude/settings.json
       ~/.ai-guardrails/runtime
       ~/.ai-guardrails/state.json

6. Inspect the current state format and migration mechanism before extending it.

7. Produce a concise internal gap map before editing:

   - canonical product additions;
   - generated outputs;
   - installation destinations;
   - manual steps;
   - hook support;
   - routing support;
   - state changes;
   - tests and documentation.

Do not ask for confirmation because the change touches several modules.

Do not replace functioning code merely because you would have designed it
differently.

======================================================================
3. VERIFY CURRENT OFFICIAL PRODUCT BEHAVIOUR
======================================================================

Before implementation, verify current behaviour using only official product
documentation.

Use at least these sources.

Visual Studio Code:

https://code.visualstudio.com/docs/agent-customization/custom-instructions
https://code.visualstudio.com/docs/agent-customization/agent-skills
https://code.visualstudio.com/docs/agent-customization/custom-agents
https://code.visualstudio.com/docs/agent-customization/hooks

Visual Studio:

https://learn.microsoft.com/en-us/visualstudio/ide/copilot-chat-context?view=visualstudio
https://learn.microsoft.com/en-us/visualstudio/ide/copilot-agent-mode?view=visualstudio
https://learn.microsoft.com/en-us/visualstudio/ide/copilot-specialized-agents?view=visualstudio
https://learn.microsoft.com/en-us/visualstudio/ide/copilot-agent-skills?view=visualstudio

JetBrains AI Assistant:

https://www.jetbrains.com/help/ai-assistant/configure-agent-behavior.html
https://www.jetbrains.com/help/ai-assistant/configure-project-rules.html
https://www.jetbrains.com/help/ai-assistant/prompt-library.html
https://www.jetbrains.com/help/ai-assistant/agent-skills.html
https://www.jetbrains.com/help/ai-assistant/agents.html
https://www.jetbrains.com/help/ai-assistant/codex-agent.html
https://www.jetbrains.com/help/ai-assistant/claude-agent.html
https://www.jetbrains.com/help/ai-assistant/copilot-agent.html
https://www.jetbrains.com/help/ai-assistant/junie-agent.html
https://www.jetbrains.com/help/ai-assistant/mcp.html

GitHub Copilot compatibility and JetBrains plugin behaviour:

https://docs.github.com/en/copilot/reference/customization-cheat-sheet
https://docs.github.com/en/copilot/reference/custom-instructions-support
https://docs.github.com/en/copilot/how-tos/configure-custom-instructions-in-your-ide/add-repository-instructions-in-your-ide
https://docs.github.com/en/copilot/reference/custom-agents-configuration

Record the verification date and exact supported behaviour in
`docs/compatibility.md`.

Distinguish:

- documented stable behaviour;
- Preview behaviour;
- version-gated behaviour;
- manual-only integration;
- behaviour that cannot be verified from files alone;
- product limitations;
- design decisions made by this repository.

If current official documentation differs from the requirements below, implement
the current documented behaviour and explain the difference. Do not preserve a
stale assumption merely because it appears in this prompt.

Known constraints to preserve unless current official documentation explicitly
supersedes them:

Visual Studio Code:

- User instructions can be stored under `~/.copilot/instructions`.
- User skills can be stored under `~/.agents/skills`.
- User custom agents can be stored under `~/.copilot/agents`.
- User hooks can be stored under `~/.copilot/hooks`.
- `PreToolUse` hooks are supported, but hooks are currently Preview.
- An organisation may disable hooks.
- VS Code also discovers Claude-compatible instruction and hook locations.
- Repository `AGENTS.md` is supported for Chat/Agent requests.
- Custom instructions do not govern inline suggestions as the user types.

Visual Studio:

- User-level instructions are stored in
  `%USERPROFILE%/copilot-instructions.md`.
- Repository instructions use `.github/copilot-instructions.md`.
- Path-specific instructions use `.github/instructions/**/*.instructions.md`.
- Custom agents require the currently documented minimum Visual Studio version.
- Personal custom agents use `%USERPROFILE%\.github\agents` by default.
- Agent Skills require the currently documented minimum Visual Studio version.
- Personal skills can use `~/.agents/skills`.
- Visual Studio does not support Copilot hooks.
- Visual Studio does not support Copilot subagents.
- Terminal commands run with the permissions of the Visual Studio process.

JetBrains:

- Native JetBrains AI Assistant Chat uses project rules under
  `.aiassistant/rules/*.md`.
- The JetBrains AI Assistant `Chat Instructions` prompt is configured through the
  Prompt Library UI and is added to new native Chat conversations.
- Do not assume a documented global Chat Instructions file exists.
- JetBrains coding agents automatically detect their supported repository
  instruction file:
  - Junie: `AGENTS.md`
  - Codex: `AGENTS.md`
  - Claude Agent: `CLAUDE.md`
  - integrated GitHub Copilot: currently documented supported instruction files
- JetBrains AI Assistant supports registration of local skill directories through
  its Skills settings.
- Do not assume that all JetBrains agents support skills equally.
- Do not assume that a Codex or Claude hook installed outside JetBrains is active
  inside the JetBrains-hosted agent unless current official documentation proves it.
- GitHub Copilot custom instructions, custom agents, subagents, and skills in
  JetBrains are currently Preview according to the GitHub compatibility matrix.
- GitHub Copilot hooks are not supported in JetBrains IDEs.
- The GitHub Copilot plugin documents a global instructions file on macOS and
  Windows:
  - macOS:
    `~/.config/github-copilot/intellij/global-copilot-instructions.md`
  - Windows:
    `%LOCALAPPDATA%\github-copilot\intellij\global-copilot-instructions.md`
- Do not invent a Linux global path when current documentation does not provide one.
- Native JetBrains operation modes, approvals, MCP exposure, and "brave mode" are
  user/administrator controls and must not be silently changed.

======================================================================
4. PRODUCT IDENTIFIERS AND CAPABILITY MODEL
======================================================================

Add these product identifiers:

    vscode
    visualstudio
    jetbrains

The full supported product set becomes:

    codex
    claude
    cursor
    vscode
    visualstudio
    jetbrains

Use these human-readable labels:

    vscode       GitHub Copilot in Visual Studio Code
    visualstudio GitHub Copilot in Visual Studio
    jetbrains    JetBrains AI Assistant and GitHub Copilot for JetBrains

Do not use a single ambiguous product identifier named `copilot`.

Extend product selection consistently across:

- build;
- validate;
- install;
- update;
- status;
- doctor;
- effective;
- diff-installed;
- receipt;
- policy applicability;
- explicit `--product`;
- no-argument detection;
- `--product all`;
- state;
- routing validation;
- generated output;
- documentation.

Introduce a small explicit product-capability mapping.

It may be a validated dictionary or similarly simple structure. Do not create a
class hierarchy or plugin interface.

Represent at least:

- automatic user instruction installation;
- repository instruction support;
- shared skill support;
- custom agent support;
- subagent support;
- deterministic hook support;
- hook maturity: stable, preview, or unsupported;
- version requirements;
- manual steps;
- platform restrictions;
- model availability verification.

Expected posture:

vscode:

- user instructions: supported;
- repository instructions: supported;
- skills: supported;
- custom agents: supported;
- subagents: supported;
- deterministic hook: Preview;
- inline suggestion coverage: unsupported.

visualstudio:

- user instructions: supported;
- repository instructions: supported;
- skills: version-gated;
- custom agents: version-gated;
- subagents: unsupported;
- deterministic hook: unsupported;
- native tool approvals: supported but unmanaged.

jetbrains:

- JetBrains AI Assistant native global Chat Instructions:
  manual UI step;
- JetBrains AI Assistant project rules:
  supported as an explicit repository export;
- repository agent instructions:
  supported by selected agents according to each agent;
- shared skill directory:
  manual registration for JetBrains AI Assistant;
- GitHub Copilot global instructions:
  auto-install only where a documented OS path is available;
- GitHub Copilot custom agents/subagents/skills:
  Preview and manual unless a current stable documented personal path exists;
- deterministic hook:
  unsupported as a JetBrains-native capability;
- native agent approvals and operation modes:
  supported but unmanaged.

Do not let the capability mapping imply that a file existing on disk proves that
an IDE, extension, organisation policy, or agent actually loaded it.

======================================================================
5. SHARED OUTPUT AND INSTALLATION PRINCIPLES
======================================================================

All generated behavioural instructions must come from the canonical policy.

Keep always-loaded instructions concise:

- KISS, DRY, YAGNI, and the Rule of Three;
- understand before changing;
- minimal correct scope;
- preserve architecture and uncommitted work;
- Git safety;
- secrets and security;
- dependency restraint;
- testing and verification;
- accurate completion reporting.

Do not concatenate all language and infrastructure pack content into global
instruction files.

Detailed language, tool, and infrastructure procedures remain skills.

All generated outputs must:

- contain an appropriate generated warning;
- identify canonical source;
- use stable ordering;
- contain no timestamp;
- contain no machine-specific path;
- end with exactly one newline;
- be deterministic;
- be validated;
- remain within configured instruction-size limits.

All installations must:

- use the current selected-home protection;
- refuse symlink traversal;
- use atomic writes;
- back up pre-existing content before the first mutation;
- preserve unrelated content;
- preserve unmanaged collisions by default;
- be idempotent;
- support dry-run;
- use state ownership;
- remove only managed content;
- preserve locally modified managed content unless `--force` is explicit.

Do not write into site-packages or package resources.

Do not point live hooks back to the Git clone.

======================================================================
6. VISUAL STUDIO CODE ADAPTER
======================================================================

----------------------------------------------------------------------
6.1 Generated user instructions
----------------------------------------------------------------------

Generate:

    dist/vscode/instructions/workstation-guardrails.instructions.md

Install at:

    ~/.copilot/instructions/workstation-guardrails.instructions.md

Use the current documented `.instructions.md` format.

The YAML frontmatter must be valid and precede the generated warning.

Use an always-on scope, currently expected to be:

    ---
    name: Workstation AI Guardrails
    description: Workstation-wide engineering and safety guidance
    applyTo: "**"
    ---

Verify the exact current schema before implementation.

The body must:

- be generated from the canonical global policy;
- remain concise;
- not include all pack content;
- not duplicate detailed skills;
- state that deterministic denials are separate from behavioural guidance.

Do not modify:

- VS Code `settings.json`;
- profile databases;
- Settings Sync;
- GitHub sign-in;
- Copilot extension configuration;
- model selection;
- organisation policy.

Document and report:

- instructions apply to Chat and Agent requests;
- instructions do not govern inline suggestions while typing;
- the user or organisation may disable instruction-file discovery;
- repository instructions may also apply;
- installation proves the file exists, not that a particular request included it.

----------------------------------------------------------------------
6.2 VS Code PreToolUse hook
----------------------------------------------------------------------

Generate a native user hook file:

    dist/vscode/hooks/workstation-guardrails.json

Install at:

    ~/.copilot/hooks/workstation-guardrails.json

Use the current documented VS Code hook schema.

Register only the existing shared `PreToolUse` runtime.

Do not add PostToolUse formatters, test hooks, prompt logging, source logging, or
automatic mutations.

The installed hook must invoke the current immutable runtime under:

    ~/.ai-guardrails/runtime/<digest>/

It must not refer to the repository.

Extend the shared hook input normalisation only as required for documented VS Code
payloads.

Support at least:

    {
      "hook_event_name": "PreToolUse",
      "tool_name": "runTerminalCommand",
      "tool_input": {
        "command": "git reset --hard"
      }
    }

Also support:

- documented snake_case envelope fields;
- camelCase fields inside `tool_input`;
- a command represented as a string or argument list where documented;
- documented file-editing tool names needed for protected-path rules;
- structured and MCP-style tool names already supported by the common engine.

For a high-confidence dangerous request, return the documented deterministic deny
shape.

For a safe or unrecognised request:

- preserve the existing common no-decision/fail-open semantics where compatible;
- do not emit a broad unconditional allow that could weaken another hook;
- do not execute the requested command;
- do not log arguments.

Do not emit `ask` from the common hook engine.

Status must show:

    Hook configuration: installed
    Hook maturity: Preview
    Runtime activation: unverified
    Organisation may disable hooks: yes

Do not claim deterministic VS Code enforcement merely because the JSON file exists.

----------------------------------------------------------------------
6.3 Avoid duplicate hook execution through Claude compatibility
----------------------------------------------------------------------

VS Code can discover user hooks from both:

    ~/.copilot/hooks
    ~/.claude/settings.json

The project already manages a Claude `PreToolUse` hook.

Prevent the same project-owned runtime from being registered twice for VS Code.

Implement the smallest safe ownership rule:

- VS Code user instructions are always installed in the native VS Code location.
  Do not build instruction deduplication logic in this milestone.
- Hook registration may use one of:
  - `native-vscode`
  - `shared-claude`
- If a project-managed Claude hook already exists and is compatible with VS Code,
  prefer `shared-claude` rather than adding the native hook.
- If no managed Claude hook exists, install the native VS Code hook.
- If VS Code is installed first and Claude is installed later, reconcile to one
  project-owned registration without a window where no hook exists.
- If Claude is uninstalled while VS Code remains managed, install the native VS Code
  hook before removing the shared Claude registration.
- If VS Code is uninstalled while Claude remains managed, preserve Claude.
- Never edit or delete an unmanaged Claude hook.
- Report a possible duplicate warning when an unmanaged compatible hook may also be
  loaded.
- Ensure a one-use waiver cannot be consumed twice by duplicate project-owned hook
  invocations.

Record the selected hook integration mode in non-sensitive state.

Do not construct a general dependency graph. Reuse the current state and managed
path ownership mechanisms.

----------------------------------------------------------------------
6.4 VS Code skills
----------------------------------------------------------------------

Use the existing canonical skill source.

Install personal skills at the existing shared location:

    ~/.agents/skills/

Do not duplicate them under `~/.copilot/skills`.

Shared ownership requirements:

- a skill already managed for Codex, Cursor, Visual Studio, or another product is
  not an unmanaged collision;
- uninstalling VS Code must not remove a skill still required by another managed
  product;
- unmanaged collisions remain protected;
- `--force` keeps current backup semantics.

----------------------------------------------------------------------
6.5 VS Code custom agents and routing
----------------------------------------------------------------------

Only when the user explicitly selects a non-`none` routing profile, generate native
VS Code custom agents from the existing canonical routing roles.

Generate:

    dist/vscode/agents/*.agent.md

Install at:

    ~/.copilot/agents/

Use current documented `.agent.md` frontmatter and tool names.

Do not change the user's main Chat model.

Add a VS Code model map.

Default every tier to inherited model selection unless current documentation
provides a stable portable model identifier that is valid across user plans.

Where native inheritance is represented by omitting `model`, omit it rather than
writing a fake identifier.

Preserve:

- economy roles are read-only;
- high-risk tasks never route exclusively to economy;
- maximum two read-only subagents under the balanced profile;
- one writing agent maximum;
- no parallel writing agents;
- explicit escalation;
- no guaranteed currency saving claim.

Status must distinguish:

- generated custom agent;
- installed custom agent;
- selected model inherited;
- model availability unverified;
- automatic subagents supported;
- routing profile disabled by default.

======================================================================
7. VISUAL STUDIO ADAPTER
======================================================================

----------------------------------------------------------------------
7.1 User-level instructions
----------------------------------------------------------------------

Generate:

    dist/visualstudio/copilot-instructions.md

Install as a managed block in:

    ~/copilot-instructions.md

On Windows, this is:

    %USERPROFILE%\copilot-instructions.md

Use the existing managed block delimiters:

    <!-- BEGIN WORKSTATION AI GUARDRAILS -->
    ...
    <!-- END WORKSTATION AI GUARDRAILS -->

Preserve all content outside the managed block.

Back up a pre-existing file before first mutation.

Do not modify:

- Visual Studio registry data;
- private settings databases;
- Tools > Options;
- GitHub authentication;
- extension installation;
- Copilot feature flags;
- model choice;
- tool approvals.

Status must explain that repository instructions additionally use:

    .github/copilot-instructions.md
    .github/instructions/**/*.instructions.md

Do not claim that Visual Studio Copilot Chat consumes repository `AGENTS.md` unless
current official documentation now explicitly confirms it.

----------------------------------------------------------------------
7.2 Visual Studio skills
----------------------------------------------------------------------

Use the shared personal skill location:

    ~/.agents/skills/

Do not create a duplicate under `~/.copilot/skills`.

Document and report the current minimum Visual Studio version for Agent Skills.

Status must distinguish:

- skills installed on disk;
- IDE version verified compatible;
- IDE version known too old;
- IDE version unverified;
- activation not proven.

----------------------------------------------------------------------
7.3 Visual Studio custom agents and routing
----------------------------------------------------------------------

Current official documentation provides a user-level custom agent location:

    ~/.github/agents/

On Windows, this is:

    %USERPROFILE%\.github\agents

When a non-`none` routing profile is explicitly selected and the current Visual
Studio version is compatible, generate and install custom agents from the canonical
roles.

Generate:

    dist/visualstudio/agents/*.agent.md

Install at:

    ~/.github/agents/

Use current Visual Studio `.agent.md` format and Visual Studio-specific tool names.

Omit `model` by default so the model picker remains authoritative.

Do not claim automatic subagent routing.

Visual Studio custom agents are user-selectable roles. They are not subagents and
must be reported as such.

If automatic version discovery is unavailable:

- generated artifacts may still be built and validated;
- an explicit real installation may install them only with a clear compatibility
  warning and state of `version-unverified`;
- no-argument detection must not claim compatibility.

If integrating all canonical roles requires unsupported tools, render the smallest
valid subset and document the omission. Do not invent tool names.

----------------------------------------------------------------------
7.4 No Visual Studio hook
----------------------------------------------------------------------

Do not generate or install a Visual Studio hook.

Do not simulate a hook by:

- wrapping `devenv.exe`;
- replacing `cmd.exe`, PowerShell, MSBuild, NuGet, or `dotnet`;
- installing proxy executables;
- changing aliases;
- editing terminal profiles;
- injecting a background process.

Status must prominently show:

    Behavioural instructions: configured
    Skills: installed; version-dependent
    Custom agents: user-selectable; version-dependent
    Subagents: unsupported
    Deterministic hook: unsupported
    Native tool approvals: unchanged

The threat model must state that behavioural instructions are not deterministic
command enforcement.

======================================================================
8. JETBRAINS ADAPTER
======================================================================

The JetBrains product contains multiple surfaces with different capabilities.

Do not pretend they are identical.

Represent them explicitly in adapter output and status without creating a general
surface framework.

The relevant surfaces are:

1. JetBrains AI Assistant native Chat mode
2. coding agents hosted inside JetBrains AI Assistant
3. the GitHub Copilot plugin for JetBrains IDEs

----------------------------------------------------------------------
8.1 JetBrains AI Assistant native Chat Instructions
----------------------------------------------------------------------

Generate:

    dist/jetbrains/ai-assistant/chat-instructions.md

This is a concise global behavioural baseline for native AI Assistant Chat mode.

Do not attempt to locate or edit an undocumented JetBrains settings database.

Add a CLI command group or similarly small interface:

    ai-guardrails jetbrains print-chat-instructions
    ai-guardrails jetbrains print-chat-instructions --clipboard

Clipboard copying:

- is optional and explicit;
- must use an already supported platform clipboard command;
- must fail clearly when unavailable;
- never counts as installation.

Installation/status must print the manual step:

    JetBrains Settings
      > Tools
      > AI Assistant
      > Prompt Library
      > General
      > Chat Instructions

Paste the complete generated text and save it.

State must record that this is a manual outstanding step.

Do not mark native Chat Instructions installed merely because the generated source
exists or was copied to the clipboard.

----------------------------------------------------------------------
8.2 JetBrains AI Assistant project rules
----------------------------------------------------------------------

Generate:

    dist/jetbrains/ai-assistant/project-rules/workstation-guardrails.md

Add an explicit repository export command, for example:

    ai-guardrails jetbrains export-project-rules --repo . --dry-run
    ai-guardrails jetbrains export-project-rules --repo .

The exact command spelling may follow the current CLI conventions, but do not create
a separate executable.

Export to:

    <repo>/.aiassistant/rules/workstation-guardrails.md

Requirements:

- never run automatically during workstation installation;
- require an explicit repository path;
- support dry-run;
- refuse paths outside the selected repository;
- refuse symlink targets;
- preserve an unmanaged collision by default;
- support `--force` only with backup;
- use atomic writes;
- use generated content from canonical policy;
- keep the rule concise;
- do not include all pack content;
- do not create or modify `.idea` metadata;
- do not claim a particular JetBrains Rule type was activated solely from the
  Markdown file.

After export, print the manual verification step:

    Settings > Tools > AI Assistant > Rules

Open the generated rule and confirm that it is active as an `Always` rule.

If current JetBrains documentation provides a stable file-only way to encode the
rule type, use it. Otherwise, keep the manual confirmation.

If the target repository contains `.noai`, refuse or warn clearly because native
JetBrains AI Assistant is disabled for that project. Do not remove `.noai`.

Do not automatically add `.github/copilot-instructions.md` to arbitrary
repositories in this task.

----------------------------------------------------------------------
8.3 JetBrains-hosted coding agents
----------------------------------------------------------------------

Document the instruction files currently used by each selected agent.

At minimum, account for:

- Junie using `AGENTS.md`;
- Codex using `AGENTS.md`;
- Claude Agent using `CLAUDE.md`;
- GitHub Copilot using the files currently documented by JetBrains.

The repository already has root `AGENTS.md` and `CLAUDE.md`.

Do not generate a second repository-level copy solely for JetBrains.

Status should say:

- repository agent instructions are available when the opened project contains the
  supported file;
- native Chat project rules are separate;
- user-global Codex/Claude configuration activation inside JetBrains is unverified;
- deterministic Codex/Claude hooks must not be assumed active inside JetBrains;
- each agent's operation mode and approval controls remain user-controlled.

Do not modify:

- Codex Read-only/Agent/full-access mode;
- Claude Manual/Auto/Accept Edits/Don't Ask/Bypass mode;
- GitHub Copilot Allow All;
- Junie modes;
- MCP pass-through;
- JetBrains MCP brave mode.

----------------------------------------------------------------------
8.4 JetBrains skills
----------------------------------------------------------------------

Continue to install canonical portable skills at:

    ~/.agents/skills/

JetBrains AI Assistant documents registration of local skill directories through:

    Settings
      > Tools
      > AI Assistant
      > Skills
      > Manage Skill Directories

Add a manual step that tells the user to register:

    ~/.agents/skills

as a Global skill directory.

Do not edit JetBrains settings storage to register it automatically.

Status must distinguish:

- skill directory installed;
- JetBrains directory registration required;
- registration unverified;
- skills supported only by the agents currently documented as supporting them.

Do not claim that Junie or every hosted agent loads Agent Skills when the current
JetBrains capability table says otherwise.

The GitHub Copilot plugin's skill support is Preview. Do not claim that the same
manual registration activates Copilot plugin skills unless current official
documentation confirms it.

----------------------------------------------------------------------
8.5 GitHub Copilot plugin global instructions in JetBrains
----------------------------------------------------------------------

Generate:

    dist/jetbrains/copilot/global-copilot-instructions.md

On documented platforms, install as a managed file or managed block at:

macOS:

    ~/.config/github-copilot/intellij/global-copilot-instructions.md

Windows:

    ~/AppData/Local/github-copilot/intellij/global-copilot-instructions.md

For a real Windows home, this corresponds to the documented
`%LOCALAPPDATA%\github-copilot\intellij` location.

Selected-home safety takes precedence:

- alternate-home tests must never follow the real `LOCALAPPDATA` outside the selected
  home;
- derive the Windows destination beneath the selected home;
- do not let an environment variable escape the selected home.

On Linux:

- do not invent or infer an undocumented global path;
- generate the file;
- report a manual GitHub Copilot Customizations step;
- do not claim installation.

On macOS or Windows, automatic installation is allowed when either:

- the documented GitHub Copilot JetBrains configuration parent already exists; or
- the user explicitly selected `--product jetbrains`.

For no-argument auto-detection without Copilot evidence:

- do not create an otherwise unused Copilot configuration tree merely because a
  JetBrains IDE exists;
- report the generated/manual option.

Preserve unrelated file content by managed block if the native file is user-editable
and can contain other instructions. Use a dedicated managed file only if current
product semantics make replacement safe.

Document that GitHub Copilot plugin custom instructions are Preview and can be
disabled.

----------------------------------------------------------------------
8.6 JetBrains GitHub Copilot custom agents and routing
----------------------------------------------------------------------

GitHub currently marks JetBrains custom agents and subagents as Preview.

Do not install custom agents into an undocumented personal path.

When a non-`none` routing profile is explicitly selected for `jetbrains`:

- generate reviewable Copilot-compatible agent files under:

      dist/jetbrains/copilot/agents/

- optionally copy the manual bundle under a project-owned location such as:

      ~/.ai-guardrails/manual/jetbrains/agents/

  only if the existing installation design has an appropriate manual-artifact
  mechanism;

- print the documented Customizations-editor import/create steps;
- record `manual-activation-required`;
- do not mark routing active;
- do not change the selected model;
- default model selection to inherited;
- do not claim a cost saving;
- do not claim that JetBrains AI Assistant native agents use these Copilot profiles.

If the current official documentation now exposes a stable documented personal
agent path, use it only after validating that it applies to the exact JetBrains
Copilot surface. Otherwise keep manual activation.

`routing show --product jetbrains` must accurately describe the manual/Preview
status.

----------------------------------------------------------------------
8.7 No JetBrains-native deterministic hook
----------------------------------------------------------------------

Do not generate a JetBrains hook.

GitHub's current compatibility matrix marks Copilot hooks unsupported in JetBrains.

JetBrains AI Assistant does not currently document a generic cross-agent
`PreToolUse` hook equivalent.

Do not:

- wrap IDE launchers;
- replace shells;
- edit terminal profiles;
- install a proxy;
- enable the IDE MCP server;
- enable MCP brave mode;
- alter agent operation modes;
- claim that existing Codex or Claude hooks are active inside JetBrains.

Status must prominently show:

    Native AI Chat guidance: manual Chat Instructions
    Project rules: explicit repository export
    Agent instructions: repository file dependent
    Skills: manual global-directory registration
    Copilot global instructions: platform/evidence dependent
    Deterministic hook: unsupported
    Native approvals/operation modes: unchanged

======================================================================
9. PRODUCT DETECTION
======================================================================

Detection must remain offline, conservative, and explainable.

Do not scan the entire filesystem.

----------------------------------------------------------------------
9.1 VS Code detection
----------------------------------------------------------------------

Use conservative evidence such as:

- `code` executable;
- `code-insiders` executable;
- known standard application locations;
- existing project-managed installation state.

Do not treat the mere existence of `~/.copilot` as conclusive evidence because other
Copilot surfaces may use it.

Report the evidence used.

----------------------------------------------------------------------
9.2 Visual Studio detection
----------------------------------------------------------------------

Automatic Visual Studio detection applies only on Windows.

Use, where available:

- `devenv.exe`;
- the officially installed `vswhere.exe`;
- bounded standard installation locations;
- existing project-managed state.

Do not:

- query the network;
- scan arbitrary drives;
- mutate the registry;
- require `vswhere`;
- fail the entire installer when version discovery is unavailable.

Record only the non-sensitive version and capability result required for status.

A real `visualstudio` installation on a non-Windows platform must fail with an
actionable message.

Build, validation, and platform-simulated tests remain cross-platform.

----------------------------------------------------------------------
9.3 JetBrains detection
----------------------------------------------------------------------

Use conservative evidence such as:

- common JetBrains launchers on PATH:
  `idea`, `pycharm`, `webstorm`, `rider`, `goland`, `clion`, `datagrip`,
  `rubymine`, `rustrover`;
- bounded standard JetBrains Toolbox locations beneath the selected home;
- bounded standard JetBrains configuration roots beneath the selected home;
- existing project-managed state.

Do not infer that:

- JetBrains AI Assistant is installed;
- a JetBrains AI subscription is active;
- the GitHub Copilot plugin is installed;
- GitHub authentication is configured;
- a specific agent is enabled.

Report IDE evidence and separately report extension/AI activation as unverified.

======================================================================
10. ROUTING MODEL MAPS AND PRODUCT SUPPORT
======================================================================

The current routing loader expects one model map per product.

Add:

    routing/model-maps/vscode.json
    routing/model-maps/visualstudio.json
    routing/model-maps/jetbrains.json

Place them in the current package-resource canonical location.

Default all tiers to inherited/unverified model selection.

Do not put current commercial model names into canonical policy.

Product-specific routing behaviour:

vscode:

- native custom agents installed when explicitly selected;
- automatic subagents supported;
- model inherited by default.

visualstudio:

- custom agents installed when explicitly selected and compatible;
- user-selectable roles only;
- no subagents;
- model inherited by default.

jetbrains:

- generated manual Copilot agent bundle only;
- Preview;
- activation manual and unverified;
- no claim that native AI Assistant routing was configured;
- model inherited by default.

Update routing validation so unsupported automation is rejected honestly rather
than silently pretending success.

The main-session model must remain unchanged for every product.

======================================================================
11. STATE, SHARED OWNERSHIP, AND MIGRATION
======================================================================

Extend the current state format using the existing migration mechanism.

State may record:

- product;
- managed paths;
- content hashes;
- source and policy digests;
- detected version;
- capability status;
- hook mode;
- manual steps;
- shared skill ownership;
- manual activation status;
- platform;
- adapter format version.

State must not contain:

- instruction contents;
- prior configuration contents;
- prompts;
- source code;
- commands or command arguments;
- GitHub credentials;
- JetBrains credentials;
- account identifiers;
- IDE telemetry;
- raw tool output.

If the state format changes:

- read the previous format;
- migrate only on successful write;
- preserve uninstall of older records;
- preserve existing Codex, Claude, and Cursor ownership;
- add migration tests.

Shared skills under `~/.agents/skills` must remain until no managed product requires
them.

Manual steps must be product-specific and must not count as completed merely because
a generated file exists.

Do not install the immutable hook runtime solely for Visual Studio or JetBrains when
no hook-capable product requires it.

VS Code may reuse the existing runtime.

======================================================================
12. CLI AND FIRST-TIME USER EXPERIENCE
======================================================================

The normal consumer journey remains:

    ai-guardrails install --dry-run
    ai-guardrails install
    ai-guardrails status

Do not require users to choose products during normal installation.

No-argument installation must install only detected products.

Support explicit selection:

    ai-guardrails install --product vscode
    ai-guardrails install --product visualstudio
    ai-guardrails install --product jetbrains
    ai-guardrails install --product all

Support all current management commands for the three products:

- build;
- validate;
- install;
- update;
- status;
- doctor;
- effective;
- diff-installed;
- uninstall;
- receipt;
- routing show/set where applicable.

Add a small JetBrains command group or equivalent:

    ai-guardrails jetbrains print-chat-instructions
    ai-guardrails jetbrains print-chat-instructions --clipboard
    ai-guardrails jetbrains export-project-rules --repo . --dry-run
    ai-guardrails jetbrains export-project-rules --repo .

Keep names consistent with the current CLI and avoid unnecessary commands.

Default dry-run/status output must be explicit.

Example VS Code summary:

    GitHub Copilot in Visual Studio Code
      User instructions       planned
      Skills                  shared installation planned
      PreToolUse hook         planned; Preview
      Hook activation         unverified
      Inline suggestions      not covered
      Main model              unchanged

Example Visual Studio summary:

    GitHub Copilot in Visual Studio
      User instructions       planned
      Skills                  planned; version compatibility unverified
      Custom agents           not installed; routing profile not selected
      Subagents               unsupported
      Deterministic hook      unsupported
      Native approvals        unchanged

Example JetBrains summary:

    JetBrains IDEs
      AI Assistant Chat       manual Chat Instructions step
      AI Assistant rules      optional repository export
      Agent instructions      AGENTS.md / CLAUDE.md per selected agent
      Skills                  installed; manual directory registration required
      Copilot instructions    platform/evidence dependent
      Copilot agents          Preview; manual when routing selected
      Deterministic hook      unsupported
      Native approvals        unchanged

Do not hide unsupported enforcement in verbose output.

======================================================================
13. SELF-PROTECTION POLICY
======================================================================

Extend the existing guardrail-modification command recognition to include mutating
forms for the new product and JetBrains export commands.

Examples requiring existing guardrail-modification treatment include:

    ai-guardrails install --product vscode
    ai-guardrails update --product visualstudio
    ai-guardrails uninstall --product jetbrains
    ai-guardrails routing set balanced --product vscode
    ai-guardrails jetbrains export-project-rules --repo ...

Do not classify read-only commands as mutations:

    ai-guardrails status --product vscode
    ai-guardrails doctor --product visualstudio
    ai-guardrails effective --product jetbrains
    ai-guardrails jetbrains print-chat-instructions
    ai-guardrails routing show --product vscode
    ai-guardrails validate --product all

Add positive and safe counterexamples.

Do not broaden matching so documentation, `echo`, or search text is falsely denied.

======================================================================
14. BUILD AND VALIDATION
======================================================================

Extend deterministic build and validation for all six products.

Build outputs must include, as applicable:

    dist/vscode/
    dist/visualstudio/
    dist/jetbrains/

Validate:

- product applicability;
- instruction frontmatter;
- Markdown;
- hook JSON;
- custom agent frontmatter;
- model maps;
- size limits;
- deterministic ordering;
- exactly one final newline;
- no machine-specific paths;
- no duplicate canonical content;
- manual-step metadata;
- capability claims;
- hook support status.

Update canonical policy manifest applicability to include the new products where
appropriate.

Do not add a wildcard product concept unless the existing schema already supports
one cleanly.

Build twice and require no second-build diff.

Ensure the built wheel and source distribution contain every new package resource.

======================================================================
15. TESTS
======================================================================

Use the existing standard-library test framework and temporary homes.

No test may launch or modify a real IDE.

No test may contact GitHub, JetBrains, Microsoft, or another network service.

No test may modify the real:

- home directory;
- VS Code configuration;
- Visual Studio configuration;
- JetBrains configuration;
- GitHub authentication;
- JetBrains authentication;
- extension/plugin installation;
- registry;
- MCP configuration.

----------------------------------------------------------------------
15.1 Product-set and build tests
----------------------------------------------------------------------

Test:

- the product set contains all six products exactly once;
- all canonical product applicability accepts the three new IDs;
- all six model maps exist and validate;
- all expected generated outputs exist;
- builds are deterministic;
- generated files have correct headers and terminal newline;
- package archives contain the new resources;
- installed CLI works outside the checkout.

----------------------------------------------------------------------
15.2 VS Code tests
----------------------------------------------------------------------

Test:

- fresh native instruction installation;
- valid `.instructions.md` frontmatter;
- native hook JSON;
- immutable runtime path;
- no repository path in live hook;
- shared skills;
- repeated installation idempotency;
- dry-run changes nothing;
- uninstall removes only owned files;
- user `settings.json` is never touched;
- hook Preview status;
- inline suggestions reported as uncovered;
- instruction discovery activation reported unverified;
- routing disabled by default;
- custom agents installed only for explicit routing;
- model selection remains inherited;
- managed Claude hook already present;
- VS Code installed first, then Claude;
- Claude installed first, then VS Code;
- uninstall Claude while VS Code remains;
- uninstall VS Code while Claude remains;
- unmanaged Claude hook preserved with warning;
- one project-owned hook registration only;
- one-use waiver cannot be consumed twice.

VS Code hook payload tests must include:

- `runTerminalCommand` with `git reset --hard`;
- force push;
- destructive infrastructure command;
- package publication;
- protected guardrail path mutation;
- safe `git status`;
- targeted tests;
- safe read-only file request;
- command text merely printed or searched;
- malformed JSON;
- missing tool input;
- unknown tool;
- no command/argument leakage in diagnostics or audit.

----------------------------------------------------------------------
15.3 Visual Studio tests
----------------------------------------------------------------------

Test:

- Windows-style selected home;
- managed block in `copilot-instructions.md`;
- preservation of unrelated content;
- first-mutation backup;
- idempotency;
- shared skills;
- custom agent minimum-version handling;
- skill minimum-version handling;
- known compatible version;
- known too-old version;
- unknown version;
- custom agents only when routing is explicit;
- no subagent claim;
- no hook file;
- no registry or private settings mutation;
- non-Windows real install rejection;
- build/validation remains cross-platform;
- uninstall removes only owned content;
- user content preserved.

----------------------------------------------------------------------
15.4 JetBrains tests
----------------------------------------------------------------------

Test:

- JetBrains IDE detection by bounded executable evidence;
- no claim that AI Assistant or Copilot plugin is installed;
- generated native Chat Instructions;
- `print-chat-instructions`;
- clipboard unavailable failure;
- project rule export dry-run;
- project rule export to `.aiassistant/rules/workstation-guardrails.md`;
- unmanaged collision preservation;
- `--force` backup;
- no `.idea` mutation;
- `.noai` warning/refusal;
- manual `Always` rule confirmation reported;
- shared skill directory installation;
- manual skill-directory registration reported;
- repository `AGENTS.md`/`CLAUDE.md` coverage documented;
- no claim that global Codex/Claude hooks are active;
- no JetBrains hook file;
- macOS Copilot global instruction path;
- Windows selected-home Copilot global instruction path;
- no escape through real `LOCALAPPDATA`;
- Linux manual Copilot instruction step;
- no invented Linux path;
- Copilot agent bundle generated only for explicit routing;
- Preview/manual activation reported;
- no model setting mutation;
- native operation modes and MCP settings untouched;
- uninstall removes only managed files and state.

----------------------------------------------------------------------
15.5 Shared ownership and migration tests
----------------------------------------------------------------------

Test:

- existing pre-extension state is readable;
- migration preserves Codex, Claude, and Cursor;
- adding VS Code does not duplicate shared skills;
- adding Visual Studio does not duplicate shared skills;
- adding JetBrains does not duplicate shared skills;
- uninstalling one product preserves skills required by another;
- runtime is not installed solely for behaviour-only products;
- `--product all` is deterministic;
- no managed path escapes selected home;
- no actual workstation path appears in generated canonical output.

======================================================================
16. CI
======================================================================

Extend the current CI rather than replacing it.

Retain one full validation job.

Add or extend focused cross-platform smoke tests for:

- Linux:
  - VS Code generation and hook payloads;
  - JetBrains Linux manual behaviour;
- macOS:
  - VS Code;
  - JetBrains documented Copilot global path;
- Windows:
  - VS Code;
  - Visual Studio path/version simulation;
  - JetBrains documented Copilot global path.

Do not multiply every expensive test across every platform unnecessarily.

No CI job may require a real IDE, extension, account, token, subscription, or
network call beyond ordinary package installation already used by CI.

Do not add a publishing workflow.

======================================================================
17. DOCUMENTATION
======================================================================

Update README.md, quick user guide, architecture, compatibility, threat model,
operations, and routing documentation where relevant.

The README quick start must remain short.

Add a clear coverage matrix.

VS Code:

- native user instructions;
- repository `AGENTS.md`;
- shared skills;
- custom agents/subagents;
- Preview hook;
- organisation may disable hook;
- inline suggestions not covered;
- main model unchanged.

Visual Studio:

- user `copilot-instructions.md`;
- repository `.github/copilot-instructions.md`;
- path-specific instructions;
- version-gated skills;
- version-gated custom agents;
- custom agents are user-selectable roles;
- subagents unsupported;
- hooks unsupported;
- terminal/tool approvals remain native.

JetBrains:

- native AI Assistant Chat Instructions are a manual Prompt Library step;
- native project rules use `.aiassistant/rules`;
- coding agents use their documented repository instruction file;
- local skills require manual directory registration;
- GitHub Copilot global instructions are automatically installable only on
  documented platforms/paths;
- GitHub Copilot customization features are Preview;
- hooks unsupported;
- global Codex/Claude hook activation inside JetBrains unverified;
- native operation modes, approvals, `.aiignore`, and MCP controls remain separate.

Threat model additions:

- behavioural instructions are not a security boundary;
- VS Code hook configuration does not prove an organisation enables hooks;
- VS Code hooks run with VS Code's user permissions;
- Visual Studio has no project hook from this tool;
- JetBrains has no project hook from this tool;
- JetBrains-hosted agents can have different approval and file-ignore behaviour;
- integrated/third-party agents may not respect JetBrains `.aiignore`;
- MCP tool exposure and brave modes can bypass assumptions if users enable them;
- OS least privilege, branch protection, cloud IAM, platform RBAC, and production
  change controls remain authoritative.

Document exact manual steps and how status represents them.

Do not claim support for inline completion guardrails.

======================================================================
18. OUT OF SCOPE
======================================================================

Do not implement:

- VS Code extension installation;
- Visual Studio extension installation;
- JetBrains plugin installation;
- GitHub or JetBrains login;
- organisation policy deployment;
- repository-wide automatic `.github` mutation;
- automatic `.aiassistant` mutation during global install;
- Visual Studio hooks;
- JetBrains hooks;
- shell or compiler wrappers;
- IDE launcher wrappers;
- registry mutation;
- undocumented settings-database mutation;
- automatic model selection;
- automatic approval-mode changes;
- automatic MCP configuration;
- JetBrains MCP server enablement;
- brave mode;
- remote telemetry;
- a new product abstraction framework;
- unrelated refactoring;
- another language;
- package publication.

======================================================================
19. ACCEPTANCE CRITERIA
======================================================================

Before reporting completion:

1. Inspect the final diff.
2. Build all six products.
3. Validate all canonical and generated data.
4. Run the complete existing test suite.
5. Run all new product tests.
6. Build twice and confirm no second-build diff.
7. Build wheel and source distribution.
8. Inspect package archives for new resources.
9. Install the wheel into a fresh temporary environment.
10. Run the installed CLI from outside the repository.
11. Run temporary-home install/status/update/uninstall journeys for:
    - VS Code;
    - Visual Studio under simulated Windows;
    - JetBrains on Linux/manual mode;
    - JetBrains under simulated macOS;
    - JetBrains under simulated Windows.
12. Test VS Code/Claude hook ownership transitions.
13. Prove no duplicate project-owned hook registration.
14. Prove Visual Studio receives no hook.
15. Prove JetBrains receives no hook.
16. Prove no real IDE configuration was modified.
17. Prove no setting, registry, authentication, model, approval, MCP, or extension
    configuration was modified.
18. Run `git diff --check`.
19. Review for:
    - duplicate canonical policy;
    - duplicate hook execution;
    - duplicate skills;
    - unsupported capability claims;
    - scattered product special cases;
    - unnecessary abstractions;
    - stale three-product assumptions;
    - undocumented paths;
    - accidental repository mutation;
    - accidental main-model changes.

At minimum, run the current repository equivalents of:

    ai-guardrails build --product all
    ai-guardrails validate --product all
    python -m unittest discover -s tests -v
    ai-guardrails install --product vscode --home <temporary-home> --dry-run
    ai-guardrails install --product visualstudio --home <temporary-home> --dry-run
    ai-guardrails install --product jetbrains --home <temporary-home> --dry-run
    ai-guardrails status --product vscode --home <temporary-home>
    ai-guardrails status --product visualstudio --home <temporary-home>
    ai-guardrails status --product jetbrains --home <temporary-home>
    git diff --check
    git status --short

Use the repository shim equivalents as well where contributor compatibility is
covered.

Do not commit or push.

======================================================================
20. FINAL REPORT
======================================================================

The final response must include:

- concise architecture summary;
- current architecture reused;
- files materially changed;
- product identifiers added;
- generated output paths;
- VS Code instruction path;
- VS Code hook path;
- VS Code hook Preview limitation;
- VS Code inline-suggestion limitation;
- VS Code/Claude hook ownership behaviour;
- Visual Studio instruction path;
- Visual Studio version requirements;
- Visual Studio custom-agent behaviour;
- Visual Studio lack of hooks and subagents;
- JetBrains native Chat manual step;
- JetBrains project-rule export;
- JetBrains skill-directory registration step;
- JetBrains Copilot platform-specific path behaviour;
- JetBrains Preview/manual routing behaviour;
- JetBrains lack of hooks;
- state migration;
- shared skill ownership;
- commands run;
- test results;
- package-build result;
- installed-wheel smoke-test result;
- CI changes;
- skipped checks;
- unresolved limitations;
- confirmation that no real IDE/workstation configuration was modified;
- confirmation that no extension/plugin was installed;
- confirmation that no commit, push, publication, login, or remote service call
  occurred.

Do not claim:

- VS Code hook activation merely because a JSON file exists;
- Visual Studio deterministic enforcement;
- JetBrains deterministic enforcement;
- inline completion coverage;
- automatic JetBrains skill activation;
- automatic JetBrains routing activation;
- model availability;
- guaranteed cost saving;
- successful checks that were not observed.
