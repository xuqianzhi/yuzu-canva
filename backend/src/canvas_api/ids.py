"""Prefixed, random, URL-safe IDs (see contract/common.py)."""

from __future__ import annotations

import secrets
import string

_ALPHABET = string.ascii_lowercase + string.digits


def new_id(prefix: str) -> str:
    """e.g. new_id("nod") -> "nod_3k9x0a7m2q1z" (12 chars, ~62 bits)."""
    return f"{prefix}_" + "".join(secrets.choice(_ALPHABET) for _ in range(12))
