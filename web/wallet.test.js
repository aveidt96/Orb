import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { initWallet } from "./wallet.js";

const html = readFileSync(resolve(process.cwd(), "web/index.html"), "utf8");
const firstAddress = `0x${"11".repeat(20)}`;
const secondAddress = `0x${"22".repeat(20)}`;
const sessionKey = "orb-wallet-session";
const expectedFees = { gas: "0x1d4c0", maxFeePerGas: "0x98", maxPriorityFeePerGas: "0x2" };

function response(body, status = 200) {
  return { ok: status >= 200 && status < 300, status, json: async () => body };
}

async function flush() {
  for (let index = 0; index < 6; index += 1) await new Promise((resolve) => setTimeout(resolve, 0));
}

function setup({ account = firstAddress, balanceStatus = 200, revokeError = null, usdg = false, dual = false, paymentError = null, quoteChange = null, judgeEnabled = false, quoteStatus = 200 } = {}) {
  let selectedAccount = account;
  let currentBalanceStatus = balanceStatus;
  let sessionValid = true;
  const handlers = new Map();
  const provider = {
    on: vi.fn((event, listener) => handlers.set(event, listener)),
    request: vi.fn(async ({ method }) => {
      if (method === "eth_accounts") return selectedAccount ? [selectedAccount] : [];
      if (method === "eth_requestAccounts") return selectedAccount ? [selectedAccount] : [];
      if (method === "eth_chainId") return "0x66eee";
      if (method === "personal_sign") return `0x${"cd".repeat(65)}`;
      if (method === "eth_getBlockByNumber") return { baseFeePerGas: "0x64" };
      if (method === "eth_maxPriorityFeePerGas") return "0x2";
      if (method === "eth_estimateGas") return "0x186a0";
      if (method === "eth_sendTransaction") {
        if (paymentError) throw paymentError;
        return `0x${"ab".repeat(32)}`;
      }
      if (method === "wallet_revokePermissions") {
        if (revokeError) throw revokeError;
        return null;
      }
      throw new Error(`Unexpected wallet method: ${method}`);
    }),
  };
  window.ethereum = provider;
  const fetchMock = vi.fn(async (url, options = {}) => {
    const path = String(url);
    if (path === "/api/orb/credits/config" && dual) return response({ enabled: true, chain_id: 421614,
      deployment_target: "usdg-staging", payment_methods: {
        native_eth: { enabled: true, price_wei: "1000" },
        usdg: { enabled: true, token_contract: "0xFFC95faa3d63Cde504a05B567C600B78C0b41892", token_decimals: 6, price_base_units: "3000" },
      } });
    if (path === "/api/orb/credits/config") return response(usdg ? { enabled: true, payment_method: "usdg",
      deployment_target: "usdg-staging",
      token_contract: "0xFFC95faa3d63Cde504a05B567C600B78C0b41892", token_decimals: 6, chain_id: 421614 }
      : { enabled: true, price_wei: "1000", judge_demo_enabled: judgeEnabled });
    if (path === "/api/orb/credits/quotes") {
      if (quoteStatus !== 200) return response({ detail: "Not Found" }, quoteStatus);
      const receiver = `0x${"33".repeat(20)}`;
      const quote = { quote_id: "usdg-quote", chain_id: 421614, payment_method: "usdg", wallet: selectedAccount,
        token_symbol: "USDG", token_contract: "0xFFC95faa3d63Cde504a05B567C600B78C0b41892", token_decimals: 6,
        receiver, to: "0xFFC95faa3d63Cde504a05B567C600B78C0b41892", value_wei: "0", credits: JSON.parse(options.body).credits,
        amount_base_units: String(3000 * JSON.parse(options.body).credits), expires_at: Math.floor(Date.now() / 1000) + 900,
        data: `0xa9059cbb${receiver.slice(2).padStart(64, "0")}${(BigInt(3000 * JSON.parse(options.body).credits)).toString(16).padStart(64, "0")}` };
      if (!usdg && (!dual || JSON.parse(options.body).payment_method === "native_eth")) {
        Object.assign(quote, { quote_id: "eth-quote", payment_method: "native_eth", to: receiver,
          value_wei: String(1000 * JSON.parse(options.body).credits), data: "0x4f524231" + "12".repeat(16) });
      }
      quoteChange?.(quote);
      return response(quote);
    }
    if (path === "/api/orb/credits/quotes/usdg-quote/verify") return response({ credits: 3, balance: { available: 5 } });
    if (path === "/api/orb/credits/quotes/eth-quote/verify") return response({ credits: 3, balance: { available: 5 } });
    if (path === "/api/orb/wallet/challenge") return response({ nonce: "nonce", message: "Sign in to Orb" });
    if (path === "/api/orb/wallet/sign-in") {
      sessionValid = true;
      return response({ wallet: selectedAccount,
        token: "test-session-token", expires_at: Math.floor(Date.now() / 1000) + 3600 });
    }
    if (path === "/api/orb/wallet/logout") {
      if (!sessionValid || options.headers?.Authorization !== "Bearer test-session-token") {
        return response({ detail: "Session expired" }, 401);
      }
      sessionValid = false;
      return response({ status: "signed_out" });
    }
    if (path === "/api/orb/credits/balance" && !sessionValid) return response({ detail: "Session expired" }, 401);
    if (path === "/api/orb/credits/balance") return response(currentBalanceStatus === 200
      ? { wallet: selectedAccount, available: 2 } : { detail: "Session unavailable" }, currentBalanceStatus);
    throw new Error(`Unexpected API request: ${path}`);
  });
  globalThis.fetch = fetchMock;
  return {
    provider, fetchMock,
    changeAccount(next) {
      selectedAccount = next;
      handlers.get("accountsChanged")?.(next ? [next] : []);
    },
    setBalanceStatus(status) { currentBalanceStatus = status; },
  };
}

function renderWallet() {
  document.open();
  document.write(html);
  document.close();
  return initWallet({ onBalance: vi.fn() });
}

function selectCredits(credits) {
  document.querySelector(`#credit-count [data-credits="${credits}"]`).click();
}

describe("Orb wallet authentication UI", () => {
  it.each([false, true])("handles a wallet-side 404 without resubmitting or granting credits (USDG=%s)", async (usdg) => {
    const { provider, fetchMock } = setup({ usdg, paymentError: new Error("Request failed with status code 404") });
    initWallet({ onBalance: vi.fn() });
    await flush();
    document.getElementById("wallet-connect").click();
    await flush();
    document.getElementById("wallet-buy").click();
    await flush();
    expect(document.getElementById("wallet-feedback").textContent).toMatch(/wallet.*service returned 404/i);
    expect(document.getElementById("wallet-feedback").textContent).toContain("Check wallet activity");
    expect(document.getElementById("wallet-switch").classList.contains("hidden")).toBe(false);
    expect(document.getElementById("wallet-switch").textContent).toBe("Register Arbitrum Sepolia");
    expect(provider.request.mock.calls.filter(([r]) => r.method === "eth_sendTransaction")).toHaveLength(1);
    expect(fetchMock.mock.calls.filter(([url]) => String(url).includes("/verify"))).toHaveLength(0);
    expect(fetchMock.mock.calls.filter(([url]) => url === "/api/orb/judge-session")).toHaveLength(0);
    expect(sessionStorage.getItem("orb-sepolia-pending-payment")).toBeNull();
    expect(document.getElementById("wallet-balance").textContent).toContain("2 testnet credits");
  });

  it("never offers judge access on the public URL even if an old backend advertises it", async () => {
    setup({ judgeEnabled: true, paymentError: new Error("Request failed with status code 404") });
    initWallet({ onBalance: vi.fn() });
    await flush(); document.getElementById("wallet-connect").click(); await flush();
    document.getElementById("wallet-buy").click(); await flush();
    expect(document.getElementById("wallet-feedback").textContent).not.toContain("Judge Demo");
    document.getElementById("header-judge").click();
    expect(document.getElementById("header-judge").classList.contains("hidden")).toBe(true);
    expect(document.getElementById("judge-demo-form").classList.contains("hidden")).toBe(true);
  });

  it("distinguishes an Orb quote endpoint 404 from a wallet provider 404", async () => {
    const { provider } = setup({ quoteStatus: 404 });
    initWallet({ onBalance: vi.fn() });
    await flush(); document.getElementById("wallet-connect").click(); await flush();
    document.getElementById("wallet-buy").click(); await flush();
    expect(document.getElementById("wallet-feedback").textContent).toContain("quote endpoint");
    expect(provider.request.mock.calls.filter(([r]) => r.method === "eth_sendTransaction")).toHaveLength(0);
    expect(document.getElementById("wallet-switch").textContent).not.toBe("Register Arbitrum Sepolia");
  });

  it("registers the exact official RPC on a user-requested network repair, switches, and never resends", async () => {
    const { provider } = setup({ paymentError: new Error("Request failed with status code 404") });
    const original = provider.request.getMockImplementation();
    provider.request.mockImplementation((request) => ["wallet_addEthereumChain", "wallet_switchEthereumChain"].includes(request.method)
      ? Promise.resolve(null) : original(request));
    initWallet({ onBalance: vi.fn() });
    await flush(); document.getElementById("wallet-connect").click(); await flush();
    document.getElementById("wallet-buy").click(); await flush();
    document.getElementById("wallet-switch").click(); await flush();
    expect(provider.request).toHaveBeenCalledWith({ method: "wallet_addEthereumChain", params: [{ chainId: "0x66eee",
      chainName: "Arbitrum Sepolia", nativeCurrency: { name: "Sepolia Ether", symbol: "ETH", decimals: 18 },
      rpcUrls: ["https://sepolia-rollup.arbitrum.io/rpc"], blockExplorerUrls: ["https://sepolia.arbiscan.io"] }] });
    expect(provider.request).toHaveBeenCalledWith({ method: "wallet_switchEthereumChain", params: [{ chainId: "0x66eee" }] });
    expect(provider.request.mock.calls.filter(([r]) => r.method === "eth_sendTransaction")).toHaveLength(1);
  });
  beforeEach(() => {
    vi.spyOn(console, "warn").mockImplementation(() => {});
    sessionStorage.clear();
    document.open();
    document.write(html);
    document.close();
    HTMLElement.prototype.focus = vi.fn();
  });

  afterEach(() => {
    if (vi.isFakeTimers()) {
      vi.clearAllTimers();
      expect(vi.getTimerCount()).toBe(0);
    }
    vi.useRealTimers();
    vi.restoreAllMocks();
    vi.unstubAllEnvs();
    delete window.ethereum;
  });

  it("shows Connected immediately after signed authentication", async () => {
    const { provider, fetchMock } = setup();
    const wallet = renderWallet();
    await flush();
    expect(document.getElementById("wallet-connect").textContent).toBe("Sign again");
    expect(document.getElementById("header-wallet").textContent).toBe("Connect Wallet");
    document.getElementById("header-wallet").click();
    await flush();

    const button = document.getElementById("wallet-connect");
    expect(button.textContent).toBe("Connected");
    expect(button.disabled).toBe(true);
    expect(document.getElementById("header-wallet").textContent).toBe("Connected");
    expect(document.getElementById("header-wallet").getAttribute("aria-expanded")).toBe("true");
    document.getElementById("wallet-close").click();
    expect(document.getElementById("header-wallet").getAttribute("aria-expanded")).toBe("false");
    document.getElementById("header-wallet").click();
    expect(document.getElementById("wallet-panel").classList.contains("hidden")).toBe(false);
    expect(provider.request.mock.calls.filter(([request]) => request.method === "personal_sign")).toHaveLength(1);
    expect(wallet.isAuthenticated()).toBe(true);
    expect(document.getElementById("wallet-address").title).toBe(firstAddress);
    expect(document.getElementById("wallet-balance").textContent).toContain("2 testnet credits");
    expect(provider.request.mock.calls.filter(([request]) => request.method === "personal_sign")).toHaveLength(1);
    expect(fetchMock.mock.calls.filter(([url]) => url === "/api/orb/credits/balance")).toHaveLength(1);
  });

  it("accepts the account event emitted during an initial MetaMask connection", async () => {
    const { changeAccount, provider } = setup({ account: null });
    const ordinaryRequest = provider.request.getMockImplementation();
    provider.request.mockImplementation((request) => {
      if (request.method === "eth_requestAccounts") {
        changeAccount(firstAddress);
        return Promise.resolve([firstAddress]);
      }
      return ordinaryRequest(request);
    });
    const wallet = renderWallet();
    await flush();
    expect(document.getElementById("wallet-connect").textContent).toBe("Connect and sign");
    document.getElementById("wallet-connect").click();
    await flush();
    expect(wallet.isAuthenticated()).toBe(true);
    expect(document.getElementById("wallet-connect").textContent).toBe("Connected");
    expect(document.getElementById("header-wallet").textContent).toBe("Connected");
  });

  it("restores a valid backend session after reload without another signature", async () => {
    const { provider, fetchMock } = setup();
    renderWallet();
    await flush();
    document.getElementById("wallet-connect").click();
    await flush();
    expect(sessionStorage.getItem(sessionKey)).toBeTruthy();

    const restoredWallet = renderWallet();
    await flush();
    expect(restoredWallet.isAuthenticated()).toBe(true);
    expect(document.getElementById("wallet-connect").textContent).toBe("Connected");
    expect(document.getElementById("wallet-balance").textContent).toContain("2 testnet credits");
    expect(provider.request.mock.calls.filter(([request]) => request.method === "personal_sign")).toHaveLength(1);
    expect(fetchMock.mock.calls.filter(([url]) => url === "/api/orb/credits/balance")).toHaveLength(2);
  });

  it("requires signing again for an expired saved session", async () => {
    setup();
    sessionStorage.setItem(sessionKey, JSON.stringify({ token: "old-session", address: firstAddress,
      expiresAt: Math.floor(Date.now() / 1000) - 1 }));
    const wallet = renderWallet();
    await flush();

    expect(wallet.isAuthenticated()).toBe(false);
    expect(document.getElementById("wallet-connect").textContent).toBe("Sign again");
    expect(document.getElementById("header-wallet").textContent).toBe("Connect Wallet");
    expect(sessionStorage.getItem(sessionKey)).toBeNull();
  });

  it("clears an expired backend session on reload", async () => {
    const { provider } = setup({ balanceStatus: 401 });
    sessionStorage.setItem(sessionKey, JSON.stringify({ token: "old-session", address: firstAddress,
      expiresAt: Math.floor(Date.now() / 1000) + 3600 }));
    const wallet = renderWallet();
    await flush();

    expect(wallet.isAuthenticated()).toBe(false);
    expect(document.getElementById("wallet-connect").textContent).toBe("Sign again");
    expect(sessionStorage.getItem(sessionKey)).toBeNull();
    expect(provider.request.mock.calls.some(([request]) => request.method === "personal_sign")).toBe(false);
  });

  it("rechecks a temporarily unavailable saved session without another signature", async () => {
    const { provider, setBalanceStatus } = setup({ balanceStatus: 503 });
    sessionStorage.setItem(sessionKey, JSON.stringify({ token: "saved-session", address: firstAddress,
      expiresAt: Math.floor(Date.now() / 1000) + 3600 }));
    const wallet = renderWallet();
    await flush();
    expect(wallet.isAuthenticated()).toBe(false);
    expect(document.getElementById("wallet-connect").textContent).toBe("Retry session");

    setBalanceStatus(200);
    document.getElementById("wallet-connect").click();
    await flush();
    expect(wallet.isAuthenticated()).toBe(true);
    expect(document.getElementById("wallet-connect").textContent).toBe("Connected");
    expect(provider.request.mock.calls.some(([request]) => request.method === "personal_sign")).toBe(false);
  });

  it("invalidates the old account and signs a fresh challenge for the new one", async () => {
    const { changeAccount, fetchMock, provider } = setup();
    const wallet = renderWallet();
    await flush();
    document.getElementById("wallet-connect").click();
    await flush();
    expect(wallet.walletAddress()).toBe(firstAddress);

    changeAccount(secondAddress);
    expect(wallet.isAuthenticated()).toBe(false);
    expect(wallet.walletAddress()).toBeNull();
    expect(document.getElementById("wallet-connect").textContent).toBe("Sign again");
    expect(document.getElementById("wallet-balance").textContent).toContain("0 testnet credits");
    expect(sessionStorage.getItem(sessionKey)).toBeNull();

    document.getElementById("wallet-connect").click();
    await flush();
    expect(wallet.walletAddress()).toBe(secondAddress);
    expect(document.getElementById("wallet-connect").textContent).toBe("Connected");
    expect(provider.request.mock.calls.filter(([request]) => request.method === "personal_sign")).toHaveLength(2);
    const challenges = fetchMock.mock.calls.filter(([url]) => url === "/api/orb/wallet/challenge");
    expect(JSON.parse(challenges[1][1].body).address).toBe(secondAddress);

    changeAccount(null);
    expect(wallet.isAuthenticated()).toBe(false);
    expect(document.getElementById("wallet-connect").textContent).toBe("Connect and sign");
    expect(sessionStorage.getItem(sessionKey)).toBeNull();
  });

  it("ignores a signature completed after the wallet account changes", async () => {
    const { changeAccount, fetchMock, provider } = setup();
    const ordinaryRequest = provider.request.getMockImplementation();
    let finishSignature;
    provider.request.mockImplementation((request) => request.method === "personal_sign"
      ? new Promise((resolve) => { finishSignature = resolve; }) : ordinaryRequest(request));
    const wallet = renderWallet();
    await flush();
    document.getElementById("wallet-connect").click();
    await flush();
    expect(finishSignature).toBeTypeOf("function");

    changeAccount(secondAddress);
    finishSignature(`0x${"cd".repeat(65)}`);
    await flush();
    expect(wallet.isAuthenticated()).toBe(false);
    expect(document.getElementById("wallet-connect").textContent).toBe("Sign again");
    expect(fetchMock.mock.calls.filter(([url]) => url === "/api/orb/wallet/sign-in")).toHaveLength(0);
  });

  it("disconnects Orb, clears saved state, and keeps the wallet disconnected after reload", async () => {
    const { fetchMock, provider } = setup();
    const wallet = renderWallet();
    await flush();
    expect(document.getElementById("wallet-disconnect").classList.contains("hidden")).toBe(true);
    document.getElementById("wallet-connect").click();
    await flush();
    expect(document.getElementById("wallet-disconnect").classList.contains("hidden")).toBe(false);
    sessionStorage.setItem("orb-sepolia-pending-payment", JSON.stringify({ quoteId: "quote" }));
    sessionStorage.setItem("orb-active-paid-job", JSON.stringify({ jobId: "job" }));

    document.getElementById("wallet-disconnect").click();
    expect(wallet.isAuthenticated()).toBe(false);
    expect(wallet.walletAddress()).toBeNull();
    expect(wallet.headers()).toEqual({});
    expect(document.getElementById("wallet-connect").textContent).toBe("Connect and sign");
    expect(document.getElementById("wallet-balance").textContent).toContain("0 testnet credits");
    expect(document.getElementById("wallet-disconnect").classList.contains("hidden")).toBe(true);
    expect(sessionStorage.getItem(sessionKey)).toBeNull();
    expect(sessionStorage.getItem("orb-sepolia-pending-payment")).toBeNull();
    expect(sessionStorage.getItem("orb-active-paid-job")).toBeNull();
    await flush();
    const logoutCall = fetchMock.mock.calls.find(([url]) => url === "/api/orb/wallet/logout");
    expect(logoutCall[1]).toMatchObject({ method: "POST", headers: { Authorization: "Bearer test-session-token" } });
    expect(provider.request.mock.calls.find(([request]) => request.method === "wallet_revokePermissions")[0])
      .toEqual({ method: "wallet_revokePermissions", params: [{ eth_accounts: {} }] });
    expect((await fetchMock("/api/orb/credits/balance", { headers: logoutCall[1].headers })).status).toBe(401);

    const reloaded = renderWallet();
    await flush();
    expect(reloaded.isAuthenticated()).toBe(false);
    expect(document.getElementById("wallet-connect").textContent).toBe("Connect and sign");
  });

  it("completes logout when MetaMask cannot revoke access, then requires a new signature", async () => {
    const { fetchMock, provider } = setup({ revokeError: new Error("method not supported") });
    const wallet = renderWallet();
    await flush();
    document.getElementById("wallet-connect").click();
    await flush();
    document.getElementById("wallet-disconnect").click();
    await flush();
    expect(wallet.isAuthenticated()).toBe(false);
    expect(document.getElementById("wallet-connect").textContent).toBe("Connect and sign");
    expect(document.getElementById("wallet-feedback").textContent).toBe("Wallet disconnected from Orb.");
    expect(provider.request.mock.calls.filter(([request]) => request.method === "eth_sendTransaction")).toHaveLength(0);

    document.getElementById("wallet-connect").click();
    await flush();
    expect(wallet.isAuthenticated()).toBe(true);
    expect(document.getElementById("wallet-connect").textContent).toBe("Connected");
    expect(provider.request.mock.calls.filter(([request]) => request.method === "personal_sign")).toHaveLength(2);
    expect(fetchMock.mock.calls.filter(([url]) => url === "/api/orb/wallet/challenge")).toHaveLength(2);
    expect(fetchMock.mock.calls.filter(([url]) => url === "/api/orb/wallet/sign-in")).toHaveLength(2);
  });

  it.each([[1, "0.003"], [3, "0.009"], [5, "0.015"]])("renders the server-configured USDG bundle price (%s credits)", async (credits, amount) => {
    setup({ dual: true });
    renderWallet();
    await flush();
    document.querySelector('[data-method="usdg"]').click();
    selectCredits(credits);
    expect(document.getElementById("credit-price").textContent).toContain(`${credits} credit${credits === 1 ? "" : "s"} · ${amount} test USDG`);
  });

  it("defaults to one accessible radio and keeps quantity through wallet and method changes", async () => {
    setup({ dual: true });
    renderWallet();
    await flush();
    const group = document.getElementById("credit-count");
    const radios = [...group.querySelectorAll('[role="radio"]')];
    expect(group.tagName).toBe("DIV");
    expect(group.getAttribute("role")).toBe("radiogroup");
    expect(document.getElementById(group.getAttribute("aria-labelledby")).textContent).toBe("Buy testnet credits");
    expect(radios.map((button) => button.dataset.credits)).toEqual(["1", "3", "5"]);
    expect(radios.map((button) => button.getAttribute("aria-checked"))).toEqual(["true", "false", "false"]);
    expect(radios.map((button) => button.tabIndex)).toEqual([0, -1, -1]);
    selectCredits(3);
    document.getElementById("wallet-connect").click();
    await flush();
    for (const method of ["usdg", "native_eth", "usdg"]) {
      document.querySelector(`[data-method="${method}"]`).click();
      expect(group.querySelector('[aria-checked="true"]').dataset.credits).toBe("3");
      expect(document.getElementById("credit-price").textContent).toContain("3 credits");
    }
    expect(radios.every((button) => !button.disabled)).toBe(true);
  });

  it("supports arrow, Home and End keys with one selected radio and one Tab stop", async () => {
    setup({ dual: true });
    renderWallet();
    await flush();
    const radios = [...document.querySelectorAll('#credit-count [role="radio"]')];
    for (const [key, expected] of [["ArrowRight", "3"], ["ArrowDown", "5"], ["ArrowRight", "1"],
      ["ArrowLeft", "5"], ["ArrowUp", "3"], ["Home", "1"], ["End", "5"]]) {
      const current = radios.find((button) => button.getAttribute("aria-checked") === "true");
      const event = new KeyboardEvent("keydown", { key, bubbles: true, cancelable: true });
      current.dispatchEvent(event);
      expect(event.defaultPrevented).toBe(true);
      const selected = radios.filter((button) => button.getAttribute("aria-checked") === "true");
      expect(selected).toHaveLength(1);
      expect(selected[0].dataset.credits).toBe(expected);
      expect(selected[0].focus).toHaveBeenCalled();
      expect(radios.filter((button) => button.tabIndex === 0)).toEqual(selected);
      expect(document.getElementById("credit-price").textContent).toContain(`${expected} credit`);
    }
    for (const key of [" ", "Enter", "Tab"]) {
      const event = new KeyboardEvent("keydown", { key, bubbles: true, cancelable: true });
      radios[2].dispatchEvent(event);
      expect(event.defaultPrevented).toBe(false); // Native button activation/navigation.
    }
  });

  it.each(["native_eth", "usdg"].flatMap((method) => [1, 3, 5].map((credits) => [method, credits])))
  ("uses selected quantity for the unchanged quote and transaction (%s, %s credits)", async (method, credits) => {
    const { provider, fetchMock } = setup({ dual: true });
    renderWallet();
    await flush();
    document.getElementById("wallet-connect").click();
    await flush();
    document.querySelector(`[data-method="${method}"]`).click();
    selectCredits(credits);
    document.getElementById("wallet-buy").click();
    await flush();
    const quotes = fetchMock.mock.calls.filter(([path]) => path === "/api/orb/credits/quotes");
    expect(quotes).toHaveLength(1);
    expect(JSON.parse(quotes[0][1].body)).toEqual({ credits, payment_method: method });
    const transactions = provider.request.mock.calls.filter(([arg]) => arg.method === "eth_sendTransaction");
    expect(transactions).toHaveLength(1);
    expect(transactions[0][0].params[0]).toEqual(method === "usdg" ? {
      ...expectedFees,
      from: firstAddress, to: "0xFFC95faa3d63Cde504a05B567C600B78C0b41892", value: "0x0",
      data: `0xa9059cbb${"33".repeat(20).padStart(64, "0")}${(3000n * BigInt(credits)).toString(16).padStart(64, "0")}`,
    } : { ...expectedFees, from: firstAddress, to: `0x${"33".repeat(20)}`, value: `0x${(1000n * BigInt(credits)).toString(16)}`,
      data: "0x4f524231" + "12".repeat(16) });
    selectCredits(credits === 5 ? 1 : 5);
    expect(document.querySelector('#credit-count [aria-checked="true"]').dataset.credits).toBe(credits === 5 ? "1" : "5");
  });

  it("keeps quantity usable during wallet approval without changing or repeating the submitted purchase", async () => {
    const { provider, fetchMock } = setup({ dual: true });
    const ordinaryRequest = provider.request.getMockImplementation();
    let finishTransaction;
    provider.request.mockImplementation((request) => request.method === "eth_sendTransaction"
      ? new Promise((resolve) => { finishTransaction = resolve; }) : ordinaryRequest(request));
    renderWallet();
    await flush();
    document.getElementById("wallet-connect").click();
    await flush();
    selectCredits(3);
    document.getElementById("wallet-buy").click();
    await flush();
    expect(document.getElementById("wallet-buy").disabled).toBe(true);
    expect([...document.querySelectorAll('#credit-count [role="radio"]')].every((button) => !button.disabled)).toBe(true);
    selectCredits(5);
    expect(document.getElementById("credit-price").textContent).toContain("5 credits");
    document.getElementById("wallet-buy").click();
    expect(fetchMock.mock.calls.filter(([path]) => path === "/api/orb/credits/quotes")).toHaveLength(1);
    expect(provider.request.mock.calls.filter(([arg]) => arg.method === "eth_sendTransaction")).toHaveLength(1);
    finishTransaction(`0x${"ab".repeat(32)}`);
    await flush();
    expect(document.getElementById("wallet-buy").disabled).toBe(false);
    expect(document.querySelector('#credit-count [aria-checked="true"]').dataset.credits).toBe("5");
    selectCredits(1);
    expect(document.getElementById("credit-price").textContent).toContain("1 credit");
  });

  it("renders the server USDG quote and transfers tokens with zero ETH and fresh network fees", async () => {
    const { provider, fetchMock } = setup({ usdg: true });
    const wallet = renderWallet();
    await flush();
    document.getElementById("wallet-connect").click();
    await flush();
    expect(document.getElementById("wallet-buy").textContent).toBe("Buy credits with USDG");
    expect(document.getElementById("wallet-testnet-notice").textContent).toContain("no monetary value");
    expect(document.getElementById("wallet-testnet-notice").textContent).toContain("ETH is still needed for gas");
    selectCredits(3);
    document.getElementById("wallet-buy").click();
    await flush();
    expect(document.getElementById("credit-price").textContent).toContain("3 credits · 0.009 test USDG");
    const [request] = provider.request.mock.calls.find(([arg]) => arg.method === "eth_sendTransaction");
    expect(request.params[0]).toEqual({ ...expectedFees, from: firstAddress,
      to: "0xFFC95faa3d63Cde504a05B567C600B78C0b41892", value: "0x0",
      data: `0xa9059cbb${"33".repeat(20).padStart(64, "0")}${(9000n).toString(16).padStart(64, "0")}` });
    expect(wallet.hasCredit()).toBe(true);
    expect(document.getElementById("wallet-balance").textContent).toContain("5 testnet credits");
    expect(fetchMock.mock.calls.filter(([url]) => url.endsWith("/verify"))).toHaveLength(1);
    expect(sessionStorage.getItem("orb-sepolia-pending-payment")).toBeNull();
  });

  it.each([
    [Object.assign(new Error("User rejected transaction"), { code: 4001 }), "Payment cancelled"],
    [new Error("ERC20: transfer amount exceeds balance"), "Insufficient test USDG"],
    [new Error("insufficient funds for gas * price + value"), "Insufficient Arbitrum Sepolia ETH for gas"],
  ])("handles rejected or insufficient-funds USDG transfers without verification", async (paymentError, message) => {
    const { fetchMock } = setup({ usdg: true, paymentError });
    renderWallet();
    await flush();
    document.getElementById("wallet-connect").click();
    await flush();
    document.getElementById("wallet-buy").click();
    await flush();
    expect(document.getElementById("wallet-feedback").textContent).toContain(message);
    expect(fetchMock.mock.calls.filter(([url]) => url.endsWith("/verify"))).toHaveLength(0);
    expect(sessionStorage.getItem("orb-sepolia-pending-payment")).toBeNull();
  });

  it.each(["chain", "amount", "data", "expired", "token"])("rejects a bad USDG quote before sending (%s)", async (fault) => {
    const { provider } = setup({ usdg: true, quoteChange(quote) {
      if (fault === "chain") quote.chain_id = 1;
      if (fault === "amount") quote.amount_base_units = "0.3";
      if (fault === "data") quote.data = "0xa9059cbb00";
      if (fault === "expired") quote.expires_at = 1;
      if (fault === "token") quote.to = secondAddress;
    } });
    renderWallet();
    await flush();
    document.getElementById("wallet-connect").click();
    await flush();
    document.getElementById("wallet-buy").click();
    await flush();
    expect(provider.request.mock.calls.filter(([arg]) => arg.method === "eth_sendTransaction")).toHaveLength(0);
  });

  it("does not submit another USDG payment while one is pending", async () => {
    const { provider } = setup({ usdg: true });
    renderWallet();
    await flush();
    document.getElementById("wallet-connect").click();
    await flush();
    sessionStorage.setItem("orb-sepolia-pending-payment", JSON.stringify({ quoteId: "pending", wallet: firstAddress }));
    document.getElementById("wallet-buy").click();
    await flush();
    expect(document.getElementById("wallet-feedback").textContent).toContain("A payment is pending");
    expect(provider.request.mock.calls.filter(([arg]) => arg.method === "eth_sendTransaction")).toHaveLength(0);
  });

  it("blocks wallet actions if the USDG Preview points to a native backend", async () => {
    // This intentional config failure schedules retries; keep them owned by
    // this test so an old wallet cannot render into a later test's document.
    vi.useFakeTimers();
    vi.stubEnv("VITE_ORB_DEPLOYMENT_TARGET", "usdg-staging");
    const { provider, fetchMock } = setup();
    const wallet = renderWallet();
    await vi.advanceTimersByTimeAsync(0);
    const configCalls = () => fetchMock.mock.calls.filter(([path]) => path === "/api/orb/credits/config");
    expect(configCalls()).toHaveLength(1);
    expect(vi.getTimerCount()).toBe(1);
    await vi.advanceTimersByTimeAsync(999);
    expect(configCalls()).toHaveLength(1);
    await vi.advanceTimersByTimeAsync(1);
    expect(configCalls()).toHaveLength(2);
    expect(vi.getTimerCount()).toBe(1); // Next retry is cleared in afterEach.
    expect(wallet.isEnabled()).toBe(false);
    expect(wallet.isAuthenticated()).toBe(false);
    expect(wallet.walletAddress()).toBeNull();
    expect(document.querySelector('[data-method][aria-pressed="true"]')).toBeNull();
    expect(document.getElementById("wallet-connect").disabled).toBe(true);
    expect(document.getElementById("wallet-buy").disabled).toBe(true);
    document.getElementById("header-wallet").click();
    document.getElementById("wallet-buy").click();
    await vi.advanceTimersByTimeAsync(0);
    expect(configCalls()).toHaveLength(2);
    expect(document.getElementById("wallet-feedback").textContent).toBe("Credit service is starting…");
    expect(fetchMock.mock.calls.some(([path]) => path === "/api/orb/credits/quotes")).toBe(false);
    expect(provider.request.mock.calls.filter(([arg]) => arg.method === "personal_sign")).toHaveLength(0);
    expect(provider.request.mock.calls.filter(([arg]) => arg.method === "eth_sendTransaction")).toHaveLength(0);
  });

  it("shows both server-enabled methods, switches compact selection and clears old quote copy", async () => {
    setup({ dual: true });
    renderWallet();
    await flush();
    const buttons = [...document.querySelectorAll("#payment-method-options button")];
    expect(buttons.map((button) => button.textContent)).toEqual(["Test ETH", "Paxos USDG"]);
    expect(buttons[0].getAttribute("aria-pressed")).toBe("true");
    buttons[1].click();
    expect(buttons[1].getAttribute("aria-pressed")).toBe("true");
    expect(buttons[0].getAttribute("aria-pressed")).toBe("false");
    expect(document.getElementById("wallet-testnet-notice").textContent).toContain("no monetary value");
    expect(document.getElementById("credit-price").textContent).toContain("server quote");
    selectCredits(3);
    expect(document.getElementById("credit-price").textContent).toContain("3 credits · 0.009 test USDG");
    buttons[0].click();
    expect(document.getElementById("wallet-buy").textContent).toBe("Pay with testnet ETH");
    expect(document.getElementById("credit-price").textContent).toContain("testnet ETH");
  });

  it.each(["native_eth", "usdg"])("quotes and pays the explicit selected method (%s)", async (method) => {
    const { provider, fetchMock } = setup({ dual: true });
    renderWallet();
    await flush();
    document.getElementById("wallet-connect").click();
    await flush();
    document.querySelector(`[data-method="${method}"]`).click();
    selectCredits(3);
    document.getElementById("wallet-buy").click();
    await flush();
    const quoteCall = fetchMock.mock.calls.find(([path]) => path === "/api/orb/credits/quotes");
    expect(JSON.parse(quoteCall[1].body)).toEqual({ credits: 3, payment_method: method });
    const request = provider.request.mock.calls.find(([arg]) => arg.method === "eth_sendTransaction")[0];
    expect(request.params[0]).toEqual(method === "usdg" ? { ...expectedFees, from: firstAddress,
      to: "0xFFC95faa3d63Cde504a05B567C600B78C0b41892", value: "0x0",
      data: `0xa9059cbb${"33".repeat(20).padStart(64, "0")}${(9000n).toString(16).padStart(64, "0")}` }
      : { ...expectedFees, from: firstAddress, to: `0x${"33".repeat(20)}`, value: "0xbb8", data: "0x4f524231" + "12".repeat(16) });
    await vi.waitFor(() => expect(document.getElementById("wallet-balance").textContent).toContain("5 testnet credits"));
    expect(sessionStorage.getItem("orb-sepolia-pending-payment")).toBeNull();
  });

  it.each(["native_eth", "usdg"])("rejects quotes for another method before wallet approval (%s)", async (method) => {
    const { provider, fetchMock } = setup({ dual: true, quoteChange(quote) {
      quote.payment_method = method === "native_eth" ? "usdg" : "native_eth";
    } });
    const wallet = renderWallet();
    await vi.waitFor(() => {
      expect(wallet.isEnabled()).toBe(true);
      expect(document.getElementById("wallet-connect").disabled).toBe(false);
    });
    document.getElementById("wallet-connect").click();
    await vi.waitFor(() => {
      expect(wallet.isAuthenticated()).toBe(true);
      expect(document.getElementById("wallet-buy").disabled).toBe(false);
    });
    document.querySelector(`[data-method="${method}"]`).click();
    expect(document.querySelector('[data-method][aria-pressed="true"]').dataset.method).toBe(method);
    document.getElementById("wallet-buy").click();
    await vi.waitFor(() => expect(document.getElementById("wallet-feedback").textContent).toContain("wrong payment method"));
    expect(provider.request.mock.calls.filter(([arg]) => arg.method === "eth_sendTransaction")).toHaveLength(0);
    expect(fetchMock.mock.calls.filter(([path]) => path.endsWith("/verify"))).toHaveLength(0);
  });

  it("does not invent a disabled server payment option", async () => {
    setup({ usdg: true });
    renderWallet();
    await flush();
    expect(document.querySelectorAll("#payment-method-options button")).toHaveLength(1);
    expect(document.querySelector('[data-method="native_eth"]')).toBeNull();
  });

  it("accepts dual methods from an explicitly isolated Preview backend", async () => {
    vi.stubEnv("VITE_ORB_DEPLOYMENT_TARGET", "usdg-staging");
    setup({ dual: true });
    expect(renderWallet().isEnabled()).toBe(false);
    await flush();
    expect(document.getElementById("wallet-connect").disabled).toBe(false);
  });

  it.each([
    ["native_eth", "insufficient funds for gas * price + value", "ETH for payment and gas"],
    ["usdg", "insufficient funds for gas * price + value", "ETH for gas"],
    ["usdg", "ERC20: transfer amount exceeds balance", "Insufficient test USDG"],
  ])("gives funds guidance for the selected method (%s)", async (method, error, message) => {
    const { provider, fetchMock } = setup({ dual: true, paymentError: new Error(error) });
    renderWallet();
    await flush();
    document.getElementById("wallet-connect").click();
    await flush();
    document.querySelector(`[data-method="${method}"]`).click();
    document.getElementById("wallet-buy").click();
    await flush();
    expect(document.getElementById("wallet-feedback").textContent).toContain(message);
    expect(fetchMock.mock.calls.filter(([path]) => path.endsWith("/verify"))).toHaveLength(0);
    expect(provider.request.mock.calls.filter(([arg]) => arg.method === "eth_sendTransaction")).toHaveLength(1);
  });
  it.each(["native_eth", "usdg"].flatMap((method) => ["estimate failure", "account change", "chain change", "rejection", "ambiguous send", "missing hash"]
    .map((failure) => [method, failure])))
  ("never sends/retries/verifies an unsafe payment (%s, %s)", async (method, failure) => {
    const { provider, fetchMock, changeAccount } = setup({ dual: true });
    renderWallet();
    await flush();
    document.getElementById("wallet-connect").click();
    await flush();
    document.querySelector(`[data-method="${method}"]`).click();
    const original = provider.request.getMockImplementation();
    provider.request.mockImplementation(async (request) => {
      if (request.method === "eth_maxPriorityFeePerGas" && failure === "rejection") {
        throw Object.assign(new Error("User rejected wallet request"), { code: 4001 });
      }
      if (request.method === "eth_estimateGas") {
        if (failure === "estimate failure") throw new Error("RPC unavailable");
        if (failure === "account change") changeAccount(secondAddress);
        if (failure === "chain change") provider.on.mock.calls.find(([event]) => event === "chainChanged")[1]("0x1");
      }
      if (request.method === "eth_sendTransaction") {
        if (failure === "ambiguous send") throw new Error("Provider connection closed after submission");
        if (failure === "missing hash") return null;
      }
      return original(request);
    });
    document.getElementById("wallet-buy").click();
    document.getElementById("wallet-buy").click(); // Busy guard rejects repeated user input.
    await flush();
    const sends = provider.request.mock.calls.filter(([request]) => request.method === "eth_sendTransaction");
    expect(sends).toHaveLength(["ambiguous send", "missing hash"].includes(failure) ? 1 : 0);
    expect(fetchMock.mock.calls.filter(([path]) => path.endsWith("/verify"))).toHaveLength(0);
    expect(fetchMock.mock.calls.filter(([path]) => path === "/api/orb/credits/quotes")).toHaveLength(1);
    expect(sessionStorage.getItem("orb-sepolia-pending-payment")).toBeNull();
    const message = document.getElementById("wallet-feedback").textContent;
    if (failure === "estimate failure") expect(message).toContain("couldn't obtain a fresh network fee estimate");
    if (["ambiguous send", "missing hash"].includes(failure)) expect(message).toContain("Check your wallet activity");
    if (failure === "rejection") {
      expect(message).toContain("Payment cancelled");
      expect(provider.request.mock.calls.some(([arg]) => ["eth_feeHistory", "eth_gasPrice"].includes(arg.method))).toBe(false);
    }
  });

  it.each(["native_eth", "usdg"])("recalculates fees independently for successive successful user purchases (%s)", async (method) => {
    const { provider, fetchMock } = setup({ dual: true });
    renderWallet();
    await flush();
    document.getElementById("wallet-connect").click();
    await flush();
    document.querySelector(`[data-method="${method}"]`).click();
    const original = provider.request.getMockImplementation();
    let base = "0x64";
    provider.request.mockImplementation((request) => request.method === "eth_getBlockByNumber"
      ? Promise.resolve({ baseFeePerGas: base }) : original(request));
    document.getElementById("wallet-buy").click();
    await flush();
    base = "0xc8";
    document.getElementById("wallet-buy").click();
    await flush();
    const transactions = provider.request.mock.calls.filter(([request]) => request.method === "eth_sendTransaction");
    expect(transactions).toHaveLength(2);
    expect(transactions[0][0].params[0].maxFeePerGas).toBe("0x98");
    expect(transactions[1][0].params[0].maxFeePerGas).toBe("0x12e");
    for (const [request] of transactions) {
      expect(request.params[0]).not.toHaveProperty("gasPrice");
      expect(request.params[0].gas).toBe("0x1d4c0");
      expect(request.params[0]).not.toHaveProperty("nonce");
    }
    const estimates = provider.request.mock.calls.filter(([request]) => request.method === "eth_estimateGas");
    expect(estimates).toHaveLength(2);
    for (const [index, [request]] of estimates.entries()) {
      const { gas, maxFeePerGas, maxPriorityFeePerGas, ...exact } = transactions[index][0].params[0];
      expect(request.params).toEqual([exact]);
    }
    expect(fetchMock.mock.calls.filter(([path]) => path.endsWith("/verify"))).toHaveLength(2);
    expect(document.getElementById("wallet-balance").textContent).toContain("5 testnet credits");
  });

  it.each(["native_eth", "usdg"])("cannot submit a late gas estimate after timeout (%s)", async (method) => {
    const { provider, fetchMock } = setup({ dual: true });
    renderWallet();
    await flush();
    document.getElementById("wallet-connect").click();
    await flush();
    document.querySelector(`[data-method="${method}"]`).click();
    const original = provider.request.getMockImplementation();
    let finishEstimate;
    provider.request.mockImplementation((request) => request.method === "eth_estimateGas"
      ? new Promise((resolve) => { finishEstimate = resolve; }) : original(request));
    vi.useFakeTimers();
    document.getElementById("wallet-buy").click();
    await vi.advanceTimersByTimeAsync(8000);
    expect(document.getElementById("wallet-feedback").textContent).toContain("couldn't obtain a fresh network fee estimate");
    expect(document.getElementById("wallet-buy").disabled).toBe(false);
    finishEstimate("0x186a0");
    await vi.advanceTimersByTimeAsync(60000);
    expect(provider.request.mock.calls.filter(([request]) => request.method === "eth_sendTransaction")).toHaveLength(0);
    expect(fetchMock.mock.calls.filter(([path]) => path.endsWith("/verify"))).toHaveLength(0);
    expect(fetchMock.mock.calls.filter(([path]) => path === "/api/orb/credits/quotes")).toHaveLength(1);
  });
});
