# Secrets and PKI capability policy

- Work with names, versions, expiry, subject, issuer, fingerprint, rotation state, and access-policy structure when those fields are safe. Minimise even metadata and redact identifying fields when unnecessary.
- Deny secret values, private keys, exportable private material, raw tokens, credential-bearing kubeconfigs, decrypted secret files, keystore passwords, and commands that render protected material into model-visible output.
- Do not create real secrets in fixtures, move secret handling into command arguments, downgrade TLS or validation, or make private keys exportable for convenience.
- Use unmistakably synthetic fixtures and repository-native certificate validation. Report expiry and trust-chain uncertainty without copying private material.
