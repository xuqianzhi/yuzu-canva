"""Collections: the collections you're in, their members and invites (and
yours to accept), their workflows, and their projects."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Response
from fastapi.concurrency import run_in_threadpool

from ..auth import is_admin
from ..contract import (
    Collection,
    CollectionCreate,
    CollectionId,
    CollectionSummary,
    CollectionUpdate,
    CollectionWorkflow,
    ErrorCode,
    Invitation,
    Invite,
    InviteCreate,
    InviteId,
    Member,
    MemberUpdate,
    Project,
    ProjectCreate,
    ProjectSummary,
    Role,
    WorkflowId,
    WorkflowSave,
)
from ..deps import (
    AccessDep,
    FilesDep,
    SettingsDep,
    StoreDep,
    UserDep,
    WorkerDep,
    require_owner,
)
from ..errors import ApiError, responses
from ..files import delete_all

router = APIRouter(tags=["collections"])
owner_only = [Depends(require_owner)]


@router.get("/collections", operation_id="listCollections", responses=responses())
def list_collections(store: StoreDep, user: UserDep) -> list[CollectionSummary]:
    """The collections you own or edit, most recently changed first."""
    return store.list_collections(user.id)


@router.post(
    "/collections", status_code=201, operation_id="createCollection", responses=responses()
)
def create_collection(body: CollectionCreate, store: StoreDep, user: UserDep) -> Collection:
    """A new collection, yours (its owner), with one workflow: ``workflow``
    if given (copy one from another collection), else the built-in one."""
    return store.create_collection(user.id, body)


@router.get(
    "/collections/{collection_id}", operation_id="getCollection", responses=responses(404)
)
def get_collection(collection_id: CollectionId, store: StoreDep, user: UserDep) -> Collection:
    return store.get_collection(collection_id, user.id)


@router.patch(
    "/collections/{collection_id}",
    operation_id="updateCollection",
    responses=responses(404, 409),
)
def update_collection(
    collection_id: CollectionId,
    body: CollectionUpdate,
    store: StoreDep,
    user: UserDep,
    settings: SettingsDep,
) -> Collection:
    """Rename it or change its instruction. 409 ``edit_conflict`` if
    someone saved since ``version``. Only admins may change
    ``no_daily_limit`` (403 ``forbidden``)."""
    if body.no_daily_limit is not None and not is_admin(settings, user.email):
        raise ApiError(403, ErrorCode.forbidden, "only an admin can change the daily limit")
    return store.update_collection(collection_id, user.id, body)


@router.delete(
    "/collections/{collection_id}",
    status_code=204,
    response_class=Response,
    operation_id="deleteCollection",
    responses=responses(403, 404),
    dependencies=owner_only,
)
async def delete_collection(
    collection_id: CollectionId, store: StoreDep, worker: WorkerDep, files: FilesDep
) -> None:
    """Owner only. Deletes it for everyone, with every project in it, its
    workflows, assets, members and invites, and their files. Usage records
    stay (they still count today)."""
    keys, active_jobs = await run_in_threadpool(store.delete_collection, collection_id)
    for job_id in active_jobs:
        worker.abort(job_id)
    await run_in_threadpool(delete_all, files, keys)


# --- projects ------------------------------------------------------------------------


@router.get(
    "/collections/{collection_id}/projects",
    operation_id="listProjects",
    responses=responses(404),
)
def list_projects(
    collection_id: CollectionId, store: StoreDep, user: UserDep
) -> list[ProjectSummary]:
    """The collection's projects, most recently updated first, with counts,
    a cover, and who else is editing each right now."""
    return store.list_project_summaries(collection_id, user.id)


@router.post(
    "/collections/{collection_id}/projects",
    status_code=201,
    operation_id="createProject",
    responses=responses(404),
)
def create_project(
    collection_id: CollectionId, body: ProjectCreate, store: StoreDep
) -> Project:
    """Create a project. It runs on the collection's active workflow and
    starts with one uploaded node per collection asset, down the left side
    of its canvas."""
    return store.create_project(collection_id, body)


# --- members -------------------------------------------------------------------------


@router.get(
    "/collections/{collection_id}/members",
    operation_id="listMembers",
    responses=responses(404),
)
def list_members(collection_id: CollectionId, store: StoreDep) -> list[Member]:
    """The owner first, then editors, each with their limits and what they
    generated here today."""
    return store.list_members(collection_id)


@router.patch(
    "/collections/{collection_id}/members/{user_id}",
    operation_id="updateMember",
    responses=responses(403, 404, 409),
    dependencies=owner_only,
)
def update_member(
    collection_id: CollectionId, user_id: str, body: MemberUpdate, store: StoreDep
) -> Member:
    """Owner only: set an editor's daily limits here."""
    return store.set_member_limits(collection_id, user_id, body.limits)


@router.delete(
    "/collections/{collection_id}/members/{user_id}",
    status_code=204,
    response_class=Response,
    operation_id="removeMember",
    responses=responses(403, 404, 409),
)
def remove_member(
    collection_id: CollectionId, user_id: str, store: StoreDep, user: UserDep, access: AccessDep
) -> None:
    """The owner removes an editor, or an editor leaves (their own user ID).
    What they made stays. The owner can't leave (409)."""
    if access.role != Role.owner and user_id != user.id:
        raise ApiError(403, ErrorCode.forbidden, "only the owner can remove other editors")
    store.remove_member(collection_id, user_id)


# --- invites -------------------------------------------------------------------------


@router.get(
    "/collections/{collection_id}/invites",
    operation_id="listInvites",
    responses=responses(404),
)
def list_invites(collection_id: CollectionId, store: StoreDep) -> list[Invite]:
    """Invites waiting to be accepted, newest first."""
    return store.list_invites(collection_id)


@router.post(
    "/collections/{collection_id}/invites",
    status_code=201,
    operation_id="createInvite",
    responses=responses(403, 404, 409),
    dependencies=owner_only,
)
def create_invite(
    collection_id: CollectionId, body: InviteCreate, store: StoreDep, user: UserDep
) -> Invite:
    """Owner only: invite an email as an editor, with their daily limits
    here. They see it after signing in (no email is sent) and accept it to
    get in; it expires after 30 days. Inviting the same email again renews
    it. 409 if they're already a member. They also need to be on the app's
    allowlist to sign in at all."""
    return store.create_invite(collection_id, user.id, body)


@router.delete(
    "/collections/{collection_id}/invites/{invite_id}",
    status_code=204,
    response_class=Response,
    operation_id="cancelInvite",
    responses=responses(403, 404),
    dependencies=owner_only,
)
def cancel_invite(collection_id: CollectionId, invite_id: InviteId, store: StoreDep) -> None:
    store.cancel_invite(collection_id, invite_id)


@router.get("/invitations", operation_id="listInvitations", responses=responses())
def list_invitations(store: StoreDep, user: UserDep) -> list[Invitation]:
    """Invites to you (by your sign-in email), newest first."""
    return store.invitations_for(user.email)


@router.post(
    "/invitations/{invite_id}/accept",
    operation_id="acceptInvitation",
    responses=responses(404),
)
def accept_invitation(invite_id: InviteId, store: StoreDep, user: UserDep) -> Collection:
    """Join the collection as an editor."""
    return store.accept_invite(invite_id, user.id, user.email)


@router.post(
    "/invitations/{invite_id}/decline",
    status_code=204,
    response_class=Response,
    operation_id="declineInvitation",
    responses=responses(404),
)
def decline_invitation(invite_id: InviteId, store: StoreDep, user: UserDep) -> None:
    store.decline_invite(invite_id, user.email)


# --- workflows -----------------------------------------------------------------------


@router.get(
    "/collections/{collection_id}/workflows",
    operation_id="listWorkflows",
    responses=responses(404),
)
def list_workflows(collection_id: CollectionId, store: StoreDep) -> list[CollectionWorkflow]:
    """The collection's workflows, oldest first; one is active."""
    return store.list_workflows(collection_id)


@router.post(
    "/collections/{collection_id}/workflows",
    status_code=201,
    operation_id="createWorkflow",
    responses=responses(404),
)
def create_workflow(
    collection_id: CollectionId, body: WorkflowSave, store: StoreDep, user: UserDep
) -> CollectionWorkflow:
    """A new workflow, not active yet (422 if two steps share a key). To
    copy one from another collection, send its definition."""
    return store.create_workflow(collection_id, user.id, body.definition)


@router.put(
    "/workflows/{workflow_id}", operation_id="updateWorkflow", responses=responses(404, 409)
)
def update_workflow(
    workflow_id: WorkflowId, body: WorkflowSave, store: StoreDep, user: UserDep
) -> CollectionWorkflow:
    """Replace a workflow (its version goes up). Editing the active one
    changes it for every project in the collection, so it's refused (409)
    while a step runs there; 409 ``edit_conflict`` if someone saved since
    ``base_version``."""
    return store.update_workflow(workflow_id, user.id, body.definition, body.base_version)


@router.delete(
    "/workflows/{workflow_id}",
    status_code=204,
    response_class=Response,
    operation_id="deleteWorkflow",
    responses=responses(404, 409),
)
def delete_workflow(workflow_id: WorkflowId, store: StoreDep) -> None:
    """Not the active one (409)."""
    store.delete_workflow(workflow_id)


@router.post(
    "/workflows/{workflow_id}/activate",
    operation_id="activateWorkflow",
    responses=responses(404, 409),
)
def activate_workflow(workflow_id: WorkflowId, store: StoreDep) -> CollectionWorkflow:
    """Every project in the collection runs on this workflow from now on;
    their steps keep their results by step key (steps it doesn't have are
    hidden until a workflow with them is active again). 409 while a step
    runs in the collection."""
    return store.activate_workflow(workflow_id)
