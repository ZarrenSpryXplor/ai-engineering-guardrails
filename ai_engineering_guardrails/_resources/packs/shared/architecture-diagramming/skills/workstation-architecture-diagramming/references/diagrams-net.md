# diagrams.net source guidance

Use `.drawio` as an editable native diagrams.net source format. It is not an architecture standard or a guaranteed universal interchange format. For new repository artifacts, choose uncompressed UTF-8 XML so reviewers can inspect meaningful diffs and ordinary XML tooling can perform structural checks.

## Document hierarchy

At a high level, an `mxfile` document contains a `diagram` page, which contains an `mxGraphModel`; the model's graph root contains cells. Base cells establish the model and default layer. Other cells represent layers, groups, vertices, and edges. This description is an invariant outline, not an XML template.

Use one page per file by default. Use multiple pages only when they form one coherent diagram set and have clear page names and shared scope.

## Cell and geometry invariants

- Give every cell a stable, unique ID. Do not derive IDs from volatile array positions or timestamps.
- Order content deterministically: model and layer cells first, then containers or groups, vertices, and edges. Within each group, use one stable semantic order.
- Make every parent reference resolve to an existing cell. Make each edge source and target resolve unless the intentionally dangling endpoint is visible and explained.
- Mark vertices and edges consistently. Give vertices explicit position and size geometry. Give edges explicit edge geometry and, where needed, deterministic waypoints or terminal points.
- Keep coordinates and dimensions consistent and reviewable. Prefer integer values when finer precision has no visual purpose.
- XML-escape labels, notes, link text, and metadata. Do not place untrusted text into style fields or executable attributes.
- Keep labels short. Put detailed rationale in adjacent documentation rather than hidden cell metadata.

## Source-of-truth and import rules

Maintain one authoritative source for a diagram. Do not hand-maintain Mermaid and `.drawio` versions as equal sources of truth. When a user requests a conversion, record which file becomes authoritative, which output is derived, and which layout or semantics cannot be regenerated exactly.

diagrams.net can import Mermaid as an image or as editable diagram shapes. Use editable import only when the user needs shape-level editing and the local application already supports it. Treat the import as generation, not lossless round-trip conversion: regenerating or reimporting Mermaid can reset manual geometry, connector routing, and style changes. Preserve Mermaid as authoritative only when those edits are intentionally disposable; otherwise make the resulting `.drawio` file authoritative and document the break in regeneration.

## Validation levels

### 1. Structural review

Confirm that:

- the XML is well formed;
- the expected `mxfile`, `diagram`, `mxGraphModel`, graph-root, and cell elements exist;
- IDs are unique;
- parent, source, and target references resolve;
- required vertex and edge geometry is present; and
- external image references, remote dependencies, and embedded scripts are absent.

Structural review proves only these source invariants. Never call it render validation or claim that it proves the diagram opens or looks correct.

### 2. diagrams.net validation

If a diagrams.net desktop application or CLI is already installed locally, open or render the file. Do not install or download a validator. Confirm that the application accepts the file without a repair prompt. Record the application or CLI used and its observed result.

### 3. Visual inspection

Inspect the rendered page at its intended output size. Check clipping, overlap, alignment, whitespace, group containment, connector routing and crossings, arrow direction, missing or truncated labels, contrast, and consistent visual semantics. Correct material defects and repeat the inspection.

## Content boundaries

Use uncompressed content. Do not add compressed diagram payloads, embedded scripts, executable links, remote image URLs, credentials, secrets, or sensitive internal URLs. Prefer generic local shapes. Use provider icons only when a current official asset is already supplied or locally available; never fetch icons, stencils, fonts, or templates at runtime.

This skill bundles no `.drawio` template, XML template, external asset, conversion runtime, or executable validator. Create only the source artifact required for the current diagram.

## Provenance

This guidance is based on the public diagrams.net documentation for [save file formats](https://www.drawio.com/docs/manual/editor/save-file-formats/), [diagram generation](https://www.drawio.com/docs/reference/diagram-generation/), and [Mermaid import](https://www.drawio.com/docs/manual/mermaid/). It summarizes a bounded repository workflow and does not claim diagrams.net approval, endorsement, certification, or formal format conformance.
