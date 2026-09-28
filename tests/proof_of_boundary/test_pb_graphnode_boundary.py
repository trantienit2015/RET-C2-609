# PB-6 supplement: outer main-slot GraphNode boundary test (Cat 2).
#
# PB-6 (test_pb_invoke_order.py) only discovers BaseNode subclasses under src/nodes/.
# CVSStoreOpsFAQGraphNode lives in src/graph/graph.py (scaffold-canonical placement for
# a Cat 2 outer main-slot GraphNode) - that placement does NOT exempt it from boundary
# testing: it sits in the outer backbone on the caller's input path, so it is a real
# security boundary.

from framework.schemas.agent_status import AgentStatus
from framework.schemas.trust_level import TrustLevel

from src.graph.graph import CVSStoreOpsFAQGraphNode


class TestGraphNodeS1TrustGate:
    def test_rejects_insufficient_trust_before_execute(self):
        node = CVSStoreOpsFAQGraphNode(kb=[], allergen_table=[])
        state = {"user_input": "How do I count inventory?", "caller_trust_level": TrustLevel.ANONYMOUS.value}

        result = node(state)

        assert result["status"] == AgentStatus.ERROR.value
        # execute() (which would call get_subgraph()/invoke()) never ran - the only
        # error_log entry is the S-1 denial itself, not a subgraph error.
        assert any("s-1 trust gate denied" in msg.lower() for msg in result.get("error_log", []))
        assert len(result.get("error_log", [])) == 1


class TestGraphNodeBoundaryMapping:
    def test_extract_input_forwards_only_the_query_and_language(self):
        node = CVSStoreOpsFAQGraphNode(kb=[], allergen_table=[])
        state = {
            "user_input": "Does this bento contain egg?",
            "detected_language": "en",
            "correlation_id": "corr-1",
            "some_unrelated_field": "must not leak into subgraph input",
        }

        extracted = node.extract_input(state)

        assert isinstance(extracted, str)
        assert "must not leak into subgraph input" not in extracted
        assert "Does this bento contain egg?" in extracted
        assert '"language": "en"' in extracted

    def test_merge_output_maps_fields_explicitly_not_pass_through(self):
        """Criterion #9: merge_output must not leak raw sub_result keys verbatim."""
        node = CVSStoreOpsFAQGraphNode(kb=[], allergen_table=[])
        sub_result = {
            "retrieved_entries": "[]",
            "allergen_matches": "[]",
            "output": "answer text",
            "status": AgentStatus.SUCCESS.value,
            "node_history": ["knowledge_retrieve_allergen_compliance", "response_generate"],
            "trace_id": "inner-trace-id",
        }

        merged = node.merge_output({"correlation_id": "corr-2"}, sub_result)

        assert set(merged.keys()) == {
            # mapped explicitly like every other field - post_process reads it to report
            # a refusal instead of an answer
            "error_code",
            "retrieved_entries",
            "allergen_matches",
            "formatted_answer",
            "result",
            "status",
        }
        # Inner-only bookkeeping fields are NOT pass-through leaked.
        assert "node_history" not in merged
        assert "trace_id" not in merged
        assert merged["formatted_answer"] == "answer text"

    def test_merge_output_keeps_the_outer_refusal_over_the_inner_one(self):
        """The outer step names the specific reason; the inner node, seeded with the
        request envelope alone, can only report the generic one. Composing inner-first
        would overwrite the specific reason with the generic one."""
        node = CVSStoreOpsFAQGraphNode(kb=[], allergen_table=[])

        merged = node.merge_output(
            {"error_code": "OUTER_REASON"},
            {"error_code": "INNER_REASON", "status": AgentStatus.SUCCESS.value},
        )

        assert merged["error_code"] == "OUTER_REASON"


# Delegation is deliberate: CVSStoreOpsFAQGraphNode.execute() (framework GraphNode base)
# invokes the inner CVSStoreOpsFAQWorkflowGraph, whose entry node runs its own S-2/S-3
# gates via BaseNode.__call__(). The outer GraphNode owns S-1 (tested above) and
# delegates content gating.
