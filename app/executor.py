"""
Execution stage: walks the TaskStep list produced by planner.py and
actually does the work - generating content for each section (via LLM,
or a deterministic mock-data fallback), then running a short reflection
pass to sanity-check the draft before it's handed to the docx renderer.
"""
from __future__ import annotations

from typing import Dict, List, Tuple

from langchain_core.prompts import ChatPromptTemplate

from .llm_client import call_llm
from .models import DocumentPlan, TaskStep

_SECTION_PROMPT = ChatPromptTemplate.from_messages([
    ("system",
     "You are drafting the '{section}' section of a professional {doc_type} "
     "titled '{title}'. Write concise, well-structured business content (3-6 sentences, or a short "
     "bulleted list where a list is more natural, e.g. attendees/action items). Use realistic "
     "mock data where specifics are missing (names, dates, figures) rather than leaving gaps. "
     "Do not repeat the section title. Do not add markdown headers."),
    ("human", "Original user request:\n\"\"\"\n{request_text}\n\"\"\"\n\nWrite the '{section}' section now."),
])

MOCK_FILLERS = {
    "Executive Summary": (
        "This document summarizes the proposed initiative, its rationale, and the "
        "expected business impact. (Auto-generated placeholder content - fallback mode.)"
    ),
    "Attendees": "- Utkarsh Maurya (Lead)\n- Project Stakeholder\n- Engineering Representative\n- QA Representative",
    "Action Items": "- Owner: TBD | Task: Finalize requirements | Due: within 1 week\n- Owner: TBD | Task: Confirm budget | Due: within 1 week",
}

GENERIC_FALLBACK = (
    "[Fallback mode - LLM unavailable] Mock content for the '{section}' section of this "
    "{doc_type} (request: \"{request_snippet}\"). This placeholder uses standard business-"
    "document conventions for this section and should be replaced with real details before "
    "external distribution."
)


def _generate_section_content(doc_type: str, title: str, section: str, request_text: str) -> Tuple[str, str]:
    """Returns (content, mode) where mode is 'llm' or 'fallback_template'."""
    messages = _SECTION_PROMPT.format_messages(
        section=section, doc_type=doc_type.replace("_", " "), title=title, request_text=request_text,
    )
    system_prompt, user_prompt = messages[0].content, messages[1].content

    content = call_llm(system_prompt, user_prompt)
    if content:
        return content.strip(), "llm"

    if section in MOCK_FILLERS:
        return MOCK_FILLERS[section], "fallback_template"

    snippet = request_text.strip().rstrip(".")
    if len(snippet) > 60:
        snippet = snippet[:57] + "..."
    fallback = GENERIC_FALLBACK.format(doc_type=doc_type.replace("_", " "), section=section, request_snippet=snippet)
    return fallback, "fallback_template"


def execute_plan(plan: DocumentPlan, tasks: List[TaskStep], request_text: str) -> Tuple[Dict[str, str], List[TaskStep], str]:
    """
    Executes each generate_section:* task in the plan.
    Returns (section_content_map, updated_tasks, overall_generation_mode).
    overall_generation_mode is 'llm' if ANY section used the live model,
    else 'fallback_template'.
    """
    section_content: Dict[str, str] = {}
    used_llm_any = False

    for task in tasks:
        if not task.name.startswith("generate_section:"):
            continue
        section = task.name.split(":", 1)[1]
        task.status = "running"
        content, mode = _generate_section_content(plan.doc_type, plan.title, section, request_text)
        section_content[section] = content
        task.status = "done"
        task.detail = f"generated via {mode} ({len(content)} chars)"
        used_llm_any = used_llm_any or (mode == "llm")

    # mark the earlier bookkeeping tasks done too, now that we've gotten this far
    for task in tasks:
        if task.name in ("validate_request", "classify_document_type", "resolve_assumptions", "plan_sections"):
            task.status = "done"
            if task.name == "classify_document_type":
                task.detail = f"doc_type={plan.doc_type}"
            elif task.name == "resolve_assumptions":
                task.detail = f"{len(plan.assumptions)} assumption(s) recorded"
            elif task.name == "plan_sections":
                task.detail = f"{len(plan.sections)} section(s) planned"

    overall_mode = "llm" if used_llm_any else "fallback_template"
    return section_content, tasks, overall_mode


def run_self_check(plan: DocumentPlan, section_content: Dict[str, str], tasks: List[TaskStep]) -> List[str]:
    """
    Reflection / lightweight self-check pass over the drafted content.
    Flags empty sections, suspiciously short sections, or duplicated content,
    and records the outcome as the task's detail. This runs regardless of
    whether the LLM or fallback path produced the content.
    """
    findings: List[str] = []
    seen_content = set()

    for section in plan.sections:
        content = section_content.get(section, "")
        if not content.strip():
            findings.append(f"'{section}' was empty - inserted a placeholder note.")
            section_content[section] = "[Content pending - not generated.]"
            continue
        if len(content.strip()) < 15:
            findings.append(f"'{section}' looked unusually short ({len(content.strip())} chars).")
        norm = content.strip().lower()
        if norm in seen_content:
            findings.append(f"'{section}' duplicated another section's content - flagged for review.")
        seen_content.add(norm)

    if not findings:
        findings.append("All sections present, non-empty, and distinct. No issues found.")

    for task in tasks:
        if task.name == "self_check":
            task.status = "done"
            task.detail = "; ".join(findings)[:200]

    return findings
