# Orb — OpenCV AI Competition 2026 (Powered by AWS) Technical Report & Submission Guide

**Orb** is a visual intelligence and creative prompt engineering platform that decodes images and videos into structured cinematic breakdowns and production-ready generation prompts (`Decode`, `Compose`, and `Enhance`).

Built for the **OpenCV AI Competition 2026 (Powered by AWS)**, Orb pairs a deterministic **OpenCV 5.0 Agentic Vision Engine** (`opencv-python-headless==5.0.0.93`) running on **AWS Graviton (Arm64 NEON / x86_64 AVX2)** with **Google Gemini VLM** synthesis—eliminating vision-language model hallucinations by grounding every prompt in physical pixel measurements and executing autonomous pre-inference visual recovery actions.

---

## 1. System Architecture (`Vercel -> AWS Graviton / Amazon S3 + OpenCV 5.0 -> Gemini VLM`)

```mermaid
flowchart TB
    subgraph Client["Frontend — Vercel Edge (orb-azure-ten.vercel.app)"]
        UI["Liquid-Glass Web UI\n(Decode · Compose · Enhance)"]
        GateUI["Access Gate\n• Arbitrum Sepolia Wallet (ETH / USDG)\n• Zero-Friction Judge Demo (?judge=OPENCV2026)"]
        TelemetryUI["OpenCV 5.0 Agentic Telemetry Card\n• Compute, AWS S3 & Latency/FPS Badges\n• Perception → Decision → Action Trace\n• Vision HUD & CLAHE Preview Switcher\n• k-Means Swatches & Optical Flow Metrics"]
    end

    subgraph AWS["AWS Cloud — EC2 Graviton2 (Arm64) + Amazon S3 Telemetry & Artifact Store"]
        API["FastAPI Backend (prometheus/api/app.py)\nuvicorn :8000 · CreditService + Rate Limiter"]
        FFmpeg["FFmpeg / OpenCV 5.0 Native Video Pipeline\n(probe + scene cut detector + frame sampler)"]
        S3["Amazon S3 Artifact Store (prometheus/storage/aws_s3.py)\ns3://<ORB_AWS_S3_BUCKET>/jobs/<job_id>/\n• opencv_hud_overlay.jpg\n• opencv_clahe_enhanced.jpg\n• opencv_telemetry.json"]

        subgraph AgenticCV["OpenCV 5.0 Agentic Vision Engine (prometheus/analysis/opencv_telemetry.py)"]
            Perceive["1. PERCEPTION\n• LAB/HSV Histograms (cv2.cvtColor, cv2.calcHist)\n• Dominant Palette k=5 (cv2.kmeans)\n• Focus Sharpness (cv2.Laplacian)\n• Rule-of-Thirds Saliency (cv2.Canny, cv2.moments)\n• Structural Geometry (cv2.HoughLinesP)\n• Dense Optical Flow (cv2.calcOpticalFlowFarneback)\n• Shot Continuity (cv2.compareHist)"]
            Decide["2. DECISION\n• Underexposed / Low-Contrast Gate\n  (mean_luminance < 60 or contrast_std < 32)\n• Motion-Blur Keyframe Gate\n  (Laplacian variance < 45.0)\n• Deterministic Telemetry Grounding"]
            Act["3. ACTION\n• Autonomous LAB L-Channel CLAHE Recovery\n  (cv2.createCLAHE → opencv_clahe_enhanced.jpg)\n• OpenCV 5.0 Vision HUD Diagnostic Overlay\n  (opencv_hud_overlay.jpg)\n• Sharpness-Gated Keyframe Ranking & Filtering\n• Inject cv_grounding_brief into VLM Context"]
            Perceive --> Decide --> Act
        end
    end

    subgraph External["External Services"]
        Gemini["Google Gemini Flash VLM\n(Structured JSON Visual Synthesis)"]
        Arb["Arbitrum Sepolia RPC\n(On-Chain ETH / Paxos USDG Verification)"]
    end

    UI -->|"HTTPS (/api/orb/* via VITE_API_BASE_URL)"| API
    GateUI -->|"POST /api/orb/judge-session or Bearer Token"| API
    API -->|"Verify On-Chain Tx"| Arb
    API --> FFmpeg --> Perceive
    Act -->|"Sync HUD, CLAHE & Telemetry JSON"| S3
    Act -->|"Original + CLAHE Frame + OpenCV Grounding Brief"| Gemini
    Gemini -->|"orb_result.json + opencv_telemetry"| API
    API -->|"JSON Result + Vision HUD & CLAHE Previews"| TelemetryUI
```

---

## 2. Agentic Vision Loop (`Perception -> Decision -> Action`)

Pure VLM pipelines frequently hallucinate lighting keys, color hex codes, camera motion directions, or miss shadow detail in dark scenes. Orb solves this with a closed **Perception $\rightarrow$ Decision $\rightarrow$ Action** loop powered by **OpenCV 5.0** before Gemini ever sees the media:

### Step 1: Deterministic OpenCV 5.0 Perception
- **Photometric & Color Perception (`cv2.cvtColor`, `cv2.calcHist`, `cv2.kmeans`):**
  Converts BGR frames into CIE **LAB** and **HSV** color spaces, computes cumulative histogram percentiles (`p5` to `p95` dynamic range), `mean_luminance` ($0\text{--}255$), and `contrast_std` ($\sigma$), and runs $K$-means clustering ($K=5$, `cv2.KMEANS_PP_CENTERS`) to extract exact dominant RGB Hex codes and pixel weights.
- **Focus & Compositional Geometry (`cv2.Laplacian`, `cv2.Canny`, `cv2.moments`, `cv2.HoughLinesP`):**
  Measures high-frequency focus variance via $\text{Var}(\nabla^2 I)$, computes spatial edge center-of-mass relative to Rule-of-Thirds power points via `cv2.Canny` + `cv2.moments`, and classifies structural line orientation (`horizontal-dominant`, `vertical-dominant`, `diagonal/dynamic`, `organic/curved`) via probabilistic Hough transforms (`cv2.HoughLinesP`).
- **Temporal Motion & Shot Continuity (`cv2.calcOpticalFlowFarneback`, `cv2.compareHist`):**
  Computes dense Farnebäck optical flow across video frames, decomposing 2D motion fields into horizontal pan (`mean_dx`), vertical tilt (`mean_dy`), and radial zoom (`radial_flow` via dot product with unit radial vectors), while correlating 2D Hue-Saturation histograms (`cv2.HISTCMP_CORREL`) to detect cuts vs. continuous takes.

### Step 2: Autonomous Agentic Decisions & Actions
1. **Autonomous CLAHE Shadow & Contrast Recovery (`clahe_shadow_contrast_recovery`):**
   - **Perception Trigger:** `mean_luminance < 60.0` or `contrast_std < 32.0`.
   - **Autonomous Action:** Applies Contrast-Limited Adaptive Histogram Equalization (`cv2.createCLAHE(clipLimit=2.5, tileGridSize=(8, 8))`) specifically to the LAB luminance channel (`L`) so chrominance (`A`, `B`) remains uncorrupted. Writes `opencv_clahe_enhanced.jpg` to the job directory, exposes `/api/jobs/{id}/frames/opencv_clahe_enhanced.jpg` to the UI, and attaches **both** the original reference and the CLAHE-recovered image to the Gemini VLM call so shadow structures are recovered without losing the original mood.
2. **Sharpness-Gated Keyframe Prioritization (`sharpness_gated_keyframe_ranking`):**
   - **Perception Trigger:** Video frames scored via `cv2.Laplacian(gray, cv2.CV_64F).var()`. Frames below `45.0` are flagged as `flagged-blurry`.
   - **Autonomous Action:** Ranks all candidate keyframes by focus sharpness, selects the sharpest keyframe for primary photometric/geometric telemetry, and logs the full sharpness ranking so motion-blurred transition frames do not degrade VLM synthesis.
3. **Deterministic Prompt Grounding (`cv_grounding_brief`):**
   - **Autonomous Action:** Compiles all OpenCV 5.0 measurements into a `[OpenCV Deterministic Telemetry — Ground your analysis in these physical measurements]` block injected directly into `OrbAIService.image()`, `OrbAIService.compose_video()`, and `_BaseRemoteAnalyzer._user_instruction()`.

---

## 3. Zero-Friction Competition Judge Demo Mode

To ensure competition judges can test the live deployment immediately without needing an Arbitrum Sepolia wallet or testnet ETH/USDG, while keeping our Gemini API quota 100% protected against automated scraping:

- **One-Click URL Auto-Unlock:** Opening `https://orb-azure-ten.vercel.app/?judge=OPENCV2026` (or `http://127.0.0.1:8000/?judge=OPENCV2026` locally) automatically exchanges the competition code via `POST /api/orb/judge-session`, mints a server-verified session pre-loaded with **10 demo credits**, and strips `?judge=...` from the address bar via `history.replaceState`.
- **Header Button Unlock:** Judges can also click **`Judge Demo`** in the top-right header, enter `OPENCV2026`, and unlock 10 credits immediately.
- **Server-Side Quota Protection:** Verified with constant-time `hmac.compare_digest`, bounded by `ORB_JUDGE_DAILY_CAP=150` runs/day globally and `ORB_JUDGE_IP_DAILY_LIMIT` per-IP session limits.

---

## 4. How to Preview Locally Right Now

Run the full Orb stack (FastAPI backend + OpenCV 5.0 Agentic Engine + Web UI) locally on port `8000`:

```powershell
# 1. Set Judge Demo Mode & local environment variables in PowerShell
$env:ORB_ENV = "local"
$env:ORB_JUDGE_DEMO_CODE = "OPENCV2026"
$env:ORB_JUDGE_DAILY_CAP = "150"
$env:ORB_COMPUTE_ENV = "AWS"
# Ensure GEMINI_API_KEY is set in your environment:
# $env:GEMINI_API_KEY = "your_gemini_api_key"

# 2. Launch the FastAPI + OpenCV 5.0 server
.\.venv\Scripts\python.exe -m uvicorn prometheus.api.app:app --host 127.0.0.1 --port 8000
```

Then open **`http://127.0.0.1:8000/?judge=OPENCV2026`** in your browser:
1. The header badge will automatically activate **`Judge Demo · 10 cr`**.
2. Upload any image or video in **Decode** or **Compose** mode (try a dark/low-contrast photo to watch Autonomous CLAHE Shadow Recovery trigger!).
3. On the Results screen, inspect the **OpenCV 5.0 Agentic Vision Telemetry** card:
   - Benchmark pills (`OpenCV 5.0.0 · ...`, `Latency: <ms>`, `Throughput: <FPS>`, `CLAHE Auto-Recovery: Active`).
   - Step-by-step **Perception $\rightarrow$ Decision $\rightarrow$ Action** log and interactive **"View OpenCV CLAHE Shadow Recovery"** preview toggle.
   - 5-color $K$-means Hex palette swatches and full CV measurement breakdown.

---

## 5. AWS Integration: Amazon S3 Telemetry Store + AWS Lambda / Graviton2 (`arm64`)

### Component A: Amazon S3 OpenCV 5.0 Artifact Store & Pre-Signed URLs (`prometheus/storage/aws_s3.py`)
Every visual job (`Decode` and `Compose`) generates deterministic OpenCV 5.0 diagnostic artifacts (`opencv_hud_overlay.jpg`, `opencv_clahe_enhanced.jpg`, and `opencv_telemetry.json`). When `ORB_AWS_S3_BUCKET` and AWS credentials (`AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`, `AWS_REGION`) are configured in the backend environment, `sync_job_artifacts_to_s3()` automatically uploads these artifacts with a 4-second timeout to:
- `s3://<ORB_AWS_S3_BUCKET>/orb-jobs/<job_id>/opencv_hud_overlay.jpg`
- `s3://<ORB_AWS_S3_BUCKET>/orb-jobs/<job_id>/opencv_clahe_enhanced.jpg`
- `s3://<ORB_AWS_S3_BUCKET>/orb-jobs/<job_id>/opencv_telemetry.json`

It generates 24-hour pre-signed S3 URLs (`hud_s3_url`, `clahe_s3_url`), attaches `opencv_telemetry["aws_s3"]`, and renders the **`AWS S3 Cloud Synced (<bucket>)`** pill badge in the OpenCV 5.0 Agentic Telemetry card.

### Component B: Serverless AWS Lambda (`arm64` Graviton) via `Mangum`
`prometheus/api/app.py` exposes `handler = Mangum(app, lifespan="auto")`, allowing the exact same FastAPI + OpenCV 5.0 container to run on **AWS Lambda (Arm64 Graviton2)** with a built-in HTTPS Function URL—bypassing EC2 vCPU limits completely.

### Component C: Launching on AWS EC2 Graviton2 (`arm64`) with Automatic Cloudflared HTTPS Tunnel
1. In the AWS Console, launch an **Ubuntu Server 24.04 LTS (HVM), SSD Volume Type — 64-bit (Arm)** instance (`t4g.small` or `t4g.micro`).
2. SSH into the instance, clone the repository, and run the automated setup script (which launches both `orb-api` and a zero-cost `cloudflared` `https://*.trycloudflare.com` HTTPS tunnel sidecar):

```bash
git clone <your-repo-url> project-orb
cd project-orb
chmod +x deploy/aws_graviton_setup.sh
./deploy/aws_graviton_setup.sh
```

3. Add your `GEMINI_API_KEY` (and `ORB_AWS_S3_BUCKET`, `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`, `AWS_REGION`) to `.env` and restart the container:

```bash
nano .env
sudo docker compose -f docker-compose.aws.yml up -d
```

### Component D: Point `orb-azure-ten.vercel.app` to the Backend
1. Open **Vercel Dashboard $\rightarrow$ Project (`orb`) $\rightarrow$ Settings $\rightarrow$ Environment Variables**.
2. Set **`VITE_API_BASE_URL`** to your HTTPS API origin (Render + AWS S3, AWS Lambda Function URL, or AWS Graviton `https://*.trycloudflare.com` tunnel URL).
3. Share the zero-friction judge link in your competition submission form:
   **`https://orb-azure-ten.vercel.app/?judge=OPENCV2026`**


