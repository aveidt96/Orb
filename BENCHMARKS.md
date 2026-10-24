# OpenCV 5.0 Agentic Vision Engine — Verified Runtime & Reproducible Benchmarks

## Verified AWS Lambda runtime and operational observations

The **2026-10-24 read-only verification audit** inspected the existing live
`orb-opencv5-api` deployment in `us-east-1`, its deployment package, completed
job artifacts, and HTTP endpoints. These observations are distinct from the
controlled **local x86_64 synthetic benchmarks** preserved below.
The enhanced pipeline was subsequently redeployed and exercised through six real
Decode requests on October 24; the fresh results are recorded next.

| Runtime property | Verified value / evidence |
| :--- | :--- |
| Compute | AWS Lambda arm64 (Graviton2); AWS control plane reports `Architectures=["arm64"]`, `State=Active` |
| Execution model | Python 3.12 **ZIP package**, FastAPI via `Mangum(app, lifespan="auto")`; serverless-synchronous execution |
| Configuration | 512 MB memory; 120-second execution timeout; enhanced ZIP deployed `2026-10-24T01:51:18Z` |
| OpenCV package | **`opencv-python-headless==5.0.0.93`**, verified in the deployed distribution metadata |
| OpenCV runtime | **`cv2.__version__ == "5.0.0"`** in persisted AWS job telemetry; distribution and runtime version strings differ intentionally |
| Native architecture | `cv2/cv2.abi3.so` has ELF machine `183` (AArch64); persisted runtime reports `aarch64`, `ARM64`, NEON and FP16 |
| Actual telemetry badge | `OpenCV 5.0.0 · AWS S3 · ARM64 NEON` |
| Persistence | `s3://orb-opencv5-vision-2026/orb-jobs/<job_id>/` for diagnostics/job JSON; encrypted conditional-write credit ledger at `orb-credits/ledger-v1.sqlite3` |

### Fresh production AWS 1080p measurements — October 24, 2026

`scripts/benchmark_lambda_opencv.py` submitted **three sequential Decode requests
per workload** through the live Function URL between **01:51:54 and 01:52:49 UTC**.
It used the same 1920×1080 fixture generators and default JPEG encoding as the
local baseline script. Every result reported `aarch64`, `ARM64`, NEON / FP16 and
OpenCV `5.0.0`. Code SHA-256, input hashes, individual timings and job IDs are
recorded in [the sanitized evidence log](docs/AWS_OPENCV_BENCHMARK_2026-10-24.json).

| Workload | AWS OpenCV runs (ms) | AWS mean | AWS min–max | Mean upload → result | Historical local x86_64 mean |
| :--- | :--- | ---: | :--- | ---: | ---: |
| 1080p standard scene | 1,439.173 / 646.084 / 759.792 | **948.350 ms** | 646.084–1,439.173 ms | 6,671.7 ms | 260.9 ms |
| 1080p underexposed | 857.472 / 899.963 / 838.369 | **865.268 ms** | 838.369–899.963 ms | 5,288.8 ms | 231.06 ms |

The standard workload bypassed CLAHE. All three underexposed runs reported:

| Production recovery measurement | Original | Enhanced (before JPEG) | Relative gain |
| :--- | ---: | ---: | ---: |
| Canny edge density | 0.96% | 1.08% | **+12.5%** |
| Laplacian variance | 20.06 | 28.04 | **+39.8%** |

The new production fields appear at the telemetry root, in `clahe_recovery`, and
in the recovery action log. The enhanced BGR image is measured **before lossy
JPEG encoding**, using the original frame's Canny thresholds (80/180) and
Laplacian (`CV_64F`). Edge density and variance are published to two decimal
places; relative gains use those published values and are rounded to one decimal.
A zero original baseline yields `null` for its percentage gain; bypassed
recovery yields `null` for all four new fields. Negative gains remain signed.

These are small-sample observations on a **512 MB Lambda**, not cold/warm
percentiles or an SLA. Container identity was not classified. The historical
local baseline predates the added recovery measurements; this is not a controlled
hardware speedup comparison. Neither AWS workload reached sub-180 ms latency.
OpenCV timing excludes external AI synthesis, network transfer and S3 uploads;
upload → result timing includes the actual AI-backed request and result retrieval,
but excludes the subsequent diagnostic-object checks.

All six jobs returned prompts and their expected S3 HUD/telemetry/job-state
objects; all underexposed jobs also persisted the CLAHE image. A single real
judge grant started at 10 credits and finished at **4 available / 6 consumed /
0 reserved**, validating settlement after every result. No wallet purchase or
blockchain transaction was submitted.

To reproduce (creates a new judge grant and six real, credit-consuming AI jobs):

```powershell
.\.venv\Scripts\python.exe scripts/benchmark_lambda_opencv.py --iterations 3 --output output/aws-opencv-new-run.json
```

The output parent must exist and the report filename must be new. The script
journals attempts and does not automatically retry a media POST. Reports exclude
tokens, wallet identifiers and signed URLs. The existing Function URL and AWS
read credentials are required for runtime/S3 verification.

### Live Vercel judge workflow and corridor reference

The final end-to-end browser check on **2026-10-24, 02:24:17–02:24:44 UTC** used
the production Vercel judge link, a real automatic 10-credit grant and one real
Decode of the **1280×720** corridor image. No HTTP responses were mocked.

- OpenCV processing: **1,620.945 ms**; browser upload-to-render: **12,747 ms**.
- Canny edge density: **8.35% → 13.78%**, production gain **+65.0%**.
- Laplacian variance: **421.57 → 935.14**, production gain **+121.8%**.
- UI: **`vertical-dominant (216 lines)`**, **`+65.0% edge gain`** and the real S3
  sync badge were visible. Original, HUD and CLAHE previews all loaded at 1280px
  native width. The original used the selected local File, avoiding ephemeral
  Lambda source-file reads.
- Credits: **10 → 9 available**, **1 consumed**, **0 reserved**. Reload preserved
  the spent balance without another judge grant; a clean public visit hid judge
  controls and cleared the cached judge session.
- Real result layouts had no horizontal overflow at **1440px and 390px**.
  Recorded-result layout replay additionally checked 320, 360 and 600px.
- All four S3 diagnostic/job-state objects were present; the persisted telemetry
  matched the HTTP result. The encrypted ledger contained one consumed
  reservation and one durable result for job `b9c78604fd8d44a8bf994c5b59f63341`.

This is a separate single-image end-to-end check, not part of the 1080p averages.
Earlier live browser checks exposed temporary-source preview and mobile-header
issues, which were fixed and published to Vercel before this passing check.
The evidence log records the additional verification jobs separately.

### Historical AWS image-processing samples

Both samples use the original **1280×720** industrial corridor reference. They
are individual production observations, not an averaged 1080p benchmark.

| Observation | Measured duration | Provenance / scope |
| :--- | ---: | :--- |
| Original demo OpenCV analysis | **1,578.769 ms** | Persisted result for job `e06339087c1546e084287b45410018e2` |
| Later OpenCV analysis of the same reference | **2,233.344 ms** | Persisted result for job `50bbe2f1cac6496d92f49d8b2b23d523`; read directly from S3 during the audit |
| Original demo capture workflow | **46.67 s** | Recorded upload, polling, result and diagnostic-artifact retrieval; includes external AI/network work and is not OpenCV processing latency |

`processing_ms` measures the local OpenCV analysis, including image decoding,
measurements, conditional recovery and HUD generation for these image samples.
It does not measure the full upload, external AI synthesis, S3 sync or HTTP
result-delivery workflow. No controlled **sub-180 ms 1080p Lambda benchmark**
has been established.

### HTTP observations from the 2026-10-24 audit

All values are client-observed round trips in milliseconds, including network
overhead. Initial and later requests are individual observations; the audit did
not establish cold/warm container identity, percentiles, load capacity or an SLA.

| Request | HTTP status | Initial round trip | Later round trip |
| :--- | ---: | ---: | ---: |
| Lambda `/api/health` | 200 | 2,983.9 ms | 1,311.5 ms |
| Lambda `/api/ready` | 200 | 2,961.1 ms | 237.0 ms |
| Lambda `/api/orb/credits/config` | 200 | 2,953.6 ms | — |
| Lambda `/api/orb/credits/config?judge=OPENCV2026` | 200 | 1,917.4 ms | 210.8 ms |
| Vercel `/` | 200 | 1,862.1 ms | — |
| Vercel `/?judge=OPENCV2026` | 200 | 1,840.8 ms | — |

At the earlier audit, `/health` returned **404** in 2,955.1 ms. After the enhanced
deployment, both health aliases returned **200 with identical JSON**:

| Post-deployment request | HTTP | Round trip |
| :--- | ---: | ---: |
| `/health` | 200 | 5,482.4 ms |
| `/api/health` | 200 | 229.0 ms |
| `/api/ready` | 200 | 231.5 ms |

These are individual sequential observations, not an isolated cold-start test.
Neither health route adds architecture/package metadata to its payload; those
facts were independently verified above. Readiness checks local upload
prerequisites, not a paid AI invocation or an S3 write.

### Audited CLAHE result on the corridor reference

Independent before/after measurements against the existing S3 recovery artifact:

| Metric | Original reference | CLAHE output |
| :--- | ---: | ---: |
| Mean LAB luminance (`0–255`) | 31.163 | 62.715 |
| Canny edge density | 8.35026% | 13.87012% |
| Laplacian variance | 421.574 | 931.152 |

The historical relative Canny edge-density gain is approximately **+66.1%** for
this reference, using `(after / before - 1) * 100`. This audit measured the decoded
JPEG artifact; the new production fields measure the uncompressed enhanced image
and may differ. Production now returns the four post-recovery metrics documented
above. Gains are image-dependent; no universal **+142–184%** claim is supported.

---

## Local synthetic benchmark provenance

> **Generated by:** `python scripts/benchmark_opencv.py`
> **Timestamp:** `2026-10-17 02:07:43 UTC`
> **OpenCV Runtime:** `OpenCV 5.0.0` (`opencv-python-headless`)
> **Compute Architecture:** `x86_64 AVX2` (`AMD64`, SIMD flags: `FP16, AVX2, AVX, SSE4_2, SSE4_1, SSE3`)

The following measurements were generated on **local x86_64 AVX2**, not AWS
Lambda. The 166.08 ms best 1080p run below must not be presented as Graviton2
latency; its three-run mean is 260.9 ms.

---

## 1. Local Image Perception & Agentic Loop Latency (`analyze_image_cv`)

Each test case executes the full OpenCV 5.0 perception pipeline (`cv2.cvtColor` BGR->LAB/HSV, `cv2.calcHist` CDF percentiles, `cv2.kmeans` $K=5$ dominant palette, `cv2.Laplacian` focus variance, `cv2.Canny` + `cv2.moments` rule-of-thirds saliency, `cv2.HoughLinesP` structural geometry, and conditional `cv2.createCLAHE` shadow recovery), averaged over 3 runs. K-means initialization is randomized; exact cluster centers can vary between runs:

| Workload | Mean Latency (`ms`) | Best Latency (`ms`) | Effective Throughput (`FPS`) | Lighting Classification | Laplacian Sharpness | Saliency Region | Autonomous CLAHE Action |
| :--- | ---: | ---: | ---: | :--- | ---: | :--- | :--- |
| 1080p Standard Scene (`1920x1080`) | **260.9 ms** | 166.08 ms | **3.83 FPS** | `balanced` | `158.32` | `center-weighted` | Bypassed (optimal exposure) |
| 4K UHD High-Res Scene (`3840x2160`) | **555.62 ms** | 514.48 ms | **1.8 FPS** | `balanced` | `78.54` | `center-weighted` | Bypassed (optimal exposure) |
| 1080p Underexposed Low-Contrast (`1920x1080`) | **231.06 ms** | 207.86 ms | **4.33 FPS** | `low-contrast` | `20.06` | `center-weighted` | Active (`opencv_clahe_enhanced.jpg`) |

---

## 2. Local Video Dense Optical Flow & Keyframe Gating (`analyze_video_cv`)

Evaluated on a **30-frame 720p (`1280x720`)** synthetic motion sequence containing a continuous horizontal camera pan and **3 intentionally motion-blurred frames** (`frame_007.jpg`, `frame_016.jpg`, `frame_024.jpg`) to validate autonomous sharpness-gated keyframe ranking:

| Metric | Measured Value | OpenCV Operations Used |
| :--- | :--- | :--- |
| **Frames Analyzed** | `30 frames` (`1280x720`) | Sequential keyframe loader + downscaled optical-flow pyramid |
| **Total Pipeline Latency** | **`1429.36 ms`** (`47.65 ms/frame`) | Full video perception + optical flow + keyframe ranking |
| **Effective Video Throughput** | **`21.92 FPS`** | `frames_processed / (processing_ms / 1000)` |
| **Classified Camera Motion** | `pan-right` (`dx=0.902`, `dy=0.005`, `radial=0.012`) | `cv2.calcOpticalFlowFarneback` dense vector field decomposition |
| **Visual Continuity Score** | `0.997` (`continuous-shot`) | `cv2.compareHist(..., cv2.HISTCMP_CORREL)` across 2D H-S histograms |
| **Sharpest Ranked Keyframe** | `frame_003.jpg` (sharpness `243.5`) | Selected as primary reference for OpenCV telemetry used by Orb AI |
| **Motion-Blurred Frames Flagged** | `3 frames` (lowest: `frame_024.jpg` at `0.36`) | `cv2.Laplacian(gray, cv2.CV_64F).var() < 45.0` sharpness gate |

---

## 3. Local Synthetic CLAHE Shadow Recovery Measurements

When `analyze_image_cv()` or `analyze_video_cv()` perceives an underexposed (`mean_luminance < 60.0`) or compressed-contrast (`contrast_std < 32.0`) frame, the Agentic Vision Loop triggers `cv2.createCLAHE(clipLimit=2.5, tileGridSize=(8, 8))` on the LAB luminance channel (`L`). Orb AI can use both the original and recovered frame alongside pixel-derived telemetry. The historical local benchmark below measured the decoded JPEG output. Its figures differ from the new pre-JPEG production measurements above:

| Visual Quality Metric | Original Underexposed Input | After OpenCV CLAHE Recovery | Measured Delta / Gain |
| :--- | ---: | ---: | :--- |
| **Mean Luminance (`0–255`)** | `21.07` | **`25.8`** | **+22.4% luminance recovery** |
| **Contrast Std Dev (`σ`)** | `8.53` | **`9.95`** | **+16.6% local contrast expansion** |
| **Dynamic Range (`p95 - p5 %`)** | `11.4%` | **`14.1%`** | **+2.7 percentage points** |
| **Laplacian Focus Sharpness** | `20.06` | **`28.61`** | **+42.6% micro-edge definition** |
| **Canny Edge Density (`%`)** | `0.96%` | **`1.09%`** | Recovered shadow structural geometry |

---

## 4. Reproducing the Synthetic Benchmarks

Run on the target machine with the pinned dependencies installed. To print a
fresh synthetic report while preserving the audited observations in this file:

```bash
python -c "from scripts.benchmark_opencv import run_benchmarks; print(run_benchmarks(iterations=3))"
```

The original command below **replaces `BENCHMARKS.md`** with a newly generated
synthetic report. Preserve or re-document the independently verified AWS section
when using it:

```bash
python scripts/benchmark_opencv.py
```

A local run, including one labeled with `ORB_COMPUTE_ENV=AWS`, is not evidence
of Lambda execution. A new Graviton benchmark must record its actual AWS runtime,
package version, memory, input dimensions, sample count and timing scope. Local
benchmark fixtures do not make network calls to the deployed Lambda.
