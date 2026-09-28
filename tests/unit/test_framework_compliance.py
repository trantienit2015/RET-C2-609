# RET-C2-609 - Framework compliance tests TC-01..TC-08.
# Reference shape: another template tests/unit/test_framework_compliance.py,
# adapted to this template's real architecture (Cat 2: outer pre/post + GraphNode-wrapped inner nodes).

import os
import re
import typing

import pytest
from framework.nodes.function_node import FunctionNode
from framework.schemas.agent_state import AgentState
from framework.schemas.agent_status import AgentStatus
from framework.schemas.invocation_context import InvocationContext
from framework.schemas.trust_level import TrustLevel

from src.nodes import knowledge_retrieve_allergen_compliance_node, post_process_node, pre_process_node, response_generate_node
from src.schemas.state import State, to_json
from src.services import degradation

_SRC = os.path.join(os.path.dirname(__file__), "..", "..", "src")
TRUST = TrustLevel.VERIFIED_EXTERNAL.value

KB = [{"language": "en", "keywords": ["inventory"], "ref_id": "OPS-01", "version": "2026.1", "summary": "Daily inventory count procedure"}]
ALLERGEN_TABLE = [{"allergen": "shrimp", "ref_id": "ALG-2026-07", "version": "2026.1", "summary": "Shrimp mandatory disclosure"}]


def _src_files():
    for root, _d, files in os.walk(_SRC):
        for f in files:
            if f.endswith(".py"):
                yield os.path.join(root, f)


# TC-01 - State is a flat TypedDict extending AgentState, added fields are primitives/JSON-str.
class TestTC01StateContract:
    def test_state_is_typeddict_extending_agent_state(self):
        assert hasattr(State, "__annotations__")
        assert "user_input" in State.__annotations__
        assert set(AgentState.__annotations__).issubset(set(State.__annotations__))

    def test_added_fields_are_primitives_or_json_str(self):
        added = [k for k in State.__annotations__ if k not in AgentState.__annotations__]
        assert added, "State must declare agent-specific fields"
        allowed = {"str", "int", "bool", "float"}
        for name in added:
            ann = State.__annotations__[name]
            # NotRequired[str] is a wrapper, not a compound value - unwrap it before
            # judging the payload type, or an optional primitive reads as a violation.
            args = typing.get_args(ann)
            if typing.get_origin(ann) is typing.NotRequired or (args and "NotRequired" in str(ann)):
                ann = args[0]
            ann_str = getattr(ann, "__name__", str(ann))
            assert ann_str in allowed, f"{name}: {ann_str} - compound fields must be JSON-string-encoded"


# TC-02 - Empty/missing input is refused without raising. A refusal the caller can act on
# completes as SUCCESS carrying an allow-listed code, so the reason reaches the caller;
# an answer failing the fail-closed sourcing invariant (TC-10) is withheld, not failed.
class TestTC02Validation:
    def test_empty_input_degrades_no_raise(self):
        node = pre_process_node.InputValidationLanguageDetectNode()
        out = node.execute({"user_input": ""})
        assert out["status"] == AgentStatus.SUCCESS.value
        assert out["error_code"] == degradation.EMPTY_INPUT

    def test_missing_query_envelope_degrades_no_raise(self):
        node = knowledge_retrieve_allergen_compliance_node.KnowledgeRetrieveAllergenComplianceNode(kb=KB)
        out = node.execute({"user_input": ""})
        assert out["status"] == AgentStatus.SUCCESS.value
        assert out["error_code"] == degradation.EMPTY_INPUT


# TC-03 - No JWT / API keys / secrets in src/; no direct os.environ reads.
class TestTC03NoCredentials:
    def test_no_credential_literals(self):
        pat = re.compile(r"(sk-[A-Za-z0-9]{16,}|AKIA[0-9A-Z]{16}|eyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+)")
        offenders = []
        for fp in _src_files():
            with open(fp, encoding="utf-8") as f:
                if pat.search(f.read()):
                    offenders.append(fp)
        assert offenders == []

    def test_no_os_environ_secret_reads(self):
        # The standalone entry point is the ONE permitted os.environ reader: it
        # authenticates the caller (INVOKE_AUTH_TOKEN) BEFORE any InvocationContext
        # exists, so ctx.secrets cannot apply. That token is a deployment-level
        # caller credential, not an agent secret, and is never stored in state.
        # See the framework rules / the STG runbook.
        offenders = []
        for fp in _src_files():
            if os.path.normpath(fp).endswith(os.path.join("src", "api", "server.py")):
                continue
            with open(fp, encoding="utf-8") as f:
                if "os.environ" in f.read():
                    offenders.append(fp)
        assert offenders == []

    def test_entry_point_env_read_is_limited_to_the_caller_auth_token(self):
        """The entry-point exception is narrow: only the two caller credentials may be read."""
        import re

        server = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(
            os.path.abspath(__file__)))), "src", "api", "server.py")
        if not os.path.exists(server):
            return
        with open(server, encoding="utf-8") as f:
            content = f.read()
        reads = re.findall(r"os\.environ(?:\.get)?[(\[]\s*[\"']([A-Z_]+)[\"']", content)
        # Two deployment-level caller credentials are sanctioned at this boundary: the
        # external bearer token and the separate staging-only runner token that maps to
        # INTERNAL. Anything else read from the environment here is still a violation.
        assert set(reads) <= {"INVOKE_AUTH_TOKEN", "STG_INTERNAL_RUNNER_TOKEN"}, (
            f"unexpected env reads: {reads}"
        )


# TC-04 - InvocationContext is never stored in State after invoke.
class TestTC04ContextIsolation:
    def test_no_invocationcontext_in_state_after_invoke(self):
        from src.graph.graph import Graph

        agent = Graph(config={"max_retry": 1, "kb": KB, "allergen_table": ALLERGEN_TABLE})
        agent.compile()
        ctx = InvocationContext(session_id="tc04", caller_trust_level=TrustLevel.VERIFIED_EXTERNAL, caller_id="staff-tc04")
        result = agent.invoke("How do I count inventory?", ctx=ctx)
        for v in result.values():
            assert not isinstance(v, InvocationContext)

    def test_from_state_available(self):
        assert hasattr(InvocationContext, "from_state")


# TC-05 - Domain events: the S-4 side-effect node emits >=1 domain event;
# no node under src/nodes/ ever re-emits a framework backbone lifecycle event.
# (KnowledgeRetrieve/ResponseGenerate are pure inner-subgraph lookups with no
# side effect of their own - the domain audit event lives on AuditLogValidateNode
# plus the GraphNode subgraph-dispatch boundary in src/graph/graph.py.)
class TestTC05Audit:
    def test_audit_node_emits_domain_event(self, monkeypatch):
        events = []
        monkeypatch.setattr(post_process_node, "emit_trace_event", lambda e, p, s: events.append(e))
        state = {
            "formatted_answer": "[OPS-01] Daily inventory count procedure",
            "retrieved_entries": to_json(KB),
            "allergen_matches": to_json([]),
            "detected_language": "en",
        }
        out = post_process_node.AuditLogValidateNode().execute(state)
        assert out["status"] == AgentStatus.SUCCESS
        assert len(events) >= 1
        assert "cvs_faq_compliance_query_answered" in events
        assert not ({"node_start", "node_complete", "node_error", "node_skip"} & set(events))

    def test_source_has_no_backbone_events(self):
        pat = re.compile(r'emit_trace_event\(\s*["\'](node_start|node_complete|node_error|node_skip)["\']')
        offenders = []
        for fp in _src_files():
            with open(fp, encoding="utf-8") as f:
                if pat.search(f.read()):
                    offenders.append(fp)
        assert offenders == []


# TC-06 / TC-07 - S-2/S-3 gates are @final on FunctionNode (overriding raises TypeError at class def).
class TestTC0607FinalGates:
    def test_input_gate_is_final(self):
        with pytest.raises(TypeError):

            class BadIn(FunctionNode):  # noqa: N801
                def _security_gate_input(self, state):
                    return state

    def test_output_gate_is_final(self):
        with pytest.raises(TypeError):

            class BadOut(FunctionNode):  # noqa: N801
                def _security_gate_output(self, result):
                    return result

    def test_extra_hook_is_overridable(self):
        assert post_process_node.AuditLogValidateNode._extra_security_gate_output is not FunctionNode._extra_security_gate_output

    def test_output_gate_blocks_credentials(self):
        # The @final S-3 credential scan actually fires (not vacuous): a
        # credential in the result is blocked, never returned as-is.
        node = post_process_node.AuditLogValidateNode()
        with pytest.raises(Exception):
            node._security_gate_output({"formatted_output": "token AKIAIOSFODNN7EXAMPLE leaked"})


# TC-08 - required_trust_level enforced: insufficient trust -> ERROR state, no raise.
class TestTC08TrustGate:
    def test_declared_trust_levels_valid(self):
        for cls in (
            pre_process_node.InputValidationLanguageDetectNode,
            knowledge_retrieve_allergen_compliance_node.KnowledgeRetrieveAllergenComplianceNode,
            response_generate_node.ResponseGenerateNode,
            post_process_node.AuditLogValidateNode,
        ):
            assert cls.required_trust_level in (TrustLevel.ANONYMOUS, TrustLevel.VERIFIED_EXTERNAL, TrustLevel.INTERNAL)

    def test_insufficient_trust_returns_error(self):
        node = pre_process_node.InputValidationLanguageDetectNode()
        out = node({"caller_trust_level": TrustLevel.ANONYMOUS.value, "user_input": "How do I count inventory?"})
        assert str(out.get("status")).lower().endswith("error")

    def test_sufficient_trust_succeeds(self):
        node = pre_process_node.InputValidationLanguageDetectNode()
        out = node({"caller_trust_level": TRUST, "user_input": "How do I count inventory?"})
        assert out["status"] == AgentStatus.SUCCESS
        assert out["detected_language"] == "en"
