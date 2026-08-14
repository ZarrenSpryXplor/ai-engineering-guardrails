---
name: workstation-technical-writing
description: Technical documentation with ASD-STE100-informed controlled English for READMEs, runbooks, procedures, architecture docs, troubleshooting, and CLI/help text.
---

# Technical writing

Use this skill for substantive technical prose: READMEs, installation and operator guides, runbooks, procedures, architecture documents, ADR/TDS-style documents, troubleshooting, recovery instructions, warnings, support instructions, and CLI/help text. Apply the clarity principles to comments and docstrings only when they preserve accurate programming terminology.

Do not automatically rewrite source identifiers, API or command names, class or function names, log or exception text, protocol fields, configuration keys, quotations, legal or licence text, third-party text, generated machine-readable formats, or ordinary conversation. Preserve literal values and product names exactly. Necessary domain terminology remains permitted.

## Priorities

Use this order:

1. Correctness.
2. Safety.
3. Unambiguous meaning.
4. Consistent terminology.
5. Concise structure.
6. Stylistic preference.

Do not shorten text if the edit removes a condition, warning, exception, recovery step, or technical distinction. Do not replace precise engineering language with vague plain English. The reviewed text should normally be shorter or equally concise.

## Writing principles

- Use direct technical sentences. Prefer shorter structures when they improve comprehension.
- Put one primary instruction or action in each procedural step where practical.
- Use the same term for the same concept. Do not introduce synonyms for variety, and use one meaning for a technical term within a document.
- Identify the actor, action, object, and important condition. Use active constructions when they make these relationships clearer.
- Use direct imperatives in procedures. For example: `Validate the configuration before you install it.`
- Put a condition before or with its consequence. For example: `If validation fails, stop the installation.`
- Make pronouns and references unambiguous.
- Define an abbreviation on first meaningful use when the intended audience might not know it.
- Use consistent forms for prerequisites, warnings, expected results, and recovery information.
- Remove filler and repetition that do not change meaning.
- Preserve accurate technical vocabulary. Do not sacrifice accuracy for shortness.

For a non-trivial procedure, use the following structure when it helps the reader: purpose or outcome, preconditions, steps, expected result, and failure or recovery information. Do not require all headings for a trivial procedure. Start a step with a clear action where practical, identify its target, and give an expected result when verification matters. Never invent a value or requirement to make the prose look more specific.

## Review procedure

1. Identify the document purpose, audience, and requested scope.
2. Preserve all technical facts and inspect repository terminology before editing.
3. Correct ambiguity before shortening text.
4. Use direct procedural language and remove unnecessary repetition.
5. Preserve necessary cautions, warnings, conditions, examples, exceptions, and recovery information.
6. Keep commands, identifiers, literal values, API fields, and product names exact.
7. Review terminology consistency and correct only the smallest necessary passages.
8. Run `ai-guardrails docs audit --path <document>` or the repository equivalent when available. Treat findings as advisory review prompts.
9. Report any ambiguity that cannot be resolved from authoritative repository evidence.
10. Never claim formal ASD-STE100 compliance from this review or audit.

## Agent-generated prose

Remove long introductions, repeated requests or conclusions, speculative architecture, unnecessary benefits sections, excessive headings, verbose transitions, inflated claims, obvious command-by-command explanations, and implementation detail that users do not need. Do not replace established terms merely for variety. Prefer necessary, factual, actionable, and concise content over promotional or exhaustive prose unless the task requires it.

## ASD-STE100 boundary

This guidance is informed by broadly applicable controlled-English principles. It does not reproduce the complete ASD-STE100 rules or controlled dictionary. Read the short [ASD-STE100 provenance and limitations](references/asd-ste100.md) before making an ASD-related claim. Exact contractual or formal compliance work requires a current authorized copy of the standard and an appropriate qualified review process outside this automated guarantee.

## Completion

Complete when the requested prose is accurate, scoped, concise, terminology-consistent, and verified against available technical evidence. State unresolved facts and audit limitations. Do not claim ASD approval, certification, or formal ASD-STE100 compliance.
