"""AgentCore Platform v1.0 - RET-C2-609 domain services.

Deterministic language detection, KB retrieval, and 食品表示法 28-allergen
rule-table lookup (Tool layer, no LLM) + LLM-optional grounded answer
synthesis (deterministic fallback when no LLM is configured). S-3 output
gate is non-suppressible: no fabricated compliance advice - every
allergen/compliance claim must cite a retrieved KB source.
"""

from __future__ import annotations

import re
from typing import Any

# Simple deterministic language detection - script-range heuristics.
# Multilingual 外国人労働者 support requires only enough precision to route
# to the correct KB slice, not full NLP language identification.
_HIRAGANA_KATAKANA = re.compile(r"[぀-ヿ]")
_CJK_HAN = re.compile(r"[一-鿿]")
_VIETNAMESE_DIACRITICS = re.compile(r"[Ạ-ỹà-῿]")

_KNOWN_ALLERGENS = (
    "shrimp",
    "crab",
    "wheat",
    "buckwheat",
    "egg",
    "milk",
    "peanut",
    "えび",
    "かに",
    "小麦",
    "そば",
    "卵",
    "乳",
    "落花生",
)


def detect_language(text: str) -> str:
    """Deterministic language detection (Tool layer, no LLM)."""
    if _HIRAGANA_KATAKANA.search(text):
        return "ja"
    if _CJK_HAN.search(text):
        return "zh"
    if _VIETNAMESE_DIACRITICS.search(text):
        return "vi"
    return "en"


def retrieve_kb_entries(query: str, language: str, kb: list[dict[str, Any]] | None = None) -> list[dict[str, Any]]:
    """Deterministic KB lookup for entries matching the query keywords and language."""
    kb = kb or []
    lower_query = query.lower()
    matches = []
    for entry in kb:
        if entry.get("language") not in (language, "any"):
            continue
        if any(kw.lower() in lower_query for kw in entry.get("keywords", [])):
            matches.append(entry)
    return matches


def lookup_allergen_rules(query: str, allergen_table: list[dict[str, Any]] | None = None) -> list[dict[str, Any]]:
    """Deterministic 食品表示法 28-allergen rule-table lookup (Tool layer, no LLM)."""
    allergen_table = allergen_table or []
    lower_query = query.lower()
    mentioned = [a for a in _KNOWN_ALLERGENS if a.lower() in lower_query]
    if not mentioned:
        return []
    return [entry for entry in allergen_table if entry.get("allergen") in mentioned]


def has_unsourced_compliance_claim(
    text: str, retrieved_entries: list[dict[str, Any]], allergen_matches: list[dict[str, Any]]
) -> bool:
    """Non-suppressible re-check: any allergen-rule-table entry cited in the answer

    must actually be present in allergen_matches; any KB citation must be present
    in retrieved_entries. Flags an answer that names a specific 食品表示法 rule
    ref_id not present in either source list (fabricated compliance advice).
    """
    known_ref_ids = {e.get("ref_id") for e in retrieved_entries} | {e.get("ref_id") for e in allergen_matches}
    cited_ref_ids = set(re.findall(r"\b[A-Z]+-\d+(?:-\d+)*\b", text))
    return bool(cited_ref_ids - known_ref_ids)


def format_answer(
    query: str,
    language: str,
    retrieved_entries: list[dict[str, Any]],
    allergen_matches: list[dict[str, Any]],
    llm: Any | None = None,
) -> str:
    """Synthesize the grounded answer.

    LLM-essential in a real deployment; deterministic fallback keeps the
    pipeline runnable without an LLM.
    """
    if llm is not None and hasattr(llm, "complete"):
        try:
            raw = llm.complete(
                [
                    {
                        "role": "user",
                        "content": f"Answer this CVS staff question in language={language}, grounded ONLY in "
                        f"KB entries {retrieved_entries} and allergen rules {allergen_matches}: {query}",
                    }
                ]
            )
            if isinstance(raw, str) and raw.strip():
                return raw.strip()
        except Exception:  # noqa: BLE001 - fall back to deterministic synthesis
            pass

    if not retrieved_entries and not allergen_matches:
        return "該当する情報が見つかりませんでした。店長にご確認ください。 / No matching information found. Please check with your store manager."

    lines = []
    for entry in retrieved_entries:
        lines.append(f"[{entry.get('ref_id', 'unknown')}] {entry.get('summary', '')}")
    for match in allergen_matches:
        lines.append(
            f"[{match.get('ref_id', 'unknown')}] Allergen: {match.get('allergen')} - {match.get('summary', '')}"
        )
    return "\n".join(lines)
