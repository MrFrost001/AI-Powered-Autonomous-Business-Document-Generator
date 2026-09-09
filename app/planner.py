"""
Planning stage: the agent decides WHAT to build before building anything.

Two paths:
  - LLM path: ask the model to classify the request and propose a document
    plan (doc_type, title, sections, assumptions) as JSON.
  - Fallback path: deterministic keyword-based classifier + section
    templates. Used automatically whenever the LLM is unavailable
    (see llm_client.py) so planning never fails.

Either way, the output is turned into an explicit, numbered TaskStep list
(the agent's own TODO list) that the executor will run through one by one.
This is the "multi-step planning" backbone of the whole system.
"""
from __future__ import annotations

import logging
from typing import List, Literal

from langchain_core.output_parsers import PydanticOutputParser
from langchain_core.prompts import ChatPromptTemplate
from pydantic import BaseModel, Field, ValidationError

from .llm_client import call_llm_json
from .models import DocumentPlan, TaskStep
from .guardrails import detect_ambiguity

logger = logging.getLogger("agent.planner")

# ---------------------------------------------------------------------------
# LangChain structured output: the schema the LLM must return, plus a
# PydanticOutputParser that (a) generates the format instructions we inject
# into the prompt and (b) validates the response before it's trusted, instead
# of the old hand-rolled `.get(...)` / `str(...)` dict massaging.
# ---------------------------------------------------------------------------
_DocType = Literal[
    "proposal", "meeting_minutes", "project_plan", "business_report",
    "technical_design", "sop", "product_spec",
]


class _PlanLLMOutput(BaseModel):
    doc_type: _DocType = Field(..., description="Best-fit document type for this request.")
    title: str = Field(..., min_length=1, description="Concise, professional document title.")
    sections: List[str] = Field(..., min_length=1, max_length=9, description="Ordered section headings.")
    assumptions: List[str] = Field(default_factory=list, description="Assumptions made about missing/ambiguous info.")
    reasoning: str = Field(default="", description="1-2 sentence explanation of the doc_type choice.")


_plan_parser = PydanticOutputParser(pydantic_object=_PlanLLMOutput)

_PLAN_PROMPT = ChatPromptTemplate.from_messages([
    ("system",
     "You are the planning module of an autonomous business-document agent. "
     "Given a user's natural-language request, decide the single best document "
     "type, a concise professional title, and an ordered list of 5-9 section "
     "headings that a polished Word document of that type should contain. If "
     "the request is vague, missing information, or ambiguous, make "
     "reasonable, clearly-stated business assumptions instead of asking a "
     "follow-up question - the agent must run autonomously end-to-end.\n\n"
     "{format_instructions}"),
    ("human", "User request:\n\"\"\"\n{request_text}\n\"\"\""),
])

SECTION_TEMPLATES = {
    "proposal": [
        "Executive Summary", "Background & Problem Statement", "Proposed Solution",
        "Scope of Work", "Timeline & Milestones", "Budget & Resources", "Risks & Mitigations",
        "Next Steps",
    ],
    "meeting_minutes": [
        "Meeting Details", "Attendees", "Agenda", "Discussion Summary",
        "Decisions Made", "Action Items", "Next Meeting",
    ],
    "project_plan": [
        "Project Overview", "Objectives", "Scope", "Milestones & Timeline",
        "Team & Responsibilities", "Budget", "Risk Management", "Success Metrics",
    ],
    "business_report": [
        "Executive Summary", "Introduction", "Key Findings", "Data & Analysis",
        "Recommendations", "Conclusion",
    ],
    "technical_design": [
        "Overview", "Goals & Non-Goals", "System Architecture", "Data Model",
        "API Design", "Security Considerations", "Rollout Plan", "Open Questions",
    ],
    "sop": [
        "Purpose", "Scope", "Roles & Responsibilities", "Procedure Steps",
        "Exceptions & Escalation", "Revision History",
    ],
    "product_spec": [
        "Overview", "Problem Statement", "Target Users", "Requirements",
        "User Stories", "Success Metrics", "Out of Scope",
    ],
}

KEYWORD_MAP = {
    "meeting_minutes": ["meeting minutes", "minutes of meeting", "attendees", "agenda"],
    "project_plan": ["project plan", "launch plan", "roadmap", "sprint plan", "release plan"],
    "technical_design": ["technical design", "architecture", "system design", "api design"],
    "sop": ["sop", "standard operating procedure", "procedure", "playbook"],
    "product_spec": ["product spec", "prd", "product requirement", "feature spec"],
    "business_report": ["report", "quarterly", "analysis", "findings"],
    "proposal": ["proposal", "pitch", "rfp", "quote"],
}

DEFAULT_DOC_TYPE = "business_report"


def _classify_fallback(request_text: str) -> str:
    lowered = request_text.lower()
    for doc_type, keywords in KEYWORD_MAP.items():
        if any(k in lowered for k in keywords):
            return doc_type
    # Ambiguous / generic request -> agent decides on the most broadly useful format
    return DEFAULT_DOC_TYPE


def _title_fallback(request_text: str, doc_type: str) -> str:
    label = doc_type.replace("_", " ").title()
    snippet = request_text.strip().rstrip(".")
    if len(snippet) > 70:
        snippet = snippet[:67] + "..."
    return f"{label}: {snippet}"


def build_plan(request_text: str) -> DocumentPlan:
    ambiguity_signals = detect_ambiguity(request_text)

    messages = _PLAN_PROMPT.format_messages(
        request_text=request_text,
        format_instructions=_plan_parser.get_format_instructions(),
    )
    system_prompt, user_prompt = messages[0].content, messages[1].content

    raw = call_llm_json(system_prompt, user_prompt)
    parsed: _PlanLLMOutput | None = None
    if raw and isinstance(raw, dict):
        try:
            parsed = _PlanLLMOutput.model_validate(raw)
        except ValidationError as exc:
            logger.warning("LLM plan failed schema validation, falling back: %s", exc)

    if parsed is not None:
        doc_type = parsed.doc_type if parsed.doc_type in SECTION_TEMPLATES else DEFAULT_DOC_TYPE
        sections = [str(s) for s in parsed.sections][:9] or SECTION_TEMPLATES[doc_type]
        title = parsed.title or _title_fallback(request_text, doc_type)
        assumptions = list(parsed.assumptions)
        if ambiguity_signals and not assumptions:
            assumptions = ambiguity_signals
        return DocumentPlan(
            doc_type=doc_type, title=title, sections=sections,
            assumptions=assumptions,
            reasoning=parsed.reasoning or "Classified via LangChain-structured LLM planning call.",
        )

    # ---- Fallback path (no LLM / LLM failed / bad JSON) ----
    doc_type = _classify_fallback(request_text)
    sections = SECTION_TEMPLATES[doc_type]
    title = _title_fallback(request_text, doc_type)
    assumptions = list(ambiguity_signals)
    if doc_type == DEFAULT_DOC_TYPE and not any("business report" in s.lower() for s in KEYWORD_MAP):
        pass
    if not assumptions and _classify_fallback(request_text) == DEFAULT_DOC_TYPE:
        assumptions.append(
            "No explicit document type was named, so the agent defaulted to a general business report format."
        )
    reasoning = (
        "LLM unavailable - used deterministic keyword classifier as fallback "
        f"and matched doc_type='{doc_type}'."
    )
    return DocumentPlan(doc_type=doc_type, title=title, sections=sections,
                         assumptions=assumptions, reasoning=reasoning)


def build_task_list(plan: DocumentPlan) -> List[TaskStep]:
    """Turn the document plan into the agent's own explicit numbered TODO list."""
    steps: List[TaskStep] = [
        TaskStep(id=1, name="validate_request", description="Validate and sanitize the incoming request."),
        TaskStep(id=2, name="classify_document_type",
                 description=f"Determine the target document type (decided: {plan.doc_type})."),
        TaskStep(id=3, name="resolve_assumptions",
                 description="Identify missing/ambiguous information and record explicit assumptions."),
        TaskStep(id=4, name="plan_sections",
                 description=f"Define the section outline ({len(plan.sections)} sections)."),
    ]
    next_id = 5
    for section in plan.sections:
        steps.append(TaskStep(
            id=next_id, name=f"generate_section:{section}",
            description=f"Generate content for section '{section}'.",
        ))
        next_id += 1
    steps.append(TaskStep(id=next_id, name="self_check",
                           description="Run a reflection pass over the drafted content for gaps/contradictions."))
    next_id += 1
    steps.append(TaskStep(id=next_id, name="render_docx",
                           description="Assemble the final polished Word (.docx) document."))
    return steps
