"use strict";

import { apiUrl } from "./api-url.js";
import { initWallet } from "./wallet.js";
import { checkFileReadable } from "./file-readability.js";
import { createActionTiming } from "./performance.js";
import { recoverService } from "./service-recovery.js";

const MAX_UPLOAD_BYTES = 200 * 1024 * 1024;
const MAX_IMAGE_BYTES = 20 * 1024 * 1024;
const REQUEST_TIMEOUT_MS = 15000;
const UPLOAD_TIMEOUT_MS = 10 * 60 * 1000;
const STEP_LABELS = {
  video: ["Uploading…", "Reading video structure…", "Analyzing scenes…", "Preparing results…"],
  image: ["Uploading…", "Analyzing image…", "Preparing prompt…", "Preparing results…"],
  enhance: ["Preparing Orb…", "Enhancing prompt…", "Reviewing response…", "Preparing results…"],
};
const STEP_IDS = ["uploading", "structure", "scenes", "results"];
const ACTIVE_JOB_KEY = "orb-active-paid-job";

const screens = {
  home: document.getElementById("screen-home"),
  processing: document.getElementById("screen-processing"),
  results: document.getElementById("screen-results"),
};

const els = {
  fileInput: document.getElementById("file-input"),
  chooseFileBtn: document.getElementById("choose-file-btn"),
  uploadShell: document.getElementById("upload-shell"),
  dropzone: document.getElementById("dropzone"),
  fileCard: document.getElementById("file-card"),
  fileName: document.getElementById("file-name"),
  fileMeta: document.getElementById("file-meta"),
  fileCheckStatus: document.getElementById("file-check-status"),
  fileClear: document.getElementById("file-clear"),
  serviceStatus: document.getElementById("service-status"),
  enhanceStatus: document.getElementById("enhance-status"),
  decodeBtn: document.getElementById("decode-btn"),
  fileKicker: document.getElementById("file-kicker"),
  modeDecode: document.getElementById("mode-decode"),
  modeCompose: document.getElementById("mode-compose"),
  modeEnhance: document.getElementById("mode-enhance"),
  createInfo: document.getElementById("create-info"),
  createPopover: document.getElementById("create-popover"),
  createPopoverClose: document.getElementById("create-popover-close"),
  modeDescription: document.getElementById("mode-description"),
  enhanceShell: document.getElementById("enhance-shell"),
  promptInput: document.getElementById("prompt-input"),
  enhanceOutput: document.getElementById("enhance-output"),
  enhanceStyle: document.getElementById("enhance-style"),
  enhanceDetail: document.getElementById("enhance-detail"),
  enhanceBtn: document.getElementById("enhance-btn"),
  enhanceError: document.getElementById("enhance-error"),
  uploadError: document.getElementById("upload-error"),
  phaseText: document.getElementById("phase-text"),
  phaseDetail: document.getElementById("phase-detail"),
  uploadBar: document.getElementById("upload-bar"),
  uploadProgress: document.querySelector(".progress"),
  stepList: document.getElementById("step-list"),
  jobError: document.getElementById("job-error"),
  backBtn: document.getElementById("back-btn"),
  resTitle: document.getElementById("res-title"),
  resChips: document.getElementById("res-chips"),
  resVideo: document.getElementById("res-video"),
  resImage: document.getElementById("res-image"),
  resPreviewCard: document.getElementById("res-preview-card"),
  resAnalysisCard: document.getElementById("res-analysis-card"),
  resAnalysis: document.getElementById("res-analysis"),
  resOpencvCard: document.getElementById("res-opencv-card"),
  resOpencvBadges: document.getElementById("res-opencv-badges"),
  resOpencvActionsWrap: document.getElementById("res-opencv-actions-wrap"),
  resOpencvActions: document.getElementById("res-opencv-actions"),
  resOpencvClaheWrap: document.getElementById("res-opencv-clahe-wrap"),
  resOpencvClaheToggle: document.getElementById("res-opencv-clahe-toggle"),
  resOpencvClaheView: document.getElementById("res-opencv-clahe-view"),
  resOpencvClaheImg: document.getElementById("res-opencv-clahe-img"),
  resOpencvPaletteWrap: document.getElementById("res-opencv-palette-wrap"),
  resOpencvPalette: document.getElementById("res-opencv-palette"),
  resOpencvMetrics: document.getElementById("res-opencv-metrics"),
  resEyebrow: document.getElementById("res-eyebrow"),
  resMode: document.getElementById("res-mode"),
  resPromptHeading: document.getElementById("res-prompt-heading"),
  resNotice: document.getElementById("res-notice"),
  resOriginal: document.getElementById("res-original"),
  resOriginalText: document.getElementById("res-original-text"),
  resPrompt: document.getElementById("res-prompt"),
  copyPrompt: document.getElementById("copy-prompt"),
  copyStatus: document.getElementById("copy-status"),
  resRefinements: document.getElementById("res-refinements"),
  resSummary: document.getElementById("res-summary"),
  resScenes: document.getElementById("res-scenes"),
  againBtn: document.getElementById("again-btn"),
  menuToggle: document.getElementById("menu-toggle"),
  siteMenu: document.getElementById("site-menu"),
  menuHome: document.getElementById("menu-home"),
  menuAbout: document.getElementById("menu-about"),
  menuWallet: document.getElementById("menu-wallet"),
  aboutPanel: document.getElementById("about-panel"),
  aboutClose: document.getElementById("about-close"),
};

const decodeLabel = els.decodeBtn.querySelector("span");
const decodeDetail = els.decodeBtn.querySelector("small");

let selectedFile = null;
let fileCheckController = null;
let currentMode = "decode";
let activeMediaKind = null;
let serviceReady = false;
let serviceTask = null;
let actionBusy = false;
let pollTimer = null;
let pollFailures = 0;
let currentJobId = null;
let pollPausedForAuth = false;
let visualAttemptKey = null;
let enhanceAttemptKey = null;
let creditMode = "local";
let wallet = null;
let privateMediaUrls = [];
let actionTiming = null;
function finishActionTiming(status) {
  actionTiming?.finish(status);
  actionTiming = null;
}
wallet = initWallet({ onBalance: (balance) => {
  // Presentation only: the existing authenticated wallet remains authoritative.
  document.getElementById("header-credit-value").textContent = String(balance);
  document.getElementById("header-credits").classList.toggle("hidden", !wallet?.isAuthenticated());
  syncDecodeButton();
  resumePaidJob();
} });

function rememberPaidJob(jobId) {
  if (creditMode === "credits" && wallet.walletAddress()) {
    sessionStorage.setItem(ACTIVE_JOB_KEY, JSON.stringify({ jobId, wallet: wallet.walletAddress(),
      mode: currentMode, mediaKind: activeMediaKind }));
  }
}

function forgetPaidJob() { sessionStorage.removeItem(ACTIVE_JOB_KEY); }

function resumePaidJob() {
  if (creditMode !== "credits" || !wallet?.isAuthenticated() || actionBusy
      || (currentJobId && !pollPausedForAuth)) return;
  try {
    const saved = JSON.parse(sessionStorage.getItem(ACTIVE_JOB_KEY) || "null");
    if (saved?.wallet?.toLowerCase() === wallet.walletAddress()?.toLowerCase()
        && /^[a-f0-9]{32}$/.test(saved.jobId)
        && (!currentJobId || currentJobId === saved.jobId)) {
      if (["decode", "compose", "enhance"].includes(saved.mode)) currentMode = saved.mode;
      if (["image", "video"].includes(saved.mediaKind)) activeMediaKind = saved.mediaKind;
      currentJobId = saved.jobId;
      actionBusy = true;
      startPolling(currentJobId);
    } else if (pollPausedForAuth && currentJobId) {
      showError(els.jobError, "Sign in with the wallet that started this analysis to continue.");
    }
  } catch { forgetPaidJob(); }
}

function showScreen(name) {
  setMenuOpen(false);
  setAboutOpen(false);
  wallet.close();
  setCreateInfoOpen(false);
  for (const key of Object.keys(screens)) {
    screens[key].classList.toggle("hidden", key !== name);
  }
  window.scrollTo(0, 0);
  screens[name].focus({ preventScroll: true });
}

function setMenuOpen(open) {
  if (open) setAboutOpen(false);
  if (open) wallet.close();
  if (open) setCreateInfoOpen(false);
  els.siteMenu.classList.toggle("hidden", !open);
  els.menuToggle.setAttribute("aria-expanded", String(open));
  els.menuToggle.setAttribute("aria-label", open ? "Close menu" : "Open menu");
}

function setAboutOpen(open, restoreFocus = false) {
  if (open) setCreateInfoOpen(false);
  els.aboutPanel.classList.toggle("hidden", !open);
  if (open) els.aboutClose.focus();
  else if (restoreFocus) els.menuToggle.focus();
}

function setCreateInfoOpen(open, restoreFocus = false) {
  const focusWasInside = els.createPopover.contains(document.activeElement);
  els.createPopover.classList.toggle("hidden", !open);
  els.createInfo.setAttribute("aria-expanded", String(open));
  if (open) els.createPopoverClose.focus();
  else if (restoreFocus || focusWasInside) els.createInfo.focus();
}

function showError(box, message) {
  box.textContent = message;
  box.classList.remove("hidden");
}

function cleanServiceError(message, fallback = "Orb AI is temporarily unavailable. Try again.") {
  if (typeof message !== "string" || !message.trim()) return fallback;
  if (/insufficient credit|credit required|no credits/i.test(message)) return "A testnet credit is needed. Open Wallet & Credits to continue.";
  if (/session expired|authentication required|unauthorized/i.test(message)) return "Session expired — sign again to continue.";
  if (/unsupported|file format|file too large|upload limit/i.test(message)) return "Unsupported upload. Use JPEG, PNG, WebP, MP4, MOV, M4V, or WebM within the stated size limit.";
  if (/prompt.*(?:too long|empty|invalid)/i.test(message)) return "Check your prompt and try again.";
  return fallback;
}

async function fetchWithTimeout(url, options = {}, timeout = REQUEST_TIMEOUT_MS) {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeout);
  try {
    return await fetch(url, { ...options, signal: controller.signal });
  } finally {
    clearTimeout(timer);
  }
}

function createUploadAttemptId() {
  if (globalThis.crypto?.randomUUID) return globalThis.crypto.randomUUID();
  return `orb-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 12)}`;
}

function uploadAttemptUrl(endpoint, attemptId) {
  const separator = endpoint.includes("?") ? "&" : "?";
  return apiUrl(`${endpoint}${separator}upload_attempt_id=${encodeURIComponent(attemptId)}`);
}

function setServiceState(ready) {
  serviceReady = ready;
  els.decodeBtn.classList.toggle("initializing", !ready);
  decodeLabel.textContent = ready ? (currentMode === "compose" ? "Compose prompt" : "Decode reference") : "Preparing Orb…";
  decodeDetail.textContent = ready ? "Analyze with Orb AI" : "One moment";
  syncDecodeButton();
}

function syncEnhanceStatus() {
  els.enhanceStatus.textContent = els.serviceStatus.textContent;
  els.enhanceStatus.className = els.serviceStatus.className;
}

function syncDecodeButton() {
  const needsCredits = creditMode === "credits" && !wallet?.hasCredit();
  if (creditMode === "credits" && serviceReady) {
    els.serviceStatus.textContent = needsCredits
      ? "A testnet credit is needed. Use Connect Wallet in the header to get started."
      : wallet?.isJudgeDemo?.()
        ? "Orb service ready. Judge demo credit available."
        : "Orb service ready. Testnet credit available.";
    syncEnhanceStatus();
  }
  els.decodeBtn.disabled = !selectedFile || !serviceReady || actionBusy || needsCredits;
  els.enhanceBtn.disabled = els.promptInput.value.trim().length < 3 || !serviceReady || actionBusy || needsCredits;
  els.menuHome.disabled = actionBusy;
  for (const button of [els.modeDecode, els.modeCompose, els.modeEnhance]) button.disabled = actionBusy;
}

function setMode(mode) {
  if (actionBusy || !["decode", "compose", "enhance"].includes(mode)) return;
  setCreateInfoOpen(false);
  currentMode = mode;
  els.modeDescription.textContent = mode === "decode"
    ? "Reconstruct a plausible generation prompt from an image or video."
    : mode === "compose"
      ? "Create a new generation-ready prompt from a visual reference."
      : "Improve an existing image or video generation prompt. Orb does not generate media yet.";
  activeMediaKind = null;
  clearFile();
  els.uploadError.classList.add("hidden");
  els.enhanceError.classList.add("hidden");
  els.uploadShell.classList.toggle("hidden", mode === "enhance");
  els.enhanceShell.classList.toggle("hidden", mode !== "enhance");
  for (const name of ["decode", "compose", "enhance"]) {
    const button = els[`mode${name[0].toUpperCase()}${name.slice(1)}`];
    button.classList.toggle("active", name === mode);
    if (name === mode) button.setAttribute("aria-current", "page");
    else button.removeAttribute("aria-current");
  }
  els.fileKicker.textContent = mode === "compose" ? "Ready to compose" : "Ready to decode";
  setServiceState(serviceReady);
  syncEnhanceStatus();
}

/* ---------- Service readiness (health -> ready -> upload-path canary) ---------- */

async function pingUploadPath(signal) {
  const pingId = createUploadAttemptId();
  const form = new FormData();
  form.append(
    "file",
    new Blob(["orb-upload-ping"], { type: "application/octet-stream" }),
    "ping.bin",
  );
  const response = await fetch(
    apiUrl(`/api/upload-ping?upload_ping_id=${encodeURIComponent(pingId)}`),
    { method: "POST", body: form, signal },
  );
  if (response.status === 204) return "ok";
  if (response.status === 404 || response.status === 405) return "unsupported";
  return "fail";
}

async function waitForService() {
  if (serviceReady) return true;
  if (serviceTask) return serviceTask;
  const timing = createActionTiming("service_startup");

  serviceTask = (async () => {
    let configurationUnavailable = false;
    const recovered = await recoverService({
      probeHealth: async (signal) => {
        const health = await fetch(apiUrl("/api/health"), { signal });
        const healthBody = await health.json().catch(() => ({}));
        return health.ok && healthBody.status === "ok" ? healthBody : null;
      },
      onHealth: (healthBody) => {
        creditMode = healthBody.orb_ai_access || "local";
        syncDecodeButton();
        resumePaidJob();
        if (healthBody.orb_ai_access === "configuration_required" || healthBody.orb_ai_access === "credits_unavailable") {
          configurationUnavailable = true;
          setServiceState(false);
          els.serviceStatus.textContent = healthBody.orb_ai_access === "configuration_required"
            ? "Orb AI is temporarily unavailable. Try again."
            : "Testnet credits are temporarily unavailable. Try again.";
          els.serviceStatus.classList.add("failed");
          syncEnhanceStatus();
          return false;
        }
      },
      verifyReadiness: async (request) => {
        const ready = await request(async (signal) => {
          const response = await fetch(apiUrl("/api/ready"), { signal });
          const body = await response.json().catch(() => ({}));
          return response.ok && body.status === "ready";
        });
        if (ready) {
          const ping = await request(pingUploadPath);
          if (ping === "ok" || ping === "unsupported") return true;
          els.serviceStatus.textContent = "Preparing Orb…";
        }
        return false;
      },
    });
    if (recovered) {
      els.serviceStatus.textContent = creditMode === "credits" && !wallet.hasCredit()
        ? "A testnet credit is needed. Use Connect Wallet in the header to get started."
        : "Orb service ready.";
      els.serviceStatus.classList.add("ready");
      els.serviceStatus.classList.remove("failed");
      syncEnhanceStatus();
      setServiceState(true);
      return true;
    }
    // Keep the explicit configuration-required states selected by onHealth.
    if (configurationUnavailable) return false;
    setServiceState(false);
    els.serviceStatus.textContent = "Orb is taking longer to start. Try again shortly.";
    els.serviceStatus.classList.add("failed");
    syncEnhanceStatus();
    return false;
  })();

  try {
    const ready = await serviceTask;
    timing?.mark("readiness_complete");
    timing?.finish(ready ? "complete" : "error");
    return ready;
  } finally {
    serviceTask = null;
  }
}

async function isServiceReady() {
  if (!serviceReady) return false;
  try {
    const ready = await fetchWithTimeout(apiUrl("/api/ready"));
    const body = await ready.json().catch(() => ({}));
    if (ready.ok && body.status === "ready") return true;
  } catch (error) {
    // Only decides whether a new upload may begin.
  }
  setServiceState(false);
  void waitForService();
  return false;
}

/* ---------- File selection ---------- */

function setFile(file) {
  if (!file || actionBusy) return;
  if (selectedFile) clearFile();
  const image = /\.(png|jpe?g|webp)$/i.test(file.name);
  const video = /\.(mp4|m4v|mov|webm)$/i.test(file.name);
  if (!image && !video) {
    showError(els.uploadError, "Unsupported file type. Choose a JPEG, PNG, WebP, MP4, MOV, M4V, or WebM file.");
    return;
  }
  if (file.size === 0) {
    showError(els.uploadError, "That file is empty. Choose a different file.");
    return;
  }
  if (file.size > (image ? MAX_IMAGE_BYTES : MAX_UPLOAD_BYTES)) {
    showError(els.uploadError, `That file exceeds the ${image ? 20 : 200} MB limit. Choose a smaller file.`);
    return;
  }
  selectedFile = file;
  els.uploadError.classList.add("hidden");
  els.uploadShell.classList.add("has-file");
  els.dropzone.classList.add("hidden");
  els.fileCard.classList.remove("hidden");
  els.fileName.textContent = file.name;
  els.fileMeta.textContent = `${(file.size / 1024 / 1024).toFixed(1)} MB`;
  syncDecodeButton();
}

function clearFile() {
  if (fileCheckController) {
    finishActionTiming("cancelled");
    fileCheckController.abort();
    fileCheckController = null;
    actionBusy = false;
    setFileChecking(false);
  }
  selectedFile = null;
  visualAttemptKey = null;
  els.fileInput.value = "";
  els.uploadShell.classList.remove("has-file");
  els.fileCard.classList.add("hidden");
  els.dropzone.classList.remove("hidden");
  syncDecodeButton();
}

/* ---------- Visual AI flow ---------- */

function setFileChecking(checking) {
  els.fileCheckStatus.textContent = checking ? "Checking file…" : "";
  els.fileCheckStatus.classList.toggle("hidden", !checking);
  els.fileCard.setAttribute("aria-busy", String(checking));
}

function showFileReadFailure(kind) {
  const title = document.createElement("strong");
  title.textContent = `Couldn't access this ${kind}`;
  const body = document.createElement("p");
  body.textContent = `Your device didn't make the selected ${kind} available to Orb. Choose it again using Files or Browse.`;
  els.uploadError.replaceChildren(title, body);
  els.uploadError.classList.remove("hidden");
}

function mapStage(stage) {
  if (!stage || stage === "Queued") return { step: "uploading", label: "Preparing Orb…", detail: "Your request is in line." };
  if (stage === "Inspecting video") return { step: "structure", label: "Reading video structure…", detail: "Looking at the reference." };
  if (stage === "Analyzing image" || stage === "Analyzing visual reference") return { step: "structure", label: "Analyzing image…", detail: "Finding the visual details." };
  if (stage === "Enhancing prompt") return { step: "structure", label: "Enhancing prompt…", detail: "Refining your creative direction." };
  if (stage === "Composing prompt") return { step: "scenes", label: "Creating prompt…", detail: "Building a new prompt from your reference." };
  if (stage === "Detecting scene cuts") return { step: "scenes", label: "Analyzing scenes…", detail: "Finding scene changes." };
  const sceneProgress = /^Analyzing scenes \((\d+)\/(\d+)\)$/.exec(stage)
    || /^Analyzing scene (\d+) of (\d+)$/.exec(stage);
  if (sceneProgress) return { step: "scenes", label: "Analyzing scenes…", detail: `Scene ${sceneProgress[1]} of ${sceneProgress[2]}` };
  if (stage === "Complete") return { step: "results", label: currentMode === "enhance" ? "Enhancing prompt…" : currentMode === "compose" ? "Creating prompt…" : "Reconstructing prompt…", detail: "Preparing your result." };
  return { step: "scenes", label: "Orb AI is processing…", detail: "Your prompt is taking shape." };
}

function processingSteps() {
  const labels = STEP_LABELS[currentMode === "enhance" ? "enhance" : activeMediaKind === "image" ? "image" : "video"];
  return STEP_IDS.map((id, index) => ({ id, label: labels[index] }));
}

function renderSteps(activeStep, uploadDone) {
  const steps = processingSteps();
  const order = steps.map((s) => s.id);
  const activeIndex = order.indexOf(activeStep);
  els.stepList.innerHTML = "";
  steps.forEach((step, index) => {
    const li = document.createElement("li");
    let state = "pending";
    if (index < activeIndex || (uploadDone && activeStep === "results")) state = "done";
    if (step.id === activeStep) state = "active";
    li.className = `step-state-${state}`;
    li.innerHTML = `<span class="dot"></span>${step.label}`;
    els.stepList.appendChild(li);
  });
}

async function startVisual() {
  if (!selectedFile || actionBusy || !serviceReady || (creditMode === "credits" && !wallet.hasCredit())) return;
  const file = selectedFile;
  const operation = currentMode;
  activeMediaKind = /\.(png|jpe?g|webp)$/i.test(file.name) ? "image" : "video";
  const mediaKind = activeMediaKind;
  finishActionTiming("cancelled");
  actionTiming = createActionTiming(`${operation}_${mediaKind}`);
  const controller = new AbortController();
  fileCheckController = controller;
  actionBusy = true;
  els.uploadError.classList.add("hidden");
  setFileChecking(true);
  syncDecodeButton();
  const attemptId = visualAttemptKey || createUploadAttemptId();
  visualAttemptKey = attemptId;
  try {
    await checkFileReadable(file, { signal: controller.signal });
  } catch (error) {
    if (fileCheckController !== controller || controller.signal.aborted) return;
    console.info(`upload_attempt=${attemptId} precheck=unreadable error=${error?.name || "UnknownError"}`);
    finishActionTiming("error");
    clearFile();
    showFileReadFailure(mediaKind);
    return;
  }
  // Cleared/replaced selections and late reads must never submit a request.
  if (fileCheckController !== controller || controller.signal.aborted || selectedFile !== file || currentMode !== operation) return;
  setFileChecking(false);
  actionTiming?.mark("readability_complete");
  if (!await isServiceReady()) {
    finishActionTiming("error");
    if (fileCheckController === controller) {
      fileCheckController = null;
      actionBusy = false;
      syncDecodeButton();
    }
    return;
  }
  if (fileCheckController !== controller || controller.signal.aborted || selectedFile !== file || currentMode !== operation) return;
  fileCheckController = null;
  actionTiming?.mark("readiness_complete");
  console.info(`upload_attempt=${attemptId} precheck=readable`);

  clearTimeout(pollTimer);
  currentJobId = null;
  els.uploadError.classList.add("hidden");
  els.decodeBtn.disabled = true;
  showScreen("processing");
  els.jobError.classList.add("hidden");
  els.backBtn.classList.add("hidden");
  els.uploadBar.style.width = "";
  els.uploadProgress.classList.add("is-indeterminate");
  els.uploadProgress.removeAttribute("aria-valuenow");
  renderSteps("uploading", false);
  els.phaseText.textContent = activeMediaKind === "video" ? "Uploading video…" : "Uploading image…";
  els.phaseDetail.textContent = "Sending your reference to Orb.";

  const fail = (message) => {
    finishActionTiming("error");
    actionBusy = false;
    els.uploadProgress.classList.remove("is-indeterminate");
    showError(els.jobError, message);
    els.backBtn.classList.remove("hidden");
    syncDecodeButton();
  };

  const form = new FormData();
  form.append("file", file);
  let response;
  actionTiming?.mark("upload_start");
  try {
    // The same-origin Vite proxy keeps the upload path and its canary intact.
    response = await fetchWithTimeout(
      uploadAttemptUrl(`/api/orb/${currentMode}/file`, attemptId),
      { method: "POST", body: form, headers: creditMode === "credits"
        ? { ...wallet.headers(), "X-Orb-Idempotency-Key": attemptId } : {} },
      UPLOAD_TIMEOUT_MS,
    );
  } catch (error) {
    const timedOut = error?.name === "AbortError";
    fail(
      timedOut
        ? `Upload timed out before Orb returned a response. No retry was made. Reference: ${attemptId}.`
        : `Upload connection was interrupted before Orb returned a response. No retry was made. Reference: ${attemptId}.`,
    );
    return;
  }

  els.uploadProgress.classList.remove("is-indeterminate");
  els.uploadBar.style.width = "100%";
  actionTiming?.mark("upload_returned");
  els.uploadProgress.setAttribute("aria-valuenow", "100");
  const data = await response.json().catch(() => ({}));
  if (!response.ok || !data.job_id) {
    fail(cleanServiceError(data.detail, `Could not start ${currentMode}. Try again.`));
    return;
  }
  currentJobId = data.job_id;
  actionTiming?.mark("job_available");
  rememberPaidJob(currentJobId);
  selectedFile = null;
  clearFile();
  startPolling(currentJobId);
}

async function startEnhance() {
  const prompt = els.promptInput.value.trim();
  if (currentMode !== "enhance" || prompt.length < 3 || !serviceReady || actionBusy
      || (creditMode === "credits" && !wallet.hasCredit())) return;
  finishActionTiming("cancelled");
  actionTiming = createActionTiming("enhance");
  actionBusy = true;
  activeMediaKind = null;
  syncDecodeButton();
  if (!await isServiceReady()) {
    finishActionTiming("error");
    actionBusy = false;
    syncDecodeButton();
    return;
  }
  els.enhanceError.classList.add("hidden");
  actionTiming?.mark("readiness_complete");
  showScreen("processing");
  els.jobError.classList.add("hidden");
  els.backBtn.classList.add("hidden");
  els.phaseText.textContent = "Enhancing prompt…";
  els.phaseDetail.textContent = "Refining your creative direction.";
  els.uploadProgress.classList.add("is-indeterminate");
  renderSteps("structure", true);
  enhanceAttemptKey ||= createUploadAttemptId();
  actionTiming?.mark("upload_start");
  try {
    const response = await fetchWithTimeout(apiUrl("/api/orb/enhance"), {
      method: "POST", headers: { "Content-Type": "application/json",
        ...(creditMode === "credits" ? { ...wallet.headers(), "X-Orb-Idempotency-Key": enhanceAttemptKey } : {}) },
      body: JSON.stringify({ prompt, output: els.enhanceOutput.value,
        style: els.enhanceStyle.value, detail: els.enhanceDetail.value }),
    }, UPLOAD_TIMEOUT_MS);
    actionTiming?.mark("upload_returned");
    const data = await response.json().catch(() => ({}));
    if (!response.ok || !data.job_id) throw new Error(data.detail || `request failed (${response.status})`);
    currentJobId = data.job_id;
    actionTiming?.mark("job_available");
    rememberPaidJob(currentJobId);
    startPolling(currentJobId);
  } catch (error) {
    finishActionTiming("error");
    actionBusy = false;
    showError(els.jobError, cleanServiceError(error.message, "Connection interrupted. Try again."));
    els.backBtn.classList.remove("hidden");
    syncDecodeButton();
  }
}

/* ---------- Job polling and results ---------- */

function startPolling(jobId) {
  clearTimeout(pollTimer);
  pollPausedForAuth = false;
  pollFailures = 0;
  showScreen("processing");
  els.jobError.classList.add("hidden");
  els.backBtn.classList.add("hidden");
  pollJob(jobId);
}

function schedulePoll(jobId, ms = 1500) {
  clearTimeout(pollTimer);
  const timing = actionTiming;
  const scheduledAt = timing ? performance.now() : 0;
  pollTimer = setTimeout(() => {
    timing?.add("poll_wait_ms", performance.now() - scheduledAt);
    pollJob(jobId);
  }, ms);
}

function pausePaidJobForAuthentication(jobId) {
  if (jobId !== currentJobId) return;
  clearTimeout(pollTimer);
  pollPausedForAuth = true;
  pollFailures = 0;
  actionBusy = false;
  showError(els.jobError, "Session expired — sign again to continue this analysis.");
  els.backBtn.classList.remove("hidden");
  wallet.requireAuthentication();
  syncDecodeButton();
}

async function pollJob(jobId) {
  if (jobId !== currentJobId) return;
  const timing = actionTiming;
  const pollStarted = timing ? performance.now() : 0;
  timing?.add("poll_requests");
  let job;
  try {
    const pollHeaders = creditMode === "credits" ? wallet.headers() : {};
    const response = await fetchWithTimeout(apiUrl(`/api/jobs/${jobId}`),
      { headers: pollHeaders });
    if (response.status === 401 && creditMode === "credits") {
      if (wallet.headers().Authorization && wallet.headers().Authorization !== pollHeaders.Authorization) {
        schedulePoll(jobId, 0);
      } else {
        pausePaidJobForAuthentication(jobId);
      }
      return;
    }
    if (response.status === 404 || response.status === 410) {
      discardJob();
      return;
    }
    if (!response.ok) throw new Error(`Server returned ${response.status}.`);
    job = await response.json();
  } catch (error) {
    if (jobId !== currentJobId) return;
    pollFailures += 1;
    if (pollFailures < 3 && currentJobId === jobId) {
      schedulePoll(jobId, 1500 * pollFailures);
      return;
    }
    showError(els.jobError, "Connection interrupted. Try again. Your analysis is still saved.");
    els.backBtn.classList.remove("hidden");
    actionBusy = false;
    if (creditMode === "credits") void wallet.refresh();
    syncDecodeButton();
    return;
  } finally {
    timing?.add("poll_request_ms", performance.now() - pollStarted);
  }
  if (jobId !== currentJobId) return;
  pollFailures = 0;
  const mapped = mapStage(job.stage || "");
  els.phaseText.textContent = mapped.label;
  els.phaseDetail.textContent = mapped.detail;
  renderSteps(mapped.step, true);
  if (job.state === "complete") {
    actionTiming?.mark("result_detected");
    clearTimeout(pollTimer);
    fetchResult(jobId);
  } else if (job.state === "error") {
    finishActionTiming("error");
    clearTimeout(pollTimer);
    forgetPaidJob();
    visualAttemptKey = null;
    enhanceAttemptKey = null;
    showError(els.jobError, `Analysis failed: ${cleanServiceError(job.error)}`);
    currentJobId = null;
    els.backBtn.classList.remove("hidden");
    actionBusy = false;
    if (creditMode === "credits") void wallet.refresh();
    syncDecodeButton();
  } else {
    schedulePoll(jobId);
  }
}

function discardJob() {
  finishActionTiming("error");
  clearTimeout(pollTimer);
  forgetPaidJob();
  currentJobId = null;
  actionBusy = false;
  clearFile();
  showScreen("home");
  showError(els.uploadError, "This analysis is no longer available on the server.");
}

async function fetchResult(jobId) {
  try {
    const resultHeaders = creditMode === "credits" ? wallet.headers() : {};
    const response = await fetchWithTimeout(apiUrl(`/api/jobs/${jobId}/result`),
      { headers: resultHeaders });
    if (response.status === 401 && creditMode === "credits") {
      if (wallet.headers().Authorization && wallet.headers().Authorization !== resultHeaders.Authorization) {
        schedulePoll(jobId, 0);
      } else {
        pausePaidJobForAuthentication(jobId);
      }
      return;
    }
    const result = await response.json();
    if (!response.ok) throw new Error(result.detail || `status ${response.status}`);
    if (jobId !== currentJobId) return;
    actionTiming?.mark("result_received");
    renderResult(result);
    actionTiming?.mark("result_displayed");
    finishActionTiming("complete");
    if (creditMode === "credits") void wallet.refresh();
  } catch (error) {
    if (jobId !== currentJobId) return;
    showError(els.jobError, cleanServiceError(error.message, "Could not load results. Try again."));
    els.backBtn.classList.remove("hidden");
    actionBusy = false;
    syncDecodeButton();
  }
}

function fmtTime(seconds) {
  return `${Number(seconds).toFixed(1)}s`;
}

export function renderResult(result) {
  forgetPaidJob();
  for (const url of privateMediaUrls) URL.revokeObjectURL(url);
  privateMediaUrls = [];
  actionBusy = false;
  syncDecodeButton();
  const video = result.video || {};
  const image = result.image || {};
  const media = result.image || result.video || {};
  const operation = result.operation || currentMode;
  els.resTitle.textContent = media.name || (operation === "enhance" ? "Enhanced prompt" : "Visual reference");
  els.resEyebrow.textContent = operation === "decode" ? "Decoded reference" : operation === "compose" ? "Composed from reference" : "Enhanced prompt";
  els.resMode.textContent = operation === "decode"
    ? "Orb AI · plausible reconstruction, not the creator’s exact prompt"
    : operation === "compose" ? "Orb AI · a new prompt inspired by your reference"
      : "Orb AI · improved prompt, ready for image or video creation";
  els.resChips.innerHTML = "";
  const chips = [
    media.width && media.height ? `${media.width}×${media.height}` : null,
    video.duration ? `${video.duration.toFixed(1)}s` : null,
    video.fps ? `${video.fps} fps` : null,
    result.scenes ? `${result.scenes.length} scenes` : null,
  ].filter(Boolean);
  for (const chip of chips) {
    const span = document.createElement("span");
    span.className = "chip";
    span.textContent = chip;
    els.resChips.appendChild(span);
  }

  els.resPreviewCard.classList.toggle("hidden", !media.preview_url);
  if (video.preview_url) {
    if (creditMode !== "credits") els.resVideo.src = apiUrl(video.preview_url);
    els.resVideo.classList.remove("hidden");
  }
  else { els.resVideo.removeAttribute("src"); els.resVideo.classList.add("hidden"); }
  if (image.preview_url) { if (creditMode !== "credits") els.resImage.src = apiUrl(image.preview_url); els.resImage.classList.remove("hidden"); }
  else { els.resImage.removeAttribute("src"); els.resImage.classList.add("hidden"); }

  els.resSummary.textContent = result.summary || "";
  els.resAnalysisCard.classList.toggle("hidden", !result.visual_analysis && !result.scenes?.length);
  els.resAnalysis.innerHTML = "";
  for (const [key, value] of Object.entries(result.visual_analysis || {})) {
    if (!value) continue;
    const group = document.createElement("div");
    const term = document.createElement("dt");
    term.textContent = key.replaceAll("_", " ");
    const detail = document.createElement("dd");
    detail.textContent = value;
    group.append(term, detail);
    els.resAnalysis.appendChild(group);
  }

  els.resScenes.innerHTML = "";
  for (const scene of result.scenes || []) {
    const card = document.createElement("div");
    card.className = "scene";
    const thumb = scene.frames && scene.frames.length ? apiUrl(scene.frames[0]) : "";
    if (thumb) {
      const img = document.createElement("img");
      img.loading = "lazy";
      if (creditMode === "credits") img.dataset.privateUrl = scene.frames[0];
      else img.src = thumb;
      img.alt = `Scene ${scene.index} thumbnail`;
      card.appendChild(img);
    }
    const info = document.createElement("div");
    info.className = "scene-meta";
    info.textContent = `Scene ${scene.index}: ${fmtTime(scene.start)} – ${fmtTime(scene.end)} · ${Number(scene.duration).toFixed(1)}s`;
    card.appendChild(info);
    els.resScenes.appendChild(card);
  }

  els.resPromptHeading.textContent = operation === "decode" ? "Reconstructed prompt" : operation === "compose" ? "New creative prompt" : "Enhanced prompt";
  els.resNotice.textContent = operation === "decode"
    ? "This is a plausible reconstruction; the creator’s exact original prompt cannot be guaranteed."
    : operation === "compose" ? "Created from your reference, not recovered from an original prompt."
      : "Your prompt has been refined; Orb has not generated media.";
  els.resOriginal.classList.toggle("hidden", !result.original_prompt);
  els.resOriginalText.textContent = result.original_prompt || "";
  els.resPrompt.textContent = result.prompt || "";
  els.copyPrompt.disabled = !result.prompt;
  els.copyStatus.textContent = "";
  els.resRefinements.innerHTML = "";
  if (result.refinements?.length) {
    const title = document.createElement("strong");
    title.textContent = "Suggested refinements";
    const list = document.createElement("ul");
    for (const refinement of result.refinements) {
      const item = document.createElement("li");
      item.textContent = refinement;
      list.appendChild(item);
    }
    els.resRefinements.append(title, list);
    els.resRefinements.classList.remove("hidden");
  } else els.resRefinements.classList.add("hidden");

  renderOpenCVTelemetry(result.opencv_telemetry);

  showScreen("results");
  if (creditMode === "credits") void loadPrivateMedia(result);
}

export function renderOpenCVTelemetry(cv) {
  if (!els.resOpencvCard) return;
  if (!cv || typeof cv !== "object") {
    els.resOpencvCard.classList.add("hidden");
    return;
  }
  els.resOpencvCard.classList.remove("hidden");

  // 1. Header & Benchmark Badges (Measurable Value)
  if (els.resOpencvBadges) {
    els.resOpencvBadges.replaceChildren();
    const fps = cv.effective_fps ?? cv.motion_and_continuity?.effective_fps;
    const claheActive = Boolean(cv.clahe_applied || cv.clahe_triggered);
    const versionLabel = `OpenCV ${cv.opencv_version || "5.0.0"}${cv.compute_badge ? ` · ${cv.compute_badge}` : ""}`;
    const badgeSpecs = [
      { text: versionLabel, highlight: false },
      cv.processing_ms !== undefined ? { text: `Latency: ${Number(cv.processing_ms).toFixed(1)} ms`, highlight: false } : null,
      fps !== undefined ? { text: `Throughput: ${Number(fps).toFixed(1)} FPS`, highlight: false } : null,
      claheActive ? { text: "CLAHE Auto-Recovery: Active", highlight: true } : null,
    ].filter(Boolean);
    for (const spec of badgeSpecs) {
      const span = document.createElement("span");
      span.className = `opencv-badge${spec.highlight ? " highlight" : ""}`;
      span.textContent = spec.text;
      els.resOpencvBadges.appendChild(span);
    }
  }

  // 2. Agentic Vision Loop (Perception -> Decision -> Action Log)
  const actions = cv.agentic_actions || cv.agentic_decisions || [];
  if (els.resOpencvActionsWrap && els.resOpencvActions) {
    els.resOpencvActions.replaceChildren();
    if (actions.length) {
      for (const act of actions) {
        const li = document.createElement("li");
        const strong = document.createElement("strong");
        strong.textContent = act.decision || "Agentic Decision";
        const span = document.createElement("span");
        span.textContent = ` — ${act.action || ""}${act.trigger ? ` (Perception trigger: ${act.trigger})` : ""}`;
        li.append(strong, span);
        els.resOpencvActions.appendChild(li);
      }
      els.resOpencvActionsWrap.classList.remove("hidden");
    } else {
      els.resOpencvActionsWrap.classList.add("hidden");
    }
  }

  // 3. CLAHE Shadow Recovery Preview Toggle
  if (els.resOpencvClaheWrap && els.resOpencvClaheImg && els.resOpencvClaheView && els.resOpencvClaheToggle) {
    els.resOpencvClaheView.classList.add("hidden");
    els.resOpencvClaheToggle.setAttribute("aria-expanded", "false");
    els.resOpencvClaheToggle.textContent = "View OpenCV CLAHE Shadow Recovery";
    if (cv.clahe_preview_url) {
      if (creditMode !== "credits") els.resOpencvClaheImg.src = apiUrl(cv.clahe_preview_url);
      else els.resOpencvClaheImg.removeAttribute("src");
      els.resOpencvClaheWrap.classList.remove("hidden");
    } else {
      els.resOpencvClaheImg.removeAttribute("src");
      els.resOpencvClaheWrap.classList.add("hidden");
    }
  }

  // 4. Dominant Color Palette (cv2.kmeans)
  const colors = cv.color_and_lighting?.dominant_colors || [];
  if (els.resOpencvPaletteWrap && els.resOpencvPalette) {
    els.resOpencvPalette.replaceChildren();
    if (colors.length) {
      for (const c of colors) {
        const swatch = document.createElement("div");
        swatch.className = "opencv-swatch";
        const dot = document.createElement("span");
        dot.className = "opencv-swatch-dot";
        dot.style.backgroundColor = c.hex;
        const hexLabel = document.createElement("span");
        hexLabel.textContent = c.hex;
        const weight = document.createElement("small");
        weight.textContent = `${c.weight_pct}%`;
        swatch.append(dot, hexLabel, weight);
        els.resOpencvPalette.appendChild(swatch);
      }
      els.resOpencvPaletteWrap.classList.remove("hidden");
    } else {
      els.resOpencvPaletteWrap.classList.add("hidden");
    }
  }

  // 5. Computer Vision Measurements Grid
  if (els.resOpencvMetrics) {
    els.resOpencvMetrics.replaceChildren();
    const cl = cv.color_and_lighting || {};
    const sg = cv.sharpness_and_geometry || {};
    const mc = cv.motion_and_continuity || {};
    const rows = [];
    if (cl.lighting_key !== undefined) {
      rows.push([
        "Lighting & Exposure (cv2.calcHist / LAB)",
        `${cl.lighting_key} · mean luminance ${cl.mean_luminance}/255 · contrast σ ${cl.contrast_std} · dynamic range ${cl.dynamic_range_pct}%`,
      ]);
    }
    if (sg.laplacian_sharpness !== undefined || sg.sharpness_score !== undefined) {
      const score = sg.sharpness_score ?? sg.laplacian_sharpness;
      const label = sg.sharpness_label ?? sg.sharpness_tier;
      const region = sg.saliency_region ?? sg.saliency_center?.composition_zone;
      const lines = sg.dominant_lines ?? sg.structural_lines?.dominant_orientation;
      rows.push([
        "Composition & Focus (cv2.Laplacian / Canny / HoughLinesP)",
        `Sharpness ${score} (${label}) · edge density ${sg.edge_density_pct}% · saliency: ${region} · lines: ${lines}`,
      ]);
    }
    if (mc && mc.dominant_motion) {
      rows.push([
        "Optical Flow & Continuity (cv2.calcOpticalFlowFarneback / compareHist)",
        `Motion: ${mc.dominant_motion} (dx=${mc.mean_dx}, dy=${mc.mean_dy}, radial=${mc.radial_flow}) · HSV continuity ${mc.mean_hist_correlation} (${mc.continuity_class})`,
      ]);
    }
    for (const [title, text] of rows) {
      const group = document.createElement("div");
      const dt = document.createElement("dt");
      dt.textContent = title;
      const dd = document.createElement("dd");
      dd.textContent = text;
      group.append(dt, dd);
      els.resOpencvMetrics.appendChild(group);
    }
  }
}

async function loadPrivateMedia(result) {
  const load = async (path, node) => {
    try {
      const response = await fetchWithTimeout(apiUrl(path), { headers: wallet.headers() });
      if (!response.ok) return;
      const url = URL.createObjectURL(await response.blob());
      privateMediaUrls.push(url);
      node.src = url;
    } catch { /* The prompt remains usable if a preview cannot load. */ }
  };
  if (result.video?.preview_url) void load(result.video.preview_url, els.resVideo);
  if (result.image?.preview_url) void load(result.image.preview_url, els.resImage);
  if (result.opencv_telemetry?.clahe_preview_url && els.resOpencvClaheImg) {
    void load(result.opencv_telemetry.clahe_preview_url, els.resOpencvClaheImg);
  }
  for (const image of els.resScenes.querySelectorAll("img[data-private-url]")) void load(image.dataset.privateUrl, image);
}

/* ---------- Wiring ---------- */

// The real file input covers the visible control and activates the picker natively.
// Do not synthesize a second click or cross an async boundary here.
["dragover", "dragenter"].forEach((name) =>
  els.dropzone.addEventListener(name, (event) => {
    event.preventDefault();
    els.dropzone.classList.add("dragover");
  }),
);
["dragleave", "drop"].forEach((name) =>
  els.dropzone.addEventListener(name, (event) => {
    event.preventDefault();
    els.dropzone.classList.remove("dragover");
  }),
);
els.dropzone.addEventListener("drop", (event) => {
  const file = event.dataTransfer && event.dataTransfer.files && event.dataTransfer.files[0];
  if (file) setFile(file);
});
els.fileInput.addEventListener("change", () => {
  if (els.fileInput.files && els.fileInput.files[0]) setFile(els.fileInput.files[0]);
});
els.menuToggle.addEventListener("click", (event) => {
  event.stopPropagation();
  setMenuOpen(els.siteMenu.classList.contains("hidden"));
});
els.menuHome.addEventListener("click", (event) => {
  event.stopPropagation();
  if (actionBusy) return;
  clearTimeout(pollTimer);
  currentJobId = null;
  clearFile();
  showScreen("home");
});
els.menuAbout.addEventListener("click", (event) => {
  event.stopPropagation();
  setMenuOpen(false);
  setAboutOpen(true);
});
els.menuWallet.addEventListener("click", (event) => {
  event.stopPropagation();
  setMenuOpen(false);
  setAboutOpen(false);
  wallet.open();
});
els.aboutClose.addEventListener("click", () => {
  setAboutOpen(false, true);
});
els.createInfo.addEventListener("click", (event) => {
  event.stopPropagation();
  setCreateInfoOpen(els.createPopover.classList.contains("hidden"), true);
});
els.createPopoverClose.addEventListener("click", (event) => {
  event.stopPropagation();
  setCreateInfoOpen(false, true);
});
document.addEventListener("click", (event) => {
  if (!els.menuToggle.parentElement.contains(event.target)) setMenuOpen(false);
  if (!document.getElementById("mode-create").contains(event.target)) setCreateInfoOpen(false);
});
document.addEventListener("keydown", (event) => {
  if (event.key === "Escape") {
    if (!els.createPopover.classList.contains("hidden")) setCreateInfoOpen(false, true);
    else if (!document.getElementById("wallet-panel").classList.contains("hidden")) wallet.close(true);
    else if (!els.aboutPanel.classList.contains("hidden")) setAboutOpen(false, true);
    else if (!els.siteMenu.classList.contains("hidden")) {
      setMenuOpen(false);
      els.menuToggle.focus();
    }
  }
});
els.fileClear.addEventListener("click", clearFile);
els.decodeBtn.addEventListener("click", startVisual);
els.enhanceBtn.addEventListener("click", startEnhance);
els.promptInput.addEventListener("input", syncDecodeButton);
for (const input of [els.promptInput, els.enhanceOutput, els.enhanceStyle, els.enhanceDetail]) {
  input.addEventListener("input", () => { enhanceAttemptKey = null; });
  input.addEventListener("change", () => { enhanceAttemptKey = null; });
}
els.modeDecode.addEventListener("click", () => setMode("decode"));
els.modeCompose.addEventListener("click", () => setMode("compose"));
els.modeEnhance.addEventListener("click", () => setMode("enhance"));
els.copyPrompt.addEventListener("click", async () => {
  try {
    await navigator.clipboard.writeText(els.resPrompt.textContent);
    els.copyStatus.textContent = "Copied";
  } catch {
    els.copyStatus.textContent = "Copy unavailable. Select the prompt text to copy it.";
  }
});
if (els.resOpencvClaheToggle) {
  els.resOpencvClaheToggle.addEventListener("click", () => {
    if (!els.resOpencvClaheView) return;
    const nextHidden = !els.resOpencvClaheView.classList.contains("hidden");
    els.resOpencvClaheView.classList.toggle("hidden", nextHidden);
    els.resOpencvClaheToggle.setAttribute("aria-expanded", String(!nextHidden));
    els.resOpencvClaheToggle.textContent = nextHidden
      ? "View OpenCV CLAHE Shadow Recovery"
      : "Hide OpenCV CLAHE Shadow Recovery";
  });
}
els.backBtn.addEventListener("click", () => {
  finishActionTiming("cancelled");
  currentJobId = null;
  actionBusy = false;
  syncDecodeButton();
  showScreen("home");
});
els.againBtn.addEventListener("click", () => {
  clearTimeout(pollTimer);
  currentJobId = null;
  actionBusy = false;
  clearFile();
  showScreen("home");
});

window.addEventListener("focus", () => {
  if (!serviceReady) void waitForService();
});
window.addEventListener("online", () => {
  if (!serviceReady) void waitForService();
});

setServiceState(false);
showScreen("home");
void waitForService();
