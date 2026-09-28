# RET-C2-609 — Test Specification

## Test Strategy

Deterministic-core: no LLM required, full suite runs offline. Answer
synthesis accepts an optional `llm` client and falls back to deterministic
citation-based synthesis when absent.

## Unit Tests (`tests/unit/test_nodes.py`)

| Node | Cases |
|---|---|
| InputValidationLanguageDetectNode | success (Japanese detected); success (Vietnamese detected); success (English default); empty user_input→degraded SUCCESS carrying `error_code: EMPTY_INPUT` |
| KnowledgeRetrieveAllergenComplianceNode | success (KB + allergen matches found); success (no matches, empty lists); missing query envelope→degraded SUCCESS carrying `error_code: EMPTY_INPUT` |
| ResponseGenerateNode | success (answer cites KB ref_id); missing query envelope→degraded SUCCESS carrying `error_code: EMPTY_INPUT` |
| AuditLogValidateNode | success (all citations sourced); unsourced compliance reference→answer withheld, SUCCESS + `CITATION_WITHHELD` (non-suppressible hook); the success return carries the answer and its sources, so the re-check reads what it is meant to check; a degraded refusal is not scanned as an answer |

## Integration Tests (`tests/integration/test_graph.py`)

| ID | Test | Expected |
|---|---|---|
| I-1 | Japanese allergen question with KB match | pipeline completes (≥4 nodes); answer cites the allergen rule ref_id |
| I-2 | English general ops question with KB match | pipeline completes; answer cites the KB entry ref_id |
| I-3 | empty query | SUCCESS; `output` is the caller-facing reason for the refusal, no answer |
| I-4 | empty query, knowledge base raises if searched | SUCCESS with the same reason; the knowledge base is never read |

### How each outcome is reported

A request with no question in it is refused as `EMPTY_INPUT`. An answer citing a compliance
reference absent from every retrieved source is withheld under the citation policy and
reported as `CITATION_WITHHELD`; `status=SUCCESS` there means the request was handled
safely, not that an answer was returned.

A security failure (credential-shaped content) and an invariant failure end as
`status=ERROR` and are never represented as a successful completion.

> Per the S-2 gate's effect on the success path, integration tests
> assert pipeline-completion invariants rather than an exact terminal status
> for success cases — unit tests already pin the success-path logic
> deterministically.

## Proof-of-Boundary Tests (`tests/proof_of_boundary/`)

| PB-ID | Boundary | Test | Expected Result |
|-------|----------|------|----------------|
| PB-1 | BaseNode → EventEmitter | `emit_trace_event()` fires on every invocation path | No silent failures |
| PB-2 | State serialization | Post-invoke State is primitives only | No Pydantic/dataclass |
| PB-4 | Import isolation | No Level 0 imports | AST scan: 0 violations |
| PB-5 | Checkpoint safety | No JWT/Pydantic in checkpoint | Inspection pass |
| PB-6 | Invoke execution order | S-1 → node_start → S-2 → execute → S-3 → node_complete | Order verified |

## Business Logic Tests

| TC-ID | Test | Input | Expected Result |
|-------|------|-------|----------------|
| BL-01 | Japanese language detection | query contains hiragana/katakana | detected_language=ja |
| BL-02 | Vietnamese language detection | query contains Vietnamese diacritics | detected_language=vi |
| BL-03 | allergen rule-table match | query mentions a known allergen (えび/shrimp/etc.) | allergen_matches non-empty |
| BL-04 | non-suppressible unsourced-claim block | answer text cites a ref_id not present in retrieved_entries or allergen_matches | `has_unsourced_compliance_claim` returns True |
| BL-05 | no knowledge base configured | neither `kb` nor `allergen_table` given (knowledge node and full graph) | SUCCESS with `KNOWLEDGE_BASE_NOT_CONFIGURED` and its notice; nothing is looked up and no model is asked |

## Non-suppressible output tests (critical)

- `formatted_answer` must never cite a compliance reference absent from
  `retrieved_entries`/`allergen_matches` (unit + I-1/I-2 + BL-04).
- The post_process S-3 hook re-checks `formatted_answer`/`retrieved_entries`/
  `allergen_matches`'s own fields only (S-3 hook self-consistency rule) —
  never cross-references separate state fields read independently.

## Test Execution Summary
- Execution date: 2026-07-08
- Total tests: see CI `run-tests` job output
- Coverage: deterministic-core, no LLM dependency

## 1. Deployment path tests

### TC-DEP-01 Marketplace entry point identity — `tests/unit/test_cli_entry_point.py`

| Case | Expected |
|---|---|
| Identity is concrete | `agent_name` / `namespace` are non-empty and not the runner default |
| Identity matches the HTTP entry point | the values equal what `src/api/server.py` passes to `secrets_factory`; where that entry point provisions no secrets, they equal the manifest `namespace` and the lower-cased template id |
| The runner call uses the constants | `run_agent_marketplace` is called with the module constants, not inline literals |

### TC-DEP-02 Standalone entry point boundary — `tests/proof_of_boundary/test_server_llm_injection.py`

| Case | Expected |
|---|---|
| Boots with no credential provisioned | the module imports and the app/agent objects are constructed |
| External bearer never reaches the internal level | resolves to the verified-external level |
| Staging runner credential reaches the internal level | resolves to the internal level |
| Wrong or missing bearer while auth is enabled | rejected with 401 |
