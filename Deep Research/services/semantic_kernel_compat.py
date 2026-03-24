"""
Compatibility helpers for Semantic Kernel imports used across the app.
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:  # pragma: no cover
    from semantic_kernel.contents.chat_history import ChatHistory as SemanticKernelChatHistory
else:  # pragma: no cover
    SemanticKernelChatHistory = Any


def create_chat_history() -> "SemanticKernelChatHistory":
    """Create a ChatHistory instance via a single local import boundary."""
    from semantic_kernel.contents.chat_history import ChatHistory

    return ChatHistory()
