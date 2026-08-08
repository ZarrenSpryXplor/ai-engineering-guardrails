# Repository contribution instructions

- Treat `policy/`, `skills/`, `enforcement/`, `routing/`, `packs/`, `config/`, and `platform-policies/` as canonical sources.
- Treat `dist/` and the generated files under `adapters/` as build output; do not edit them directly.
- Use Python 3.11+ and its standard library for all implementation and tests. Do not add another implementation language, shell helper, runtime dependency, packaging framework, service, or daemon.
- Apply KISS, DRY, YAGNI, and the Rule of Three: keep control flow explicit, retain one owner for policy knowledge, and do not add speculative abstractions or extension points.
- Keep product-specific configuration in adapters. Do not duplicate canonical behavioural policy there.
- Keep vendor model identifiers in `routing/model-maps/`, never in behavioural policy or portable role instructions.
- Keep stack guidance in on-demand capability packs rather than the always-loaded policy. Detectors must be offline, evidence-producing, and fixture-tested.
- Keep lifecycle target mappings credential-free. Tests must be offline and fixture-based; never contact Kubernetes, Helm or package registries, Terraform backends, databases, observability services, Azure, another cloud API, or Spacelift.
- Treat Spacelift platform policies as examples only; build and validation must never attach them to an account.
- Inspect the working tree before editing and preserve existing uncommitted work.
- Use temporary homes for every installer or uninstaller test. Never modify real workstation configuration during development.
- Run `python tools/guardrails.py build`, `python tools/guardrails.py validate`, `python -m unittest discover -s tests -v`, and applicable compile/scan checks before reporting completion.
- Review generated output and the final Git diff. Report any check that could not be run.
