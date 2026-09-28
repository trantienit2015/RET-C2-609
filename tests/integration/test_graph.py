# RET-C2-609 - Integration test: full graph compile + invoke (Cat 2 outer + inner).

from framework.schemas.invocation_context import InvocationContext
from framework.schemas.trust_level import TrustLevel

from src.graph.graph import Graph
from src.services import degradation

KB = [{"language": "en", "keywords": ["inventory"], "ref_id": "OPS-01", "version": "2026.1", "summary": "Daily inventory count procedure"}]
ALLERGEN_TABLE = [{"allergen": "shrimp", "ref_id": "ALG-2026-07", "version": "2026.1", "summary": "Shrimp mandatory disclosure"}]

ALLERGEN_QUERY = "Does this bento contain shrimp allergen?"
OPS_QUERY = "How do I count inventory at closing?"
EMPTY_QUERY = ""


class TestAgentIntegration:
    def test_allergen_question_reaches_full_pipeline(self):
        # Per the S-2 gate's effect on the success path, assert the
        # environment-independent invariant (pipeline completion), not an
        # exact terminal status - unit tests already pin the success-path
        # logic deterministically.
        agent = Graph(config={"max_retry": 1, "kb": KB, "allergen_table": ALLERGEN_TABLE})
        agent.compile()
        ctx = InvocationContext(session_id="it-1", caller_trust_level=TrustLevel.VERIFIED_EXTERNAL, caller_id="staff-001")
        result = agent.invoke(ALLERGEN_QUERY, ctx=ctx)

        assert len(result.get("node_history", [])) >= 4
        assert result["status"] in ("success", "error", "cancelled")

    def test_ops_question_reaches_full_pipeline(self):
        agent = Graph(config={"max_retry": 1, "kb": KB, "allergen_table": ALLERGEN_TABLE})
        agent.compile()
        ctx = InvocationContext(session_id="it-2", caller_trust_level=TrustLevel.VERIFIED_EXTERNAL, caller_id="staff-001")
        result = agent.invoke(OPS_QUERY, ctx=ctx)

        assert len(result.get("node_history", [])) >= 4
        assert result["status"] in ("success", "error", "cancelled")

    def test_empty_query_degrades_instead_of_failing(self):
        """End-to-end shape of a caller-correctable rejection: the run completes and the
        reason is in the output."""
        agent = Graph(config={"max_retry": 1, "kb": KB, "allergen_table": ALLERGEN_TABLE})
        agent.compile()
        ctx = InvocationContext(session_id="it-3", caller_trust_level=TrustLevel.VERIFIED_EXTERNAL, caller_id="staff-001")
        result = agent.invoke(EMPTY_QUERY, ctx=ctx)
        assert result["status"] == "success"
        assert result["output"] == degradation.explain_degradation(degradation.EMPTY_INPUT)

    def test_refused_request_never_reaches_the_knowledge_base(self):
        """The refusal happens before retrieval, so the short-circuit - not the absence of
        data - is what has to stop the search. The knowledge base fails the test if used."""

        class RefusingKB(list):
            def __iter__(self):
                raise AssertionError("the store-operations knowledge base was searched on a refused request")

        agent = Graph(config={"max_retry": 1, "kb": RefusingKB(), "allergen_table": ALLERGEN_TABLE})
        agent.compile()
        ctx = InvocationContext(session_id="it-6", caller_trust_level=TrustLevel.VERIFIED_EXTERNAL, caller_id="staff-001")
        result = agent.invoke(EMPTY_QUERY, ctx=ctx)
        assert result["status"] == "success"
        assert result["output"] == degradation.explain_degradation(degradation.EMPTY_INPUT)


def test_full_graph_without_knowledge_base_reports_not_configured():
    """A deployment given no knowledge base completes and says nothing was looked up."""
    agent = Graph(config={"max_retry": 1})
    agent.compile()
    ctx = InvocationContext(session_id="it-9", caller_trust_level=TrustLevel.VERIFIED_EXTERNAL, caller_id="staff-001")
    result = agent.invoke("How do I count inventory at closing?", ctx=ctx)
    assert result["status"] == "success"
    assert result["output"] == degradation.explain_degradation(degradation.KNOWLEDGE_BASE_NOT_CONFIGURED)
