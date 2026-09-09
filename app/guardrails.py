"""
Lightweight guardrails applied before any planning/generation happens.

Not the mandatory "real engineering improvement" for this build (that's
retry & fallback in llm_client.py), but basic validation is still good
practice and feeds the agent's plan/assumptions.
"""
from __future__ import annotations

from typing import List, Tuple

MIN_LEN = 3
MAX_LEN = 4000

BLOCKED_TERMS = [
    # keeps the demo focused on legitimate business-document generation
    "malware", "ransomware", "exploit code", "bomb making", "weaponize",
]


def validate_request(text: str) -> Tuple[bool, List[str]]:
    """Returns (is_valid, list_of_problems)."""
    problems: List[str] = []
    stripped = text.strip()

    if len(stripped) < MIN_LEN:
        problems.append("Request is too short to determine intent.")
    if len(stripped) > MAX_LEN:
        problems.append("Request exceeds maximum allowed length.")

    lowered = stripped.lower()
    for term in BLOCKED_TERMS:
        if term in lowered:
            problems.append(f"Request appears to ask for disallowed content ('{term}').")

    return (len(problems) == 0, problems)


def detect_ambiguity(text: str) -> List[str]:
    """
    Heuristic ambiguity detector. Looks for signals that the request is
    vague / under-specified so the planner knows it will need to make and
    clearly label assumptions rather than silently guessing.
    """
    signals = []
    lowered = text.lower()

    vague_phrases = [
        "some kind of", "not sure", "whatever you think", "up to you",
        "everything important", "you decide", "not sure what",
        "something for", "anything that works",
    ]
    if any(p in lowered for p in vague_phrases):
        signals.append("Request uses vague language and does not specify an exact document type.")

    if len(text.split()) < 12:
        signals.append("Request is very short; many details will need to be assumed.")

    if "?" in text and len(text.split()) < 25:
        signals.append("Request is phrased as an open question rather than a concrete instruction.")

    return signals
