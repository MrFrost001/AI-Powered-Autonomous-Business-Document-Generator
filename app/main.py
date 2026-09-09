"""
Autonomous Document Agent - FastAPI entrypoint.

POST /agent
    body: {"request": "..."}
    -> agent plans its own task list, executes each step, self-checks the
       draft, renders a .docx, and returns the plan + document metadata.

GET /agent/download/{filename}
    -> download the generated .docx.

Run:
    uvicorn app.main:app --reload --port 8000
"""
from __future__ import annotations

import logging
import os

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from .docgen import OUTPUT_DIR, render_docx
from .executor import execute_plan, run_self_check
from .guardrails import validate_request
from .llm_client import llm_configured
from .models import AgentRequest, AgentResponse
from .planner import build_plan, build_task_list

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("agent.api")

app = FastAPI(
    title="Autonomous Document Agent",
    description="Plans its own tasks, executes them, and produces a polished .docx",
    version="1.0.0",
)


@app.get("/health")
def health():
    return {"status": "ok", "llm_configured": llm_configured()}


@app.post("/agent", response_model=AgentResponse)
def run_agent(payload: AgentRequest):
    request_text = payload.request

    # ---- Step 0: guardrails ----
    is_valid, problems = validate_request(request_text)
    if not is_valid:
        raise HTTPException(status_code=422, detail={"errors": problems})

    # ---- Step 1: agent plans its own task list ----
    plan = build_plan(request_text)
    tasks = build_task_list(plan)
    logger.info("Plan created: doc_type=%s sections=%s", plan.doc_type, plan.sections)

    # ---- Step 2: agent executes each task ----
    section_content, tasks, generation_mode = execute_plan(plan, tasks, request_text)

    # ---- Step 3: reflection / self-check ----
    findings = run_self_check(plan, section_content, tasks)

    # ---- Step 4: render final artifact ----
    docx_path = render_docx(
        title=plan.title,
        doc_type=plan.doc_type,
        sections=plan.sections,
        section_content=section_content,
        assumptions=plan.assumptions,
        generation_mode=generation_mode,
    )
    for task in tasks:
        if task.name == "render_docx":
            task.status = "done"
            task.detail = os.path.basename(docx_path)

    filename = os.path.basename(docx_path)
    return AgentResponse(
        status="success",
        message=(
            f"Generated a {plan.doc_type.replace('_', ' ')} titled '{plan.title}' "
            f"across {len(plan.sections)} sections."
        ),
        doc_type=plan.doc_type,
        title=plan.title,
        plan=tasks,
        assumptions=plan.assumptions,
        self_check=findings,
        generation_mode=generation_mode,
        docx_path=docx_path,
        docx_download_url=f"/agent/download/{filename}",
    )


@app.get("/agent/download/{filename}")
def download(filename: str):
    safe_name = os.path.basename(filename)  # prevent path traversal
    path = os.path.join(OUTPUT_DIR, safe_name)
    if not os.path.isfile(path):
        raise HTTPException(status_code=404, detail="File not found")
    return FileResponse(
        path,
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        filename=safe_name,
    )


# ---------------------------------------------------------------------------
# Serve the frontend (frontend/index.html, style.css, script.js) as static
# files. Mounted last and at "/" so it never shadows the API routes above.
# Visit http://127.0.0.1:8000/ once the server is running.
# ---------------------------------------------------------------------------
FRONTEND_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "frontend")
if os.path.isdir(FRONTEND_DIR):
    app.mount("/", StaticFiles(directory=FRONTEND_DIR, html=True), name="frontend")
