# Quick user guide

This is the short version. Python 3.11+ and [pipx](https://pipx.pypa.io/) are recommended. Do not use `sudo` or an elevated shell.

## Install

Install the published package, then preview before writing anything:

```sh
pipx install ai-engineering-guardrails

ai-guardrails install --dry-run
ai-guardrails install
ai-guardrails status
```

Reviewed tag/commit, local-clone, and local-wheel installs remain available alternatives:

```sh
pipx install 'git+https://github.com/ZarrenSpryXplor/ai-engineering-guardrails.git@<reviewed-tag-or-full-commit>'
pipx install .
pipx install ./dist/ai_engineering_guardrails-<version>-py3-none-any.whl
```

No pack, profile, model, cloud login, or target mapping is required. The `ai-guardrails install` command itself does not contact remote services.

## Cursor: one manual step

```sh
ai-guardrails print-cursor-rules
```

Open **Cursor Settings / Customize / Rules / User Rules**, paste the complete output, and save it. The command prints the rules; it does not install them.

## VS Code, Visual Studio, and JetBrains

VS Code Copilot gets a native user instruction file and a **Preview** `PreToolUse` hook when no project-managed Claude-compatible hook already covers it. Hooks can be disabled by an organisation and do not cover inline suggestions.

Visual Studio gets `~/copilot-instructions.md` (the documented `%USERPROFILE%\copilot-instructions.md` on Windows). Skills require Visual Studio 18.5+; custom agents require 18.4+ and are user-selectable roles. Hooks and subagents are unsupported, so native approvals remain in charge.

JetBrains intentionally needs a couple of manual confirmations:

```sh
ai-guardrails jetbrains print-chat-instructions
ai-guardrails jetbrains export-project-rules --repo . --dry-run
ai-guardrails jetbrains export-project-rules --repo .
```

Paste the first command's output in **Settings > Tools > AI Assistant > Prompt Library > General > Chat Instructions**. After exporting, open **Settings > Tools > AI Assistant > Rules** and confirm the rule is **Always**. Register `~/.agents/skills` under **Settings > Tools > AI Assistant > Skills > Manage Skill Directories**. The installer does not change JetBrains operation modes, approvals, MCP settings, or plugins. Copilot custom agents in JetBrains are Preview/manual, and no JetBrains hook is installed.

## Day-to-day use

Work normally. Skills are short, on-demand procedures rather than another giant always-loaded rulebook. The default install keeps deterministic enforcement from all stable packs but exposes only six core skills plus ten contextual language/shared skills. Thirteen specialist infrastructure, delivery, operations, and technical-writing skills remain packaged; `install --skill-catalogue all` exposes the complete 29-skill catalogue and `--skill-catalogue contextual` explicitly restores the smaller managed set. See the [skills catalogue](skills.md) for exact names, tiers, and deliberately reduced `--pack ID` installations.

Where the selected product supports explicit skill invocation, ask for a skill by its exact `workstation-…` name when you want a specific workflow—for example `workstation-code-review`, `workstation-python`, `workstation-kubernetes`, or `workstation-incident-analysis`. Product-specific discovery and invocation remain product-controlled, so an installed directory is not proof that every session activated a skill. `ai-guardrails packs detect --repo .` is a useful offline hint about which stack skills fit the repository; it does not run a tool or grant permission.

Default behavior:

- local source edits, builds, tests, lint, rendering, validation, and plans are available;
- remote infrastructure changes, production changes, publication, credential reads, and destructive operations are denied;
- model routing is off, so your primary model is unchanged;
- audit entries are local, redacted, and contain no command arguments or source.

See what is active:

```sh
ai-guardrails status --repo .
```

Human output uses compact tables and terminal-aware colour. Use `--no-color` (or the common `NO_COLOR` environment variable) when styling is not useful. Validation, status, and other report-style commands offer deterministic JSON for scripts:

```sh
ai-guardrails validate --format json
ai-guardrails status --repo . --format json
ai-guardrails skills audit --format json
```

Machine formats write one JSON document to standard output and do not include Rich styling.

For substantive technical prose, use `workstation-technical-writing`. Its ASD-STE100-informed guidance preserves technical terms and facts without claiming formal compliance. The optional offline audit is advisory:

```sh
ai-guardrails docs audit --repo .
ai-guardrails docs audit --path README.md
```

See [technical writing](technical-writing.md) for scope, exclusions, and the standard provenance boundary.

## Optional routing

Routing is off by default. Enabling it installs five product-native roles for bounded exploration, test-output analysis, ordinary implementation, independent review, and verification. It does not inspect your prompts or automatically broker model calls: you or the primary agent still decide whether delegation is useful.

If you followed the installation steps above, preview and enable the recommended profile on the existing managed Codex installation:

```sh
ai-guardrails routing show --profile balanced --product codex
ai-guardrails routing set balanced --product codex --dry-run
ai-guardrails routing set balanced --product codex
ai-guardrails status --product codex --show-routing
```

For a fresh installation, use `install --product codex --routing-profile balanced` with the same dry-run/apply sequence. In a session, a concrete request is enough where native delegation is supported:

> Use `workstation_explorer` to map the relevant files and constraints. Keep it read-only and return evidence only; do not edit.

Codex keeps underscore role names; the other rendered products use hyphens, such as `workstation-explorer`. Visual Studio roles are selected by the user rather than run as subagents, and JetBrains routing is a manual Preview bundle.

Use `routing set none --product codex --dry-run` and then the same command without `--dry-run` to reconfigure the managed product without routing when no model override is stored. Read the [engineer routing guide](routing-and-cost.md) for profile selection, model overrides, and product activation, and review its [disable limitations](routing-and-cost.md#inspect-troubleshoot-and-disable) before applying that full installation transaction.

## Optional terminal UX

Terminal UX is separate from routing and remains off unless selected. It shows distinct local facts—context capacity, product-native token/rate-limit views, a vendor-provided cost estimate where Claude exposes one, content-free guardrail counts, and deterministic complexity signals. It never reads account, billing, or transcript stores.

```sh
ai-guardrails statusline preview --product all --profile standard
ai-guardrails statusline install --product all --profile standard --dry-run
ai-guardrails statusline install --product all --profile standard
ai-guardrails activity --since 24h
ai-guardrails complexity --repo . --write-snapshot
ai-guardrails receipt --repo . --product all --compact
```

Claude receives the managed command-based line and requires workspace trust. Codex receives an explicit marker-owned native `tui.status_line` edit that preserves unrelated `config.toml` text; `ai-guardrails statusline print-codex-setup` prints the same reviewable native-field recommendation. Cursor uses the user-controlled `/status-indicators` title feature; it has no documented programmable usage bar. `ai-guardrails demo --scenario all` is entirely synthetic and executes none of the operations it displays. The [terminal UX guide](terminal-ux.md) covers profiles, activation limits, cache behavior, and removal.

## Ansible

The Ansible pack is detected from distinctive files such as `ansible.cfg`, `.ansible-lint`, `galaxy.yml`, execution-environment metadata, Molecule configuration, or collection/role requirements.

Check detection:

```sh
ai-guardrails packs detect --repo .
```

Preferred source validation after reviewing repository configuration and plugins:

```sh
ansible-playbook --syntax-check playbooks/site.yml
```

The default guardrails:

- treat playbook, ad hoc, pull, and console execution, including `--check`, as remote mutation;
- deny Vault `view`, `edit`, and `decrypt` in agent tool calls;
- warn before broad inventory or active-configuration output because it may contain secrets;
- deny Galaxy publication, hosted mutation, and certificate/signature-validation bypass;
- never contact managed hosts during repository tests.

Explain a decision without running it:

```sh
ai-guardrails explain \
  --command 'ansible-playbook -i inventories/dev playbooks/site.yml' \
  --pack ansible
```

Advanced non-production execution requires the `infrastructure-nonprod` safety profile and an exact inventory mapping in `~/.ai-guardrails/targets.json`:

```json
{
  "schema_version": 1,
  "classifications": {
    "ansible_inventories": {
      "inventories/dev": "dev"
    }
  }
}
```

Names do not imply safety. An unmapped inventory is protected, and direct `prd` mutation remains denied.

## Update

```sh
ai-guardrails update --dry-run
ai-guardrails update
ai-guardrails status
```

## Remove

```sh
ai-guardrails uninstall --dry-run
ai-guardrails uninstall
pipx uninstall ai-engineering-guardrails
```

The dry run previews removal without writing. The next command removes only recorded managed product content, and the last removes the pipx application. User-modified managed files are retained unless `--force` is explicit.

## Troubleshoot

```sh
ai-guardrails doctor
ai-guardrails diff-installed
```

Continue through the [operator documentation](README.md) for architecture, advanced profiles, waivers, scanning, enterprise examples, and contributor guidance.
