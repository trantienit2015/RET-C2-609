"""AgentCore Platform v1.0 - RET-C2-609 inner domain workflow graph.

Cat 2 inner graph: KB retrieval + allergen rule-table lookup (Tool) -> LLM-
optional grounded answer synthesis. Instantiated by
CVSStoreOpsFAQGraphNode.get_subgraph() in graph.py.

Pipeline (linear, fail-fast on ERROR):
    START -> knowledge_retrieve_allergen_compliance -> response_generate -> END
"""

from typing import Any

from framework.graph.base_graph import BaseGraph
from framework.schemas.agent_state import AgentState
from framework.schemas.agent_status import AgentStatus
from langgraph.graph import END, START

from src.nodes.knowledge_retrieve_allergen_compliance_node import KnowledgeRetrieveAllergenComplianceNode
from src.nodes.response_generate_node import ResponseGenerateNode
from src.schemas.state import State


class CVSStoreOpsFAQWorkflowGraph(BaseGraph):
    """Inner graph for the RET-C2-609 CVS store ops FAQ workflow."""

    @property
    def name(self) -> str:
        return "ret-cvs-store-ops-faq-workflow"

    @property
    def state_schema(self) -> type:
        return State

    def _validate_config(self) -> None:
        # No mandatory config: kb/allergen_table/llm are optional.
        pass

    def register_nodes(self) -> None:
        # No super() - BaseGraph.register_nodes() is abstract.
        kb = self.config.get("kb")
        allergen_table = self.config.get("allergen_table")
        llm = self.config.get("llm")

        self._nodes["knowledge_retrieve_allergen_compliance"] = KnowledgeRetrieveAllergenComplianceNode(
            kb=kb, allergen_table=allergen_table
        )
        self._nodes["response_generate"] = ResponseGenerateNode(llm=llm)

    def add_edges(self) -> None:
        self._sg.add_edge(START, "knowledge_retrieve_allergen_compliance")
        self._sg.add_conditional_edges(
            "knowledge_retrieve_allergen_compliance",
            lambda s: END if self._is_error(s) else "response_generate",
            {"response_generate": "response_generate", END: END},
        )
        self._sg.add_edge("response_generate", END)

    @staticmethod
    def _is_error(state: AgentState) -> bool:
        # A degraded rejection ends the run as SUCCESS, so keying only on the status
        # would let the remaining nodes run on a request that was already refused.
        return bool(state.get("error_code")) or state.get("status") == AgentStatus.ERROR.value

    def route(self, state: AgentState) -> str:
        return END if self._is_error(state) else "response_generate"

    def get_output(self, state: AgentState) -> dict[str, Any]:
        return {
            "error_code": state.get("error_code"),
            "retrieved_entries": state.get("retrieved_entries"),
            "allergen_matches": state.get("allergen_matches"),
            "output": state.get("formatted_answer"),
            "status": state.get("status"),
            "trace_id": state.get("trace_id"),
            "correlation_id": state.get("correlation_id"),
            "node_history": state.get("node_history", []),
        }
