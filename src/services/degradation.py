"""Caller-facing wording for runs that end without an answer.

Each outcome here is reported by completing the run with an allow-listed ``error_code``
and a fixed sentence derived from that code alone. No request value is ever
interpolated, so a notice can never echo caller content back. On such a run
``status=SUCCESS`` means the agent finished handling the request safely; it does not
mean an answer was returned.

Caller-correctable: EMPTY_INPUT, a request with no question in it. The sentence names
what to send instead.

Not configured: KNOWLEDGE_BASE_NOT_CONFIGURED — neither a knowledge base nor an allergen
table was given to this deployment, so nothing was looked up. The run completes and says
so rather than reporting that nothing matched.

Policy withholding: CITATION_WITHHELD. An answer citing a compliance reference that is
in none of the retrieved sources is withheld under this agent's citation policy; nothing
assembled for it is returned.

Not reported here, and ending as ``status=ERROR`` instead: credential-shaped content,
which fails closed with no output and no status conversion; an internally inconsistent
run (state a preceding step guarantees is absent), which is a defect; and a failed call
to a required external dependency. None of these is ever represented as a successful
completion.
"""

from __future__ import annotations

EMPTY_INPUT = "EMPTY_INPUT"
CITATION_WITHHELD = "CITATION_WITHHELD"
KNOWLEDGE_BASE_NOT_CONFIGURED = "KNOWLEDGE_BASE_NOT_CONFIGURED"

_MESSAGES: dict[str, str] = {
    EMPTY_INPUT: (
        "No question was received. Describe the store-operations question to answer — "
        "the procedure, product handling or food-labelling rule you need guidance on."
    ),
    CITATION_WITHHELD: (
        "An answer was assembled but not returned, because part of it could not be "
        "traced to the store-operations sources this agent answers from. Ask about one "
        "procedure or product at a time and send it again."
    ),
}

_MESSAGES[KNOWLEDGE_BASE_NOT_CONFIGURED] = (
    "No knowledge base is configured for this deployment, so nothing was looked up and no "
    "answer was produced. Contact whoever operates this deployment."
)

_FALLBACK = "The request could not be accepted and no answer was produced."


def explain_degradation(code: str) -> str:
    """Return one caller-facing sentence for a degradation code."""
    return _MESSAGES.get(code, f"{_FALLBACK} [{code}]" if code else _FALLBACK)
