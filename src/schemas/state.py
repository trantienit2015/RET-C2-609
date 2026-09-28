"""AgentCore Platform v1.0 - RET-C2-609 state schema.

Retail CVS Store Operations Staff FAQ Agent (食品表示法 allergen rules +
multilingual 外国人労働者 support). Flat TypedDict extension of AgentState
(ADR-005). Structured payloads (dict/list) are JSON-string-encoded before
being stored in state fields.
"""

import json
from typing import Any, NotRequired

from framework.schemas.agent_state import AgentState


def to_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False)


def from_json(value: str | None, default: Any = None) -> Any:
    if not value:
        return default
    try:
        return json.loads(value)
    except (TypeError, ValueError):
        return default


class State(AgentState):
    """Agent state for RET-C2-609.

    detected_language: "ja" | "en" | "zh" | "vi" - detected from user_input.
    retrieved_entries: JSON list[dict] of matched KB entries (store ops
      procedures + allergen rules), each version-stamped.
    allergen_matches: JSON list[dict] of matched allergen rule-table entries
      when the query concerns a specific allergen/menu item.
    formatted_answer: str - final grounded answer citing KB sources.
    """

    # Outcome marker. A run that completes without an answer - a caller-correctable refusal or
    # a policy withholding - carries this code, and its output says why in wording
    # derived from the code alone (src/services/degradation.py). A security failure or
    # an internally inconsistent run ends as status=ERROR instead.
    error_code: NotRequired[str]

    detected_language: str
    retrieved_entries: str
    allergen_matches: str
    formatted_answer: str
