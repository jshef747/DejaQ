import uuid
import logging
from datetime import datetime, timezone
from typing import Optional

logger = logging.getLogger("dejaq.services.conversation_store")


class ConversationStore:
    """In-memory conversation history for multi-turn chat."""

    def __init__(self, max_history: int = 20):
        self._conversations: dict[str, list[dict]] = {}
        self._metadata: dict[str, dict] = {}  # {conv_id: {created_at, preview}}
        self._max_history = max_history

    def get_or_create(self, conversation_id: Optional[str] = None) -> str:
        if conversation_id and conversation_id in self._conversations:
            return conversation_id
        new_id = conversation_id or str(uuid.uuid4())
        self._conversations[new_id] = []
        self._metadata[new_id] = {
            "created_at": datetime.now(timezone.utc).isoformat(),
            "preview": "",
        }
        logger.info("Created conversation %s", new_id)
        return new_id

    def get_history(self, conversation_id: str) -> list[dict]:
        return list(self._conversations.get(conversation_id, []))

    def add_message(self, conversation_id: str, role: str, content: str) -> None:
        if conversation_id not in self._conversations:
            self._conversations[conversation_id] = []
        self._conversations[conversation_id].append({"role": role, "content": content})

        # Set preview from first user message
        meta = self._metadata.get(conversation_id)
        if meta and not meta["preview"] and role == "user":
            meta["preview"] = content[:80]

        # Trim to stay within context window
        if len(self._conversations[conversation_id]) > self._max_history:
            self._conversations[conversation_id] = self._conversations[conversation_id][-self._max_history:]
            logger.debug("Trimmed conversation %s to %d messages", conversation_id, self._max_history)

    def list_conversations(self) -> list[dict]:
        """Return all conversations sorted newest-first."""
        result = []
        for conv_id, messages in self._conversations.items():
            meta = self._metadata.get(conv_id, {})
            result.append({
                "id": conv_id,
                "preview": meta.get("preview", ""),
                "created_at": meta.get("created_at", ""),
                "message_count": len(messages),
            })
        result.sort(key=lambda c: c["created_at"], reverse=True)
        return result

    def delete_conversation(self, conversation_id: str) -> bool:
        """Delete a conversation. Returns True if it existed."""
        if conversation_id in self._conversations:
            del self._conversations[conversation_id]
            self._metadata.pop(conversation_id, None)
            logger.info("Deleted conversation %s", conversation_id)
            return True
        return False
