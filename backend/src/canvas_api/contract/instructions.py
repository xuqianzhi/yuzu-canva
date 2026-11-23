"""Instructions: standing guidance for a whole canvas, like a project's
custom instructions in a chat app.

Every collection has one, and every project has its own, copied from its
collection's when the project is created and edited separately after that.
For now they are only stored and shown; nothing reads them when generating.
"""

from __future__ import annotations

MAX_INSTRUCTION_CHARS = 20_000
