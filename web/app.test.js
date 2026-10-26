import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const html = readFileSync(resolve(process.cwd(), "web/index.html"), "utf8");
const css = readFileSync(resolve(process.cwd(), "web/styles.css"), "utf8");

function response(body, status = 200) {
  return { ok: status >= 200 && status < 300, status, json: async () => body };
}

function isInspectUrl(url) {
  return /\/api\/orb\/(decode|compose)\/file(\?|$)/.test(String(url));
}

function isUploadPingUrl(url) {
  return /\/api\/upload-ping(\?|$)/.test(String(url));
}

function inspectCalls(fetchMock = globalThis.fetch) {
  return fetchMock.mock.calls.filter(([url]) => isInspectUrl(url));
}

async function flush() {
  for (let index = 0; index < 6; index += 1) {
    await new Promise((resolve) => setTimeout(resolve, 0));
  }
}

function chooseVideo(name = "clip.mp4") {
  const input = document.getElementById("file-input");
  Object.defineProperty(input, "files", {
    value: [new File(["video-data"], name, { type: "video/mp4" })],
    configurable: true,
  });
  input.dispatchEvent(new Event("change"));
}

function mockApi({
  inspectError = null,
  healthOk = true,
  readyOk = true,
  pingStatus = 204,
  jobStatuses = [],
  jobError = null,
} = {}) {
  let inspectNumber = 0;
  const fetchMock = vi.fn(async (url, options = {}) => {
    const path = String(url);
    if (path === "/api/orb/credits/config") return response({ enabled: false, chain_id: 421614, price_wei: "1000000000000" });
    if (path === "/api/health") return response({ status: healthOk ? "ok" : "unavailable" }, healthOk ? 200 : 503);
    if (path === "/api/ready") return response({ status: readyOk ? "ready" : "starting" }, readyOk ? 200 : 503);
    if (isUploadPingUrl(path)) return response({}, pingStatus);
    if (isInspectUrl(path)) {
      if (inspectError) throw inspectError;
      inspectNumber += 1;
      return response({ job_id: `job-${inspectNumber}` }, 202);
    }
    if (path === "/api/orb/enhance") return response({ job_id: "job-enhance" }, 202);
    if (path.startsWith("/api/jobs/") && path.endsWith("/result")) {
      const id = path.split("/")[3];
      return response({
        job_id: id,
        operation: id === "job-enhance" ? "enhance" : "decode",
        provider: "gemini",
        video: id === "job-enhance" ? undefined : { name: "clip.mp4", duration: 2, width: 320, height: 240, fps: 24, preview_url: `/api/jobs/${id}/frames/source.mp4` },
        summary: "One scene detected.",
        scenes: id === "job-enhance" ? [] : [{ index: 0, start: 0, end: 2, duration: 2, frames: [] }],
        visual_analysis: { composition: "Centered subject" },
        original_prompt: id === "job-enhance" ? "a blue car" : undefined,
        prompt: "A blue car under soft daylight.",
        notice: "Exact original prompt cannot be guaranteed.",
      });
    }
    if (path.startsWith("/api/jobs/")) {
      if (jobError) throw jobError;
      const job = jobStatuses.length ? jobStatuses.shift() : { state: "complete", stage: "Complete" };
      return response(job);
    }
    throw new Error(`Unexpected request: ${path}`);
  });
  globalThis.fetch = fetchMock;
  return fetchMock;
}

async function startPaidJobWithExpiredSession({ released = false } = {}) {
  const owner = `0x${"11".repeat(20)}`;
  const other = `0x${"22".repeat(20)}`;
  const jobId = "a".repeat(32);
  const handlers = new Map();
  let selectedAccount = owner;
  let signIns = 0;
  let available = 1;
  const provider = {
    on: vi.fn((event, listener) => handlers.set(event, listener)),
    request: vi.fn(async ({ method }) => {
      if (method === "eth_accounts" || method === "eth_requestAccounts") return [selectedAccount];
      if (method === "eth_chainId") return "0x66eee";
      if (method === "personal_sign") return `0x${"cd".repeat(65)}`;
      throw new Error(`Unexpected wallet method: ${method}`);
    }),
  };
  window.ethereum = provider;
  const fetchMock = vi.fn(async (url, options = {}) => {
    const path = String(url);
    if (path === "/api/orb/credits/config") return response({ enabled: true, chain_id: 421614, price_wei: "1000" });
    if (path === "/api/health") return response({ status: "ok", orb_ai_access: "credits" });
    if (path === "/api/ready") return response({ status: "ready" });
    if (isUploadPingUrl(path)) return response({}, 204);
    if (path === "/api/orb/wallet/challenge") return response({ nonce: `nonce-${signIns}`, message: "Sign in to Orb" });
    if (path === "/api/orb/wallet/sign-in") return response({ wallet: selectedAccount,
      token: `session-${++signIns}`, expires_at: Math.floor(Date.now() / 1000) + 3600 });
    if (path === "/api/orb/credits/balance") return response({ wallet: selectedAccount, available });
    if (isInspectUrl(path)) return response({ job_id: jobId }, 202);
    if (path === `/api/jobs/${jobId}`) {
      if (options.headers?.Authorization === "Bearer session-1") {
        available = 0;
        return response({ detail: "Wallet session expired. Sign again." }, 401);
      }
      if (selectedAccount !== owner) return response({ detail: "Unknown job." }, 404);
      if (released) {
        available = 1;
        return response({ state: "error", stage: "Interrupted", error: "AI processing failed." });
      }
      return response({ state: "complete", stage: "Complete" });
    }
    if (path === `/api/jobs/${jobId}/result`) return response({ job_id: jobId, operation: "decode",
      provider: "gemini", video: { name: "clip.mp4", duration: 2, width: 320, height: 240 },
      scenes: [], prompt: "Recovered durable prompt.", visual_analysis: {} });
    throw new Error(`Unexpected request: ${path}`);
  });
  globalThis.fetch = fetchMock;
  await import("./app.js");
  await flush();
  document.getElementById("wallet-connect").click();
  await flush();
  chooseVideo();
  document.getElementById("decode-btn").click();
  await flush();
  return { owner, other, jobId, provider, fetchMock, changeAccount(next) {
    selectedAccount = next;
    handlers.get("accountsChanged")?.([next]);
  } };
}

describe("Orb frontend", () => {
  it.each(["decode", "compose", "enhance"])("records %s lifecycle diagnostics without changing result or request counts", async (mode) => {
    const info = vi.spyOn(console, "info").mockImplementation(() => {});
    const api = mockApi();
    await import("./app.js");
    await flush();
    document.getElementById(`mode-${mode}`).click();
    if (mode === "enhance") {
      const input = document.getElementById("prompt-input");
      input.value = "private-prompt-sentinel";
      input.dispatchEvent(new Event("input"));
      document.getElementById("enhance-btn").click();
    } else {
      chooseVideo("private-filename.mp4");
      document.getElementById("decode-btn").click();
    }
    await flush();
    await vi.waitFor(() => expect(info.mock.calls.filter(([label]) => label === "orb_perf_frontend")).toHaveLength(1));
    const values = info.mock.calls.find(([label]) => label === "orb_perf_frontend")[1];
    expect(values.operation).toBe(mode === "enhance" ? "enhance" : `${mode}_video`);
    expect(values.status).toBe("complete");
    for (const field of ["readiness_wait_ms", "upload_request_ms", "job_available_ms", "result_detected_ms", "result_displayed_ms", "total_ms"]) {
      expect(values[field]).toBeGreaterThanOrEqual(0);
    }
    expect(values.poll_requests).toBe(1);
    expect(JSON.stringify(values)).not.toContain("private-");
    expect(document.getElementById("res-prompt").textContent).toBe("A blue car under soft daylight.");
    expect(api.mock.calls.filter(([url]) => mode === "enhance" ? url === "/api/orb/enhance" : isInspectUrl(url))).toHaveLength(1);
  });
  beforeEach(() => {
    vi.resetModules();
    delete window.ethereum;
    sessionStorage.clear();
    document.open();
    document.write(html);
    document.close();
    window.scrollTo = vi.fn();
    HTMLElement.prototype.focus = vi.fn();
  });

  afterEach(() => {
    vi.clearAllTimers();
    vi.useRealTimers();
    vi.restoreAllMocks();
  });

  it("shows three working modes and a locked fourth Create stage", async () => {
    mockApi();
    await import("./app.js");
    await flush();

    expect(document.querySelector(".wordmark").textContent).toBe("Orb");
    expect(document.querySelector(".mode-pill.active strong").textContent).toBe("Decode");
    expect(Array.from(document.querySelectorAll(".mode-pill")).map((item) => item.id)).toEqual([
      "mode-decode", "mode-compose", "mode-enhance", "mode-create",
    ]);
    expect(document.getElementById("mode-compose").disabled).toBe(false);
    expect(document.getElementById("mode-enhance").disabled).toBe(false);
    expect(document.getElementById("mode-create").getAttribute("aria-label")).toMatch(/locked; coming soon/i);
    expect(document.querySelector("#mode-create .create-lock")).not.toBeNull();
    expect(document.querySelector("#mode-create small").textContent).toBe("Coming soon");
    expect(document.querySelector("#mode-create > button:not(#create-info)")).toBeNull();
    expect(document.querySelector(".mode-cards")).toBeNull();
    expect(document.querySelector(".mode-nav")).toBeNull();
    expect(document.querySelector("#dropzone small").textContent).toContain("WebP");
    expect(document.querySelector(".topbar #header-wallet").textContent).toBe("Connect Wallet");
    expect(document.querySelector("#upload-shell #header-wallet")).toBeNull();
    expect(document.getElementById("upload-credits-cta")).toBeNull();
    expect(document.querySelector(".roadmap-note")).toBeNull();
    expect(document.body.textContent).not.toMatch(/Gemini/i);
  });

  it("uses fresh network fees and a new quote only on a user retry after an under-base-fee rejection", async () => {
    const address = `0x${"11".repeat(20)}`;
    const receiver = `0x${"22".repeat(20)}`;
    const txHash = `0x${"ab".repeat(32)}`;
    const paidJobId = "f".repeat(32);
    let chain = "0x1";
    let available = 0;
    let feeFailure = true;
    const provider = {
      on: vi.fn(),
      request: vi.fn(async ({ method, params }) => {
        if (method === "eth_accounts") return [address];
        if (method === "eth_requestAccounts") return [address];
        if (method === "eth_chainId") return chain;
        if (method === "wallet_switchEthereumChain") { chain = params[0].chainId; return null; }
        if (method === "personal_sign") return `0x${"cd".repeat(65)}`;
        if (method === "eth_getBlockByNumber") return { baseFeePerGas: feeFailure ? "0x64" : "0xc8" };
        if (method === "eth_maxPriorityFeePerGas") return "0x2";
        if (method === "eth_estimateGas") return "0x186a0";
        if (method === "eth_sendTransaction") {
          if (feeFailure) {
            feeFailure = false;
            const error = new Error("Internal JSON-RPC error.");
            error.data = { message: "maxFeePerGas: 31140000 less than block baseFee: 31286000" };
            throw error;
          }
          return txHash;
        }
        throw new Error(`Unexpected wallet method: ${method}`);
      }),
    };
    window.ethereum = provider;
    const fetchMock = vi.fn(async (url, options = {}) => {
      const path = String(url);
      if (path === "/api/orb/credits/config") return response({ enabled: true, chain_id: 421614, price_wei: "1000000000000" });
      if (path === "/api/health") return response({ status: "ok", orb_ai_access: "credits" });
      if (path === "/api/ready") return response({ status: "ready" });
      if (isUploadPingUrl(path)) return response({}, 204);
      if (path === "/api/orb/wallet/challenge") return response({ nonce: "nonce", message: "Sign in to Orb testnet" });
      if (path === "/api/orb/wallet/sign-in") return response({ wallet: address, token: "session-token",
        expires_at: Math.floor(Date.now() / 1000) + 3600 });
      if (path === "/api/orb/credits/balance") return response({ wallet: address, available });
      if (path === "/api/orb/credits/quotes") return response({ quote_id: "quote", chain_id: 421614,
        to: receiver, value_wei: "1000000000000", data: "0x4f524231abcd" });
      if (path === "/api/orb/credits/quotes/quote/verify") {
        available = 1;
        return response({ credits: 1, balance: { available } });
      }
      if (isInspectUrl(path)) return response({ job_id: paidJobId }, 202);
      if (path === `/api/jobs/${paidJobId}`) return response({ state: "processing", stage: "Analyzing image" });
      throw new Error(`Unexpected request: ${path}`);
    });
    globalThis.fetch = fetchMock;
    await import("./app.js");
    await flush();
    chooseVideo();
    expect(document.getElementById("decode-btn").disabled).toBe(true);
    expect(document.getElementById("upload-credits-cta")).toBeNull();
    document.getElementById("header-wallet").click();
    await flush();
    expect(provider.request.mock.calls.some(([arg]) => arg.method === "wallet_switchEthereumChain")).toBe(true);
    expect(document.getElementById("wallet-network").textContent).toContain("Arbitrum Sepolia");
    expect(document.getElementById("wallet-address").textContent).toContain("0x1111");
    expect(document.getElementById("header-wallet").textContent).toBe("Connected");
    document.getElementById("wallet-buy").click();
    await flush();
    expect(document.getElementById("wallet-feedback").textContent).toContain("Your wallet's fee estimate was below Arbitrum Sepolia's current base fee");
    expect(provider.request.mock.calls.filter(([arg]) => arg.method === "eth_sendTransaction")).toHaveLength(1);
    expect(sessionStorage.getItem("orb-sepolia-pending-payment")).toBeNull();
    expect(fetchMock.mock.calls.filter(([url]) => String(url).endsWith("/verify"))).toHaveLength(0);
    document.getElementById("wallet-buy").click();
    await flush();
    const transactions = provider.request.mock.calls.filter(([arg]) => arg.method === "eth_sendTransaction");
    expect(transactions).toHaveLength(2);
    for (const [index, [request]] of transactions.entries()) {
      expect(request.params[0]).toEqual({
        from: address, to: receiver, value: `0x${BigInt("1000000000000").toString(16)}`,
        data: "0x4f524231abcd",
        gas: "0x1d4c0", maxFeePerGas: index === 0 ? "0x98" : "0x12e", maxPriorityFeePerGas: "0x2",
      });
    }
    expect(fetchMock.mock.calls.filter(([url]) => url === "/api/orb/credits/quotes")).toHaveLength(2);
    expect(provider.request.mock.calls.filter(([arg]) => arg.method === "eth_maxPriorityFeePerGas")).toHaveLength(2);
    expect(document.getElementById("wallet-balance").textContent).toContain("1 testnet credit");
    expect(document.getElementById("header-credit-value").textContent).toBe("1");
    expect(document.getElementById("header-credits").classList.contains("hidden")).toBe(false);
    expect(document.getElementById("decode-btn").disabled).toBe(false);
    document.getElementById("wallet-close").click();
    document.getElementById("decode-btn").click();
    await flush();
    const request = inspectCalls(fetchMock)[0][1];
    expect(request.headers.Authorization).toBe("Bearer session-token");
    expect(request.headers["X-Orb-Idempotency-Key"]).toBeTruthy();
    expect(JSON.parse(sessionStorage.getItem("orb-active-paid-job")).jobId).toBe(paidJobId);
    expect(document.getElementById("screen-processing").classList.contains("hidden")).toBe(false);
  });

  it("pauses a paid 401 and resumes the same job and durable result after signing again", async () => {
    const { jobId, provider, fetchMock } = await startPaidJobWithExpiredSession();
    expect(document.getElementById("job-error").textContent).toBe(
      "Session expired — sign again to continue this analysis.");
    expect(document.getElementById("wallet-panel").classList.contains("hidden")).toBe(false);
    expect(document.getElementById("wallet-connect").textContent).toBe("Sign again");
    expect(JSON.parse(sessionStorage.getItem("orb-active-paid-job")).jobId).toBe(jobId);
    expect(fetchMock.mock.calls.filter(([url]) => String(url) === `/api/jobs/${jobId}`)).toHaveLength(1);

    document.getElementById("wallet-connect").click();
    await flush();
    expect(provider.request.mock.calls.filter(([request]) => request.method === "personal_sign")).toHaveLength(2);
    expect(fetchMock.mock.calls.filter(([url]) => String(url) === `/api/jobs/${jobId}`)).toHaveLength(2);
    expect(fetchMock.mock.calls.filter(([url]) => String(url) === `/api/jobs/${jobId}/result`)).toHaveLength(1);
    expect(inspectCalls(fetchMock)).toHaveLength(1);
    expect(document.getElementById("res-prompt").textContent).toBe("Recovered durable prompt.");
    expect(sessionStorage.getItem("orb-active-paid-job")).toBeNull();
  });

  it("keeps an expired paid job private when a different wallet signs in", async () => {
    const { other, jobId, changeAccount, fetchMock } = await startPaidJobWithExpiredSession();
    changeAccount(other);
    document.getElementById("wallet-connect").click();
    await flush();
    expect(document.getElementById("wallet-connect").textContent).toBe("Connected");
    expect(document.getElementById("job-error").textContent).toContain("wallet that started this analysis");
    expect(JSON.parse(sessionStorage.getItem("orb-active-paid-job")).jobId).toBe(jobId);
    expect(fetchMock.mock.calls.filter(([url]) => String(url) === `/api/jobs/${jobId}`)).toHaveLength(1);
    expect(inspectCalls(fetchMock)).toHaveLength(1);
  });

  it("refreshes the restored credit balance when a resumed paid job failed", async () => {
    const { jobId, fetchMock } = await startPaidJobWithExpiredSession({ released: true });
    document.getElementById("wallet-connect").click();
    await flush();
    expect(document.getElementById("job-error").textContent).toContain("Analysis failed");
    expect(document.getElementById("wallet-balance").textContent).toContain("1 testnet credit available");
    expect(sessionStorage.getItem("orb-active-paid-job")).toBeNull();
    expect(fetchMock.mock.calls.filter(([url]) => String(url) === `/api/jobs/${jobId}`)).toHaveLength(2);
    expect(inspectCalls(fetchMock)).toHaveLength(1);
  });

  it("opens a grouped menu, closes outside and on Escape, and shows About Orb", async () => {
    mockApi();
    await import("./app.js");
    await flush();

    const input = document.getElementById("file-input");
    const filePicker = vi.fn();
    input.addEventListener("click", filePicker);
    input.dispatchEvent(new MouseEvent("click", { bubbles: true }));
    expect(filePicker).toHaveBeenCalledTimes(1);

    const toggle = document.getElementById("menu-toggle");
    const menu = document.getElementById("site-menu");
    toggle.click();
    expect(toggle.getAttribute("aria-expanded")).toBe("true");
    expect(menu.classList.contains("hidden")).toBe(false);
    expect(Array.from(menu.querySelectorAll(".menu-heading")).map((item) => item.textContent)).toEqual([
      "Home", "Workspace", "Account", "Information",
    ]);
    expect(menu.querySelectorAll(".menu-action")).toHaveLength(3);
    expect(menu.querySelectorAll(".menu-unavailable")).toHaveLength(2);
    expect(Array.from(menu.querySelectorAll(".menu-unavailable small")).every((item) => item.textContent === "Coming soon")).toBe(true);
    expect(menu.querySelector("#menu-upload")).toBeNull();

    document.body.click();
    expect(toggle.getAttribute("aria-expanded")).toBe("false");

    toggle.click();
    document.dispatchEvent(new KeyboardEvent("keydown", { key: "Escape", bubbles: true }));
    expect(toggle.getAttribute("aria-expanded")).toBe("false");
    expect(toggle.focus).toHaveBeenCalled();

    toggle.click();
    document.getElementById("menu-about").click();
    expect(toggle.getAttribute("aria-expanded")).toBe("false");
    expect(document.getElementById("about-panel").classList.contains("hidden")).toBe(false);
    expect(document.getElementById("about-panel").textContent).toContain("autonomous visual intelligence and creative analysis");
    document.getElementById("about-close").click();
    toggle.click();
    document.getElementById("menu-wallet").click();
    expect(document.getElementById("wallet-panel").classList.contains("hidden")).toBe(false);
    expect(document.getElementById("wallet-panel").textContent).toContain("TESTNET ONLY");
    document.dispatchEvent(new KeyboardEvent("keydown", { key: "Escape", bubbles: true }));
    expect(document.getElementById("wallet-panel").classList.contains("hidden")).toBe(true);
    expect(document.getElementById("about-panel").textContent).toContain("Perceive with OpenCV 5.0 → evaluate visual quality");
    expect(document.getElementById("about-panel").textContent).toContain("Arbitrum Sepolia testnet credits");
    expect(document.getElementById("about-panel").textContent).toContain("Create · realize");
    document.getElementById("about-close").click();
    expect(document.getElementById("about-panel").classList.contains("hidden")).toBe(true);
  });

  it.each(["click", "keyboard"])("keeps one direct native-input activation path (%s)", async (activation) => {
    const fetchMock = mockApi();
    await import("./app.js");
    await flush();
    const wrapper = document.getElementById("choose-file-btn");
    const input = document.getElementById("file-input");
    expect(wrapper.tagName).toBe("DIV");
    expect(wrapper.querySelector('input[type="file"]')).toBe(input);
    expect(document.querySelector('label[for="file-input"]')).toBeNull();
    expect(input.hidden).toBe(false);
    expect(input.tabIndex).toBe(0);
    expect(input.hasAttribute("capture")).toBe(false);
    expect(input.accept).toBe("image/jpeg,image/png,image/webp,.jpg,.jpeg,.png,.webp,video/mp4,.mp4,.m4v,.mov,.webm");
    const activations = vi.fn();
    input.addEventListener("click", activations);
    const syntheticClick = vi.spyOn(input, "click");
    if (activation === "keyboard") {
      const key = new KeyboardEvent("keydown", { key: "Enter", bubbles: true, cancelable: true });
      input.dispatchEvent(key);
      expect(key.defaultPrevented).toBe(false); // Native file input handles keyboard activation.
    }
    // jsdom does not implement the OS picker; model its native click event.
    input.dispatchEvent(new MouseEvent("click", { bubbles: true }));
    expect(syntheticClick).not.toHaveBeenCalled();
    expect(activations).toHaveBeenCalledTimes(1);
    expect(inspectCalls(fetchMock)).toHaveLength(0);
    input.dispatchEvent(new Event("cancel"));
    expect(document.getElementById("file-card").classList.contains("hidden")).toBe(true);
    expect(document.getElementById("decode-btn").disabled).toBe(true);
  });

  it.each(["decode", "compose"].flatMap((mode) => ["png", "mp4"].map((extension) => [mode, extension])))
  ("keeps native picker selection, reset and one upload intact (%s, %s)", async (mode, extension) => {
    const fetchMock = mockApi();
    await import("./app.js");
    await flush();
    document.getElementById(`mode-${mode}`).click();
    const input = document.getElementById("file-input");
    const name = `reference.${extension}`;
    const select = () => {
      input.dispatchEvent(new MouseEvent("click", { bubbles: true }));
      Object.defineProperty(input, "files", { value: [new File(["media"], name,
        { type: extension === "png" ? "image/png" : "video/mp4" })], configurable: true });
      input.dispatchEvent(new Event("change"));
    };
    select();
    expect(document.getElementById("file-name").textContent).toBe(name);
    expect(document.getElementById("decode-btn").disabled).toBe(false);
    expect(inspectCalls(fetchMock)).toHaveLength(0);
    document.getElementById("file-clear").click();
    expect(input.value).toBe("");
    expect(document.getElementById("file-card").classList.contains("hidden")).toBe(true);
    select(); // Fresh selection with exactly the same name after reset.
    const submit = document.getElementById("decode-btn");
    submit.click();
    submit.click();
    await flush();
    expect(inspectCalls(fetchMock)).toHaveLength(1);
    expect(inspectCalls(fetchMock)[0][0]).toContain(`/api/orb/${mode}/file`);
    expect(inspectCalls(fetchMock)[0][1].body.get("file").name).toBe(name);
  });

  it("keeps native picker focus visible and the wallet close header sticky", () => {
    const style = document.createElement("style");
    style.textContent = css;
    document.head.appendChild(style);
    const input = document.getElementById("file-input");
    expect(getComputedStyle(input).position).toBe("absolute");
    expect(getComputedStyle(input).opacity).toBe("0");
    expect(getComputedStyle(input).display).not.toBe("none");
    expect(getComputedStyle(input).visibility).toBe("visible");
    expect(getComputedStyle(input).pointerEvents).toBe("auto");
    expect(getComputedStyle(input).zIndex).toBe("1");
    expect(getComputedStyle(input).width).toBe("100%");
    expect(getComputedStyle(input).height).toBe("100%");
    expect(getComputedStyle(document.querySelector(".choose-file-content")).pointerEvents).toBe("none");
    expect(css).toMatch(/\.choose-file-btn:focus-within\s*\{[^}]*outline:/);
    expect(getComputedStyle(document.querySelector("#wallet-panel .about-head")).position).toBe("sticky");
    expect(document.querySelector("#wallet-panel .about-head #wallet-close")).not.toBeNull();
    expect(getComputedStyle(document.querySelector("#credit-count button")).minHeight).toBe("44px");
  });

  it("has no wrapper activation or programmatic file-input click in application code", async () => {
    const fetchMock = mockApi();
    await import("./app.js");
    await flush();
    const input = document.getElementById("file-input");
    const activations = vi.fn();
    input.addEventListener("click", activations);
    document.getElementById("choose-file-btn").click();
    expect(activations).not.toHaveBeenCalled(); // A physical tap must land on the overlaid input.
    const source = readFileSync(resolve(process.cwd(), "web/app.js"), "utf8");
    expect(source).not.toMatch(/(?:fileInput|file-input)[^\n]*\.click\s*\(/);
    expect(inspectCalls(fetchMock)).toHaveLength(0);
  });

  it("keeps Decode disabled until the service passes health, ready, and the upload canary", async () => {
    vi.useFakeTimers();
    const fetchMock = mockApi({ healthOk: false });
    await import("./app.js");
    await vi.advanceTimersByTimeAsync(0);

    expect(document.getElementById("decode-btn").disabled).toBe(true);
    expect(document.getElementById("decode-btn").querySelector("span").textContent).toBe("Preparing Orb…");
    expect(inspectCalls(fetchMock)).toHaveLength(0);
  });

  it("shares one wake-up task across focus/online events and waits for the upload canary", async () => {
    vi.useFakeTimers();
    const listeners = vi.spyOn(window, "addEventListener");
    const fetchMock = mockApi();
    const original = fetchMock.getMockImplementation();
    let resolveHealth;
    let resolveCanary;
    fetchMock.mockImplementation((url, options) => {
      if (url === "/api/health") return new Promise((resolve) => { resolveHealth = resolve; });
      if (isUploadPingUrl(url)) return new Promise((resolve) => { resolveCanary = resolve; });
      return original(url, options);
    });
    await import("./app.js");
    await vi.advanceTimersByTimeAsync(0);
    const focus = listeners.mock.calls.find(([name]) => name === "focus")[1];
    const online = listeners.mock.calls.find(([name]) => name === "online")[1];
    focus(); online(); focus();
    expect(fetchMock.mock.calls.filter(([url]) => url === "/api/health")).toHaveLength(1);
    chooseVideo();
    expect(document.getElementById("decode-btn").disabled).toBe(true);
    resolveHealth(response({ status: "ok" }));
    await vi.advanceTimersByTimeAsync(0);
    expect(document.getElementById("decode-btn").disabled).toBe(true);
    focus(); online();
    expect(fetchMock.mock.calls.filter(([url]) => isUploadPingUrl(url))).toHaveLength(1);
    resolveCanary(response({}, 204));
    await vi.advanceTimersByTimeAsync(0);
    expect(document.getElementById("decode-btn").disabled).toBe(false);
    await vi.advanceTimersByTimeAsync(120000);
    focus(); online();
    expect(fetchMock.mock.calls.filter(([url]) => url === "/api/health")).toHaveLength(1);
    expect(fetchMock.mock.calls.filter(([url]) => url === "/api/ready")).toHaveLength(1);
    expect(fetchMock.mock.calls.filter(([url]) => isUploadPingUrl(url))).toHaveLength(1);
    expect(fetchMock.mock.calls.filter(([url]) => url === "/api/orb/credits/config")).toHaveLength(1);
    expect(inspectCalls(fetchMock)).toHaveLength(0);
  });

  it("recovers at one-second health intervals without repeating or resetting credit configuration", async () => {
    vi.useFakeTimers();
    const fetchMock = mockApi();
    const original = fetchMock.getMockImplementation();
    let healthCalls = 0;
    fetchMock.mockImplementation((url, options) => {
      if (url === "/api/health" && ++healthCalls < 3) return Promise.resolve(response({ status: "starting" }, 503));
      return original(url, options);
    });
    await import("./app.js");
    await vi.advanceTimersByTimeAsync(1999);
    expect(document.getElementById("service-status").textContent).not.toContain("Orb service ready.");
    expect(fetchMock.mock.calls.filter(([url]) => url === "/api/ready")).toHaveLength(0);
    await vi.advanceTimersByTimeAsync(1);
    expect(document.getElementById("service-status").textContent).toBe("Orb service ready.");
    expect(fetchMock.mock.calls.filter(([url]) => url === "/api/health")).toHaveLength(3);
    expect(fetchMock.mock.calls.filter(([url]) => isUploadPingUrl(url))).toHaveLength(1);
    expect(fetchMock.mock.calls.filter(([url]) => url === "/api/orb/credits/config")).toHaveLength(1);
  });

  it("allows readiness and upload verification to each take longer than five seconds", async () => {
    vi.useFakeTimers();
    const fetchMock = mockApi();
    const original = fetchMock.getMockImplementation();
    fetchMock.mockImplementation(async (url, options) => {
      if (url === "/api/ready" || isUploadPingUrl(url)) {
        await new Promise((resolve) => setTimeout(resolve, 6000));
        expect(options.signal.aborted).toBe(false);
      }
      return original(url, options);
    });
    await import("./app.js");
    chooseVideo();
    await vi.advanceTimersByTimeAsync(11999);
    expect(document.getElementById("decode-btn").disabled).toBe(true);
    await vi.advanceTimersByTimeAsync(1);
    expect(document.getElementById("decode-btn").disabled).toBe(false);
    expect(fetchMock.mock.calls.filter(([url]) => url === "/api/health")).toHaveLength(1);
    expect(fetchMock.mock.calls.filter(([url]) => url === "/api/ready")).toHaveLength(1);
    expect(fetchMock.mock.calls.filter(([url]) => isUploadPingUrl(url))).toHaveLength(1);
  });

  it("enables Decode after the upload-path canary succeeds", async () => {
    mockApi();
    await import("./app.js");
    await flush();

    // Service is ready but no file is chosen: the button still waits.
    const button = document.getElementById("decode-btn");
    expect(document.getElementById("service-status").textContent).toContain("ready");
    expect(button.disabled).toBe(true);
    chooseVideo();
    expect(button.disabled).toBe(false);
    expect(button.querySelector("span").textContent).toBe("Decode reference");
  });

  it("accepts image files and rejects unsupported files before upload", async () => {
    const fetchMock = mockApi();
    await import("./app.js");
    await flush();
    chooseVideo("snapshot.png");
    await flush();

    expect(document.getElementById("decode-btn").disabled).toBe(false);
    chooseVideo("snapshot.gif");
    expect(document.getElementById("upload-error").textContent).toContain("Unsupported file type");
    expect(inspectCalls(fetchMock)).toHaveLength(0);
  });

  it.each(["image", "video"])("keeps the original %s preview local when Lambda's temporary source is unavailable", async (kind) => {
    const job = "a".repeat(32);
    const address = `0x${"11".repeat(20)}`;
    const sourcePath = `/api/jobs/${job}/frames/source.${kind === "image" ? "png" : "mp4"}`;
    const create = vi.fn(() => "blob:orb-local-reference");
    const revoke = vi.fn();
    const NativeURL = URL;
    vi.stubGlobal("URL", class extends NativeURL {
      static createObjectURL = create;
      static revokeObjectURL = revoke;
    });
    try {
      sessionStorage.setItem("orb-wallet-session", JSON.stringify({ token: "saved-session", address,
        expiresAt: Date.now() / 1000 + 3600 }));
      window.ethereum = { on: vi.fn(), request: vi.fn(async ({ method }) =>
        method === "eth_chainId" ? "0x66eee" : [address]) };
      const payload = { job_id: job, operation: "decode", prompt: "A reference-derived prompt.",
        [kind]: { name: "reference", width: 1280, height: 720, preview_url: sourcePath } };
      const fetchMock = vi.fn(async (url) => {
        if (url === "/api/orb/credits/config") return response({ enabled: true, chain_id: 421614, price_wei: "1000" });
        if (url === "/api/health") return response({ status: "ok", orb_ai_access: "credits" });
        if (url === "/api/ready") return response({ status: "ready" });
        if (isUploadPingUrl(url)) return response({}, 204);
        if (url === "/api/orb/credits/balance") return response({ wallet: address, available: 1 });
        if (isInspectUrl(url)) return response({ job_id: job }, 202);
        if (url === `/api/jobs/${job}`) return response({ state: "complete", stage: "Complete" });
        if (url === `/api/jobs/${job}/result`) return response(payload);
        return response({ detail: "Temporary source unavailable." }, 404);
      });
      globalThis.fetch = fetchMock;
      const mod = await import("./app.js");
      await flush();
      const input = document.getElementById("file-input");
      const file = new File(["reference-bytes"], kind === "image" ? "reference.png" : "reference.mp4",
        { type: kind === "image" ? "image/png" : "video/mp4" });
      Object.defineProperty(input, "files", { configurable: true, value: [file] });
      input.dispatchEvent(new Event("change"));
      document.getElementById("decode-btn").click();
      await flush();
      const preview = document.getElementById(kind === "image" ? "res-image" : "res-video");
      expect(create).toHaveBeenCalledWith(file);
      expect(preview.getAttribute("src")).toBe("blob:orb-local-reference");
      expect(preview.classList.contains("hidden")).toBe(false);
      expect(fetchMock.mock.calls.some(([url]) => url === sourcePath)).toBe(false);
      expect(inspectCalls(fetchMock)).toHaveLength(1);
      mod.renderResult(payload);
      expect(revoke).not.toHaveBeenCalledWith("blob:orb-local-reference");
      document.getElementById("again-btn").click();
      expect(revoke).toHaveBeenCalledWith("blob:orb-local-reference");
      mod.renderResult({ ...payload, job_id: "b".repeat(32) });
      expect(preview.getAttribute("src")).not.toBe("blob:orb-local-reference");
    } finally {
      vi.unstubAllGlobals();
    }
  });

  it("runs one correlated upload and renders the reconstructed prompt", async () => {
    const fetchMock = mockApi({
      jobStatuses: [{ state: "complete", stage: "Complete" }],
    });
    await import("./app.js");
    await flush();
    chooseVideo();
    document.getElementById("decode-btn").click();
    await flush();

    const inspect = inspectCalls(fetchMock);
    expect(inspect).toHaveLength(1);
    expect(inspect[0][0]).toMatch(/^\/api\/orb\/decode\/file\?upload_attempt_id=[A-Za-z0-9-]+$/);
    expect(inspect[0][1].method).toBe("POST");
    expect(inspect[0][1].body).toBeInstanceOf(FormData);
    expect(inspect[0][1].headers?.["Content-Type"]).toBeUndefined();

    expect(document.getElementById("screen-results").classList.contains("hidden")).toBe(false);
    expect(document.getElementById("res-title").textContent).toBe("clip.mp4");
    expect(document.querySelectorAll("#res-scenes .scene")).toHaveLength(1);
    expect(document.getElementById("res-prompt").textContent).toContain("A blue car");
    expect(document.getElementById("res-notice").textContent).toContain("cannot be guaranteed");
    expect(document.getElementById("screen-results").textContent).not.toMatch(/Gemini/i);
    expect(document.getElementById("res-mode").textContent).toContain("plausible reconstruction");
  });

  it("labels an interrupted upload without retrying", async () => {
    const fetchMock = mockApi({ inspectError: new TypeError("Failed to fetch") });
    await import("./app.js");
    await flush();
    chooseVideo();
    document.getElementById("decode-btn").click();
    await flush();

    const message = document.getElementById("job-error").textContent;
    expect(message).toContain("Upload connection was interrupted");
    expect(message).toContain("No retry was made");
    expect(message).toContain("Reference:");
    expect(inspectCalls(fetchMock)).toHaveLength(1);
  });

  it("blocks an unreadable file before any upload and guides to another source", async () => {
    const fetchMock = mockApi();
    await import("./app.js");
    await flush();
    chooseVideo();
    const file = document.getElementById("file-input").files[0];
    vi.spyOn(file, "slice").mockReturnValue({
      arrayBuffer: () => Promise.reject(new DOMException("denied", "NotReadableError")),
    });
    const info = vi.spyOn(console, "info").mockImplementation(() => {});
    vi.useFakeTimers();
    document.getElementById("decode-btn").click();
    await vi.advanceTimersByTimeAsync(1100);

    expect(inspectCalls(fetchMock)).toHaveLength(0);
    const message = document.getElementById("upload-error").textContent;
    expect(message).toContain("Couldn't access this video");
    expect(message).toContain("Choose it again using Files or Browse.");
    expect(message).not.toMatch(/NotReadableError|Reference:|No upload/);
    expect(document.getElementById("screen-home").classList.contains("hidden")).toBe(false);
    expect(document.getElementById("file-card").classList.contains("hidden")).toBe(true);
    expect(info).toHaveBeenCalledWith(expect.stringContaining("precheck=unreadable"));
  });

  it.each([
    ["decode", "clip.mp4"], ["decode", "photo.png"],
    ["compose", "clip.mp4"], ["compose", "photo.png"],
  ])("checks %s %s on the selection screen before making one upload", async (mode, filename) => {
    const fetchMock = mockApi({ jobStatuses: [{ state: "processing", stage: "Analyzing image" }] });
    await import("./app.js");
    await flush();
    document.getElementById(`mode-${mode}`).click();
    chooseVideo(filename);
    let resolveRead;
    const file = document.getElementById("file-input").files[0];
    const read = vi.fn(() => new Promise((resolve) => { resolveRead = resolve; }));
    vi.spyOn(file, "slice").mockReturnValue({ arrayBuffer: read });
    vi.useFakeTimers();
    document.getElementById("decode-btn").click();
    document.getElementById("decode-btn").click();
    await vi.advanceTimersByTimeAsync(0);
    expect(document.getElementById("file-check-status").textContent).toBe("Checking file…");
    expect(document.getElementById("screen-processing").classList.contains("hidden")).toBe(true);
    expect(document.getElementById("screen-home").classList.contains("hidden")).toBe(false);
    expect(read).toHaveBeenCalledTimes(1);
    expect(inspectCalls(fetchMock)).toHaveLength(0);
    expect(sessionStorage.getItem("orb-active-paid-job")).toBeNull();
    resolveRead(new ArrayBuffer(8));
    await vi.advanceTimersByTimeAsync(0);
    expect(inspectCalls(fetchMock)).toHaveLength(1);
    expect(inspectCalls(fetchMock)[0][0]).toContain(`/api/orb/${mode}/file`);
    expect(document.getElementById("file-check-status").classList.contains("hidden")).toBe(true);
    expect(document.getElementById("screen-processing").classList.contains("hidden")).toBe(false);
  });

  it.each(["NotReadableError", "NotFoundError"])("recovers locally from %s and makes only one POST", async (name) => {
    const fetchMock = mockApi();
    await import("./app.js");
    await flush();
    chooseVideo();
    const read = vi.fn().mockRejectedValueOnce(new DOMException("unavailable", name))
      .mockResolvedValue(new ArrayBuffer(8));
    vi.spyOn(document.getElementById("file-input").files[0], "slice").mockReturnValue({ arrayBuffer: read });
    vi.useFakeTimers();
    document.getElementById("decode-btn").click();
    await vi.advanceTimersByTimeAsync(299);
    expect(inspectCalls(fetchMock)).toHaveLength(0);
    expect(read).toHaveBeenCalledTimes(1);
    await vi.advanceTimersByTimeAsync(1);
    expect(read).toHaveBeenCalledTimes(2);
    expect(inspectCalls(fetchMock)).toHaveLength(1);
  });

  it("clears a persistently unreadable image and permits fresh same-name selection", async () => {
    const fetchMock = mockApi();
    await import("./app.js");
    await flush();
    chooseVideo("photo.png");
    const input = document.getElementById("file-input");
    // Simulate the picker value so clearing the failed selection is observable.
    Object.defineProperty(input, "value", { value: "C:\\fakepath\\photo.png", writable: true, configurable: true });
    const read = vi.fn().mockRejectedValue(new DOMException("locked", "NotReadableError"));
    vi.spyOn(input.files[0], "slice").mockReturnValue({ arrayBuffer: read });
    vi.useFakeTimers();
    document.getElementById("decode-btn").click();
    await vi.advanceTimersByTimeAsync(1100);
    expect(read).toHaveBeenCalledTimes(3);
    expect(inspectCalls(fetchMock)).toHaveLength(0);
    expect(input.value).toBe("");
    expect(document.getElementById("decode-btn").disabled).toBe(true);
    expect(document.getElementById("upload-error").textContent).toContain("Couldn't access this image");
    expect(document.getElementById("upload-error").textContent).toContain("selected image available to Orb");
    chooseVideo("photo.png");
    vi.spyOn(input.files[0], "slice").mockReturnValue({ arrayBuffer: () => Promise.resolve(new ArrayBuffer(8)) });
    document.getElementById("decode-btn").click();
    await vi.advanceTimersByTimeAsync(0);
    expect(inspectCalls(fetchMock)).toHaveLength(1);
  });

  it("times out a local read and never uploads after late resolution", async () => {
    const fetchMock = mockApi();
    await import("./app.js");
    await flush();
    chooseVideo();
    let resolveRead;
    const read = vi.fn(() => new Promise((resolve) => { resolveRead = resolve; }));
    vi.spyOn(document.getElementById("file-input").files[0], "slice").mockReturnValue({ arrayBuffer: read });
    vi.useFakeTimers();
    document.getElementById("decode-btn").click();
    await vi.advanceTimersByTimeAsync(5000);
    expect(inspectCalls(fetchMock)).toHaveLength(0);
    expect(document.getElementById("file-card").classList.contains("hidden")).toBe(true);
    expect(document.getElementById("upload-error").textContent).toContain("Couldn't access this video");
    resolveRead(new ArrayBuffer(8));
    await vi.advanceTimersByTimeAsync(10000);
    expect(inspectCalls(fetchMock)).toHaveLength(0);
    expect(read).toHaveBeenCalledTimes(1);
  });

  it("never uploads a superseded File after a fresh selection succeeds", async () => {
    const fetchMock = mockApi();
    await import("./app.js");
    await flush();
    chooseVideo();
    let resolveRead;
    vi.spyOn(document.getElementById("file-input").files[0], "slice").mockReturnValue({
      arrayBuffer: () => new Promise((resolve) => { resolveRead = resolve; }),
    });
    vi.useFakeTimers();
    document.getElementById("decode-btn").click();
    document.getElementById("file-clear").click();
    chooseVideo("replacement.mp4");
    vi.spyOn(document.getElementById("file-input").files[0], "slice").mockReturnValue({
      arrayBuffer: () => Promise.resolve(new ArrayBuffer(8)),
    });
    document.getElementById("decode-btn").click();
    await vi.advanceTimersByTimeAsync(0);
    expect(inspectCalls(fetchMock)).toHaveLength(1);
    expect(inspectCalls(fetchMock)[0][1].body.get("file").name).toBe("replacement.mp4");
    resolveRead(new ArrayBuffer(8));
    await vi.advanceTimersByTimeAsync(0);
    expect(inspectCalls(fetchMock)).toHaveLength(1);
  });

  it("rejects an empty file before checking or uploading", async () => {
    const fetchMock = mockApi();
    await import("./app.js");
    await flush();
    const input = document.getElementById("file-input");
    const file = new File([], "empty.mp4", { type: "video/mp4" });
    const slice = vi.spyOn(file, "slice");
    Object.defineProperty(input, "files", { value: [file], configurable: true });
    input.dispatchEvent(new Event("change"));
    document.getElementById("decode-btn").click();
    await flush();
    expect(slice).not.toHaveBeenCalled();
    expect(inspectCalls(fetchMock)).toHaveLength(0);
    expect(document.getElementById("upload-error").textContent).toContain("empty");
  });

  it("preserves the selected File when the picker is cancelled normally", async () => {
    mockApi();
    await import("./app.js");
    await flush();
    chooseVideo();
    document.getElementById("file-input").dispatchEvent(new MouseEvent("click", { bubbles: true }));
    document.getElementById("file-input").dispatchEvent(new Event("cancel"));
    expect(document.getElementById("file-name").textContent).toBe("clip.mp4");
    expect(document.getElementById("decode-btn").disabled).toBe(false);
  });

  it("makes no paid job request during local recovery, then submits one authenticated idempotent POST", async () => {
    const address = `0x${"11".repeat(20)}`;
    window.ethereum = { on: vi.fn(), request: vi.fn(async ({ method }) => {
      if (method === "eth_accounts") return [];
      if (method === "eth_requestAccounts") return [address];
      if (method === "eth_chainId") return "0x66eee";
      if (method === "personal_sign") return `0x${"cd".repeat(65)}`;
      throw new Error(`Unexpected wallet method: ${method}`);
    }) };
    const base = mockApi({ jobStatuses: [{ state: "processing", stage: "Analyzing image" }] });
    const fetchMock = vi.fn(async (url, options) => {
      if (url === "/api/orb/credits/config") return response({ enabled: true, chain_id: 421614, price_wei: "1000" });
      if (url === "/api/health") return response({ status: "ok", orb_ai_access: "credits" });
      if (url === "/api/orb/wallet/challenge") return response({ nonce: "nonce", message: "Sign in to Orb" });
      if (url === "/api/orb/wallet/sign-in") return response({ wallet: address, token: "signed-session",
        expires_at: Math.floor(Date.now() / 1000) + 3600 });
      if (url === "/api/orb/credits/balance") return response({ wallet: address, available: 1 });
      return base(url, options);
    });
    globalThis.fetch = fetchMock;
    await import("./app.js");
    await flush();
    document.getElementById("wallet-connect").click();
    await flush();
    document.getElementById("wallet-close").click();
    chooseVideo();
    const read = vi.fn().mockRejectedValueOnce(new DOMException("locked", "NotReadableError"))
      .mockResolvedValue(new ArrayBuffer(8));
    vi.spyOn(document.getElementById("file-input").files[0], "slice").mockReturnValue({ arrayBuffer: read });
    vi.useFakeTimers();
    document.getElementById("decode-btn").click();
    await vi.advanceTimersByTimeAsync(299);
    expect(inspectCalls(fetchMock)).toHaveLength(0);
    expect(fetchMock.mock.calls.filter(([url]) => String(url).startsWith("/api/jobs/"))).toHaveLength(0);
    expect(document.getElementById("wallet-balance").textContent).toContain("1 testnet credit");
    expect(sessionStorage.getItem("orb-active-paid-job")).toBeNull();
    await vi.advanceTimersByTimeAsync(1);
    const uploads = inspectCalls(fetchMock);
    expect(uploads).toHaveLength(1);
    expect(uploads[0][1].headers.Authorization).toBe("Bearer signed-session");
    const key = uploads[0][1].headers["X-Orb-Idempotency-Key"];
    expect(key).toBeTruthy();
    expect(uploads[0][0]).toContain(`upload_attempt_id=${key}`);
  });

  it("returns to the upload screen from results", async () => {
    mockApi();
    await import("./app.js");
    await flush();
    chooseVideo();
    document.getElementById("decode-btn").click();
    await flush();

    document.getElementById("menu-toggle").click();
    document.getElementById("menu-home").click();
    expect(document.getElementById("screen-home").classList.contains("hidden")).toBe(false);
    expect(document.getElementById("screen-results").classList.contains("hidden")).toBe(true);
    expect(document.getElementById("site-menu").classList.contains("hidden")).toBe(true);
    expect(document.getElementById("file-input").value).toBe("");
  });

  it("composes from an image and prevents repeated submission", async () => {
    const fetchMock = mockApi();
    await import("./app.js");
    await flush();
    document.getElementById("mode-compose").click();
    chooseVideo("reference.png");
    const button = document.getElementById("decode-btn");
    button.click();
    button.click();
    await flush();
    expect(inspectCalls(fetchMock)).toHaveLength(1);
    expect(inspectCalls(fetchMock)[0][0]).toContain("/api/orb/compose/file");
  });

  it("enhances a prompt and copies the result", async () => {
    const fetchMock = mockApi();
    Object.defineProperty(navigator, "clipboard", { value: { writeText: vi.fn(async () => {}) }, configurable: true });
    await import("./app.js");
    await flush();
    document.getElementById("mode-enhance").click();
    const input = document.getElementById("prompt-input");
    input.value = "a blue car";
    input.dispatchEvent(new Event("input"));
    document.getElementById("enhance-btn").click();
    await flush();
    expect(fetchMock.mock.calls.filter(([url]) => String(url) === "/api/orb/enhance")).toHaveLength(1);
    expect(document.getElementById("res-original-text").textContent).toBe("a blue car");
    document.getElementById("copy-prompt").click();
    await flush();
    expect(navigator.clipboard.writeText).toHaveBeenCalledWith("A blue car under soft daylight.");
  });

  it("shows prompt-specific processing labels during Enhance", async () => {
    mockApi({ jobStatuses: Array.from({ length: 10 }, () => ({ state: "processing", stage: "Enhancing prompt" })) });
    await import("./app.js");
    await flush();
    document.getElementById("mode-enhance").click();
    const input = document.getElementById("prompt-input");
    input.value = "A red balloon";
    input.dispatchEvent(new Event("input"));
    document.getElementById("enhance-btn").click();
    await flush();
    expect(document.getElementById("phase-text").textContent).toBe("Enhancing prompt…");
    expect(document.getElementById("step-list").textContent).not.toContain("Detecting scenes");
  });

  it("shows the Orb mark during video scene analysis and hides provider details", async () => {
    mockApi({ jobStatuses: [{ state: "processing", stage: "Analyzing scenes (2/3)" }] });
    await import("./app.js");
    await flush();
    chooseVideo();
    document.getElementById("decode-btn").click();
    await flush();
    const loader = document.querySelector("#screen-processing .orb-spin .orb-mark .orb-sphere");
    expect(loader).not.toBeNull();
    expect(document.querySelector(".brand-icon .orb-mark .orb-sphere")).not.toBeNull();
    expect(document.getElementById("phase-text").textContent).toBe("Analyzing scenes…");
    expect(document.getElementById("phase-detail").textContent).toBe("Scene 2 of 3");
    expect(document.getElementById("screen-processing").textContent).not.toMatch(/Gemini|FFmpeg|FFprobe/i);
  });

  it("keeps mode copy and controls distinct while switching without a reload", async () => {
    mockApi();
    await import("./app.js");
    await flush();
    chooseVideo();
    expect(document.getElementById("file-card").classList.contains("hidden")).toBe(false);
    document.getElementById("mode-compose").click();
    expect(document.getElementById("file-card").classList.contains("hidden")).toBe(true);
    expect(document.getElementById("mode-description").textContent).toContain("new generation-ready prompt");
    expect(document.getElementById("mode-compose").getAttribute("aria-current")).toBe("page");
    document.getElementById("mode-enhance").click();
    expect(document.getElementById("enhance-shell").classList.contains("hidden")).toBe(false);
    expect(document.getElementById("upload-shell").classList.contains("hidden")).toBe(true);
    expect(document.getElementById("mode-description").textContent).toContain("does not generate media yet");
    document.getElementById("mode-decode").click();
    expect(document.getElementById("mode-description").textContent).toContain("plausible generation prompt");
    expect(document.getElementById("enhance-shell").classList.contains("hidden")).toBe(true);
    expect(document.querySelectorAll(".mode-pill.active")).toHaveLength(1);
  });

  it("replaces provider-specific job errors with Orb wording", async () => {
    mockApi({ jobStatuses: [{ state: "error", stage: "Interrupted", error: "Gemini provider unavailable" }] });
    await import("./app.js");
    await flush();
    chooseVideo();
    document.getElementById("decode-btn").click();
    await flush();
    expect(document.getElementById("job-error").textContent).toContain("Orb AI is temporarily unavailable");
    expect(document.getElementById("screen-processing").textContent).not.toMatch(/Gemini/i);
  });

  it("opens Create information without enabling Create or starting an AI operation", async () => {
    const fetchMock = mockApi();
    await import("./app.js");
    await flush();
    const before = inspectCalls(fetchMock).length;
    const create = document.getElementById("mode-create");
    const info = document.getElementById("create-info");
    const popover = document.getElementById("create-popover");
    create.click();
    expect(document.querySelector(".mode-pill.active").id).toBe("mode-decode");
    expect(inspectCalls(fetchMock)).toHaveLength(before);
    info.focus();
    info.click();
    expect(info.getAttribute("aria-expanded")).toBe("true");
    expect(popover.classList.contains("hidden")).toBe(false);
    expect(popover.textContent).toContain("advanced image and video generation models");
    expect(popover.textContent).toContain("Create → realize");
    expect(document.querySelector("#create-popover-close svg path").getAttribute("d")).toBe("M5 5 19 19M19 5 5 19");
    expect(document.getElementById("create-popover-close").focus).toHaveBeenCalled();
    document.dispatchEvent(new KeyboardEvent("keydown", { key: "Escape", bubbles: true }));
    expect(popover.classList.contains("hidden")).toBe(true);
    expect(info.focus).toHaveBeenCalled();
    info.click();
    document.body.click();
    expect(info.getAttribute("aria-expanded")).toBe("false");
    info.click();
    document.getElementById("create-popover-close").click();
    expect(popover.classList.contains("hidden")).toBe(true);
    expect(inspectCalls(fetchMock)).toHaveLength(before);
  });

  it("uses a 1005px desktop frame, atmospheric Orb motion, and mobile safe-area rules", () => {
    const style = document.createElement("style");
    style.textContent = css;
    document.head.appendChild(style);
    expect(getComputedStyle(document.querySelector(".app-frame")).maxWidth).toBe("1005px");
    expect(getComputedStyle(document.getElementById("wallet-close")).display).toBe("grid");
    expect(css).toMatch(/\.about-close\s*\{[^}]*place-items:\s*center/);
    expect(css).toMatch(/@media \(max-width: 600px\)[\s\S]*?safe-area-inset-bottom/);
    expect(getComputedStyle(document.getElementById("create-popover-close")).display).toBe("grid");
    expect(css).toMatch(/\.orb-sphere::before\s*\{[^}]*left:\s*-70%;[^}]*width:\s*70%;[^}]*animation:\s*orb-prograde 6s/);
    expect(css).toMatch(/@keyframes orb-prograde[\s\S]*?translateX\(0\)[\s\S]*?translateX\(250%\)/);
    expect(css).toMatch(/\.orb-spin \.orb-mark\s*\{\s*width:\s*70px;\s*height:\s*70px/);
    expect(css).toMatch(/\.orb-spin \.orb-sphere::before\s*\{\s*animation-duration:\s*2\.4s/);
    expect(css).toMatch(/@media \(prefers-reduced-motion: reduce\)[\s\S]*?\.orb-sphere::before[^}]*animation:\s*none/);
    expect(css).toMatch(/@media \(max-width: 600px\)[\s\S]*?\.mode-pills\s*\{\s*grid-template-columns:\s*repeat\(2/);
    expect(document.querySelector("#wallet-close svg path").getAttribute("d")).toBe("M5 5 19 19M19 5 5 19");
  });

  it("places the compact hero and all four mode controls before the active workspace", () => {
    expect(document.querySelector(".hero h1").textContent).toBe("Understand visuals.Create better prompts.");
    const modes = document.querySelector(".mode-pills");
    expect(modes.compareDocumentPosition(document.getElementById("upload-shell")) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    for (const mode of ["decode", "compose", "enhance"]) {
      const button = document.getElementById(`mode-${mode}`);
      expect(button.querySelector("svg[aria-hidden=true]")).not.toBeNull();
      expect(button.querySelector("strong").textContent.toLowerCase()).toBe(mode);
      expect(button.querySelector("small").textContent).not.toBe("");
    }
    expect(document.querySelector("#mode-create button").id).toBe("create-info");
    expect(document.getElementById("mode-create").matches("button,a")).toBe(false);
  });

  it("mirrors only authenticated credits in the header and clears them on disconnect", async () => {
    const context = await startPaidJobWithExpiredSession();
    document.getElementById("wallet-connect").click();
    await flush();
    await vi.waitFor(() => expect(document.getElementById("res-prompt").textContent).toBe("Recovered durable prompt."));
    const capsule = document.getElementById("header-credits");
    expect(capsule.classList.contains("hidden")).toBe(false);
    expect(document.getElementById("header-credit-value").textContent).toBe("0");
    // No purchase or new visual reservation is introduced by this read-only display.
    expect(inspectCalls(context.fetchMock)).toHaveLength(1);
    expect(context.fetchMock.mock.calls.filter(([url]) => String(url).includes("/credits/quotes"))).toHaveLength(0);
    document.getElementById("wallet-disconnect").click();
    await flush();
    expect(capsule.classList.contains("hidden")).toBe(true);
    expect(document.getElementById("header-wallet").textContent).toBe("Connect Wallet");
  });

  it("keeps real result content in distinct prompt, analysis and refinement surfaces", async () => {
    const api = mockApi();
    const original = api.getMockImplementation();
    api.mockImplementation(async (url, options) => {
      if (String(url).endsWith("/result")) {
        const result = await original(url, options);
        const body = await result.json();
        return response({ ...body, refinements: ["Keep the soft lighting."] });
      }
      return original(url, options);
    });
    await import("./app.js");
    await flush();
    chooseVideo();
    document.getElementById("decode-btn").click();
    await vi.waitFor(() => expect(document.getElementById("screen-results").classList.contains("hidden")).toBe(false));
    expect(document.querySelector(".result-grid #res-analysis-card").textContent).toContain("Centered subject");
    expect(document.querySelector(".result-grid .prompt-card #res-prompt").textContent).toBe("A blue car under soft daylight.");
    expect(document.getElementById("res-refinements").parentElement.className).toBe("result-grid");
    expect(document.getElementById("res-refinements").textContent).toContain("Keep the soft lighting.");
  });

  it("provides opaque glass fallbacks, non-intercepting decoration and reduced motion", () => {
    expect(css).toContain("--glass-blur: 20px");
    expect(css).toMatch(/@supports[\s\S]*backdrop-filter/);
    expect(css).toMatch(/\.topbar, \.upload-shell, \.about-panel, \.site-menu, \.create-popover[\s\S]*background: #eff8ff/);
    expect(css).toMatch(/\.atmosphere \{[^}]*pointer-events: none/);
    expect(css).toMatch(/\.upload-shell::before \{[^}]*pointer-events: none/);
    expect(css).toMatch(/prefers-reduced-motion: reduce[\s\S]*\.card \{ animation: none/);
    expect(html).not.toMatch(/<canvas|<iframe|<script[^>]+https:/i);
  });

});
