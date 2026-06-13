const state = {
  mode: "text",
  activeSessionId: null,
  pendingFile: null,
  pendingPreviewUrl: null,
  lastOutputText: "",
  isBusy: false,
  selectedSessionIds: new Set(),
  recentSessionIds: [],
  progressTimer: null,
  progressStepIds: [],
  progressStepIndex: 0,
  currentStreamStep: null,
  liveTokenText: "",
  showAllSessions: false,
  account: null,
  accountDetails: null,
  authMode: "login",
  signupPendingId: null,
};

const els = {
  modeTabs: document.querySelectorAll(".mode-tab"),
  textMode: document.querySelector("#textMode"),
  urlMode: document.querySelector("#urlMode"),
  imageMode: document.querySelector("#imageMode"),
  textInput: document.querySelector("#textInput"),
  urlInput: document.querySelector("#urlInput"),
  dropZone: document.querySelector("#dropZone"),
  fileInput: document.querySelector("#fileInput"),
  uploadButton: document.querySelector("#uploadButton"),
  selectedFilePreview: document.querySelector("#selectedFilePreview"),
  dropTitle: document.querySelector("#dropTitle"),
  checkButton: document.querySelector("#checkButton"),
  clearButton: document.querySelector("#clearButton"),
  uploadLimitStatus: document.querySelector("#uploadLimitStatus"),
  uploadState: document.querySelector("#uploadState"),
  emptyOutput: document.querySelector("#emptyOutput"),
  resultShell: document.querySelector("#resultShell"),
  chatMessages: document.querySelector("#chatMessages"),
  pipelineTime: document.querySelector("#pipelineTime"),
  copyOutputButton: document.querySelector("#copyOutputButton"),
  gemmaRate: document.querySelector("#gemmaRate"),
  debugDetails: document.querySelector("#debugDetails"),
  debugPayload: document.querySelector("#debugPayload"),
  sessionList: document.querySelector("#sessionList"),
  themeToggle: document.querySelector("#themeToggle"),
  accountStatus: document.querySelector("#accountStatus"),
  accountName: document.querySelector("#accountName"),
  loginButton: document.querySelector("#loginButton"),
  signupButton: document.querySelector("#signupButton"),
  logoutButton: document.querySelector("#logoutButton"),
  helpButton: document.querySelector("#helpButton"),
  selectSessionsButton: document.querySelector("#selectSessionsButton"),
  selectAllSessionsButton: document.querySelector("#selectAllSessionsButton"),
  deleteSelectedButton: document.querySelector("#deleteSelectedButton"),
  cancelSelectionButton: document.querySelector("#cancelSelectionButton"),
  selectionSummary: document.querySelector("#selectionSummary"),
  viewAllButton: document.querySelector("#viewAllButton"),
  authModal: document.querySelector("#authModal"),
  authForm: document.querySelector("#authForm"),
  authTitle: document.querySelector("#authTitle"),
  authCredentialsFields: document.querySelector("#authCredentialsFields"),
  authUsername: document.querySelector("#authUsername"),
  authEmail: document.querySelector("#authEmail"),
  authPassword: document.querySelector("#authPassword"),
  authPasswordConfirm: document.querySelector("#authPasswordConfirm"),
  authWebsite: document.querySelector("#authWebsite"),
  emailVerificationFields: document.querySelector("#emailVerificationFields"),
  emailVerificationCode: document.querySelector("#emailVerificationCode"),
  authSubmitButton: document.querySelector("#authSubmitButton"),
  authCloseButton: document.querySelector("#authCloseButton"),
  authStatus: document.querySelector("#authStatus"),
  accountModal: document.querySelector("#accountModal"),
  accountCloseButton: document.querySelector("#accountCloseButton"),
  accountPanelUsername: document.querySelector("#accountPanelUsername"),
  accountTierChip: document.querySelector("#accountTierChip"),
  accountEmail: document.querySelector("#accountEmail"),
  accountTierValue: document.querySelector("#accountTierValue"),
  accountUsage: document.querySelector("#accountUsage"),
  accountUpgradeButton: document.querySelector("#accountUpgradeButton"),
  accountDeleteButton: document.querySelector("#accountDeleteButton"),
  accountStatusMessage: document.querySelector("#accountStatusMessage"),
  helpModal: document.querySelector("#helpModal"),
  helpCloseButton: document.querySelector("#helpCloseButton"),
};

const APP_CONFIG = window.F1_FACT_CHECK_CONFIG || {};
const KNOWLEDGE_SOURCE_LABEL =
  APP_CONFIG.knowledgeSourceLabel || "Knowledge Database (F1 WC database + F1 Jolpica API)";
const RECENT_SESSION_TEXT_MAX_CHARS = 110;
const MAX_EVIDENCE_ITEMS_PER_CLAIM = 4;

const PIPELINE_STEPS = [
  { id: "preparing_input", label: "Preparing input", detail: "Checking the input before submission." },
  { id: "submitting_text", label: "Submitting text", detail: "Sending the request to the fact-check service.", modes: ["text"] },
  { id: "submitting_url", label: "Submitting URL", detail: "Sending the article URL to the fact-check service.", modes: ["url"] },
  { id: "uploading_image", label: "Uploading screenshot", detail: "Sending the image to the fact-check service.", modes: ["image"] },
  {
    id: "waiting_for_result",
    label: "Waiting for fact-check result",
    detail: "The backend is running the full pipeline and will return one completed response.",
  },
];

const SERVER_STAGE_LABELS = {
  url_fetch: { label: "Fetching URL text", detail: "The backend is downloading and normalizing the article text." },
  ocr: { label: "Running OCR", detail: "The backend is converting the screenshot into normalized text." },
  f1_signal_check: { label: "Checking F1 relevance", detail: "The backend is checking whether the input contains Formula 1 content." },
  claim_extraction: { label: "Extracting F1 claims", detail: "Gemma is extracting Formula 1-related checkable claims." },
  claim_classification: { label: "Classifying claims", detail: "Gemma is selecting structured, web, mixed, or unsupported routes." },
  route_planning: { label: "Planning execution", detail: "The backend is building per-claim retrieval worklists." },
  structured_claim_rewrite: { label: "Completing structured claims", detail: "Gemma is adding missing context for local-data claims." },
  structured_retrieval: { label: "Checking local records", detail: "The backend is searching SQLite/FTS and FAISS evidence." },
  web_retrieval: { label: "Gathering web evidence", detail: "The backend is using Brave grounding and source-policy ranking." },
  evidence_consolidation: { label: "Consolidating evidence", detail: "The backend is merging evidence back into claim bundles." },
  verdict_generation: { label: "Generating verdict", detail: "Gemma verdict tokens are streaming live when model generation is needed." },
  result_aggregation: { label: "Persisting result", detail: "The backend is aggregating and saving the completed result." },
};

document.addEventListener("DOMContentLoaded", async () => {
  bindEvents();
  await loadAccountState();
  await loadRecentSessions();
});

function bindEvents() {
  els.modeTabs.forEach((button) => {
    button.addEventListener("click", () => setMode(button.dataset.mode));
  });
  on(els.checkButton, "click", submitCheck);
  on(els.clearButton, "click", clearInput);
  on(els.copyOutputButton, "click", copyOutput);
  on(els.uploadButton, "click", () => els.fileInput.click());
  on(els.fileInput, "change", () => {
    const file = els.fileInput.files?.[0];
    if (file) attachFile(file);
    els.fileInput.value = "";
  });
  on(els.dropZone, "click", (event) => {
    if (!event.target.closest("button")) els.fileInput.click();
  });
  on(els.dropZone, "keydown", (event) => {
    if (event.key === "Enter" || event.key === " ") {
      event.preventDefault();
      els.fileInput.click();
    }
  });
  on(els.dropZone, "dragover", (event) => {
    event.preventDefault();
    els.dropZone.classList.add("is-dragging");
  });
  on(els.dropZone, "dragleave", () => els.dropZone.classList.remove("is-dragging"));
  on(els.dropZone, "drop", (event) => {
    event.preventDefault();
    els.dropZone.classList.remove("is-dragging");
    const file = event.dataTransfer?.files?.[0];
    if (file) attachFile(file);
  });
  document.addEventListener("paste", (event) => {
    if (state.mode !== "image") return;
    const file = [...(event.clipboardData?.files || [])].find((item) => item.type.startsWith("image/"));
    if (!file) return;
    event.preventDefault();
    attachFile(new File([file], "pasted-f1-news.png", { type: file.type || "image/png" }));
  });
  on(els.themeToggle, "click", () => document.body.classList.toggle("dark"));
  on(els.accountStatus, "click", openAccountModal);
  on(els.loginButton, "click", () => openAuthModal("login").catch((error) => setStatus(error.message, "error")));
  on(els.signupButton, "click", () => openAuthModal("signup").catch((error) => setStatus(error.message, "error")));
  on(els.logoutButton, "click", logout);
  on(els.helpButton, "click", () => { els.helpModal.hidden = false; });
  on(els.helpCloseButton, "click", () => { els.helpModal.hidden = true; });
  on(els.authCloseButton, "click", () => { els.authModal.hidden = true; });
  on(els.authForm, "submit", submitAuthForm);
  on(els.accountCloseButton, "click", () => { els.accountModal.hidden = true; });
  on(els.accountUpgradeButton, "click", () => setAccountStatus("Account upgrades are not configured yet."));
  on(els.accountDeleteButton, "click", () => setAccountStatus("Account deletion is not configured yet."));
  on(els.selectSessionsButton, "click", enterSelectionMode);
  on(els.selectAllSessionsButton, "click", toggleSelectAllSessions);
  on(els.cancelSelectionButton, "click", exitSelectionMode);
  on(els.deleteSelectedButton, "click", deleteSelectedSessions);
  on(els.viewAllButton, "click", () => {
    state.showAllSessions = true;
    loadRecentSessions();
  });
}

function setMode(mode) {
  if (!["text", "url", "image"].includes(mode) || state.isBusy) return;
  state.mode = mode;
  els.modeTabs.forEach((button) => {
    const active = button.dataset.mode === mode;
    button.classList.toggle("is-active", active);
    button.setAttribute("aria-selected", String(active));
  });
  els.textMode.hidden = mode !== "text";
  els.urlMode.hidden = mode !== "url";
  els.imageMode.hidden = mode !== "image";
  setStatus("");
}

function attachFile(file) {
  const error = validateImage(file);
  if (error) {
    setStatus(error, "error");
    return;
  }
  clearPendingFile();
  state.pendingFile = file;
  state.pendingPreviewUrl = URL.createObjectURL(file);
  els.selectedFilePreview.innerHTML = `
    <div class="selected-thumb"><img src="${state.pendingPreviewUrl}" alt="" /></div>
    <div class="selected-meta">
      <strong>${escapeHtml(file.name)}</strong>
      <span>${escapeHtml(file.type || "image")}</span>
    </div>
    <button class="remove-file" type="button" aria-label="Remove selected image" title="Remove selected image">&times;</button>
  `;
  els.selectedFilePreview.hidden = false;
  els.dropTitle.textContent = file.name;
  els.selectedFilePreview.querySelector(".remove-file").addEventListener("click", (event) => {
    event.stopPropagation();
    clearPendingFile();
  });
}

async function submitCheck() {
  if (state.isBusy) return;
  state.isBusy = true;
  setControlsBusy(true);
  clearResult();
  startPipelineProgress(state.mode);
  setStatus("Preparing input...");

  try {
    let session = null;
    await streamCurrentInput((eventName, data) => {
      if (eventName === "done") {
        session = data;
        return;
      }
      handleFactCheckStreamEvent(eventName, data);
    });
    if (!session) throw new Error("Fact-check stream ended before returning a result.");
    state.activeSessionId = session.id;
    renderSession(session, { animate: false });
    renderRateLimit(session.rate_limit);
    setStatus("Fact-check complete.", "success");
    await loadRecentSessions();
  } catch (error) {
    stopPipelineProgress();
    stopRenderProgress();
    setStatus(error.message, "error");
    els.emptyOutput.hidden = false;
  } finally {
    if (!els.resultShell.hidden) stopPipelineProgress();
    state.isBusy = false;
    setControlsBusy(false);
  }
}

async function streamCurrentInput(onEvent) {
  const response = await postCurrentInputStream();
  await readSseResponse(response, onEvent);
}

async function postCurrentInput() {
  if (state.mode === "text") {
    const text = els.textInput.value.trim();
    if (!text) {
      els.textInput.focus();
      throw new Error("Text input cannot be empty.");
    }
    return fetch("/sessions/check", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ input_type: "text", text, session_id: state.activeSessionId }),
    });
  }
  if (state.mode === "url") {
    const url = els.urlInput.value.trim();
    if (!url) {
      els.urlInput.focus();
      throw new Error("URL input cannot be empty.");
    }
    return fetch("/sessions/check", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ input_type: "url", url, session_id: state.activeSessionId }),
    });
  }
  if (!state.pendingFile) {
    throw new Error("Choose or paste a screenshot first.");
  }
  const body = new FormData();
  body.append("image", state.pendingFile);
  const query = state.activeSessionId ? `?session_id=${encodeURIComponent(state.activeSessionId)}` : "";
  return fetch(`/sessions/check-image${query}`, { method: "POST", body });
}

async function postCurrentInputStream() {
  if (state.mode === "text") {
    const text = els.textInput.value.trim();
    if (!text) {
      els.textInput.focus();
      throw new Error("Text input cannot be empty.");
    }
    return fetch("/sessions/check/stream", {
      method: "POST",
      headers: { "Content-Type": "application/json", "Accept": "text/event-stream" },
      body: JSON.stringify({ input_type: "text", text, session_id: state.activeSessionId }),
    });
  }
  if (state.mode === "url") {
    const url = els.urlInput.value.trim();
    if (!url) {
      els.urlInput.focus();
      throw new Error("URL input cannot be empty.");
    }
    return fetch("/sessions/check/stream", {
      method: "POST",
      headers: { "Content-Type": "application/json", "Accept": "text/event-stream" },
      body: JSON.stringify({ input_type: "url", url, session_id: state.activeSessionId }),
    });
  }
  if (!state.pendingFile) {
    throw new Error("Choose or paste a screenshot first.");
  }
  const body = new FormData();
  body.append("image", state.pendingFile);
  const query = state.activeSessionId ? `?session_id=${encodeURIComponent(state.activeSessionId)}` : "";
  return fetch(`/sessions/check-image/stream${query}`, {
    method: "POST",
    headers: { "Accept": "text/event-stream" },
    body,
  });
}

function renderSession(session, options = {}) {
  const result = session.fact_check_result;
  if (!result) {
    clearResult();
    return;
  }
  stopRenderProgress();
  els.emptyOutput.hidden = true;
  els.resultShell.hidden = false;
  els.chatMessages.hidden = false;
  els.debugDetails.hidden = false;
  els.pipelineTime.textContent = pipelineTimeLabel(result, session);
  els.gemmaRate.textContent = gemmaRateLabel(result);
  const claims = Array.isArray(result.claims) ? result.claims : [];
  const messages = claims.length
    ? claims.map((item, index) => renderClaimMessage(item, index))
    : [renderSystemMessage(result.summary || "No information related to F1 could be extracted.")];
  els.chatMessages.setAttribute("aria-label", "Fact-check result");
  els.chatMessages.innerHTML = messages.join("");
  els.debugPayload.textContent = JSON.stringify(debugPayload(result), null, 2);
  state.lastOutputText = outputTextFromResult(result, session);
}

function renderClaimMessage(item, index) {
  const claim = item.claim || {};
  const evidence = Array.isArray(item.evidence) ? item.evidence : [];
  const evidenceBox = renderEvidenceSummaryBox(evidence);
  return `
    <div class="chat-message assistant-message">
      <div class="message-head">
        <span>${escapeHtml(claim.claim_id || `C${index + 1}`)}</span>
        <span class="validity-pill validity-${validityClass(item.verdict)}">${escapeHtml(validityLabel(item.verdict))}</span>
      </div>
      <p class="claim-text">${escapeHtml(claim.text || "Claim")}</p>
      <p><strong>Explanation</strong><br>${escapeHtml(item.rationale || "No claim explanation was returned.")}</p>
      <div class="evidence-grid">${evidenceBox}</div>
      <p><strong>Conclusion</strong><br>${escapeHtml(conclusionText(item))}</p>
    </div>
  `;
}

function renderSystemMessage(message) {
  return `
    <div class="chat-message assistant-message">
      <p>${escapeHtml(message)}</p>
    </div>
  `;
}

function renderProgressMessage(step, stateClass) {
  return `
    <div class="progress-line ${escapeHtml(stateClass)}" data-step="${escapeHtml(step.id)}">
      <span class="progress-label">
        ${escapeHtml(step.label)}
        <span class="progress-dots" aria-hidden="true"><span>.</span><span>.</span><span>.</span></span>
      </span>
      <small>${escapeHtml(step.detail)}</small>
    </div>
  `;
}

function renderLiveTokenMessage() {
  if (!state.liveTokenText) return "";
  return `
    <div class="chat-message assistant-message live-token-message">
      <div class="message-head">
        <span>Gemma stream</span>
        <span class="validity-pill">Live</span>
      </div>
      <pre class="live-token-text">${escapeHtml(state.liveTokenText)}</pre>
    </div>
  `;
}

function renderLiveStreamView(step, stateClass = "is-active") {
  state.currentStreamStep = step;
  els.chatMessages.innerHTML = `${renderProgressMessage(step, stateClass)}${renderLiveTokenMessage()}`;
  els.chatMessages.scrollTop = els.chatMessages.scrollHeight;
}

function handleFactCheckStreamEvent(eventName, data = {}) {
  if (eventName === "gemma_token") {
    appendLiveGemmaToken(data.delta || "");
    return;
  }
  if (eventName.endsWith("_started") || eventName.endsWith("_finished")) {
    renderServerStage(eventName, data);
  }
}

function renderServerStage(eventName, data = {}) {
  const stageId = data.stage || eventName.replace(/_(started|finished)$/, "");
  const labels = SERVER_STAGE_LABELS[stageId] || {
    label: humanizeStage(stageId),
    detail: "The backend reported a fact-check pipeline event.",
  };
  const status = eventName.endsWith("_finished") ? "finished" : "started";
  const step = {
    id: stageId,
    label: status === "finished" ? `${labels.label} complete` : labels.label,
    detail: labels.detail,
  };
  renderLiveStreamView(step, status === "finished" ? "is-done" : "is-active");
}

function appendLiveGemmaToken(delta) {
  if (!delta) return;
  state.liveTokenText += delta;
  const step = state.currentStreamStep || {
    id: "verdict_generation",
    ...SERVER_STAGE_LABELS.verdict_generation,
  };
  renderLiveStreamView(step, "is-active");
}

function renderEvidenceSummaryBox(evidence) {
  if (!evidence.length) {
    return `<div class="evidence-box"><strong>Source</strong><p>No evidence source was returned for this claim.</p></div>`;
  }
  const visibleEvidence = evidence.slice(0, MAX_EVIDENCE_ITEMS_PER_CLAIM);
  const topEvidence = visibleEvidence[0];
  const localCount = visibleEvidence.filter((item) => item.source_type === "local_db").length;
  const webItems = visibleEvidence.filter((item) => item.source_type === "web");
  const sourceLabels = [];
  if (localCount) sourceLabels.push(KNOWLEDGE_SOURCE_LABEL);
  if (webItems.length) {
    const domains = [...new Set(webItems.map((item) => item.source_id || item.url || "web source"))].slice(0, 3);
    sourceLabels.push(`Web evidence: ${domains.join(", ")}`);
  }
  const extraItems = visibleEvidence.slice(1);
  const expandable = evidence.length > 1;
  return `
    <details class="evidence-box" ${expandable ? "" : "open"}>
      <summary>
        <div>
          <strong>Source</strong>
          <p class="evidence-title">${escapeHtml(sourceLabels.join(" + ") || sourceLabelForEvidence(topEvidence))}</p>
          <p>${escapeHtml(topEvidence.snippet || topEvidence.title || "No summary text was returned.")}</p>
        </div>
        <span>${escapeHtml(`${Math.min(evidence.length, MAX_EVIDENCE_ITEMS_PER_CLAIM)} shown${evidence.length > MAX_EVIDENCE_ITEMS_PER_CLAIM ? ` of ${evidence.length}` : ""}`)}</span>
      </summary>
      ${extraItems.length ? `<div class="evidence-extra">${extraItems.map(renderEvidenceDetail).join("")}</div>` : ""}
    </details>
  `;
}

function renderEvidenceDetail(item, index) {
  return `
    <div class="evidence-detail">
      <strong>${escapeHtml(`Evidence ${index + 2}`)}</strong>
      <p>${escapeHtml(sourceLabelForEvidence(item))}</p>
      <p>${escapeHtml(item.snippet || item.title || "No summary text was returned.")}</p>
    </div>
  `;
}

function sourceLabelForEvidence(item) {
  if (!item) return "Evidence";
  if (item.source_type === "local_db") return KNOWLEDGE_SOURCE_LABEL;
  if (item.source_type === "web") return item.source_id || item.url || "Web evidence";
  return item.source_id || item.source_type || "Evidence";
}

function stopRenderProgress() {}

function validityLabel(value) {
  const normalized = String(value || "NOT_ENOUGH_INFO");
  if (normalized === "SUPPORTS") return "Valid";
  if (normalized === "REFUTES") return "Invalid";
  return "Not enough info";
}

function validityClass(value) {
  const normalized = String(value || "NOT_ENOUGH_INFO").toLowerCase();
  return normalized.replace(/[^a-z0-9_]+/g, "_");
}

function conclusionText(item) {
  const label = validityLabel(item.verdict);
  const confidence = formatConfidence(item.confidence);
  return `${label}. Confidence: ${confidence}. Source route: ${item.verification_stream || item.claim?.verification_stream || "unknown"}.`;
}

function pipelineTimeLabel(result, session) {
  const total = result.meta?.timings_ms?.total ?? session.answer_elapsed_ms;
  if (!Number.isFinite(Number(total))) return "Pipeline time: unavailable";
  return `Pipeline time: ${formatDuration(Number(total))}`;
}

function gemmaRateLabel(result) {
  const rate = result.meta?.gemma_tokens_per_second;
  if (!Number.isFinite(Number(rate))) return "";
  return `Gemma ${Number(rate).toFixed(2)} tok/s`;
}

function outputTextFromResult(result, session) {
  const claims = Array.isArray(result.claims) ? result.claims : [];
  const lines = [pipelineTimeLabel(result, session), gemmaRateLabel(result), "Fact checking system"].filter(Boolean);
  if (!claims.length) {
    lines.push(result.summary || "No information related to F1 could be extracted.");
    return lines.join("\n");
  }
  claims.forEach((item, index) => {
    const claim = item.claim || {};
    const evidence = Array.isArray(item.evidence) ? item.evidence : [];
    lines.push("");
    lines.push(`${claim.claim_id || `C${index + 1}`}: ${claim.text || "Claim"}`);
    lines.push(`Validity: ${validityLabel(item.verdict)}`);
    lines.push(`Explanation: ${item.rationale || "No claim explanation was returned."}`);
    lines.push(`Source: ${plainEvidenceSources(evidence)}`);
    lines.push(`Conclusion: ${conclusionText(item)}`);
  });
  return lines.join("\n");
}

function plainEvidenceSources(evidence) {
  if (!evidence.length) return "No evidence source returned.";
  const labels = [];
  if (evidence.some((item) => item.source_type === "local_db")) labels.push(KNOWLEDGE_SOURCE_LABEL);
  const webSources = evidence
    .filter((item) => item.source_type === "web")
    .map((item) => item.source_id || item.url)
    .filter(Boolean);
  if (webSources.length) labels.push(`Web evidence: ${[...new Set(webSources)].slice(0, 3).join(", ")}`);
  return labels.join(" + ") || "Evidence";
}

async function copyOutput() {
  const text = state.lastOutputText || els.chatMessages.textContent.trim();
  if (!text) return;
  try {
    await navigator.clipboard.writeText(text);
    setStatus("Output copied.", "success");
  } catch {
    setStatus("Copy failed.", "error");
  }
}

function debugPayload(result) {
  return {
    cleaned_input_text: result.text || "",
    ocr_extracted_text: result.meta?.ocr_text || null,
    url_metadata: result.meta?.url_metadata || null,
    retrieved_evidence: (result.claims || []).map((item) => ({
      claim_id: item.claim?.claim_id,
      evidence: item.evidence || [],
    })),
    timings_ms: result.meta?.timings_ms || null,
    gemma_tokens_per_second: result.meta?.gemma_tokens_per_second || null,
  };
}

async function loadRecentSessions() {
  try {
    const query = state.showAllSessions ? "?include_all=1" : "";
    const response = await fetch(`/sessions/recent${query}`);
    const data = await readJsonResponse(response);
    renderRecentSessions(data.sessions || []);
  } catch (error) {
    els.sessionList.innerHTML = `<div class="empty-list">${escapeHtml(error.message)}</div>`;
  }
}

function renderRecentSessions(sessions) {
  state.recentSessionIds = sessions.map((session) => session.id);
  if (!sessions.length) {
    els.sessionList.innerHTML = `<div class="empty-list">No fact-check runs yet.</div>`;
    updateSelectionControls();
    return;
  }
  els.sessionList.innerHTML = sessions.map(renderSessionItem).join("");
  els.sessionList.querySelectorAll("[data-session-id]").forEach((item) => {
    item.addEventListener("click", (event) => {
      if (event.target.closest("button") || event.target.closest("input")) return;
      const sessionId = item.dataset.sessionId;
      if (item.classList.contains("selection-mode")) {
        toggleSessionSelected(sessionId);
      } else {
        openSession(sessionId);
      }
    });
  });
  els.sessionList.querySelectorAll("[data-delete-session]").forEach((button) => {
    button.addEventListener("click", () => deleteSession(button.dataset.deleteSession));
  });
  els.sessionList.querySelectorAll("[data-select-session]").forEach((input) => {
    input.addEventListener("change", () => toggleSessionSelected(input.dataset.selectSession));
  });
  updateSelectionControls();
}

function renderSessionItem(session) {
  const selected = state.selectedSessionIds.has(session.id);
  const selectionClass = state.selectedSessionIds.size || !els.cancelSelectionButton.hidden ? " selection-mode" : "";
  const preview = session.input_preview || session.filename || "F1 fact-check";
  return `
    <article class="session-item${selectionClass}" data-session-id="${escapeHtml(session.id)}">
      <input class="session-check" type="checkbox" data-select-session="${escapeHtml(session.id)}" ${selected ? "checked" : ""} ${els.cancelSelectionButton.hidden ? "hidden" : ""} />
      <div class="session-main">
        <p title="${escapeHtml(preview)}">${escapeHtml(truncateText(preview, RECENT_SESSION_TEXT_MAX_CHARS))}</p>
        <span>${escapeHtml(session.input_type || "check")} · ${formatDate(session.updated_at)}</span>
      </div>
      <div class="session-actions-fixed">
        <button class="icon-button session-delete" type="button" data-delete-session="${escapeHtml(session.id)}" aria-label="Delete session" title="Delete">
          <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M6 7h12" /><path d="M10 11v6M14 11v6" /><path d="M9 7l1-2h4l1 2" /><path d="M8 7l1 14h6l1-14" /></svg>
        </button>
      </div>
    </article>
  `;
}

async function openSession(sessionId) {
  try {
    const response = await fetch(`/sessions/${encodeURIComponent(sessionId)}`);
    const data = await readJsonResponse(response);
    state.activeSessionId = data.id;
    restoreSessionInput(data);
    renderSession(data);
  } catch (error) {
    setStatus(error.message, "error");
  }
}

function restoreSessionInput(session) {
  const inputType = session.input_type || "text";
  if (["text", "url", "image"].includes(inputType)) setMode(inputType);
  const resultText = session.fact_check_result?.text || "";
  if (inputType === "text") {
    els.textInput.value = resultText || session.input_preview || "";
  } else if (inputType === "url") {
    const run = Array.isArray(session.fact_check_runs) ? session.fact_check_runs[0] : null;
    els.urlInput.value = run?.source_url || session.input_preview || "";
  } else if (inputType === "image") {
    clearPendingFile();
    els.dropTitle.textContent = session.filename || session.input_preview || "Uploaded screenshot";
  }
}

async function deleteSession(sessionId) {
  try {
    const response = await fetch(`/sessions/${encodeURIComponent(sessionId)}`, { method: "DELETE" });
    await readJsonResponse(response);
    if (state.activeSessionId === sessionId) {
      state.activeSessionId = null;
      clearResult();
    }
    state.selectedSessionIds.delete(sessionId);
    await loadRecentSessions();
  } catch (error) {
    setStatus(error.message, "error");
  }
}

function enterSelectionMode() {
  els.cancelSelectionButton.hidden = false;
  els.selectAllSessionsButton.hidden = false;
  els.deleteSelectedButton.hidden = false;
  els.selectionSummary.hidden = false;
  els.selectSessionsButton.hidden = true;
  renderRecentSessionsFromDom();
}

function exitSelectionMode() {
  state.selectedSessionIds.clear();
  els.cancelSelectionButton.hidden = true;
  els.selectAllSessionsButton.hidden = true;
  els.deleteSelectedButton.hidden = true;
  els.selectionSummary.hidden = true;
  els.selectSessionsButton.hidden = false;
  loadRecentSessions();
}

function toggleSelectAllSessions() {
  const allSelected = state.recentSessionIds.every((id) => state.selectedSessionIds.has(id));
  state.selectedSessionIds = allSelected ? new Set() : new Set(state.recentSessionIds);
  renderRecentSessionsFromDom();
}

function toggleSessionSelected(sessionId) {
  if (state.selectedSessionIds.has(sessionId)) state.selectedSessionIds.delete(sessionId);
  else state.selectedSessionIds.add(sessionId);
  renderRecentSessionsFromDom();
}

async function deleteSelectedSessions() {
  const sessionIds = [...state.selectedSessionIds];
  if (!sessionIds.length) return;
  try {
    const response = await fetch("/sessions/bulk-delete", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ session_ids: sessionIds }),
    });
    await readJsonResponse(response);
    if (sessionIds.includes(state.activeSessionId)) {
      state.activeSessionId = null;
      clearResult();
    }
    exitSelectionMode();
  } catch (error) {
    setStatus(error.message, "error");
  }
}

function renderRecentSessionsFromDom() {
  loadRecentSessions();
}

async function loadAccountState() {
  try {
    const response = await fetch("/auth/me");
    const data = await readJsonResponse(response);
    state.account = data.identity;
    renderAccountState(data.identity);
    renderRateLimit(data.rate_limit);
  } catch (error) {
    setStatus(error.message, "error");
  }
}

async function openAuthModal(mode) {
  state.authMode = mode;
  state.signupPendingId = null;
  els.authTitle.textContent = mode === "signup" ? "Sign up" : "Log in";
  els.authSubmitButton.textContent = mode === "signup" ? "Sign up" : "Log in";
  els.authStatus.textContent = "";
  els.authUsername.value = "";
  els.authEmail.value = "";
  els.authPassword.value = "";
  els.authPasswordConfirm.value = "";
  els.authWebsite.value = "";
  els.emailVerificationCode.value = "";
  renderAuthStage(mode);
  els.authModal.hidden = false;
}

async function submitAuthForm(event) {
  event.preventDefault();
  els.authSubmitButton.disabled = true;
  els.authStatus.textContent = "Working...";
  try {
    if (state.authMode === "signup") await startSignup();
    else if (state.authMode === "signup-verify") await verifySignupEmail();
    else await startLogin();
  } catch (error) {
    els.authStatus.textContent = error.message;
    els.authStatus.className = "state-text error";
  } finally {
    els.authSubmitButton.disabled = false;
  }
}

function renderAuthStage(stage) {
  state.authMode = stage;
  const signup = stage === "signup";
  els.authCredentialsFields.hidden = stage === "signup-verify";
  els.emailVerificationFields.hidden = stage !== "signup-verify";
  document.querySelectorAll(".signup-only").forEach((node) => { node.hidden = !signup; });
}

async function startSignup() {
  const password = els.authPassword.value;
  if (password !== els.authPasswordConfirm.value) throw new Error("Passwords do not match.");
  const response = await fetch("/auth/signup/start", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      email: els.authEmail.value,
      username: els.authUsername.value,
      password,
      website: els.authWebsite.value,
    }),
  });
  const data = await readJsonResponse(response);
  state.signupPendingId = data.pending_id;
  renderAuthStage("signup-verify");
  els.authStatus.textContent = "Verification code sent.";
}

async function verifySignupEmail() {
  const response = await fetch("/auth/signup/verify-email", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ pending_id: state.signupPendingId, code: els.emailVerificationCode.value }),
  });
  await readJsonResponse(response);
  const complete = await fetch("/auth/signup/complete", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ pending_id: state.signupPendingId }),
  });
  const data = await readJsonResponse(complete);
  els.authModal.hidden = true;
  renderAccountState(data.user);
  renderRateLimit(data.rate_limit);
  await loadRecentSessions();
}

async function startLogin() {
  const response = await fetch("/auth/login", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ email: els.authEmail.value, password: els.authPassword.value }),
  });
  const data = await readJsonResponse(response);
  els.authModal.hidden = true;
  renderAccountState(data.user);
  renderRateLimit(data.rate_limit);
  await loadRecentSessions();
}

async function logout() {
  try {
    const response = await fetch("/auth/logout", { method: "POST" });
    await readJsonResponse(response);
    await loadAccountState();
    await loadRecentSessions();
  } catch (error) {
    setStatus(error.message, "error");
  }
}

async function openAccountModal() {
  if (!state.account?.authenticated) {
    await openAuthModal("login");
    return;
  }
  try {
    const response = await fetch("/account");
    const data = await readJsonResponse(response);
    const account = data.account;
    els.accountPanelUsername.textContent = account.username || "Account";
    els.accountEmail.textContent = account.email || "";
    els.accountTierValue.textContent = account.tier || "";
    els.accountTierChip.textContent = String(account.tier || "free").toUpperCase();
    els.accountTierChip.className = `account-chip tier-${account.tier_color || "gray"}`;
    els.accountUsage.textContent = account.usage?.summary || "";
    els.accountStatusMessage.textContent = "";
    els.accountModal.hidden = false;
  } catch (error) {
    setStatus(error.message, "error");
  }
}

function renderAccountState(identity) {
  state.account = identity;
  els.accountName.textContent = identity?.username || "Guest";
  els.accountStatus.className = `account-status tier-${identity?.tier_color || "gray"}`;
  els.loginButton.hidden = Boolean(identity?.authenticated);
  els.signupButton.hidden = Boolean(identity?.authenticated);
  els.logoutButton.hidden = !identity?.authenticated;
}

function renderRateLimit(rateLimit) {
  if (!rateLimit) return;
  if (rateLimit.unlimited) {
    els.uploadLimitStatus.textContent = "Fact-check runs: unlimited";
  } else {
    els.uploadLimitStatus.textContent = `${rateLimit.remaining}/${rateLimit.limit} fact-check runs remaining this hour`;
  }
}

function setProgress(step) {
  els.emptyOutput.hidden = true;
  els.resultShell.hidden = false;
  els.chatMessages.hidden = false;
  els.debugDetails.hidden = true;
  els.gemmaRate.textContent = "";
  els.pipelineTime.textContent = "Pipeline time: running";
  renderPipelineProgress(state.mode, step);
}

function progressOrder(step) {
  return state.progressStepIds.indexOf(step);
}

function startPipelineProgress(mode) {
  stopPipelineProgress();
  stopRenderProgress();
  state.progressStepIndex = 0;
  state.currentStreamStep = null;
  state.liveTokenText = "";
  els.chatMessages.innerHTML = "";
  renderPipelineProgress(mode);
  const firstStep = state.progressStepIds[0] || "preparing_input";
  setProgress(firstStep);
}

function stopPipelineProgress() {
  if (state.progressTimer) window.clearInterval(state.progressTimer);
  state.progressTimer = null;
}

function renderPipelineProgress(mode, activeStep = state.progressStepIds[state.progressStepIndex] || "preparing_input") {
  const steps = PIPELINE_STEPS.filter((step) => !step.modes || step.modes.includes(mode));
  state.progressStepIds = steps.map((step) => step.id);
  const activeOrder = Math.max(progressOrder(activeStep), 0);
  const active = steps[activeOrder] || steps[0];
  if (active) renderLiveStreamView(active, "is-active");
  else els.chatMessages.innerHTML = "";
}

function clearInput() {
  state.activeSessionId = null;
  els.textInput.value = "";
  els.urlInput.value = "";
  clearPendingFile();
  clearResult();
  setStatus("");
}

function clearPendingFile() {
  if (state.pendingPreviewUrl) URL.revokeObjectURL(state.pendingPreviewUrl);
  state.pendingFile = null;
  state.pendingPreviewUrl = null;
  els.selectedFilePreview.hidden = true;
  els.selectedFilePreview.innerHTML = "";
  els.dropTitle.textContent = "Upload or paste a screenshot";
}

function clearResult() {
  stopRenderProgress();
  els.resultShell.hidden = false;
  els.chatMessages.hidden = true;
  els.chatMessages.innerHTML = "";
  state.lastOutputText = "";
  state.currentStreamStep = null;
  state.liveTokenText = "";
  els.debugDetails.hidden = true;
  els.debugPayload.textContent = "";
  els.pipelineTime.textContent = "Ready";
  els.gemmaRate.textContent = "";
  els.emptyOutput.hidden = false;
}

function setControlsBusy(isBusy) {
  els.checkButton.disabled = isBusy;
  els.clearButton.disabled = isBusy;
  els.uploadButton.disabled = isBusy;
  els.modeTabs.forEach((button) => { button.disabled = isBusy; });
}

function updateSelectionControls() {
  const count = state.selectedSessionIds.size;
  els.selectionSummary.textContent = `${count} selected`;
  els.deleteSelectedButton.disabled = count === 0;
}

function setStatus(message, tone = "") {
  els.uploadState.textContent = message || "";
  els.uploadState.className = `state-text ${tone}`.trim();
}

function setAccountStatus(message) {
  els.accountStatusMessage.textContent = message;
}

async function readJsonResponse(response) {
  const text = await response.text();
  let data = {};
  if (text) {
    try {
      data = JSON.parse(text);
    } catch {
      data = { detail: text };
    }
  }
  if (!response.ok) throw new Error(data.detail || `Request failed with HTTP ${response.status}`);
  return data;
}

async function readSseResponse(response, onEvent) {
  if (!response.ok) {
    const data = await response.text();
    throw new Error(data || `Request failed with HTTP ${response.status}`);
  }
  if (!response.body) {
    throw new Error("Streaming response is not available in this browser.");
  }
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  while (true) {
    const { value, done } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    const frames = buffer.split(/\r?\n\r?\n/);
    buffer = frames.pop() || "";
    for (const frame of frames) {
      await handleSseFrame(frame, onEvent);
    }
  }
  buffer += decoder.decode();
  if (buffer.trim()) await handleSseFrame(buffer, onEvent);
}

async function handleSseFrame(frame, onEvent) {
  const event = parseSseFrame(frame);
  if (!event) return;
  if (event.name === "error") {
    onEvent(event.name, event.data);
    throw new Error(event.data.detail || "Fact-check stream failed.");
  }
  onEvent(event.name, event.data);
}

function parseSseFrame(frame) {
  let name = "message";
  const dataLines = [];
  frame.split(/\r?\n/).forEach((line) => {
    if (line.startsWith("event:")) name = line.slice(6).trim() || "message";
    else if (line.startsWith("data:")) dataLines.push(line.slice(5).trimStart());
  });
  if (!dataLines.length) return null;
  let data = {};
  try {
    data = JSON.parse(dataLines.join("\n"));
  } catch {
    data = {};
  }
  return { name, data };
}

function validateImage(file) {
  const allowed = ["image/png", "image/jpeg"];
  if (!allowed.includes(file.type)) return "Only PNG, JPG, and JPEG screenshots are supported.";
  return "";
}

function evidenceSummary(evidence) {
  if (!evidence.length) return "No evidence returned.";
  const sources = evidence.map((item) => item.source_type || item.source_id || "evidence");
  return [...new Set(sources)].join(", ");
}

function formatConfidence(value) {
  return Number.isFinite(value) ? `${Math.round(value * 100)}%` : "Not reported";
}

function formatDate(value) {
  if (!value) return "";
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString();
}

function formatDuration(ms) {
  if (ms < 1000) return `${Math.round(ms)} ms`;
  return `${(ms / 1000).toFixed(1)} s`;
}

function truncateText(value, maxChars) {
  const text = String(value || "");
  if (text.length <= maxChars) return text;
  return `${text.slice(0, Math.max(maxChars - 1, 0)).trimEnd()}…`;
}

function humanizeStage(value) {
  return String(value || "Pipeline event")
    .replace(/_/g, " ")
    .replace(/\b\w/g, (letter) => letter.toUpperCase());
}

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function on(element, eventName, handler) {
  if (element) element.addEventListener(eventName, handler);
}
