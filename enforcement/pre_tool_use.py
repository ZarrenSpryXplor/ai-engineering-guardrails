#!/usr/bin/env python3
"""Repository launcher for the standalone hook runtime."""

from __future__ import annotations

import sys
from pathlib import Path


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

from guardrails.enforcement import main as runtime_main  # noqa: E402


if __name__ == "__main__":
    raise SystemExit(
        runtime_main(
            [
                "--product",
                "codex",
                "--policy",
                str(REPOSITORY_ROOT / "enforcement/command-policy.json"),
                "--structured-policy",
                str(REPOSITORY_ROOT / "enforcement/structured-tool-policy.json"),
                "--redaction-policy",
                str(REPOSITORY_ROOT / "enforcement/redaction-policy.json"),
                "--metadata",
                str(REPOSITORY_ROOT / "enforcement/runtime-metadata.example.json"),
            ]
        )
    )
