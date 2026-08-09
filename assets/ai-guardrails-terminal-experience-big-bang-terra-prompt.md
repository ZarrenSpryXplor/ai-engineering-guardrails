# AI Engineering Guardrails — Terminal Experience, Usage Visibility, Complexity Signals, and Demo UX

You are working at the root of the existing repository:

    ai-engineering-guardrails

Implement a focused, production-quality terminal experience milestone before the
project's first public release.

The repository already provides a packaged Python CLI, canonical policy resources,
six product adapters, deterministic hooks, routing, capability packs, installation
state, redacted audit events, policy overlays, explain/simulate commands, scanning,
waivers, and receipts.

Extend that existing implementation with:

1. Optional status-line and usage-visibility integration for:
   - OpenAI Codex CLI
   - Anthropic Claude Code
   - Cursor CLI

2. A compact local guardrail-activity summary.

3. Transparent maintainability and KISS/DRY complexity signals.

4. A safe synthetic demonstration mode.

5. More useful compact and playful session-receipt output.

This is one implementation pass, but it is not permission to redesign the project.

Do not commit, push, tag, publish, create a release, install an IDE/CLI, authenticate
to a vendor, contact a cloud service, or modify my real workstation configuration
while developing or testing.

Use temporary homes and fixtures for every installation test.

==============================================================================
1. NON-NEGOTIABLE SIMPLICITY RULES
==============================================================================

Apply KISS, DRY, YAGNI, and the Rule of Three.

KISS:

- Extend the current CLI and installer.
- Do not build a monitoring platform.
- Do not build a cross-vendor terminal wrapper.
- Do not proxy, launch, scrape, or intercept Codex, Claude, or Cursor sessions.
- Do not add a daemon, background service, database, web server, dashboard, TUI, or
  long-running collector.
- Do not add another implementation language.
- Keep executable project logic in Python 3.11+ using the standard library.
- Prefer a few focused functions or modules over a framework.
- Keep status-line rendering deterministic and fast.
- Keep the normal installation journey unchanged unless the user explicitly enables
  a status-line profile.

DRY:

- Reuse the existing immutable runtime, installation state, atomic writes, backups,
  managed ownership, JSON merging, audit schema, explain/simulate engine, repository
  detection, and receipt machinery.
- Do not create a second installer.
- Do not create a second audit log format.
- Do not create a second policy evaluator.
- Do not duplicate canonical product capability data.
- Do not maintain separate hand-written status-line logic for visually identical
  profiles where one renderer can express the difference.
- Do not treat similar-looking vendor APIs as identical when their contracts differ.

YAGNI:

- No remote usage API client.
- No authentication-token reader.
- No billing-account integration.
- No undocumented vendor endpoint.
- No automatic cost-saving claims.
- No AI-generated maintainability score.
- No plugin system.
- No theme marketplace.
- No arbitrary expression language.
- No shell-script business logic.
- No Click, Typer, Rich, Pydantic, platformdirs, tomlkit, or other new runtime
  dependency.
- No custom terminal emulator integration.
- No automatic model switching.
- No automatic session termination.
- No automatic policy weakening.
- No speculative support for CLIs that are not currently in scope.

Rule of Three:

- Do not generalise after seeing only one or two similar code paths.
- A small amount of explicit vendor-specific code is preferable to a misleading
  abstraction.
- Prefer five obvious lines to a reusable helper that obscures ownership or safety.

Agent execution:

- Work serially.
- Do not spawn implementation subagents.
- Do not use parallel writing agents.
- Preserve all pre-existing uncommitted work.
- A final independent read-only review is acceptable after implementation and tests.

==============================================================================
2. INSPECT THE CURRENT REPOSITORY BEFORE EDITING
==============================================================================

Before making changes:

1. Run:

       git status --short

2. Read:

   - AGENTS.md
   - CLAUDE.md
   - README.md
   - docs/architecture.md
   - docs/compatibility.md
   - docs/threat-model.md
   - docs/routing-and-measurement.md or its current equivalent
   - pyproject.toml
   - the current CLI implementation
   - build.py
   - install.py
   - state.py
   - enforcement.py
   - policy.py
   - routing.py
   - scan.py
   - util.py
   - the canonical resource layout
   - current audit and receipt schemas
   - all tests covering installation, state, audit, receipts, and CLI output

3. Determine the current public commands and state format.

4. Identify existing support for:

   - dry-run;
   - alternate `--home`;
   - product detection;
   - shared artifact ownership;
   - immutable runtime installation;
   - JSON settings merges;
   - Codex config handling, if any;
   - local audit-event storage;
   - receipt generation;
   - output formats and ANSI handling;
   - `NO_COLOR`;
   - Windows path quoting.

5. Search for all assumptions that the project has no terminal-UX subsystem.

6. Produce a concise internal implementation map before editing:

   - existing components to reuse;
   - genuinely new source files required;
   - existing public interfaces that must remain compatible;
   - state migration, if any;
   - generated resources and docs to update;
   - tests to add.

Do not replace functioning architecture because you would have designed it differently.

==============================================================================
3. VERIFY CURRENT OFFICIAL PRODUCT BEHAVIOUR
==============================================================================

Before implementation, verify current behaviour using only official product
documentation.

At minimum, review:

OpenAI Codex:

https://developers.openai.com/codex/developer-commands
https://developers.openai.com/codex/config-reference
https://developers.openai.com/codex/config-file/config-sample
https://developers.openai.com/codex/models

Anthropic Claude Code:

https://code.claude.com/docs/en/statusline
https://code.claude.com/docs/en/costs
https://code.claude.com/docs/en/settings
https://code.claude.com/docs/en/changelog

Cursor CLI:

https://cursor.com/docs/cli/reference/slash-commands.md
https://cursor.com/docs/cli/overview
https://cursor.com/docs/cli/reference/configuration

Record the exact verification date and relevant capability matrix in
docs/compatibility.md.

If the current official documentation differs from this prompt, follow the current
documented behaviour and clearly document the difference.

Important currently documented constraints to preserve unless superseded:

Codex:

- Codex has a native configurable footer status line through `/statusline`.
- Native items include model/reasoning, context information, rate limits, Git branch,
  token counters, session metadata, directory/project information, and version.
- Configuration persists through `tui.status_line` in `config.toml`.
- `/usage` is the documented account-usage surface.
- The native status line is a list of supported item identifiers, not a documented
  arbitrary external-renderer interface.
- `/pets` is a native optional fun feature.
- Do not claim the project can inject arbitrary custom shield, KISS, audit, or cost
  segments into the Codex footer unless official documentation now supports it.

Claude Code:

- Claude Code supports a programmable status line through a local command configured
  in `~/.claude/settings.json`.
- The command receives structured JSON on stdin and prints the displayed status line.
- The input can include model, effort, context-window usage, rate limits, estimated
  session cost, duration, line changes, workspace, Git/PR fields, session identity,
  and related documented fields.
- Fields may be missing or null and must be handled gracefully.
- Rate-limit fields are not available for every authentication mode.
- The status-line command does not consume model tokens.
- `COLUMNS` and `LINES` are the supported width inputs.
- A status-line command may run frequently and must remain fast.
- The displayed dollar value is an estimate based on list rates and may not represent
  subscription billing, discounts, Bedrock, Foundry, or other provider billing.

Cursor CLI:

- `/status-indicators` controls terminal-title status indicators.
- The current documented slash-command list does not provide a programmable custom
  status-line command comparable to Claude Code.
- Do not claim `/usage` exists unless the current official docs explicitly list it.
- Do not scrape Cursor's screen, logs, private account files, or undocumented
  endpoints to manufacture parity.
- Do not wrap the Cursor executable.

==============================================================================
4. RELEASE AND USER-EXPERIENCE BOUNDARY
==============================================================================

This capability is part of the first release, but remains optional.

The existing default journey must still work without new questions or cosmetic
configuration:

    ai-guardrails install --dry-run
    ai-guardrails install
    ai-guardrails status

A no-argument installation must not modify any product status line.

A user can opt in either during installation:

    ai-guardrails install --statusline-profile standard

or afterwards:

    ai-guardrails statusline preview --product all --profile standard
    ai-guardrails statusline install --product all --profile standard --dry-run
    ai-guardrails statusline install --product all --profile standard
    ai-guardrails statusline status --product all

Supported profiles:

    compact
    standard
    fun

Use `none` only where the existing profile conventions make it useful. Do not require
a `none` value if absence already expresses disabled state cleanly.

`update` must preserve the currently installed status-line profile unless the user
explicitly changes it.

The normal `uninstall` command must remove this project's managed status-line
configuration along with other managed product configuration.

A dedicated status-line uninstall must remove only status-line integration:

    ai-guardrails statusline uninstall --product all --dry-run
    ai-guardrails statusline uninstall --product all

Do not enable status lines, colors, Unicode, pets, or terminal-title changes without
explicit user intent.

==============================================================================
5. CLI SURFACE
==============================================================================

Add a focused command group:

    ai-guardrails statusline preview
    ai-guardrails statusline install
    ai-guardrails statusline status
    ai-guardrails statusline uninstall

Support:

    --product codex
    --product claude
    --product cursor
    --product all
    --profile compact
    --profile standard
    --profile fun
    --home <path>
    --dry-run
    --force
    --format human
    --format json
    --no-color

Use only options that make sense for each subcommand.

Add the optional top-level installation option:

    --statusline-profile compact|standard|fun

Do not add an interactive wizard.

Add:

    ai-guardrails activity
    ai-guardrails complexity
    ai-guardrails demo

Enhance the existing receipt command rather than replacing it:

    ai-guardrails receipt --compact
    ai-guardrails receipt --fun

Do not add more top-level commands unless a current requirement genuinely needs one.

Human output must be useful without understanding internal manifests.

JSON output must be stable, versioned where appropriate, and contain no ANSI codes.

==============================================================================
6. STATUS-LINE PROFILES
==============================================================================

Use one small canonical profile definition, stored with existing package resources.

Each profile should define intended information, not vendor-specific rendering
implementation.

Suggested semantics:

compact:

- model or model/reasoning where available;
- context usage or remaining context;
- active Git branch where available;
- active guardrail safety posture;
- fit on one short line.

standard:

- everything in compact;
- rate-limit windows where officially provided;
- estimated session cost where officially provided;
- elapsed session time;
- concise guardrail warning/denial activity where reliably attributable;
- one line by default, two only when terminal width is insufficient or the product
  explicitly supports it well.

fun:

- the same factual content as standard;
- tasteful shield, warning, fire, or smoke symbols;
- context heat indicators;
- a concise KISS indicator only when based on a current, transparent local snapshot;
- no animations;
- no random output;
- no sound;
- no misleading severity;
- no custom Codex text that the native Codex status line cannot support.

Profiles must not imply equivalent capabilities across products.

The preview must show each product's actual result:

Example:

    Claude Code
      Native programmable status line: supported
      Preview:
        🛡 observe │ Sonnet · high │ ctx ███████░░░ 72% │ 5h 18% │ est $0.84 │ main*

    Codex
      Native item status line: supported
      Managed native items:
        model-with-reasoning, context, rate limits, tokens, git branch
      Custom guardrail counters: unsupported by native status line
      Optional fun extra: configure `/pets` manually

    Cursor CLI
      Programmable status line: not documented
      Native terminal-title indicators: `/status-indicators`
      No files will be modified

Do not use these example item IDs blindly. Verify exact current Codex identifiers.

==============================================================================
7. CLAUDE CODE STATUS LINE
==============================================================================

Claude Code is the full custom-rendering implementation.

------------------------------------------------------------------------------
7.1 Runtime
------------------------------------------------------------------------------

Add a small standard-library Python renderer to the existing immutable runtime.

It must:

- read one JSON object from stdin;
- write only status-line text to stdout;
- write diagnostics only to stderr;
- never execute input;
- never import the repository checkout;
- never contact the network;
- never read prompts or transcripts;
- never read authentication or billing secrets;
- never print raw paths when a basename or short project name is sufficient;
- fail gracefully with a minimal fallback line or no output;
- return promptly;
- work on Windows, macOS, and Linux;
- honour `NO_COLOR`;
- support ASCII fallback when Unicode is disabled or unsuitable;
- use `COLUMNS` to select compact rendering;
- contain no external dependency.

Keep the hot path fast.

Target ordinary execution below 100 ms where practical.

Do not run a repository scan on every refresh.

------------------------------------------------------------------------------
7.2 Claude fields
------------------------------------------------------------------------------

Use only current documented fields and handle absence gracefully.

Potential segments include:

- `model.display_name`;
- `effort.level`;
- `context_window.used_percentage`;
- `context_window.remaining_percentage`;
- `rate_limits.five_hour.used_percentage`;
- `rate_limits.seven_day.used_percentage`;
- `cost.total_cost_usd`;
- `cost.total_duration_ms`;
- `cost.total_lines_added`;
- `cost.total_lines_removed`;
- `workspace.current_dir`;
- `workspace.project_dir`;
- `workspace.git_worktree`;
- `session_id`;
- `session_name`;
- documented Git/PR fields.

Never require all fields.

Label estimated cost as:

    est $0.84

not simply:

    $0.84

Document that the estimate may not equal the user's bill.

------------------------------------------------------------------------------
7.3 Context heat
------------------------------------------------------------------------------

Use transparent thresholds:

- below 70%: normal;
- 70% to 84%: caution;
- 85% to 94%: hot;
- 95% or above: critical.

The standard profile should use color where allowed but remain readable without it.

The fun profile may use:

- caution: `⚠`;
- hot: `🔥`;
- critical: `💨`;

Do not imply the machine is physically damaged.

Do not automatically invoke `/compact`, terminate work, or change model settings.

------------------------------------------------------------------------------
7.4 Git information
------------------------------------------------------------------------------

Where branch/dirty data is not already provided, a local Git query is permitted.

Requirements:

- use `subprocess` with an argument list;
- never use `shell=True`;
- use a short timeout;
- suppress command output on failure;
- cache by stable session ID and repository;
- refresh no more frequently than necessary;
- store only branch and small numeric dirty-state data;
- use a temporary or guardrails cache location;
- never store file names, diff content, or source code;
- handle non-Git directories silently.

------------------------------------------------------------------------------
7.5 Guardrail posture and event counts
------------------------------------------------------------------------------

Read only the existing non-sensitive installed state and audit schema.

The status line may show:

- active safety profile;
- active trust mode;
- installed routing profile;
- warning and denial counts.

Only label counts as session counts when a reliable, existing session correlation is
available.

If correlation is not reliable, either omit the segment or label the period
explicitly, for example:

    today: 1 warn

Do not broaden audit logging merely to create an attractive counter unless the added
identifier is already present in supported hook input and can be stored as a
non-reversible hash.

Never store or display:

- command text;
- command arguments;
- prompts;
- source code;
- file contents;
- secret values;
- full transcript paths;
- raw user identifiers.

Do not show an "allowed" count unless the current audit schema actually records it.
Do not fabricate zeroes.

------------------------------------------------------------------------------
7.6 Complexity/KISS segment
------------------------------------------------------------------------------

Do not calculate repository complexity from scratch on every status-line update.

The fun profile may display:

    KISS ✓

or:

    KISS ⚠

only when a recent local complexity snapshot exists for the current repository.

Otherwise omit the segment.

The segment must link conceptually to the transparent `complexity` command described
below; it is not an AI judgement.

------------------------------------------------------------------------------
7.7 Claude settings merge
------------------------------------------------------------------------------

Structurally merge a managed `statusLine` entry into:

    ~/.claude/settings.json

Use the current documented schema.

The command must reference the immutable installed runtime with the current Python
interpreter, using safe cross-platform quoting.

Preserve every unrelated setting and hook.

If no status line exists:

- install the managed configuration.

If a status line already exists and is unmanaged:

- preserve it;
- report the collision;
- refuse replacement by default;
- permit replacement only with explicit `--force`;
- back up the settings file before replacement.

If the existing status line is project-managed:

- update it idempotently.

Uninstallation:

- remove only the managed status-line property;
- preserve unrelated settings;
- preserve a user-modified managed value unless `--force` is explicit;
- never delete the entire settings file.

Do not configure `refreshInterval` unless a clear need exists.

If used, choose a conservative value and document why.

==============================================================================
8. CODEX STATUS LINE
==============================================================================

Use Codex's native status-line system.

Do not build a custom Codex wrapper or renderer.

------------------------------------------------------------------------------
8.1 Exact native items
------------------------------------------------------------------------------

Verify the current official and installed-version-supported status-line item
identifiers.

Map compact, standard, and fun profiles only to supported native identifiers.

The mapping should prefer:

compact:

- model with reasoning;
- context remaining or usage;
- Git branch.

standard:

- compact fields;
- rate limits;
- token counters;
- concise project/directory information where useful.

fun:

- the standard native item list;
- no invented custom text;
- preview may recommend `/pets` as an optional manual extra;
- do not enable a pet automatically.

If exact identifiers differ by version, use a small compatibility map or fail with a
clear unsupported-version message.

Do not guess.

------------------------------------------------------------------------------
8.2 Safe config.toml modification
------------------------------------------------------------------------------

This is opt-in functionality only.

When the user explicitly runs Codex status-line installation, update only:

    tui.status_line

in the effective user-level Codex `config.toml`.

Honour the same safe CODEX_HOME logic already used by the project.

Requirements:

- parse the existing document with `tomllib` before modification;
- preserve all unrelated text, comments, tables, and ordering;
- do not introduce a general TOML writer;
- use a narrowly scoped textual edit for one managed key;
- add clear begin/end comments around the managed key;
- place the key inside the existing `[tui]` table when present;
- create `[tui]` only when absent;
- validate the complete resulting TOML with `tomllib` before writing;
- back up the file before first mutation;
- use atomic replacement;
- remain idempotent.

If an unmanaged `tui.status_line` already exists:

- preserve it;
- report the current configured value without leaking unrelated config;
- refuse to replace it by default;
- allow replacement only with `--force`;
- create a backup first.

On uninstall:

- remove only the managed key block;
- remove a project-created empty `[tui]` table only when it remains empty and this
  project can prove ownership;
- preserve user changes;
- never rewrite the whole file into normalised TOML.

Do not alter:

- model;
- reasoning effort;
- sandbox;
- approvals;
- network;
- hooks;
- providers;
- analytics;
- terminal title;
- pets;
- theme;
- keybindings.

------------------------------------------------------------------------------
8.3 Codex usage guidance
------------------------------------------------------------------------------

Document and report:

- `/usage` is the native account-usage view;
- `/status` is the native session/status view;
- `/statusline` is the native interactive editor;
- `/pets` is optional fun configuration.

Do not call these commands programmatically.

Do not scrape Codex account data.

Do not claim a Codex dollar cost or local guardrail-event segment when the native
status-line interface does not expose one.

==============================================================================
9. CURSOR CLI
==============================================================================

Be deliberately honest.

Current documented capability:

- terminal-title status indicators through `/status-indicators`;
- no documented programmable custom status-line command comparable to Claude Code.

Therefore:

- `statusline preview --product cursor` must explain the limitation;
- `statusline status --product cursor` must report no managed custom bar;
- `statusline install --product cursor` must make no file change;
- when selected alone, report that custom installation is unsupported and show the
  exact native command;
- when included in `--product all`, skip it without failing supported product
  installation;
- record a manual-information result only when the current state model supports that
  cleanly;
- do not create an internal Cursor config file;
- do not modify `~/.cursor/cli-config.json` for this feature;
- do not infer a hidden `/usage` command;
- do not scrape terminal output, logs, local databases, or account files;
- do not wrap or alias the Cursor executable.

If official documentation gains a programmable status line during implementation,
record and implement only the documented stable interface.

==============================================================================
10. LOCAL ACTIVITY SUMMARY
==============================================================================

Add:

    ai-guardrails activity

Purpose:

- summarise the project's existing redacted local policy-decision events;
- make guardrail behaviour visible without opening raw event files;
- provide useful status-line-adjacent information.

Support:

    --since 1h
    --since 24h
    --since 7d
    --product <id|all>
    --repo <path>
    --format human|json
    --home <path>

Use a simple duration parser or reuse an existing one.

Report only fields already safe in the audit schema, such as:

- observed matches;
- warnings;
- denials;
- operation classes;
- stable rule identifiers;
- product;
- explicitly labelled time window.

Do not report:

- command contents;
- tool arguments;
- prompts;
- file contents;
- secret values;
- raw session identifiers;
- raw usernames.

Do not claim complete product coverage.

For products without deterministic hooks, state that no hook events are expected.

If no events exist, say so plainly.

Do not add a background collector.

==============================================================================
11. COMPLEXITY AND KISS/DRY SIGNALS
==============================================================================

Add:

    ai-guardrails complexity --repo .

This is a transparent local heuristic, not an AI quality score.

Support:

    --repo <path>
    --base <git-revision>
    --format human|json
    --write-snapshot
    --home <path>

Default comparison:

- staged, unstaged, and untracked work against HEAD where practical.

With `--base`:

- compare against the explicit Git revision.

Use Git through `subprocess` argument lists with timeouts.

Do not use `shell=True`.

Do not contact the network.

------------------------------------------------------------------------------
11.1 Measurements
------------------------------------------------------------------------------

Measure only what can be established cheaply and transparently:

- changed-file count;
- added and deleted lines where Git reports them;
- source-file count;
- test-file count;
- documentation-file count;
- generated-file count or ratio where recognised by existing project rules;
- distinct implementation-language extensions touched;
- dependency/build manifest changes;
- infrastructure/governance file changes;
- number of newly added files;
- whether source changed without tests;
- whether more than one new implementation language appears;
- whether a new build or package-management system appears;
- whether generated output dominates the change;
- whether the diff crosses configurable size thresholds.

Use the repository's existing detector knowledge where possible.

Do not parse every language deeply.

Do not try to determine architectural layers with an LLM.

Do not count vendored, dependency-cache, or build-output directories.

------------------------------------------------------------------------------
11.2 Signals
------------------------------------------------------------------------------

Use named, explainable signals.

Examples:

- `large-change-surface`;
- `high-line-churn`;
- `multiple-implementation-languages`;
- `new-build-system`;
- `runtime-dependency-manifest-changed`;
- `source-without-tests`;
- `generated-output-dominates`;
- `high-risk-governance-files`;
- `many-new-files`.

Each signal must include:

- stable identifier;
- measured evidence;
- threshold;
- why it deserves review;
- whether it is informational or review-recommended.

Do not output a fake precision score such as 82.7/100.

A concise human summary may say:

    KISS status: review recommended

or:

    KISS status: no obvious complexity signals

It must also list the reasons.

Do not say a change is bad merely because it is large.

Do not enforce or block based on these signals.

------------------------------------------------------------------------------
11.3 Configurability
------------------------------------------------------------------------------

Keep default thresholds in one small canonical JSON resource.

Do not create a policy language.

Allow repository-specific threshold overrides only through the existing
`.ai-guardrails.json` mechanism if a small compatible extension is possible.

Otherwise defer overrides and document the fixed transparent defaults.

Do not add a second repository-config file.

------------------------------------------------------------------------------
11.4 Snapshot
------------------------------------------------------------------------------

`--write-snapshot` may write a small non-sensitive snapshot under:

    ~/.ai-guardrails/cache/complexity/

Key it by repository identity without storing source content.

Store only:

- schema version;
- repository digest or safe path hash;
- timestamp;
- KISS status;
- signal identifiers;
- aggregate counts.

The Claude fun status line may read a recent snapshot.

Expire or ignore stale snapshots.

Do not store file names by default.

==============================================================================
12. SAFE DEMONSTRATION MODE
==============================================================================

Add:

    ai-guardrails demo

The demo is an onboarding and presentation feature.

It must:

- execute no demonstrated command;
- contact no service;
- modify no repository or home configuration;
- use synthetic payloads;
- reuse the existing explain/simulate/policy engine;
- clearly label every request as synthetic.

Support:

    --scenario core
    --scenario development
    --scenario infrastructure
    --scenario spacelift
    --scenario all
    --format human|json
    --fun
    --no-color

Example core demonstrations:

    git status                                  ALLOW / no denial
    git reset --hard                           DENY
    git push origin feature/example            ALLOW / no denial
    git push --force-with-lease                 DENY
    npm test                                    ALLOW / no denial
    npm publish                                 DENY

Example infrastructure demonstrations:

    terraform plan                              ALLOW / no denial
    terraform destroy                           DENY
    kubectl get pods                            ALLOW / no denial
    kubectl delete namespace payments           DENY
    helm template                               ALLOW / no denial
    helm uninstall                              DENY

Example Spacelift demonstrations:

- read-only run inspection;
- run confirmation denial;
- mutation-tool denial.

Use current policy identifiers rather than hard-coded display-only decisions.

If a policy changes, the demo must reflect the real engine.

The fun output may use shields and warning symbols but no animation or sleep delays.

The JSON output must be deterministic.

==============================================================================
13. RECEIPT ENHANCEMENTS
==============================================================================

Preserve the existing receipt command and schema.

Add:

    --compact
    --fun

Compact output should prioritise:

- repository;
- products;
- files changed;
- verification result;
- warnings and denials where available;
- routing profile;
- complexity snapshot status where available;
- policy version or source digest.

Fun output may add restrained symbols but must not change the facts.

Do not make the receipt depend on a status-line installation.

Do not claim current-session event attribution without evidence.

Do not add prompts, source code, command text, or secrets to receipts.

Machine-readable receipt output must remain stable and free of ANSI codes.

==============================================================================
14. INSTALLATION STATE, OWNERSHIP, AND UPDATE
==============================================================================

Extend the current state only as much as necessary.

State may record:

- installed status-line product;
- profile;
- managed path;
- content hash;
- integration mode;
- manual step;
- renderer/runtime digest;
- capability status.

State must not record:

- vendor account usage;
- model prompts;
- command text;
- terminal contents;
- cost history;
- auth data;
- source code.

Shared runtime ownership:

- reuse the existing immutable runtime;
- do not create a second runtime tree solely for the status-line renderer;
- status-line uninstall must not remove a runtime still used by hooks;
- full uninstall removes the runtime only when no managed feature owns it.

Update:

- preserve profile and integration mode;
- regenerate managed renderer/config safely;
- preserve unmanaged collisions;
- report stale or modified files.

Uninstall:

- remove only managed status-line configuration;
- preserve user profile/configuration files not owned by the project;
- preserve local activity logs and complexity snapshots unless the existing project
  has a documented purge option;
- never delete an entire product configuration directory.

If the state format changes:

- read the previous format;
- migrate on successful write;
- preserve uninstall support for previous state;
- test migration.

==============================================================================
15. PERFORMANCE, PRIVACY, AND SAFETY
==============================================================================

Status-line rendering must be safe to run frequently.

Requirements:

- no network;
- no model call;
- no package installation;
- no shell;
- bounded file reads;
- bounded audit scan;
- cached Git lookup;
- short subprocess timeout;
- no uncaught exception;
- no unbounded log growth caused by the renderer;
- no diagnostics containing raw stdin.

The renderer must not trust status-line input as authority.

Treat every string as display data.

Sanitise or remove:

- control characters;
- newlines inside a segment;
- arbitrary ANSI escape sequences from input;
- OSC sequences;
- excessively long strings.

Only the renderer may add its own known ANSI sequences.

Honour:

    NO_COLOR

Provide an ASCII-safe rendering path.

Never display a full home path when a short project name is enough.

Do not implement clickable links in the first version.

==============================================================================
16. BUILD AND PACKAGE RESOURCES
==============================================================================

Keep canonical profile and threshold data in the existing package resource tree.

Do not add a duplicate root-level canonical directory.

Generated output must be deterministic:

- stable ordering;
- no build timestamp;
- exactly one trailing newline;
- no machine-specific path;
- no terminal color in generated config;
- no generated output written to installed `site-packages`.

Ensure wheel and source distribution contain every required renderer/resource.

The installed status line must work after the source checkout is deleted.

==============================================================================
17. TESTING
==============================================================================

Use the existing standard-library test suite.

No test may modify the real home directory or launch a real agent CLI.

All installation tests use temporary homes.

------------------------------------------------------------------------------
17.1 Profile tests
------------------------------------------------------------------------------

Test:

- profile schema;
- deterministic ordering;
- compact, standard, and fun semantics;
- product capability filtering;
- unsupported segment omission;
- ASCII fallback;
- `NO_COLOR`;
- JSON output contains no ANSI;
- exact terminal newline behaviour.

------------------------------------------------------------------------------
17.2 Claude renderer tests
------------------------------------------------------------------------------

Create official-shape synthetic payload fixtures covering:

- full payload;
- minimal payload;
- null context;
- absent rate limits;
- API-key style cost data;
- subscription rate limits;
- effort absent;
- long model name;
- narrow `COLUMNS`;
- wide `COLUMNS`;
- Git repository;
- non-Git directory;
- missing state;
- installed state;
- recent audit event;
- no reliable session correlation;
- recent complexity snapshot;
- stale complexity snapshot;
- malformed JSON;
- control characters in fields;
- ANSI/OSC content in fields.

Assert:

- no raw input is echoed;
- cost is labelled estimated;
- missing fields do not crash;
- context thresholds render correctly;
- Unicode and ASCII output are valid;
- renderer exits quickly;
- no network or shell is invoked;
- cache contains no source paths or file names beyond the permitted safe hash.

------------------------------------------------------------------------------
17.3 Claude settings tests
------------------------------------------------------------------------------

Test:

- fresh settings;
- unrelated existing settings;
- existing hooks;
- existing unmanaged statusLine collision;
- `--force` backup and replacement;
- managed update;
- idempotent repeated install;
- dry-run;
- uninstall only managed property;
- modified managed property preserved unless forced;
- Windows command path quoting;
- macOS/Linux path quoting;
- alternate home;
- runtime shared with hooks.

------------------------------------------------------------------------------
17.4 Codex tests
------------------------------------------------------------------------------

Use synthetic `config.toml` fixtures:

- empty file;
- no `[tui]` table;
- existing `[tui]`;
- `[tui]` followed by another table;
- comments;
- arrays;
- existing unmanaged `status_line`;
- existing managed status line;
- malformed TOML;
- CODEX_HOME inside selected home;
- CODEX_HOME outside selected home;
- Windows paths;
- Unix paths.

Assert:

- only `tui.status_line` changes;
- comments and unrelated content remain byte-for-byte where possible;
- resulting TOML parses;
- install is idempotent;
- uninstall removes only managed content;
- a project-created empty `[tui]` table is handled safely;
- unmanaged value is protected;
- `--force` creates backup;
- exact item identifiers are validated against the supported map;
- model/sandbox/approval/network/title/pets/theme settings never change.

------------------------------------------------------------------------------
17.5 Cursor tests
------------------------------------------------------------------------------

Test:

- preview reports native `/status-indicators`;
- no custom status line is claimed;
- install makes no file change;
- `--product all` continues installing supported products;
- explicit Cursor selection reports the limitation clearly;
- no undocumented `/usage` guidance appears;
- no Cursor private config path is modified.

------------------------------------------------------------------------------
17.6 Activity tests
------------------------------------------------------------------------------

Test:

- empty audit directory;
- one-hour/day/week windows;
- warn/deny/observe counts;
- product filtering;
- repository filtering where safely supported;
- malformed event ignored with diagnostic;
- no command or tool arguments in output;
- JSON stability;
- products without hooks clearly identified.

------------------------------------------------------------------------------
17.7 Complexity tests
------------------------------------------------------------------------------

Use temporary Git repositories and fixture files.

Test:

- clean repository;
- small source/test change;
- source without tests;
- many files;
- large line churn;
- multiple implementation languages;
- generated output dominance;
- dependency manifest change;
- infrastructure/governance files;
- untracked files;
- explicit base revision;
- non-Git directory;
- excluded build/cache/vendor paths;
- deterministic JSON;
- snapshot creation;
- stale snapshot;
- no file contents stored.

Assert the output explains every signal and never gives a pseudo-precise score.

------------------------------------------------------------------------------
17.8 Demo tests
------------------------------------------------------------------------------

Test:

- no real command execution;
- deterministic scenarios;
- decisions come from the real policy evaluator;
- human and JSON formats;
- no delay in `--fun`;
- all synthetic requests are labelled;
- changed policy fixtures change demo results.

------------------------------------------------------------------------------
17.9 Receipt tests
------------------------------------------------------------------------------

Test:

- existing default output remains compatible;
- compact output;
- fun output;
- no ANSI in JSON;
- no fabricated activity;
- complexity snapshot optional;
- no prompt/source/command leakage.

------------------------------------------------------------------------------
17.10 Consumer and package tests
------------------------------------------------------------------------------

From a built wheel in a clean temporary environment, outside the repository, run:

    ai-guardrails statusline preview --product all --profile standard
    ai-guardrails statusline install --product claude \
      --profile standard --home <temp-home> --dry-run
    ai-guardrails statusline install --product claude \
      --profile standard --home <temp-home>
    ai-guardrails statusline status --product all --home <temp-home>
    ai-guardrails activity --home <temp-home>
    ai-guardrails complexity --repo <fixture-repo>
    ai-guardrails demo --scenario all
    ai-guardrails statusline uninstall --product claude \
      --home <temp-home>

Confirm:

- no source-checkout dependency;
- no write to `site-packages`;
- no real product config;
- no network;
- no external runtime dependency.

==============================================================================
18. DOCUMENTATION
==============================================================================

Update README.md without overwhelming the quick start.

The first-time three-command journey must remain before optional terminal UX.

Add a short section:

    Optional terminal visibility

Show:

    ai-guardrails statusline preview --product all --profile standard
    ai-guardrails statusline install --product all --profile standard --dry-run
    ai-guardrails statusline install --product all --profile standard
    ai-guardrails statusline status --product all

Clearly document:

Codex:

- native configurable item status line;
- exact fields the selected profile configures;
- `/usage`;
- `/statusline`;
- optional `/pets`;
- no custom project audit/KISS segment.

Claude Code:

- programmable managed status line;
- context, model, effort, rate limits, estimated cost, duration, Git, posture, and
  safely available activity;
- cost-estimate caveat;
- profile examples;
- collision behaviour;
- removal.

Cursor CLI:

- `/status-indicators`;
- no currently documented programmable custom bar;
- no `/usage` claim unless the official docs now support it;
- no files modified by this feature.

Document:

- `activity`;
- `complexity`;
- `demo`;
- compact/fun receipts;
- privacy model;
- no background telemetry;
- no prompt/source/command storage;
- no exact cost-saving promise;
- no default cosmetic changes.

Update docs/architecture.md with the simple flow:

    product/session data
            |
            v
    local renderer or native product configuration
            |
            +--> status line
            +--> no network
            +--> no prompt/source capture

Update docs/threat-model.md:

- status-line data is display data, not authority;
- status lines are not security boundaries;
- cost values may be estimates;
- local audit counts cover only supported hooks;
- complexity signals are heuristics;
- a compromised local account can alter local configuration;
- ANSI/control-sequence sanitisation is required;
- no vendor parity should be implied.

Update docs/compatibility.md with current official sources and verification date.

Add a focused document if useful:

    docs/terminal-experience.md

Do not create a documentation site.

==============================================================================
19. CI
==============================================================================

Retain the current full validation pipeline.

Add focused cross-platform tests for:

- Claude renderer;
- settings merge;
- Codex TOML edit;
- wheel-installed status-line commands.

Use the existing CI structure.

Do not multiply every expensive test across every OS unnecessarily.

A sensible approach:

- full suite on Ubuntu;
- focused terminal-UX smoke matrix on Windows, macOS, and Ubuntu.

Do not install or launch real Codex, Claude, or Cursor in CI.

Do not add vendor credentials.

==============================================================================
20. OUT OF SCOPE
==============================================================================

Do not implement:

- a universal CLI wrapper;
- screen scraping;
- undocumented local usage database parsing;
- vendor billing API calls;
- account authentication;
- subscription management;
- remote telemetry;
- background polling;
- a daemon;
- a dashboard;
- a web UI;
- a TUI;
- terminal animation;
- sound;
- automatic context compaction;
- automatic model changes;
- automatic session termination;
- exact money-saved claims;
- an AI complexity score;
- automatic policy changes from complexity signals;
- a Cursor custom status bar unless officially documented;
- custom Codex renderer text unless officially documented;
- IDE status bars;
- shell prompt integration;
- native installers;
- unrelated repository refactoring.

==============================================================================
21. ACCEPTANCE CRITERIA
==============================================================================

Before declaring completion:

1. Inspect the final repository state.
2. Build generated output.
3. Run canonical validation.
4. Run the complete existing and new test suite.
5. Build wheel and source distribution.
6. Install the wheel into a clean temporary environment.
7. Run the consumer journey outside the repository.
8. Verify Claude status-line rendering with full/minimal/malformed fixtures.
9. Verify Codex config changes preserve unrelated TOML.
10. Verify Cursor receives no fake custom implementation.
11. Verify no real home or product configuration changed.
12. Verify no network access occurred.
13. Verify no prompt, source, command, or secret data is stored.
14. Verify status-line execution is bounded and fast.
15. Verify the default no-argument installation still makes no status-line change.
16. Build twice and confirm the second build produces no generated diff.
17. Run `git diff --check`.
18. Review the final diff for:
    - duplicate installers;
    - duplicate audit formats;
    - a generic monitoring framework;
    - unnecessary abstractions;
    - runtime dependencies;
    - shell wrappers;
    - private vendor-file assumptions;
    - unsupported capability claims;
    - accidental default enablement;
    - excessive README complexity.

At minimum, run the current repository equivalents of:

    python tools/guardrails.py build
    python tools/guardrails.py validate
    python -m unittest discover -s tests -v
    python -m build --outdir release
    python tools/guardrails.py statusline preview \
      --product all --profile standard
    python tools/guardrails.py demo --scenario all
    git diff --check
    git status --short

Also run installed-wheel commands from outside the source tree with temporary homes.

Do not commit or push.

==============================================================================
22. FINAL REPORT
==============================================================================

The final response must include:

- concise architecture summary;
- files materially added or changed;
- status-line profiles implemented;
- exact Codex integration and supported native items;
- exact Claude integration and displayed fields;
- Cursor limitation and native guidance;
- collision and backup behaviour;
- state migration, if any;
- activity command behaviour;
- complexity signals and thresholds;
- demo scenarios;
- receipt enhancements;
- privacy and performance guarantees;
- commands run;
- complete test results;
- wheel smoke-test result;
- cross-platform checks;
- any checks skipped;
- unresolved product limitations;
- confirmation that no real workstation configuration was modified;
- confirmation that no vendor account was contacted;
- confirmation that no commit, push, tag, release, or publication occurred.

Do not claim:

- Cursor has a programmable bar without official support;
- Codex displays custom guardrail segments without official support;
- estimated Claude cost equals the user's bill;
- local audit events cover unsupported product surfaces;
- complexity signals prove overengineering;
- the feature saves a specific amount of money.
