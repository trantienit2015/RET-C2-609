"""AgentCore Platform v1.0 - RET-C2-609 InputValidationLanguageDetectNode (outer pre_process).

Combines InputValidation (S-1 + S-2) + LanguageDetect (multilingual
routing: JA/EN/ZH/VI) per the original draft's node flow, since both
operate on the raw input with no branching between them.
"""

from typing import Any, ClassVar

from framework.nodes.function_node import FunctionNode
from shared.services.events import emitter
from shared.services.events.types import EventType
from framework.schemas.agent_status import AgentStatus
from framework.schemas.trust_level import TrustLevel
from shared.utils.audit_logger import emit_trace_event

from src.services.degradation import EMPTY_INPUT

from src.services.service import detect_language


class InputValidationLanguageDetectNode(FunctionNode):
    """Validate the staff query and detect its language for KB routing."""

    # Corrected from the original draft's invalid "AUTHENTICATED" literal -
    # TrustLevel has no AUTHENTICATED member; VERIFIED_EXTERNAL is the
    # nearest valid value (authenticated staff, not anonymous public access).
    required_trust_level: ClassVar[TrustLevel] = TrustLevel.VERIFIED_EXTERNAL

    def execute(self, state: dict[str, Any]) -> dict[str, Any]:
        # Progress (non-terminal) event for the caller. Outside the Marketplace runtime
        # this resolves to a no-op emitter, so it is safe on every entry path.
        emitter().emit_event(
            event_type=EventType.PROGRESS_UPDATE,
            message="Checking the request...",
            metadata={"step": "pre_process"},
        )
        user_input = state.get("user_input", "")

        if not user_input or not user_input.strip():
            # The caller can act on this, so the run completes and carries the reason.
            emit_trace_event("cvs_faq_query_refused", {"error_code": EMPTY_INPUT}, state)
            return {
                "error_code": EMPTY_INPUT,
                "status": AgentStatus.SUCCESS.value,
            }

        detected_language = detect_language(user_input)

        # S-4: domain event for the language-routing
        # decision - language only, no raw query content (PII surface).
        emit_trace_event("language_detected", {"detected_language": detected_language}, state)

        return {
            "detected_language": detected_language,
            "status": AgentStatus.SUCCESS.value,
        }
