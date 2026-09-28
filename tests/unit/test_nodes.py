# RET-C2-609 - Unit tests: per-node success + error/edge paths.

from framework.schemas.agent_status import AgentStatus

from src.nodes.knowledge_retrieve_allergen_compliance_node import KnowledgeRetrieveAllergenComplianceNode
from src.nodes.post_process_node import AuditLogValidateNode
from src.nodes.pre_process_node import InputValidationLanguageDetectNode
from src.nodes.response_generate_node import ResponseGenerateNode
from src.schemas.state import from_json, to_json
from src.services.degradation import CITATION_WITHHELD, EMPTY_INPUT, KNOWLEDGE_BASE_NOT_CONFIGURED

KB = [{"language": "en", "keywords": ["inventory"], "ref_id": "OPS-01", "version": "2026.1", "summary": "Daily inventory count procedure"}]
ALLERGEN_TABLE = [{"allergen": "shrimp", "ref_id": "ALG-2026-07", "version": "2026.1", "summary": "Shrimp mandatory disclosure"}]


class TestInputValidationLanguageDetectNode:
    def test_success_japanese(self):
        state = {"user_input": "アレルゲン表示について教えてください"}
        r = InputValidationLanguageDetectNode().execute(state)
        assert r["status"] == AgentStatus.SUCCESS
        assert r["detected_language"] == "ja"

    def test_success_vietnamese(self):
        state = {"user_input": "Xin chào, tôi cần hỏi về quy trình"}
        r = InputValidationLanguageDetectNode().execute(state)
        assert r["status"] == AgentStatus.SUCCESS
        assert r["detected_language"] == "vi"

    def test_success_english_default(self):
        state = {"user_input": "How do I count inventory?"}
        r = InputValidationLanguageDetectNode().execute(state)
        assert r["status"] == AgentStatus.SUCCESS
        assert r["detected_language"] == "en"

    def test_empty_input_degrades(self):
        # The reason travels as an allow-listed code on a completed run; asserting the
        # status alone would also pass on a node that silently produced no answer.
        r = InputValidationLanguageDetectNode().execute({"user_input": ""})
        assert r["status"] == AgentStatus.SUCCESS.value
        assert r["error_code"] == EMPTY_INPUT


class TestKnowledgeRetrieveAllergenComplianceNode:
    def test_success_matches_found(self):
        envelope = {"query": "Does this item contain shrimp allergen?", "language": "en"}
        state = {"user_input": to_json(envelope)}
        r = KnowledgeRetrieveAllergenComplianceNode(kb=KB, allergen_table=ALLERGEN_TABLE).execute(state)
        assert r["status"] == AgentStatus.SUCCESS
        assert len(from_json(r["allergen_matches"], [])) == 1

    def test_success_no_matches(self):
        envelope = {"query": "unrelated question", "language": "en"}
        state = {"user_input": to_json(envelope)}
        r = KnowledgeRetrieveAllergenComplianceNode(kb=KB, allergen_table=ALLERGEN_TABLE).execute(state)
        assert r["status"] == AgentStatus.SUCCESS
        assert from_json(r["allergen_matches"], []) == []

    def test_missing_query_degrades(self):
        r = KnowledgeRetrieveAllergenComplianceNode(kb=KB).execute({"user_input": ""})
        assert r["status"] == AgentStatus.SUCCESS.value
        assert r["error_code"] == EMPTY_INPUT

    def test_no_knowledge_base_reports_not_configured(self):
        """With nothing to search, "no matching entry" would be a claim never checked."""
        state = {"user_input": to_json({"query": "How do I count inventory at closing?", "language": "en"})}
        r = KnowledgeRetrieveAllergenComplianceNode().execute(state)
        assert r == {"error_code": KNOWLEDGE_BASE_NOT_CONFIGURED, "status": AgentStatus.SUCCESS.value}


class TestResponseGenerateNode:
    def test_success_cites_kb_ref(self):
        envelope = {"query": "How do I count inventory?", "language": "en"}
        state = {"user_input": to_json(envelope), "retrieved_entries": to_json(KB), "allergen_matches": to_json([])}
        r = ResponseGenerateNode().execute(state)
        assert r["status"] == AgentStatus.SUCCESS
        assert "OPS-01" in r["formatted_answer"]

    def test_missing_query_degrades(self):
        r = ResponseGenerateNode().execute({"user_input": ""})
        assert r["status"] == AgentStatus.SUCCESS.value
        assert r["error_code"] == EMPTY_INPUT


class TestAuditLogValidateNode:
    def test_success_all_sourced(self):
        state = {
            "formatted_answer": "[OPS-01] Daily inventory count procedure",
            "retrieved_entries": to_json(KB),
            "allergen_matches": to_json([]),
        }
        r = AuditLogValidateNode().execute(state)
        assert r["status"] == AgentStatus.SUCCESS

    def test_unsourced_reference_withholds_the_answer(self):
        state = {
            "formatted_answer": "[FAKE-999] fabricated compliance claim",
            "retrieved_entries": to_json(KB),
            "allergen_matches": to_json([]),
        }
        r = AuditLogValidateNode().execute(state)
        # The fabricated citation must be gone from every field - that is the
        # withholding, a policy outcome rather than a failure.
        assert "FAKE-999" not in str(r)
        assert r["error_code"] == CITATION_WITHHELD
        assert r["status"] == AgentStatus.SUCCESS.value

    def test_extra_gate_blocks_unsourced_reference(self):
        bad_state = {"formatted_answer": "[FAKE-999] fabricated claim", "retrieved_entries": to_json([]), "allergen_matches": to_json([])}
        out = AuditLogValidateNode()._extra_security_gate_output(bad_state)
        assert "FAKE-999" not in str(out)
        assert out["error_code"] == CITATION_WITHHELD

    def test_extra_gate_passthrough_sourced_answer(self):
        good_state = {"formatted_answer": "[OPS-01] procedure", "retrieved_entries": to_json(KB), "allergen_matches": to_json([])}
        assert AuditLogValidateNode()._extra_security_gate_output(good_state) is good_state


class TestAuditLogValidateS3Recheck:
    def test_success_return_carries_what_the_recheck_reads(self):
        """The hook sees this node's own result dict, not the full state (self-consistency
        rule). A return that omits the answer and its sources makes the re-check scan an
        empty string against no sources and pass on every run - a non-suppressible gate
        that never actually fires."""
        node = AuditLogValidateNode()
        state = {
            "formatted_answer": "[OPS-01] Daily inventory count procedure",
            "retrieved_entries": to_json(KB),
            "allergen_matches": to_json([]),
        }

        result = node.execute(state)

        assert result["status"] == AgentStatus.SUCCESS.value
        assert result["formatted_answer"] == state["formatted_answer"]
        assert result["retrieved_entries"] == state["retrieved_entries"]
        assert result["allergen_matches"] == state["allergen_matches"]
        # Given that dict the hook really evaluates it: a grounded citation survives,
        # a reference present in no source is blocked.
        assert node._extra_security_gate_output(result) is result
        tampered = {**result, "formatted_answer": result["formatted_answer"] + " see ALG-9999-01"}
        blocked = node._extra_security_gate_output(tampered)
        assert blocked["error_code"] == CITATION_WITHHELD
        assert "ALG-9999-01" not in str(blocked)

    def test_degraded_refusal_is_not_scanned_as_an_answer(self):
        """The refusal carries no citations, so scoping the check by the marker withholds
        nothing - it keeps the gate from judging a message that is not an answer."""
        node = AuditLogValidateNode()
        result = node.execute({"error_code": EMPTY_INPUT})

        assert result["status"] == AgentStatus.SUCCESS.value
        assert result["error_code"] == EMPTY_INPUT
        assert node._extra_security_gate_output(result) is result
