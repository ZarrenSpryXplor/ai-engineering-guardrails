# Test fixtures

Tests create mutable fixtures inside `tempfile.TemporaryDirectory`; no fixture or test may target the developer's real home directory.
