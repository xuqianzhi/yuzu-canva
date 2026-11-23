"""Each text node's chat with the model."""

from __future__ import annotations

from ..contract import (
    ChatMessage,
    ChatRole,
    ErrorCode,
    Output,
)
from ..errors import ApiError
from ..ids import new_id
from .base import (
    Row,
    _dt,
    _not_found,
    _ts,
    now,
)


class ChatMixin:
    """Each text node's chat with the model."""

    @staticmethod
    def _message(r: Row) -> ChatMessage:
        return ChatMessage(
            id=r["id"],
            node_id=r["node_id"],
            role=ChatRole(r["role"]),
            text=r["text"],
            proposal=r["proposal"],
            applied_output_id=r["applied_output_id"],
            created_at=_dt(r["created_at"]),
        )

    def list_messages(self, node_id: str) -> list[ChatMessage]:
        self.get_node(node_id)
        rows = self._all("SELECT * FROM messages WHERE node_id = ? ORDER BY seq", node_id)
        return [self._message(r) for r in rows]

    def get_message(self, message_id: str) -> ChatMessage:
        row = self._one("SELECT * FROM messages WHERE id = ?", message_id)
        if not row:
            raise _not_found("message", message_id)
        return self._message(row)

    def add_messages(
        self, node_id: str, messages: list[tuple[ChatRole, str, str | None]]
    ) -> list[ChatMessage]:
        ids = []
        with self._tx() as db:
            for role, text, proposal in messages:
                message_id = new_id("msg")
                db.execute(
                    "INSERT INTO messages (id, node_id, role, text, proposal, created_at) "
                    "VALUES (?, ?, ?, ?, ?, ?)",
                    (message_id, node_id, role.value, text, proposal, _ts(now())),
                )
                ids.append(message_id)
        return [self.get_message(i) for i in ids]

    def apply_proposal(self, message_id: str) -> Output:
        message = self.get_message(message_id)
        if message.proposal is None:
            raise ApiError(409, ErrorCode.validation_error, "this message has no proposal")
        output = self.add_text_take(message.node_id, message.proposal)
        with self._tx() as db:
            db.execute(
                "UPDATE messages SET applied_output_id = ? WHERE id = ?",
                (output.id, message_id),
            )
        return output
