"""AgentCore Platform v1.0 - RET-C2-609 KnowledgeRetrieveAllergenComplianceNode (inner subgraph).

Combines KnowledgeRetrieve (vector-similarity KB lookup) + AllergenCompliance
(食品表示法 28-allergen rule-table lookup) per the original draft's node
flow, since both are deterministic KB lookups on the same query/language
input with no branching between them.
"""

from typing import Any, ClassVar

from framework.nodes.function_node import FunctionNode
from framework.schemas.agent_status import AgentStatus
from framework.schemas.trust_level import TrustLevel
from shared.utils.audit_logger import emit_trace_event

from src.services.degradation import EMPTY_INPUT, KNOWLEDGE_BASE_NOT_CONFIGURED

from src.schemas.state import from_json, to_json
from src.services.service import lookup_allergen_rules, retrieve_kb_entries


class KnowledgeRetrieveAllergenComplianceNode(FunctionNode):
    """Retrieve KB entries and check for 食品表示法 allergen rule matches."""

    required_trust_level: ClassVar[TrustLevel] = TrustLevel.VERIFIED_EXTERNAL

    def __init__(
        self, kb: list[dict[str, Any]] | None = None, allergen_table: list[dict[str, Any]] | None = None
    ) -> None:
        super().__init__()
        self._kb = kb or []
        self._allergen_table = allergen_table or []

    def execute(self, state: dict[str, Any]) -> dict[str, Any]:
        # extract_input() forwards a combined {query, language} JSON
        # envelope as user_input - detected_language is an independent
        # outer-classified field, not re-derivable from the query alone
        # (see the multi-field envelope pattern).
        envelope = from_json(state.get("user_input"), {})
        query = envelope.get("query", "")
        language = envelope.get("language", "en")

        if not query:
            # The subgraph is seeded with the request envelope alone, so this node cannot
            # tell "the outer step already refused" from "upstream dropped the field".
            # Both readings point at the same thing the caller can do.
            return {"error_code": EMPTY_INPUT, "status": AgentStatus.SUCCESS.value}

        if not self._kb and not self._allergen_table:
            emit_trace_event("kb_allergen_not_configured", {"correlation_id": state.get("correlation_id", "")}, state)
            # With nothing to search, "no matching entry" would be a claim that was never
            # checked. The run says the deployment has no knowledge base instead.
            return {"error_code": KNOWLEDGE_BASE_NOT_CONFIGURED, "status": AgentStatus.SUCCESS.value}

        retrieved_entries = retrieve_kb_entries(query, language, kb=self._kb)
        allergen_matches = lookup_allergen_rules(query, allergen_table=self._allergen_table)

        # S-4: domain event for the compliance-critical KB
        # lookup - hit counts only, no raw query/passage content.
        emit_trace_event(
            "kb_allergen_retrieved",
            {"retrieved_count": len(retrieved_entries), "allergen_match_count": len(allergen_matches)},
            state,
        )

        return {
            "retrieved_entries": to_json(retrieved_entries),
            "allergen_matches": to_json(allergen_matches),
            "status": AgentStatus.SUCCESS.value,
        }
