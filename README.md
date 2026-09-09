<<<<<<< HEAD
# Autonomous Document Agent

A small FastAPI service that takes a natural-language request, **plans its own
task list**, executes each step, self-checks the draft, and produces a
polished `.docx` (proposal, meeting minutes, project plan, business report,
technical design, SOP, or product spec).

**LLM layer:** all model calls go through [LangChain](https://python.langchain.com/)
(`langchain-core` + `langchain-groq`'s `ChatGroq`) instead of the raw `groq`
SDK, with the retry/backoff/fallback contract preserved in `app/llm_client.py`.
On top of that, `planner.py` and `executor.py` were upgraded to use
LangChain's own prompt/parsing tools rather than hand-built f-strings:
- `planner.py` builds its prompt with a `ChatPromptTemplate` and validates the
  model's JSON with a `PydanticOutputParser` (schema: doc type, title,
  sections, assumptions, reasoning). A malformed or off-schema LLM response
  is now caught by Pydantic *before* it reaches the rest of the pipeline and
  cleanly degrades to the keyword-classifier fallback, instead of being
  silently patched up with `.get(...)`/`str(...)` calls.
- `executor.py` builds its per-section prompt with a `ChatPromptTemplate`
  instead of manual string formatting.

Everything else - guardrails, the fallback templates, `docgen.py`'s Word
rendering, `models.py`'s API schemas, and `main.py`'s routes - is unchanged.

## Quick start

```bash
pip install -r requirements.txt

# optional - without this, the agent runs fully in fallback/template mode
cp .env.example .env
# then set GROQ_API_KEY in .env (free key: https://console.groq.com/keys)

uvicorn app.main:app --reload --port 8000
```

In another terminal:

```bash
python test_client.py
```

or directly:
=======
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
 2. Planning               build_plan() — LangChain ChatPromptTemplate +
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
>>>>>>> ad06b46389998f5618941de30ebeea80634e722f

```bash
curl -X POST http://127.0.0.1:8000/agent \
  -H "Content-Type: application/json" \
<<<<<<< HEAD
  -d '{"request": "Create a project plan for launching a new mobile banking bill-split feature in Q3, including timeline, budget and risks."}'
```

The response includes the agent's task list, its assumptions, its self-check
findings, and a `docx_download_url` to fetch the generated Word file from
`GET /agent/download/{filename}`.

**Note:** this sandbox could not reach `api.groq.com` (network egress here is
allow-listed to a fixed set of domains), so it was built and demoed in
fallback mode. It runs identically against the real Groq API once
`GROQ_API_KEY` is set on a machine with normal internet access — same code
path, just `generation_mode: "llm"` instead of `"fallback_template"`.

## Architecture

```
POST /agent
    │
    ▼
guardrails.validate_request()        -- length/blank/blocklist checks
    │
    ▼
planner.build_plan()                 -- LLM call (JSON mode) -> doc_type,
    │                                    title, sections, assumptions
    │                                    falls back to a keyword classifier
    │                                    + section templates if the LLM
    │                                    is unavailable
    ▼
planner.build_task_list()            -- turns the plan into an explicit,
    │                                    numbered TaskStep list (the agent's
    │                                    own TODO list)
    ▼
executor.execute_plan()              -- runs each generate_section:* task,
    │                                    one LLM call per section (with the
    │                                    same retry/fallback machinery)
    ▼
executor.run_self_check()            -- reflection pass: flags empty,
    │                                    too-short, or duplicated sections
    ▼
docgen.render_docx()                 -- python-docx assembly: title page,
    │                                    assumptions callout, section
    │                                    headings, bullet detection
    ▼
AgentResponse                        -- plan, assumptions, self-check,
                                         generation_mode, download URL
```

Modules: `app/models.py` (pydantic schemas), `app/guardrails.py`,
`app/llm_client.py`, `app/planner.py`, `app/executor.py`, `app/docgen.py`,
`app/main.py` (FastAPI routes).

## Agent workflow / planning logic

The agent never asks the user a follow-up question — it has to run
autonomously end-to-end, so:

1. It classifies the request into one of 7 document types either by asking
   the LLM (structured JSON output) or, if that's unavailable, by keyword
   matching against a fallback table.
2. If the request is vague ("some kind of document", very short, phrased as
   a question, etc. — see `guardrails.detect_ambiguity`), it doesn't stall:
   it records explicit **assumptions** and proceeds, and those assumptions
   are surfaced both in the API response and as a callout box at the top of
   the generated document.
3. It expands the plan into a numbered `TaskStep` list — `validate_request`,
   `classify_document_type`, `resolve_assumptions`, `plan_sections`, one
   `generate_section:<name>` step per section, `self_check`, `render_docx`
   — and executes them in order, updating each step's status/detail as it
   completes. That list is returned to the caller so the "autonomous
   planning" is actually visible, not just internal.
4. Each section is generated independently (own LLM call / own fallback),
   which keeps failures isolated — one bad section doesn't take down the
   whole document.
5. A lightweight reflection pass re-reads the draft before rendering and
   flags empty/short/duplicated sections.

## LLM integration

`app/llm_client.py` wraps the Groq API (OpenAI-compatible `chat.completions`,
free tier, `llama-3.3-70b-versatile` by default). Used twice per request:
once for planning (JSON-mode) and once per section for drafting content.

## Document generation

`app/docgen.py` uses `python-docx` to build one consistent, clean layout
(title, metadata line, optional assumptions callout, then a `Heading 1` +
body per section) that works for any of the 7 document types, with basic
bullet-list detection so attendee lists / action items render as real
Word bullets instead of a wall of text.

## API design

- `POST /agent` — the only endpoint that matters for the assignment;
  request/response are typed Pydantic models (`AgentRequest`,
  `AgentResponse`), validation errors return `422` with a clear error list.
- `GET /agent/download/{filename}` — serves the generated file, with a
  `os.path.basename()` guard against path traversal.
- `GET /health` — reports whether an LLM key is configured, useful for the
  demo and for ops.

## Real engineering improvement: Retry & Fallback Logic

**What:** every LLM call (planning + each section) goes through
`llm_client.call_llm()` / `call_llm_json()`, which retries with exponential
backoff on any exception (timeout, rate limit, network blip, malformed
JSON), and — if all retries are exhausted or no API key is configured at
all — transparently falls back to a deterministic, template-based
generator so the pipeline still returns a complete `.docx`.

**Why this one:** free-tier LLM endpoints are the most likely thing to
break during an actual demo (rate limits, key not set, transient network
issues) — and it's also the one improvement that's trivially demoable:
just don't set `GROQ_API_KEY` and the whole system still works,
end-to-end, with `generation_mode: "fallback_template"` visible in the
response.

**How it improves the agent:** turns "LLM had a bad moment" from a hard
failure (500 error, no document) into a graceful degradation (slightly
generic content, but a complete, correctly-structured document, and the
caller is told exactly which mode was used via `generation_mode` in the
JSON and a footer note in the .docx itself).

## Debugging insight (talking point for video)

While wiring up the fallback content generator, the first version used one
shared generic-fallback string per document, formatted only with `doc_type`.
Running the self-check reflection pass against a test case immediately
flagged every section after the first as "duplicated another section's
content" — because the *only* thing that varied between sections was the
heading in the .docx, not the actual paragraph text feeding the self-check.
Root cause: the fallback template ignored the `section` name entirely. Fix:
parameterized the fallback string with `section` and a snippet of the
original request (`GENERIC_FALLBACK.format(doc_type=..., section=...,
request_snippet=...)`), so fallback content is unique per section. This
also validated that the self-check reflection logic actually catches real
issues rather than being decorative.

## Tradeoff discussion (talking point for video)

**Simplicity vs. Extensibility:** `docgen.py` uses a single shared layout
function for all 7 document types instead of a bespoke template per type
(e.g. a real table-based attendee grid for meeting minutes, a Gantt-style
table for project plans). That was the right call for a 60-minute build —
one code path to test, one thing that can break — but it caps visual
polish for structured data like attendee lists or milestone tables, which
currently render as bullet points instead of proper Word tables. The clean
extension point already exists (`SECTION_TEMPLATES` in `planner.py` keys
each doc type; `docgen.render_docx` could dispatch on `doc_type` to
type-specific renderers), it's just not built out — a reasonable line to
draw given the time box, but the first thing I'd change with another hour.

## Files

```
app/
  main.py         FastAPI app, POST /agent, GET /agent/download/{filename}
  models.py       Pydantic request/response/plan models
  guardrails.py   Request validation + ambiguity detection
  llm_client.py   Groq wrapper: retry + exponential backoff + fallback
  planner.py      Doc-type classification, section plan, task list builder
  executor.py     Runs each task, section content generation, self-check
  docgen.py       python-docx rendering
test_client.py    Demo script hitting both required test cases
requirements.txt
.env.example
output/           Generated .docx files land here
```
=======
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
>>>>>>> ad06b46389998f5618941de30ebeea80634e722f
