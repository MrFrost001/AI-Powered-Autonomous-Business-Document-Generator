/* ---------------------------------------------------------------
   Autonomous Document Agent — front end logic
   Talks to the FastAPI backend:
     GET  {base}/health
     POST {base}/agent               body: { request: string }
     GET  {base}/agent/download/{filename}
----------------------------------------------------------------- */

const STORAGE_KEY = "agent-api-base";

const els = {
  apiBase: document.getElementById("api-base"),
  statusDot: document.getElementById("status-dot"),
  statusText: document.getElementById("status-text"),
  form: document.getElementById("request-form"),
  input: document.getElementById("request-input"),
  generateBtn: document.getElementById("generate-btn"),
  errorPanel: document.getElementById("error-panel"),
  logSection: document.getElementById("log-section"),
  logList: document.getElementById("log-list"),
  resultSection: document.getElementById("result-section"),
  resultTitle: document.getElementById("result-title"),
  resultMode: document.getElementById("result-mode"),
  resultType: document.getElementById("result-type"),
  assumptionsBlock: document.getElementById("assumptions-block"),
  assumptionsList: document.getElementById("assumptions-list"),
  selfcheckList: document.getElementById("selfcheck-list"),
  downloadLink: document.getElementById("download-link"),
};

const GLYPHS = { pending: "○", running: "●", done: "✓", failed: "✕" };

function getApiBase() {
  return els.apiBase.value.trim().replace(/\/+$/, "");
}

function saveApiBase() {
  localStorage.setItem(STORAGE_KEY, getApiBase());
}

function hide(el) { el.classList.add("hidden"); }
function show(el) { el.classList.remove("hidden"); }

function setStatus(state, text) {
  els.statusDot.classList.remove("online", "offline");
  if (state === "online") els.statusDot.classList.add("online");
  if (state === "offline") els.statusDot.classList.add("offline");
  els.statusText.textContent = text;
}

async function checkHealth() {
  const base = getApiBase();
  if (!base) { setStatus("unknown", "no agent URL set"); return; }
  setStatus("unknown", "checking\u2026");
  try {
    const res = await fetch(`${base}/health`, { method: "GET" });
    if (!res.ok) throw new Error(String(res.status));
    const data = await res.json();
    setStatus(
      "online",
      data.llm_configured ? "connected \u2014 LLM configured" : "connected \u2014 fallback mode (no LLM key)"
    );
  } catch (err) {
    setStatus("offline", "can\u2019t reach agent");
  }
}

function showError(message, details) {
  els.errorPanel.innerHTML = `<strong>${message}</strong>`;
  if (details && details.length) {
    const ul = document.createElement("ul");
    details.forEach((d) => {
      const li = document.createElement("li");
      li.textContent = d;
      ul.appendChild(li);
    });
    els.errorPanel.appendChild(ul);
  }
  show(els.errorPanel);
}

function clearOutput() {
  hide(els.errorPanel);
  els.errorPanel.innerHTML = "";
  hide(els.logSection);
  els.logList.innerHTML = "";
  hide(els.resultSection);
  hide(els.downloadLink);
  hide(els.assumptionsBlock);
}

function renderLog(tasks) {
  show(els.logSection);
  tasks.forEach((task, i) => {
    const li = document.createElement("li");
    li.style.animationDelay = `${i * 45}ms`;

    const glyph = document.createElement("span");
    glyph.className = `log-glyph ${task.status}`;
    glyph.textContent = GLYPHS[task.status] || "○";

    const name = document.createElement("span");
    name.className = "log-name";
    name.textContent = task.name;

    const detail = document.createElement("span");
    detail.className = "log-detail";
    detail.textContent = task.detail || "";

    li.append(glyph, name, detail);
    els.logList.appendChild(li);
  });
}

function renderResult(data, base) {
  show(els.resultSection);

  els.resultTitle.textContent = data.title;

  els.resultMode.textContent = data.generation_mode === "llm" ? "LLM-drafted" : "fallback template";
  els.resultMode.classList.toggle("fallback", data.generation_mode !== "llm");

  els.resultType.textContent =
    `${data.doc_type.replace(/_/g, " ")} \u00b7 ${data.plan.filter(t => t.name.startsWith("generate_section:")).length} sections`;

  els.assumptionsList.innerHTML = "";
  if (data.assumptions && data.assumptions.length) {
    data.assumptions.forEach((a) => {
      const li = document.createElement("li");
      li.textContent = a;
      els.assumptionsList.appendChild(li);
    });
    show(els.assumptionsBlock);
  } else {
    hide(els.assumptionsBlock);
  }

  els.selfcheckList.innerHTML = "";
  (data.self_check || []).forEach((f) => {
    const li = document.createElement("li");
    li.textContent = f;
    els.selfcheckList.appendChild(li);
  });

  els.downloadLink.href = `${base}${data.docx_download_url}`;
  els.downloadLink.textContent = `Download .docx`;
  show(els.downloadLink);
}

async function handleSubmit(evt) {
  evt.preventDefault();
  const requestText = els.input.value.trim();
  if (!requestText) return;

  const base = getApiBase();
  saveApiBase();
  clearOutput();

  els.generateBtn.disabled = true;
  els.generateBtn.textContent = "Generating\u2026";

  try {
    const res = await fetch(`${base}/agent`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ request: requestText }),
    });

    if (res.status === 422) {
      const errBody = await res.json().catch(() => null);
      const problems = errBody?.detail?.errors || errBody?.detail || [];
      showError(
        "The agent rejected that request.",
        Array.isArray(problems) ? problems : [String(problems)]
      );
      return;
    }

    if (!res.ok) {
      showError(`The agent returned an error (HTTP ${res.status}). Try again in a moment.`);
      return;
    }

    const data = await res.json();
    renderLog(data.plan);
    renderResult(data, base);
    setStatus("online", "connected");
  } catch (err) {
    showError(
      `Can\u2019t reach the agent at ${base}.`,
      [
        "Make sure the FastAPI server is running (uvicorn app.main:app --port 8000).",
        "If the frontend and backend are on different origins, the backend needs CORS enabled.",
      ]
    );
    setStatus("offline", "can\u2019t reach agent");
  } finally {
    els.generateBtn.disabled = false;
    els.generateBtn.textContent = "Generate document";
  }
}

els.form.addEventListener("submit", handleSubmit);
els.apiBase.addEventListener("change", () => { saveApiBase(); checkHealth(); });

(function init() {
  const saved = localStorage.getItem(STORAGE_KEY);
  if (saved) {
    els.apiBase.value = saved;
  } else if (location.protocol.startsWith("http")) {
    // Same-origin default: works out of the box when FastAPI serves this
    // frontend itself (StaticFiles mount). Editable for a two-server setup.
    els.apiBase.value = location.origin;
  } else {
    // Opened as a local file (file://) — fall back to the usual dev port.
    els.apiBase.value = "http://127.0.0.1:8000";
  }
  checkHealth();
})();
