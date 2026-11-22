"""Node IDs mentioned in prompts.

A node's optional ID (the API field ``name``) is letters (any script),
digits, ``_`` and ``-``. A prompt mentions a node simply by containing its
ID -- no "@" (the UI's "@" picker inserts the bare ID):

- At each position the longest existing ID that matches wins, ignoring case;
  matches don't overlap.
- An ID that starts or ends with a Latin letter, digit, ``_`` or ``-`` must
  be a whole word on that side: "fox" is not in "redfox" or "foxes". Chinese
  needs no spaces: "兔子老板走进来" mentions 兔子老板.

A generating node's main-input links exist exactly when its prompt mentions
the source (see Store.sync_links).
"""

from __future__ import annotations

import re
from collections.abc import Callable, Mapping

ID_RE = re.compile(r"^[\w-]+$")
_ASCII_WORD = re.compile(r"[A-Za-z0-9_-]")

ID_RULE = "an ID can use letters, numbers, _ and - (no spaces)"


def is_valid_id(name: str) -> bool:
    return bool(ID_RE.match(name))


def to_valid_id(name: str) -> str:
    """Turn any old name into a valid ID: invalid runs become ``_``."""
    cleaned = re.sub(r"[^\w-]+", "_", name.strip()).strip("_")
    return cleaned or "node"


def find_mentions(text: str, ids: Mapping[str, str]) -> list[tuple[int, int, str]]:
    """Every mention in `text` as (start, end, node id), in order.

    `ids` maps each existing ID to its node id.
    """
    if not text or not ids:
        return []
    lowered = text.lower()
    keys = sorted(
        ((name.lower(), node) for name, node in ids.items()), key=lambda k: -len(k[0])
    )
    found: list[tuple[int, int, str]] = []
    i, n = 0, len(text)
    while i < n:
        match = None
        for key, node in keys:
            if not key or not lowered.startswith(key, i):
                continue
            stop = i + len(key)
            # Latin edges must be word edges: "fox" is not in "redfox"/"foxes".
            if _ASCII_WORD.match(key[0]) and i > 0 and _ASCII_WORD.match(text[i - 1]):
                continue
            if _ASCII_WORD.match(key[-1]) and stop < n and _ASCII_WORD.match(text[stop]):
                continue
            match = (i, stop, node)
            break
        if match:
            found.append(match)
            i = match[1]
        else:
            i += 1
    return found


def mentioned(text: str, ids: Mapping[str, str]) -> list[str]:
    """Node ids mentioned in `text`, in order of first mention."""
    return list(dict.fromkeys(node for _, _, node in find_mentions(text, ids)))


def replace_mentions(text: str, ids: Mapping[str, str], fn: Callable[[str, str], str]) -> str:
    """Replace each mention with fn(node id, the mention as written)."""
    out, last = [], 0
    for start, end, node in find_mentions(text, ids):
        out.append(text[last:start])
        out.append(fn(node, text[start:end]))
        last = end
    out.append(text[last:])
    return "".join(out)


def remove_mentions(text: str, ids: Mapping[str, str], node_id: str) -> str:
    """`text` without its mentions of `node_id` (spacing tidied)."""
    cleaned = replace_mentions(text, ids, lambda node, raw: "" if node == node_id else raw)
    cleaned = re.sub(r"[ \t]{2,}", " ", cleaned)
    cleaned = re.sub(r"[ \t]+([,.;:!?，。；：！？、])", r"\1", cleaned)
    return cleaned.strip()
