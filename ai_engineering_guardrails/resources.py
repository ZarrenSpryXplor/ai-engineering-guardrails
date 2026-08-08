"""Locations for immutable package data and optional contributor output."""

from __future__ import annotations

from pathlib import Path


PACKAGE_ROOT = Path(__file__).resolve().parent
RESOURCE_ROOT = PACKAGE_ROOT / "_resources"


def repository_output_root() -> Path | None:
    """Return a checkout root only when this package is running from one.

    Runtime policy always comes from ``RESOURCE_ROOT``. This is solely the explicit
    destination for contributor-generated artifacts.
    """
    candidate = PACKAGE_ROOT.parent
    return candidate if (candidate / "tools/guardrails.py").is_file() else None
