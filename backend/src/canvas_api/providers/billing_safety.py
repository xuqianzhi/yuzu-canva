"""Not paying twice for a Seedance video.

Every Seedance task Ark creates is billed, whether or not we ever see its
answer. These are the rules for talking to Ark that keep one click from
becoming two paid tasks, in one place; seedance_video.py calls them.

The rest of the app's guards, for reference (each is small and lives where
the thing it guards is):

- One generation per node at a time: ``Store.create_job`` refuses a second
  active job for a node inside the same transaction (two quick clicks can't
  both queue), and ``POST /nodes/{id}/generate`` answers 409
  ``job_in_progress`` (routes/nodes.py).
- A step's Generate skips nodes already generating (``generateStep`` in
  routes/workflow.py), and asks before paying for videos (StepPanel.tsx).
- A node's Generate button turns into Stop while its job runs (GenNode.tsx).
- Jobs live in the database. Ark's task id is saved the moment Ark answers
  (``on_submitted`` -> ``jobs.provider_task_id``), so a restarted backend
  keeps polling that task instead of creating another (jobs/worker.py).
- The seed and send time are saved *before* the create request goes out
  (``on_sending`` -> ``jobs.provider_seed`` / ``jobs.sent_at``). If the
  backend stops mid-send, the restarted worker looks the task up by that
  seed (below) rather than failing the job and inviting a second click.
- Spending limits cap how many paid jobs can run or be made per day
  (spending.py); they bound the cost of any mistake.

The rules here:

1. Every task gets a seed (random unless the node sets one): Ark lists it
   with the task, which identifies a task whose create answer was lost.
2. A create request is never blindly resent. Retried only when it can't
   have created anything: it never connected, or Ark said 429. A timeout,
   a dropped connection or a 5xx after sending raises ``MaybeCreated``.
3. After ``MaybeCreated`` (or a restart mid-send) the task is looked up in
   Ark's recent tasks by seed and settings. Found: it's picked up and
   polled. Not found: the job fails, saying generating again is safe.
   The lookup itself failing: the job fails, saying to check the Ark
   console first.
4. Reads (status, listing) are retried freely: they cost nothing.
5. Cancelling only ever sends DELETE for a task that is still queued: on a
   finished task, DELETE removes its record and video link instead.
"""

from __future__ import annotations

import asyncio
import logging
import secrets
from collections.abc import Awaitable, Callable
from typing import Any

from ..contract import VideoParams
from .base import ProviderError

log = logging.getLogger(__name__)

TASKS_PATH = "/contents/generations/tasks"
MAX_SEED = 2**32 - 1
# Statuses worth retrying for a read. A create is retried only on 429.
RETRY_STATUSES = frozenset({408, 429, 500, 502, 503, 504})
# How far back (seconds) to look for a task a lost create request may have
# made, allowing for clock skew between this machine and Ark.
RECOVERY_SLACK_S = 300
RECOVERY_PAGES = 3
RECOVERY_PAGE_SIZE = 50

# How long cancelling may take before it is given up on (seconds).
CANCEL_TIMEOUT_S = 15

# The settings that, with the seed, identify a task in Ark's listing.
MATCHED = ("seed", "duration", "ratio", "resolution")

Request = Callable[[str, str], Awaitable[Any]]


class MaybeCreated(ProviderError):
    """A create request went out but its answer was lost: the task may exist."""


def pick_seed(params: VideoParams) -> int:
    """Rule 1: the node's seed, else a random one (always sent)."""
    return params.seed if params.seed is not None else secrets.randbelow(MAX_SEED)


def retryable(method: str, status: int) -> bool:
    """Rules 2 and 4: may this answer be retried? A create only on 429
    (definitely not created); a 5xx may come after Ark made the task."""
    if method == "POST":
        return status == 429
    return status in RETRY_STATUSES


def identity(params: VideoParams, seed: int) -> dict[str, Any]:
    """What a task this request made looks like in Ark's listing."""
    return {
        "seed": seed,
        "duration": params.duration_s,
        "ratio": params.ratio,
        "resolution": params.resolution,
    }


async def find_created(
    get: Request, model: str, want: dict[str, Any], since: float
) -> str | None:
    """Rule 3: the id of the task with this seed and these settings, created
    at or after `since` (Unix seconds, less RECOVERY_SLACK_S); None if Ark
    has none. Raises ProviderError when the listing can't be read: then
    nobody can say whether the task exists."""
    try:
        for page in range(1, RECOVERY_PAGES + 1):
            listing = await get(
                "GET",
                f"{TASKS_PATH}?page_num={page}&page_size={RECOVERY_PAGE_SIZE}"
                f"&filter.model={model}",
            )
            items = listing.get("items") or []
            for task in items:  # newest first
                if (task.get("created_at") or 0) < since - RECOVERY_SLACK_S:
                    return None
                if all(task.get(k) == v for k, v in want.items()) and task.get("id"):
                    return str(task["id"])
            if len(items) < RECOVERY_PAGE_SIZE:
                return None
    except ProviderError as exc:
        raise ProviderError(
            "The request to Seedance was lost and checking whether Ark created the "
            f"task failed too ({exc}). Check the Ark console before generating again, "
            "so you don't pay twice."
        ) from exc
    return None


async def cancel_if_queued(request: Request, task_id: str) -> None:
    """Rule 5: cancel a task only while it is queued (best effort: slow or
    failed answers are logged, never raised)."""
    try:
        async with asyncio.timeout(CANCEL_TIMEOUT_S):
            task = await request("GET", f"{TASKS_PATH}/{task_id}")
            if str(task.get("status")).lower() == "queued":
                await request("DELETE", f"{TASKS_PATH}/{task_id}")
    except Exception:  # best effort; the job is cancelled either way
        log.warning("could not cancel Seedance task %s", task_id, exc_info=True)
