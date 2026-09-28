# Template Design Specification

## Position in AgentCore Architecture

- **Agent Class**: `RETCVSStoreOpsFAQAgent`
- **L1 Base**: AgentBaseGraph
- **Three-Layer Separation**:
  - State: flat TypedDict composition (no Pydantic — msgpack incompatible)
  - Node: L1 inheritance (Template Method: `execute(self, state: dict) -> dict` override only)
  - Graph: composition (`register_nodes()` for node substitution)

## Architecture Overview

Cat 2: outer `AgentBaseGraph` (fixed 5-node backbone) + `GraphNode` in the
`main` slot wrapping an inner `BaseGraph` (2-step linear domain workflow).

### Node Configuration (outer)

| Node | Responsibility | Input State | Output State | Inherits/Overrides |
|------|---------------|-------------|--------------|-------------------|
| initialize | schema_version/session_id/trust_level | - | - | InitializeNode (default) |
| pre_process | `InputValidationLanguageDetectNode` — S-1/S-2 gate + multilingual routing (JA/EN/ZH/VI) | `user_input` | `detected_language` | FunctionNode |
| main | `CVSStoreOpsFAQGraphNode` — wraps inner workflow | `user_input`, `detected_language` | `retrieved_entries`, `allergen_matches`, `formatted_answer` | GraphNode |
| post_process | `AuditLogValidateNode` — S-4 audit + non-suppressible unsourced-claim re-check | `formatted_answer`, `retrieved_entries`, `allergen_matches` | (validated) | FunctionNode |
| finalize | response_metadata, total_time_ms | - | - | FinalizeNode (default) |

### Node Configuration (inner, per the locked node flow)

| Node | Responsibility |
|------|-----------------|
| `KnowledgeRetrieveAllergenComplianceNode` | Deterministic KB retrieval (store ops procedures) + 食品表示法 28-allergen rule-table lookup; no LLM |
| `ResponseGenerateNode` | LLM-optional grounded answer synthesis (deterministic fallback when no LLM is configured); every compliance claim must cite a retrieved source |

### Data Flow

```
START → initialize → pre_process → main → {route} → post_process → finalize → END
                                            ↓ (retry)
                                          pre_process
```

Inner (wrapped by `main`):
```
START → knowledge_retrieve_allergen_compliance → response_generate → END
```

### State Definition

| Field | Type | Purpose | Required |
|-------|------|---------|----------|
| `detected_language` | str | `ja`\|`en`\|`zh`\|`vi` — routes to language-appropriate KB slice | Yes |
| `retrieved_entries` | str (JSON list[dict]) | matched store-ops KB entries, each version-stamped | Yes |
| `allergen_matches` | str (JSON list[dict]) | matched 食品表示法 allergen rule-table entries | Yes |
| `formatted_answer` | str | final grounded answer citing KB sources | Yes |

**State Constraints (mandatory):**
- Flat TypedDict only (primitives + JSON-serializable types)
- No JWT, API keys, credentials in State (checkpoint DB leakage)
- InvocationContext via `config["configurable"]` only (not in State)
- No Pydantic models, dataclass, arbitrary Python objects (msgpack incompatible)

## Framework Utilization

### Shared Components Used
- [x] InvocationContext (correlation_id, session_id, permissions, credential handle)
- [x] SecurityViolationError
- [x] S-1: `required_trust_level = VERIFIED_EXTERNAL` on every node, the outer
      main-slot `CVSStoreOpsFAQGraphNode` included — left undeclared it inherits
      `ANONYMOUS`, and `gate-trust-level-check` does not scan `GraphNode` subclasses.
      **Correction:** the original draft specified `AUTHENTICATED`, which is
      not a valid `TrustLevel` enum member (only `ANONYMOUS` /
      `VERIFIED_EXTERNAL` / `INTERNAL` exist); `VERIFIED_EXTERNAL` is the
      nearest valid value (authenticated staff, not anonymous public access).
- [x] S-2: `InputValidationLanguageDetectNode` validates the request and detects
      its language. A request with no question in it is refused as a degraded run:
      the node returns SUCCESS with `error_code: EMPTY_INPUT` and no answer, and the
      routing short-circuits the knowledge-base retrieval. The run completes and tells
      the caller what to send instead. An answer failing the citation check below is
      withheld as a policy outcome (`error_code: CITATION_WITHHELD`).
- [x] S-3: `_extra_security_gate_output()` — non-suppressible re-check on
      `AuditLogValidateNode` that the answer cites no compliance reference
      absent from any retrieved KB/allergen source (no fabricated
      compliance advice). Own-dict field re-check only, per the S-3 hook
      self-consistency rule — so the node's success return carries the answer and its
      source lists, without which the re-check scans an empty answer against no sources
      and passes on every run.
- [x] S-4: `emit_trace_event()` — domain events (`ret_cvs_faq_workflow_dispatched`,
      `cvs_faq_compliance_query_answered`, `ret_cvs_faq_workflow_completed`,
      `audit_log_validate_s3_recheck_blocked`) inside each `execute()`. The
      compliance-query audit event logs language + KB-source count only
      (no raw PII), per APPI 2026 staff-query audit requirements.

> **S-2/S-3 gate behaviour by node type (ADR-017):**
> - `FunctionNode` subclass → framework `@final` gate always runs automatically;
>   extend via `_extra_security_gate_input()` / `_extra_security_gate_output()` only
> - `GraphNode` / `RemoteAgentNode` → deliberate no-op (upstream or remote node's gate already applied)

### Composition Pattern

- **Pattern**: GraphNode (subgraph) — `CVSStoreOpsFAQGraphNode` wraps
  `CVSStoreOpsFAQWorkflowGraph`.
- **Composition target**: inner `BaseGraph` (2-node linear domain workflow).
- **Error propagation strategy**: `propagate` (fail fast — re-raise inner
  errors as `SubgraphError`, default). No HITL in this template.

## Outcome classification

Each way a run can end without an answer falls into one class, and the class decides how it
is reported.

| Class | In this agent | Reported as |
|---|---|---|
| Security failure | Credential-shaped content detected by the baseline S-3 gate | `status=ERROR`, `output=None` |
| Policy withholding | An answer citing a compliance reference absent from every retrieved source | `status=SUCCESS`, `error_code=CITATION_WITHHELD`, fixed notice, no answer body |
| Caller-correctable | A request with no question in it | `status=SUCCESS`, `error_code=EMPTY_INPUT` |
| Not configured | Neither `kb` nor `allergen_table` was given to this deployment | `status=SUCCESS`, `error_code=KNOWLEDGE_BASE_NOT_CONFIGURED`; nothing is looked up |
| Optional dependency unavailable | The model is unreachable — the answer is composed from the same retrieved sources without it | `status=SUCCESS` with the deterministic answer; the citation check applies either way |
| Invariant failure | A query envelope or retrieved sources a preceding step guarantees are absent | `status=ERROR`; never represented as successful completion |
| No result | No knowledge-base entry matches a valid question | `status=SUCCESS` with a not-found answer |

Credential-shaped content detected by baseline S-3 causes fail-closed termination:
`status=ERROR`, `output=None`. The template does not transform this terminal status to SUCCESS
and does not emit any source-derived response.

On a policy-withholding or caller-correctable run, `status=SUCCESS` means the agent finished
handling the request safely; it does not mean an answer was returned. The notice is derived from
the `error_code` alone, so nothing from the request is echoed back.

## Import Isolation Confirmation
- [x] Template does not import agenticstar-platform SDK (Level 0)
- [x] Import targets: framework/ and shared/ only (no agents/base/ required)

## Design Decision Record

| Decision | Option A | Option B | Chosen | Rationale |
|----------|----------|----------|--------|-----------|
| L1 base type | AgentBaseGraph | AutonomousBaseGraph | AgentBaseGraph | Cat 2 fixed multi-step workflow, no autonomous loop needed |
| Composition pattern | Standalone nodes | GraphNode (subgraph) | GraphNode | Domain complexity (dual KB retrieval + grounded synthesis) is encapsulated inside the inner workflow per the locked node flow |
| Allergen rule-table lookup | LLM-based | Deterministic (Tool, rule table) | Deterministic | Per the KB suitability note: the 28-allergen list is a stable regulatory table (消費者庁, fixed Oct 2026 effective date) — a rule-table lookup, not LLM inference, keeps the audit trail traceable to the exact published table |
| S-1 trust level | AUTHENTICATED (issue spec, invalid) | VERIFIED_EXTERNAL | VERIFIED_EXTERNAL | `AUTHENTICATED` is not a valid `TrustLevel` enum member; `VERIFIED_EXTERNAL` is the nearest valid value |
| Node flow mapping | 6 separate nodes matching the original draft exactly | Combine InputValidation+LanguageDetect (pre_process); KnowledgeRetrieve+AllergenCompliance (inner) | Combined pairs | Each combined pair operates on the same input with no branching/retry boundary between them |
| Extract_input envelope | Forward user_input only | Forward a combined `{query, language}` JSON envelope | Combined envelope | `detected_language` is an independent outer-classified field, not re-derivable from the query alone — per the multi-field envelope pattern |

## 1. Deployment entry points

The agent is reachable through two entry points, and both resolve their runtime inputs the same way.

| Entry point | File | Used by |
|---|---|---|
| Standalone HTTP | `src/api/server.py` | staging rehearsal, direct invocation |
| Marketplace one-shot Pod | `cli.py` | the platform runner (container `CMD`) |

Both read runtime parameters from `config/config.yaml` — the manifest carries discovery metadata
only — and both scope secrets to the same location (`namespace=ret`, `agent_name=ret-c2-609`), so a
secret provisioned for one path resolves identically on the other.

**Deployment-provided LLM client.** The three Azure OpenAI connection values
(`AZURE_OPENAI_API_KEY`, `AZURE_OPENAI_ENDPOINT` — the bare resource endpoint — and
`AZURE_OPENAI_DEPLOYMENT`) are resolved through the agent's own secret provider, never from the
process environment. The standalone entry point passes a client as `config["llm"]` only when the
provider client is available and all three values already resolve at startup; otherwise the key
stays unset and the graph runs its deterministic path. The Marketplace entry point cannot resolve
the values while the graph is built, so whenever the provider client is available it passes a
client that resolves them on each call. A value missing at that point makes the call fail, and the
model being optional here, the answer is composed from the retrieved sources without it; the
failure is recorded in the audit event. The manifest declares the three secrets and the provider
extra.

**Progress events.** Each pipeline stage emits a non-terminal progress event at its start, so a
caller sees the run advancing. Outside the Marketplace runtime the emitter resolves to a no-op, so
the same code is safe on every path. Terminal events belong to the platform runner and are never
emitted by this agent.

**Caller authentication at the standalone entry point.** A caller that no upstream middleware
vouched for stays anonymous unless it presents a deployment-level credential: the external bearer
token grants the verified-external level, and a separate staging-only runner credential is the only
way to reach the internal level. Trust established upstream is never changed.
