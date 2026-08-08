# Helm capability policy

- Lint and render before deployment; inspect a rendered diff/plan when tooling already exists. Preserve values precedence, chart hooks, CRD ownership, and lifecycle semantics. Never edit rendered output.
- Treat lint/template/show/search/list/status/history/get/dependency list/verify as observe or validate. Treat install/upgrade/rollback/test/push/login/repo add/plugin install as mutation.
- Deny uninstall, `upgrade --take-ownership`, insecure TLS/plain HTTP, validation bypass, unsafe credential flags, and unreviewed plugin installation. Never put secrets in `--set` arguments.
- Detect required/installed Helm version when possible without assuming a major version or automatically installing plugins/validators.
