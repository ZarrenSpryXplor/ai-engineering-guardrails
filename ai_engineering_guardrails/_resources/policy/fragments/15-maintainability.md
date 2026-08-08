## Maintainability

- Choose the simplest design that satisfies known requirements and use the repository's existing language and stack.
- Keep one authoritative source for policy and configuration. Do not add a second framework or language for a local problem.
- Do not build extension points without a current consumer. Apply the Rule of Three before introducing a general abstraction.
- Prefer a few explicit lines or limited duplication over an abstraction that combines unrelated concepts.
- Remove dead code and wrappers that add no semantic value. Explain any new dependency, framework, service, or architectural layer.

