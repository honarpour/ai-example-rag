const SAMPLE_QUESTIONS = [
  "How much PTO do I get, and does it carry over?",
  "Is my data encrypted at rest?",
  "What's the home office equipment budget?",
  "Who do I contact if I lose my laptop?",
  "How long is file version history kept?",
];

const STAGE_DELAY_MS = 550;
const knownTitles = {};
const documentCache = {};
let defaultModelId = "server default"; // replaced with the real deployed model id once /api/corpus responds

function apiBase() {
  const port = document.getElementById("backendSelect").value;
  return `${window.location.protocol}//${window.location.hostname}:${port}`;
}

// Anything from a server response or a caught error (error messages, the model id
// echoed back from /ask) is untrusted text getting dropped into innerHTML for
// convenience elsewhere in this file - always run it through this first. The
// model override field in particular passes through only a "contains 'claude'"
// check server-side, so unescaped HTML there is a real (if low-stakes, local-only)
// self-XSS path otherwise.
function escapeHtml(str) {
  return String(str)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;");
}

function el(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
}

function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

async function loadKnownTitles() {
  try {
    const res = await fetch("corpus-manifest.json");
    const manifest = await res.json();
    for (const doc of manifest.docs) knownTitles[doc.doc_id] = doc.title;
  } catch (e) {
    // fine - just means no curated titles are available yet
  }
}

function renderCorpus(docs) {
  const kbCards = document.getElementById("kbCards");
  kbCards.innerHTML = "";
  let totalChunks = 0;

  for (const doc of docs) {
    const title = knownTitles[doc.doc_id] || doc.title || doc.doc_id;
    const card = el("div", "kb-card");
    card.dataset.docId = doc.doc_id;
    card.appendChild(el("h3", null, title));
    const pillWrap = el("div", "chunk-pills");
    for (const chunk of doc.chunks) {
      const pill = el("span", "chunk-pill", `#${chunk.chunk_id.split("#")[1]}`);
      pill.dataset.chunkId = chunk.chunk_id;
      pill.title = chunk.preview;
      pillWrap.appendChild(pill);
      totalChunks += 1;
    }
    card.appendChild(pillWrap);

    const viewBtn = el("button", "view-doc-btn", "View full document ▾");
    viewBtn.type = "button";
    viewBtn.dataset.docId = doc.doc_id;
    card.appendChild(viewBtn);

    const content = el("div", "doc-content");
    content.hidden = true;
    card.appendChild(content);

    kbCards.appendChild(card);
  }

  document.getElementById("docCount").textContent = docs.length;
  document.getElementById("chunkCount").textContent = totalChunks;
}

async function toggleDocument(docId, contentEl, button) {
  if (!contentEl.hidden) {
    contentEl.hidden = true;
    button.textContent = "View full document ▾";
    return;
  }

  if (documentCache[docId]) {
    contentEl.innerHTML = documentCache[docId];
    contentEl.hidden = false;
    button.textContent = "Hide full document ▴";
    return;
  }

  button.textContent = "Loading...";
  try {
    const res = await fetch(`${apiBase()}/api/document?doc_id=${encodeURIComponent(docId)}`);
    const data = await res.json();
    if (!res.ok) {
      contentEl.innerHTML = `<span class="error-box">${escapeHtml(data.error || "Could not load document")}</span>`;
    } else {
      const html = `<pre class="doc-source">${data.content.replace(/</g, "&lt;")}</pre>`;
      documentCache[docId] = html;
      contentEl.innerHTML = html;
    }
    contentEl.hidden = false;
    button.textContent = "Hide full document ▴";
  } catch (err) {
    contentEl.innerHTML = `<span class="error-box">${escapeHtml(err.message)}</span>`;
    contentEl.hidden = false;
    button.textContent = "Hide full document ▴";
  }
}

function initDocumentViewer() {
  document.getElementById("kbCards").addEventListener("click", (event) => {
    const button = event.target.closest(".view-doc-btn");
    if (!button) return;
    const card = button.closest(".kb-card");
    const contentEl = card.querySelector(".doc-content");
    toggleDocument(button.dataset.docId, contentEl, button);
  });
}

let modelFieldEditedByUser = false;

function applyDefaultModelId(modelId) {
  if (!modelId) return;
  defaultModelId = modelId;
  const input = document.getElementById("modelIdInput");
  if (!modelFieldEditedByUser) input.value = defaultModelId;
}

async function loadCorpus() {
  // Prefer the live index (reflects uploads); fall back to the static manifest
  // (e.g. before AWS is deployed, or if the corpus endpoint is unreachable).
  try {
    const res = await fetch(`${apiBase()}/api/corpus`);
    if (!res.ok) throw new Error("live corpus not available");
    const data = await res.json();
    if (!data.docs || data.docs.length === 0) throw new Error("empty");
    renderCorpus(data.docs);
    applyDefaultModelId(data.default_model_id);
    return;
  } catch (e) {
    const res = await fetch("corpus-manifest.json");
    const data = await res.json();
    renderCorpus(data.docs);
  }
}

function loadSampleQuestions() {
  const wrap = document.getElementById("sampleQuestions");
  for (const q of SAMPLE_QUESTIONS) {
    const chip = el("button", "sample-chip", q);
    chip.type = "button";
    chip.addEventListener("click", () => {
      document.getElementById("queryInput").value = q;
      document.getElementById("askForm").requestSubmit();
    });
    wrap.appendChild(chip);
  }
}

async function loadServerInfo() {
  try {
    const res = await fetch(`${apiBase()}/api/info`);
    const info = await res.json();
    document.getElementById("runtimeBadge").textContent = `Answering via: ${info.runtime}, port ${info.port}`;
  } catch (e) {
    document.getElementById("runtimeBadge").textContent = "Backend unreachable - is it running?";
  }
}

function setUploadStatus(text, kind) {
  const status = document.getElementById("uploadStatus");
  status.textContent = text;
  status.className = "upload-status" + (kind ? ` ${kind}` : "");
}

async function waitForIndexing(docId, attempts = 8) {
  for (let i = 0; i < attempts; i++) {
    await sleep(2000);
    try {
      const res = await fetch(`${apiBase()}/api/corpus`);
      if (res.ok) {
        const data = await res.json();
        if (data.docs.some((d) => d.doc_id === docId)) {
          // Already have the fresh data right here - render it directly instead of
          // making loadCorpus() re-fetch the same thing again.
          renderCorpus(data.docs);
          applyDefaultModelId(data.default_model_id);
          return true;
        }
      }
    } catch (e) {
      // keep polling
    }
  }
  await loadCorpus();
  return false;
}

async function handleUpload(event) {
  const file = event.target.files[0];
  if (!file) return;

  const text = await file.text();
  setUploadStatus(`Uploading "${file.name}"...`);

  try {
    const res = await fetch(`${apiBase()}/api/upload`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ filename: file.name, content: text }),
    });
    const data = await res.json();
    if (!res.ok) {
      setUploadStatus(`Error: ${data.error || "upload failed"}`, "error");
      return;
    }

    delete documentCache[data.doc_id]; // re-uploads should show fresh content, not a stale cache hit
    setUploadStatus(`Uploaded. Indexing "${data.doc_id}"...`);
    const indexed = await waitForIndexing(data.doc_id);
    setUploadStatus(
      indexed
        ? `"${data.doc_id}" is indexed - try asking about it below.`
        : `Still indexing "${data.doc_id}" - it should appear shortly; try asking anyway.`,
      indexed ? "success" : null
    );
  } catch (err) {
    setUploadStatus(`Error: ${err.message}`, "error");
  } finally {
    event.target.value = "";
  }
}

function resetPipeline() {
  document.querySelectorAll(".stage").forEach((s) => s.classList.remove("active"));
  document.querySelectorAll("[data-body]").forEach((b) => (b.innerHTML = ""));
  document.querySelectorAll(".chunk-pill").forEach((p) => {
    p.classList.remove("match", "dim");
  });
}

function activateStage(name, html) {
  const stage = document.querySelector(`.stage[data-stage="${name}"]`);
  stage.classList.add("active");
  document.querySelector(`[data-body="${name}"]`).innerHTML = html;
}

function highlightSources(sources) {
  const matchedIds = new Set(sources.map((s) => s.chunk_id));
  document.querySelectorAll(".chunk-pill").forEach((pill) => {
    if (matchedIds.has(pill.dataset.chunkId)) {
      pill.classList.add("match");
    } else {
      pill.classList.add("dim");
    }
  });
}

function renderSources(sources) {
  if (sources.length === 0) {
    return '<div class="source-list">No relevant sources found.</div>';
  }
  const list = el("div", "source-list");
  for (const s of sources) {
    const item = el("div", "source-item");
    const meta = el("div", "source-meta");
    meta.appendChild(el("span", null, s.doc_id));
    meta.appendChild(el("span", "score-badge", `similarity ${s.score.toFixed(3)}`));
    item.appendChild(meta);
    item.appendChild(el("div", null, s.text));
    list.appendChild(item);
  }
  return list.outerHTML;
}

async function handleAsk(event) {
  event.preventDefault();
  const query = document.getElementById("queryInput").value.trim();
  if (!query) return;

  const button = document.getElementById("askButton");
  button.disabled = true;
  resetPipeline();

  try {
    activateStage("embed", '<span class="spinner"></span> Embedding your question with Bedrock Titan Embeddings...');
    await sleep(STAGE_DELAY_MS);
    activateStage("embed", "Embedded your question with Bedrock Titan Embeddings.");

    activateStage("search", '<span class="spinner"></span> Running a k-NN search over the S3 Vectors index...');

    const modelIdRaw = document.getElementById("modelIdInput").value.trim();
    const modelId = modelIdRaw === defaultModelId ? "" : modelIdRaw;
    const res = await fetch(`${apiBase()}/api/ask`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ query, k: 3, ...(modelId ? { model_id: modelId } : {}) }),
    });
    const data = await res.json();

    if (!res.ok) {
      activateStage("search", `<span class="error-box">${escapeHtml(data.error || "Request failed")}</span>`);
      return;
    }

    highlightSources(data.sources);
    activateStage("search", renderSources(data.sources));
    await sleep(STAGE_DELAY_MS);

    activateStage("prompt", `<div class="prompt-box">${escapeHtml(data.prompt)}</div>`);
    await sleep(STAGE_DELAY_MS);

    activateStage("answer", '<span class="spinner"></span> Asking Claude on Bedrock...');
    await sleep(STAGE_DELAY_MS);
    const modelNote = data.model_id ? `<div class="model-note">via ${escapeHtml(data.model_id)}</div>` : "";
    activateStage("answer", `<div class="answer-box">${escapeHtml(data.answer)}</div>${modelNote}`);
  } catch (err) {
    activateStage("answer", `<span class="error-box">${escapeHtml(err.message)}</span>`);
  } finally {
    button.disabled = false;
  }
}

function initBackendSelect() {
  const select = document.getElementById("backendSelect");
  // Default to whichever port served this page - if it's neither 5001 nor 5002
  // (e.g. opened some other way), fall back to the Python backend.
  const currentPort = window.location.port;
  if ([...select.options].some((o) => o.value === currentPort)) {
    select.value = currentPort;
  }
  select.addEventListener("change", () => {
    loadServerInfo();
    loadCorpus();
  });
}

document.getElementById("askForm").addEventListener("submit", handleAsk);
document.getElementById("fileInput").addEventListener("change", handleUpload);
document.getElementById("modelIdInput").addEventListener("input", () => {
  modelFieldEditedByUser = true;
});
initBackendSelect();
initDocumentViewer();
loadKnownTitles().then(loadCorpus);
loadSampleQuestions();
loadServerInfo();
