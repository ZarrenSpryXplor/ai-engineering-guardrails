# Local waivers

Waivers are exact-digest, repository- and target-scoped exceptions created only through an interactive TTY. The default is one use for 15 minutes; the hard maximum is 24 hours. Raw commands and tool arguments are never stored.

The hook uses an exclusive local lock while rechecking and consuming a matching waiver. A stale lock fails closed for later use. A user who can edit the local files can still bypass this defence-in-depth mechanism, so a waiver is not a signature or cryptographic human approval. Destructive, sensitive-read, publication, privilege-escalation, and guardrail-modification rules cannot receive broad wildcard waivers.
