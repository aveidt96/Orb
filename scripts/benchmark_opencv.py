"""Reproducible OpenCV 5.0 Agentic Vision Benchmark & Evaluation Suite.

Runs deterministic benchmarks across:
1. 1080p Standard Reference Image (1920x1080)
2. 4K UHD Reference Image (3840x2160)
3. 1080p Underexposed Low-Contrast Image (triggers autonomous CLAHE recovery)
4. 30-Frame 720p Motion Video Sequence (1280x720, Farnebäck dense optical flow,
   HSV histogram continuity, and Laplacian sharpness-gated keyframe ranking)

Writes measured latency, throughput (FPS), and before/after CLAHE quality gains
to BENCHMARKS.md in the repository root.
"""

from __future__ import annotations

import statistics
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from prometheus.analysis.opencv_telemetry import (
    _color_and_lighting_metrics,
    _read_bgr,
    _sharpness_and_geometry_metrics,
    analyze_image_cv,
    analyze_video_cv,
    detect_compute_runtime,
)


def _make_standard_image(width: int, height: int) -> np.ndarray:
    """Create a synthetic balanced-exposure scene with rule-of-thirds geometry."""
    x = np.linspace(15, 245, width, dtype=np.float32)
    y = np.linspace(10, 240, height, dtype=np.float32)
    xv, yv = np.meshgrid(x, y)
    b = np.clip(xv, 0, 255).astype(np.uint8)
    g = np.clip(yv, 0, 255).astype(np.uint8)
    r = np.clip(255.0 - xv * 0.7, 0, 255).astype(np.uint8)
    canvas = cv2.merge([b, g, r])

    # High-contrast architectural bands + rule-of-thirds focal elements
    canvas[: height // 4, :] = (24, 28, 36)
    canvas[height * 3 // 4 :, :] = (235, 238, 244)
    third_x, third_y = width // 3, height // 3
    cv2.rectangle(
        canvas,
        (third_x - width // 12, third_y - height // 10),
        (third_x + width // 6, third_y + height // 5),
        (20, 185, 250),
        thickness=-1,
    )
    cv2.circle(canvas, (2 * third_x, third_y), min(width, height) // 9, (240, 55, 85), thickness=-1)
    for offset in range(5):
        y_line = int(height * (0.45 + offset * 0.06))
        cv2.line(canvas, (width // 10, y_line), (width * 9 // 10, y_line), (250, 245, 235), thickness=3)
    return canvas


def _make_underexposed_image(width: int, height: int) -> np.ndarray:
    """Create a dark, low-contrast 1080p scene that triggers autonomous CLAHE recovery."""
    canvas = np.full((height, width, 3), 22, dtype=np.uint8)
    third_x, third_y = width // 3, height // 3
    cv2.rectangle(
        canvas,
        (third_x - 160, third_y - 120),
        (third_x + 280, third_y + 220),
        (44, 38, 34),
        thickness=-1,
    )
    cv2.circle(canvas, (2 * third_x, 2 * third_y), 150, (52, 46, 40), thickness=-1)
    for i in range(8):
        y_line = 180 + i * 95
        cv2.line(canvas, (140, y_line), (width - 140, y_line), (58, 52, 48), thickness=2)
    return canvas


def _make_720p_video_frames(out_dir: Path, num_frames: int = 30) -> list[Path]:
    """Generate 30 frames of 1280x720 video with steady horizontal pan + 3 blurry frames."""
    width, height = 1280, 720
    frame_paths: list[Path] = []
    blurred_indices = {7, 16, 24}

    for idx in range(num_frames):
        canvas = np.full((height, width, 3), 38, dtype=np.uint8)
        shift_x = idx * 12
        # Moving foreground subject and vertical/horizontal architectural grid
        for col in range(4):
            x0 = (120 + col * 240 + shift_x) % (width - 140)
            cv2.rectangle(canvas, (x0, 140), (x0 + 90, 560), (215, 165, 75), thickness=-1)
            cv2.rectangle(canvas, (x0 + 14, 170), (x0 + 76, 530), (45, 85, 205), thickness=3)
        cv2.line(canvas, (0, 360), (width, 360), (190, 210, 225), thickness=2)

        if idx in blurred_indices:
            canvas = cv2.GaussianBlur(canvas, (31, 31), 11.0)

        path = out_dir / f"frame_{idx:03d}.jpg"
        cv2.imwrite(str(path), canvas, [int(cv2.IMWRITE_JPEG_QUALITY), 92])
        frame_paths.append(path)
    return frame_paths


def run_benchmarks(iterations: int = 3) -> str:
    runtime = detect_compute_runtime()
    with tempfile.TemporaryDirectory() as tmp:
        tmp_dir = Path(tmp)

        std_1080p_path = tmp_dir / "std_1080p.jpg"
        cv2.imwrite(str(std_1080p_path), _make_standard_image(1920, 1080))

        uhd_4k_path = tmp_dir / "uhd_4k.jpg"
        cv2.imwrite(str(uhd_4k_path), _make_standard_image(3840, 2160))

        dark_1080p_path = tmp_dir / "dark_1080p.jpg"
        cv2.imwrite(str(dark_1080p_path), _make_underexposed_image(1920, 1080))

        cases = [
            ("1080p Standard Scene (`1920x1080`)", std_1080p_path),
            ("4K UHD High-Res Scene (`3840x2160`)", uhd_4k_path),
            ("1080p Underexposed Low-Contrast (`1920x1080`)", dark_1080p_path),
        ]

        image_rows = []
        clahe_delta = {}

        for label, path in cases:
            latencies = []
            last_telemetry = None
            run_out = tmp_dir / f"out_{path.stem}"
            for _ in range(iterations):
                tel = analyze_image_cv(path, output_dir=run_out)
                latencies.append(tel.processing_ms)
                last_telemetry = tel

            mean_ms = statistics.mean(latencies)
            eff_fps = 1000.0 / max(0.001, mean_ms)
            payload = last_telemetry.to_dict()
            cl = payload["color_and_lighting"]
            sg = payload["sharpness_and_geometry"]
            image_rows.append({
                "label": label,
                "mean_ms": round(mean_ms, 2),
                "min_ms": round(min(latencies), 2),
                "fps": round(eff_fps, 2),
                "lighting_key": cl["lighting_key"],
                "sharpness": sg["laplacian_sharpness"],
                "saliency": sg["saliency_region"],
                "clahe": "Active (`opencv_clahe_enhanced.jpg`)" if payload["clahe_applied"] else "Bypassed (optimal exposure)",
            })

            if payload["clahe_applied"] and last_telemetry.clahe_enhanced_path:
                orig_bgr = _read_bgr(path)
                enh_bgr = _read_bgr(last_telemetry.clahe_enhanced_path)
                orig_cl = _color_and_lighting_metrics(orig_bgr)
                enh_cl = _color_and_lighting_metrics(enh_bgr)
                orig_sg = _sharpness_and_geometry_metrics(orig_bgr)
                enh_sg = _sharpness_and_geometry_metrics(enh_bgr)
                clahe_delta = {
                    "before_lum": orig_cl["mean_luminance"],
                    "after_lum": enh_cl["mean_luminance"],
                    "before_std": orig_cl["contrast_std"],
                    "after_std": enh_cl["contrast_std"],
                    "before_dr": orig_cl["dynamic_range_pct"],
                    "after_dr": enh_cl["dynamic_range_pct"],
                    "before_sharp": orig_sg["laplacian_sharpness"],
                    "after_sharp": enh_sg["laplacian_sharpness"],
                    "before_edges": orig_sg["edge_density_pct"],
                    "after_edges": enh_sg["edge_density_pct"],
                }

        # Video 30-frame 720p benchmark
        frames_dir = tmp_dir / "video_720p_frames"
        frames_dir.mkdir(parents=True, exist_ok=True)
        frame_paths = _make_720p_video_frames(frames_dir, num_frames=30)

        vid_latencies = []
        vid_fps_list = []
        vid_payload = None
        for _ in range(iterations):
            vtel = analyze_video_cv(None, frame_paths, output_dir=tmp_dir / "vid_out")
            vid_latencies.append(vtel.processing_ms)
            vp = vtel.to_dict()
            vid_fps_list.append(vp["motion_and_continuity"]["effective_fps"])
            vid_payload = vp

        vid_mean_ms = round(statistics.mean(vid_latencies), 2)
        vid_mean_fps = round(statistics.mean(vid_fps_list), 2)
        mc = vid_payload["motion_and_continuity"]
        ranking = mc.get("keyframe_ranking", [])
        top_frame = ranking[0] if ranking else {"file": "n/a", "sharpness": 0.0}
        bottom_frame = ranking[-1] if ranking else {"file": "n/a", "sharpness": 0.0}

    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    lum_gain_pct = round(
        ((clahe_delta["after_lum"] - clahe_delta["before_lum"]) / max(1.0, clahe_delta["before_lum"])) * 100.0, 1
    )
    std_gain_pct = round(
        ((clahe_delta["after_std"] - clahe_delta["before_std"]) / max(1.0, clahe_delta["before_std"])) * 100.0, 1
    )
    dr_gain_pct = round(clahe_delta["after_dr"] - clahe_delta["before_dr"], 2)
    sharp_gain_pct = round(
        ((clahe_delta["after_sharp"] - clahe_delta["before_sharp"]) / max(1.0, clahe_delta["before_sharp"])) * 100.0, 1
    )

    md = f"""# OpenCV 5.0 Agentic Vision Engine — Reproducible Benchmarks

> **Generated by:** `python scripts/benchmark_opencv.py`
> **Timestamp:** `{timestamp}`
> **OpenCV Runtime:** `OpenCV {cv2.__version__}` (`opencv-python-headless`)
> **Compute Architecture:** `{runtime["compute_badge"]}` (`{runtime["raw_machine"]}`, SIMD flags: `{", ".join(runtime["simd_flags"]) or "baseline"}`)

---

## 1. Image Perception & Agentic Loop Latency (`analyze_image_cv`)

Each test case executes the full deterministic OpenCV 5.0 perception pipeline (`cv2.cvtColor` BGR->LAB/HSV, `cv2.calcHist` CDF percentiles, `cv2.kmeans` $K=5$ dominant palette, `cv2.Laplacian` focus variance, `cv2.Canny` + `cv2.moments` rule-of-thirds saliency, `cv2.HoughLinesP` structural geometry, and conditional `cv2.createCLAHE` shadow recovery), averaged over {iterations} runs:

| Workload | Mean Latency (`ms`) | Best Latency (`ms`) | Effective Throughput (`FPS`) | Lighting Classification | Laplacian Sharpness | Saliency Region | Autonomous CLAHE Action |
| :--- | ---: | ---: | ---: | :--- | ---: | :--- | :--- |
"""
    for row in image_rows:
        md += (
            f"| {row['label']} | **{row['mean_ms']} ms** | {row['min_ms']} ms | "
            f"**{row['fps']} FPS** | `{row['lighting_key']}` | `{row['sharpness']}` | "
            f"`{row['saliency']}` | {row['clahe']} |\n"
        )

    md += f"""
---

## 2. Video Dense Optical Flow & Keyframe Gating (`analyze_video_cv`)

Evaluated on a **30-frame 720p (`1280x720`)** synthetic motion sequence containing a continuous horizontal camera pan and **3 intentionally motion-blurred frames** (`frame_007.jpg`, `frame_016.jpg`, `frame_024.jpg`) to validate autonomous sharpness-gated keyframe ranking:

| Metric | Measured Value | OpenCV Operations Used |
| :--- | :--- | :--- |
| **Frames Analyzed** | `{mc["frames_processed"]} frames` (`1280x720`) | Sequential keyframe loader + downscaled optical-flow pyramid |
| **Total Pipeline Latency** | **`{vid_mean_ms} ms`** (`{round(vid_mean_ms / mc["frames_processed"], 2)} ms/frame`) | Full video perception + optical flow + keyframe ranking |
| **Effective Video Throughput** | **`{vid_mean_fps} FPS`** | `frames_processed / (processing_ms / 1000)` |
| **Classified Camera Motion** | `{mc["dominant_motion"]}` (`dx={mc["mean_dx"]}`, `dy={mc["mean_dy"]}`, `radial={mc["radial_flow"]}`) | `cv2.calcOpticalFlowFarneback` dense vector field decomposition |
| **Visual Continuity Score** | `{mc["mean_hist_correlation"]}` (`{mc["continuity_class"]}`) | `cv2.compareHist(..., cv2.HISTCMP_CORREL)` across 2D H-S histograms |
| **Sharpest Ranked Keyframe** | `{top_frame["file"]}` (sharpness `{top_frame["sharpness"]}`) | Selected as primary reference frame for Gemini VLM synthesis |
| **Motion-Blurred Frames Filtered** | `{mc["blurry_frame_count"]} frames` (lowest: `{bottom_frame["file"]}` at `{bottom_frame["sharpness"]}`) | `cv2.Laplacian(gray, cv2.CV_64F).var() < 45.0` sharpness gate |

---

## 3. Measurable Impact of Autonomous CLAHE Shadow Recovery

When `analyze_image_cv()` or `analyze_video_cv()` perceives an underexposed (`mean_luminance < 60.0`) or compressed-contrast (`contrast_std < 32.0`) frame, the Agentic Vision Loop triggers `cv2.createCLAHE(clipLimit=2.5, tileGridSize=(8, 8))` on the LAB luminance channel (`L`) and supplies both the original and recovered frame to Gemini alongside deterministic telemetry:

| Visual Quality Metric | Original Underexposed Input | After OpenCV CLAHE Recovery | Measured Delta / Gain |
| :--- | ---: | ---: | :--- |
| **Mean Luminance (`0–255`)** | `{clahe_delta["before_lum"]}` | **`{clahe_delta["after_lum"]}`** | **+{lum_gain_pct}% luminance recovery** |
| **Contrast Std Dev (`σ`)** | `{clahe_delta["before_std"]}` | **`{clahe_delta["after_std"]}`** | **+{std_gain_pct}% local contrast expansion** |
| **Dynamic Range (`p95 - p5 %`)** | `{clahe_delta["before_dr"]}%` | **`{clahe_delta["after_dr"]}%`** | **+{dr_gain_pct} percentage points** |
| **Laplacian Focus Sharpness** | `{clahe_delta["before_sharp"]}` | **`{clahe_delta["after_sharp"]}`** | **+{sharp_gain_pct}% micro-edge definition** |
| **Canny Edge Density (`%`)** | `{clahe_delta["before_edges"]}%` | **`{clahe_delta["after_edges"]}%`** | Recovered shadow structural geometry |

---

## 4. Reproducing These Benchmarks Locally or on AWS Graviton

```bash
python scripts/benchmark_opencv.py
```
"""
    return md


def main() -> None:
    report_md = run_benchmarks(iterations=3)
    out_path = ROOT / "BENCHMARKS.md"
    out_path.write_text(report_md, encoding="utf-8")
    print(f"Wrote benchmark report to {out_path}")


if __name__ == "__main__":
    main()
