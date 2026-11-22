from __future__ import annotations

from fastapi import APIRouter

from ..contract import GlobalInstruction, GlobalInstructionUpdate
from ..deps import StoreDep
from ..errors import responses

router = APIRouter(prefix="/global-instruction", tags=["instructions"])


@router.get("", operation_id="getGlobalInstruction", responses=responses())
def get_global_instruction(store: StoreDep) -> GlobalInstruction:
    """The instruction every new project starts with."""
    return GlobalInstruction(instruction=store.get_global_instruction())


@router.put("", operation_id="setGlobalInstruction", responses=responses())
def set_global_instruction(body: GlobalInstructionUpdate, store: StoreDep) -> GlobalInstruction:
    """Replace it. Existing projects keep their own instruction."""
    return GlobalInstruction(instruction=store.set_global_instruction(body.instruction))
