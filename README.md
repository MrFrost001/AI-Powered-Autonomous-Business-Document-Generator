# AI-Powered-Autonomous-Business-Document-Generator
# 🤖 Autonomous Document Agent

An autonomous FastAPI agent that takes a single natural-language request and,
with **zero follow-up questions**, plans its own task list, executes each
step, self-checks its draft, and produces a polished, ready-to-share
**`.docx`** business document — a proposal, meeting minutes, project plan,
business report, technical design, SOP, or product spec.

Built with **FastAPI**, **LangChain** (`langchain-groq` / `ChatGroq`), and
**python-docx**, with a deterministic fallback pipeline so it always returns
a usable document — even with no API key configured.

---

## Table of Contents

- [Why this project](#why-this-project)
- [How the agent works](#how-the-agent-works)
- [Tech stack](#tech-stack)
- [Project structure](#project-structure)
- [Getting started](#getting-started)
- [Environment variables](#environment-variables)
- [API reference](#api-reference)
- [Fallback mode (no API key needed)](#fallback-mode-no-api-key-needed)
- [Frontend](#frontend)
- [Testing](#testing)
- [Design tradeoffs & limitations](#design-tradeoffs--limitations)
- [Roadmap ideas](#roadmap-ideas)

---

## Why this project

Most "AI agent" demos are a single prompt-in, text-out call. This project is
built around three things a real agent actually needs:

1. **Autonomous planning** — the agent decides *what* to build (document
   type, title, section outline) before generating any content, and turns
   that plan into its own explicit, numbered TODO list.
2. **Resilience** — free-tier LLM APIs rate-limit and occasionally fail.
   Every model call retries with exponential backoff, times out instead of
   hanging, and falls back to deterministic template generation on failure
   — so the API never 500s just because the model provider had a bad
   moment.
3. **Self-checking** — after drafting, the agent runs a reflection pass over
   its own output looking for gaps or inconsistencies before handing back
   the final file.

## How the agent works

```
POST /agent  { "request": "<natural language request>" }
      │
      ▼
 1. Guardrails            validate_request() — length checks, blocked terms
      │
      ▼
 2. Planning              build_plan() — LangChain ChatPromptTemplate +
                           PydanticOutputParser ask an LLM (ChatGroq) to
                           choose: doc_type, title, section outline,
                           assumptions. Falls back to a deterministic
                           keyword classifier if the LLM is unavailable
                           or its response fails schema validation.
      │
      ▼
 3. Task list             build_task_list() — turns the plan into an
                           explicit numbered TaskStep list (the agent's
                           own TODO list)
      │
      ▼
 4. Execution             execute_plan() — generates content for each
                           section via an LLM call (ChatPromptTemplate),
                           or realistic mock content if the LLM is
                           unavailable
      │
      ▼
 5. Self-check            run_self_check() — reflection pass over the
                           drafted sections, flagging gaps/short sections
      │
      ▼
 6. Render                render_docx() — assembles a polished .docx with
                           title page, headings, and formatted sections
      │
      ▼
 Response: plan + task list + assumptions + self-check notes +
           download link for the generated .docx
```

Every stage is designed to **never hard-fail** on a missing or misbehaving
LLM — at worst, the agent quietly switches to its deterministic fallback
path and says so in the response (`generation_mode: "fallback_template"`).

## Tech stack

| Layer              | Choice                                                        |
|--------------------|-----------------------------------------------------------------|
| API framework       | [FastAPI](https://fastapi.tiangolo.com/)                        |
| LLM orchestration   | [LangChain](https://python.langchain.com/) (`langchain-core`, `langchain-groq`) |
| LLM provider        | [Groq](https://console.groq.com/) (free-tier, e.g. `llama-3.3-70b-versatile`) |
| Structured output   | Pydantic v2 + LangChain's `PydanticOutputParser`                 |
| Document generation | [python-docx](https://python-docx.readthedocs.io/)               |
| Frontend            | Static HTML/CSS/JS (no build step), served by FastAPI's `StaticFiles` |

## Project structure

```
project/
├── app/
│   ├── main.py          # FastAPI app & routes: POST /agent, GET /agent/download/{filename}
│   ├── models.py        # Pydantic request/response schemas (AgentRequest, AgentResponse, ...)
│   ├── guardrails.py     # Request validation + ambiguity detection
│   ├── planner.py        # Agent decides doc_type/title/sections (LLM + fallback classifier)
│   ├── executor.py       # Generates content per section (LLM + fallback mock content)
│   ├── docgen.py          # Renders the final .docx with python-docx
│   └── llm_client.py      # LangChain (ChatGroq) wrapper: retry, backoff, JSON mode, fallback
├── frontend/
│   ├── index.html
│   ├── style.css
│   └── script.js
├── requirements.txt
├── test_client.py         # Simple end-to-end smoke test against a running server
├── .env.example
└── README.md
```

## Getting started

```bash
# 1. Install dependencies
pip install -r requirements.txt

# 2. (Optional) configure a free Groq API key — without this, the agent
#    runs fully in deterministic fallback/template mode.
cp .env.example .env
# then edit .env and set GROQ_API_KEY (get one free at https://console.groq.com/keys)

# 3. Run the server
uvicorn app.main:app --reload --port 8000
```

Then open **http://127.0.0.1:8000/** for the frontend, or call the API
directly (see below).

## Environment variables

All configured via `.env` (see `.env.example`):

| Variable            | Default                    | Description                                      |
|---------------------|-----------------------------|---------------------------------------------------|
| `GROQ_API_KEY`       | *(empty)*                   | Your Groq API key. Leave blank to force fallback mode. |
| `GROQ_MODEL`         | `llama-3.3-70b-versatile`   | Groq model name to use.                            |
| `LLM_MAX_RETRIES`    | `3`                          | Max retry attempts per LLM call.                   |
| `LLM_BASE_BACKOFF`   | `1.5`                        | Base seconds for exponential backoff between retries. |
| `LLM_TIMEOUT`        | `20`                         | Per-request timeout, in seconds.                   |

## API reference

### `GET /health`

Basic health check.

```json
{ "status": "ok", "llm_configured": true }
```

### `POST /agent`

Runs the full agent pipeline end-to-end.

**Request**

```json
{ "request": "Create a project plan for launching a bill-split feature in Q3, including timeline, budget and risks." }
```

**Response**

```json
{
  "status": "success",
  "message": "Generated a project plan titled '...' across 8 sections.",
  "doc_type": "project_plan",
  "title": "Q3 Bill-Split Feature Launch Plan",
  "plan": [
    { "id": 1, "name": "validate_request", "description": "...", "status": "done", "detail": null },
    { "id": 2, "name": "classify_document_type", "description": "...", "status": "done", "detail": null }
  ],
  "assumptions": ["..."],
  "self_check": ["..."],
  "generation_mode": "llm",
  "docx_path": "/absolute/path/to/output/....docx",
  "docx_download_url": "/agent/download/....docx"
}
```

- `generation_mode` is `"llm"` when Groq produced the content, or
  `"fallback_template"` when the deterministic fallback was used.
- Invalid/blocked requests return **HTTP 422** with a list of problems.

### `GET /agent/download/{filename}`

Downloads the generated `.docx` file returned by `docx_download_url`.

**Example**

```bash
curl -X POST http://127.0.0.1:8000/agent \
  -H "Content-Type: application/json" \
  -d '{"request": "Write meeting minutes for today'\''s sprint planning call."}'
```

## Fallback mode (no API key needed)

This project is designed to be **fully runnable and demoable with zero cost
or setup**. If `GROQ_API_KEY` is not set, or the LLM call fails after all
retries, or its response doesn't match the expected schema, the agent
transparently falls back to:

- a deterministic **keyword-based classifier** for document type (`planner.py`)
- **realistic mock section content** rather than empty gaps (`executor.py`)

The response always tells you which path was used via `generation_mode`, so
nothing is silently degraded without visibility.

## Frontend

A minimal static frontend (`frontend/`) is served directly by FastAPI at
`/` — enter a request, watch the agent's task list execute, and download the
resulting `.docx`. No build tooling required.

## Testing

`test_client.py` is a lightweight end-to-end smoke test that hits a running
server:

```bash
uvicorn app.main:app --port 8000 &
python test_client.py
```

## Design tradeoffs & limitations

- **One shared `.docx` layout for every document type**, rather than a
  bespoke template per type — kept simple intentionally; see
  `docgen.py`. Easy to extend with per-type templates later.
- **Retry/fallback logic lives in one place** (`llm_client.py`) so
  `planner.py` and `executor.py` never need to know which LLM
  framework or provider is behind `call_llm()` / `call_llm_json()`.
- **Guardrails are intentionally lightweight** (length checks + a small
  blocklist) — enough to keep the demo focused on legitimate business
  documents, not a full content-moderation system.

## Roadmap ideas

- Per-document-type `.docx` templates/styling
- Streaming section-by-section generation to the frontend
- Swap the keyword-based fallback classifier for a small local model
- Support additional LLM providers behind the same LangChain interface
