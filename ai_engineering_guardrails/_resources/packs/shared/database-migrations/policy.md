# Database migration capability policy

- Separate migration source creation from execution against a database. Inspect the existing migration framework, ordering, transaction behavior, rollback conventions, data volume, and compatibility first.
- Preserve migration history; never delete and regenerate it as a repair shortcut. Avoid destructive or irreversible data operations without explicit architecture and human-controlled execution planning.
- Agents may author and statically/test validate migrations against isolated disposable fixtures, but must not update a real database or production target. Treat connection strings, row data, dumps, query results, plan output, and backups as potentially sensitive.
- Deny production migration apply, database/schema reset, database drop, destructive repair, and broad `DROP`/`TRUNCATE` or `DELETE`/`UPDATE` without an established predicate. Command matching is not a SQL parser; require native migration review and platform controls.
