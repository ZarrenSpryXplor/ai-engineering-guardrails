# Technical writing

ASD-STE100 Simplified Technical English is a controlled natural language and an international standard for technical documentation. The [official STEMG site](https://www.asd-ste100.org/) identified Issue 9, released 15 January 2025, as current when this project last verified it on 2026-08-10.

This project uses a small set of ASD-STE100-informed principles to make agent-generated technical prose more accurate, direct, consistent, and concise. It does not reproduce the standard, its rule tables, or its controlled dictionary.

## Specialist skill

`workstation-technical-writing` applies to substantive READMEs, installation and operator guides, runbooks, procedures, troubleshooting, architecture documents, warning text, and CLI/help content. It preserves technical facts and exact commands, identifiers, API fields, configuration keys, log text, quotations, legal text, third-party text, and generated machine-readable content. Ordinary conversation is outside its automatic scope.

The skill is specialist and is not part of the fresh default catalogue. Select `--skill-catalogue all`, or select the `technical-writing` pack explicitly for a deliberately reduced installation. Product discovery and activation remain product-controlled.

This milestone does not add repository preferred-term configuration or a controlled-dictionary engine. A canonical-term mapping can be considered later only if an existing configuration consumer establishes a concrete need.

## Advisory audit

The offline audit reports project clarity findings without rewriting text:

```sh
ai-guardrails docs audit --repo .
ai-guardrails docs audit --path README.md
ai-guardrails docs audit --format json
```

The initial checks cover numbered procedural sentences above a transparent 45-word review threshold and two explicit filler prefaces. They exclude code blocks, inline code, headings, block quotations, quoted text, and URLs. Findings use `review` or `info`; they are advisory and do not block installation or establish formal compliance.

## Copyright and compliance boundary

ASD owns ASD-STE100, and the name is protected by copyright and trademark. The project does not redistribute the official standard or dictionary, use the ASD logo, or claim ASD/STEMG sponsorship, approval, or certification. This project is not an ASD-approved or certified checker.

ASD and STEMG state that they do not endorse, certify, or authorise software tools, including AI-based tools. When exact contractual or formal compliance is required, [request the current official copy from STEMG](https://www.asd-ste100.org/STE_downloads.html), reverify the current issue, and use an appropriate qualified review process. The built-in skill and audit alone cannot establish formal ASD-STE100 compliance.
