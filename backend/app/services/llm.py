"""Helpers for reading Claude Messages API responses."""

from __future__ import annotations

from typing import Any


class ClaudeRefusalError(RuntimeError):
    """Claude declined the request (HTTP 200 with ``stop_reason == "refusal"``)."""


def response_text(message: Any) -> str:
    """Return the concatenated text blocks of a Messages API response.

    Haiku 5.5 thinks by default, so a response can begin with ``thinking``
    blocks; never read ``content[0]`` as the answer. Raises
    ``ClaudeRefusalError`` when the model declined the request.
    """
    if message.stop_reason == "refusal":
        raise ClaudeRefusalError("Claude declined the request.")
    return "".join(block.text for block in message.content if block.type == "text")
