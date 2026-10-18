"""OpenCV Agentic Vision Engine (Perception -> Decision -> Action) for Orb.

Provides deterministic computer-vision perception (LAB/HSV color & luminance
histograms, k-means dominant hex palette, Laplacian focus sharpness, Canny
rule-of-thirds edge saliency, probabilistic Hough structural geometry, and
Farnebäck dense optical flow + HSV histogram continuity) coupled with an
autonomous decision/action loop:
1. Autonomous CLAHE shadow & low-contrast recovery (`opencv_clahe_enhanced.jpg`).
2. Sharpness-gated keyframe ranking & blur filtering for video synthesis.
3. Deterministic OpenCV grounding brief injected into Gemini multimodal prompts.

Compatible with OpenCV 4.x and OpenCV 5.x (including AWS Graviton / COOL builds).
"""

from __future__ import annotations

import functools
import math
import os
import platform
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import cv2
import numpy as np


CLAHE_LUMINANCE_THRESHOLD = 60.0
CLAHE_CONTRAST_THRESHOLD = 32.0
BLUR_SHARPNESS_THRESHOLD = 45.0


from prometheus.storage.aws_s3 import build_aws_integration_metadata


@functools.lru_cache(maxsize=1)
def _cached_cv_build_info() -> str:
    try:
        return cv2.getBuildInformation() or ""
    except Exception:
        return ""


def detect_compute_runtime() -> dict[str, Any]:
    """Detect CPU architecture and OpenCV SIMD acceleration flags (NEON / AVX2 / etc.)."""
    raw_machine = (platform.machine() or "unknown").strip()
    lowered = raw_machine.lower()
    if lowered in {"aarch64", "arm64"} or lowered.startswith("arm"):
        arch = "ARM64"
    elif lowered in {"x86_64", "amd64", "x64"}:
        arch = "x86_64"
    else:
        arch = raw_machine or "CPU"

    build_info = _cached_cv_build_info()

    cpu_section = ""
    match = re.search(
        r"CPU/HW features:\s*(.*?)(?:\n\n|\n[A-Z][A-Za-z0-9 _/-]+:)",
        build_info,
        flags=re.DOTALL,
    )
    if match:
        cpu_section = match.group(1)
    else:
        cpu_section = build_info

    candidate_flags = ["NEON", "FP16", "DOTPROD", "AVX512", "AVX2", "AVX", "SSE4_2", "SSE4_1", "SSE3"]
    detected_flags: list[str] = []
    for token in candidate_flags:
        if re.search(rf"\b{re.escape(token)}\b", cpu_section, flags=re.IGNORECASE):
            detected_flags.append(token)

    if arch == "ARM64":
        primary_simd = "NEON" if "NEON" in detected_flags or not detected_flags else detected_flags[0]
        if "NEON" not in detected_flags:
            detected_flags.insert(0, "NEON")
    else:
        if "AVX2" in detected_flags:
            primary_simd = "AVX2"
        elif "AVX512" in detected_flags:
            primary_simd = "AVX512"
        elif detected_flags:
            primary_simd = detected_flags[0]
        else:
            primary_simd = ""

    s3_bucket = (
        os.environ.get("ORB_AWS_S3_BUCKET", "").strip()
        or os.environ.get("AWS_S3_BUCKET", "").strip()
    )
    cloud_env = os.environ.get("ORB_COMPUTE_ENV", "").strip()
    if not cloud_env and (os.environ.get("AWS_EXECUTION_ENV") or s3_bucket):
        cloud_env = "AWS"
    if s3_bucket and "S3" not in cloud_env.upper():
        cloud_env = f"{cloud_env} S3".strip() if cloud_env else "AWS S3"

    badge_parts = [p for p in [arch, primary_simd] if p]
    compute_badge = " ".join(badge_parts)
    if cloud_env:
        compute_badge = f"{cloud_env} · {compute_badge}".strip(" ·") if s3_bucket else f"{cloud_env} {compute_badge}".strip()

    return {
        "arch": arch,
        "raw_machine": raw_machine,
        "simd_flags": detected_flags,
        "primary_simd": primary_simd,
        "compute_badge": compute_badge,
    }


@dataclass
class OpenCVTelemetry:
    opencv_version: str
    media_kind: str
    processing_ms: float
    color_and_lighting: dict[str, Any]
    sharpness_and_geometry: dict[str, Any]
    motion_and_continuity: dict[str, Any] = field(default_factory=dict)
    agentic_actions: list[dict[str, Any]] = field(default_factory=list)
    cv_grounding_brief: str = ""
    clahe_enhanced_path: Path | None = None
    hud_overlay_path: Path | None = None
    aws_integration: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        fps = (
            self.motion_and_continuity.get("effective_fps")
            if self.motion_and_continuity
            else round(1000.0 / max(0.001, self.processing_ms), 2)
        )
        clahe_active = self.clahe_enhanced_path is not None
        runtime = detect_compute_runtime()
        default_artifacts: list[str] = []
        if self.hud_overlay_path is not None:
            default_artifacts.append(self.hud_overlay_path.name)
        if self.clahe_enhanced_path is not None:
            default_artifacts.append(self.clahe_enhanced_path.name)
        default_artifacts.append("opencv_telemetry.json")
        aws_meta = self.aws_integration or build_aws_integration_metadata(
            default_artifacts if os.environ.get("ORB_AWS_S3_BUCKET", "").strip() else []
        )
        payload: dict[str, Any] = {
            "opencv_version": self.opencv_version,
            "compute_arch": runtime["arch"],
            "compute_badge": runtime["compute_badge"],
            "compute_runtime": runtime,
            "aws_integration": aws_meta,
            "media_kind": self.media_kind,
            "processing_ms": round(self.processing_ms, 3),
            "effective_fps": fps,
            "color_and_lighting": self.color_and_lighting,
            "sharpness_and_geometry": self.sharpness_and_geometry,
            "motion_and_continuity": self.motion_and_continuity,
            "agentic_actions": self.agentic_actions,
            "agentic_decisions": self.agentic_actions,
            "cv_grounding_brief": self.cv_grounding_brief,
            "clahe_triggered": clahe_active,
            "clahe_applied": clahe_active,
        }
        if self.clahe_enhanced_path is not None:
            payload["clahe_artifact"] = self.clahe_enhanced_path.name
        if self.hud_overlay_path is not None:
            payload["hud_artifact"] = self.hud_overlay_path.name
        return payload


def _read_bgr(image_path: Path) -> np.ndarray:
    img = cv2.imread(str(image_path), cv2.IMREAD_COLOR)
    if img is not None:
        return img
    raw = np.frombuffer(Path(image_path).read_bytes(), dtype=np.uint8)
    decoded = cv2.imdecode(raw, cv2.IMREAD_COLOR)
    if decoded is None:
        raise ValueError(f"OpenCV could not decode image: {image_path}")
    return decoded


def _dominant_hex_colors(bgr: np.ndarray, k: int = 5) -> list[dict[str, Any]]:
    rgb = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)
    h, w = rgb.shape[:2]
    max_dim = 96
    if max(h, w) > max_dim:
        scale = max_dim / float(max(h, w))
        rgb = cv2.resize(
            rgb,
            (max(1, int(round(w * scale))), max(1, int(round(h * scale)))),
            interpolation=cv2.INTER_AREA,
        )
    pixels = rgb.reshape((-1, 3)).astype(np.float32)
    unique_pixels = np.unique(pixels, axis=0)
    clusters = max(1, min(k, len(unique_pixels)))
    if clusters == 1:
        center = unique_pixels[0].astype(int)
        hex_code = f"#{int(center[0]):02x}{int(center[1]):02x}{int(center[2]):02x}"
        return [{"hex": hex_code, "rgb": [int(center[0]), int(center[1]), int(center[2])], "weight_pct": 100.0}]

    criteria = (cv2.TERM_CRITERIA_EPS + cv2.TERM_CRITERIA_MAX_ITER, 20, 1.0)
    _, labels, centers = cv2.kmeans(
        pixels, clusters, None, criteria, 3, cv2.KMEANS_PP_CENTERS
    )
    counts = np.bincount(labels.flatten(), minlength=clusters)
    total = float(counts.sum()) or 1.0
    order = np.argsort(-counts)
    palette: list[dict[str, Any]] = []
    for idx in order:
        if counts[idx] <= 0:
            continue
        r, g, b = (int(np.clip(round(float(c)), 0, 255)) for c in centers[idx])
        weight = round(float(counts[idx]) / total * 100.0, 1)
        palette.append({
            "hex": f"#{r:02x}{g:02x}{b:02x}",
            "rgb": [r, g, b],
            "weight_pct": weight,
        })
    return palette


def _color_and_lighting_metrics(bgr: np.ndarray) -> dict[str, Any]:
    lab = cv2.cvtColor(bgr, cv2.COLOR_BGR2LAB)
    hsv = cv2.cvtColor(bgr, cv2.COLOR_BGR2HSV)
    l_channel = lab[:, :, 0]
    s_channel = hsv[:, :, 1]

    hist = cv2.calcHist([l_channel], [0], None, [256], [0, 256]).flatten()
    total_px = float(hist.sum()) or 1.0
    cdf = np.cumsum(hist) / total_px
    p5 = float(np.searchsorted(cdf, 0.05))
    p95 = float(np.searchsorted(cdf, 0.95))

    mean_lum = float(np.mean(l_channel))
    contrast_std = float(np.std(l_channel))
    dynamic_range_pct = round(max(0.0, (p95 - p5) / 255.0 * 100.0), 1)
    mean_sat = float(np.mean(s_channel))

    if contrast_std < CLAHE_CONTRAST_THRESHOLD:
        lighting_key = "low-contrast"
    elif mean_lum < CLAHE_LUMINANCE_THRESHOLD:
        lighting_key = "low-key"
    elif mean_lum > 185.0:
        lighting_key = "high-key"
    else:
        lighting_key = "balanced"

    palette = _dominant_hex_colors(bgr, k=5)
    return {
        "mean_luminance": round(mean_lum, 2),
        "contrast_std": round(contrast_std, 2),
        "dynamic_range_pct": dynamic_range_pct,
        "lighting_key": lighting_key,
        "mean_saturation": round(mean_sat, 2),
        "dominant_colors": palette,
    }


def _sharpness_and_geometry_metrics(bgr: np.ndarray) -> dict[str, Any]:
    gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)
    h, w = gray.shape[:2]
    laplacian_var = float(cv2.Laplacian(gray, cv2.CV_64F).var())
    if laplacian_var >= 180.0:
        sharpness_tier = "crisp/high-detail"
    elif laplacian_var >= BLUR_SHARPNESS_THRESHOLD:
        sharpness_tier = "moderate-focus"
    else:
        sharpness_tier = "soft/motion-blurred"

    edges = cv2.Canny(gray, 80, 180)
    edge_density_pct = round(float(np.count_nonzero(edges)) / float(max(1, h * w)) * 100.0, 2)

    moments = cv2.moments(edges)
    if moments["m00"] > 0:
        cx_norm = float(moments["m10"] / moments["m00"]) / float(max(1, w))
        cy_norm = float(moments["m01"] / moments["m00"]) / float(max(1, h))
    else:
        cx_norm, cy_norm = 0.5, 0.5

    thirds = {
        "upper-left third": (1.0 / 3.0, 1.0 / 3.0),
        "upper-right third": (2.0 / 3.0, 1.0 / 3.0),
        "lower-left third": (1.0 / 3.0, 2.0 / 3.0),
        "lower-right third": (2.0 / 3.0, 2.0 / 3.0),
    }
    nearest_third, third_pt = min(
        thirds.items(),
        key=lambda item: math.hypot(cx_norm - item[1][0], cy_norm - item[1][1]),
    )
    third_dist = math.hypot(cx_norm - third_pt[0], cy_norm - third_pt[1])
    center_dist = math.hypot(cx_norm - 0.5, cy_norm - 0.5)
    if center_dist <= 0.11:
        comp_zone = "center-weighted"
    elif third_dist <= 0.16:
        comp_zone = nearest_third
    else:
        comp_zone = "golden-ratio balanced"

    min_line_len = max(8, int(round(min(h, w) * 0.1)))
    lines = cv2.HoughLinesP(
        edges, 1.0, np.pi / 180.0, threshold=25, minLineLength=min_line_len, maxLineGap=10
    )
    horiz = vert = diag = 0
    if lines is not None and len(lines) > 0:
        for x1, y1, x2, y2 in np.asarray(lines).reshape(-1, 4):
            angle = abs(math.degrees(math.atan2(float(y2 - y1), float(x2 - x1)))) % 180.0
            if angle <= 20.0 or angle >= 160.0:
                horiz += 1
            elif 70.0 <= angle <= 110.0:
                vert += 1
            else:
                diag += 1
    total_lines = horiz + vert + diag
    if total_lines < 3:
        dominant_orientation = "organic/curved"
        h_pct = v_pct = d_pct = 0.0
    else:
        h_pct = round(horiz / total_lines * 100.0, 1)
        v_pct = round(vert / total_lines * 100.0, 1)
        d_pct = round(diag / total_lines * 100.0, 1)
        if h_pct >= v_pct and h_pct >= d_pct:
            dominant_orientation = "horizontal-dominant"
        elif v_pct >= h_pct and v_pct >= d_pct:
            dominant_orientation = "vertical-dominant"
        else:
            dominant_orientation = "diagonal/dynamic"

    return {
        "laplacian_sharpness": round(laplacian_var, 2),
        "sharpness_score": round(laplacian_var, 2),
        "sharpness_tier": sharpness_tier,
        "sharpness_label": sharpness_tier,
        "edge_density_pct": edge_density_pct,
        "saliency_region": comp_zone,
        "dominant_lines": dominant_orientation,
        "saliency_center": {
            "x_norm": round(cx_norm, 3),
            "y_norm": round(cy_norm, 3),
            "composition_zone": comp_zone,
        },
        "structural_lines": {
            "dominant_orientation": dominant_orientation,
            "line_count": int(total_lines),
            "horizontal_pct": h_pct,
            "vertical_pct": v_pct,
            "diagonal_pct": d_pct,
        },
    }


def _apply_clahe_recovery(bgr: np.ndarray, output_dir: Path) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    lab = cv2.cvtColor(bgr, cv2.COLOR_BGR2LAB)
    l_chan, a_chan, b_chan = cv2.split(lab)
    clahe = cv2.createCLAHE(clipLimit=2.5, tileGridSize=(8, 8))
    l_enhanced = clahe.apply(l_chan)
    merged = cv2.merge((l_enhanced, a_chan, b_chan))
    enhanced_bgr = cv2.cvtColor(merged, cv2.COLOR_LAB2BGR)
    out_path = output_dir / "opencv_clahe_enhanced.jpg"
    ok, encoded = cv2.imencode(".jpg", enhanced_bgr, [int(cv2.IMWRITE_JPEG_QUALITY), 92])
    if not ok:
        raise RuntimeError("OpenCV failed to encode CLAHE enhanced image.")
    out_path.write_bytes(encoded.tobytes())
    return out_path


def _render_hud_overlay(
    bgr: np.ndarray,
    output_dir: Path,
    color_lighting: dict[str, Any],
    geometry: dict[str, Any],
    motion: dict[str, Any] | None = None,
    flow_field: np.ndarray | None = None,
    clahe_active: bool = False,
) -> Path:
    """Render an OpenCV 5.0 Vision HUD diagnostic overlay onto the reference frame."""
    output_dir.mkdir(parents=True, exist_ok=True)
    orig_h, orig_w = bgr.shape[:2]
    max_dim = max(orig_h, orig_w)
    if max_dim < 640:
        scale = 640.0 / float(max(1, max_dim))
        canvas = cv2.resize(
            bgr,
            (max(320, int(round(orig_w * scale))), max(240, int(round(orig_h * scale)))),
            interpolation=cv2.INTER_CUBIC,
        )
    elif max_dim > 1600:
        scale = 1600.0 / float(max_dim)
        canvas = cv2.resize(
            bgr,
            (max(320, int(round(orig_w * scale))), max(240, int(round(orig_h * scale)))),
            interpolation=cv2.INTER_AREA,
        )
    else:
        canvas = bgr.copy()

    h, w = canvas.shape[:2]
    # 1. Subtle darkened/cool-tinted base + electric-blue Canny edge contours
    dark_tint = np.full_like(canvas, (30, 18, 10), dtype=np.uint8)
    hud = cv2.addWeighted(canvas, 0.74, dark_tint, 0.26, 0.0)

    gray = cv2.cvtColor(canvas, cv2.COLOR_BGR2GRAY)
    edges = cv2.Canny(gray, 80, 180)
    edge_layer = hud.copy()
    edge_layer[edges > 0] = (255, 225, 35)  # Electric cyan in BGR
    hud = cv2.addWeighted(hud, 0.65, edge_layer, 0.35, 0.0)

    # 2. Rule-of-Thirds Grid & Hough Structural Lines (semi-transparent geometry overlay)
    geom_layer = hud.copy()
    x1, x2 = w // 3, (2 * w) // 3
    y1, y2 = h // 3, (2 * h) // 3
    grid_color = (215, 175, 95)
    cv2.line(geom_layer, (x1, 0), (x1, h), grid_color, 1, cv2.LINE_AA)
    cv2.line(geom_layer, (x2, 0), (x2, h), grid_color, 1, cv2.LINE_AA)
    cv2.line(geom_layer, (0, y1), (w, y1), grid_color, 1, cv2.LINE_AA)
    cv2.line(geom_layer, (0, y2), (w, y2), grid_color, 1, cv2.LINE_AA)

    # 3. Hough Structural Lines in golden/amber accent
    min_line_len = max(12, int(round(min(h, w) * 0.1)))
    lines = cv2.HoughLinesP(
        edges, 1.0, np.pi / 180.0, threshold=28, minLineLength=min_line_len, maxLineGap=12
    )
    if lines is not None and len(lines) > 0:
        segs = np.asarray(lines).reshape(-1, 4)
        lengths = np.hypot(segs[:, 2] - segs[:, 0], segs[:, 3] - segs[:, 1])
        top_indices = np.argsort(-lengths)[:24]
        for idx in top_indices:
            lx1, ly1, lx2, ly2 = (int(v) for v in segs[idx])
            cv2.line(geom_layer, (lx1, ly1), (lx2, ly2), (40, 195, 255), 2, cv2.LINE_AA)

    hud = cv2.addWeighted(hud, 0.44, geom_layer, 0.56, 0.0)

    # 4. Optical Flow Motion Vector Arrows (for video keyframes)
    if flow_field is not None and flow_field.ndim == 3 and flow_field.shape[2] == 2:
        fh, fw = flow_field.shape[:2]
        cols, rows = 8, 5
        margin_x = max(24, w // 12)
        margin_y = max(48, h // 7)
        xs = np.linspace(margin_x, w - margin_x, cols)
        ys = np.linspace(margin_y, h - margin_y, rows)
        arrow_scale = max(4.0, min(w, h) * 0.035)
        max_arrow = max(18.0, min(w, h) * 0.11)
        for gy in ys:
            for gx in xs:
                fi_y = min(fh - 1, max(0, int(round(gy / float(max(1, h)) * (fh - 1)))))
                fi_x = min(fw - 1, max(0, int(round(gx / float(max(1, w)) * (fw - 1)))))
                dx = float(flow_field[fi_y, fi_x, 0])
                dy = float(flow_field[fi_y, fi_x, 1])
                mag = math.hypot(dx, dy)
                if mag < 0.05 and motion:
                    dx = float(motion.get("mean_dx", 0.0))
                    dy = float(motion.get("mean_dy", 0.0))
                    mag = math.hypot(dx, dy)
                vx = dx * arrow_scale
                vy = dy * arrow_scale
                vmag = math.hypot(vx, vy)
                if vmag > max_arrow and vmag > 0:
                    vx = vx / vmag * max_arrow
                    vy = vy / vmag * max_arrow
                elif vmag < 6.0 and mag > 0.02:
                    vx = (dx / mag) * 8.0
                    vy = (dy / mag) * 8.0
                p1 = (int(round(gx)), int(round(gy)))
                p2 = (int(round(gx + vx)), int(round(gy + vy)))
                cv2.circle(hud, p1, 2, (160, 255, 80), -1, cv2.LINE_AA)
                cv2.arrowedLine(hud, p1, p2, (140, 255, 65), 2, cv2.LINE_AA, tipLength=0.32)

    # 2b. Saliency Center-of-Mass Target Reticle
    saliency = geometry.get("saliency_center", {})
    sx_norm = float(saliency.get("x_norm", 0.5))
    sy_norm = float(saliency.get("y_norm", 0.5))
    comp_zone = str(saliency.get("composition_zone", geometry.get("saliency_region", "balanced")))
    cx = int(np.clip(round(sx_norm * w), 24, w - 24))
    cy = int(np.clip(round(sy_norm * h), 44, h - 48))
    r_outer = max(16, int(round(min(h, w) * 0.042)))
    r_inner = max(6, r_outer // 2)
    reticle_cyan = (255, 235, 55)
    reticle_amber = (55, 205, 255)
    cv2.circle(hud, (cx, cy), r_outer, reticle_cyan, 2, cv2.LINE_AA)
    cv2.circle(hud, (cx, cy), r_inner, reticle_amber, 1, cv2.LINE_AA)
    cv2.circle(hud, (cx, cy), 2, reticle_amber, -1, cv2.LINE_AA)
    tick = r_outer + 8
    cv2.line(hud, (cx - tick, cy), (cx - r_inner, cy), reticle_cyan, 1, cv2.LINE_AA)
    cv2.line(hud, (cx + r_inner, cy), (cx + tick, cy), reticle_cyan, 1, cv2.LINE_AA)
    cv2.line(hud, (cx, cy - tick), (cx, cy - r_inner), reticle_cyan, 1, cv2.LINE_AA)
    cv2.line(hud, (cx, cy + r_inner), (cx, cy + tick), reticle_cyan, 1, cv2.LINE_AA)

    font = cv2.FONT_HERSHEY_SIMPLEX
    font_scale = max(0.38, min(0.62, w / 1450.0))
    reticle_label = f"SALIENCY ({sx_norm:.2f},{sy_norm:.2f}) [{comp_zone.upper()}]"
    tx = min(w - int(len(reticle_label) * 8 * font_scale) - 12, max(10, cx + r_outer + 8))
    ty = max(52, min(h - 56, cy - 6))
    cv2.putText(hud, reticle_label, (tx + 1, ty + 1), font, font_scale, (10, 12, 18), 2, cv2.LINE_AA)
    cv2.putText(hud, reticle_label, (tx, ty), font, font_scale, reticle_cyan, 1, cv2.LINE_AA)

    # 5. Top & Bottom Telemetry Burn-In Strips
    top_h = max(34, int(round(h * 0.075)))
    bot_h = max(38, int(round(h * 0.085)))
    bar_layer = hud.copy()
    cv2.rectangle(bar_layer, (0, 0), (w, top_h), (20, 13, 8), -1)
    cv2.rectangle(bar_layer, (0, h - bot_h), (w, h), (20, 13, 8), -1)
    hud = cv2.addWeighted(hud, 0.22, bar_layer, 0.78, 0.0)
    cv2.line(hud, (0, top_h), (w, top_h), (235, 190, 50), 1, cv2.LINE_AA)
    cv2.line(hud, (0, h - bot_h), (w, h - bot_h), (235, 190, 50), 1, cv2.LINE_AA)

    runtime = detect_compute_runtime()
    lighting_key = str(color_lighting.get("lighting_key", "balanced")).upper()
    sharp_score = float(geometry.get("laplacian_sharpness", 0.0))
    edge_pct = float(geometry.get("edge_density_pct", 0.0))
    motion_tag = f" | FLOW: {str(motion.get('dominant_motion', '')).upper()}" if motion else ""
    clahe_tag = "CLAHE: ACTIVE" if clahe_active else "CLAHE: NATIVE"
    header_text = (
        f"OpenCV {cv2.__version__} HUD [{runtime['compute_badge']}]  "
        f"KEY: {lighting_key} | SHARP: {sharp_score:.1f} | EDGES: {edge_pct:.1f}%{motion_tag} | {clahe_tag}"
    )
    text_y = int(round(top_h * 0.66))
    cv2.putText(hud, header_text, (12, text_y), font, font_scale, (245, 248, 255), 1, cv2.LINE_AA)

    # Bottom bar: 5 k-means dominant color palette swatches
    palette = color_lighting.get("dominant_colors", [])[:5]
    swatch_x = 12
    swatch_y1 = h - bot_h + max(6, int(round(bot_h * 0.18)))
    swatch_y2 = h - max(6, int(round(bot_h * 0.18)))
    swatch_w = max(18, int(round(bot_h * 0.65)))
    for c in palette:
        rgb = c.get("rgb", [128, 128, 128])
        bgr_col = (int(rgb[2]), int(rgb[1]), int(rgb[0]))
        cv2.rectangle(hud, (swatch_x, swatch_y1), (swatch_x + swatch_w, swatch_y2), bgr_col, -1)
        cv2.rectangle(hud, (swatch_x, swatch_y1), (swatch_x + swatch_w, swatch_y2), (220, 235, 250), 1)
        label = f"{c.get('hex', '')} ({c.get('weight_pct', 0):.0f}%)"
        cv2.putText(
            hud,
            label,
            (swatch_x + swatch_w + 5, int(round((swatch_y1 + swatch_y2) * 0.5 + 4))),
            font,
            max(0.34, font_scale * 0.88),
            (225, 238, 252),
            1,
            cv2.LINE_AA,
        )
        swatch_x += swatch_w + int(round(105 * max(0.4, font_scale)))
        if swatch_x > w - 80:
            break

    out_path = output_dir / "opencv_hud_overlay.jpg"
    ok, encoded = cv2.imencode(".jpg", hud, [int(cv2.IMWRITE_JPEG_QUALITY), 92])
    if not ok:
        raise RuntimeError("OpenCV failed to encode HUD overlay image.")
    out_path.write_bytes(encoded.tobytes())
    return out_path


def _build_grounding_brief(
    color_lighting: dict[str, Any],
    geometry: dict[str, Any],
    motion: dict[str, Any] | None,
    actions: list[dict[str, Any]],
) -> str:
    hex_list = ", ".join(
        f"{c['hex']} ({c['weight_pct']}%)" for c in color_lighting.get("dominant_colors", [])[:5]
    )
    saliency = geometry.get("saliency_center", {})
    lines_info = geometry.get("structural_lines", {})
    parts = [
        "[OpenCV Deterministic Telemetry — Ground visual analysis in these measurements]:",
        (
            f"- Palette (k-means RGB): {hex_list}; "
            f"Lighting key: {color_lighting.get('lighting_key')} "
            f"(mean luminance {color_lighting.get('mean_luminance')}/255, "
            f"contrast std {color_lighting.get('contrast_std')}, "
            f"dynamic range {color_lighting.get('dynamic_range_pct')}%)."
        ),
        (
            f"- Geometry & Focus: Laplacian sharpness {geometry.get('laplacian_sharpness')} "
            f"({geometry.get('sharpness_tier')}), Canny edge density {geometry.get('edge_density_pct')}%, "
            f"saliency center ({saliency.get('x_norm')}, {saliency.get('y_norm')}) -> {saliency.get('composition_zone')}, "
            f"Hough line structure: {lines_info.get('dominant_orientation')} ({lines_info.get('line_count')} lines)."
        ),
    ]
    if motion:
        parts.append(
            f"- Optical Flow & Continuity: dominant motion '{motion.get('dominant_motion')}' "
            f"(dx={motion.get('mean_dx')}, dy={motion.get('mean_dy')}, radial={motion.get('radial_flow')}, "
            f"magnitude={motion.get('motion_magnitude')}), HSV continuity={motion.get('mean_hist_correlation')} "
            f"({motion.get('continuity_class')})."
        )
    if actions:
        action_summaries = "; ".join(f"{a['decision']} -> {a['action']}" for a in actions)
        parts.append(f"- Agentic CV Actions Taken: {action_summaries}.")
    return "\n".join(parts)


def analyze_image_cv(image_path: Path | str, output_dir: Path | str | None = None) -> OpenCVTelemetry:
    started = time.perf_counter()
    path = Path(image_path)
    target_dir = Path(output_dir) if output_dir is not None else path.parent
    bgr = _read_bgr(path)

    color_lighting = _color_and_lighting_metrics(bgr)
    geometry = _sharpness_and_geometry_metrics(bgr)
    actions: list[dict[str, Any]] = []
    clahe_path: Path | None = None

    mean_lum = color_lighting["mean_luminance"]
    contrast_std = color_lighting["contrast_std"]
    if mean_lum < CLAHE_LUMINANCE_THRESHOLD or contrast_std < CLAHE_CONTRAST_THRESHOLD:
        clahe_path = _apply_clahe_recovery(bgr, target_dir)
        trigger_reason = (
            f"mean_luminance={mean_lum} (<{CLAHE_LUMINANCE_THRESHOLD})"
            if mean_lum < CLAHE_LUMINANCE_THRESHOLD
            else f"contrast_std={contrast_std} (<{CLAHE_CONTRAST_THRESHOLD})"
        )
        actions.append({
            "step": "perception->decision->action",
            "type": "clahe_shadow_contrast_recovery",
            "trigger": trigger_reason,
            "decision": "Autonomous CLAHE shadow/contrast recovery activated",
            "action": f"Equalized LAB L-channel (clipLimit=2.5, grid=8x8) and attached {clahe_path.name} alongside original reference",
            "artifact": clahe_path.name,
        })
    else:
        actions.append({
            "step": "perception->decision->action",
            "type": "exposure_validation",
            "trigger": f"mean_luminance={mean_lum}, contrast_std={contrast_std}",
            "decision": "Dynamic range sufficient; preserve native tonal exposure",
            "action": "Passed unmodified reference with deterministic k-means hex palette and geometry grounding",
            "artifact": None,
        })

    hud_path: Path | None = None
    if output_dir is not None:
        hud_path = _render_hud_overlay(
            bgr,
            target_dir,
            color_lighting,
            geometry,
            motion=None,
            flow_field=None,
            clahe_active=clahe_path is not None,
        )

    brief = _build_grounding_brief(color_lighting, geometry, None, actions)
    elapsed_ms = (time.perf_counter() - started) * 1000.0
    return OpenCVTelemetry(
        opencv_version=str(cv2.__version__),
        media_kind="image",
        processing_ms=elapsed_ms,
        color_and_lighting=color_lighting,
        sharpness_and_geometry=geometry,
        motion_and_continuity={},
        agentic_actions=actions,
        cv_grounding_brief=brief,
        clahe_enhanced_path=clahe_path,
        hud_overlay_path=hud_path,
    )


def _sample_video_frames(
    video_path: Path | None, frame_paths: list[Path] | None, max_samples: int = 30
) -> list[np.ndarray]:
    sampled: list[np.ndarray] = []
    if video_path is not None and video_path.is_file():
        cap = cv2.VideoCapture(str(video_path))
        try:
            if cap.isOpened():
                total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
                if total_frames >= 2:
                    count = min(max_samples, total_frames)
                    indices = [int(round(i * (total_frames - 1) / max(1, count - 1))) for i in range(count)]
                    for idx in indices:
                        cap.set(cv2.CAP_PROP_POS_FRAMES, idx)
                        ok, frame = cap.read()
                        if ok and frame is not None:
                            sampled.append(frame)
                else:
                    while len(sampled) < max_samples:
                        ok, frame = cap.read()
                        if not ok or frame is None:
                            break
                        sampled.append(frame)
        finally:
            cap.release()

    if len(sampled) < 2 and frame_paths:
        sampled = []
        step = max(1, len(frame_paths) // max_samples)
        for p in frame_paths[::step][:max_samples]:
            if Path(p).is_file():
                sampled.append(_read_bgr(Path(p)))
    return sampled


def _classify_motion(mean_dx: float, mean_dy: float, radial_flow: float, mean_mag: float) -> str:
    if mean_mag < 0.35:
        return "static/locked-off"
    if abs(radial_flow) > 0.45 and abs(radial_flow) >= 0.75 * math.hypot(mean_dx, mean_dy):
        return "push-in/zoom-in" if radial_flow > 0 else "pull-out/zoom-out"
    directional = math.hypot(mean_dx, mean_dy)
    if directional >= 0.35:
        if abs(mean_dx) >= abs(mean_dy):
            return "pan-right" if mean_dx > 0 else "pan-left"
        return "tilt-down" if mean_dy > 0 else "tilt-up"
    if mean_mag >= 2.0:
        return "high-kinetic-motion"
    return "static/locked-off"


def analyze_video_cv(
    video_path: Path | str | None,
    frame_paths: list[Path | str] | None = None,
    output_dir: Path | str | None = None,
) -> OpenCVTelemetry:
    started = time.perf_counter()
    vpath = Path(video_path) if video_path is not None else None
    fpaths = [Path(p) for p in (frame_paths or []) if Path(p).is_file()]
    target_dir = (
        Path(output_dir)
        if output_dir is not None
        else (vpath.parent if vpath is not None else (fpaths[0].parent if fpaths else Path(".")))
    )

    loaded_fpaths: dict[Path, np.ndarray] = {}
    if (vpath is None or not vpath.is_file()) and fpaths:
        for p in fpaths:
            loaded_fpaths[p] = _read_bgr(p)
        step = max(1, len(fpaths) // 30)
        frames = [loaded_fpaths[p] for p in fpaths[::step][:30]]
    else:
        frames = _sample_video_frames(vpath, fpaths, max_samples=30)

    if not frames:
        raise ValueError("No readable video frames available for OpenCV telemetry.")

    actions: list[dict[str, Any]] = []
    # 1. Rank candidate keyframes by Laplacian focus sharpness:
    candidate_frames: list[tuple[str, Path | None, np.ndarray, float]] = []
    if fpaths:
        for p in fpaths:
            bgr = loaded_fpaths.get(p)
            if bgr is None:
                bgr = _read_bgr(p)
            gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)
            sharp = float(cv2.Laplacian(gray, cv2.CV_64F).var())
            candidate_frames.append((p.name, p, bgr, sharp))
    else:
        for idx, bgr in enumerate(frames):
            gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)
            sharp = float(cv2.Laplacian(gray, cv2.CV_64F).var())
            candidate_frames.append((f"sample_{idx:03d}.jpg", None, bgr, sharp))

    ranked = sorted(candidate_frames, key=lambda item: item[3], reverse=True)
    primary_name, _, primary_bgr, primary_sharp = ranked[0]
    blurry_count = sum(1 for _, _, _, s in candidate_frames if s < BLUR_SHARPNESS_THRESHOLD)
    ranking_payload = [
        {
            "file": name,
            "sharpness": round(sharp, 2),
            "status": "flagged-blurry" if sharp < BLUR_SHARPNESS_THRESHOLD else "selected-sharp",
            "rank": rank_idx + 1,
        }
        for rank_idx, (name, _, _, sharp) in enumerate(ranked)
    ]
    actions.append({
        "step": "perception->decision->action",
        "type": "sharpness_gated_keyframe_ranking",
        "trigger": f"Evaluated {len(candidate_frames)} keyframes; {blurry_count} below sharpness threshold ({BLUR_SHARPNESS_THRESHOLD})",
        "decision": f"Selected sharpest keyframe '{primary_name}' (Laplacian={round(primary_sharp, 2)}) for primary telemetry",
        "action": "Ranked keyframes by focus sharpness and deprioritized motion-blurred frames for prompt synthesis",
        "artifact": primary_name,
    })

    color_lighting = _color_and_lighting_metrics(primary_bgr)
    geometry = _sharpness_and_geometry_metrics(primary_bgr)

    clahe_path: Path | None = None
    mean_lum = color_lighting["mean_luminance"]
    contrast_std = color_lighting["contrast_std"]
    if mean_lum < CLAHE_LUMINANCE_THRESHOLD or contrast_std < CLAHE_CONTRAST_THRESHOLD:
        clahe_path = _apply_clahe_recovery(primary_bgr, target_dir)
        actions.append({
            "step": "perception->decision->action",
            "type": "clahe_shadow_contrast_recovery",
            "trigger": f"Primary keyframe mean_luminance={mean_lum}, contrast_std={contrast_std}",
            "decision": "Autonomous CLAHE shadow/contrast recovery activated on primary keyframe",
            "action": f"Saved equalized keyframe {clahe_path.name} in run directory",
            "artifact": clahe_path.name,
        })

    # 2. Dense Optical Flow (Farnebäck) + HSV Histogram Continuity:
    dx_vals: list[float] = []
    dy_vals: list[float] = []
    radial_vals: list[float] = []
    mag_vals: list[float] = []
    correl_vals: list[float] = []

    flow_w, flow_h = 160, 90
    grid_x, grid_y = np.meshgrid(
        np.linspace(-1.0, 1.0, flow_w, dtype=np.float32),
        np.linspace(-1.0, 1.0, flow_h, dtype=np.float32),
    )
    norm = np.hypot(grid_x, grid_y)
    norm[norm == 0] = 1.0
    unit_rx = grid_x / norm
    unit_ry = grid_y / norm

    prev_gray: np.ndarray | None = None
    prev_hist: np.ndarray | None = None
    accum_flow: np.ndarray | None = None
    flow_count = 0

    for frame in frames:
        small = cv2.resize(frame, (flow_w, flow_h), interpolation=cv2.INTER_AREA)
        gray = cv2.cvtColor(small, cv2.COLOR_BGR2GRAY)
        hsv = cv2.cvtColor(small, cv2.COLOR_BGR2HSV)
        hist = cv2.calcHist([hsv], [0, 1], None, [30, 32], [0, 180, 0, 256])
        cv2.normalize(hist, hist, 0, 1, cv2.NORM_MINMAX)

        if prev_gray is not None:
            flow = cv2.calcOpticalFlowFarneback(
                prev_gray, gray, None, 0.5, 3, 15, 3, 5, 1.2, 0
            )
            if accum_flow is None:
                accum_flow = flow.astype(np.float32)
            else:
                accum_flow += flow
            flow_count += 1
            fx = flow[:, :, 0]
            fy = flow[:, :, 1]
            dx_vals.append(float(np.mean(fx)))
            dy_vals.append(float(np.mean(fy)))
            mag_vals.append(float(np.mean(np.hypot(fx, fy))))
            radial_vals.append(float(np.mean(fx * unit_rx + fy * unit_ry)))

        if prev_hist is not None:
            corr = float(cv2.compareHist(prev_hist, hist, cv2.HISTCMP_CORREL))
            correl_vals.append(corr)

        prev_gray = gray
        prev_hist = hist

    mean_dx = float(np.mean(dx_vals)) if dx_vals else 0.0
    mean_dy = float(np.mean(dy_vals)) if dy_vals else 0.0
    mean_radial = float(np.mean(radial_vals)) if radial_vals else 0.0
    mean_mag = float(np.mean(mag_vals)) if mag_vals else 0.0
    dominant_motion = _classify_motion(mean_dx, mean_dy, mean_radial, mean_mag)

    mean_corr = float(np.mean(correl_vals)) if correl_vals else 1.0
    min_corr = float(np.min(correl_vals)) if correl_vals else 1.0
    if min_corr < 0.45:
        continuity_class = "multi-cut/dynamic"
    elif mean_corr < 0.78:
        continuity_class = "moderate-transitions"
    else:
        continuity_class = "continuous-shot"

    elapsed_sec = max(1e-6, time.perf_counter() - started)
    elapsed_ms = elapsed_sec * 1000.0
    frames_processed = len(frames)
    effective_fps = round(frames_processed / elapsed_sec, 2)

    motion_metrics = {
        "frames_processed": frames_processed,
        "effective_fps": effective_fps,
        "mean_dx": round(mean_dx, 3),
        "mean_dy": round(mean_dy, 3),
        "radial_flow": round(mean_radial, 3),
        "motion_magnitude": round(mean_mag, 3),
        "dominant_motion": dominant_motion,
        "mean_hist_correlation": round(mean_corr, 3),
        "min_hist_correlation": round(min_corr, 3),
        "continuity_class": continuity_class,
        "primary_keyframe": primary_name,
        "blurry_frame_count": blurry_count,
        "keyframe_ranking": ranking_payload,
    }

    hud_path: Path | None = None
    if output_dir is not None:
        mean_flow_field = (accum_flow / float(max(1, flow_count))) if accum_flow is not None else None
        hud_path = _render_hud_overlay(
            primary_bgr,
            target_dir,
            color_lighting,
            geometry,
            motion=motion_metrics,
            flow_field=mean_flow_field,
            clahe_active=clahe_path is not None,
        )

    brief = _build_grounding_brief(color_lighting, geometry, motion_metrics, actions)
    return OpenCVTelemetry(
        opencv_version=str(cv2.__version__),
        media_kind="video",
        processing_ms=elapsed_ms,
        color_and_lighting=color_lighting,
        sharpness_and_geometry=geometry,
        motion_and_continuity=motion_metrics,
        agentic_actions=actions,
        cv_grounding_brief=brief,
        clahe_enhanced_path=clahe_path,
        hud_overlay_path=hud_path,
    )
