"""Pydantic models shared across the agent."""
from __future__ import annotations

from typing import List, Optional
from pydantic import BaseModel, Field, field_validator


class AgentRequest(BaseModel):
    request: str = Field(..., min_length=3, max_length=4000)

    @field_validator("request")
    @classmethod
    def not_blank(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("request must not be blank/whitespace-only")
        return v.strip()


class TaskStep(BaseModel):
    """A single step in the agent's self-generated TODO list."""
    id: int
    name: str
    description: str
    status: str = "pending"  # pending -> running -> done / failed
    detail: Optional[str] = None  # short note filled in once executed


class DocumentPlan(BaseModel):
    """The plan the agent produces before writing any content."""
    doc_type: str
    title: str
    sections: List[str]
    assumptions: List[str] = []
    reasoning: str = ""


class AgentResponse(BaseModel):
    status: str
    message: str
    doc_type: str
    title: str
    plan: List[TaskStep]
    assumptions: List[str]
    self_check: List[str]
    generation_mode: str  # "llm" or "fallback_template"
    docx_path: str
    docx_download_url: str
