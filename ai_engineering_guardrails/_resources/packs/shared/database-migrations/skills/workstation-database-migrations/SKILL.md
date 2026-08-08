---
name: workstation-database-migrations
description: Author and verify database migration source using the repository's existing framework while separating creation from execution and preserving history. Use for bounded schema/data migration code and isolated tests; do not use to apply migrations to real databases, delete history, or execute destructive production data changes.
---

# Migration authoring workflow

1. Map the migration framework, history, ordering, transaction and rollback conventions, affected schema/data, and compatibility window.
2. Distinguish source generation from execution. Create the smallest forward/rollback artifacts without rewriting prior applied history.
3. Review locking, failure recovery, data volume, backward/forward application compatibility, and deployment sequencing.
4. Verify with static checks or an isolated disposable database fixture only; never contact a real database.
5. Report assumptions, generated files, test evidence, irreversible steps, and the separate human-controlled execution plan.

Complete after isolated verification; execution remains unperformed.
