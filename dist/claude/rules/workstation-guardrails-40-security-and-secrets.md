<!-- GENERATED — DO NOT EDIT
Canonical source: policy/fragments/40-security-and-secrets.md
-->

## Security and secrets

- Never display, copy, commit, or log credentials, tokens, private keys, or secret values.
- Treat environment files, kubeconfigs, cloud credentials, and package-registry credentials as sensitive.
- Do not replace proper secret handling with hard-coded placeholders that look real.
- Do not suppress security scanners without explaining and justifying the exception.
- Report suspected credential exposure without reproducing the secret.
