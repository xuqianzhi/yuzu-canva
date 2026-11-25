"""Queue a node's generation: plan it from its inputs, record the job, and
hand it to the worker. Used by the generate route and by workflow runs."""

from __future__ import annotations

from functools import partial
from pathlib import PurePath
from typing import TYPE_CHECKING

from ..contract import Job, Node
from ..domain.planner import Reference, plan
from ..providers.base import RefFile
from ..store import Store

if TYPE_CHECKING:
    from ..spending import Spending
    from .worker import Worker


def queue_generation(
    store: Store, worker: Worker, node: Node, actor: str, spending: Spending | None = None
) -> Job:
    """Generate `node` for `actor`.
    With `spending`, the generation is counted against the limits once it is
    known to be valid (callers that already counted pass None)."""
    refs = [Reference(node=n, output=o) for n, o in store.node_inputs(node)]
    planned = plan(node, refs)
    if spending is not None:
        collection_id = store.collection_of(node.project_id)
        spending.check_jobs(collection_id, 1)
        spending.charge(actor, collection_id, node.kind.value)
    job = store.create_job(node, planned.provider, planned.operation, planned.job_input)
    worker.enqueue(job.id)
    return job


def ref_file(store: Store, node_id: str, asset_id: str) -> RefFile:
    """A stored asset as a provider reference (its bytes read on demand)."""
    asset, key = store.asset_file(asset_id)
    return RefFile(
        node_id=node_id,
        kind=asset.kind,
        mime=asset.mime,
        name=PurePath(key).name,
        read=partial(store.files.read, key),
    )
