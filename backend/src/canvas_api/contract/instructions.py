"""Instructions: standing guidance for a whole canvas, like a project's
custom instructions in a chat app.

There is one global instruction, and every project has its own, copied from
the global one when the project is created and edited separately after that.
For now they are only stored and shown; nothing reads them when generating.
"""

from __future__ import annotations

from pydantic import Field

from .common import CompleteModel, ContractModel

MAX_INSTRUCTION_CHARS = 20_000


class GlobalInstruction(CompleteModel):
    # The text new projects start with. Empty until someone writes one.
    instruction: str


class GlobalInstructionUpdate(ContractModel):
    instruction: str = Field(max_length=MAX_INSTRUCTION_CHARS)
