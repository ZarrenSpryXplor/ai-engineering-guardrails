# Standards and notation provenance

Last project verification: 2026-08-13.

Use these sources to confirm scope and provenance before making notation or asset claims. They are evidence, not permission to redistribute protected material or a substitute for the current authoritative publication.

## Architecture descriptions and views

- [ISO/IEC/IEEE 42010:2022](https://www.iso.org/standard/74393.html) is an architecture-description framework organized around stakeholders, concerns, viewpoints, and views. It is not a drawing notation and does not prescribe one universal diagram set. Use it to clarify why a view exists and which concerns it addresses.
- [C4 diagrams](https://c4model.com/diagrams) provide a practical, notation-independent model for communicating software architecture at several abstraction levels. [C4 notation guidance](https://c4model.com/diagrams/notation) emphasizes clear elements, types, descriptions, boundaries, and relationships. Use only the levels needed for the current question; this project does not claim C4 conformance.

## Interaction, state, data, and process notation

- [UML 2.5.1](https://www.omg.org/spec/UML/2.5.1/) is the provenance source for the selected sequence and state semantics in this skill. The skill uses a small useful subset and does not reproduce UML notation tables or establish formal UML conformance.
- Crow's Foot-style ERDs communicate entity cardinality and optionality. State whether a model is conceptual, logical, or physical. This project does not designate that common style as a complete database-modeling standard.
- [BPMN 2.0.2](https://www.omg.org/spec/BPMN/2.0.2/) is a related business-process specification, but BPMN-conformance guidance is intentionally excluded from v1. Do not infer BPMN semantics from a generic flowchart.
- [ArchiMate licensed downloads](https://www.opengroup.org/archimate-licensed-downloads) define a licensed-access boundary. Its licensing and AI-use boundaries require a separate current rights review. ArchiMate 4 is outside v1: do not use or summarize its specification without an authorized source.

## Diagram tools and provider assets

- [Mermaid C4 documentation](https://mermaid.js.org/syntax/c4.html) identifies Mermaid's C4 syntax as experimental. Use stable flowchart primitives for C4-informed repository diagrams in this skill. Stable Mermaid sequence, state, and entity-relationship syntax may be used when it expresses the view adequately.
- Use generic shapes by default. When a concrete service benefits from a provider icon, use only a current official asset that is already supplied or locally available, and follow its terms and naming guidance. Official sources are [AWS Architecture Icons](https://aws.amazon.com/architecture/icons/), [Azure Architecture Icons](https://learn.microsoft.com/en-us/azure/architecture/icons/), and [Google Cloud icons](https://cloud.google.com/icons). Do not download assets automatically or imply that an icon proves service placement, ownership, or configuration.

## Claim boundary

This project does not redistribute any standard, reproduce controlled notation tables, or bundle standards-body or cloud-provider logos. Standards-informed means that the guidance draws on selected public concepts; it does not mean conformant, certified, approved, or endorsed by ISO, IEC, IEEE, OMG, The Open Group, Mermaid, diagrams.net, AWS, Microsoft, or Google Cloud.

Precise contractual or regulated conformance requires the current authorized specification and an appropriate qualified review. Report the notation subset, source links, project verification date, assumptions, and validation actually performed.
