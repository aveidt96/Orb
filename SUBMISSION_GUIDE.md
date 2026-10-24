# Orb — OpenCV AI Competition 2026 (Powered by AWS) Technical Report & Submission Guide

**Orb** is a visual intelligence and creative prompt engineering platform.
**Decode** reconstructs a plausible generation prompt from an image or video;
**Compose** builds a new prompt inspired by a reference; **Enhance** refines an
existing text prompt. **Create** is visibly locked and coming soon. Orb currently
produces prompts, not generated media, and cannot guarantee the creator's exact
original prompt.

Orb combines an **OpenCV 5.0 Agentic Vision Engine** with **Orb AI** multimodal
synthesis. Pixel-derived measurements and conditional visual recovery ground
the synthesis; they do not guarantee elimination of model hallucinations.

The runtime and operational observations below were verified in the
**2026-10-24 read-only audit and subsequent authorized deployment/live Decode
benchmark**. See [BENCHMARKS.md](BENCHMARKS.md) and the
[sanitized AWS evidence log](docs/AWS_OPENCV_BENCHMARK_2026-10-24.json) for
provenance, new ARM64 results and separately labeled local baseline measurements.

## 1. Live architecture: Vercel → AWS Lambda / Mangum → OpenCV + Orb AI + S3

```mermaid
flowchart TB
    subgraph Client["Vercel — orb-azure-ten.vercel.app"]
        UI["Liquid-glass Web UI\nDecode · Compose · Enhance; Create locked"]
        Gate["Explicit judge link OR signed Arbitrum Sepolia wallet"]
        Results["Prompt, analysis, OpenCV telemetry and preview controls"]
    end
    subgraph AWS["AWS us-east-1 — Lambda arm64 Graviton2 + Amazon S3"]
        API["FastAPI via Mangum\nPython 3.12 ZIP package\nServerless-synchronous execution"]
        CV["OpenCV 5.0\nPerception → Decision → Action"]
        Artifacts["S3 orb-jobs/<job_id>/\nHUD, conditional CLAHE, telemetry, job_state.json"]
        Ledger["S3 orb-credits/ledger-v1.sqlite3\nSessions, quotes, balances, reservations, results\nEncrypted ETag-conditional snapshot writes"]
    end
    Synthesis["Orb AI\nExternal multimodal model API"]
    Arb["Arbitrum Sepolia RPC\nTest ETH / Paxos test USDG verification"]
    UI -->|"HTTPS via VITE_API_BASE_URL"| API
    Gate -->|"Judge code exchange or wallet signature authentication"| API
    API --> Ledger
    API -->|"Verify testnet transaction"| Arb
    API --> CV
    CV -->|"Original reference, optional recovered image, grounding brief"| Synthesis
    Synthesis -->|"Structured prompt and analysis"| API
    API -->|"Best-effort diagnostic / job-state persistence"| Artifacts
    API -->|"Authenticated result retrieval"| Results
```

### Verified deployment footprint

- **Frontend:** `https://orb-azure-ten.vercel.app`
- **Backend:** `https://jsnwiqkw5sqs3c7hag6ywd3ngm0vljpc.lambda-url.us-east-1.on.aws/`
- **Lambda:** `orb-opencv5-api`, `us-east-1`, `Architectures=["arm64"]`, Python 3.12,
  **512 MB**, **120-second timeout**, active at audit.
  The enhanced ZIP was deployed on October 24 at **01:51:18 UTC**, preserving
  the existing configuration, payment options, Function URL and credit ledger.
- **Adapter:** `handler = Mangum(app, lifespan="auto")` in `prometheus/api/app.py`.
  `ORB_SERVERLESS_SYNC=1` makes accepted jobs execute before Lambda returns and
  freezes the invocation; scratch work uses `/tmp`.
- **Packaging:** The live function uses a **ZIP**, assembled by the arm64 wheel
  packager in `deploy/deploy_aws_lambda.py`. `Dockerfile.lambda` is a supported
  container-image build path, not the packaging of the audited live function.
- **OpenCV:** `opencv-python-headless==5.0.0.93`, with runtime
  `cv2.__version__ == "5.0.0"`. Deployed package metadata and the AArch64 native
  binary were inspected; historical telemetry reports ARM64 NEON / FP16.
- **Version pin:** `pyproject.toml`, `requirements.txt` and the ZIP deployer's
  package list pin `5.0.0.93`. The Lambda Dockerfile installs `requirements.txt`.
- **Public API origin:** Production Vercel's `VITE_API_BASE_URL` targets Lambda.

The repository also contains an EC2/Uvicorn/Cloudflared deployment path
(`deploy/aws_graviton_setup.sh`, `docker-compose.aws.yml`). That is an alternate
deployment option, not the architecture of the audited live service. Local
x86_64 AVX2 execution is likewise distinct from AWS arm64 execution.

### Health and readiness

`GET /api/health` returns application status, application version, analyzer
configuration, payment-gate status and AI-access state. The repository now also
registers `GET /health` on **the same handler**, returning the exact same JSON.
Neither response includes the OpenCV package version or architecture.

After deployment, live `/health` and `/api/health` both returned **200 with
identical JSON**. Live `/api/ready` also returned 200. The earlier audit's root
404 is historical. Readiness checks local upload prerequisites; it does not
execute an AI operation, purchase credits or prove an S3 write.

## 2. OpenCV agentic loop: Perception → Decision → Action

### Perception

- **Exposure:** BGR-to-LAB/HSV conversion, LAB L-channel histogram percentiles,
  mean luminance, contrast standard deviation and dynamic range.
- **Palette:** `cv2.kmeans` in **RGB space**, up to five clusters, returning
  RGB/hex centers and pixel weights. There is no separate LAB cluster palette;
  cluster initialization uses `KMEANS_PP_CENTERS` without a fixed RNG seed.
- **Focus and geometry:** Laplacian variance, Canny edge density, edge
  center-of-mass relative to rule-of-thirds points, and probabilistic Hough lines.
  `structural_lines.line_count` is in JSON and the UI renders it beside the
  orientation, for example **`vertical-dominant (216 lines)`**.
- **Video:** Farnebäck dense optical flow, horizontal/vertical/radial motion
  summaries and HSV histogram correlation for visual continuity.

### Decisions and actions

1. **CLAHE recovery:** `mean_luminance < 60.0` **or** `contrast_std < 32.0`
   automatically triggers `cv2.createCLAHE(clipLimit=2.5, tileGridSize=(8, 8))`.
   Recovery modifies the LAB **L-channel**, retaining the A/B channels before
   conversion back to BGR, and writes `opencv_clahe_enhanced.jpg`. Original and
   recovered references can both be supplied to Orb AI.
   Recovery now measures enhanced-image Canny edge density and Laplacian variance
   before JPEG encoding, and calculates signed percentage changes from the
   original frame's published measurements.
2. **Keyframe ranking:** Video candidates are ranked by Laplacian variance;
   values below **45.0** are flagged as blurry. The sharpest candidate supplies
   primary OpenCV telemetry. Ranking/flags should not be described as proof that
   every blurry frame is removed from every downstream model call.
3. **Grounding:** `cv_grounding_brief` passes pixel measurements and action
   summaries into the multimodal synthesis context.
4. **HUD:** `opencv_hud_overlay.jpg` visualizes Canny contours, a rule-of-thirds
   grid, Hough structural lines, saliency crosshairs and RGB palette swatches;
   video HUDs can additionally include optical-flow vectors.

### What the results UI actually displays

The **OpenCV 5.0 Agentic Telemetry** card appears after Decode/Compose returns
visual telemetry; text-only Enhance results hide it. It shows:

- Runtime badge: **`OpenCV 5.0.0 · AWS S3 · ARM64 NEON`** in the audited AWS sample.
- OpenCV processing latency, effective throughput and conditional
  **`CLAHE Auto-Recovery: Active`**, plus a highlighted **`+N.N% edge gain`** when
  recovery produces a positive, defined relative edge-density change.
- **`AWS S3 Synced (orb-opencv5-vision-2026)`** when the sync metadata qualifies.
- Exposure, Laplacian sharpness, Canny edge density, saliency, Hough orientation
  **and line count**, hex/weight palette swatches, and video motion/continuity
  when present. A recovery row shows enhanced measurements and signed gains.
- Action/trigger logs and **Original Reference**, **OpenCV Vision HUD**,
  **CLAHE Shadow Recovery** preview tabs when their artifacts are available.

Production telemetry now returns **`post_clahe_edge_density`** (percentage),
**`edge_density_gain_pct`**, **`post_clahe_laplacian_variance`** and
**`sharpness_gain_pct`** at the root, inside `clahe_recovery`, and in the recovery
action log, for both images and video keyframes. Canny thresholds remain 80/180;
Laplacian uses `CV_64F`. Published measurements have two decimals and gains have
one. Bypassed recovery returns nulls; zero baselines yield an undefined (`null`)
relative gain instead of infinity. Gains can be negative and are image-dependent.

All three fresh AWS underexposed 1080p runs measured **0.96% → 1.08% edge density
(+12.5%)** and **20.06 → 28.04 Laplacian variance (+39.8%)** before JPEG encoding.
The historical corridor audit's **+66.1%** measured a decoded JPEG artifact and
is not a universal gain or an interchangeable pre-JPEG measurement.
The final fresh Vercel corridor Decode reported **+65.0% edge gain** and
**+121.8% sharpness gain**, with **216 Hough lines** displayed in the UI.

## 3. Judge instant access and the public Web3 boundary

**Judge link:** `https://orb-azure-ten.vercel.app/?judge=OPENCV2026`

- The exact explicit query parameter is required by the frontend. Backend
  capability confirmation precedes automatic `POST /api/orb/judge-session`.
  Activation does not request wallet connection, signing or payment.
- A new judge session normally receives **10 evaluation credits**, bounded by
  remaining daily capacity. Exhausted limits return 429. Judge credits are
  separate from purchased wallet credits and cannot purchase more credits.
- The query is **retained** so reload stays in explicit judge mode. A valid cached
  judge session is restored on that link without another grant.
- Judge controls, including the header button/code form, are available only on
  the explicit judge link after backend confirmation. They are hidden on clean
  public URLs; they are not a public payment-failure bypass.
- Clean `/` visits clear cached Orb judge sessions/flags from localStorage and
  sessionStorage, while retaining unrelated wallet state. This does not delete
  server-side balances.
- Config defaults `judge_demo_enabled` to false; a matching code or valid judge
  bearer session can enable it. Config responses are `private, no-store`.
- Backend checks use `hmac.compare_digest`. The audited deployment uses
  **150 global runs/day** and **25 judge sessions/IP/day**. These limits constrain
  usage; they do not guarantee that automated access is impossible.

Public consumers authenticate with an EVM wallet on **Arbitrum Sepolia**:
**421614 / `0x66eee`**, using `https://sepolia-rollup.arbitrum.io/rpc`. Both native
test ETH and Paxos test USDG were enabled at audit. Credits are testnet/demo
credits with no real-money value. One successful Decode, Compose or Enhance
consumes one credit; failed processing releases its reservation.

## 4. Amazon S3 persistence and atomic credit accounting

### Diagnostic artifacts and job state

With `ORB_AWS_S3_BUCKET=orb-opencv5-vision-2026` and AWS credentials (including
Lambda execution-role credentials), the artifact module uploads available files:

```text
s3://orb-opencv5-vision-2026/orb-jobs/<job_id>/opencv_hud_overlay.jpg
s3://orb-opencv5-vision-2026/orb-jobs/<job_id>/opencv_clahe_enhanced.jpg
s3://orb-opencv5-vision-2026/orb-jobs/<job_id>/opencv_telemetry.json
s3://orb-opencv5-vision-2026/orb-jobs/<job_id>/job_state.json
```

The CLAHE image exists only when recovery triggers. S3 diagnostic uploads are
**best-effort**, with bounded per-request connection/read timeouts, and are
separate from credit settlement. They are not an atomic multi-object upload.
`aws_s3.synced` means at least one candidate uploaded; inspect the returned
`keys` for completeness. The stored telemetry JSON is uploaded before final sync
metadata is added, so it need not contain the final `aws_s3` result.

The backend can issue 24-hour pre-signed HUD/CLAHE URLs and fallback-read
diagnostics/job JSON from S3 across Lambda containers. Original uploaded media
is not part of this diagnostic S3 upload set; its server `/tmp` copy is ephemeral.
For a newly submitted job, the browser keeps a job-bound object URL for the
user-selected File so the Original tab does not depend on Lambda container
affinity. The URL is released on returning home, selecting a new reference or
rendering another job; it is not persisted across reloads or uploaded again.

### Shared credit/result ledger

The audited Lambda has no `ORB_DATABASE_URL`; its authoritative ledger is:

```text
s3://orb-opencv5-vision-2026/orb-credits/ledger-v1.sqlite3
```

Each operation reads a fresh SQLite snapshot into memory. Grants, sessions,
quotes, accepted transactions, balances, reservations and durable result JSON
share this ledger. Publication uses **AES256 encryption** and S3 **`If-Match`**
against the loaded ETag; initial bootstrap uses **`If-None-Match: *`**. Conflicts
retry the complete operation against a fresh snapshot, up to eight attempts.
Storage failures fail closed rather than granting/spending against stale state.

Result persistence precedes successful credit settlement. These are separate
conditional-write operations; an interruption between them can leave a durable
result with a reserved credit. Cold starts do not blindly release another live
invocation's reservation. The snapshot ledger is capped at **16 MiB**; the
repository also supports Postgres for larger workloads.

The October 24 read-only audit found a valid encrypted ledger and no
balance/reservation inconsistencies. The subsequent live benchmark created a
real 10-credit judge session and completed **six real Decode jobs**, ending at
**4 available / 6 consumed / 0 reserved**. Every job's expected S3 objects were
verified, including CLAHE artifacts on all underexposed inputs. Concurrency and
storage-failure handling remain covered by mocked S3/RPC tests rather than a
destructive production race test. See [Lambda credit persistence](docs/LAMBDA_CREDIT_PERSISTENCE.md).

## 5. Performance evidence and validation limits

- Fresh AWS arm64 **1920×1080**, three runs per workload, **512 MB Lambda**:
  standard scene **948.350 ms mean** (646.084–1,439.173 ms), underexposed scene
  **865.268 ms mean** (838.369–899.963 ms). Corresponding mean upload-to-result
  times were **6,671.7 ms** and **5,288.8 ms**, including real AI synthesis.
  These are sequential observations with no verified cold/warm classification,
  not an SLA or a sub-180 ms result.
- Historical AWS OpenCV analysis of the **1280×720** corridor reference reported
  **1,578.769 ms** and **2,233.344 ms**. These are individual observations, not
  1080p averages or an SLA.
- The original demo capture recorded **46.67 seconds** for upload, polling,
  result and artifact retrieval. Its edited interaction timings are not a
  real-time performance recording.
- The recorded local x86_64 AVX2 synthetic **1080p standard-scene mean is
  260.9 ms**; its best run was 166.08 ms. No controlled sub-180 ms 1080p Lambda
  result has been established.
- The original audit used read-only inspection and intercepted browser replay.
  The later benchmark exercised the ordinary deployed, judge-authenticated Decode
  pipeline and real S3 persistence/credit settlement, without a debug endpoint or
  automatic media-POST retries. No wallet purchase, signature or blockchain
  transaction was made. The earlier local baseline predates the additional
  recovery measurements; it is not a controlled hardware speedup comparison.

Local regression verification for the recovery-metrics revision: **343 backend
tests passed**, with **8 Postgres integration skips**, and **246 frontend tests
passed across 10 files**. The health test checks both aliases; new recovery tests
cover positive measurements, bypass, zero baselines and video keyframes. UI tests
cover Hough counts, positive/negative/undefined gains and older result payloads.
Two additional UI regressions verify original image/video previews when Lambda's
temporary source endpoint is unavailable, including URL cleanup and job isolation.
Mobile header actions wrap so judge, wallet, credits and menu controls remain
within the viewport when all are visible.
The guarded production frontend build also passed, including the preview fix.

The final production Vercel browser workflow passed with **unmocked HTTP**:
automatic 10-credit judge activation without a wallet prompt, one corridor
Decode, quantitative recovery/Hough display, and all three preview images
loaded. The balance became **9 available / 1 consumed / 0 reserved**; a reload
restored that spent balance without another grant. Returning to the public URL
hid judge controls and cleared the cached session. Desktop (1440px) and mobile
(390px) result layouts stayed within the viewport. Direct S3/ledger inspection
confirmed all expected objects, matching recovery metrics and the consumed
reservation with a durable result. This completes the previously pending live
judge/Decode verification; it is not a real-wallet purchase test.

## 6. Local preview and deployment references

Install the repository's pinned dependencies and configure the existing backend
provider credentials privately. For the current provider, the environment name
is `GEMINI_API_KEY`; no credential belongs in frontend `VITE_` variables.

```powershell
$env:ORB_ENV = "local"
$env:ORB_JUDGE_DEMO_CODE = "OPENCV2026"
$env:ORB_JUDGE_DAILY_CAP = "150"
# Configure the backend API key in the local environment or ignored .env.
.\.venv\Scripts\python.exe -m uvicorn prometheus.api.app:app --host 127.0.0.1 --port 8000
```

Open `http://127.0.0.1:8000/?judge=OPENCV2026`. The active header reads
**Judge Demo · Active**, with credits displayed separately. Analyze a dark
reference to inspect the telemetry and available preview tabs. Do not label a
local machine as AWS by setting `ORB_COMPUTE_ENV=AWS`.

For an explicitly authorized deployment of the existing Lambda ZIP function:

```powershell
.\.venv\Scripts\python.exe deploy/deploy_aws_lambda.py --mode zip
```

The deployer preserves the existing function's package type and runtime settings;
it does not replace a ZIP function with a container deployment. Vercel Production
should keep `VITE_API_BASE_URL` set to the audited Lambda origin. Share the exact
judge link above for evaluation access.
