const state = {
  mode: "text",
  activeSessionId: null,
  pendingFile: null,
  pendingPreviewUrl: null,
  isBusy: false,
  selectedSessionIds: new Set(),
  recentSessionIds: [],
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
  progressList: document.querySelector("#progressList"),
  emptyOutput: document.querySelector("#emptyOutput"),
  resultShell: document.querySelector("#resultShell"),
  overallVerdict: document.querySelector("#overallVerdict"),
  claimsList: document.querySelector("#claimsList"),
  claimVerdicts: document.querySelector("#claimVerdicts"),
  summaryText: document.querySelector("#summaryText"),
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
  setProgress("preprocessing");
  setStatus("Preparing input...");
  clearResult();

  try {
    const response = await postCurrentInput();
    const session = await readJsonResponse(response);
    state.activeSessionId = session.id;
    renderSession(session);
    renderRateLimit(session.rate_limit);
    setStatus("Fact-check complete.", "success");
    await loadRecentSessions();
  } catch (error) {
    setStatus(error.message, "error");
    els.progressList.hidden = true;
    els.emptyOutput.hidden = false;
  } finally {
    state.isBusy = false;
    setControlsBusy(false);
  }
}

async function postCurrentInput() {
  if (state.mode === "text") {
    const text = els.textInput.value.trim();
    if (!text) {
      els.textInput.focus();
      throw new Error("Text input cannot be empty.");
    }
    setProgress("extracting_claims");
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
    setProgress("retrieving_evidence");
    return fetch("/sessions/check", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ input_type: "url", url, session_id: state.activeSessionId }),
    });
  }
  if (!state.pendingFile) {
    throw new Error("Choose or paste a screenshot first.");
  }
  setProgress("extracting_claims");
  const body = new FormData();
  body.append("image", state.pendingFile);
  const query = state.activeSessionId ? `?session_id=${encodeURIComponent(state.activeSessionId)}` : "";
  return fetch(`/sessions/check-image${query}`, { method: "POST", body });
}

function renderSession(session) {
  const result = session.fact_check_result;
  if (!result) {
    clearResult();
    return;
  }
  els.emptyOutput.hidden = true;
  els.progressList.hidden = true;
  els.resultShell.hidden = false;
  const verdict = String(result.verdict || "NOT_ENOUGH_INFO");
  els.overallVerdict.textContent = verdict;
  els.overallVerdict.className = `verdict-pill verdict-${verdict.toLowerCase()}`;
  const claims = Array.isArray(result.claims) ? result.claims : [];
  els.claimsList.innerHTML = claims.length
    ? claims.map((item, index) => renderClaimSummary(item, index)).join("")
    : `<div class="empty-list">No checkable claims were extracted.</div>`;
  els.claimVerdicts.innerHTML = claims.length
    ? claims.map(renderClaimVerdict).join("")
    : `<div class="empty-list">No claim verdicts available.</div>`;
  els.summaryText.textContent = result.summary || "No final explanation was returned.";
  els.debugPayload.textContent = JSON.stringify(debugPayload(result), null, 2);
}

function renderClaimSummary(item, index) {
  const claim = item.claim || {};
  return `
    <div class="claim-row">
      <span>${escapeHtml(claim.claim_id || `c${String(index + 1).padStart(3, "0")}`)}</span>
      <p>${escapeHtml(claim.text || "")}</p>
    </div>
  `;
}

function renderClaimVerdict(item) {
  const claim = item.claim || {};
  const evidence = Array.isArray(item.evidence) ? item.evidence : [];
  return `
    <article class="claim-card">
      <div class="claim-card-head">
        <strong>${escapeHtml(claim.text || "Claim")}</strong>
        <span class="mini-verdict">${escapeHtml(item.verdict || "NOT_ENOUGH_INFO")}</span>
      </div>
      <dl>
        <div><dt>Type</dt><dd>${escapeHtml(claim.claim_type || claim.verification_stream || "unknown")}</dd></div>
        <div><dt>Confidence</dt><dd>${formatConfidence(item.confidence)}</dd></div>
        <div><dt>Evidence</dt><dd>${escapeHtml(evidenceSummary(evidence))}</dd></div>
      </dl>
      <p>${escapeHtml(item.rationale || "No claim explanation was returned.")}</p>
    </article>
  `;
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
  return `
    <article class="session-item${selectionClass}" data-session-id="${escapeHtml(session.id)}">
      <input class="session-check" type="checkbox" data-select-session="${escapeHtml(session.id)}" ${selected ? "checked" : ""} ${els.cancelSelectionButton.hidden ? "hidden" : ""} />
      <div class="session-main">
        <div class="session-title-row">
          <strong>${escapeHtml(session.filename || "F1 fact-check")}</strong>
          <span class="mini-verdict">${escapeHtml(session.overall_verdict || session.status || "pending")}</span>
        </div>
        <p>${escapeHtml(session.input_preview || "")}</p>
        <span>${escapeHtml(session.input_type || "check")} · ${formatDate(session.updated_at)}</span>
      </div>
      <button class="icon-button session-delete" type="button" data-delete-session="${escapeHtml(session.id)}" aria-label="Delete session" title="Delete">
        <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M6 7h12" /><path d="M10 11v6M14 11v6" /><path d="M9 7l1-2h4l1 2" /><path d="M8 7l1 14h6l1-14" /></svg>
      </button>
    </article>
  `;
}

async function openSession(sessionId) {
  try {
    const response = await fetch(`/sessions/${encodeURIComponent(sessionId)}`);
    const data = await readJsonResponse(response);
    state.activeSessionId = data.id;
    renderSession(data);
    setStatus("Loaded fact-check run.");
  } catch (error) {
    setStatus(error.message, "error");
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
  els.resultShell.hidden = true;
  els.progressList.hidden = false;
  els.progressList.querySelectorAll("[data-step]").forEach((item) => {
    item.classList.toggle("is-active", item.dataset.step === step);
    item.classList.toggle("is-done", progressOrder(item.dataset.step) < progressOrder(step));
  });
}

function progressOrder(step) {
  return ["preprocessing", "extracting_claims", "retrieving_evidence", "generating_verdict"].indexOf(step);
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
  els.progressList.hidden = true;
  els.resultShell.hidden = true;
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
