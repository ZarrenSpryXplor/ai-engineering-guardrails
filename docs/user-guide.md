# Quick user guide

This is the short version. Python 3.11+ and [pipx](https://pipx.pypa.io/) are recommended. Do not use `sudo` or an elevated shell.

## Install

Install the application from a reviewed clone, then preview first:

```sh
git clone https://github.com/ZarrenSpryXplor/ai-engineering-guardrails.git
cd ai-engineering-guardrails
pipx install .

ai-guardrails install --dry-run
```

After reviewing a specific tag or full commit, a direct VCS install is also available:

```sh
pipx install 'git+https://github.com/ZarrenSpryXplor/ai-engineering-guardrails.git@<reviewed-tag-or-full-commit>'
```

This repository does not publish a package as part of its normal workflow.

Install for locally detected Codex, Claude Code, Cursor, VS Code Copilot, Visual Studio Copilot, and JetBrains IDE evidence:

```sh
ai-guardrails install
ai-guardrails status
```

No pack, profile, model, cloud login, or target mapping is required. Installation does not contact remote services.

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

Work normally. Skills are short, on-demand procedures rather than another giant always-loaded rulebook. The default install ships six core workstation skills plus 22 capability-pack skills. See the [skills catalogue](skills.md) for the exact names and use cases.

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

The first command removes only recorded managed product content; the last removes the pipx application. User-modified managed files are retained unless `--force` is explicit.

## Troubleshoot

```sh
ai-guardrails doctor
ai-guardrails diff-installed
```

Use the main [README](../README.md) for architecture, advanced profiles, waivers, scanning, enterprise examples, and contributor commands.
