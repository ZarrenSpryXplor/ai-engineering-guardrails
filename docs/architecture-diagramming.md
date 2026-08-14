# Architecture diagramming

Use `workstation-architecture-diagramming` to create, update, review, or standardize software and cloud architecture diagrams. Use [technical writing](technical-writing.md) for prose-only architecture documents.

The skill is specialist and is not part of the fresh default catalogue. Select `--skill-catalogue all`, or select the `architecture-diagramming` pack explicitly for a deliberately reduced installation. Product discovery and activation remain product-controlled.

## Define the view

Before you change a diagram, identify:

- the primary question and decision;
- the audience;
- the system boundary and abstraction level;
- the viewpoint, such as context, deployment, interaction, state, data, or trust boundary;
- whether the view is `as-is`, `to-be`, or `reference`;
- the known facts, assumptions, and unresolved facts;
- the authoritative source format.

Do not add a diagram only to decorate a document. Use a table or prose when it communicates the information more directly.

## Select a view

| Primary concern | Preferred view | Required content |
| --- | --- | --- |
| Software boundaries and dependencies | C4-informed system-context or container view | Named elements, responsibilities, boundaries, and directional relationships. |
| Runtime placement | Deployment view | Evidenced environments, regions, nodes, clusters, networks, and hosting boundaries. |
| One interaction over time | UML-informed sequence view | One scenario, meaningful participants, message direction, and material failure paths. |
| Lifecycle behaviour | UML-informed state view | Valid states, triggers or conditions, exceptional transitions, and terminal states. |
| Data structure | Conceptual, logical, or physical Crow's Foot-style ERD | Declared model level, entities, cardinality, and optionality. |
| Security or data movement | Trust-boundary, network, or data-flow view | Sources, sinks, stores, direction, boundary crossings, and known protocols or classifications. |
| A small decision or operational path | Flowchart | One bounded decision or process with labelled branches. |

BPMN and ArchiMate conformance guidance is outside the skill's current scope. Do not infer formal notation conformance from a generic flowchart or an architecture view.

## Select one authoritative source

Use inline Mermaid for compact repository documentation when stable `flowchart`, `sequenceDiagram`, `stateDiagram`, or `erDiagram` syntax is sufficient. Do not use Mermaid's experimental C4 or `architecture-beta` syntax. Keep node identifiers stable, quote labels that contain punctuation, and keep each diagram focused on one question.

Use an uncompressed UTF-8 `.drawio` file only when shape-level editing or manual layout is required. Treat it as diagrams.net source, not as a universal interchange format. Do not maintain independent Mermaid and `.drawio` versions as equal sources of truth.

Do not add generated PNG, PDF, or SVG copies unless a current repository consumer requires them. If you add a derived file, identify its authoritative source and regeneration limits.

## Follow repository conventions

- Introduce each diagram with its audience, primary question, scope, and status when these facts are known.
- Keep one abstraction level in each view.
- Label relationships and branch conditions.
- Use separate arrows when direction has different meanings.
- Use adjacent prose to state important limits and conclusions.
- Do not use colour as the only source of meaning.
- Use generic shapes for logical concepts.
- Link to an authoritative diagram instead of copying its source into another document.
- Never add credentials, secrets, sensitive URLs, remote images, embedded scripts, or automatically downloaded assets.

## Validate a diagram

1. Compare every element and relationship with repository source, configuration, tests, or user-provided facts.
2. Review the source for stable identifiers, labelled relationships, consistent terminology, and one abstraction level.
3. Use an existing local renderer when one is available. Do not install or download a renderer for validation.
4. Inspect rendered output for clipping, overlap, spacing, connector routing, labels, contrast, and readable text.
5. If no renderer is available, report source review only. Do not call it render validation.
6. Run the documentation audit and local link checks after you change surrounding Markdown.

For `.drawio`, also check well-formed XML, unique IDs, resolved parent/source/target references, required geometry, and the absence of scripts or external images. Opening the file without a repair prompt and visually inspecting it are separate checks.

## Maintained repository views

| Concern | Authoritative document |
| --- | --- |
| Canonical source, build, local installation, and runtime boundaries | [Architecture](architecture.md) |
| Policy evidence lifecycle | [Policy authoring](policy-authoring.md#attach-evidence-metadata-not-duplicate-prose) |
| Task-contract and evidence evaluation | [Evidence and assurance](evidence-and-assurance.md) |
| Terminal status and local signal flow | [Terminal UX](terminal-ux.md) |
| Static role rendering and bounded task allocation | [Routing and cost](routing-and-cost.md) |
| Protected release and Trusted Publishing flow | [Releasing to PyPI](releasing.md) |

These views are repository-native communication aids. They do not establish formal conformance, certification, approval, or endorsement by a standards body, notation owner, diagram tool, or cloud provider.
