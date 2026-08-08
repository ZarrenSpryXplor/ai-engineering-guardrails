---
name: workstation-secrets-pki
description: Inspect secret and certificate metadata and review PKI source without exposing protected values. Use for expiry, issuer, fingerprint, rotation, and access-policy analysis; do not use to retrieve secret values, private keys, raw tokens, kubeconfigs, decrypted files, or keystore passwords.
---

# Secrets and PKI workflow

1. Establish whether the requested evidence is public certificate metadata, secret metadata, access-policy structure, or protected value material.
2. Refuse value/private-material retrieval. Minimise metadata and redact identifiers that are not needed for the task.
3. Use repository-native configuration and public-certificate tools for subject, issuer, expiry, fingerprint, and chain checks. Do not place passwords or values in arguments.
4. Use only unmistakably synthetic fixtures and preserve existing trust, encryption, and rotation controls.
5. Report safe metadata, provenance, validation results, uncertainty, and the protected fields deliberately not accessed.

Complete only when the requested metadata or source review is verified without exposing protected material or contacting a remote secret store in tests.
