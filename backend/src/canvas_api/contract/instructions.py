"""Instructions: standing guidance, like custom instructions in a chat app.

Two kinds, both sent to the text model with every step run and AI edit:

- A **collection instruction**: what every project (video) in the series
  shares, such as its format. Edited in the collection; each project reads
  it live (``Project.collection_instruction``) and can't change it.
- A **project description**: what this one video is about ("Describe
  this video" in the app). Starts empty and belongs to the project.
"""

from __future__ import annotations

MAX_INSTRUCTION_CHARS = 20_000
