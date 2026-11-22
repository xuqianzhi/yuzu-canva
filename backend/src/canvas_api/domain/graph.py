"""Reference graph rules: edge validation, cycles, prompt mentions."""

from __future__ import annotations

import re
from collections import defaultdict

from ..contract import Edge, EdgeCreate, ErrorCode
from ..errors import ApiError

MENTION = re.compile(r"@\{(nod_[A-Za-z0-9]+)\}")


def would_create_cycle(edges: list[Edge], source: str, target: str) -> bool:
    """True if adding source -> target closes a cycle, i.e. target already
    reaches source by following existing edges."""
    out: dict[str, list[str]] = defaultdict(list)
    for edge in edges:
        out[edge.source_node_id].append(edge.target_node_id)
    stack, seen = [target], set()
    while stack:
        node = stack.pop()
        if node == source:
            return True
        if node in seen:
            continue
        seen.add(node)
        stack.extend(out[node])
    return False


def check_new_edge(edges: list[Edge], body: EdgeCreate) -> None:
    """Raise the contract error for an edge that may not be added."""
    source, target = body.source_node_id, body.target_node_id
    context = {"source_node_id": source, "target_node_id": target}
    if source == target:
        raise ApiError(409, ErrorCode.self_reference, "a node cannot reference itself", context)
    if any(
        e.source_node_id == source and e.target_node_id == target and not e.workflow
        for e in edges
    ):
        raise ApiError(409, ErrorCode.duplicate_edge, "this reference already exists", context)
    if would_create_cycle(edges, source, target):
        raise ApiError(
            409,
            ErrorCode.cycle,
            f"{target} already depends on {source}; referencing it back would make a cycle",
            context,
        )
