"""Composite responses."""

from __future__ import annotations

from pydantic import Field

from .common import CompleteModel, ContractModel, EdgeId, NodeId
from .generation import Asset, Job, Output
from .graph import Edge, Node
from .projects import Project
from .workflow import StepRun


class ProjectGraph(CompleteModel):
    """Everything the canvas needs to open a project, in one response."""

    project: Project
    nodes: list[Node]
    edges: list[Edge]
    # Every take of every node in the project, newest first per node.
    outputs: list[Output]
    # Jobs that are still queued or running, so progress survives a reload.
    active_jobs: list[Job] = Field(default_factory=list)
    # The last run of each workflow step that has been run.
    runs: list[StepRun] = Field(default_factory=list)


class ProjectSummary(Project):
    """A project as listed on the landing page."""

    node_count: int = 0
    image_count: int = 0
    video_count: int = 0
    # Jobs queued or running right now.
    running_count: int = 0
    # The newest image or video output, to show on the project's card.
    cover: Asset | None = None


class RestoreRequest(ContractModel):
    """Bring back soft-deleted nodes and edges (undo of a delete)."""

    node_ids: list[NodeId] = Field(default_factory=list)
    edge_ids: list[EdgeId] = Field(default_factory=list)


class RestoreResult(CompleteModel):
    """What came back: nodes (with their outputs) and edges.

    An edge is left deleted if one of its nodes is still deleted, an identical
    connection exists again, or it would now make a loop.
    """

    nodes: list[Node]
    edges: list[Edge]
    outputs: list[Output]
