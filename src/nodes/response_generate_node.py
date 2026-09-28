"""AgentCore Platform v1.0 - RET-C2-609 ResponseGenerateNode (inner subgraph).

LLM-essential in a real deployment; deterministic fallback keeps the
pipeline runnable without an LLM. Runs after
KnowledgeRetrieveAllergenComplianceNode within the SAME inner subgraph
invocation - retrieved_entries/allergen_matches are already in state
(no GraphNode boundary crossing between inner nodes).
"""

from typing import Any, ClassVar

from framework.nodes.function_node import FunctionNode
from framework.schemas.agent_status import AgentStatus
from framework.schemas.trust_level import TrustLevel
from shared.utils.audit_logger import emit_trace_event

from src.services.degradation import EMPTY_INPUT

from src.schemas.state import from_json
from src.services.service import format_answer


class ResponseGenerateNode(FunctionNode):
    """Synthesize the grounded, KB-cited answer."""

    required_trust_level: ClassVar[TrustLevel] = TrustLevel.VERIFIED_EXTERNAL

    def __init__(self, llm: Any | None = None) -> None:
        super().__init__()
        self._llm = llm

    def execute(self, state: dict[str, Any]) -> dict[str, Any]:
        envelope = from_json(state.get("user_input"), {})
        query = envelope.get("query", "")
        language = envelope.get("language", "en")
        retrieved_entries = from_json(state.get("retrieved_entries", ""), [])
        allergen_matches = from_json(state.get("allergen_matches", ""), [])

        if not query:
            # Same reading as the retrieval step above: the envelope carries no question,
            # which is the one thing the caller can fix.
            return {"error_code": EMPTY_INPUT, "status": AgentStatus.SUCCESS.value}

        answer = format_answer(query, language, retrieved_entries, allergen_matches, llm=self._llm)

        # S-4: domain event for the generation step -
        # language + answer length only, no raw answer content.
        emit_trace_event("response_generated", {"language": language, "answer_length": len(answer)}, state)

        return {
            "formatted_answer": answer,
            "status": AgentStatus.SUCCESS.value,
        }
