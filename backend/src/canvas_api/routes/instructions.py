from __future__ import annotations

from fastapi import APIRouter

from ..contract import GlobalInstruction, GlobalInstructionUpdate
from ..deps import StoreDep, UserDep
from ..errors import responses

router = APIRouter(prefix="/global-instruction", tags=["instructions"])


@router.get("", operation_id="getGlobalInstruction", responses=responses())
def get_global_instruction(store: StoreDep, user: UserDep) -> GlobalInstruction:
    """The instruction every new project of yours starts with."""
    return GlobalInstruction(instruction=store.get_global_instruction(user.id))


@router.put("", operation_id="setGlobalInstruction", responses=responses())
def set_global_instruction(
    body: GlobalInstructionUpdate, store: StoreDep, user: UserDep
) -> GlobalInstruction:
    """Replace it. Existing projects keep their own instruction."""
    text = store.set_global_instruction(user.id, body.instruction)
    return GlobalInstruction(instruction=text)
