"""AgentCore Platform v1.0 - RET-C2-609 outer graph (Cat 2).

Cat 2: outer AgentBaseGraph with the fixed 5-node backbone. Domain
complexity is encapsulated in CVSStoreOpsFAQGraphNode (the `main` slot),
which wraps the inner CVSStoreOpsFAQWorkflowGraph. Do NOT override
add_edges().

Backbone: initialize -> pre_process(InputValidationLanguageDetect) ->
          main(GraphNode) -> post_process(AuditLogValidate) -> finalize

CVSStoreOpsFAQGraphNode lives here (not under src/nodes/) - the PB-6
invoke-order test only discovers BaseNode subclasses under src/nodes/,
and a GraphNode's __call__ intentionally skips the standard S-2/S-4/S-3
lifecycle (gating is delegated to the inner subgraph).
"""

import json
from typing import Any, ClassVar

from framework.graph.agent_base_graph import AgentBaseGraph
from shared.services.events import emitter
from shared.services.events.types import EventType
from framework.nodes.graph_node import GraphNode
from framework.schemas.agent_state import AgentState
from framework.schemas.trust_level import TrustLevel
from shared.utils.audit_logger import emit_trace_event

from src.nodes.post_process_node import AuditLogValidateNode
from src.nodes.pre_process_node import InputValidationLanguageDetectNode
from src.schemas.state import State


class CVSStoreOpsFAQGraphNode(GraphNode):
    """Wraps the inner KB-retrieval/allergen-compliance/answer-generation workflow (Cat 2 composition)."""

    # S-1: outer main-slot wrapper - a node in the outer backbone receiving caller input,
    # so it carries the same requirement the manifest declares and its pre/post siblings
    # enforce. Left undeclared it inherits ANONYMOUS, and gate-trust-level-check does not
    # scan GraphNode subclasses, so CI would not report the gap.
    required_trust_level: ClassVar[TrustLevel] = TrustLevel.VERIFIED_EXTERNAL
    # "propagate": re-raise inner errors as SubgraphError (fail fast - default).
    error_strategy: ClassVar[str] = "propagate"
    # No HITL in this template.
    propagate_hitl: ClassVar[bool] = False

    def __init__(self, kb: Any | None = None, allergen_table: Any | None = None, llm: Any | None = None) -> None:
        super().__init__()
        self._kb = kb or []
        self._allergen_table = allergen_table or []
        self._llm = llm

    def get_subgraph(self) -> AgentBaseGraph:
        from src.graph.domain_workflow_graph import CVSStoreOpsFAQWorkflowGraph

        sg = CVSStoreOpsFAQWorkflowGraph(
            config={"kb": self._kb, "allergen_table": self._allergen_table, "llm": self._llm}
        )
        sg.compile()
        return sg

    def extract_input(self, state: AgentState) -> str:
        # extract_input() can only forward a single string across the
        # GraphNode subgraph boundary. detected_language is an independent
        # outer-classified field, so re-encode it into a combined envelope
        # per the multi-field envelope pattern.
        # Progress (non-terminal) event for the caller, emitted as the subgraph step
        # begins. Outside the Marketplace runtime this is a no-op emitter.
        emitter().emit_event(
            event_type=EventType.PROGRESS_UPDATE,
            message="Working on the request...",
            metadata={"step": "main"},
        )
        emit_trace_event("ret_cvs_faq_workflow_dispatched", {"correlation_id": state.get("correlation_id", "")}, state)
        return json.dumps(
            {
                "query": state.get("user_input", ""),
                "language": state.get("detected_language", "en"),
            }
        )

    def merge_output(self, state: AgentState, sub_result: dict[str, Any]) -> dict[str, Any]:
        emit_trace_event(
            "ret_cvs_faq_workflow_completed",
            {"correlation_id": state.get("correlation_id", ""), "status": str(sub_result.get("status"))},
            state,
        )
        return {
            # Mapped explicitly like every other field - post_process reads it to report
            # a refusal instead of an answer. The outer marker wins: it names the specific
            # reason, while the inner node can only report the generic one.
            "error_code": state.get("error_code") or sub_result.get("error_code", ""),
            "retrieved_entries": sub_result.get("retrieved_entries"),
            "allergen_matches": sub_result.get("allergen_matches"),
            "formatted_answer": sub_result.get("output"),
            "result": sub_result.get("output"),
            "status": sub_result.get("status"),
        }


class RETCVSStoreOpsFAQAgent(AgentBaseGraph):
    """RET-C2-609 - Retail CVS Store Operations Staff FAQ Agent (Cat 2)."""

    @property
    def name(self) -> str:
        return "ret-c2-609"

    @property
    def state_schema(self) -> type:
        return State

    def register_nodes(self) -> None:
        super().register_nodes()  # injects initialize + finalize

        kb = self.config.get("kb")
        allergen_table = self.config.get("allergen_table")
        llm = self.config.get("llm")

        self._nodes["pre_process"] = InputValidationLanguageDetectNode()
        self._nodes["main"] = CVSStoreOpsFAQGraphNode(kb=kb, allergen_table=allergen_table, llm=llm)
        self._nodes["post_process"] = AuditLogValidateNode()

    # add_edges() is NOT overridden - backbone wiring belongs to the framework.


# Stable alias for the standalone entry point import (src/api/server.py).
Graph = RETCVSStoreOpsFAQAgent
