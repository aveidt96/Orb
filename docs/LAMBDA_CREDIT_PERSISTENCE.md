# Wallet 404 handling and Lambda credit persistence

## Findings (2026-10-22)

The public Vercel bundle `/assets/index-D1WXgsm8.js` points at
`https://orb-api-7qwv.onrender.com`, not Lambda. Both Render and the AWS
Function URL expose `/api/orb/credits/quotes` and
`/api/orb/credits/quotes/{quote_id}/verify`: empty unauthenticated POSTs
returned 401, not route-not-found 404. No authenticated purchase or live
wallet transaction was submitted during this investigation.

The payment implementation lives in `web/wallet.js`, with fresh fee estimation
in `web/payment-fees.js`. `web/app.js` handles AI workflows. An extension's
internal `Request failed with status code 404` cannot be attributed conclusively
without its diagnostics. Separately, old Lambda invocations used container-local
SQLite, so a verification invocation could genuinely lose a previous quote and
return `Payment quote was not found.` Signed tokens restored identity, not
purchased credit history.

## Wallet behavior

- The exact quoted receiver, value and native quote-binding/ERC-20 calldata
  remain unchanged. ETH/USDG price and backend receipt verification are unchanged.
- `eth_estimateGas` uses that exact transaction. Submission now includes
  `gas = max(100000, ceil(estimate * 1.2))`, in canonical hex, alongside the
  existing fresh EIP-1559 fees. A fixed 100k cap is unsafe because Arbitrum's
  estimate includes variable L1 posting costs.
- On a wallet fee-RPC 404 only, read-only fee/estimation calls can use
  `https://sepolia-rollup.arbitrum.io/rpc`, first checking `eth_chainId` equals
  421614. Existing eight-second RPC and thirty-second estimation deadlines,
  and account/network/quote validity checks remain. Rejections, execution
  reverts and other errors do not trigger this fallback. No fallback can sign
  or send a transaction.
- Missing-chain registration uses `wallet_addEthereumChain` with the official
  RPC, followed by explicit switching. A wallet-side 404 exposes a user-driven
  **Register Arbitrum Sepolia** repair action. It never automatically sends again.
- If the extension still rejects submission, copy distinguishes wallet failure
  from Orb quote-route failure and advises checking wallet activity. Existing
  access-code Judge Demo remains available. An arbitrary client-reported 404
  never mints paid wallet credits or bypasses the demo code/rate limits.

## Durable S3 ledger

When Lambda/serverless execution has no `ORB_DATABASE_URL`, all credit state is
authoritative in a **private, encrypted** object:

`s3://<ORB_AWS_S3_BUCKET>/orb-credits/ledger-v1.sqlite3`

Each operation loads a fresh snapshot into an in-memory SQLite connection. All
wallets, challenges, sessions, quotes (ETH and USDG), accepted tx hashes,
reservations and completed result JSON share one transaction boundary. Writes
publish with S3 `If-Match` against the loaded ETag; initial bootstrap uses
`If-None-Match: *`. No unconditional overwrite is used. Conditional conflicts
retry the complete business operation against a fresh snapshot (up to eight
attempts with short jitter); no blockchain transaction or AI call is retried.

Per-wallet JSON backups would not atomically protect global transaction-hash
uniqueness, quote completion and balance changes. Token-encoded balances could
replay old spending state. Neither is used. Spendable balances remain server-side.

- S3 failures return 503; no local/stale fallback or successful grant is reported.
- Logged-out sessions cannot be reconstructed from old signed tokens on S3.
- Used challenges remain consumed across containers.
- Cold starts do not reconcile/release another container's active reservations.
- Completed result JSON is stored in the ledger before settlement. Image/media
  artifact storage continues through the existing separate S3 job system.
- Interrupted reservations remain durable; they are not blindly released on a
  cold start. A truly interrupted job may need targeted reconciliation. This
  change does not introduce an unsafe timer-based refund while a job is active.
- A missing, corrupt or unsupported ledger fails closed. Only explicit deployment
  bootstrap may initialize a new object; it cannot overwrite an existing one.
- This serialized snapshot strategy is for Orb's small testnet workload, capped
  at 16 MiB. Use the existing transactional Postgres adapter for larger scale.

`ORB_DATABASE_URL`, if configured for Lambda, selects Postgres instead. Local
development SQLite and existing production Render/Postgres remain supported.
No existing Postgres schema or data migration is performed by this change.

## Deployment and migration boundaries

The existing deployment script bootstraps a fresh S3 ledger explicitly, then
deploys code. It preserves existing settings (including methods, prices, keys,
receiver and session secret), IAM role, package type, memory and Function URL.
It refuses package-type replacement instead of deleting the live function.
The deployment zip includes boto3 with conditional-write support and psycopg.

There was no durable Lambda credit ledger before this fix. New bootstrap is
**not a recovery of inaccessible old `/tmp` databases**. Old Lambda sessions
require reauthentication; an old missing quote cannot be invented or credited
without independent evidence. Any historic Lambda payment recovery requires
its transaction hash, quote details and an audited reconciliation. Render's
Postgres balances are separate and are not imported/reset. Do not point the
Vercel site at Lambda as a shortcut to migration.

The GitHub deployment workflow supports `[skip aws]` in a commit message, so a
manual exact-code deployment does not trigger another competing AWS deployment
when pushed. Vercel/Render may still perform their normal configured Git deploys.
No `dev` branch is created if it does not already exist.

## Validation boundaries

Mocked S3/RPC tests exercise conditional conflicts, simultaneous verification,
single-credit concurrent reservations, idempotency, persistent result recovery,
successful/failed settlement, nonce replay, logout, Judge Demo consumption,
USDG receipts and failure handling. Frontend tests cover wallet/provider 404,
backend-route 404, explicit RPC registration, fresh gas fields and exact payloads.
These do not prove that a particular installed Zerion version accepts Sepolia
transactions. A human-approved real testnet purchase remains the final check.
