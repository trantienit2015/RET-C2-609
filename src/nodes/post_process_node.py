"""AgentCore Platform v1.0 - RET-C2-609 AuditLogValidateNode (outer post_process slot).

Combines AuditLog (S-4: emit_trace_event() for the compliance query domain
event) + OutputValidate (S-3: non-suppressible re-check that no
compliance claim in the answer is unsourced) per the original draft's
node flow. Own-dict field re-check only (S-3 self-consistency rule -
s3 hook cross state recheck fragile).
"""

from typing import Any, ClassVar

from framework.nodes.function_node import FunctionNode
from shared.services.events import emitter
from shared.services.events.types import EventType
from framework.schemas.agent_status import AgentStatus
from framework.schemas.trust_level import TrustLevel
from shared.utils.audit_logger import emit_trace_event

from src.schemas.state import from_json
from src.services.degradation import CITATION_WITHHELD, explain_degradation
from src.services.service import has_unsourced_compliance_claim


class AuditLogValidateNode(FunctionNode):
    """Audit-log the compliance query and validate the answer cites only known sources."""

    required_trust_level: ClassVar[TrustLevel] = TrustLevel.VERIFIED_EXTERNAL

    def execute(self, state: dict[str, Any]) -> dict[str, Any]:
        # Progress (non-terminal) event for the caller. Outside the Marketplace runtime
        # this resolves to a no-op emitter, so it is safe on every entry path.
        emitter().emit_event(
            event_type=EventType.PROGRESS_UPDATE,
            message="Preparing the result...",
            metadata={"step": "post_process"},
        )
        # A degraded run produced no answer by design. The output keeps a caller-facing
        # shape and states why; every value is a constant, so nothing the refused request
        # left in State reaches the caller. The sourcing invariant below does not apply:
        # it exists so that no produced *answer* leaves citing an unknown reference, and
        # a refusal cites nothing.
        degraded_code = state.get("error_code", "")
        if degraded_code:
            reason = explain_degradation(degraded_code)
            emit_trace_event("cvs_faq_answer_degraded", {"error_code": degraded_code}, state)
            return {
                # carried in this node's own dict so the S-3 re-check - which sees that
                # dict, not the full state - can scope itself to produced answers
                "error_code": degraded_code,
                "formatted_output": reason,
                "status": AgentStatus.SUCCESS.value,
            }

        formatted_answer = state.get("formatted_answer", "")
        retrieved_entries = from_json(state.get("retrieved_entries", ""), [])
        allergen_matches = from_json(state.get("allergen_matches", ""), [])

        if has_unsourced_compliance_claim(formatted_answer, retrieved_entries, allergen_matches):
            # A policy outcome under the answer-quality contract, not a failure: the
            # answer is replaced by a fixed statement that none is coming, so the
            # unsourced citation cannot leave in any field.
            emit_trace_event("audit_log_validate_unsourced_claim_blocked", {}, state)
            return self._withheld(
                "AuditLogValidateNode: answer cites a compliance reference not present in any retrieved KB source"
            )

        # S-4: domain event for the compliance query (APPI 2026 staff query
        # audit trail) - language + response-source citation, no raw PII.
        emit_trace_event(
            "cvs_faq_compliance_query_answered",
            {
                "detected_language": state.get("detected_language", ""),
                "kb_sources_cited": len(retrieved_entries) + len(allergen_matches),
            },
            state,
        )

        return {
            "formatted_output": formatted_answer,
            # The S-3 re-check below sees this dict, not the full state (self-consistency
            # rule), so the fields it reads have to be in it. Returning only the assembled
            # output made the re-check scan an empty answer against no sources and pass on
            # every run - a non-suppressible gate that never actually fired.
            "formatted_answer": formatted_answer,
            "retrieved_entries": state.get("retrieved_entries", ""),
            "allergen_matches": state.get("allergen_matches", ""),
            "status": AgentStatus.SUCCESS.value,
        }

    def _extra_security_gate_output(self, state: dict[str, Any]) -> dict[str, Any]:
        """Non-suppressible re-check on the output dict's own fields.

        The invariant applies to produced answers. A degraded run carries a refusal
        instead - so the check is scoped by the degradation marker, not weakened.
        """
        if state.get("error_code"):
            return state
        formatted_answer = state.get("formatted_answer", "")
        retrieved_entries = from_json(state.get("retrieved_entries", ""), [])
        allergen_matches = from_json(state.get("allergen_matches", ""), [])

        if has_unsourced_compliance_claim(formatted_answer, retrieved_entries, allergen_matches):
            emit_trace_event("audit_log_validate_s3_recheck_blocked", {}, state)
            return self._withheld(
                "AuditLogValidateNode: S-3 re-check blocked an answer citing an unsourced compliance reference"
            )
        return state

    @staticmethod
    def _withheld(log_line: str) -> dict[str, Any]:
        """The result that replaces an answer withheld under the citation policy.

        Both answer fields are overwritten with the caller-facing statement, and the
        source lists are not carried on, so nothing from the rejected answer travels
        further.
        """
        reason = explain_degradation(CITATION_WITHHELD)
        return {
            "error_code": CITATION_WITHHELD,
            "formatted_output": reason,
            "formatted_answer": reason,
            "status": AgentStatus.SUCCESS.value,
            "error_log": [log_line],
        }
