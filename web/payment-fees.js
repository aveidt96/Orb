// Fresh, read-only EIP-1193 estimation. This helper never submits a transaction.
export const FEE_ESTIMATE_ERROR = "Orb couldn't obtain a fresh network fee estimate. Please retry Buy Credits.";
const CHAIN_ID = 421614n;
const RPC_TIMEOUT_MS = 8000;
const ESTIMATE_DEADLINE_MS = 30000;
const MAX_QUANTITY = (1n << 256n) - 1n;
const SEPOLIA_RPC = "https://sepolia-rollup.arbitrum.io/rpc";
const FEE_READ_METHODS = new Set(["eth_getBlockByNumber", "eth_maxPriorityFeePerGas", "eth_feeHistory", "eth_gasPrice", "eth_estimateGas"]);

export function isWalletService404(error) {
  return /(?:status(?: code)?[ :]*404|\bHTTP 404\b)/i.test(
    [error?.message, error?.cause?.message, error?.data?.message, error?.data?.originalError?.message].filter(Boolean).join(" "));
}

function quantity(value, positive = false) {
  if (typeof value !== "string" || !/^0x(?:0|[1-9a-fA-F][0-9a-fA-F]*)$/.test(value)) throw new Error("Invalid RPC quantity");
  const result = BigInt(value);
  if (result > MAX_QUANTITY || (positive && result === 0n)) throw new Error("Invalid RPC quantity range");
  return result;
}

const hex = (value) => `0x${value.toString(16)}`;
const terminal = (error) => [4001, 4900, 4901].includes(error?.code) || error?.stopFeeEstimation;

export async function estimatePaymentFees(provider, transaction, assertActive = () => {}) {
  const started = Date.now();
  // Isolate the exact quoted payload from the caller and any provider mutation.
  const exact = { from: transaction.from, to: transaction.to, value: transaction.value, data: transaction.data };
  function active() {
    assertActive();
    if (Date.now() - started >= ESTIMATE_DEADLINE_MS) {
      throw Object.assign(new Error(FEE_ESTIMATE_ERROR), { stopFeeEstimation: true });
    }
  }
  async function rpc(method, params = []) {
    active();
    let timer;
    const controller = new AbortController();
    async function publicRead(name, args) {
      const response = await fetch(SEPOLIA_RPC, { method: "POST", signal: controller.signal,
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ jsonrpc: "2.0", id: 1, method: name, params: args }) });
      if (!response.ok) throw new Error("Official Sepolia fee RPC unavailable");
      const body = await response.json();
      if (body?.error || body?.jsonrpc !== "2.0" || body.id !== 1 || !("result" in body)) throw new Error("Invalid Sepolia RPC response");
      return body.result;
    }
    try {
      const result = await Promise.race([
        Promise.resolve().then(() => provider.request({ method, params })).catch(async (error) => {
          if (error?.code === 4001 || !FEE_READ_METHODS.has(method) || !isWalletService404(error)) throw error;
          // A broken extension simulation service must not dictate gas. Only
          // read-only fee methods may use the explicit official network RPC.
          // Signing, accounts, switching and sending always remain in-wallet.
          if (quantity(await publicRead("eth_chainId", [])) !== CHAIN_ID) throw new Error("Wrong fee RPC network");
          active();
          return publicRead(method, params);
        }),
        new Promise((_, reject) => {
          timer = setTimeout(() => reject(new Error("Fee RPC timed out")),
            Math.min(RPC_TIMEOUT_MS, ESTIMATE_DEADLINE_MS - (Date.now() - started)));
        }),
      ]);
      active();
      return result;
    } catch (error) {
      // Diagnostic detail stays in the console, outside product-facing copy.
      console.warn("[Orb fee estimation]", method, error?.code, error?.message);
      active();
      throw error;
    } finally { clearTimeout(timer); controller.abort(); }
  }
  async function identity() {
    if (quantity(await rpc("eth_chainId")) !== CHAIN_ID) {
      throw Object.assign(new Error("Network changed. Switch to Arbitrum Sepolia before buying credits."), { stopFeeEstimation: true });
    }
    const accounts = await rpc("eth_accounts");
    if (!Array.isArray(accounts) || accounts[0]?.toLowerCase() !== exact.from.toLowerCase()) {
      throw Object.assign(new Error("Wallet changed. Sign again before buying credits."), { stopFeeEstimation: true });
    }
  }
  async function baseFee() {
    for (const block of ["pending", "latest"]) {
      try { return quantity((await rpc("eth_getBlockByNumber", [block, false]))?.baseFeePerGas, true); }
      catch (error) { if (terminal(error)) throw error; }
    }
    throw new Error("No current block base fee");
  }
  function saneTip(value, base) {
    const tip = quantity(value);
    // Network-derived only: refuse tips above the base fee instead of imposing
    // an arbitrary fixed gwei value. Try another current network source.
    if (tip > base) throw new Error("Priority suggestion exceeds dynamic safety bound");
    return tip;
  }
  async function priorityFee(base) {
    try { return saneTip(await rpc("eth_maxPriorityFeePerGas"), base); }
    catch (error) { if (terminal(error)) throw error; }
    try {
      const history = await rpc("eth_feeHistory", ["0x3", "latest", [50]]);
      if (!Array.isArray(history?.reward) || history.reward.length !== 3) throw new Error("Invalid fee history");
      const tips = history.reward.map((row) => {
        if (!Array.isArray(row) || row.length !== 1) throw new Error("Invalid fee history reward");
        return saneTip(row[0], base);
      }).sort((a, b) => a < b ? -1 : a > b ? 1 : 0);
      return tips[1]; // Median of the last three blocks' 50th-percentile tips.
    } catch (error) { if (terminal(error)) throw error; }
    const gasPrice = quantity(await rpc("eth_gasPrice"), true);
    if (gasPrice < base) throw new Error("Gas price is below the current base fee");
    return saneTip(hex(gasPrice - base), base);
  }

  try {
    await identity();
    const base = await baseFee();
    const priority = await priorityFee(base);
    // Include Arbitrum's variable L1 posting component, not a static 100k cap.
    // A 100k minimum and 20% integer headroom reduce wallet-side re-estimation.
    const estimate = quantity(await rpc("eth_estimateGas", [{ ...exact }]), true);
    const paddedGas = (estimate * 6n + 4n) / 5n;
    const gas = paddedGas < 100000n ? 100000n : paddedGas;
    if (gas > MAX_QUANTITY) throw new Error("Gas limit overflow");
    // Refresh base fee after potentially slow gas estimation, before approval.
    const freshBase = await baseFee();
    if (priority > freshBase) throw new Error("Priority fee exceeds fresh dynamic safety bound");
    const maxFee = (freshBase * 3n + 1n) / 2n + priority;
    if (maxFee > MAX_QUANTITY) throw new Error("Fee cap overflow");
    await identity();
    active();
    return { gas: hex(gas), maxFeePerGas: hex(maxFee), maxPriorityFeePerGas: hex(priority) };
  } catch (error) {
    if (terminal(error)) throw error;
    throw new Error(FEE_ESTIMATE_ERROR, { cause: error });
  }
}
