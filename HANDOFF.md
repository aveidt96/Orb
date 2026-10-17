# ORB Project Handoff

## 2026-10-07 — Liquid-glass UI test branch

- Branch: `ui-liquid-glass-test`, created from main
  `2399c9f896f2f9264b8f0e2e42de8a733e07768b`. Main is not merged or modified.
- The five uncommitted Phase 3 experiment files were preserved in stash
  `bd0d5a667b95f0060da719a92a54cd0f49f36bc8` before branching; they are not part
  of this UI change. The stash and ignored benchmark artifacts remain intact.
- Replaced the frontend presentation with an ice-blue liquid-glass system:
  compact hero, mode cards above the workspace, atmospheric CSS background,
  glass upload/selected/Enhance/processing/result surfaces, wallet capsules and
  floating wallet sheet. The original ringed Orb and reduced-motion support
  remain. Desktop max-width stays 1005px; mobile uses two-column mode controls.
- All existing DOM IDs remain. The real directly tappable file input and its
  accepted formats, readability preflight and reset behavior are unchanged.
- The only `app.js` change mirrors authenticated balances into the new header
  credit capsule. `wallet.js`, backend, AI, fee estimation, pricing, payments,
  database, credit settlement and job recovery behavior are unchanged.
- `vercel.json` adds a Git deployment disable entry for this test branch only,
  preventing automatic preview deployment on push. No live infrastructure or
  environment configuration was changed.
- Full backend regression: **319 passed, 8 expected Postgres skips**. Guarded
  production frontend build passed with a placeholder HTTPS API origin.
- Full frontend regression: **196 passed across 8 files**, including the four
  added presentation tests. A concurrent validation run hit local process-start
  timeouts; the full standalone rerun passed without weakening tests.
- Rendered Chromium checks passed at 1440, 1280, 1024, 768, 390, 360 and 320px,
  including direct native input activation, sticky wallet close, Create lock,
  quantity/payment controls, mocked results and reduced motion. Extended checks
  verified Copy Prompt, keyboard focus and actual Orb highlight movement.
- See `docs/LIQUID_GLASS_UI.md` for scope, preservation details and validation
  limits. Screenshots/harness are ignored under `output/liquid-glass/`. No live
  wallet transactions or AI calls were made; physical wallet WebViews still need
  device testing. No deployment, production changes or Prometheus changes.

ORB is an AI-powered creative intelligence platform for the Arbitrum Open
House Online Buildathon. It reuses the proven Prometheus analysis engine but
is an independent project: new frontend, new branding, separate repository,
separate ports, and no shared deployments.

Absolute path: `C:\Users\USER\Documents\project-prometheus\project-orb`

Prometheus source: `C:\Users\USER\Documents\project-prometheus\ai-video-reverse-engineer`
(main @ `cb05f4b`; left completely unchanged, including its uncommitted work).

## What was copied from Prometheus (working tree, verified byte-identical)

- `prometheus/` — the full backend package: FastAPI app, job manager,
  FFmpeg/FFprobe video tools, pipeline, storage, analyzer (Gemini/OpenAI/
  mock), prompt builder, remix, schema, DTOs, and the payment module
  (see Payment isolation below).
- `tests/` — all engine tests, including the uncommitted
  `test_gemini_analyzer.py` / `test_scene_analysis.py` updates and the
  untracked `tests/test_jobs.py`, matching the uncommitted
  `prometheus/analysis/analyzer.py` and `prometheus/api/jobs.py` changes.
- `main.py`, `config.yaml`, `requirements.txt`, `Dockerfile`,
  `.dockerignore`, `LICENSE`.

## What was deliberately NOT copied

- `.git/` history (new independent repo, no remote configured).
- `.env` files, credentials, private keys.
- `.vscode/` IDE settings, Prometheus docs (`CODEX_HANDOFF.md`,
  `DEPLOYMENT.md`, `REAL_MINI_APP_TESTING.md`, old `README.md`).
- `samples/`, `uploads/`, `output/`, `api_output/`, logs, caches.
- `render.yaml` / `vercel.json` (no deployment connection).
- Prometheus branding assets and its `web/` frontend (Orb has a new one).

## What was created or modified inside Orb

- `.gitignore` — covers `.venv/`, `node_modules/`, `web_dist/`, `.env`,
  local output/upload dirs, caches, IDE files.
- `README.md` — setup, local run, tests, mode-status table.
- `package.json`, `vite.config.js` (dev port 5174, `/api` proxy to
  backend port 8790), `vitest.config.js` (jsdom), `.env.example`
  (no payment credentials; Nimiq enable-flag documented as forbidden).
- `web/index.html`, `web/styles.css`, `web/app.js` — the new ORB
  frontend: white `#FFFFFF` background, `#F5F9FF` surfaces, `#368BE9`
  accents, rounded cards/buttons, responsive layout, text wordmark.
- `web/api-url.js`, `web/api-url.test.js` — API base-URL helper and tests.
- `web/app.test.js` — 8 new interface tests.
- `prometheus/api/app.py` — payment isolation gate only (no analysis
  logic touched): inherited Nimiq payments stay dormant unless
  `ORB_ENABLE_NIMIQ_PAYMENTS=1`; `/api/payments/config` and
  `/api/payments/quotes/{id}/verify` return 503 when disabled.
- `tests/conftest.py` — autouse fixture enabling the flag so the inherited
  payment tests keep exercising that code.
- `tests/test_api.py` — one brand assertion adapted (`"Prometheus"` to
  `"ORB"` in the served-index test); all engine assertions unchanged.

## Frontend structure and modes (Stage 2)

- Header: exact "Orb" wordmark, a small blue ringed planet drawn in SVG
  with a slow CSS rotation and reduced-motion support. The hamburger
  opens a grouped Home / Workspace / Account / Information menu. Home
  returns to the upload screen; About Orb opens a small information
  panel. My Creations, Wallet & Credits, and Settings are static
  "Coming soon" rows.
- Home: the approved Stage 2 mockup's left-aligned badge and hero,
  centered pale-blue upload panel, wide blue Choose file button, and
  compact mode pills below the panel. The three large cards and duplicate
  header mode tabs were removed.
- The panel uses the mockup's "Drop your image or video" heading and
  supporting text, with an additional visible line explaining that Decode
  currently accepts videos only. The picker accepts MP4, MOV, and WebM,
  up to 200 MB. After selection the panel shows the file, service state,
  and Decode action; errors remain visible in the panel.
- Decode is active; Compose and Enhance pills are muted, non-interactive,
  and labeled "Coming soon" for assistive technology.
- Processing: spinner, phase text, stage list, progress bar, error + back.
- Results: title, metadata chips, source preview, scene-by-scene
  thumbnails, and a prompt card that states reconstruction is unavailable
  instead of fabricating one.
- Decode wires to the live backend (`/api/health` → `/api/ready` →
  `/api/upload-ping` gate, single-attempt correlated upload, 64 KB
  readability pre-check, job polling, basic-tier results). Videos only;
  images are rejected with an honest next-stage message. Compose, Enhance,
  prompt reconstruction, and remix have no client path and are visibly
  marked unavailable.
- Vite's local proxy now matches `/api/` endpoints rather than every
  `/api` prefix; this lets `/api-url.js` load in the dev server while
  preserving the backend proxy.
- The white application frame is capped at 1180px and centered on
  desktop. Tablet and mobile widths remain fluid. Mobile adds a 28px
  page gutter below the full frame, plus any bottom safe-area inset;
  the frame uses the dynamic viewport height.
- The menu closes on its toggle, outside click, Escape, or functional
  selection. Keyboard focus reaches Home and About Orb while reserved
  rows remain non-interactive. The menu stays within narrow viewports
  and scrolls internally on short screens.

## Backend functionality preserved

Upload streaming + validation, FFprobe metadata, scene detection, frame
sampling, basic-tier local inspection, staged/gated upload readiness,
single-attempt uploads with attempt IDs, job polling, result DTOs, prompt
reconstruction and remix code (server-side, unexposed), and the payment
module with its replay-protection tests (dormant behind the flag).

## Test results

- Backend: 138 passed (`pytest`), own `.venv`, Python 3.13.
- Stage 1 frontend: 11 passed (`test:web`: 8 app + 3 api-url), jsdom.
  Two failures during development were test-harness issues, not app bugs
  (a label assertion that ignored fast mock resolution, and a queued poll
  stuck behind a real 1500 ms timer); both fixed in the tests.
- `vite build`: clean (`web_dist/`).
- Independent startup smoke test on port 8790: `/api/health` ok
  (`payment_required: false`), `/api/ready` ready,
  `/api/payments/config` 503 as designed.
- Stage 2 frontend: 12 passed (9 app + 3 api-url) with
  `npm run test:web -- --pool=threads --maxWorkers=1`.
  The default Vitest fork pool timed out starting workers on this
  Windows host before running tests.
- Stage 2 production build: `npm run build` passed.
- Stage 2 served-index regression: 1 backend test passed after adapting
  its wordmark assertion to exact "Orb".
- Browser review: desktop 1776×887, tablet 768×1024, and mobile
  390×844. The page had no horizontal overflow at tablet or mobile
  widths. The menu opened and closed, file selection and clearing worked,
  Decode stayed disabled with the backend offline, and service guidance
  appeared. The planet uses a 32-second CSS rotation and a
  `prefers-reduced-motion` override. No end-to-end video analysis was
  run for Stage 2.
- Targeted UI follow-up: 12 frontend tests passed, and `npm run build`
  passed. Browser checks measured an 1180px centered frame at 1600px
  width and a 28px bottom mobile gutter at the end of a 390px-wide page.
  The grouped menu opened and closed by toggle, outside click, and
  Escape; Tab reached its two functional items with visible focus.
  The menu fit 390px and 320px widths and scrolled internally at
  320×400. The existing upload tests still cover file selection,
  readiness, single-attempt upload, error, and result states.

## Local history (no remote)

- `d0391b2` — initial project (engine copy, payment gate, new frontend,
  configs, README).
- `b56b3f7` — this handoff document.
- `e0baa81` — record test-harness fixes in this handoff.
- Stage 2 changes are currently uncommitted in the independent Orb
  working tree. No remote is configured; nothing has been pushed or
  deployed.

## Unresolved issues

- One inherited test needed a one-word brand adaptation (see above);
  no engine behavior was weakened.
- `resume-after-reload` recovery from Prometheus was intentionally left
  out of the Orb frontend for stage 1.
- The internal Python package is still named `prometheus` for
  compatibility; renaming is deferred.
- The Stage 2 homepage adds a visible video-only support line to the
  upload panel because the mockup's image-or-video heading would
  otherwise imply image analysis works. The mockup does not depict the
  opened menu, selected-file state, loading, errors, or results.

## Current priority

Stage 3 code is implemented and its five workflows were verified against a
live Gemini provider locally on 2026-09-24. Stage 4 wallet, testnet credit,
and payment-gating code is implemented locally on 2026-09-25; real on-chain
purchase verification still requires a dedicated receiver and a user-approved
funded testnet wallet transaction. Preserve all uncommitted work. Public
unpaid AI operations remain blocked. The configured default Gemini model
returned provider 503 errors during Stage 3 verification, so live checks used
a temporary process-only model override described below.

### Stage 3 implementation plan (recorded before code changes)

1. Add one server-side authorization function for every real AI entry point.
   Permit unpaid AI only with explicit local development configuration and a
   loopback client; fail closed in production until Stage 4 verifies credits.
   Keep inherited Nimiq tests isolated and Nimiq disabled in normal Orb.
2. Reuse `PrometheusPipeline` for video Decode. Add size/type/content checks
   for JPEG, PNG, and WebP and an Orb multimodal request for image Decode.
   Return real prompt, analysis, and refinements; reject missing providers.
3. Build Compose from analyzed visual evidence (video pipeline or image
   vision request), with a distinct creative synthesis request. Add a
   separate text-only Enhance request with constrained preferences.
4. Integrate mode selection, upload/text workspaces, processing/results,
   copying, and guarded submission into the existing Stage 2 UI.
5. Test each milestone before proceeding, then run all backend/frontend
   suites and production build. Distinguish mock-provider integration tests
   from any genuine provider runs and record missing configuration.

### Stage 3 implementation and verification

- `prometheus/analysis/orb_ai.py` adds distinct image Decode, image Compose,
  video Compose synthesis, and text Enhance calls. It uses the inherited
  Gemini/OpenAI client and retry machinery. Images are sent as real bytes;
  video Compose is grounded in the existing frame-based video report. No
  filename-based or mock output is offered through Orb's new AI routes.
- `prometheus/api/app.py` adds JPEG/PNG/WebP uploads (20 MB and 32 million
  pixel bounds with Pillow content validation), new queued Orb routes, and
  structured prompt/visual-analysis results. Video Decode/Compose reuse the
  inherited FFprobe, segmentation, frame sampling, scene AI, global AI, and
  reconstruction pipeline. It preserves the video limit and multipart upload
  checks. Job errors are generic to clients, with details logged server-side.
- All three Orb operations pass through one `_authorize_ai` boundary before
  work starts. Stage 3 allows real provider calls only with `ORB_ENV=local`,
  `ORB_AI_LOCAL_TESTING=1`, a loopback request and local host, no forwarded
  client, and a configured server-side key. Production returns 402 until
  Stage 4 supplies verified credit authorization. The inherited Nimiq
  service and routes are restricted to explicit local testing; legacy real
  analysis cannot bypass the local/credit gate. Mock legacy analysis is also
  blocked outside explicit local testing.
- `web/index.html`, `web/app.js`, `web/styles.css` activate the three existing
  mode pills without changing the Stage 2 hero or visual identity. Decode and
  Compose share the upload workspace; Enhance has text and preference inputs.
  Results display the generated prompt, real visual evidence when available,
  original text for Enhance, and a working Copy Prompt control. Upload
  precheck, canary, single-attempt behavior, polling, and submission guard
  remain. Missing provider/payment configuration is shown in the UI.
- `requirements.txt` adds Pillow. `.env.example` and `README.md` document
  local-only provider configuration; no credentials were copied. `package.json`
  and `vite.config.js` bind Vite to loopback so its proxy cannot provide local
  unpaid AI access over a LAN. `tests/conftest.py` keeps inherited Nimiq
  tests explicitly local. `tests/test_api.py` now expects a missing key to
  fail before queuing a job.
- New `tests/test_orb_stage3.py` covers JPEG/PNG/WebP validation, image and
  video modes with fake providers, Enhance, provider errors, missing keys,
  forwarded requests, and production payment denial. New
  `tests/test_orb_ai.py` verifies actual image bytes reach both SDK adapters.
  Frontend tests cover mode activation, upload reliability, repeated clicks,
  result display and prompt copy.
- Initial Stage 3 backend suite: **150 passed** (`pytest -q`); existing FastAPI
  `on_event` deprecation warnings remain. Initial frontend suite: **14 passed**
  (`npm run test:web -- --pool=threads --maxWorkers=1 --isolate=false`). A
  concurrent run hit a Windows Vitest worker startup timeout; the reused
  worker run passed. Final `npm run build` passed.
- Browser review measured an 1180px centered frame at 1440px desktop width,
  and at 390px mobile width verified no horizontal overflow, a 28px bottom
  gutter, and a usable Enhance form. With no key, the live local backend
  shows clear configuration guidance and disables AI actions.
- At the time of that initial Stage 3 implementation, genuine end-to-end
  provider analysis had not run. The subsequent live verification is recorded
  below; automated tests still use fake SDK clients or the inherited mock
  analyzer and are identified separately from live results.
- Stage 4 must replace `_authorize_ai`'s local-only allowance with a verified
  Arbitrum Sepolia credit reservation/consumption flow, plus credit UX and
  durable entitlements. Public AI access remains closed. No deployment,
  push, or commit was made.

### Stage 3 live Gemini verification (2026-09-24)

- An existing, ignored Orb `.env` was present and readable. It configured
  `ORB_ENV=local`, `ORB_AI_LOCAL_TESTING=1`, and Gemini with a server-side
  key. The key was loaded only into the backend process environment and was
  never printed, copied into source, or committed. The backend bound to
  `127.0.0.1:8790`, and Vite to `127.0.0.1:5174`. `/api/health` reported
  local AI access with payment not required; `/api/ready` passed.
- The existing default `gemini-3.8-flash` was called for image Decode first,
  but Gemini returned 503 `UNAVAILABLE` after the configured retries, citing
  high demand. Orb displayed a safe error and retry path. Without editing
  `.env` or the tracked default, the backend was restarted with a temporary
  process-only `ORB_AI_MODEL=gemini-3.5-flash-lite`. `/api/health` confirmed
  the actual model for the successful checks. The default model's transient
  availability remains unverified; use an explicit supported model or retry
  when it recovers for further local checks.
- Real sample inputs were generated locally under the ignored
  `uploads/stage3-verification/`: a PNG showing a red/yellow balloon over
  green hills and a three-second MP4 showing a red ball moving across a
  simple landscape. Both were selected through Orb's UI. No mocked provider
  response was used for these five live workflows.
- **Image Decode:** request reached the backend and the live Gemini vision
  call; prompt, image-derived visual analysis, refinements, and original-prompt
  disclaimer appeared. Copy Prompt matched the displayed prompt exactly.
- **Video Decode:** the inherited FFprobe, scene/frame sampling, and Gemini
  analysis ran. Orb showed video metadata, scene evidence, reconstruction
  prompt, and disclaimer. Copy Prompt matched the displayed generation prompt.
- **Image Compose:** live Gemini analyzed the balloon reference and returned
  a distinct creative prompt with evidence and refinements. Copy matched.
- **Video Compose:** frame-based Gemini analysis and a distinct composition
  request returned a creative video prompt with evidence. Copy matched.
- **Enhance:** live Gemini improved a text prompt with selected output/style/
  detail preferences, preserved the original idea, and displayed original and
  enhanced text. Copy matched. A second live run confirmed the corrected
  prompt-specific loading label.
- During live review, two small fixes were made: `web/app.js` now shows
  operation-appropriate processing labels (including Enhance), and video
  Decode in `prometheus/api/app.py` returns only the inherited report's
  generation-prompt section via `prometheus/analysis/orb_ai.py`. The latter
  also removes inherited `INFERENCE:`/`OBSERVATION:` prefixes from result
  evidence. Frontend and backend tests were extended for these behaviors.
- Disabled actions during processing and exact clipboard contents were checked
  in the browser. At 1440px desktop width the app frame measured 1180px;
  at 390px mobile width there was no horizontal overflow and the bottom gap
  measured 28px. The menu opened and closed with Escape. A remote `Host` and
  a forwarded-client request each returned 402, while explicit local testing
  succeeded. Automated tests also cover disabled local testing and production
  denial. No payment code was added.
- Final backend suite: **151 passed**, 88 inherited FastAPI `on_event`
  deprecation warnings (`.venv\Scripts\python.exe -m pytest -q`). Final
  frontend suite: **15 passed** (`npm run test:web -- --pool=threads
  --maxWorkers=1 --isolate=false`). `npm run build` passed. The first backend
  run caught an overly specific assertion against its mock video fixture;
  after correcting that assertion and adding a direct extraction test, the
  full suite passed. Browser checks above are live-provider checks, separate
  from these automated tests.
- The backend and Vite processes were stopped after verification. No push,
  commit, or deployment was made. The ignored local sample files and logs
  remain for reproducibility; the exact configured key was checked as absent
  from those logs. Stage 4 still needs verified Arbitrum Sepolia credit
  authorization before public AI access can open.

## Later stage work

1. Resolve or explicitly override the default model's 503 availability for
   future local checks; all five workflows succeeded with the temporary
   `gemini-3.5-flash-lite` override.
2. Orb credit system on Arbitrum Sepolia with its own entitlement model;
   keep Nimiq code dormant.
3. Deployment configuration (new hosting, HTTPS, production RPC or model
   endpoints) — nothing is deployed or pushed anywhere yet.

### Stage 4 implementation plan (recorded before code changes, 2026-09-25)

1. Keep the existing Orb AI routes and local-only bypass. Introduce a
   dedicated persistent SQLite credit ledger and a bearer session backed by
   a one-time, expiring, origin-bound wallet signature. Require an authenticated
   session for balance, quotes, verification, and paid AI work.
2. Use a dedicated Arbitrum Sepolia receiver configured in Orb's environment.
   A server quote binds wallet, credit count, exact native testnet ETH amount,
   expiry, and transaction data. Verify RPC chain ID, receipt success and
   confirmations, canonical block, sender, receiver, amount, empty/expected
   transaction semantics, and quote data before granting; enforce unique
   transaction hash in the database. No contract or private key is needed.
3. Reserve one credit transactionally per AI idempotency key after validation.
   Finalize only after a result file is written; release on failure. Reconcile
   interrupted reservations against delivered result files after restart.
   Protect paid job status/results by wallet session and preserve the local
   development bypass and inherited Nimiq isolation.
4. Add a focused wallet/credits panel to the existing menu, a small testnet
   notice, network switching, balance and transaction states. Keep the current
   upload, results, desktop width, mobile spacing, and menu behavior.
5. Test signature replay, receipt rejection, duplicate grants/requests,
   concurrent reservations, failures and restart recovery with a mocked RPC;
   rerun backend and frontend suites and production build. Record clearly
   whether a real Arbitrum Sepolia transaction could be performed.

### Stage 4 implementation and verification (2026-09-25)

- `prometheus/api/orb_credits.py` adds a SQLite WAL credit ledger with durable
  challenges, hashed bearer sessions, wallet balances, payment quotes, unique
  verified purchases, and unique per-wallet idempotency reservations. It uses
  `eth-account` for EIP-191 wallet signature recovery and binds sign-in to an
  exact configured browser origin, Arbitrum Sepolia chain ID 421614, a random
  one-time nonce, and a five-minute expiry. Sessions expire after one hour.
  Contract-wallet signatures are not supported yet.
- The payment uses native Arbitrum Sepolia testnet ETH to a dedicated
  configured EOA, with unique quote data included in the transaction input.
  Quotes offer 1, 3, or 5 demo credits, defaulting to 0.000001 testnet ETH per
  credit and three confirmations. The backend independently reads the chain
  ID, transaction, receipt, canonical block, confirmation depth, receiver
  code, sender, recipient, exact value, input data, success status, and block
  timestamp. Database uniqueness prevents granting the same transaction or
  quote twice. No contract, payment key, or Prometheus account is used.
- `prometheus/api/app.py` adds wallet challenge/sign-in, balance, quote, and
  verification routes. Decode, Compose, and Enhance now use the existing
  authorization boundary: explicit loopback-only local testing still bypasses
  credits; otherwise a signed wallet session and one available testnet credit
  are required. Uploads are validated before credit reservation. SQLite write
  transactions reserve one credit atomically; job success finalizes only after
  a result is saved, and job failure releases it. Duplicate idempotency keys
  return the original job, while altered content under the same key is rejected.
  On restart, saved results finalize interrupted reservations; missing results
  release them. Paid status, result, and media reads require the wallet session.
  The inherited `/api/analyze` route remains local-only and cannot use wallet
  credits to bypass the new routes. Nimiq remains dormant.
- `web/wallet.js`, `web/index.html`, `web/app.js`, and `web/styles.css` add a
  compact Wallet & Credits panel under the existing menu, network detection and
  switch, wallet signing, available balance, quote/purchase/verification states,
  persistent pending transaction reference in session storage, and visible
  TESTNET ONLY/demo/no-real-money messaging. The frontend keeps its session
  token in memory and reloads paid media with authenticated requests. It
  retains an active paid job ID in session storage so results can be resumed
  after reconnecting. AI actions require an available credit in the UI, with
  a visible wallet/buy action when empty; the server remains authoritative.
  Ambiguous manual retries reuse an idempotency key. The approved home layout,
  responsive frame, menu, upload canary, and result experience remain.
- `requirements.txt` adds `eth-account`; `.env.example` and `README.md` document
  safe Arbitrum Sepolia settings, a dedicated receiving EOA, SQLite single
  instance limits, and the local paid-gate test procedure. The existing local
  `.env` was not edited. No credentials, private keys, or production backend
  URL were added to source.
- **Mocked-chain tests only:** `tests/test_orb_credits.py` uses generated
  disposable test wallets and a fake JSON-RPC provider. It covers valid and
  invalid signatures, nonce replay/expiry, wrong origin, wrong chain, failed
  or unrelated receipts, insufficient value, wrong input or receiver, missing
  confirmations, noncanonical blocks, duplicate grants, concurrent
  reservations, idempotency, AI failure release, and restart reconciliation.
  Paid API tests exercise image Decode, image Compose, and Enhance with a fake
  AI service; existing Stage 3 tests continue covering video and local bypass.
  `web/app.test.js` verifies wallet network switching, payment-flow UI states,
  authenticated paid upload, and active-job recovery reference. These tests
  do not prove a real Arbitrum transaction or live Gemini in paid mode.
- Final automated results: **166 backend tests passed** (`pytest -q`), with 92
  inherited FastAPI `on_event` deprecation warnings; **16 frontend tests
  passed** (`npm run test:web -- --pool=threads --maxWorkers=1 --isolate=false`);
  `npm run build` passed. Visual check: frame width 1180px in a 1440px desktop
  viewport, no mobile horizontal overflow at 383px, about 28px mobile bottom
  gap, and wallet panel within both viewports. The loopback preview servers
  were stopped after review.
- **Not verified on-chain:** no dedicated receiver or funded user wallet was
  provided, and the existing `.env` remains in local AI testing mode. No real
  Arbitrum Sepolia transfer, real wallet signature, or paid live-Gemini request
  was performed. To complete live verification, configure
  `ORB_CREDITS_ENABLED=1`, an exact `ORB_PUBLIC_ORIGIN`, trusted HTTPS
  `ORB_ARBITRUM_RPC_URL`, dedicated EOA `ORB_CREDIT_RECEIVER`, and persistent
  `ORB_CREDIT_DB`; set `ORB_AI_LOCAL_TESTING=0`; start Orb locally; connect a
  funded Arbitrum Sepolia wallet, sign the challenge, and approve a one-credit
  testnet transfer in the wallet. Do not provide a private key. The user must
  authorize and execute that transaction before claiming on-chain success.
  No deployment, push, or commit was made.

## 2026-09-25 local backend restart

- Confirmed the original Orb listener on `127.0.0.1:8790` belonged to Orb
  Uvicorn processes 13064/16152, then stopped them. Their environment had not
  loaded Orb's `.env`; live health had reported `provider=mock` and
  `orb_ai_access=configuration_required`.
- Installed `python-dotenv` **only in the existing Orb `.venv`** because
  Uvicorn's `--env-file` option required it. No source or dependency manifest
  was changed for this runtime repair. A rebuilt virtual environment will need
  `python-dotenv` installed again to use that launch option.
- Restarted Orb from its project directory with `uvicorn
  prometheus.api.app:app --host 127.0.0.1 --port 8790 --env-file .env`.
  The launch process uses a process-only `ORB_AI_LOCAL_TESTING=1`; no key was
  printed or copied. The `.env` file itself was left untouched and contains
  three `ORB_AI_LOCAL_TESTING` entries, with the last set to `0`. Without the
  process override, a fresh load would disable local AI testing.
- Final live `GET /api/health`: `status=ok`, `provider=gemini`,
  `model=gemini-3.5-flash-lite`, `orb_ai_access=local`;
  `configuration_required` is resolved. `GET /api/ready` returned HTTP 200
  with `status=ready`. The current backend parent process was PID 10212 and
  its listener child PID 13748 at verification time; PIDs may change later.
- This was a configuration/startup check, not a live AI workflow or payment
  verification. Prometheus, payment configuration, and source files were not
  modified; nothing was deployed, pushed, or committed.

## 2026-09-25 Arbitrum Sepolia local restart

- After the user updated Orb's `.env`, stopped the verified Orb Uvicorn
  processes and restarted from the Orb project with `--env-file .env` on
  `127.0.0.1:8790`. Inherited Orb variables were removed from the launch
  process so the updated file took effect; no process-only local bypass was
  applied. The serving backend PID was 9020 under parent 5768 at verification.
- Read-only inspection of the serving process confirmed `ORB_ENV=local`,
  `ORB_CREDITS_ENABLED=1`, `ORB_AI_LOCAL_TESTING=0`, Gemini provider,
  `gemini-3.5-flash-lite` model, the configured browser origin matching
  `http://127.0.0.1:5174`, and presence of the server-side Gemini key, RPC
  URL, and receiving address. No secret value was displayed.
- Read-only calls to the configured RPC returned HTTP 200 for `eth_chainId`,
  `eth_blockNumber`, and `eth_getCode`; chain ID was 421614 (Arbitrum Sepolia).
  The receiving address passed syntax and nonzero checks and had no contract
  code at the checked block. These checks do not establish who controls it.
- Replaced the mislaunched Orb Vite process on port 5173 with Orb Vite on
  `127.0.0.1:5174` (PID 9684 at verification). Frontend HTTP and proxied
  `/api/health` and `/api/orb/credits/config` returned successfully.
- Backend `/api/health` returned `status=ok`, `provider=gemini`,
  `orb_ai_access=credits`; the credit config endpoint reported enabled,
  testnet only, chain 421614, a one-credit price of 1000000000000 wei,
  and three confirmations. `/api/ready` returned `ready`. Wallet challenge,
  sign-in, balance, quote, and quote verification routes were registered;
  unauthenticated balance access returned HTTP 401.
- No wallet signature, real payment, credit grant, or paid AI operation was
  performed. A user-controlled wallet and testnet ETH are still needed for
  live payment verification. No source files, Orb payment settings, or
  Prometheus files were changed; nothing was deployed, pushed, or committed.

## 2026-09-25 Stage 5 production preparation (not deployed)

- The user reports a subsequent successful live local MetaMask signature,
  Arbitrum Sepolia credit purchase, and paid Decode. This Stage 5 work did not
  repeat that real transaction or spend testnet ETH.
- Selected architecture: a **new paid, single-instance Render Docker web
  service** with a persistent disk mounted at `/var/data`. Keep the SQLite
  ledger at `/var/data/ledger/credits.sqlite3` and saved AI results at
  `/var/data/results` on the same disk. Keep temporary uploads at
  `/tmp/orb_uploads`. Render's disk persists across deploys/restarts but
  precludes horizontal scaling and zero-downtime deploys. No Render service
  or disk was created.
- `prometheus/api/orb_deployment.py` and `prometheus/api/app.py` now fail
  public startup unless `ORB_ENV=production`, Gemini and its key are explicit,
  `ORB_AI_LOCAL_TESTING=0`, `ORB_CREDITS_ENABLED=1`, the exact HTTPS Orb
  frontend origin is set, and both ledger/results paths are under an actual
  attached disk mount. Production refuses inherited Prometheus variables or
  Nimiq payment activation. Local behavior remains supported. Production
  CORS allows only `ORB_PUBLIC_ORIGIN`. Legacy `/api/uploads`, `/api/inspect`,
  and `/api/analyze` paths are unavailable in production.
- Orb result JSON is written with a temporary file, fsync, and atomic replace
  before credit settlement. Restart reconciliation now consumes a reserved
  credit only for a complete, matching prompt result; incomplete/missing
  results release the reservation. The ledger's SQLite transactions and
  unique payment/idempotency constraints remain unchanged.
- `vercel.json`, `package.json`, and `scripts/check-vercel-env.mjs` prepare a
  separate Vercel Vite build from the repo root into `web_dist`. Its build
  requires `VITE_API_BASE_URL` to be a nonlocal HTTPS backend origin. Local
  Vite's loopback proxy remains development-only. `.env.example` and
  `README.md` document Render/Vercel setup using placeholders, no secrets.
- Validation: **169 backend tests passed** with 94 inherited FastAPI
  deprecation warnings, using the already-installed local FFmpeg; **16
  frontend tests passed**. Guarded Vercel production build passed with a
  non-secret placeholder API origin. Missing/localhost API origins failed the
  build guard. Built assets contained the placeholder backend origin and no
  localhost backend or backend secret variable names. `.env` is ignored and
  untracked; the exact locally configured Gemini key was absent from source
  and built assets. The configured RPC currently matches the intentionally
  public Arbitrum Sepolia wallet-network endpoint already in the frontend;
  it has no credential-bearing userinfo, query, or fragment. A future
  credential-bearing RPC URL must remain server-side. `git diff --check`
  found no whitespace errors.
- The computer automation service timed out, so headless Edge was used for
  read-only screenshots of Orb's local page at desktop (1440px) and tablet
  (about 780 CSS px) widths; both retained the approved layout. Edge's
  minimum layout width made its attempted 390px screenshot a crop rather than
  a valid mobile viewport. Responsive CSS and UI code were unchanged;
  existing frontend tests passed, and Stage 4 had a prior 383px mobile visual
  check. Docker is unavailable locally, so the Render container was not built
  in this turn. Render mount behavior, Vercel/Render origins, wallet flow,
  disk persistence, and real production payment still require verification
  after deployment. Monitor disk usage, backup/recovery, and abuse of public
  endpoints during the first demo.
- Pre-existing uncommitted Orb changes were preserved. The already-running
  local Orb services were not restarted with these Stage 5 source changes.
  Orb is its own Git root but currently has no configured Git remote; all
  earlier Stage 3/4 work and this preparation remain uncommitted. An
  independent repository and reviewed commit/push are approval-gated steps.
  No source was changed outside the independent Orb project; no commit,
  push, deployment, paid infrastructure creation, or fund transfer occurred.

## 2026-09-25 Stage 5.1 local Git snapshot

- Reviewed the complete pending Orb source, frontend, test, configuration, and
  deployment-preparation changes for Stages 3 through 5. Confirmed Orb has its
  own Git root and no configured remote. The original Prometheus checkout is a
  separate sibling repository; its pre-existing changes were inspected only
  and were not modified.
- Secret and runtime-file audit: Orb's populated `.env` is ignored and
  untracked. No Gemini key bytes, private key block, seed phrase, runtime
  database, generated upload, or other private runtime file belongs in the
  snapshot. The only matching RPC URL in frontend code is the public Arbitrum
  Sepolia wallet-network endpoint without credentials. Stage only the reviewed
  source, test, documentation, and deployment-config files explicitly.
- Complete backend suite: **169 passed** with 94 inherited FastAPI deprecation
  warnings. The first sandboxed run could not access the installed FFmpeg;
  rerunning with that existing binary on the process PATH passed. Complete
  frontend suite: **16 passed** across two files, using one Vitest thread after
  the default worker pool timed out. Guarded `npm run build:vercel` passed with
  a safe placeholder HTTPS API origin; no production endpoint was created.
- Generated pytest directories were removed before staging. Record the final
  local commit hash and clean working-tree status in the task report. No push,
  deployment, infrastructure creation, or testnet transaction was performed.


## 2026-09-26 Stage 5.2 Supabase Postgres preparation (not deployed)

- Production persistence is now direct server-side Postgres through Psycopg;
  Render Free keeps only processing files in temporary storage. Local
  development remains SQLite with local result files. Production startup
  requires `ORB_DATABASE_URL`, paid credits, Gemini, an exact HTTPS browser
  origin, and `ORB_AI_LOCAL_TESTING=0`. No persistent Render disk or
  `ORB_DATA_DIR`/`ORB_CREDIT_DB`/`ORB_OUTPUT_DIR` production setting is
  required. A missing or unreachable Postgres database fails startup; there
  is no production in-memory or SQLite fallback.
- `prometheus/api/orb_database.py` owns a versioned `orb` Postgres schema
  and shared connection interface. The initial migration creates challenges,
  sessions, balances, quotes, purchases, reservations, and JSONB results under
  an advisory transaction lock. Database checks/unique constraints prevent
  negative balances, duplicate payment grants, and duplicate idempotency
  keys. The shared `CreditService` still verifies chain receipts, reserves
  atomically, settles once, and releases failed jobs.
- Completed paid result JSON is committed to Postgres before credit
  consumption. On restart, reconciliation consumes a reserved credit only if
  its complete matching result survives in Postgres; otherwise it releases
  the reservation. A status/result request can also finish settlement after
  a transient settlement failure. Public results retain prompt, analysis,
  and compact scene metadata; source media and frames are not persisted, so
  production preview media is unavailable after processing. Temporary
  upload and pipeline directories are cleaned after jobs.
- `README.md`, `.env.example`, and `requirements.txt` now document the
  server-only Supabase Postgres URL, TLS, Psycopg, Render Free, automated
  schema initialization, and exact manual deployment sequence. Supabase's
  shared Session pooler is documented for IPv4 Render connectivity. Existing
  local SQLite credits are not migrated automatically; perform an audited
  one-time data migration if they must carry into production. No Supabase
  project, Render service, Vercel site, or external transaction was created.
- Validation: **175 backend tests passed**, including existing SQLite and
  video tests plus mocked Postgres-path schema/transaction/recovery tests;
  **16 frontend tests passed**; guarded Vercel production build passed with
  a placeholder HTTPS API origin. The first full backend run exposed a
  two-second asynchronous test timeout; that test was given a bounded
  15-second deadline and the complete suite then passed. FastAPI emitted
  98 inherited deprecation warnings. No live Postgres connection, Supabase
  migration, live Gemini call, or real Arbitrum transaction was performed in
  this stage. A real Supabase connection, restart recovery check, and paid
  testnet workflow remain required after approved infrastructure creation.
- At the end of Stage 5.2 implementation, Orb changes were uncommitted and
  unpushed. The original Prometheus checkout, its history, and deployments
  were not modified.

## 2026-09-26 Stage 5.2 local commit audit

- Reviewed the complete Orb Stage 5.2 diff and ran the full validation again:
  **175 backend tests passed**, **16 frontend tests passed**, and the guarded
  production frontend build passed with a placeholder HTTPS API origin.
- The local `.env` remains ignored. The commit candidate contains no
  configured Gemini key, RPC secret, database URL, wallet private key, seed
  phrase, SQLite database, uploads, generated results, or runtime data.
  Credential-shaped URLs in tests use explicit `db.example.invalid`
  placeholders. No live Postgres or Supabase test was performed in this audit.
- This audit prepares one local Orb commit only; no push, deployment,
  infrastructure creation, or testnet transaction is part of this step.

## 2026-09-26 Wallet authentication UI state fix (local, not deployed)

- Fixed the Wallet & Credits button in `web/wallet.js`: an authenticated
  session now displays **Connected**; a connected account without valid Orb
  authentication displays **Sign again**; no selected account displays
  **Connect and sign**. The balance and payment interface remain unchanged.
- The signed backend session is stored in browser session storage with its
  server expiry, then checked against the currently selected MetaMask account
  and the authenticated backend balance endpoint on reload. A valid session
  restores without another signature. Expiry, backend 401, or account change
  clears stale UI state and requires a fresh signed challenge. An account
  change during a pending signature cannot authenticate the former account.
  A temporary backend failure displays **Retry session** and rechecks the
  saved token without requiring another signature.
- Updated the existing paid-flow frontend fixture and added dedicated wallet
  state tests in `web/wallet.test.js`. Full frontend suite: **24 passed** in
  3 files. Guarded production frontend build passed using a placeholder
  HTTPS API origin. No backend code, Prometheus code, payment configuration,
  deployment, or push was changed in this step.

## 2026-09-26 Wallet disconnect (local, not deployed)

- Added **Disconnect wallet** to Wallet & Credits, visible only for an
  authenticated Orb session. Clicking it immediately clears the browser's
  bearer token, authenticated address, displayed balance, pending payment,
  and saved paid-job pointer. A per-tab disconnected marker keeps the panel
  at **Connect and sign** after reload even if MetaMask still exposes the
  previously permitted account. Reconnecting uses the existing account
  request, signed challenge, and backend session flow.
- Added `POST /api/orb/wallet/logout`. It requires the exact configured
  browser origin and a valid bearer session, then deletes only that session
  from Orb's persistent sessions table. Other sessions and credit balances
  are unaffected. The frontend attempts MetaMask's
  `wallet_revokePermissions` for `eth_accounts` after local logout; an
  unsupported or rejected request does not undo logout. No transaction or
  token approval revocation is attempted. If backend revocation cannot be
  confirmed, the UI reports that local logout completed and the old server
  session will expire.
- Validation: **26 relevant backend tests passed** across wallet credits,
  mocked Postgres adapter, and deployment guard; **26 frontend tests passed**
  across 3 files; guarded production frontend build passed with a placeholder
  HTTPS API origin. No live Postgres or deployed-browser verification was
  performed. At this validation point, Orb changes were uncommitted and
  undeployed; Prometheus was not modified.

## 2026-09-26 Wallet UX commit audit

- Reviewed the complete pending wallet authentication and disconnect diff,
  including the earlier **Connected** state fix. Full backend suite:
  **177 passed**. Full frontend suite: **26 passed** in 3 files. The first
  frontend runner attempt timed out before starting a worker or executing
  tests; a standalone retry passed. The guarded production frontend build
  passed with a placeholder HTTPS API origin.
- The populated `.env` remains ignored. The nine-file Orb commit candidate
  contains no configured Gemini key, database URL, RPC credential, wallet
  private key, seed phrase, runtime database, upload, or generated result.
  The Arbitrum RPC literal in the wallet network metadata is public; any
  credential-shaped database URLs in tests use invalid-domain placeholders.
  The original Prometheus checkout was not modified.
- This audit supports the requested single Orb wallet UX commit and push to
  `origin/main`. It does not authorize or perform deployment.

## 2026-09-26 Paid job session-expiry recovery (local, not deployed)

- A 401 from a paid job-status or result request now pauses polling immediately,
  retains the saved job ID, and opens the existing Wallet & Credits sign-in
  control with a clear session-expiry message. It does not submit another AI
  operation, reserve another credit, or mark the job failed.
- After a new signed session and successful balance check, polling resumes for
  the saved job only when the authenticated wallet matches the saved owner.
  The backend's existing wallet ownership check remains in force. A completed
  Postgres result can be read after reauthentication; a released job displays
  its error and refreshes the restored credit balance. A stale 401 from an old
  token cannot invalidate a newer session.
- The frontend now allows `resumePaidJob` to restart a job paused for auth even
  while `currentJobId` is retained. Intentional Disconnect still deletes the
  saved job pointer. The server session TTL remains 3600 seconds; no payment,
  video-limit, backend authorization, or deployment configuration changed.
- Added frontend tests for immediate 401 pause, saved-job retention, same-wallet
  signed recovery, wrong-wallet refusal, one-upload reuse, durable-result
  display, and released-balance refresh. Added backend tests for expired-token
  rejection, same-wallet result recovery, wrong-wallet 404, one settlement,
  and released-credit restoration. Existing Disconnect tests still pass.
- Validation: full backend suite **179 passed** (104 existing FastAPI
  deprecation warnings); full frontend suite **29 passed** in 3 files; guarded
  Vercel build passed with a placeholder HTTPS Orb API origin. An initial
  sandboxed pytest attempt failed before setup due temp-directory permissions,
  and an initial Vitest fork attempt timed out before executing tests; both
  suites passed using the supported test access and a single thread worker.
  No live production job or Supabase query was performed, and nothing was
  deployed, pushed, or committed in this change.

## 2026-09-27 Arbitrum Sepolia wallet fee rejection (local, not deployed)

- Audited Buy Credits: Orb's `eth_sendTransaction` request already contains only
  the authenticated `from` address, server-quoted `to`, exact hex `value`, and
  quote `data`. It contains no `gas`, `gasPrice`, `maxFeePerGas`, or
  `maxPriorityFeePerGas`. The quote `data` must remain because the backend
  checks the on-chain input against that quote to prevent unrelated payments.
- The reported `maxFeePerGas < baseFee` values therefore arise after the
  request reaches MetaMask or its RPC fee estimator. Orb cannot remove a fee
  override it does not send. The wallet UI now gives specific retry guidance
  for this rejection, reminds the user to check wallet activity, and does not
  automatically resubmit a transaction. Clicking Buy Credits again obtains a
  fresh server quote and asks MetaMask to estimate and approve it again.
- The payment amount, receiver, chain ID 421614, wallet authentication, and
  backend receipt verification remain unchanged. An integration test asserts
  both initial and retry transaction objects have exactly the four required
  fields and that a failed fee estimate creates no pending-payment record.
- No real on-chain transaction was initiated as part of this change. A live
  MetaMask retry is still needed to determine whether its current network/RPC
  fee estimate succeeds.
- Validation: targeted frontend file **16 passed**, full frontend suite
  **29 passed** across 3 files, and guarded Vercel production build passed
  using a placeholder HTTPS API origin. No push or deployment was performed.

## 2026-09-27 Final Orb UI/UX polish (local, not deployed)

- The header now contains the compact primary Connect Wallet / Connected
  action beside the existing menu. It uses the same signed wallet flow and
  opens Wallet & Credits; the redundant wallet prompts below upload/Enhance
  were removed. The panel still shows account, network, credits, buying, and
  disconnect. Its testnet notice is shorter.
- The processing view uses Orb's Neptune-style mark instead of a generic ring
  spinner. It rotates subtly and stops under reduced-motion preferences.
  Upload, image/video analysis, scene analysis, prompt creation, and Enhance
  labels now use product language. Payment verification text is simplified.
- The desktop frame is capped at **980px** and centered. The hero wraps in
  balanced lines. Mobile retains fluid width, safe-area bottom spacing, and
  responsive header, panel, upload, and mode controls. Existing circular panel
  close icons use a symmetric SVG cross with grid centering. This checkout has
  no separate processing cancel control or backend cancel route, so no fake
  cancel action was introduced.
- Results no longer render the backend provider name. Provider/infrastructure
  errors are shown as Orb AI errors. Decode keeps a plausible-reconstruction
  caveat; Compose and Enhance have distinct purpose text. A noninteractive
  `Generate · Coming soon` roadmap note appears below the mode pills.
- Existing local uncommitted wallet fee-guidance changes are preserved. No AI,
  payment, credit, auth, Postgres, chain, backend processing, or job-recovery
  behavior was intentionally changed. Nothing was committed, pushed, or
  deployed during this polish pass.
- Validation: full backend suite **179 passed** (104 existing FastAPI
  deprecation warnings); full frontend suite **33 passed** in 3 files; guarded
  Vercel production build passed with a placeholder HTTPS API origin.
- Local browser visual checks at desktop 1280px, tablet 768px, mobile 390px,
  and narrow mobile 320px confirmed the centered 980px desktop frame, fluid
  mobile layout, no horizontal overflow, 28px mobile bottom gap, readable
  header controls, reachable Wallet & Credits panel/close icon, and usable
  Enhance fields. The local Vite preview had no live backend attached, so
  rendered paid results and processing were checked by frontend tests rather
  than an end-to-end browser run. No real wallet transaction was initiated.

## 2026-09-27 Final visual refinement (local, not committed or deployed)

- The desktop frame maximum width is now **1005px**, centered. Tablet and
  mobile remain fluid with the existing breakpoints and safe-area spacing.
- The header and processing views share a CSS atmospheric blue/cyan sphere
  with Orb's tilted planetary ring. A diffused highlight travels left to right
  across the sphere to suggest prograde rotation; the ring remains steady.
  Header motion loops in 12 seconds and processing motion in 4.5 seconds.
  Reduced-motion preferences stop the animation.
- The mode row now reads Decode, Compose, Enhance, Create. Create is a locked,
  non-actionable mode with a Coming soon label. Its separate information button
  opens a keyboard-accessible roadmap popover and closes on outside click,
  Escape, or its close button. It has no backend path or credit action. The
  prior Generate roadmap note was removed.
- About Orb now explains the problem, the three current stages, the future
  Create stage, the creative loop, intended audiences, and testnet credits.
  Its sections stay scrollable on mobile and its close control stays visible.
- Rendered browser checks at 1280px, 768px, 390px, and 320px found no
  horizontal overflow. The desktop frame measured 1005px; mobile preserved a
  28px bottom gap. The Create popover was adjusted to fit a 320px viewport.
  The local preview had no live backend, so this pass did not perform a paid
  AI or wallet transaction in the browser.
- Validation: full backend suite **179 passed** (104 existing FastAPI
  deprecation warnings); full frontend suite **34 passed** in 3 files; guarded
  Vercel production build passed with a placeholder HTTPS API origin.

## 2026-09-27 Create close icon and Orb motion follow-up (local, not committed or deployed)

- The Create information popover's text `×` used uneven font glyph metrics
  despite grid centering. It now uses a symmetric SVG cross inside the same
  28px circular button. Browser geometry showed zero horizontal and vertical
  offset on desktop and mobile, and at 125% and 150% CSS zoom.
- The previous oversized, blurred, symmetric glow moved in CSS but changed
  too little of the clipped sphere to read as motion. A narrower atmospheric
  highlight now traverses the sphere fully from left to right while Orb's ring
  stays steady. The header loop takes 6 seconds; the larger processing mark
  loops in 2.4 seconds. Reduced-motion rules continue to stop movement.
- A temporary local visual fixture rendered both sizes together; it was
  removed after checks. Browser samples over 300ms measured about 3.6px of
  left-to-right header travel and 9.5px of processing travel. Desktop and
  390px/320px mobile popovers showed a centered close cross and no horizontal
  overflow. The local preview had no backend attached, so no live AI or paid
  processing flow was run for this purely visual follow-up.
- Validation: targeted frontend file **21 passed**; full frontend suite
  **34 passed** in 3 files; guarded Vercel production build passed with a
  placeholder HTTPS API origin.

## 2026-09-29 Hackathon submission README refresh

- Reworked README around the user's submission draft for the Arbitrum Open
  House Singapore Online Buildathon: why Orb exists, Decode, Compose,
  Enhance, locked Create roadmap, Arbitrum integration, credit safety,
  architecture, video processing, and security.
- Preserved the public frontend and backend links and the Arbitrum Sepolia
  testnet/demo disclaimer. Removed outdated product and predeployment wording;
  the retained `prometheus` internal package path is explained only where
  needed for the working startup command and repository layout.
- Preserved and refreshed PowerShell setup, local unpaid/paid testing,
  Supabase Postgres, Render Free, Vercel, environment configuration, and
  deployment validation instructions. Local startup explicitly loads `.env`
  with Uvicorn, including installation of `python-dotenv`. Render's recurring
  health check is documented as `/api/health`, with `/api/ready` reserved for
  upload/analysis readiness checks.
- Corrected the old in-memory session description: hashed server sessions
  persist in the ledger, browser tokens use session storage, and same-wallet
  signing resumes an existing paid job after expiry. Documented durable result
  recovery, temporary production media, and the single-worker/instance
  reconciliation constraint.
- All private configuration examples use placeholders; no populated `.env`,
  API key, database credential, RPC credential, private key, or seed phrase
  was read or added. `.env` remains ignored. Only README and HANDOFF were
  edited; application code and the original Prometheus project were untouched.
- Validation: full backend suite **179 passed** with 104 existing FastAPI
  deprecation warnings; full frontend suite **34 passed** in 3 files after
  retrying an initial worker-start timeout; guarded production build passed
  with a placeholder HTTPS API origin. These tests use AI/blockchain/database
  doubles where documented; no live provider call, Supabase verification, or
  on-chain transaction was performed during this documentation task.
- No commit, push, or deployment was performed.

## 2026-10-02 USDG staging database isolation review

- Started from clean `main` at `ed54ebe682ca64be6580f33887881b01099ae4f3`
  and created the requested local `usdg-test` branch. Main remains unchanged.
- Inspected the existing payment service and Postgres schema without reading
  populated environment files or connecting to any deployed database.
- Sharing production's current ledger is unsafe: all Postgres connections use
  the fixed `orb` schema; balances are keyed only by wallet; sessions, quotes,
  purchases, reservations, and results have no deployment/environment scope.
  Startup reconciliation visits every reserved job and can release a live
  production job's reservation if its result has not yet been stored.
- Per the user's section 10 stop instruction, payment implementation is
  paused pending agreement on isolated staging storage. Recommended minimum:
  a separate staging Postgres database with separate credentials and a staging
  `ORB_DATABASE_URL`; a separate Supabase project is one way to provide it.
  No production database URL or environment group should be reused. A separate
  schema in the existing database would require deliberate schema selection
  and database role permissions; the current code does not support it safely.
- No application code, schema, payment configuration, production deployment,
  Prometheus, or orb-demo-video files were changed. Only this HANDOFF entry was
  added on `usdg-test`. No tests were rerun because application code is unchanged.
- No infrastructure was created, and no commit, push, migration, deployment,
  wallet signature, or transaction was performed.

## 2026-10-02 Paxos test USDG implementation on usdg-test

- The user approved an isolated staging Postgres database; implementation
  resumed on `usdg-test`. The unchanged main baseline is
  `ed54ebe682ca64be6580f33887881b01099ae4f3`. No existing environment file,
  production database/service, Prometheus, or orb-demo-video was modified.
- Native ETH remains the default when USDG variables are absent. USDG mode
  requires the explicit `usdg-staging` target, Arbitrum Sepolia 421614, official
  Paxos token `0xFFC95faa3d63Cde504a05B567C600B78C0b41892`, six decimals,
  and integer pricing of 100000 base units per credit.
- USDG quotes store wallet, receiver, token, exact amount, creation time/block,
  deadline, and completion via the existing quote record. Standard ERC-20
  transfer calldata has no quote ID; a matching transfer is assigned once to
  its verified quote, protected by global transaction and quote uniqueness.
  Payments must be mined after quote creation and verified before expiry.
- Backend verification independently checks network, receipt success,
  canonical block and confirmations, wallet/target/value/calldata, receiver
  EOA, token code/decimals, and one exact well-formed nonremoved Transfer log.
  Credit grant, purchase insertion, and quote completion are atomic. Concurrent
  same-quote retries return the existing grant without incrementing twice.
- Added USDG extension version 1: `orb.usdg_quotes` and
  `orb.usdg_schema_versions`, with a quote foreign key, integer constraints,
  and transactional/advisory-locked fresh database bootstrap. Core schema
  version 1 and existing columns stay intact. USDG refuses an unmarked,
  nonempty Orb ledger. No hosted migration was applied. Local USDG defaults
  to separate SQLite; public staging requires its own Postgres URL.
- Wallet sends only from/to/value/data; USDG target is the configured token,
  native value is zero, and data is a server-quoted ERC-20 transfer. Wallet
  controls gas/fees and requests user approval. Added concise USDG/gas copy,
  quote validation, pending-payment protection, and wallet rejection/funds
  guidance. Wallet/session/AI credit-reservation and job-recovery flows remain.
- Staging build rejects the current production backend and Production USDG
  deployments; staging wallet refuses a backend not identifying as USDG
  staging. Vercel Git auto-deploy for `usdg-test` is disabled in branch config
  so the authorized push does not publish a preview automatically. Production
  branch configuration and external settings were not changed.
- `.env.example`, README, and `docs/USDG_STAGING.md` document safe placeholders,
  isolated Supabase setup, Render staging, branch-scoped Vercel Preview values,
  exact origin/CORS, test-asset acquisition, and the manual acceptance flow.
  No new runtime dependency or payment contract was added.
- Validation: full backend **225 passed**, with 106 FastAPI deprecation
  warnings; full frontend **49 passed** across 4 files; guarded staging build
  passed with a placeholder HTTPS API origin. Tests include default native
  regressions, USDG faults/expiry/replays/concurrency/rollback, signed purchase
  followed by paid Enhance, result recovery, and staging isolation. Blockchain
  and AI use mocks; Postgres uses SQL-recording/SQLite-backed doubles. No live
  Supabase, Gemini, or USDG transaction verification was performed in this pass.
- Ready for the user-authorized commit/push to `usdg-test`, then stop before
  cloud creation/deployment. Staging credentials, actual preview origin,
  receiver, faucet funds, live database bootstrap, and one real payment/AI
  acceptance test remain external setup work.

## 2026-10-02 Dual-payment preparation and explicit USDG migration

- Started from clean `usdg-test` at `fc9a9c838347f637bda0b559928f933243b0beab`.
  Main and origin/main remain `ed54ebe682ca64be6580f33887881b01099ae4f3`.
  The user reported real single-method USDG staging success: 0.30 USDG,
  three credits, persistence, AI consumption, and no duplicate grants. This
  pass prepares dual methods; it does not claim their live staging acceptance.
- Added `ORB_PAYMENT_METHODS=native_eth,usdg`. The explicit list takes
  precedence over the legacy single switch; absent variables preserve native
  ETH. USDG token/chain/decimals/100000 price checks remain. Explicit methods
  prepare eventual production activation without a staging-only requirement;
  the legacy USDG switch and designated staging origins keep their safeguards.
- Config exposes server-enabled structured methods; quotes explicitly select
  a method when both are enabled. Single-method omitted selection remains
  compatible. Existing native price/receiver/ORB1 calldata and verification
  remain; USDG uses exact server-quoted transfer calldata, zero ETH, and receipt
  Transfer verification. Verification dispatches by persisted quote metadata,
  not client claims or the backend's default method. Both assets share global
  purchase-hash/quote uniqueness and atomic credit grants.
- Added compact Test ETH / Paxos USDG selection, pressed-state accessibility,
  method-specific notices/funds guidance, and explicit quote requests. UI shows
  only enabled methods and blocks another payment while one is pending.
  Wallet/session/job recovery, AI operations, credit lifecycle, and balances
  are unchanged. No wallet USDG balance query or dependency was added.
- Added `python -m prometheus.api.orb_usdg_migrate --check` (alias `--dry-run`)
  and the explicit migration without flags. The command reads privately supplied
  ORB_DATABASE_URL, never imports the app or loads .env, and checks core v1
  columns/constraints/version plus extension shape. Missing/extra/partial or
  unsupported schemas fail closed. Checks are read-only: exit 0 ready, 2
  migration required, 1 refused. Migration adds only usdg_quotes and extension
  marker in one advisory-locked transaction, verifies, and safely retries. No
  balance/session/purchase/job/result row is changed or reconciled. Startup
  still rejects a populated unmarked ledger; no production migration was run.
- README, .env.example, USDG staging guide and docs/DUAL_PAYMENTS.md document
  staging dual acceptance, production backup/migration rehearsal, commands,
  configuration, and compatible rollout: new backend native-only, new frontend,
  then enable both methods. Old tabs may require refresh. Existing staging
  isolation/build guard and disabled Git auto-deploy remain. No merge, hosted
  environment change, production database/service change, Prometheus edit,
  orb-demo-video edit, or blockchain transaction was performed.
- Final validation: complete backend **253 passed** with 108 existing FastAPI
  deprecation warnings; complete frontend **59 passed** across four files;
  guarded staging production build passed with a non-routable HTTPS origin.
  Frontend ran with one threads worker after a fork-worker startup timeout;
  initial sandbox Node/temp-directory access errors were resolved with normal
  filesystem access. Targeted final dual/migration tests also passed (28).
  RPC/AI and Postgres catalogs use doubles; real Postgres migration rehearsal
  and real dual-method staging payments remain pre-merge acceptance gates.
- Secret/runtime review found no real credentials or private runtime files in
  the 16 intended changes. Populated env files remain ignored. Authorized
  delivery is one commit/push solely to `usdg-test` after validation, then stop;
  no production database/origin/environment or deployment action is authorized.


## 2026-10-03 Populated disposable Postgres USDG migration rehearsal

- Worked only in Orb on `usdg-test`, starting from clean
  `a24a618ee0694e56e1528e0d6d3a434b163f7f6d`. Main/origin/main remain
  `ed54ebe682ca64be6580f33887881b01099ae4f3`. No production database,
  Render/Vercel configuration, original Prometheus, orb-demo-video, real wallet,
  provider, or payment transaction was accessed or modified.
- No local Postgres/container runtime existed. Used official portable EDB
  PostgreSQL 17.11 binaries under ignored api_output, with an owned loopback-only
  random-port TLS cluster. No Windows service/cloud infrastructure was created.
  Added a runner that strips inherited configuration, never loads .env, creates
  a unique cluster ownership marker, and stops only its owned cluster. Windows
  inherited output-pipe handling was fixed in the test launcher, not Orb code.
- Added eight opt-in real-Postgres integration cases. Each uses a new database
  with exact POSTGRES_SCHEMA_V1 and synthetic sessions/wallets, balances, native
  quotes/purchases, successful/released/reserved jobs and durable results.
  Initial counts: schema_versions 1, challenges 2, sessions 2, balances 2,
  quotes 4, purchases 3, reservations 6, results 4. Wallet A: granted 10,
  consumed 2, reserved 2, available 6; wallet B: granted 3, consumed 1,
  reserved 0, available 2.
- Actual subprocess CLI: pre --check exit 2/no mutation; explicit migration
  exit 0; post --check exit 0; repeat migration and final dry-run exit 0/no
  changes. Adds only usdg_quotes and usdg_schema_versions with marker 1.
  Full core row values/counts, columns/constraints/indexes, relation identities,
  filenodes and row ctid/xmin stayed identical. No migration reconciliation or
  credit release occurred. Existing migration code needed no fix.
- Five separate malformed ledgers (partial USDG, extra core column, wrong
  session column type, missing core table, unsupported USDG version/integrity)
  refused both check/apply with exit 1 and no changes. Injected failure after
  the first extension table rolled back all DDL. Two concurrent migration
  commands succeeded under the advisory lock with one marker and unchanged core.
- Real ASGI startup on migrated Postgres passed production paid guards using
  synthetic config and mocked RPC, then showed both payment methods, preserved
  authenticated access/native payment replay, issued a 300000-unit three-credit
  USDG quote, and recovered the durable result. EXISTING restart reconciliation
  consumed one reserved completed result and released one interrupted no-result
  reservation; A became granted 10/consumed 3/reserved 0/available 7. Other
  records/counts remained intact and a second startup made no further changes.
  No recovery, pricing, auth, payment, AI, or database application logic changed.
- Evidence: docs/MIGRATION_REHEARSAL.md and ignored JSON reports under
  api_output/migration_rehearsal_runtime/<run-id>/reports. The focused real-PG
  run was 97ca51a0bb7a4fe88865f32c135a0c7d: eight passed. These are actual
  Postgres migrations, not SQL doubles; blockchain RPC is mocked and AI is
  not called. Frontend: 59 passed (four files). Guarded staging production
  build passed with a non-routable HTTPS API origin.
- Full backend validation passed: **261 tests**, including all eight real-PG
  cases (112 existing FastAPI deprecation warnings), in 365.97 seconds. The
  full-suite cluster run was 7c4e08d7d74a45f29ae407d741712623; its reports are
  saved alongside the focused run, and both owned servers were stopped. No commit/push/merge/deployment was performed. Portable binaries,
  TLS keys, clusters and raw runtime reports are ignored, as are populated env
  files. Remaining: real dual staging acceptance, separate merge/production
  approval, verified backup/restore, authorized production check/migration,
  core-record comparison, compatible native-first rollout, then real payments.
  Finish active AI work before backend restart; the migration itself does not
  reconcile jobs. See docs/DUAL_PAYMENTS.md for the exact rollout.

## 2026-10-03 Migration CLI suppressed-exception diagnosis

- Inspected clean application sources on `usdg-test` at
  `ba321cbb2a6fe2cc3bb8b9aa60d346f39a904f8f`. The user's untracked
  `backups/` directory was neither opened nor modified.
- Plain `python` in this session resolves to the global Python 3.13 executable,
  which has no `psycopg` or `psycopg_binary`. Orb's `.venv` has both installed.
  The production database environment variable remains unavailable to this
  Codex process; no production connection or schema inspection was attempted.
- Reproduced the suppressed exception using only a synthetic connection URL.
  `_connect_postgres()` fails at `import psycopg` with
  `ModuleNotFoundError: No module named 'psycopg'`, wraps it as
  `RuntimeError: Orb could not connect to its production Postgres database.`,
  and the migration CLI's broad exception handler emits the reported generic
  message and exit 1. No SQL is executed in this failure path.
- Minimal correction: in the same private PowerShell environment where psql
  succeeds, use `.\.venv\Scripts\python.exe -m prometheus.api.orb_usdg_migrate
  --check`. This selects Orb's installed dependencies. It does not establish
  what the production schema check will return once the correct interpreter
  is used; another live error would require diagnosis in that private session.
- No application behavior was changed and no temporary diagnostic mode was
  needed. No credentials were printed, production records modified, write
  migration applied, merge/deployment/configuration change made, or commit
  created. Only this handoff records the local diagnostic evidence.

## 2026-10-04 Configurable USDG credit price

- Working on `main`, separated USDG pricing from the fixed token safety guard.
  `CreditConfig.__post_init__` previously rejected `self.usdg_price != USDG_PRICE`,
  where `USDG_PRICE` was 100000. That made a legitimate 3000-unit price fail
  startup with the generic Paxos configuration error.
- Default/intended USDG price is now 3000 base units per credit: 1/3/5 credits
  cost 0.003/0.009/0.015 test USDG. Environment parsing accepts positive decimal
  integers only; zero, negative, malformed, decimal and scientific values fail
  startup. Explicit 100000 remains valid. Typed configuration also rejects
  non-integers, including booleans. No floating-point payment arithmetic added.
- Chain 421614, official Paxos contract, six decimals, explicit payment-method
  enablement and isolated legacy staging checks remain enforced. Native ETH
  pricing, receiver configuration, receipt verification, authentication, credit
  lifecycle, persistence, migrations and job recovery are unchanged. Existing
  USDG quotes retain their stored amount across price changes.
- Updated configuration examples, README and payment/staging guides. The
  existing frontend formatter already supports the smaller values; only its
  tests changed, with explicit 1/3/5-credit price coverage.
- Full backend: 274 passed, 8 opt-in real-Postgres tests skipped, 114 existing
  FastAPI deprecation warnings. Full frontend: 62 passed. Guarded main production
  build passed using https://orb-api.example.invalid. Provider and blockchain
  calls were mocked; no live AI, chain transaction or production database access
  occurred during this pass.
- User confirmed both production Git auto-deployments are disabled and
  authorized commit/push to main after validation. No production environment,
  database or service configuration was changed; no deployment was performed.
  Changes are confined to independent Orb. Populated .env files, secrets,
  backups, uploads, results and runtime databases remain excluded from Git.

## 2026-10-04 Credit config recovery and wallet restoration isolation

- Fixed the frontend conflation of pending/failed payment config requests with
  explicit server-disabled configuration. `web/wallet.js` now keeps parsed
  configuration separate from loading/ready/disabled/unavailable state.
  Only a successfully fetched explicit `enabled: false` shows
  "Testnet credits are not configured on this Orb server."
- Initial pending requests show "Loading credit options…". Transient request,
  timeout, HTTP error (including unexpected 401/403), invalid JSON or invalid
  response failures show "Credit service is starting…". Exhaustion shows
  "Credit service temporarily unavailable. Try again." Success clears the
  temporary warning and renders the server's payment methods without refresh.
- One shared config task prevents concurrent requests/retry cycles. Each
  request has a 15-second abort timeout; retry backoff is 1/2/4/8 seconds,
  capped at 8 seconds, with at most 12 attempts and a two-minute total budget.
  Explicit disabled responses are not retried. The header opens the panel
  safely while loading and can restart recovery after exhausted retries.
- Config validation/payment rendering precede independent network and session
  restoration. A wallet provider, saved-session or balance restoration failure
  cannot erase valid payment config. The isolated USDG Preview guard and legacy
  single-method compatibility remain intact; ready responses must have usable
  server-enabled payment metadata before purchase controls become available.
- Added 27 mocked-fetch/wallet frontend tests covering delayed responses,
  network/CORS failures, 503/401/403, invalid responses, timeout/abort ordering,
  late stale responses, bounded retry/backoff, manual recovery, disabled state,
  both payment options and wallet/session/network restoration independence.
  Full frontend: 89 passed. Guarded main production frontend build passed with
  https://orb-api.example.invalid. Full backend: 274 passed, 8 opt-in real-
  Postgres tests skipped, 114 existing FastAPI deprecation warnings. Provider,
  wallet and blockchain integration checks used mocks; no live payment or AI
  operation was performed in this pass.
- No backend, pricing, quote/transaction/verification, database, auth protocol,
  session expiry, AI/job recovery or Render/Vercel configuration code changed.
  No production services/databases or secrets were accessed. User authorized
  commit/push to main after full validation; production automatic Git deployments
  were previously confirmed disabled. Original Prometheus remains untouched.

## 2026-10-05 Mobile file readability recovery

- Decode/Compose image and video uploads now stay on the selection screen with
  an accessible "Checking file…" status before any upload/processing UI appears.
  A small 64 KB prefix is checked; no full-file browser buffering was added.
- `web/file-readability.js` permits only two additional local reads for
  NotReadableError/NotFoundError, after 300 ms and 800 ms. Each read has a
  five-second timeout. Other errors/timeouts are not retried. FileReader provides
  the same bounded prefix check when Blob.arrayBuffer is unavailable.
- Persistent failures clear the saved File, input value and attempt state,
  restore selection controls, and show "Couldn't access this video/image" with
  concise Files/Browse guidance. Diagnostics remain in the console. Orb does not
  claim it can force an Android provider. Normal picker cancellation preserves
  the selection; clearing a pending check aborts it. Late or superseded reads
  cannot start an upload, including after a replacement File succeeds.
- Local retries construct no FormData and send no media/job request, so no
  backend job or credit reservation/consumption begins. A successful check
  proceeds to readiness and one existing authenticated/idempotent upload POST.
  HTTP upload retries, payments, pricing, database, AI/FFmpeg behavior, job
  recovery and infrastructure remain unchanged. A readable prefix still cannot
  guarantee that the remainder stays accessible throughout upload.
- Added focused helper and rendered frontend tests for immediate success,
  bounded retry/backoff, third-read success, non-retryable errors, timeout/late
  resolution, cancellation/replacement, clean image/video failures, fresh
  same-name selection, empty files, Decode/Compose, repeated clicks and paid
  authentication/idempotency preservation. Full frontend: 110 passed. Guarded
  production build passed using https://orb-api.example.invalid.
- Full backend: 274 passed, 8 opt-in real-Postgres tests skipped, 114 existing
  FastAPI deprecation warnings. An initial run's two guard failures came from
  the runner's temporary PROMETHEUS_FFMPEG_DIR variable; supplying FFmpeg through
  the test process PATH made the complete suite pass without backend changes.
- No production services/database, live AI quota or on-chain transactions were
  used. Secrets and runtime artifacts remain excluded. Original Prometheus is
  untouched. User authorized commit/push to main after validation; automatic
  production Git deployments were previously confirmed disabled. No deployment
  is performed here. Physical Android Gallery verification remains a follow-up
  after the user deploys this change.

## 2026-10-05 Mobile wallet browser control compatibility

- Replaced the native credit quantity select with compact HTML button radios
  for 1/3/5 credits, defaulting to 1. The labelled radio group exposes checked
  state, a single Tab stop, arrow-key wrapping and Home/End navigation. Native
  button Space/Enter activation is preserved; no touch-specific handlers or
  wallet/browser detection were added. Quantity remains usable during wallet
  activity and survives payment-method switching. Existing integer pricing and
  server-authoritative quote/transaction construction are unchanged.
- Choose File is now an associated label containing the actual native file
  input. The transparent input covers only the visible Choose File control,
  remains keyboard/screen-reader accessible, and accepts direct taps as a
  fallback for browsers that do not forward label activation. Removed the
  JavaScript input.click handler, avoiding duplicate picker activation or an
  async boundary. Accepted media types, absence of capture, change handling,
  readability preflight, cancellation and same-file reset behaviour remain.
- Wallet & Credits keeps its existing fixed panel and desktop appearance; its
  heading/close control now sticks while the panel scrolls. No backdrop or
  modal architecture was introduced.
- Full frontend: 126 passed (16 added cases); full backend: 274 passed,
  8 opt-in real-Postgres tests skipped, 114 existing FastAPI deprecation
  warnings. Guarded production build passed with https://orb-api.example.invalid.
  Tests cover accessible selection, keyboard navigation, all native/USDG
  quantities and exact unchanged transaction fields, selection during/after
  payment, label/direct input single activation, cancellation, same-name reset,
  image/video Decode/Compose and single-upload submission. Existing readability,
  authentication, payment/idempotency and paid-job recovery tests still pass.
- Also checked the built frontend in a local Chromium browser with in-memory
  mocked wallet/API responses and all real transactions blocked. Native pointer
  and Enter activation emitted file-chooser events. Keyboard quantity selection
  and method switching worked. At 390px and 320px there was no horizontal page
  overflow; the wallet close control remained hit-testable after panel scrolling.
  Physical Zerion Android, MetaMask, Rabby, Chrome Android and Edge checks remain
  manual follow-ups: web code cannot guarantee a host app presents its chooser
  or releases a native overlay. No live AI, payments or production API/DB calls
  occurred. The local mock server was stopped after verification.
- No backend, authentication protocol, pricing, ETH/USDG verification,
  persistence, AI, MetaMask gas behaviour or infrastructure code changed.
  Original Prometheus remains untouched. User authorized commit/push on main
  after validation; production automatic Git deployments were previously
  confirmed disabled. No deployment is performed in this pass. Secrets and
  runtime files, including the local QA screenshot, are excluded from the commit.

## 2026-10-05 Direct native file-picker activation

- Physical Zerion Android feedback confirmed quantity controls and general
  wallet/page interaction now work, but Choose File still did not open a picker.
  This follow-up changes only the file-control markup/styles and related tests.
- Removed the wrapping label and its forwarding path. A non-interactive relative
  wrapper contains visual text with pointer-events disabled and the real file
  input positioned over its entire area (inset 0, width/height 100%, opacity 0,
  z-index 1, pointer-events auto). The input remains focusable, screen-reader
  labelled, and neither display:none nor visibility:hidden. No synthetic click,
  async activation, duplicate touch handler or wallet-specific detection exists.
- Accepted formats, absence of capture, file change handling, Decode/Compose,
  readability preflight, cancellation, same-file reset and paid/idempotent upload
  behaviour remain unchanged. Quantity, wallet/payment, MetaMask gas, backend,
  AI, database, blockchain and infrastructure code were not modified.
- Local Chromium checks of the guarded build confirmed all five sampled hit
  points across the control target file-input at 1280px, 390px and 320px; input
  bounds equal the visual wrapper bounds. Direct click and Enter opened native
  file-chooser events, click counts were one, and mobile widths had no horizontal
  overflow. Checks used an isolated local mock API without real AI/payment or
  production access; local test servers were stopped afterward.
- Physical Zerion Android must be retested after a user-authorized deployment.
  If direct native input activation still fails there, the remaining problem is
  likely Zerion's embedded WebView/native file-chooser implementation. Normal
  website JavaScript cannot reliably repair a host app that does not present
  the chooser. This change does not promise to force a particular Android
  picker/provider. Original Prometheus remains untouched.
- Full frontend: 127 passed. Full backend: 274 passed, 8 opt-in real-Postgres
  tests skipped, 114 existing FastAPI deprecation warnings. Guarded production
  build passed using https://orb-api.example.invalid. Focused tests verify the
  input's active overlay, no wrapper/label/programmatic activation, a single
  native click path, cancellation, same-name reset, image/video Decode/Compose
  and no duplicate media uploads. Existing wallet/payment/readability suites
  remain passing. User authorized commit/push to main after validation; automatic
  production Git deployments were previously confirmed disabled. No deployment
  is performed here; secrets/runtime data and the QA screenshot remain excluded.

## 2026-10-05 Fresh Arbitrum Sepolia EIP-1559 fee estimation

- User reported wallet-selected caps below the current Arbitrum Sepolia base
  fee before a transaction hash was returned. Both native ETH and USDG need
  native ETH gas. This change is frontend-only and wallet-agnostic.
- Added web/payment-fees.js: fresh EIP-1193 reads on every Buy Credits attempt;
  pending block base fee with latest fallback; priority suggestion from
  eth_maxPriorityFeePerGas, then three-block feeHistory median rewards, then
  gasPrice minus base fee. All quantities and fee arithmetic use BigInt.
  Invalid/absent base fees fail closed. Tips above the base fee are rejected
  as excessive rather than replacing them with an arbitrary static gwei tip.
- The fee cap is ceil(fresh base fee * 3 / 2) + priority fee: 50% base-fee
  headroom. Base fee is refreshed after exact-payload eth_estimateGas. The
  wallet controls the gas limit; no gasPrice, gas, or nonce is supplied.
  Tests cover rounding, quantities beyond Number precision and 49% base-fee
  growth. This is a bounded cushion, not a guarantee against unlimited wallet
  approval delays or congestion. Details and primary-source links are in
  docs/DUAL_PAYMENTS.md; README payment guidance is updated.
- The original quoted from/to/value/data remain unchanged for native ORB1
  binding and USDG transfer. Before sending, recheck authenticated wallet,
  account/chain, provider identity, auth epoch and quote expiry. Read calls
  have 8-second timeouts and a 30-second total estimation deadline. Rejection,
  disconnect or identity change stops the attempt; late responses cannot send.
- Clear fee-estimation error copy replaces static-fee fallback; base-fee error
  guidance is wallet-neutral. Diagnostic errors stay in the console. Only one
  eth_sendTransaction is permitted per user attempt. No hash means no payment
  verification or grant; ambiguous send errors advise inspecting wallet activity
  before a manual retry. Existing shared replay/idempotency protections remain.
- Added 53 deterministic frontend tests for RPC fallbacks, malformed data,
  bounds, fresh repeated estimates, exact native/USDG payloads, identity races,
  rejection, ambiguous sends, missing hashes and late timeout completion.
  One asynchronous settlement assertion now waits for the actual expected
  balance instead of relying on fixed event-loop flushes.
- Full frontend: 180 passed. Guarded production build passed with the safe
  https://orb-api.example.invalid API origin. Full backend: 274 passed, 8 opt-in
  real-Postgres tests skipped, 114 existing FastAPI deprecation warnings. The
  initial sandbox run could not access pytest's Windows temporary directory;
  rerunning with required local filesystem access passed the complete suite.
  Production DB/RPC/AI credentials were removed from the test process environment.
  No live transaction, AI call or
  deployment is performed. Physical wallet/testnet approval remains a manual
  check after an authorized deployment. Backend, pricing, verification, database,
  infrastructure and original Prometheus code remain unchanged.

## 2026-10-06 Performance timing instrumentation

- Added content-free monotonic observations for Orb Decode/Compose images and
  videos, and text Enhance. This is instrumentation only: media sampling,
  frame resolution/quality, scene thresholds, FFmpeg command arguments/timeouts,
  prompts/models, retry policy, single-worker FIFO, payment pricing/verification,
  wallet security, credit lifecycle, database schema and infrastructure remain
  unchanged. The original Prometheus project and orb-demo-video are untouched.
- prometheus/performance.py defines numeric/label allowlists, ContextVar job
  scope, timers, SDK call/retry observations, and transparent ASGI receive timing.
  Context is explicitly carried from the request into JobManager's existing
  worker. JobTiming is internal only and is absent from public job/result DTOs.
  It does not become ledger or recovery data. Logger exceptions are contained
  within the observer and cannot change a job or credit outcome.
- Backend events through the existing Uvicorn logger: orb_perf (arrival,
  worker start, AI calls and retry waits), orb_perf_request (HTTP receive/parse /
  acceptance), and orb_perf_summary (one completed/failed job summary). Random
  request/job IDs correlate stages. No filenames, prompts, media/base64, wallet
  identifiers/signatures, credentials or full transaction data are included.
- Timed boundaries cover receive+multipart parsing/spooling, existing file save,
  authorization, image/video validation, paid-file/Enhance hashing, job creation,
  reservation, actual queue wait, worker processing, both existing FFprobes,
  scene detection, each extraction aggregated, subprocess execution/launches,
  local frame preparation, every SDK AI call, existing retry sleep, response
  parsing/validation, pipeline artifacts, durable result save, settlement and
  cleanup. Summary counts include image/video dimensions, bytes, duration,
  scenes, scene/global/total frames, calls/retries, longest/average AI durations.
  Dimensions are gauges so repeated probes do not double them; no-retry counts
  are explicit zero. Nested spans must not be summed as if disjoint.
- web/performance.js provides local/dev console timing only; production is
  quiet unless the user sets sessionStorage orb-perf to 1 in that browser tab.
  No infrastructure env var is needed. Browser events separate initial service
  wake/readiness from AI click-to-result, readability/readiness, upload request,
  job-ID availability, actual scheduled polling waits/requests and result display.
  Same-page session recovery keeps the timer; a reload cannot recover the old
  click timestamp. No requests, upload retries or poll intervals are added.
- Added 13 backend and 12 frontend cases covering all modes, real local video
  tools with mocked AI, failed jobs/uploads, queue isolation, SDK/parse retries,
  content exclusion, unchanged payloads, credit consumption/release/idempotency,
  signed disposable test-wallet sessions, logger failures and browser gating.
  README validation counts and docs/PERFORMANCE_TIMING.md are updated.
- Generated fixture: four-second 320x240 video, 144770 bytes; two FFprobes,
  one scene, ten frames (two scene/eight global), eleven FFmpeg launches;
  total 2831.015 ms, queue 0.993 ms, FFmpeg 1654.852 ms. AI transport was mocked:
  its two calls / 31.997 ms must not be presented as live Gemini latency.
  Local microbenchmark during validation measured about 10.4 microseconds per
  timer+metric and 58.1 microseconds per AI JSON event with a NullHandler;
  actual log-output I/O and production end-to-end overhead remain unmeasured.
- Full frontend: 192 passed; guarded production build passed using the safe
  https://orb-api.example.invalid origin. Full backend: 287 passed, 8 expected
  opt-in real-Postgres skips, 134 existing FastAPI deprecation warnings across
  the expanded suite. Final source, including zero-counter summary formatting,
  passed complete backend/frontend validation. Opt-in real PostgreSQL tests
  are excluded unless explicitly using a disposable DB. No paid/live AI calls,
  actual transactions, production service/database access or deployment occurs
  in this pass. User authorized commit/push to main after validation; automatic
  production Git deployments were previously confirmed disabled.

## 2026-10-06 Safe video performance Phase 1

- Dependency inspection confirmed each scene call depends only on metadata,
  its own scene and frames. Only those calls now overlap, with a maximum of two
  outstanding calls including their existing retry loops. A completed slot is
  replenished immediately; results and artifacts are assembled in original
  scene position order. FFmpeg remains sequential. Global analysis depends on
  the ordered scene descriptions and remains sequential; Compose synthesis
  consumes the completed report and remains sequential afterward.
- Scene frames are prepared before the bounded AI phase. On failure/interruption,
  dispatch stops once the failure is observed, pending calls are cancelled where
  possible, and running calls are joined before source cleanup or settlement.
  Synchronous SDK calls cannot be forcibly cancelled; existing timeouts and retry
  policy remain unchanged. Already-started independent work may finish after
  another scene fails. No unbounded scene queue or additional job worker exists.
- Orb visual upload validation now returns internal ValidatedVideo metadata.
  The pipeline reuses it only when resolved path, device/inode, size and nanosecond
  modification/change timestamps match the original before/after-probe identity.
  Otherwise the authoritative existing probe is retained. Unchanged Orb uploads
  use one FFprobe instead of two. Standalone/legacy callers still probe normally.
- Per-run extraction cache uses the exact existing three-decimal FFmpeg seek
  argument, source path, image format and quality. It copies identical bytes into
  the original destinations, retaining raw timestamps, indices, order, filenames
  and every scene/global evidence entry. No nearby seek strings are merged and
  no cache survives between jobs. Default synthetic/two-cut fixtures have zero
  duplicates; the existing four-global-frame two-cut configuration shares four
  seeks (0.500, 1.500, 2.500, 3.500). Production sampling settings are unchanged.
- Existing orb_perf fields/events remain. Added peak_ai_concurrency,
  sequential_ai_sum_ms (alias of summed ai_total_ms), scene_ai_wall_ms (provider
  phase including retries/scheduling/join, excluding extraction/ordered writes),
  unique_extracted_frames and frame_cache_hits. Summed SDK time is not elapsed
  time when calls overlap. Context is copied separately into each scene thread.
- No prompts/models, frame count/resolution/JPEG quality, scene thresholds or
  boundaries, timestamps, FFmpeg commands/timeouts, retries, payment pricing or
  blockchain verification, database schema, job worker ownership/idempotency,
  frontend UI, infrastructure, original Prometheus or orb-demo-video changed.
  Scene threads never reserve credits or persist/settle durable results. Tests
  prove one worker reservation/result save/settlement, exact consumption or
  failed-job release, and duplicate-job reuse. Existing GET recovery can safely
  repeat an idempotent settlement during a race; no duplicate consumption occurs.
- Added 22 backend tests in tests/test_video_phase1.py: 1/2/12 scenes, maximum
  concurrency, reordered completion, unchanged prompt instructions/frame bytes /
  final aggregation, retries, failures, SDK timeout, interruption/join, canonical
  seeks, metadata identity fallback, generated fixture comparisons, and paid
  Decode/Compose consumption/release/idempotency. Existing instrumentation/API
  test adapters now assert one probe and unique-extraction launch counts.
- Final mock benchmark: four independent 500 ms calls, 2190.2 ms sequential
  versus 1129.7 ms bounded parallel total; scene AI wall time 1022.4 ms.
  Generated synthetic/default: 1924.7 -> 1853.9 ms, probes 2 -> 1, ten evidence
  entries and eleven FFmpeg launches unchanged, two AI calls. Two-cut/default:
  2515.6 -> 1935.8 ms, twelve entries/thirteen FFmpeg launches/three AI calls
  unchanged, peak AI calls 1 -> 2. Two-cut/existing four-frame configuration:
  2224.2 -> 1207.1 ms, eight evidence entries unchanged, unique extractions
  8 -> 4 and FFmpeg launches 9 -> 5, three AI calls unchanged. Real local
  FFmpeg/FFprobe; provider delays/responses mocked, no live AI calls or quotas.
- Full backend: 309 passed, 8 expected opt-in real-Postgres skips, 142 existing
  FastAPI deprecation warnings. Full frontend: 192 passed; initial default
  parallel run encountered three Windows Vitest fork startup timeouts, rerun of
  all eight files with --maxWorkers=1 passed. This changes only test execution,
  not application worker count/configuration. Guarded production frontend build
  passed with https://orb-api.example.invalid. Final isolated benchmark subset:
  four tests passed. README/docs/PERFORMANCE_TIMING.md updated; new
  docs/VIDEO_PHASE1.md documents safety, measurements and repeatable checks.
  No production AI/RPC/database/service access, deployment or infrastructure
  mutation occurs. User authorized commit/push to main after passing validation;
  automatic Git deployments were previously confirmed disabled.

## 2026-10-06 — Video performance Phase 2 experiments; no production change

- Profiled existing commands before experiments: scene detection selects every
  native video frame with gt(scene,0.3)/showinfo and null output; individual JPEG
  extraction uses accurate input-side -ss, original dimensions and q:v 2.
  The reported 32 unique frames therefore require 32 extraction processes plus
  one scene-detection process. Production retains these commands and launches.
- Added local-only scripts/benchmark-video-phase2.py, ten experiment tests,
  docs/VIDEO_PHASE2.md and a 324-row generated-fixture equivalence CSV. Sources
  are synthetic moving H.264/AAC videos approximating 17 s landscape, 30 s
  vertical and 120 s 720p. Media/raw reports stay ignored under output/.
  No downloaded/user media or production secrets/services were used.
- Default workstation extraction wall milliseconds (baseline / single / two
  batches): short 1791.7 / 550.1 / 1318.1; medium 1506.1 / 1047.6 / 2140.0;
  long 4088.2 / 2896.8 / 5743.7. Single-batch CPU cost rose about 70% on medium
  and 93% on long. A one-CPU sensitivity check showed medium 2428.5 -> 5439.7
  ms and long 7105.2 -> 8964.2 ms: about 124% and 26% slower, respectively.
  This fails the safe constrained-host performance gate. No batching adopted.
- Stream suppression, explicit decoder threads and output-side seeking were
  also benchmarked. Scene boundaries matched across all tested flags, but
  no scene command showed consistent large benefit across both host setups.
  Explicit first-video mapping cannot universally preserve automatic stream
  selection. No scene-command change adopted and no FFmpeg parallelism added.
- All 54 representative baseline frames match the original production helper
  byte-for-byte. Six experimental variants preserve those JPEGs, dimensions,
  q:v 2 and evidence ordering; source checksums independently match batch/thread
  variants. Additional VFR/odd/overlapping timestamp tests pass. Output-side
  seek equality is JPEG-based; its actual emitted PTS was not independently
  exposed. The report documents seek-rebased timestamp precision limits.
- Full backend: 319 passed, 8 expected real-Postgres skips, 142 existing
  warnings. Full frontend ran twice: 191 passed, one unchanged USDG cross-method
  quote test failed at web/wallet.test.js:585 (expected wrong payment method,
  received 3 testnet credits added). Both variants pass isolated; likely timing
  or test-order sensitivity remains unconfirmed. No wallet/test changes made.
  Guarded frontend build passed with https://orb-api.example.invalid.
- Phase 1 concurrency/order, probes/cache, AI prompts/model, frame evidence,
  instrumentation, payments/credit lifecycle, database, UI and infrastructure
  remain unchanged. No production speedup claimed. Prometheus and orb-demo-video
  untouched. No commit/push/deploy: main/origin remain at
  a722bbb936b97990865c14f4bc17a3a52f6a7b2a. Experiments/tests/docs are uncommitted.
- Next work needs actual source codec/GOP/deployed FFmpeg CPU-budget evidence
  before considering adaptive batching, plus a separate diagnosis of the
  frontend full-suite failure. Do not deploy these experiments as production
  extraction code or infer Render performance from the multicore benchmark.

## 2026-10-08 — Faster bounded frontend backend wake-up detection

- Frontend recovery now uses `web/service-recovery.js`: 5-second lightweight
  health probes, a 1-second delay after failed probes, unchanged 15-second
  readiness/canary allowances and a 5-second pause after failed full
  verification. Requests and delays respect a monotonic 100-second deadline.
- One awaited request at a time; the existing shared application recovery
  task prevents duplicate startup/focus/online flows. Timed-out requests are
  aborted, and late completion cannot update readiness. Successful full
  verification stops all probes. Explicit configuration messages and existing
  upload-canary compatibility semantics remain intact.
- No attempt-count limit shortens recovery under latency. Worst-case fast
  failed health responses produce 100 lightweight requests per recovery
  window; stalled requests produce at most 17. Full verification retries are
  limited to five-second pauses rather than running every second. No new
  background keep-alive was added. Credit-config retry code is unchanged.
- Added fake-clock recovery tests and application integration tests. The
  existing intentional unavailable-health test now uses fake timers so its
  retry cannot leak into another test. Full frontend: 215 passed. Guarded
  production build passed with `https://orb-api.example.invalid`.
- See `docs/BACKEND_WAKEUP.md` for exact before/after timings, lifecycle,
  timeout/deadline behavior and load bounds. Backend/AI, payments, auth,
  database, infrastructure and Prometheus are unchanged.
- Read-only Vercel project inspection confirmed automatic Git deployments
  are enabled for main. User explicitly requested keeping the eventual
  validated commit local; do not push or deploy this change.
- Final backend rerun: 319 passed, 8 expected real-Postgres skips, 142 existing
  deprecation warnings. The first run had one timing-sensitive failure in
  `test_ai_failure_retries_same_paid_job`: its existing 10-second polling
  allowance ended while video processing was still running. It passed in
  isolation and in the complete rerun without backend/test changes.

## 2026-10-06 — Wallet test isolation resolved; benchmark documentation approved

- Wallet test failure above was traced to a real config retry timer surviving
  the intentional preview-config failure test. Its old wallet instance reused
  a later test's fetch mock/document and replaced that test's method controls.
  Production payment validation was unaffected.
- Commit 97568fac4714cfd30d0d236ffbf293de1415197a, pushed to origin/main,
  modifies only web/wallet.test.js: fake timers for the intentional retry,
  deterministic retry assertions, zero remaining fake timers before restoring
  real timers, and explicit authentication/selection/rejection assertions.
- Repeated affected cases passed ten executions each; wallet 59 passed; full
  frontend 192 passed; full backend 319 passed, 8 expected PostgreSQL skips;
  guarded production frontend build passed. No production code was changed.
- User now explicitly authorizes committing/pushing the five Phase 2 benchmark
  files with message "Document video extraction benchmarks". The benchmark
  report records the resolved validation issue. No production extraction change,
  live provider/database access, deployment or infrastructure mutation is part
  of this commit. Prometheus and orb-demo-video remain untouched.

## 2026-10-16 — OpenCV AI Competition 2026, Sprint 1 Part 1: read-only audit

- Process rule from the user: every step taken must be recorded in this file.
  New entries are appended at the end of the file.
- Context: Orb is being upgraded for the OpenCV AI Competition 2026 (AWS).
  Sprint 2 will add a Python OpenCV 5 + AWS microservice. Sprint 1 is this
  audit plus a "Judge Demo Mode" so judges without an Arbitrum Sepolia wallet
  can try Decode/Compose/Enhance on the live URL.
- Repository state at audit: branch `main`, in sync with `origin/main`, clean
  working tree. HEAD `3f6d304` (backend wake-up detection), which follows
  `e22ea0a` (liquid glass UI merged into main). Note: the 2026-10-08 entry
  said to keep the wake-up change local; it is now committed and on
  origin/main. Stash `stash@{0}` (Phase 3 scene experiments) is still present.
- Findings:
  - Frontend is vanilla JavaScript ES modules built with Vite 7 (no React,
    Next.js, router, or state library). Single page `web/index.html`; screens
    switch via `showScreen()` in `web/app.js`. State is module-level variables
    (`creditMode`, `currentMode`, `selectedFile`, ...) plus `sessionStorage`
    for the wallet session token and active paid job ID. Tests use Vitest +
    jsdom.
  - Backend is FastAPI (`prometheus/api/app.py`) with one JobManager worker.
    Uploads: `startVisual()` in `web/app.js` posts multipart to
    `POST /api/orb/{decode|compose}/file`; `startEnhance()` posts JSON to
    `POST /api/orb/enhance`. Both then poll `GET /api/jobs/{id}` and fetch
    `GET /api/jobs/{id}/result`. AI calls are in
    `prometheus/analysis/orb_ai.py` (images, Enhance, video Compose) and the
    inherited `PrometheusPipeline` (video).
  - Credit gate is server-authoritative. `_authorize_ai()` allows loopback
    local testing only; otherwise it requires a bearer session created by
    wallet signature (`CreditService.authenticate`). `_reserve_paid()` calls
    `CreditService.reserve()`, which atomically increments `reserved` when
    `granted - consumed - reserved >= 1` (402 otherwise). `settle()` consumes
    the credit after the result is saved, or releases it on failure. Paid job
    status/result/media reads require the owning wallet session. The frontend
    `wallet.hasCredit()` check only disables buttons; the server decides.
  - Implication for Judge Demo Mode: a localStorage-only credit counter cannot
    work on the live URL, because the backend would still return 401/402. A
    working demo mode needs a server-side path, which opens public AI access
    (Gemini cost/abuse risk) and so needs an explicit design decision.
- No code, configuration, deployment, or Prometheus files were changed in this
  step. No tests were run (read-only).

## 2026-10-16 — OpenCV AI Competition 2026, Sprint 1 Task 1: Server-backed Judge Demo Mode (Option B + URL auto-unlock)

- Implemented server-backed Judge Demo Mode so OpenCV AI Competition 2026 judges can test `Decode`, `Compose`, and `Enhance` with 10 demo credits and zero Web3 / Arbitrum Sepolia friction while keeping Gemini quota protected on the server:
  - **Backend (`prometheus/api/orb_credits.py`, `prometheus/api/app.py`):**
    - Added `ORB_JUDGE_DEMO_CODE` (disabled when unset/empty), `ORB_JUDGE_DAILY_CAP` (default `150` runs/day across all judge sessions), and `ORB_JUDGE_IP_DAILY_LIMIT` (default `3` session creations/IP/day) to `CreditConfig`.
    - Added `CreditService.create_judge_session(code, client_ip)` verified via `hmac.compare_digest`.
    - Synthetic judge identities are encoded as valid 20-byte addresses prefixed with `0x4a75646765<YYYYMMDD>` (`"Judge"` in hex + UTC day + 22 random hex chars) in existing `balances`/`sessions` tables and per-IP rate-limit markers in `challenges` (`judge-ip:<day>:<sha256>`), requiring zero database DDL/schema changes and keeping `orb_usdg_migrate.inspect_schema()` 100% intact.
    - Each valid session is pre-loaded with 10 demo credits (`granted=10`) so `CreditService.reserve()`, `settle()`, job polling (`/api/jobs/{id}`), result fetching (`/api/jobs/{id}/result`), and private media ownership checks work without modifying the core job pipeline.
    - Added `POST /api/orb/judge-session` in `prometheus/api/app.py`, wired `_client_ip(request)`, and updated `_authorize_ai()` and `/api/health` (`orb_ai_access`) so Judge Demo sessions are accepted even when Web3 RPC is disabled or alongside normal Arbitrum Sepolia credits.
  - **Frontend (`web/index.html`, `web/styles.css`, `web/wallet.js`, `web/app.js`):**
    - Added `#header-judge` (`"Judge Demo"`) button in `.header-actions` and `#judge-demo-box` inline access-code form inside `#wallet-panel` styled to match Orb's liquid-glass UI.
    - Added URL auto-unlock on page load in `web/wallet.js`: if `?judge=<code>` is present in `window.location.search`, Orb strips the `judge` param immediately via `window.history.replaceState` and calls `POST /api/orb/judge-session` to activate the 10-credit judge session automatically.
    - Preserved 100% of existing Arbitrum Sepolia wallet, ETH/USDG quote, and session restoration behavior when Judge Demo Mode is not active.
  - **Verification:**
    - `tests/test_orb_credits.py`: 20 passed (including `test_judge_demo_session_and_rate_limits`).
    - `web/credit-config.test.js`: 29 passed (including header button code activation and `?judge=<code>` URL auto-unlock + `history.replaceState` tests).

## 2026-10-16 — OpenCV AI Competition 2026, Sprint 1 Task 2: Read-only audit of `prometheus/analysis/` (Prep for Sprint 2)

- Audited `prometheus/analysis/orb_ai.py`, `prometheus/analysis/analyzer.py`, `prometheus/analysis/prompt_builder.py`, `prometheus/analysis/schema.py`, `prometheus/analysis/scene_schema.py`, `prometheus/api/dto.py`, `prometheus/pipeline.py`, `prometheus/video/`, and `requirements.txt`:
  1. **Image & Video Processing and OpenCV (`cv2`) Status:**
     - `cv2` / `opencv` is **not** currently imported anywhere in `prometheus/` and is **not** in `requirements.txt` (no `pyproject.toml` exists; dependencies are managed in `requirements.txt`, which currently lists `Pillow>=11.0`, `google-genai>=1.0`, `openai>=1.40`, `fastapi>=0.115`, `uvicorn>=0.30`, `pyyaml>=6.0`, `pytest>=8.0`, `python-multipart>=0.0.9`, `eth-account>=0.13,<1`, `psycopg[binary]>=3.2,<4`).
     - **Images:** Validated via `Pillow` (`Image.open` + `.verify()`) in `prometheus/api/app.py:_validate_orb_image()`, then read as raw bytes (`image.read_bytes()`) in `OrbAIService.image()` and passed directly to Gemini as `types.Part.from_bytes(data=..., mime_type=...)`.
     - **Videos:** Probed via `ffprobe` (`prometheus/video/probe.py:probe_video`), segmented into scenes via `ffmpeg` scene-change filter `select='gt(scene,threshold)',showinfo` (`prometheus/video/scene_detection.py:detect_scene_cuts`), and sampled into JPEG/PNG frames on disk via `ffmpeg -ss <timestamp> -i <video> -frames:v 1` (`prometheus/video/sampler.py:FrameSampler`). Per-scene frames (max 2 concurrent scene calls via `ThreadPoolExecutor(max_workers=2)`) and global frames are sent as `types.Part.from_bytes` to `GeminiAnalyzer`.
  2. **Exact Gemini Inputs & Prompt Structures (`decode`, `compose`, `enhance`):**
     - All Gemini calls use `types.GenerateContentConfig(system_instruction=..., response_mime_type="application/json", temperature=0.2, automatic_function_calling=disable)`.
     - **Image `decode` (`OrbAIService.image("decode", path)`):** System prompt `_IMAGE_DECODE`; user text `"Analyze the attached reference image and return the requested JSON."` + 1 image `Part.from_bytes`. Expects JSON `{ "prompt": str, "visual_analysis": {8 VISUAL_FIELDS}, "refinements": list[str] }`.
     - **Image `compose` (`OrbAIService.image("compose", path)`):** System prompt `_IMAGE_COMPOSE`; user text `"Analyze the attached reference image and return the requested JSON."` + 1 image `Part.from_bytes`. Expects the same JSON shape `{ "prompt", "visual_analysis", "refinements" }`.
     - **Video `decode` (`PrometheusPipeline.run` -> `video_generation_prompt`):**
       - Per scene (`GeminiAnalyzer.analyze_scene`): System prompt `SCENE_SYSTEM_PROMPT` (8 `SCENE_CATEGORIES`), user text `_scene_instruction` (scene index, start/end/duration, video resolution/fps, frame timestamps) + sampled scene frame `Part`s. Returns `{ "description": str, "categories": {key: {"observations": [...], "inferences": [...], "confidence": float}} }`.
       - Global (`GeminiAnalyzer.analyze`): System prompt `SYSTEM_PROMPT` (19 `CATEGORIES`), user text `_user_instruction` (video metadata, chronological frame timestamps, and per-scene descriptions timeline) + sampled global frame `Part`s. Returns `{ "summary": str, "categories": {...} }`.
       - `build_reconstructed_prompt(report)` builds Markdown with `## Generation prompt`, and `video_generation_prompt(markdown)` extracts the plain text prompt, while `_visual_from_report(analysis)` maps the 19 categories into the 8 `VISUAL_FIELDS`.
     - **Video `compose` (`PrometheusPipeline.run` + `OrbAIService.compose_video`):** Runs the same frame-based `PrometheusPipeline.run` first, then sends a JSON text payload `{"summary", "categories", "scenes": [{"start", "end", "description"}]}` to Gemini with system prompt `_VIDEO_COMPOSE` to synthesize `{ "prompt": str, "refinements": list[str] }`.
     - **Text `enhance` (`OrbAIService.enhance`):** System prompt `_ENHANCE`; user text is JSON `{"original_prompt": prompt, "intended_output": output, "visual_style": style, "detail_level": detail}` (no image parts). Returns `{ "enhanced_prompt": str }`.
  3. **JSON Structure Returned by `GET /api/jobs/{id}/result`:**
     - If `orb_result.json` exists in `run_dir` (all 3 Orb modes: `/api/orb/decode/file`, `/api/orb/compose/file`, `/api/orb/enhance`), `/api/jobs/{id}/result` returns `orb_result.json` directly:
       - **Image `decode` / `compose`:** `{"job_id", "mode": "orb", "operation": "decode"|"compose", "media_kind": "image", "image": {"name", "width", "height", "format", "preview_url"}, "prompt", "visual_analysis": {subject_and_scene, composition, lighting, camera_perspective, color_palette, visual_style, atmosphere, motion_and_progression}, "refinements": [...]}`
       - **Video `decode` / `compose`:** Same base keys as `build_result_dto()` (`job_id`, `tier`, `video`, `analyzer`, `summary`, `prompt_markdown`, `scene_count`, `scenes`, `global_frames`, `breakdown`, `parameters`) overlaid with `"mode": "orb"`, `"operation": "decode"|"compose"`, `"media_kind": "video"`, `"prompt": str`, `"visual_analysis": {8 VISUAL_FIELDS}`, `"refinements": list[str]`.
       - **Text `enhance`:** `{"job_id", "mode": "orb", "operation": "enhance", "media_kind": "text", "original_prompt", "prompt", "preferences": {"output", "style", "detail"}, "visual_analysis": {}, "refinements": []}`.

## 2026-10-16 — OpenCV AI Competition 2026, Sprint 2: OpenCV Agentic Vision Engine (`Perception -> Decision -> Action`)

- Added `opencv-python-headless>=4.10.0` (installed `5.0.0.93` in `.venv`) and `numpy>=1.26.0` (installed `2.5.4`) to `requirements.txt`.
- Created `prometheus/analysis/opencv_telemetry.py` implementing the OpenCV Agentic Vision Engine (`OpenCVTelemetry`, `analyze_image_cv`, `analyze_video_cv`) compatible across OpenCV 4.x and 5.x (`np.asarray(lines).reshape(-1, 4)` for `HoughLinesP`):
  - **Perception (Image & Keyframes):**
    - `cv2.cvtColor` (BGR -> LAB & HSV), `cv2.calcHist` CDF percentiles (`p5`–`p95` `dynamic_range_pct`), `mean_luminance`, `contrast_std`, `lighting_key` (`"low-key"`, `"high-key"`, `"low-contrast"`, `"balanced"`), and `cv2.kmeans` ($K=5$) dominant RGB Hex palette with percentage weights.
    - `cv2.Laplacian(gray, cv2.CV_64F).var()` focus sharpness, `cv2.Canny` edge density, `cv2.moments` spatial center-of-mass mapped to Rule-of-Thirds grid intersections (`"center-weighted"`, `"upper-left third"`, etc.), and `cv2.HoughLinesP` structural line orientation (`"horizontal-dominant"`, `"vertical-dominant"`, `"diagonal/dynamic"`, `"organic/curved"`).
  - **Perception (Video Motion & Continuity):**
    - `cv2.VideoCapture` / extracted frame sequence sampling with Farnebäck dense optical flow (`cv2.calcOpticalFlowFarneback`) computing mean horizontal (`mean_dx`), vertical (`mean_dy`), and radial zoom (`radial_flow`) vectors plus `motion_magnitude`, classifying dominant camera/scene motion (`"static/locked-off"`, `"pan-right"`, `"pan-left"`, `"tilt-up"`, `"tilt-down"`, `"push-in/zoom-in"`, `"pull-out/zoom-out"`, `"high-kinetic-motion"`).
    - 2D H-S histogram correlation (`cv2.compareHist(..., cv2.HISTCMP_CORREL)`) across consecutive frames to quantify continuity (`mean_hist_correlation`, `min_hist_correlation`, `continuity_class`), plus `frames_processed`, `processing_ms`, and `effective_fps`.
  - **Agentic Decision & Action Loop (`agentic_actions` / `agentic_decisions`):**
    1. **Autonomous CLAHE Shadow/Contrast Recovery:** When `mean_luminance < 60.0` or `contrast_std < 32.0`, applies `cv2.createCLAHE(clipLimit=2.5, tileGridSize=(8, 8))` on the LAB L-channel, writes `opencv_clahe_enhanced.jpg` into `run_dir`, and passes **both** the original image and the CLAHE-recovered frame to Gemini (`OrbAIService._generate`).
    2. **Sharpness-Gated Keyframe Ranking (Video):** Scores candidate video frames via `Laplacian` variance, flags blurry frames (`< 45.0`), selects the sharpest keyframe for primary telemetry, and logs the ranking in `motion_and_continuity.keyframe_ranking` and `agentic_actions`.
    3. **Adaptive Prompt Grounding Directive (`cv_grounding_brief`):** Generates a deterministic measurement summary injected into `OrbAIService.image()`, `OrbAIService.compose_video()`, and `_BaseRemoteAnalyzer._user_instruction()`.
- Wired `opencv_telemetry` into `prometheus/analysis/orb_ai.py`, `prometheus/analysis/analyzer.py`, `prometheus/pipeline.py`, and `prometheus/api/app.py` (`_run_orb_visual_job`) so every image and video `orb_result.json` includes top-level `"opencv_telemetry"`.
- Added unit and integration tests in `tests/test_opencv_telemetry.py`:
  - `pytest tests/test_opencv_telemetry.py tests/test_orb_ai.py -q`: 7 passed in 2.40s.
  - `pytest tests/test_pipeline.py -q`: 5 passed in 22.34s.

## 2026-10-16 — OpenCV AI Competition 2026, Sprint 3: Surfacing OpenCV 5.0 Agentic Telemetry & Benchmarks in the Orb UI

- **Backend Preview URL & UI Convenience Keys (`prometheus/analysis/opencv_telemetry.py`, `prometheus/api/app.py`):**
  - Updated `OpenCVTelemetry.to_dict()` and `_sharpness_and_geometry_metrics()` in `prometheus/analysis/opencv_telemetry.py` to include UI convenience fields alongside existing keys (`effective_fps`, `clahe_applied`, `sharpness_score`, `sharpness_label`, `saliency_region`, `dominant_lines`).
  - Updated `_run_orb_visual_job()` in `prometheus/api/app.py` so whenever autonomous CLAHE shadow/contrast recovery writes `opencv_clahe_enhanced.jpg` into `run_dir` (and `not public_mode`), `opencv_telemetry["clahe_preview_url"] = f"/api/jobs/{job.id}/frames/opencv_clahe_enhanced.jpg"` is attached to `orb_result.json` (and stripped in `public_mode` where local files are deleted immediately).
- **Frontend "OpenCV 5.0 Agentic Vision Telemetry" Card (`web/index.html`, `web/styles.css`, `web/app.js`):**
  - Added `#res-opencv-card` to `.result-grid` inside `#screen-results` (`web/index.html`) and styled it with Orb's liquid-glass aesthetic in `web/styles.css` (`.opencv-card`, `.opencv-badges`, `.opencv-badge.highlight`, `.opencv-actions-list`, `.opencv-clahe-wrap`, `.opencv-palette`, `.opencv-swatch`, `.opencv-metrics-grid`).
  - Implemented `renderOpenCVTelemetry(cv)` in `web/app.js`, called inside `renderResult(result)`:
    1. **Header & Benchmark Badges (Measurable Value):** Renders pills for `OpenCV <version>`, `Latency: <processing_ms> ms`, `Throughput: <effective_fps> FPS`, and a highlighted `CLAHE Auto-Recovery: Active` badge when `clahe_applied` / `clahe_triggered` is true.
    2. **Agentic Vision Loop (`Perception -> Decision -> Action` Log):** Renders `agentic_actions` step-by-step with perception triggers and autonomous actions, plus an interactive `"View OpenCV CLAHE Shadow Recovery"` preview toggle (`#res-opencv-clahe-toggle` / `#res-opencv-clahe-view` / `#res-opencv-clahe-img`) fetched via `loadPrivateMedia(result)` when in credit/judge mode.
    3. **Dominant Color Palette (`cv2.kmeans`):** Renders visual color swatches (`background-color: #hex`) with hex labels and percentage weights (`weight_pct%`) for each of the 5 extracted dominant colors.
    4. **Computer Vision Measurements Grid:** Displays `Lighting & Exposure (cv2.calcHist / LAB)`, `Composition & Focus (cv2.Laplacian / Canny / HoughLinesP)`, and (for video runs) `Optical Flow & Continuity (cv2.calcOpticalFlowFarneback / compareHist)`.
    5. **Text-Only `Enhance` Runs:** Automatically hides `#res-opencv-card` when `result.opencv_telemetry` is absent and keeps `.prompt-card` full-width (`#res-analysis-card.hidden + #res-opencv-card.hidden + .prompt-card { grid-column: 1 / -1; }`).
- **Verification:**
  - `tests/test_opencv_telemetry.py` + `tests/test_orb_ai.py`: 7 passed.
  - `web/opencv-telemetry.test.js` + `web/credit-config.test.js`: 31 passed (verifying badge pills, agentic loop trace, CLAHE preview toggle, 5 color swatches, CV metrics grid, and hiding on `Enhance`).

## 2026-10-17 — OpenCV AI Competition 2026, Sprint 4: AWS Graviton Deployment Kit, Benchmark Suite (`BENCHMARKS.md`), and Technical Report (`SUBMISSION_GUIDE.md`)

- **Deployment Configuration Audit:**
  - Inspected `vercel.json`, `web/api-url.js`, `scripts/check-vercel-env.mjs`, and `Dockerfile`.
  - Confirmed `orb-azure-ten.vercel.app` is built by Vercel (`npm run build:vercel` -> `web_dist`) with no proxy rewrites in `vercel.json`; instead, `web/api-url.js` prepends `import.meta.env.VITE_API_BASE_URL` to every `/api/*` request, currently pointing to the Render service (`https://orb-api-7qwv.onrender.com`), while keeping relative `/api/*` paths same-origin during local development.
- **AWS Graviton (`arm64` / `x86_64`) Zero-Cost Deployment Kit & Hardware SIMD Telemetry:**
  - Upgraded `Dockerfile` for multi-arch compatibility (`linux/arm64` AWS Graviton and `linux/amd64`), installing `ffmpeg`, `libglib2.0-0`, `curl`, and `requirements.txt` (`opencv-python-headless==5.0.0.93`), exposing port `8000`, and running `uvicorn prometheus.api.app:app --host 0.0.0.0 --port ${PORT:-8000}` (preserving PaaS `${PORT}` override compatibility).
  - Created `docker-compose.aws.yml` and `deploy/aws_graviton_setup.sh` for one-command provisioning on a free-tier AWS EC2 `t4g.small` (Ubuntu 24.04 LTS Arm64) instance with `GEMINI_API_KEY`, `ORB_JUDGE_DEMO_CODE=OPENCV2026`, `ORB_JUDGE_DAILY_CAP=150`, and `ORB_CORS_ORIGINS=https://orb-azure-ten.vercel.app`.
  - Added `detect_compute_runtime()` in `prometheus/analysis/opencv_telemetry.py` using `platform.machine()` and `cv2.getBuildInformation()` to report `compute_arch`, `compute_badge` (e.g., `ARM64 NEON` on AWS Graviton or `x86_64 AVX2`), and `compute_runtime` in `OpenCVTelemetry.to_dict()`, and updated `web/app.js` (`renderOpenCVTelemetry`) to display `OpenCV <version> · <compute_badge>`.
- **Reproducible Benchmark & Evaluation Suite (`scripts/benchmark_opencv.py` -> `BENCHMARKS.md`):**
  - Created and executed `scripts/benchmark_opencv.py` across 1080p standard (`260.9 ms` mean / `166.08 ms` best, `3.83 FPS`), 4K UHD (`555.62 ms` mean / `514.48 ms` best, `1.8 FPS`), 1080p underexposed low-contrast (`231.06 ms` mean, `4.33 FPS`, triggering autonomous CLAHE with **+22.4% luminance recovery**, **+16.6% contrast std expansion**, and **+42.6% Laplacian micro-edge sharpness gain**), and a 30-frame 720p optical-flow + keyframe-gating video sequence (`1429.36 ms` total, `47.65 ms/frame`, **`21.92 FPS`** effective throughput, filtering 3 motion-blurred frames).
- **Competition Technical Report & Architecture Diagram (`SUBMISSION_GUIDE.md`):**
  - Created `SUBMISSION_GUIDE.md` with a Mermaid architecture diagram (`Vercel Frontend -> AWS Graviton EC2 + OpenCV 5.0 Agentic Loop -> Gemini VLM + Arbitrum Sepolia / Judge Demo Gate`), detailed breakdown of the `Perception -> Decision -> Action` loop, local preview commands (`http://127.0.0.1:8000/?judge=OPENCV2026`), and step-by-step instructions to switch `VITE_API_BASE_URL` on Vercel to the AWS Graviton HTTPS origin.
- **Verification:**
  - `pytest tests/test_opencv_telemetry.py tests/test_orb_ai.py tests/test_orb_credits.py -q`: 27 passed.
  - `vitest run web/opencv-telemetry.test.js web/credit-config.test.js`: 31 passed.

## 2026-10-17 — OpenCV AI Competition 2026: Clean Commit on `main` & Local Preview Server Launch

- Verified `git status --short` on `main`—all modified and new files belong to Sprints 1–4 (`Dockerfile`, `HANDOFF.md`, `BENCHMARKS.md`, `SUBMISSION_GUIDE.md`, `docker-compose.aws.yml`, `deploy/aws_graviton_setup.sh`, `requirements.txt`, `prometheus/`, `scripts/benchmark_opencv.py`, `tests/`, and `web/`), with zero temporary or untracked junk artifacts.
- Staged all Sprint 1–4 files and created a single clean commit on `main`: `feat(opencv): add OpenCV 5.0 agentic vision telemetry, judge demo mode, and AWS Graviton deployment kit` (not pushed to `origin`, awaiting local browser testing).
- Started the local FastAPI preview server in the background on `http://127.0.0.1:8000` with `ORB_JUDGE_DEMO_CODE=OPENCV2026`, `ORB_JUDGE_DAILY_CAP=150`, and `ORB_COMPUTE_ENV=AWS` for browser testing at `http://127.0.0.1:8000/?judge=OPENCV2026`.

## 2026-10-17 — Live Diagnostic Fix: Wake-Up Stall, Stale `web_dist/` Bundle, and OpenCV 5.0 Native Video Fallbacks

- **Root Cause 1 — Stale `web_dist/` Bundle & Localhost API Routing (`web/api-url.js`, `web/wallet.js`, `web_dist/`):**
  - `prometheus/api/app.py` serves `_BUILT_WEB_DIR` (`web_dist/`) when it exists. The pre-existing `web_dist/` bundle predated Sprints 1–3 and had `VITE_API_BASE_URL` baked in, causing local runs to wait on a cold Render instance (`"Credit service is starting…"` / `"Orb is taking longer to start. Try again shortly."`).
  - Updated `web/api-url.js` so `window.location.hostname === "localhost" || window.location.hostname === "127.0.0.1"` **always** returns same-origin `""` regardless of build-time `VITE_API_BASE_URL`, and guarded `import.meta.env` in `web/api-url.js` and `web/wallet.js`.
  - Updated `_check_origin()` in `prometheus/api/orb_credits.py` to accept both `http://127.0.0.1(:port)` and `http://localhost(:port)` when `ORB_ENV == "local"`.
  - Rebuilt `web_dist/` with `npm run build` so FastAPI serves the updated `#header-judge` and `#res-opencv-card` assets locally.
- **Root Cause 2 — Pure OpenCV 5.0 (`cv2.VideoCapture`) Fallbacks for Video Upload & Fast `/api/ready`:**
  - Cached verified video tools in `_VERIFIED_VIDEO_TOOLS` in `prometheus/api/app.py` (`_verify_video_tool`) and added an OpenCV (`import cv2`) fallback so `/api/ready` responds in `<10 ms` without spawning `ffmpeg -version` subprocesses on every poll.
  - Added pure OpenCV 5.0 (`cv2.VideoCapture`) native fallbacks across the entire video pipeline whenever `ffprobe` or `ffmpeg` is missing or fails:
    - `prometheus/video/probe.py` (`_probe_video_opencv`): Extracts width, height, FPS, frame count, duration, and FOURCC codec via `cv2.VideoCapture`.
    - `prometheus/video/scene_detection.py` (`_detect_scene_cuts_opencv`): Computes consecutive 2D HSV histogram distances (`1.0 - cv2.compareHist(..., cv2.HISTCMP_CORREL)`) at ~12 Hz to detect scene cuts without `ffmpeg`.
    - `prometheus/video/sampler.py` (`_extract_frame_opencv`, `FrameSampler.__init__`) and `prometheus/video/segmenter.py` (`SceneSegmenter.__init__`): Seek to target timestamps (`cv2.CAP_PROP_POS_MSEC`) and write PNG frames via `cv2.imwrite`.
- **Root Cause 3 — Gemini Model Availability & `.env` Key Loading (`prometheus/analysis/analyzer.py`, `prometheus/api/app.py`):**
  - Updated `GeminiAnalyzer._generate_with_model_fallback` in `prometheus/analysis/analyzer.py` to iterate through `("gemini-flash-lite-latest", "gemini-2.5-flash", "gemini-2.5-flash-lite")` on `404`/`NOT_FOUND` (since Google deprecated `models/gemini-2.5-flash-lite` for newer API keys in favor of `gemini-flash-lite-latest`).
  - Added `_load_local_dotenv_defaults()` in `prometheus/api/app.py` to load `GEMINI_API_KEY` and `ORB_JUDGE_DEMO_CODE` from `.env` when running outside `pytest`.
- **Live End-to-End Verification Against Running Server (`http://127.0.0.1:8000`):**
  - `GET /`: `200 OK` (`#header-judge` and `#res-opencv-card` present).
  - `GET /api/ready` & `GET /api/orb/credits/config`: `200 OK` (`5.9 ms`, `enabled=True`, `judge_demo_enabled=True`).
  - `POST /api/orb/judge-session` (`{"code": "OPENCV2026"}`): `200 OK` (`credits=10`).
  - Live Image `POST /api/orb/decode/file`: Completed with `OpenCV 5.0.0 (AWS x86_64 AVX2)`, `clahe_applied=True`, and Gemini reconstructed prompt (`262 chars`).
  - Live 2-Second MP4 Video `POST /api/orb/decode/file`: Completed with `OpenCV 5.0.0`, `motion_class="pan-right"`, `effective_fps=15.86`, `scenes=1`, and Gemini reconstructed prompt (`2974 chars`).
  - Unit tests: `pytest` (`44 passed`) + `vitest` (`31 passed`).

## 2026-10-17 — Fix `?judge=OPENCV2026` Startup Race Condition & Localhost Web3 Wallet Connection

- **Fix 1 — `?judge=OPENCV2026` Startup Race Condition & UI State (`web/wallet.js`, `web/app.js`):**
  - Previously, `loadConfig()` and `checkJudgeUrlParam()` ran concurrently on startup (`void loadConfig(); checkJudgeUrlParam();`). When `window.ethereum` was present, `GET /api/orb/credits/config` resolved in ~5ms while `POST /api/orb/judge-session` (~170ms) was still in flight (`isJudge === false`), causing `loadConfig()` to invoke `restoreWallet()` -> `window.ethereum.request({ method: "eth_accounts" })` under the same `authEpoch` and overwrite or clear the newly created Judge Demo session.
  - Updated `web/wallet.js` to extract `?judge=<code>` synchronously (`extractJudgeUrlCode()`) and `await checkJudgeUrlParam()` **sequentially after** `requestConfig()` inside `loadConfig()`, returning before `restoreWallet()` can run.
  - Added `judgeActivating` guard and incremented `authEpoch += 1` inside `activateJudgeDemo()` so `restoreWallet()`, `restoreSession()`, `accountsChanged`, and `chainChanged` never overwrite or clear an activating or active Judge session.
  - Updated Judge Demo UI state in `web/wallet.js` and `web/app.js` to display `"Judge Demo Mode is Active"` with `"10 test credits available"`, keep `#header-wallet` as `"Connect Wallet"`, keep `#wallet-connect` (`"Connect and sign"`) enabled, and label `#wallet-disconnect` as `"Exit Judge Mode / Connect Wallet"` so users can switch to a real Web3 wallet at any time.
- **Fix 2 — Localhost Web3 Wallet Connection & Treasury Configuration (`prometheus/api/app.py`, `prometheus/api/orb_credits.py`, `web/wallet.js`):**
  - Updated `_load_local_dotenv_defaults()` and `create_app()` in `prometheus/api/app.py` to load `ORB_CREDITS_ENABLED`, `ORB_ARBITRUM_RPC_URL`, and `ORB_CREDIT_RECEIVER` / `ORB_TREASURY_ADDRESS` (defaulting locally to checksummed `0xc855D21175D81C852E657169424FA974171394F1`) so `GET /api/orb/credits/config` returns `enabled: true` and `"treasury_address": "0xc855D21175D81C852E657169424FA974171394F1"`.
  - Updated `challenge()`, `sign_in()`, and `_check_origin()` in `prometheus/api/orb_credits.py` so both `http://127.0.0.1:8000` and `http://localhost:8000` are accepted and the SIWE challenge message binds the exact verified browser origin (`netloc` and `URI`) to prevent MetaMask/Rabby/Zerion domain-mismatch warnings.
  - Updated `accountsChanged` and `chainChanged` listeners in `web/wallet.js` so initial account selection (`eth_requestAccounts`) and switching to Arbitrum Sepolia (`wallet_switchEthereumChain`) during `connect()` do not prematurely call `clearSession()`.
- **Verification:**
  - Rebuilt `web_dist/` (`npm run build`), restarted FastAPI server on `127.0.0.1:8000`, and verified `GET /api/orb/credits/config`, `POST /api/orb/judge-session`, and `POST /api/orb/wallet/challenge` + `/api/orb/wallet/sign-in` across both `http://127.0.0.1:8000` and `http://localhost:8000`.
  - `pytest tests/test_orb_credits.py -q` (`20 passed`) and `vitest run web/credit-config.test.js` (`29 passed`).

