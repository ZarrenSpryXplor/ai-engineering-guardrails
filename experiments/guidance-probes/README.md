# Guidance probes

This optional format supports manual, repeatable evaluation of a bounded guidance change. It is not part of normal installation, policy enforcement, routing, or CI execution.

Each JSON probe follows `schema.json` and names a local fixture/reference, task description, expected allowed and forbidden behaviours, expected files/subsystems, and outcome checks. The repository test suite validates only that shape and portable identifiers. It never calls a model, launches a coding agent, downloads a repository, changes policy, or publishes a benchmark claim.

To evaluate a probe, a maintainer runs the same fixture and task manually in each chosen product/model under separately approved conditions, preserves the observed evidence outside this repository, and reviews differences before changing concise guidance. A favourable one-off run is not authority to weaken safety controls.
