# Security policy

## Supported versions

Security fixes are made on the current `main` development line and the latest release published on PyPI. Older release lines are not currently supported; this section will name additional supported lines and their end-of-support dates if that policy changes.

## Report a vulnerability privately

Do not open a public issue with exploit details, proof-of-concept payloads, credentials, tokens, private configuration, or personal data.

1. Use GitHub's private vulnerability-reporting flow for this repository when it is available.
2. If that flow is unavailable, email [zarren.spry@xplortechnologies.com](mailto:zarren.spry@xplortechnologies.com) with the subject `ai-engineering-guardrails security report`.
3. Include a concise impact statement, affected version or commit, reproduction steps that do not disclose secrets, and any suggested mitigation. Encrypt sensitive material only after agreeing on a channel with the maintainer.

You should receive an acknowledgement within seven calendar days. If the report is accepted, the maintainer will coordinate a fix and disclosure timeline with the reporter. Please do not publish detailed exploitation guidance before a fix or agreed disclosure date.

## Scope

The project accepts reports about its packaged Python code, canonical resources, generated adapter output, installation/update/uninstall behavior, CI configuration, and published documentation. Product-native behavior, vendor account security, cloud configuration, and arbitrary third-party skills are outside this repository's direct control, but reports that show this project misrepresents or unsafely configures them are welcome.

This project intentionally has bounded enforcement coverage. A report should distinguish a genuine bypass of a documented control from a limitation already stated in the [threat model](docs/threat-model.md).

## Safe handling

Maintainers will not ask reporters to send credentials, production data, customer source, or unrestricted remote access. Test with synthetic fixtures, a temporary home, and non-production targets. Do not contact a vendor service, mutate infrastructure, or publish a package while reproducing an issue.
