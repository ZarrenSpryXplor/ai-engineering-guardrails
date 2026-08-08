# Context and output efficiency

- Search before reading large files or directories, then use targeted reads around relevant matches.
- Avoid rereading unchanged content. Reuse already collected evidence and resume an existing agent when its context remains useful.
- Run the narrowest relevant checks first and request terse output when the tool supports it.
- Summarise bounded logs deterministically around failures, counts, and evidence; retain exit status and diagnostically relevant failure details.
- Keep the return concise. Report conclusions, evidence references, unresolved questions, and verification outcomes rather than raw transcripts or unbounded logs.
- Use only tool integrations needed for the task and stop agents that are no longer useful.
- Never rewrite a shell command or hide output in a way that could change behaviour, exit status, or material diagnostics.
