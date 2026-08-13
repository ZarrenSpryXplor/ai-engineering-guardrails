---
name: workstation-architecture-diagramming
description: Architecture diagram creation and review for software, cloud, deployment, network, data-flow, and interaction views using C4-informed views, selected UML, ERDs, Mermaid, or diagrams.net (.drawio) XML.
---

# Architecture diagramming

## Scope

Use this skill to create, update, review, or standardize software or cloud diagrams: context, container, deployment, runtime, network, trust-boundary, data-flow, interaction, sequence, state-transition, ERD, Mermaid, and editable `.drawio` views or source.

This skill owns visual models and diagram source. `workstation-technical-writing` owns prose-only architecture documentation. Exclude mechanical, electrical, civil, manufacturing, PCB, CAD, and construction drawings; quantitative charts; UI wireframes and mockups; ordinary prose-only documentation; complete enterprise modeling; and formal compliance or certification assessment.

BPMN and ArchiMate are outside v1. If either is required, state this limit and require a current authorized source and qualified review; do not invent conformance guidance.

Read [standards and notation](references/standards-and-notation.md) before choosing notation, icons, or provenance claims. Read [diagrams.net source](references/diagrams-net.md) before changing or validating `.drawio` XML.

## Evidence-first workflow

1. Identify the audience, decision, scope, viewpoint, abstraction, and output format.
2. Inspect source, infrastructure/deployment definitions, interfaces, data models, and existing diagrams.
3. Separate observed facts, user facts, assumptions, and unknowns. Never invent services, protocols, placement, flows, controls, dependencies, availability, or ownership.
4. Ask only when an unknown materially changes the view; otherwise label it visibly.
5. Give each diagram one primary question and split overloaded views.
6. Choose the smallest useful view and one authoritative source format.
7. Create or revise the smallest useful source artifact.
8. Check semantics, structure, available rendering, accessibility, and provenance.
9. Report source and derived files, assumptions, unresolved facts, and checks run.

## Select the view by concern

- **Software boundaries and dependencies:** Use a C4-informed system-context or container view. Use deployment for runtime instances, environments, regions, clusters, nodes, or hosting boundaries. Do not require every level. For Mermaid, use stable flowcharts, not experimental C4 syntax.
- **One interaction over time:** Use a UML-informed sequence view with one scenario, meaningful participants, direction, important messages, asynchronous behavior, and relevant failures.
- **Lifecycle behavior:** Use a UML-informed state view with valid states, triggers or conditions, terminal states, and material invalid or exceptional transitions.
- **Data structure:** Use a Crow's Foot-style ERD. Declare conceptual, logical, or physical scope; show cardinality and optionality; never imply that conceptual entities are tables.
- **Network, security, or deployment topology:** Show evidenced ownership, network, availability-zone, region, environment, and trust boundaries. Label known ingress, egress, protocols, ports, encryption, identity, and classifications. Never put a managed service inside a network it does not occupy.
- **Data flow:** Show sources, sinks, transformations, stores, direction, batch or streaming behavior, trust-boundary crossings, and known classification.
- **Simple decision or operational flow:** Use a compact flowchart. Do not use BPMN for ordinary software interactions merely for visual formality.

## Choose and validate the source

Use Mermaid for simple repository-native source when stable `flowchart`, `sequenceDiagram`, `stateDiagram`, or `erDiagram` syntax is adequate. Avoid experimental C4 and `architecture-beta`. Keep IDs stable, labels readable and quoted when punctuation can break parsing, and views compact. Use an existing local renderer; never install one. Otherwise report source review only.

Treat `.drawio` as editable native diagrams.net output, not a standard or universal interchange. Emit uncompressed UTF-8 XML with stable unique IDs, deterministic order/geometry, resolved references, explicit vertex/edge geometry, and escaped text. Default to one page. Exclude compression, scripts, remote images, secrets, credentials, and sensitive URLs. Use generic shapes or current official icons already available for concrete services. Never download assets.

Apply these `.drawio` validation levels accurately:

1. **Structural review:** Check well-formed XML, expected elements, unique IDs, resolved parent/source/target references, required geometry, and absent external images or scripts.
2. **diagrams.net validation:** With an existing local app or CLI, open or render without installation and confirm no repair prompt.
3. **Visual inspection:** Check clipping, overlap, spacing, routing, labels, contrast, and consistency; fix material defects.

Never call structural XML review render validation. Do not maintain independent Mermaid and `.drawio` sources of truth. For a requested conversion, name the authoritative source and regeneration limits.

## Quality and completion

When known, include a concise title, type/viewpoint, purpose/audience, system and diagram scope, `as-is`, `to-be`, `reference`, or equivalent status, environment, revision or last-updated metadata, explicit boundaries, named elements with short responsibilities, directional labeled relationships, material protocol/data/event labels, and a compact legend for non-obvious semantics. Never invent metadata.

Keep one abstraction level. Label connectors and use separate arrows when direction matters. Keep casing, line weight, arrowheads, spacing, and shape meaning consistent. Limit crossings; prefer orthogonal topology connectors. Ensure contrast, do not rely on color alone, and check text at output size. Use generic shapes for logical concepts and current official icons only for evidenced services.

Complete when the view answers its question, matches evidence, has sound source and legible output, does not rely on color, and makes no claim of formal conformance, certification, approval, or endorsement.
