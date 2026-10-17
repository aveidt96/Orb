import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { initWallet } from "./wallet.js";

const html = readFileSync(resolve(process.cwd(), "web/index.html"), "utf8");
const account = `0x${"11".repeat(20)}`;
const disabledMessage = "Testnet credits are not configured on this Orb server.";
const readyConfig = {
  enabled: true, chain_id: 421614,
  payment_methods: {
    native_eth: { enabled: true, price_wei: "1000000000000" },
    usdg: { enabled: true, token_contract: "0xFFC95faa3d63Cde504a05B567C600B78C0b41892",
      token_decimals: 6, price_base_units: "3000" },
  },
};
const response = (body, status = 200) => ({ ok: status >= 200 && status < 300, status, json: async () => body });
const feedback = () => document.getElementById("wallet-feedback").textContent;
const header = () => document.getElementById("header-wallet");
const settle = () => vi.advanceTimersByTimeAsync(0);

function setup(configRequest, { accountsError = false, networkError = false, balanceStatus = 200 } = {}) {
  const provider = { on: vi.fn(), request: vi.fn(async ({ method }) => {
    if (method === "eth_chainId") {
      if (networkError) throw new Error("Wallet RPC unavailable");
      return "0x66eee";
    }
    if (method === "eth_accounts" && accountsError) throw new Error("Wallet restoration unavailable");
    if (method === "eth_accounts" || method === "eth_requestAccounts") return [account];
    if (method === "personal_sign") return "synthetic-signature";
    throw new Error(`Unexpected wallet operation: ${method}`);
  }) };
  window.ethereum = provider;
  const configFetch = vi.fn(configRequest || (() => response(readyConfig)));
  const fetchMock = vi.fn(async (url, options) => {
    if (url === "/api/orb/credits/config") return configFetch(options);
    if (url === "/api/orb/credits/balance") return response(balanceStatus === 200
      ? { available: 2 } : { detail: "Session unavailable" }, balanceStatus);
    if (url === "/api/orb/wallet/challenge") return response({ nonce: "synthetic-nonce", message: "Sign in to Orb" });
    if (url === "/api/orb/wallet/sign-in") return response({ wallet: account, token: "synthetic-session-token",
      expires_at: Math.floor(Date.now() / 1000) + 3600 });
    throw new Error(`Unexpected API operation: ${url}`);
  });
  globalThis.fetch = fetchMock;
  const wallet = initWallet({ onBalance: vi.fn() });
  return { wallet, configFetch, fetchMock, provider };
}

function savedSession() {
  sessionStorage.setItem("orb-wallet-session", JSON.stringify({ address: account,
    token: "synthetic-session-token", expiresAt: Date.now() / 1000 + 3600 }));
}

describe("Orb credit configuration availability", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    sessionStorage.clear();
    document.open(); document.write(html); document.close();
    HTMLElement.prototype.focus = vi.fn();
  });
  afterEach(() => {
    vi.clearAllTimers(); vi.useRealTimers(); vi.restoreAllMocks(); vi.unstubAllEnvs();
    delete window.ethereum;
  });

  it("shows loading immediately and keeps header clicks from starting authentication", async () => {
    let finish;
    const { wallet, configFetch, provider } = setup(() => new Promise((resolve) => { finish = resolve; }));
    expect(feedback()).toBe("Loading credit options…");
    header().click(); header().click();
    expect(feedback()).toBe("Loading credit options…");
    expect(configFetch).toHaveBeenCalledTimes(1);
    expect(provider.request).not.toHaveBeenCalled();
    expect(wallet.isEnabled()).toBe(false);
    finish(response(readyConfig)); await settle();
    expect(wallet.isEnabled()).toBe(true);
  });

  it("accepts a valid enabled response and renders both server payment methods", async () => {
    const { wallet } = setup(); await settle();
    expect(wallet.isEnabled()).toBe(true);
    expect(feedback()).toBe("Connect a wallet to see your testnet credits.");
    expect([...document.querySelectorAll("[data-method]")].map((button) => button.textContent))
      .toEqual(["Test ETH", "Paxos USDG"]);
    expect(document.getElementById("wallet-connect").disabled).toBe(false);
  });

  it("shows disabled only for an explicit false response and never retries it", async () => {
    const { wallet, configFetch, provider } = setup(() => response({ enabled: false }));
    await settle(); header().click(); await vi.advanceTimersByTimeAsync(120000);
    expect(feedback()).toBe(disabledMessage);
    expect(wallet.isEnabled()).toBe(false);
    expect(configFetch).toHaveBeenCalledTimes(1);
    expect(provider.request).not.toHaveBeenCalled();
  });

  it.each([5000, 20000])("recovers from a %s ms delayed config without refresh", async (duration) => {
    let resolveFirst;
    let attempts = 0;
    const { wallet, configFetch } = setup(({ signal }) => new Promise((resolve, reject) => {
      if (++attempts > 1) return resolve(response(readyConfig));
      resolveFirst = resolve;
      signal.addEventListener("abort", () => reject(new DOMException("Timed out", "AbortError")));
    }));
    await vi.advanceTimersByTimeAsync(duration);
    expect(feedback()).not.toBe(disabledMessage);
    // An aborted request's late response must not overwrite recovered config.
    resolveFirst(response(duration > 15000 ? { enabled: false } : readyConfig)); await settle();
    expect(wallet.isEnabled()).toBe(true);
    expect([...document.querySelectorAll("[data-method]")].map((button) => button.textContent))
      .toEqual(["Test ETH", "Paxos USDG"]);
  });

  it.each(["network", "CORS", 503, 401, 403])("retries %s failure and clears the temporary warning on success", async (failure) => {
    let attempts = 0;
    const { wallet, configFetch, provider, fetchMock } = setup(() => {
      if (++attempts > 1) return response(readyConfig);
      if (typeof failure === "string") throw new TypeError("Failed to fetch");
      return response({ detail: "Request failed" }, failure);
    });
    await settle();
    expect(feedback()).toBe("Credit service is starting…");
    header().click(); header().click(); await settle();
    expect(feedback()).not.toBe(disabledMessage);
    expect(provider.request).not.toHaveBeenCalled();
    expect(configFetch).toHaveBeenCalledTimes(1);
    await vi.advanceTimersByTimeAsync(1000);
    expect(wallet.isEnabled()).toBe(true);
    expect(feedback()).toBe("Connect a wallet to see your testnet credits.");
    expect(configFetch).toHaveBeenCalledTimes(2);
    expect(document.querySelectorAll("[data-method]")).toHaveLength(2);
    expect(fetchMock.mock.calls.every(([path]) => path === "/api/orb/credits/config")).toBe(true);
  });

  it("backs off 1, 2, 4, then 8 seconds and recovers from several failures", async () => {
    let attempts = 0;
    const { wallet, configFetch } = setup(() => ++attempts <= 4 ? response({}, 503) : response(readyConfig));
    await settle();
    for (const duration of [1000, 2000, 4000, 8000]) {
      const previous = configFetch.mock.calls.length;
      await vi.advanceTimersByTimeAsync(duration - 1);
      expect(configFetch).toHaveBeenCalledTimes(previous);
      expect(feedback()).not.toBe(disabledMessage);
      await vi.advanceTimersByTimeAsync(1);
      expect(configFetch).toHaveBeenCalledTimes(previous + 1);
    }
    expect(wallet.isEnabled()).toBe(true);
  });

  it.each([null, {}, [], { enabled: "false" }, { enabled: 0 }, { enabled: true, payment_methods: {} },
    { enabled: true, price_wei: "invalid" }])("treats invalid config %j as unavailable rather than disabled", async (body) => {
    let attempts = 0;
    const { wallet } = setup(() => response(++attempts === 1 ? body : readyConfig));
    await settle(); header().click();
    expect(feedback()).toBe("Credit service is starting…");
    expect(wallet.isEnabled()).toBe(false);
    await vi.advanceTimersByTimeAsync(1000);
    expect(wallet.isEnabled()).toBe(true);
  });

  it("treats malformed JSON as unavailable and retries", async () => {
    let attempts = 0;
    setup(() => ++attempts === 1 ? { ok: true, json: async () => { throw new SyntaxError("Invalid JSON"); } }
      : response(readyConfig));
    await settle();
    expect(feedback()).toBe("Credit service is starting…");
    await vi.advanceTimersByTimeAsync(1000);
    expect(feedback()).toBe("Connect a wallet to see your testnet credits.");
  });

  it("times out a stalled request and aborts it before issuing the next request", async () => {
    let active = 0, maximum = 0, attempts = 0;
    const { wallet, configFetch } = setup(({ signal }) => {
      if (++attempts > 1) { maximum = Math.max(maximum, active + 1); return response(readyConfig); }
      active += 1; maximum = Math.max(maximum, active);
      return new Promise((resolve, reject) => signal.addEventListener("abort", () => {
        active -= 1; reject(new DOMException("Timed out", "AbortError"));
      }));
    });
    await vi.advanceTimersByTimeAsync(14999); header().click();
    expect(feedback()).toBe("Loading credit options…");
    await vi.advanceTimersByTimeAsync(1);
    expect(feedback()).toBe("Credit service is starting…");
    expect(configFetch.mock.calls[0][0].signal.aborted).toBe(true);
    await vi.advanceTimersByTimeAsync(1000);
    expect(wallet.isEnabled()).toBe(true);
    expect(maximum).toBe(1);
  });

  it("bounds repeated failures and lets the header start a fresh retry cycle", async () => {
    let recovering = false;
    const { wallet, configFetch } = setup(() => response(recovering ? readyConfig : {}, recovering ? 200 : 503));
    await vi.advanceTimersByTimeAsync(120000);
    expect(configFetch).toHaveBeenCalledTimes(12);
    expect(feedback()).toBe("Credit service temporarily unavailable. Try again.");
    await vi.advanceTimersByTimeAsync(120000);
    expect(configFetch).toHaveBeenCalledTimes(12);
    recovering = true; header().click(); await settle();
    expect(wallet.isEnabled()).toBe(true);
    expect(configFetch).toHaveBeenCalledTimes(13);
  });

  it("bounds stalled requests by the overall two-minute deadline", async () => {
    const { configFetch } = setup(({ signal }) => new Promise((resolve, reject) => {
      signal.addEventListener("abort", () => reject(new DOMException("Timed out", "AbortError")));
    }));
    await vi.advanceTimersByTimeAsync(120000);
    const count = configFetch.mock.calls.length;
    expect(count).toBeGreaterThan(1); expect(count).toBeLessThanOrEqual(12);
    expect(feedback()).toBe("Credit service temporarily unavailable. Try again.");
    await vi.advanceTimersByTimeAsync(120000);
    expect(configFetch).toHaveBeenCalledTimes(count);
  });

  it("does not erase successful config when eth_accounts restoration fails", async () => {
    const { wallet, provider, configFetch } = setup(null, { accountsError: true });
    await settle();
    expect(wallet.isEnabled()).toBe(true);
    expect(feedback()).toBe("Could not restore wallet session. Connect and sign again.");
    expect(document.getElementById("wallet-connect").disabled).toBe(false);
    header().click(); await settle();
    expect(wallet.isAuthenticated()).toBe(true);
    expect(provider.request.mock.calls.filter(([arg]) => arg.method === "personal_sign")).toHaveLength(1);
    expect(configFetch).toHaveBeenCalledTimes(1);
  });

  it("keeps config when saved-session restoration throws", async () => {
    sessionStorage.setItem("orb-wallet-session", JSON.stringify({ address: 42,
      token: "synthetic-session-token", expiresAt: Date.now() / 1000 + 3600 }));
    const { wallet, configFetch } = setup(); await settle();
    expect(wallet.isEnabled()).toBe(true);
    expect(feedback()).toBe("Could not restore wallet session. Connect and sign again.");
    expect(configFetch).toHaveBeenCalledTimes(1);
  });

  it.each([401, 503])("keeps config when restored-session balance returns %s", async (balanceStatus) => {
    savedSession();
    const { wallet, configFetch } = setup(null, { balanceStatus }); await settle();
    expect(wallet.isEnabled()).toBe(true);
    expect(wallet.isAuthenticated()).toBe(false);
    expect(feedback()).not.toBe(disabledMessage);
    expect(configFetch).toHaveBeenCalledTimes(1);
    if (balanceStatus === 401) expect(feedback()).toBe("Wallet session expired. Sign again.");
  });

  it("keeps config available after wallet network restoration fails", async () => {
    const { wallet, configFetch } = setup(null, { networkError: true }); await settle();
    expect(wallet.isEnabled()).toBe(true);
    expect(document.getElementById("wallet-network").textContent).toBe("Wallet network unavailable. Try again.");
    expect(feedback()).not.toBe(disabledMessage);
    expect(configFetch).toHaveBeenCalledTimes(1);
  });

  it("activates a 10-credit Judge Demo session via the header Judge Demo button without a Web3 wallet", async () => {
    delete window.ethereum;
    const judgeWallet = "0x4a75646765202610160000000000000000000001";
    globalThis.fetch = vi.fn(async (url, options) => {
      if (url === "/api/orb/credits/config") return response({ enabled: false });
      if (url === "/api/orb/judge-session") {
        const body = JSON.parse(options.body);
        if (body.code !== "opencv-2026") return response({ detail: "Invalid judge demo access code." }, 401);
        return response({
          wallet: judgeWallet, token: "judge-session-token",
          expires_at: Math.floor(Date.now() / 1000) + 86400,
          judge_demo: true, credits: 10,
          balance: { wallet: judgeWallet, available: 10, reserved: 0, consumed: 0, granted: 10, judge_demo: true },
        });
      }
      throw new Error(`Unexpected API operation: ${url}`);
    });
    const onBalance = vi.fn();
    const wallet = initWallet({ onBalance });
    await settle();
    document.getElementById("header-judge").click();
    expect(document.getElementById("wallet-panel").classList.contains("hidden")).toBe(false);
    expect(document.getElementById("judge-demo-form").classList.contains("hidden")).toBe(false);
    document.getElementById("judge-code-input").value = "opencv-2026";
    document.getElementById("judge-demo-form").dispatchEvent(new Event("submit", { cancelable: true }));
    await settle();
    expect(wallet.isJudgeDemo()).toBe(true);
    expect(wallet.hasCredit()).toBe(true);
    expect(wallet.headers()).toEqual({ Authorization: "Bearer judge-session-token" });
    expect(document.getElementById("header-judge").textContent).toBe("Judge Demo · Active");
    expect(document.getElementById("wallet-balance").textContent).toBe("10 demo credits available");
    expect(document.getElementById("header-credit-label").textContent).toBe("Demo credits");
    expect(onBalance).toHaveBeenLastCalledWith(10);
  });

  it("auto-unlocks Judge Demo Mode from ?judge=<code> on load and strips the query param via history.replaceState", async () => {
    delete window.ethereum;
    const judgeWallet = "0x4a75646765202610160000000000000000000002";
    const originalUrl = window.location.href;
    window.history.replaceState({}, "", "/?judge=auto-code-2026&keep=1");
    const replaceSpy = vi.spyOn(window.history, "replaceState");
    globalThis.fetch = vi.fn(async (url, options) => {
      if (url === "/api/orb/credits/config") return response(readyConfig);
      if (url === "/api/orb/judge-session") {
        const body = JSON.parse(options.body);
        expect(body.code).toBe("auto-code-2026");
        return response({
          wallet: judgeWallet, token: "auto-judge-token",
          expires_at: Math.floor(Date.now() / 1000) + 86400,
          judge_demo: true, credits: 10,
          balance: { wallet: judgeWallet, available: 10, reserved: 0, consumed: 0, granted: 10, judge_demo: true },
        });
      }
      throw new Error(`Unexpected API operation: ${url}`);
    });
    const wallet = initWallet({ onBalance: vi.fn() });
    await settle();
    expect(replaceSpy).toHaveBeenCalledWith({}, "", "/?keep=1");
    expect(window.location.search).toBe("?keep=1");
    expect(wallet.isJudgeDemo()).toBe(true);
    expect(wallet.hasCredit()).toBe(true);
    expect(feedback()).toContain("10 demo credits unlocked");
    window.history.replaceState({}, "", originalUrl);
  });
});

