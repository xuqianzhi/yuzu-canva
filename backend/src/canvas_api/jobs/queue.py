"""Queue a node's generation: plan it from its inputs, record the job, and
hand it to the worker. Used by the generate route and by workflow runs."""

from __future__ import annotations

from ..contract import Job, Node
from ..domain.planner import Reference, plan
from ..store import Store
from .worker import Worker


def queue_generation(store: Store, worker: Worker, node: Node) -> Job:
    refs = [Reference(node=n, output=o) for n, o in store.node_inputs(node)]
    planned = plan(node, refs, store.get_language().value)
    job = store.create_job(node, planned.provider, planned.operation, planned.job_input)
    worker.enqueue(job.id)
    return job
