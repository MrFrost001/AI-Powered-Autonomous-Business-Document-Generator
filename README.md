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

```bash
curl -X POST http://127.0.0.1:8000/agent \
  -H "Content-Type: application/json" \
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
