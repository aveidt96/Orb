import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { estimatePaymentFees, FEE_ESTIMATE_ERROR } from "./payment-fees.js";

const wallet = `0x${"11".repeat(20)}`;
const receiver = `0x${"33".repeat(20)}`;
const native = { from: wallet, to: receiver, value: "0x3e8", data: "0x4f524231" + "12".repeat(16) };
const usdg = { from: wallet, to: "0xFFC95faa3d63Cde504a05B567C600B78C0b41892", value: "0x0",
  data: `0xa9059cbb${receiver.slice(2).padStart(64, "0")}${(9000n).toString(16).padStart(64, "0")}` };
const unsupported = () => { throw Object.assign(new Error("Unsupported RPC method"), { code: 4200 }); };

function provider(overrides = {}) {
  const defaults = { eth_chainId: "0x66eee", eth_accounts: [wallet], eth_getBlockByNumber: { baseFeePerGas: "0x64" },
    eth_maxPriorityFeePerGas: "0x2", eth_estimateGas: "0x186a0",
    eth_feeHistory: { reward: [["0x4"], ["0x2"], ["0x3"]] }, eth_gasPrice: "0x69" };
  return { request: vi.fn(async ({ method, params }) => {
    const value = method in overrides ? overrides[method] : defaults[method];
    if (value === undefined) throw new Error(`Unexpected RPC ${method}`);
    return typeof value === "function" ? value(params) : value;
  }) };
}

describe("fresh Arbitrum Sepolia EIP-1559 estimation", () => {
  beforeEach(() => vi.spyOn(console, "warn").mockImplementation(() => {}));
  afterEach(() => { vi.useRealTimers(); vi.restoreAllMocks(); vi.unstubAllGlobals(); });

  it.each([native, usdg])("uses the official chain-checked RPC only when wallet fee estimation returns 404", async (transaction) => {
    const fetchRpc = vi.fn(async (url, options) => {
      expect(url).toBe("https://sepolia-rollup.arbitrum.io/rpc");
      const { method, params } = JSON.parse(options.body);
      if (method === "eth_estimateGas") expect(params).toEqual([transaction]);
      return { ok: true, json: async () => ({ jsonrpc: "2.0", id: 1,
        result: method === "eth_chainId" ? "0x66eee" : "0x186a0" }) };
    });
    vi.stubGlobal("fetch", fetchRpc);
    const rpc = provider({ eth_estimateGas: () => { throw new Error("Request failed with status code 404"); } });
    expect((await estimatePaymentFees(rpc, transaction)).gas).toBe("0x1d4c0");
    expect(fetchRpc).toHaveBeenCalledTimes(2);
    expect(rpc.request.mock.calls.some(([r]) => r.method === "eth_sendTransaction")).toBe(false);
  });

  it("rejects a wrong-chain fallback RPC without sending any transaction", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => ({ ok: true, json: async () => ({ jsonrpc: "2.0", id: 1, result: "0x1" }) })));
    await expect(estimatePaymentFees(provider({ eth_estimateGas: () => { throw new Error("HTTP 404"); } }), native))
      .rejects.toThrow(FEE_ESTIMATE_ERROR);
    expect(fetch).toHaveBeenCalledTimes(1);
  });

  it("does not contact the fallback RPC after wallet rejection or a genuine execution revert", async () => {
    vi.stubGlobal("fetch", vi.fn());
    for (const error of [Object.assign(new Error("HTTP 404"), { code: 4001 }), new Error("execution reverted")]) {
      await expect(estimatePaymentFees(provider({ eth_estimateGas: () => { throw error; } }), native)).rejects.toThrow();
    }
    expect(fetch).not.toHaveBeenCalled();
  });

  it("uses the current base and priority suggestion with 50% base headroom", async () => {
    const rpc = provider();
    expect(await estimatePaymentFees(rpc, native)).toEqual({ gas: "0x1d4c0", maxFeePerGas: "0x98", maxPriorityFeePerGas: "0x2" });
    expect(rpc.request.mock.calls.filter(([arg]) => arg.method === "eth_getBlockByNumber"))
      .toEqual([[{ method: "eth_getBlockByNumber", params: ["pending", false] }],
        [{ method: "eth_getBlockByNumber", params: ["pending", false] }]]);
  });

  it.each([["0x5208", 100000n], ["0x186a0", 120000n], ["0x493e0", 360000n]])
  ("supplies a clean hex gas limit from %s without imposing a 100k cap", async (estimate, expected) => {
    const fees = await estimatePaymentFees(provider({ eth_estimateGas: estimate }), usdg);
    expect(fees.gas).toBe(`0x${expected.toString(16)}`);
    expect(fees).not.toHaveProperty("gasPrice");
    expect(fees).not.toHaveProperty("nonce");
  });

  it.each([1n, 31140000n, 90071992547409930001n])("keeps integer headroom above base %s, including beyond Number precision", async (base) => {
    const result = await estimatePaymentFees(provider({ eth_getBlockByNumber: { baseFeePerGas: `0x${base.toString(16)}` },
      eth_maxPriorityFeePerGas: "0x0" }), native);
    const cap = BigInt(result.maxFeePerGas);
    expect(cap).toBe((base * 3n + 1n) / 2n);
    expect(cap).toBeGreaterThan(base);
    expect(cap).toBeGreaterThanOrEqual(BigInt(result.maxPriorityFeePerGas));
    // Deterministic policy stress: accommodates 49% base growth before approval.
    expect(cap).toBeGreaterThan(base * 149n / 100n);
  });

  it("reads new fees each attempt rather than caching the prior base or tip", async () => {
    let base = "0x64", tip = "0x2";
    const rpc = provider({ eth_getBlockByNumber: () => ({ baseFeePerGas: base }), eth_maxPriorityFeePerGas: () => tip });
    expect((await estimatePaymentFees(rpc, native)).maxFeePerGas).toBe("0x98");
    base = "0xc8"; tip = "0x4";
    expect(await estimatePaymentFees(rpc, native)).toEqual({ gas: "0x1d4c0", maxFeePerGas: "0x130", maxPriorityFeePerGas: "0x4" });
    expect(rpc.request.mock.calls.filter(([arg]) => arg.method === "eth_maxPriorityFeePerGas")).toHaveLength(2);
    expect(rpc.request.mock.calls.filter(([arg]) => arg.method === "eth_estimateGas")).toHaveLength(2);
  });

  it("refreshes base after gas estimation rather than using a now-stale initial block", async () => {
    let base = "0x64";
    const rpc = provider({ eth_getBlockByNumber: () => ({ baseFeePerGas: base }),
      eth_estimateGas: () => { base = "0xc8"; return "0x186a0"; } });
    expect((await estimatePaymentFees(rpc, native)).maxFeePerGas).toBe("0x12e");
  });

  it.each([unsupported, () => ({}), () => ({ baseFeePerGas: "bad" })])
  ("falls back from unsupported/missing/malformed pending block to latest", async (pending) => {
    const rpc = provider({ eth_getBlockByNumber: ([tag]) => tag === "pending" ? pending() : { baseFeePerGas: "0x64" } });
    expect((await estimatePaymentFees(rpc, native)).maxFeePerGas).toBe("0x98");
    expect(rpc.request.mock.calls.filter(([arg]) => arg.method === "eth_getBlockByNumber" && arg.params[0] === "latest")).toHaveLength(2);
  });

  it.each([null, {}, { baseFeePerGas: "0x0" }, { baseFeePerGas: "0xZZ" }, { baseFeePerGas: "100" }])
  ("refuses missing/malformed/zero base fees without submitting (%j)", async (block) => {
    const rpc = provider({ eth_getBlockByNumber: block });
    await expect(estimatePaymentFees(rpc, native)).rejects.toThrow(FEE_ESTIMATE_ERROR);
    expect(rpc.request.mock.calls.some(([arg]) => arg.method === "eth_estimateGas" || arg.method === "eth_sendTransaction")).toBe(false);
  });

  it.each([unsupported, "bad", "0x1000"])("uses feeHistory median for unsupported/malformed/excessive priority (%s)", async (priority) => {
    const rpc = provider({ eth_maxPriorityFeePerGas: priority });
    expect(await estimatePaymentFees(rpc, native)).toEqual({ gas: "0x1d4c0", maxFeePerGas: "0x99", maxPriorityFeePerGas: "0x3" });
    expect(rpc.request).toHaveBeenCalledWith({ method: "eth_feeHistory", params: ["0x3", "latest", [50]] });
    expect(rpc.request.mock.calls.some(([arg]) => arg.method === "eth_gasPrice")).toBe(false);
  });

  it.each([unsupported, {}, { reward: [["bad"], ["0x0"], ["0x0"]] }])
  ("derives a priority from fresh gasPrice when both tip sources are unavailable", async (history) => {
    const rpc = provider({ eth_maxPriorityFeePerGas: unsupported, eth_feeHistory: history });
    expect(await estimatePaymentFees(rpc, native)).toEqual({ gas: "0x1d4c0", maxFeePerGas: "0x9b", maxPriorityFeePerGas: "0x5" });
  });

  it.each(["bad", "0x63", "0x1000", "0x0"])("refuses bad/stale/excessive gasPrice (%s)", async (price) => {
    await expect(estimatePaymentFees(provider({ eth_maxPriorityFeePerGas: unsupported,
      eth_feeHistory: unsupported, eth_gasPrice: price }), native)).rejects.toThrow(FEE_ESTIMATE_ERROR);
  });

  it.each([native, usdg])("estimates EXACT transaction and supplies gas without nonce/gasPrice", async (transaction) => {
    const snapshot = { ...transaction };
    const rpc = provider();
    const fees = await estimatePaymentFees(rpc, transaction);
    expect(rpc.request).toHaveBeenCalledWith({ method: "eth_estimateGas", params: [snapshot] });
    expect(transaction).toEqual(snapshot);
    expect(Object.keys(fees).sort()).toEqual(["gas", "maxFeePerGas", "maxPriorityFeePerGas"]);
    expect(rpc.request.mock.calls.some(([arg]) => arg.method === "eth_sendTransaction")).toBe(false);
  });

  it.each([() => { throw new Error("execution reverted"); }, "0x0", "malformed"])
  ("fails closed when estimateGas fails or is malformed", async (gas) => {
    await expect(estimatePaymentFees(provider({ eth_estimateGas: gas }), native)).rejects.toThrow(FEE_ESTIMATE_ERROR);
  });

  it.each([4001, 4900, 4901])("does not fallback/retry a rejected or disconnected provider request (%s)", async (code) => {
    const error = Object.assign(new Error("Wallet request stopped"), { code });
    const rpc = provider({ eth_maxPriorityFeePerGas: () => { throw error; } });
    await expect(estimatePaymentFees(rpc, native)).rejects.toBe(error);
    expect(rpc.request.mock.calls.some(([arg]) => ["eth_feeHistory", "eth_gasPrice", "eth_sendTransaction"].includes(arg.method))).toBe(false);
  });

  it.each(["chain", "account"])("stops if %s changes during estimation without an event", async (changed) => {
    let estimating = false;
    const rpc = provider({ eth_estimateGas: () => { estimating = true; return "0x186a0"; },
      eth_chainId: () => estimating && changed === "chain" ? "0x1" : "0x66eee",
      eth_accounts: () => estimating && changed === "account" ? [receiver] : [wallet] });
    await expect(estimatePaymentFees(rpc, native)).rejects.toThrow(changed === "chain" ? "Network changed" : "Wallet changed");
  });

  it("honors the caller's authentication/provider epoch guard even when account switches away and back", async () => {
    let changed = false;
    const error = Object.assign(new Error("Authentication changed"), { stopFeeEstimation: true });
    const rpc = provider({ eth_estimateGas: () => { changed = true; return "0x186a0"; } });
    await expect(estimatePaymentFees(rpc, native, () => { if (changed) throw error; })).rejects.toBe(error);
  });

  it("bounds read timeouts/deadline and cannot submit on late resolution", async () => {
    vi.useFakeTimers();
    let finish;
    const rpc = provider({ eth_estimateGas: () => new Promise((resolve) => { finish = resolve; }) });
    const result = expect(estimatePaymentFees(rpc, native)).rejects.toThrow(FEE_ESTIMATE_ERROR);
    await vi.advanceTimersByTimeAsync(8000);
    await result;
    const count = rpc.request.mock.calls.length;
    finish("0x186a0");
    await vi.advanceTimersByTimeAsync(60000);
    expect(rpc.request.mock.calls).toHaveLength(count);
    expect(vi.getTimerCount()).toBe(0);
  });

  it("has a total 30-second ceiling even if every fee source hangs", async () => {
    vi.useFakeTimers();
    const never = () => new Promise(() => {});
    const rpc = provider({ eth_getBlockByNumber: ([block]) => block === "pending" ? never() : { baseFeePerGas: "0x64" },
      eth_maxPriorityFeePerGas: never, eth_feeHistory: never, eth_gasPrice: never });
    const result = expect(estimatePaymentFees(rpc, native)).rejects.toThrow(FEE_ESTIMATE_ERROR);
    await vi.advanceTimersByTimeAsync(30000);
    await result;
    expect(vi.getTimerCount()).toBe(0);
    expect(rpc.request.mock.calls.some(([arg]) => arg.method === "eth_estimateGas")).toBe(false);
  });
});
