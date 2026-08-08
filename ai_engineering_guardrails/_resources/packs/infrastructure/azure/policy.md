# Azure capability policy

- Classify subscription and tenant separately from lifecycle. Remote mutation must name an explicit subscription and, where applicable, tenant; an unmapped subscription is protected and direct prd mutation is denied.
- Permit bounded metadata reads such as account/resource/AKS/ACR/role-assignment/monitor listings when output cannot contain credentials. Treat deployment outputs and diagnostic data as potentially sensitive.
- Deny access-token, secret-value, storage-key, service-principal credential, kubeconfig, and admin-credential retrieval. Deny privilege grants, role changes, policy exemption weakening, broad or prd deletion, and cross-tenant mutation by default.
- Prefer workload identity, short-lived authentication, least-privilege wrappers, and source-controlled plans. Never print cached credentials or attempt to implement a credential broker.
