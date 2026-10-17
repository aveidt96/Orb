"use strict";

import { apiUrl } from "./api-url.js";
import { estimatePaymentFees } from "./payment-fees.js";

const CHAIN_ID = 421614;
const CHAIN_HEX = `0x${CHAIN_ID.toString(16)}`;
const PENDING_KEY = "orb-sepolia-pending-payment";
const SESSION_KEY = "orb-wallet-session";
const DISCONNECTED_KEY = "orb-wallet-disconnected";
const ACTIVE_JOB_KEY = "orb-active-paid-job";
const CONFIG_TIMEOUT_MS = 15000;
const CONFIG_DEADLINE_MS = 120000;
const CONFIG_MAX_ATTEMPTS = 12;
const CONFIG_BACKOFF_MS = [1000, 2000, 4000, 8000];
const CONFIG_MESSAGES = {
  loading: "Loading credit options…",
  disabled: "Testnet credits are not configured on this Orb server.",
  unavailable: "Credit service is starting…",
};

export function initWallet({ onBalance }) {
  const el = (id) => document.getElementById(id);
  const panel = el("wallet-panel");
  const feedback = el("wallet-feedback");
  const connectButton = el("wallet-connect");
  const headerButton = el("header-wallet");
  const headerJudgeButton = el("header-judge");
  const headerCreditLabel = el("header-credit-label");
  const judgeToggleButton = el("judge-demo-toggle");
  const judgeForm = el("judge-demo-form");
  const judgeCodeInput = el("judge-code-input");
  const judgeCodeSubmit = el("judge-code-submit");
  const disconnectButton = el("wallet-disconnect");
  const switchButton = el("wallet-switch");
  const buyButton = el("wallet-buy");
  const retryButton = el("wallet-retry");
  const count = el("credit-count");
  const quantities = [...count.querySelectorAll('[role="radio"]')];
  const creditCount = () => count.querySelector('[aria-checked="true"]').dataset.credits;
  let config = null;
  let configState = "loading";
  let configTask = null;
  let paymentMethods = {};
  let selectedMethod = null;
  let token = null;
  let address = null;
  let walletAccount = null;
  let verified = false;
  let isJudge = false;
  let judgeActivating = false;
  let disconnected = sessionStorage.getItem(DISCONNECTED_KEY) === "1";
  let balance = 0;
  let busy = false;
  let verifyTimer = null;
  let sessionTimer = null;
  let authEpoch = 0;

  async function json(path, options = {}) {
    const response = await fetch(apiUrl(path), options);
    const body = await response.json().catch(() => ({}));
    if (!response.ok) {
      const error = new Error(body.detail || `Request failed (${response.status}).`);
      error.status = response.status;
      throw error;
    }
    return body;
  }

  function headers() {
    return token ? { Authorization: `Bearer ${token}` } : {};
  }

  function setFeedback(message) { feedback.textContent = message; }

  function savedSessionData() {
    try { return JSON.parse(sessionStorage.getItem(SESSION_KEY) || "null"); }
    catch { sessionStorage.removeItem(SESSION_KEY); return null; }
  }

  function update() {
    const judgeActive = isJudge && verified;
    const walletConnected = !isJudge && verified;
    if (judgeActive) {
      el("wallet-network").textContent = "Judge Demo Mode is Active · OpenCV 2026";
      switchButton.classList.add("hidden");
    }
    el("wallet-address").textContent = judgeActive
      ? `Judge Demo Mode is Active · ${address.slice(0, 10)}…${address.slice(-4)}`
      : address ? `Authenticated wallet · ${address.slice(0, 6)}…${address.slice(-4)}` : "";
    el("wallet-address").title = address || "";
    el("wallet-balance").textContent = judgeActive
      ? `${balance} test credit${balance === 1 ? "" : "s"} available`
      : `${balance} testnet credit${balance === 1 ? "" : "s"} available`;
    if (headerCreditLabel) {
      headerCreditLabel.textContent = judgeActive ? "Test credits" : "Testnet credits";
    }
    el("wallet-purchase").classList.toggle("hidden", judgeActive || !verified || configState !== "ready");
    disconnectButton.classList.toggle("hidden", !verified);
    disconnectButton.textContent = judgeActive ? "Exit Judge Mode / Connect Wallet" : "Disconnect wallet";
    disconnectButton.disabled = busy;
    connectButton.textContent = walletConnected
      ? "Connected"
      : (!judgeActive && token)
        ? "Retry session"
        : walletAccount
          ? "Sign again"
          : "Connect and sign";
    connectButton.disabled = busy || walletConnected || configState !== "ready";
    headerButton.textContent = walletConnected ? "Connected" : "Connect Wallet";
    headerButton.setAttribute("aria-label", walletConnected
      ? "Wallet connected. Open Wallet & Credits"
      : "Connect wallet");
    headerButton.classList.toggle("connected", walletConnected);
    headerButton.disabled = busy;
    if (headerJudgeButton) {
      headerJudgeButton.textContent = judgeActive ? "Judge Demo · Active" : "Judge Demo";
      headerJudgeButton.classList.toggle("active", judgeActive);
      headerJudgeButton.setAttribute("aria-pressed", String(judgeActive));
      headerJudgeButton.disabled = busy;
    }
    if (judgeToggleButton) {
      judgeToggleButton.textContent = judgeActive ? "Judge Demo Active (10-credit bypass)" : "Judge Demo Mode (OpenCV 2026)";
      judgeToggleButton.disabled = busy || judgeActive;
    }
    if (judgeForm && judgeActive) {
      judgeForm.classList.add("hidden");
      judgeToggleButton?.setAttribute("aria-expanded", "false");
    }
    if (judgeCodeSubmit) judgeCodeSubmit.disabled = busy;
    if (judgeCodeInput) judgeCodeInput.disabled = busy;
    buyButton.disabled = busy || !verified || judgeActive;
    retryButton.disabled = busy || !verified || judgeActive;
    el("payment-method-options").querySelectorAll("button").forEach((button) => {
      button.disabled = busy;
      button.setAttribute("aria-pressed", String(button.dataset.method === selectedMethod));
    });
    onBalance(balance);
  }

  function clearSession(message = "Wallet session cleared. Connect and sign again.") {
    authEpoch += 1;
    token = null;
    address = null;
    verified = false;
    isJudge = false;
    balance = 0;
    sessionStorage.removeItem(SESSION_KEY);
    clearTimeout(verifyTimer);
    clearTimeout(sessionTimer);
    retryButton.classList.add("hidden");
    setFeedback(message);
    update();
  }

  function requireAuthentication() {
    clearSession("Wallet session expired. Sign again.");
    open();
    connectButton.focus();
  }

  function scheduleExpiry(expiresAt) {
    clearTimeout(sessionTimer);
    const milliseconds = Math.max(0, expiresAt * 1000 - Date.now());
    sessionTimer = setTimeout(() => clearSession("Wallet session expired. Sign again."), milliseconds);
  }

  async function network() {
    if (!window.ethereum?.request) throw new Error("Install an Arbitrum-compatible wallet to connect.");
    const chain = await window.ethereum.request({ method: "eth_chainId" });
    const correct = Number.parseInt(chain, 16) === CHAIN_ID;
    if (!isJudge && !judgeActivating) {
      el("wallet-network").textContent = correct ? "Network: Arbitrum Sepolia" : "Wrong network. Switch to Arbitrum Sepolia.";
      switchButton.classList.toggle("hidden", correct);
    }
    return correct;
  }

  async function switchNetwork() {
    if (!window.ethereum?.request) throw new Error("An Arbitrum-compatible wallet is required.");
    try {
      await window.ethereum.request({ method: "wallet_switchEthereumChain", params: [{ chainId: CHAIN_HEX }] });
    } catch (error) {
      if (error?.code !== 4902) throw error;
      await window.ethereum.request({ method: "wallet_addEthereumChain", params: [{ chainId: CHAIN_HEX,
        chainName: "Arbitrum Sepolia", nativeCurrency: { name: "Sepolia Ether", symbol: "ETH", decimals: 18 },
        rpcUrls: ["https://sepolia-rollup.arbitrum.io/rpc"],
        blockExplorerUrls: ["https://sepolia.arbiscan.io"] }] });
    }
    if (!await network()) throw new Error("Switch your wallet to Arbitrum Sepolia before continuing.");
  }

  async function refresh() {
    if (!token) return false;
    const currentToken = token;
    const epoch = authEpoch;
    try {
      const result = await json("/api/orb/credits/balance", { headers: headers() });
      if (token !== currentToken || epoch !== authEpoch) return false;
      balance = result.available;
      if (result.judge_demo) isJudge = true;
      verified = true;
      update();
      return true;
    } catch (error) {
      if (token !== currentToken || epoch !== authEpoch) return false;
      if (error.status === 401) clearSession("Wallet session expired. Sign again.");
      else {
        setFeedback(`Could not verify wallet session: ${error.message}`);
        update();
      }
      return false;
    }
  }

  async function restoreSession() {
    if (isJudge || judgeActivating) return;
    const saved = savedSessionData();
    if (saved?.judgeDemo) {
      const epoch = authEpoch;
      if (typeof saved.token !== "string" || !saved.token ||
          !Number.isFinite(saved.expiresAt) || saved.expiresAt <= Date.now() / 1000) {
        clearSession("Judge demo session expired.");
        return;
      }
      disconnected = false;
      sessionStorage.removeItem(DISCONNECTED_KEY);
      token = saved.token;
      address = saved.address;
      isJudge = true;
      verified = false;
      el("wallet-network").textContent = "Judge Demo Mode is Active · OpenCV 2026";
      switchButton.classList.add("hidden");
      scheduleExpiry(saved.expiresAt);
      if (await refresh() && epoch === authEpoch) {
        setFeedback(`Judge Demo Mode is Active. ${balance} test credits available for Decode, Compose, and Enhance.`);
      }
      return;
    }
    if (disconnected) {
      walletAccount = null;
      el("wallet-network").textContent = "Wallet not connected.";
      switchButton.classList.add("hidden");
      update();
      return;
    }
    const epoch = authEpoch;
    const accounts = await window.ethereum?.request?.({ method: "eth_accounts" }) || [];
    if (epoch !== authEpoch || isJudge || judgeActivating) return;
    walletAccount = accounts[0] || null;
    if (!saved) { update(); return; }
    if (!walletAccount || saved.address?.toLowerCase() !== walletAccount.toLowerCase()) {
      clearSession("Wallet account changed. Sign again.");
      return;
    }
    if (typeof saved.token !== "string" || !saved.token ||
        !Number.isFinite(saved.expiresAt) || saved.expiresAt <= Date.now() / 1000) {
      clearSession("Wallet session expired. Sign again.");
      return;
    }
    token = saved.token;
    address = saved.address;
    isJudge = false;
    verified = false;
    scheduleExpiry(saved.expiresAt);
    if (await refresh() && epoch === authEpoch) {
      setFeedback("Wallet session restored. Testnet credits only.");
      const pending = pendingPayment();
      if (pending && pending.wallet.toLowerCase() === address.toLowerCase()) retryButton.classList.remove("hidden");
    }
  }

  async function connect() {
    if (busy) return;
    if (configState !== "ready") {
      setFeedback(CONFIG_MESSAGES[configState]);
      if (configState === "unavailable") void loadConfig();
      return;
    }
    if (!window.ethereum?.request) {
      if (isJudge && verified) {
        setFeedback("Install an Arbitrum-compatible wallet (such as MetaMask or Rabby) to connect a Web3 wallet. Judge Demo Mode remains active.");
        update();
        return;
      }
      clearSession("Install an Arbitrum-compatible wallet to connect.");
      return;
    }
    busy = true;
    disconnected = false;
    sessionStorage.removeItem(DISCONNECTED_KEY);
    authEpoch += 1;
    let attemptEpoch = authEpoch;
    update();
    try {
      const accounts = await window.ethereum.request({ method: "eth_requestAccounts" });
      if (!accounts?.[0]) throw new Error("No wallet account was selected.");
      if (attemptEpoch !== authEpoch && walletAccount?.toLowerCase() !== accounts[0].toLowerCase()) return;
      walletAccount = accounts[0];
      if (!await network()) await switchNetwork();
      if (walletAccount?.toLowerCase() !== accounts[0].toLowerCase()) return;
      attemptEpoch = authEpoch;
      const challenge = await json("/api/orb/wallet/challenge", { method: "POST",
        headers: { "Content-Type": "application/json" }, body: JSON.stringify({ address: accounts[0] }) });
      const signature = await window.ethereum.request({ method: "personal_sign", params: [challenge.message, accounts[0]] });
      if (attemptEpoch !== authEpoch || walletAccount?.toLowerCase() !== accounts[0].toLowerCase()) return;
      const session = await json("/api/orb/wallet/sign-in", { method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ nonce: challenge.nonce, signature }) });
      if (attemptEpoch !== authEpoch || walletAccount?.toLowerCase() !== accounts[0].toLowerCase()) return;
      if (typeof session.token !== "string" || !session.token ||
          session.wallet?.toLowerCase() !== accounts[0].toLowerCase() ||
          !Number.isFinite(session.expires_at) || session.expires_at <= Date.now() / 1000) {
        throw new Error("Wallet session could not be verified. Sign again.");
      }
      token = session.token;
      address = session.wallet;
      isJudge = false;
      verified = false;
      sessionStorage.setItem(SESSION_KEY, JSON.stringify({ token, address, expiresAt: session.expires_at }));
      scheduleExpiry(session.expires_at);
      setFeedback("Wallet authenticated for this session. Testnet credits only.");
      update();
      if (!await refresh()) return;
      const pending = pendingPayment();
      if (pending && pending.wallet.toLowerCase() === address.toLowerCase()) retryButton.classList.remove("hidden");
    } catch (error) {
      if (attemptEpoch === authEpoch) clearSession(error.message || "Wallet connection was cancelled.");
    } finally {
      busy = false;
      update();
    }
  }

  async function activateJudgeDemo(rawCode) {
    const code = (rawCode || "").trim();
    if (!code) {
      setFeedback("Enter the OpenCV 2026 judge access code.");
      return false;
    }
    if (busy) return false;
    busy = true;
    judgeActivating = true;
    disconnected = false;
    sessionStorage.removeItem(DISCONNECTED_KEY);
    authEpoch += 1;
    const attemptEpoch = authEpoch;
    setFeedback("Activating OpenCV 2026 Judge Demo session…");
    update();
    try {
      const session = await json("/api/orb/judge-session", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ code }),
      });
      if (attemptEpoch !== authEpoch) return false;
      if (typeof session.token !== "string" || !session.token ||
          typeof session.wallet !== "string" || !session.wallet ||
          !Number.isFinite(session.expires_at) || session.expires_at <= Date.now() / 1000) {
        throw new Error("Judge demo session could not be verified.");
      }
      token = session.token;
      address = session.wallet;
      isJudge = true;
      verified = true;
      balance = Number.isFinite(session.balance?.available) ? session.balance.available : (session.credits || 10);
      sessionStorage.setItem(SESSION_KEY, JSON.stringify({
        token, address, expiresAt: session.expires_at, judgeDemo: true,
      }));
      el("wallet-network").textContent = "Judge Demo Mode is Active · OpenCV 2026";
      switchButton.classList.add("hidden");
      if (judgeCodeInput) judgeCodeInput.value = "";
      scheduleExpiry(session.expires_at);
      setFeedback(`Judge Demo Mode is Active. ${balance} test credits available (${balance} demo credits unlocked for Decode, Compose, and Enhance).`);
      update();
      return true;
    } catch (error) {
      const saved = savedSessionData();
      if (saved?.judgeDemo && typeof saved.token === "string" && saved.token &&
          Number.isFinite(saved.expiresAt) && saved.expiresAt > Date.now() / 1000) {
        token = saved.token;
        address = saved.address;
        isJudge = true;
        verified = false;
        scheduleExpiry(saved.expiresAt);
        if (await refresh() && attemptEpoch === authEpoch) {
          setFeedback(`Judge Demo Mode is Active. ${balance} test credits available (${balance} demo credits unlocked).`);
          update();
          return true;
        }
      }
      if (attemptEpoch === authEpoch) {
        setFeedback(error.message || "Judge Demo activation failed.");
      }
      return false;
    } finally {
      judgeActivating = false;
      busy = false;
      update();
    }
  }

  function pendingPayment() {
    try { return JSON.parse(sessionStorage.getItem(PENDING_KEY) || "null"); }
    catch { return null; }
  }

  function formatTestnetEth(wei) {
    const units = BigInt(wei);
    const whole = units / 1000000000000000000n;
    const fraction = (units % 1000000000000000000n).toString().padStart(18, "0").replace(/0+$/, "");
    return `${whole}${fraction ? `.${fraction}` : ""}`;
  }

  function formatUsdg(units) {
    const value = BigInt(units);
    const fraction = (value % 1000000n).toString().padStart(6, "0").replace(/0+$/, "").padEnd(2, "0");
    return `${value / 1000000n}.${fraction}`;
  }

  function showPrice(quote = null) {
    const methodConfig = paymentMethods[selectedMethod];
    if (selectedMethod === "usdg") {
      // Informational preview derives from server config; only a returned quote
      // supplies the actual transaction amount and credits.
      el("credit-price").textContent = quote
        ? `${quote.credits} credits · ${formatUsdg(quote.amount_base_units)} test USDG. Quote expires in 15 minutes.`
        : methodConfig?.price_base_units
          ? `${creditCount()} credit${creditCount() === "1" ? "" : "s"} · ${formatUsdg(BigInt(methodConfig.price_base_units) * BigInt(creditCount()))} test USDG. Final price confirmed by server quote; ETH is needed for gas.`
          : "Get a server quote for the exact test USDG price. Arbitrum Sepolia ETH is needed for gas.";
    } else if (methodConfig) {
      el("credit-price").textContent = `${formatTestnetEth(BigInt(methodConfig.price_wei) * BigInt(creditCount()))} testnet ETH for ${creditCount()} credit${creditCount() === "1" ? "" : "s"} (plus gas). Quote expires in 15 minutes.`;
    }
  }

  function selectMethod(method) {
    if (!paymentMethods[method]?.enabled || busy) return;
    selectedMethod = method;
    buyButton.textContent = method === "usdg" ? "Buy credits with USDG" : "Pay with testnet ETH";
    el("wallet-testnet-notice").textContent = method === "usdg"
      ? "Paxos USDG · Arbitrum Sepolia. Testnet USDG has no monetary value. Arbitrum Sepolia ETH is still needed for gas."
      : "Arbitrum Sepolia · TESTNET ONLY. Demo credits have no real-money value. Testnet ETH is needed for payment and gas.";
    showPrice();
    update();
  }

  function renderMethods() {
    const options = el("payment-method-options");
    options.replaceChildren();
    for (const [method, label] of [["native_eth", "Test ETH"], ["usdg", "Paxos USDG"]]) {
      if (!paymentMethods[method]?.enabled) continue;
      const button = document.createElement("button");
      button.type = "button";
      button.dataset.method = method;
      button.textContent = label;
      button.addEventListener("click", () => selectMethod(method));
      options.append(button);
    }
    el("payment-method-picker").classList.toggle("hidden", options.children.length < 2);
    const pending = pendingPayment();
    selectMethod(paymentMethods[pending?.paymentMethod]?.enabled ? pending.paymentMethod
      : paymentMethods.native_eth?.enabled ? "native_eth" : "usdg");
  }

  function validateConfig(loaded) {
    if (!loaded || Array.isArray(loaded) || typeof loaded.enabled !== "boolean") {
      throw new Error("Invalid credit configuration response.");
    }
    if (import.meta.env?.VITE_ORB_DEPLOYMENT_TARGET === "usdg-staging"
        && (!(loaded.payment_methods?.usdg?.enabled || loaded.payment_method === "usdg")
            || loaded.deployment_target !== "usdg-staging")) {
      throw new Error("This preview requires the isolated USDG staging backend.");
    }
    if (!loaded.enabled) return {};
    // Retain legacy single-method support; never invent structured methods.
    const methods = loaded.payment_methods || (loaded.payment_method === "usdg"
      ? { usdg: { ...loaded, enabled: true } } : { native_eth: { ...loaded, enabled: true } });
    const enabled = ["native_eth", "usdg"].filter((method) => methods[method]?.enabled === true);
    if (!enabled.length) throw new Error("No supported payment method is enabled.");
    for (const method of enabled) {
      const value = methods[method];
      if (method === "native_eth" && !/^[1-9][0-9]*$/.test(value.price_wei)) {
        throw new Error("Invalid native payment configuration.");
      }
      if (method === "usdg" && (value.token_decimals !== 6
          || !/^0x[0-9a-fA-F]{40}$/.test(value.token_contract)
          || (value.price_base_units !== undefined && !/^[1-9][0-9]*$/.test(value.price_base_units)))) {
        throw new Error("Invalid USDG payment configuration.");
      }
    }
    return Object.fromEntries(enabled.map((method) => [method, methods[method]]));
  }

  async function requestConfig(timeout) {
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), timeout);
    try {
      const response = await fetch(apiUrl("/api/orb/credits/config"), { signal: controller.signal });
      if (!response.ok) throw new Error("Credit configuration request failed.");
      const loaded = await response.json();
      return { loaded, methods: validateConfig(loaded) };
    } finally {
      clearTimeout(timer);
    }
  }

  function extractJudgeUrlCode() {
    try {
      const params = new URLSearchParams(window.location.search);
      const code = (params.get("judge") || "").trim();
      if (!code) return null;
      params.delete("judge");
      const query = params.toString();
      const nextUrl = `${window.location.pathname}${query ? `?${query}` : ""}${window.location.hash || ""}`;
      window.history?.replaceState?.({}, "", nextUrl);
      return code;
    } catch {
      return null;
    }
  }

  let pendingJudgeCode = extractJudgeUrlCode();

  async function checkJudgeUrlParam() {
    if (!pendingJudgeCode) return false;
    const code = pendingJudgeCode;
    pendingJudgeCode = null;
    return await activateJudgeDemo(code);
  }

  async function restoreWallet() {
    if (isJudge || judgeActivating) return;
    if (savedSessionData()?.judgeDemo) {
      try {
        await restoreSession();
      } catch {
        setFeedback("Could not restore judge demo session.");
        update();
      }
      return;
    }
    if (!window.ethereum?.request) return;
    // Wallet/network failures must never invalidate a successful config fetch.
    await network().catch(() => {
      if (!isJudge && !judgeActivating) {
        el("wallet-network").textContent = "Wallet network unavailable. Try again.";
      }
    });
    if (isJudge || judgeActivating) return;
    try {
      await restoreSession();
    } catch {
      if (!isJudge && !judgeActivating) {
        setFeedback("Could not restore wallet session. Connect and sign again.");
        update();
      }
    }
  }

  function loadConfig() {
    if (configTask) return configTask;
    setFeedback(CONFIG_MESSAGES[configState]);
    configTask = (async () => {
      const deadline = Date.now() + CONFIG_DEADLINE_MS;
      for (let attempt = 0; attempt < CONFIG_MAX_ATTEMPTS && Date.now() < deadline; attempt += 1) {
        let result;
        try {
          result = await requestConfig(Math.min(CONFIG_TIMEOUT_MS, deadline - Date.now()));
        } catch {
          configState = "unavailable";
          if (!isJudge && !judgeActivating) setFeedback(CONFIG_MESSAGES.unavailable);
          update();
          if (attempt + 1 < CONFIG_MAX_ATTEMPTS && Date.now() < deadline) {
            const delay = CONFIG_BACKOFF_MS[Math.min(attempt, CONFIG_BACKOFF_MS.length - 1)];
            await new Promise((resolve) => setTimeout(resolve, Math.min(delay, deadline - Date.now())));
          }
          continue;
        }
        config = result.loaded;
        paymentMethods = result.methods;
        configState = config.enabled ? "ready" : "disabled";
        if (configState === "disabled") {
          if (await checkJudgeUrlParam()) return;
          if (!isJudge) setFeedback(CONFIG_MESSAGES.disabled);
          update();
          if (savedSessionData()?.judgeDemo) void restoreWallet();
          return;
        }
        renderMethods();
        if (await checkJudgeUrlParam()) return;
        if (!isJudge) setFeedback("Connect a wallet to see your testnet credits.");
        update();
        void restoreWallet();
        return;
      }
      await checkJudgeUrlParam();
      if (!isJudge) setFeedback("Credit service temporarily unavailable. Try again.");
    })().finally(() => { configTask = null; });
    return configTask;
  }

  async function verifyPending(attempts = 0) {
    const pending = pendingPayment();
    if (!pending || !verified || !token || pending.wallet.toLowerCase() !== address?.toLowerCase()) return;
    const currentToken = token;
    const epoch = authEpoch;
    retryButton.classList.remove("hidden");
    setFeedback("Verifying payment on Arbitrum Sepolia…");
    try {
      const result = await json(`/api/orb/credits/quotes/${encodeURIComponent(pending.quoteId)}/verify`, {
        method: "POST", headers: { "Content-Type": "application/json", ...headers() },
        body: JSON.stringify({ tx_hash: pending.txHash }),
      });
      if (currentToken !== token || epoch !== authEpoch) return;
      sessionStorage.removeItem(PENDING_KEY);
      retryButton.classList.add("hidden");
      balance = result.balance.available;
      setFeedback(`${result.credits} testnet credit${result.credits === 1 ? "" : "s"} added.`);
      update();
    } catch (error) {
      if (currentToken !== token || epoch !== authEpoch) return;
      if (error.status === 409 && attempts < 30) {
        setFeedback("Waiting for the required testnet confirmations…");
        verifyTimer = setTimeout(() => void verifyPending(attempts + 1), 5000);
      } else setFeedback(`Verification pending: ${error.message} Use “Check pending transaction” to retry.`);
    }
  }

  async function buy() {
    if (busy || !token || isJudge || !paymentMethods[selectedMethod]?.enabled) return;
    if (pendingPayment()) {
      setFeedback("A payment is pending. Check pending transaction before buying again.");
      retryButton.classList.remove("hidden");
      return;
    }
    const payingWallet = address;
    const payingMethod = selectedMethod;
    const methodConfig = paymentMethods[payingMethod];
    let epoch = authEpoch;
    let submissionStarted = false;
    busy = true;
    update();
    try {
      if (!await network()) await switchNetwork();
      if (!verified || !address || payingWallet?.toLowerCase() !== walletAccount?.toLowerCase()) {
        throw new Error("Wallet changed. Sign again before buying credits.");
      }
      epoch = authEpoch;
      const quote = await json("/api/orb/credits/quotes", { method: "POST",
        headers: { "Content-Type": "application/json", ...headers() },
        body: JSON.stringify({ credits: Number(creditCount()), payment_method: payingMethod }) });
      if (quote.chain_id !== CHAIN_ID) throw new Error("Server quote has the wrong chain.");
      if (epoch !== authEpoch || !verified) throw new Error("Wallet changed. Sign again before buying credits.");
      if (quote.expires_at && quote.expires_at <= Date.now() / 1000) throw new Error("Payment quote expired. Request a new quote.");
      if ((quote.payment_method || "native_eth") !== payingMethod) throw new Error("Server quote has the wrong payment method.");
      if (payingMethod === "usdg") {
        if (quote.payment_method !== "usdg" || quote.token_symbol !== "USDG" || quote.token_decimals !== 6
            || quote.token_contract?.toLowerCase() !== methodConfig.token_contract?.toLowerCase()
            || quote.to?.toLowerCase() !== quote.token_contract.toLowerCase()
            || quote.wallet?.toLowerCase() !== payingWallet.toLowerCase() || quote.value_wei !== "0"
            || !/^0x[0-9a-fA-F]{40}$/.test(quote.receiver)
            || !/^[1-9][0-9]*$/.test(quote.amount_base_units)) {
          throw new Error("Server returned an invalid USDG quote.");
        }
        const expectedData = `0xa9059cbb${quote.receiver.slice(2).toLowerCase().padStart(64, "0")}${BigInt(quote.amount_base_units).toString(16).padStart(64, "0")}`;
        if (quote.data?.toLowerCase() !== expectedData) throw new Error("Server returned invalid USDG transfer data.");
        showPrice(quote);
      }
      const provider = window.ethereum;
      const transaction = {
        from: payingWallet, to: quote.to, value: `0x${BigInt(quote.value_wei).toString(16)}`, data: quote.data,
      };
      const assertActive = () => {
        if (provider !== window.ethereum || epoch !== authEpoch || !verified
            || payingWallet.toLowerCase() !== walletAccount?.toLowerCase()) {
          throw Object.assign(new Error("Wallet or network changed. Sign again before buying credits."), { stopFeeEstimation: true });
        }
        if (quote.expires_at && quote.expires_at <= Date.now() / 1000) {
          throw Object.assign(new Error("Payment quote expired. Request a new quote."), { stopFeeEstimation: true });
        }
      };
      setFeedback("Estimating current network fees…");
      const fees = await estimatePaymentFees(provider, transaction, assertActive);
      assertActive();
      setFeedback("Confirm the Arbitrum Sepolia testnet transfer in your wallet…");
      // Exactly one send per user attempt. Never automatically resend on error.
      submissionStarted = true;
      const txHash = await provider.request({ method: "eth_sendTransaction", params: [{ ...transaction, ...fees }] });
      if (!/^0x[0-9a-fA-F]{64}$/.test(txHash)) throw new Error("Wallet did not return a valid transaction hash.");
      // Remember a submitted transfer even if the account changes while the
      // wallet approval dialog is open. Only its original wallet can verify it.
      sessionStorage.setItem(PENDING_KEY, JSON.stringify({ quoteId: quote.quote_id, txHash, wallet: payingWallet, paymentMethod: payingMethod }));
      setFeedback("Payment submitted. Verifying payment…");
      void verifyPending();
    } catch (error) {
      console.warn("[Orb payment attempt]", error?.code, error?.message, error?.cause?.message, error?.data?.message);
      const feeError = [error?.message, error?.cause?.message, error?.data?.message, error?.data?.originalError?.message]
        .filter((message) => typeof message === "string").join(" ");
      if (/(?:max\s*fee\s*per\s*gas|maxFeePerGas).*(?:base\s*fee|baseFee)/i.test(feeError)) {
        setFeedback("Your wallet's fee estimate was below Arbitrum Sepolia's current base fee. Check your wallet activity before retrying Buy Credits. Orb did not receive a transaction hash.");
      } else if (error?.code === 4001) setFeedback("Payment cancelled in your wallet. No new credits were charged.");
      else if (payingMethod === "usdg" && /insufficient|exceeds balance|transfer amount exceeds/i.test(feeError)
          && /token|usdg|transfer amount|balanceOf/i.test(feeError)) {
        setFeedback("Insufficient test USDG. Obtain Paxos test USDG on Arbitrum Sepolia and try again.");
      } else if (/insufficient funds|insufficient.*gas|gas.*insufficient/i.test(feeError)) {
        setFeedback(payingMethod === "usdg"
          ? "Insufficient Arbitrum Sepolia ETH for gas. Add testnet ETH and try again."
          : "Insufficient Arbitrum Sepolia ETH for payment and gas. Add testnet ETH and try again.");
      } else setFeedback(submissionStarted
        ? "Orb did not receive a transaction hash. Check your wallet activity before retrying Buy Credits."
        : (error.message || "Testnet payment was cancelled."));
    }
    finally { busy = false; update(); }
  }

  async function disconnect() {
    if (!verified || !token || busy) return;
    const oldToken = token;
    const wasJudge = isJudge;
    busy = true;
    if (wasJudge) {
      disconnected = false;
      sessionStorage.removeItem(DISCONNECTED_KEY);
    } else {
      disconnected = true;
      sessionStorage.setItem(DISCONNECTED_KEY, "1");
      walletAccount = null;
    }
    clearSession(wasJudge ? "Exiting Judge Demo Mode…" : "Disconnecting wallet from Orb…");
    sessionStorage.removeItem(PENDING_KEY);
    sessionStorage.removeItem(ACTIVE_JOB_KEY);
    el("wallet-network").textContent = "Wallet not connected.";
    switchButton.classList.add("hidden");
    update();
    let revoked = false;
    try {
      await json("/api/orb/wallet/logout", { method: "POST",
        headers: { Authorization: `Bearer ${oldToken}` } });
      revoked = true;
    } catch (error) {
      revoked = error.status === 401;
    }
    if (!wasJudge) {
      try {
        await window.ethereum?.request?.({ method: "wallet_revokePermissions",
          params: [{ eth_accounts: {} }] });
      } catch { /* Some wallets do not support site permission revocation. */ }
    }
    setFeedback(wasJudge
      ? "Exited Judge Demo Mode. Connect and sign with your Web3 wallet."
      : revoked ? "Wallet disconnected from Orb." :
        "Wallet disconnected locally. Server sign-out could not be confirmed; the old session will expire.");
    busy = false;
    update();
    if (wasJudge && window.ethereum?.request && configState === "ready") {
      void connect();
    }
  }

  function open() { panel.classList.remove("hidden"); headerButton.setAttribute("aria-expanded", "true"); el("wallet-close").focus(); }
  function close(restoreFocus = false) {
    panel.classList.add("hidden");
    headerButton.setAttribute("aria-expanded", "false");
    if (restoreFocus) headerButton.focus();
  }

  function openJudgePrompt() {
    open();
    if (isJudge && verified) return;
    if (judgeForm) {
      judgeForm.classList.remove("hidden");
      judgeToggleButton?.setAttribute("aria-expanded", "true");
      judgeCodeInput?.focus();
    }
  }

  el("wallet-close").addEventListener("click", () => close(true));
  connectButton.addEventListener("click", () => void (token && !verified && !isJudge ? refresh() : connect()));
  headerButton.addEventListener("click", () => {
    open();
    if (configState !== "ready") {
      void connect();
      return;
    }
    if (!verified || isJudge) void (token && !isJudge ? refresh() : connect());
  });
  headerJudgeButton?.addEventListener("click", () => openJudgePrompt());
  judgeToggleButton?.addEventListener("click", () => {
    if (isJudge && verified) return;
    const isHidden = judgeForm?.classList.toggle("hidden");
    judgeToggleButton.setAttribute("aria-expanded", String(!isHidden));
    if (!isHidden) judgeCodeInput?.focus();
  });
  judgeForm?.addEventListener("submit", (event) => {
    event.preventDefault();
    void activateJudgeDemo(judgeCodeInput?.value || "");
  });
  disconnectButton.addEventListener("click", () => void disconnect());
  switchButton.addEventListener("click", async () => {
    try { await switchNetwork(); setFeedback("Arbitrum Sepolia selected. Connect and sign to continue."); }
    catch (error) { setFeedback(error.message || "Network switch cancelled."); }
  });
  buyButton.addEventListener("click", () => void buy());
  retryButton.addEventListener("click", () => void verifyPending());
  function selectQuantity(selected) {
    for (const button of quantities) {
      button.setAttribute("aria-checked", String(button === selected));
      button.tabIndex = button === selected ? 0 : -1;
    }
    showPrice();
  }
  quantities.forEach((button, index) => {
    button.addEventListener("click", () => selectQuantity(button));
    button.addEventListener("keydown", (event) => {
      let next;
      if (["ArrowRight", "ArrowDown"].includes(event.key)) next = (index + 1) % quantities.length;
      else if (["ArrowLeft", "ArrowUp"].includes(event.key)) next = (index + quantities.length - 1) % quantities.length;
      else if (event.key === "Home") next = 0;
      else if (event.key === "End") next = quantities.length - 1;
      else return; // Space/Enter retain the button's native click activation.
      event.preventDefault();
      selectQuantity(quantities[next]);
      quantities[next].focus();
    });
  });
  window.ethereum?.on?.("accountsChanged", (accounts) => {
    if (disconnected || isJudge || judgeActivating) return;
    const next = accounts?.[0] || null;
    if (next?.toLowerCase() === walletAccount?.toLowerCase()) return;
    const hadWallet = Boolean(walletAccount);
    walletAccount = next;
    if (busy && !hadWallet && next) return;
    clearSession("Wallet account changed. Sign again.");
  });
  window.ethereum?.on?.("chainChanged", (chainIdHex) => {
    if (disconnected || isJudge || judgeActivating) return;
    const isTargetChain = typeof chainIdHex === "string" && Number.parseInt(chainIdHex, 16) === CHAIN_ID;
    if (busy && isTargetChain) {
      void network().catch(() => {});
      return;
    }
    if (!isTargetChain || verified) {
      clearSession("Wallet network changed. Switch to Arbitrum Sepolia and sign again.");
    }
    void network().catch(() => {});
  });
  void loadConfig();
  update();
  return { open, close, refresh, headers, requireAuthentication, hasCredit: () => verified && balance > 0,
    isAuthenticated: () => verified, walletAddress: () => verified ? address : null,
    isEnabled: () => configState === "ready", isJudgeDemo: () => isJudge && verified,
    activateJudgeDemo };
}
