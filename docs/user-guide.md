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

Install for locally detected Codex, Claude Code, and Cursor products:

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

## Day-to-day use

Work normally. Relevant skills are loaded on demand for the repository's detected stack.

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
```

Uninstall removes only recorded managed content. User-modified managed files are retained unless `--force` is explicit.

## Troubleshoot

```sh
ai-guardrails doctor
ai-guardrails diff-installed
```

Use the main [README](../README.md) for architecture, advanced profiles, waivers, scanning, enterprise examples, and contributor commands.
