import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { beforeAll, describe, expect, it, vi } from "vitest";

const html = readFileSync(resolve(process.cwd(), "web/index.html"), "utf8");

describe("OpenCV 5.0 Agentic Vision Telemetry UI (Sprint 3)", () => {
  let renderResult;
  let renderOpenCVTelemetry;

  beforeAll(async () => {
    document.open();
    document.write(html);
    document.close();
    window.scrollTo = vi.fn();
    globalThis.fetch = vi.fn(async (url) => {
      if (String(url).includes("/api/orb/credits/config")) {
        return { ok: true, status: 200, json: async () => ({ enabled: false }) };
      }
      if (String(url).includes("/api/health")) {
        return { ok: true, status: 200, json: async () => ({ status: "ok", credit_mode: "local" }) };
      }
      return { ok: true, status: 200, json: async () => ({}) };
    });
    const mod = await import("./app.js");
    renderResult = mod.renderResult;
    renderOpenCVTelemetry = mod.renderOpenCVTelemetry;
  });

  it("renders benchmark badges, agentic actions, CLAHE toggle, 5 color swatches, and CV metrics on Decode/Compose", () => {
    const sampleResult = {
      operation: "decode",
      media_kind: "video",
      video: {
        name: "test-clip.mp4",
        width: 1920,
        height: 1080,
        duration: 4.2,
        fps: 24,
        preview_url: "/api/jobs/job123/frames/source.mp4",
      },
      summary: "Low-key tracking shot across neon wet pavement.",
      visual_analysis: {
        subject_and_scene: "Cyberpunk alleyway at night",
        lighting: "Low-key moody rim light",
      },
      prompt: "Cinematic pan-right tracking shot across a dark rain-slicked alley.",
      opencv_telemetry: {
        opencv_version: "5.0.0",
        compute_badge: "ARM64 NEON",
        media_kind: "video",
        processing_ms: 42.8,
        effective_fps: 186.9,
        clahe_triggered: true,
        clahe_applied: true,
        post_clahe_edge_density: 12.37,
        edge_density_gain_pct: 66.1,
        post_clahe_laplacian_variance: 368.4,
        sharpness_gain_pct: 100,
        clahe_preview_url: "/api/jobs/job123/frames/opencv_clahe_enhanced.jpg",
        hud_preview_url: "/api/jobs/job123/frames/opencv_hud_overlay.jpg",
        aws_s3: {
          enabled: true,
          synced: true,
          bucket: "orb-opencv-2026-artifacts",
          region: "us-east-1",
          keys: [
            "orb-jobs/job123/opencv_hud_overlay.jpg",
            "orb-jobs/job123/opencv_clahe_enhanced.jpg",
            "orb-jobs/job123/opencv_telemetry.json",
          ],
          hud_s3_url: "https://orb-opencv-2026-artifacts.s3.us-east-1.amazonaws.com/orb-jobs/job123/opencv_hud_overlay.jpg",
        },
        color_and_lighting: {
          mean_luminance: 38.4,
          contrast_std: 24.1,
          dynamic_range_pct: 41.2,
          lighting_key: "low-key",
          dominant_colors: [
            { hex: "#141824", weight_pct: 42.5 },
            { hex: "#2b3a55", weight_pct: 23.0 },
            { hex: "#0d99ff", weight_pct: 15.5 },
            { hex: "#ff3366", weight_pct: 11.0 },
            { hex: "#f2c94c", weight_pct: 8.0 },
          ],
        },
        sharpness_and_geometry: {
          laplacian_sharpness: 184.2,
          sharpness_score: 184.2,
          sharpness_tier: "crisp/in-focus",
          sharpness_label: "crisp/in-focus",
          edge_density_pct: 7.45,
          saliency_region: "golden-ratio balanced",
          dominant_lines: "horizontal-dominant",
          structural_lines: { dominant_orientation: "horizontal-dominant", line_count: 216 },
        },
        motion_and_continuity: {
          dominant_motion: "pan-right",
          mean_dx: 1.42,
          mean_dy: -0.08,
          radial_flow: 0.03,
          mean_hist_correlation: 0.942,
          continuity_class: "continuous-single-take",
        },
        agentic_actions: [
          {
            type: "clahe_shadow_contrast_recovery",
            trigger: "mean_luminance=38.4 (<60) or contrast_std=24.1 (<32)",
            decision: "Autonomous CLAHE Shadow & Contrast Recovery",
            action: "Applied LAB L-channel CLAHE (clipLimit=2.5, tileGridSize=8x8).",
          },
          {
            type: "sharpness_gated_keyframe_ranking",
            trigger: "8 video frames scored via Laplacian variance + Canny edge density",
            decision: "Sharpness-Gated Keyframe Prioritization",
            action: "Ranked frame_001.png highest and deprioritized motion-blurred frame_003.png.",
          },
        ],
      },
    };

    renderResult(sampleResult);

    const card = document.getElementById("res-opencv-card");
    expect(card.classList.contains("hidden")).toBe(false);

    // 1. Badges
    const badges = [...document.querySelectorAll("#res-opencv-badges .opencv-badge")].map((b) => b.textContent);
    expect(badges).toEqual([
      "OpenCV 5.0.0 · ARM64 NEON",
      "Latency: 42.8 ms",
      "Throughput: 186.9 FPS",
      "CLAHE Auto-Recovery: Active",
      "+66.1% edge gain",
      "AWS S3 Synced (orb-opencv-2026-artifacts)",
    ]);
    expect(document.querySelector("#res-opencv-badges .opencv-badge.highlight")?.textContent).toBe(
      "CLAHE Auto-Recovery: Active",
    );

    // 2. Agentic actions log
    const actionItems = [...document.querySelectorAll("#res-opencv-actions li")];
    expect(actionItems).toHaveLength(2);
    expect(actionItems[0].textContent).toContain("Autonomous CLAHE Shadow & Contrast Recovery");

    // 3a. Preview Mode Switcher (Original Reference | OpenCV Vision HUD | CLAHE Shadow Recovery)
    const switcher = document.getElementById("res-preview-switcher");
    const tabOriginal = document.getElementById("preview-tab-original");
    const tabHud = document.getElementById("preview-tab-hud");
    const tabClahe = document.getElementById("preview-tab-clahe");
    const hudImg = document.getElementById("res-hud-image");
    const clahePreviewImg = document.getElementById("res-clahe-preview-image");
    expect(switcher.classList.contains("hidden")).toBe(false);
    expect(tabHud.classList.contains("hidden")).toBe(false);
    expect(tabClahe.classList.contains("hidden")).toBe(false);
    tabHud.click();
    expect(tabHud.getAttribute("aria-selected")).toBe("true");
    expect(hudImg.classList.contains("hidden")).toBe(false);
    expect(hudImg.getAttribute("src")).toContain("opencv_hud_overlay.jpg");
    tabClahe.click();
    expect(tabClahe.getAttribute("aria-selected")).toBe("true");
    expect(clahePreviewImg.classList.contains("hidden")).toBe(false);
    tabOriginal.click();
    expect(tabOriginal.getAttribute("aria-selected")).toBe("true");

    // 3b. OpenCV HUD & CLAHE card toggles
    const hudWrap = document.getElementById("res-opencv-hud-wrap");
    const hudToggle = document.getElementById("res-opencv-hud-toggle");
    const hudView = document.getElementById("res-opencv-hud-view");
    expect(hudWrap.classList.contains("hidden")).toBe(false);
    expect(hudView.classList.contains("hidden")).toBe(true);
    hudToggle.click();
    expect(hudView.classList.contains("hidden")).toBe(false);

    const claheWrap = document.getElementById("res-opencv-clahe-wrap");
    const claheToggle = document.getElementById("res-opencv-clahe-toggle");
    const claheView = document.getElementById("res-opencv-clahe-view");
    expect(claheWrap.classList.contains("hidden")).toBe(false);
    expect(claheView.classList.contains("hidden")).toBe(true);
    claheToggle.click();
    expect(claheView.classList.contains("hidden")).toBe(false);
    expect(claheToggle.getAttribute("aria-expanded")).toBe("true");
    expect(claheToggle.textContent).toBe("Hide OpenCV CLAHE Shadow Recovery");

    // 4. Dominant 5 color swatches
    const swatches = [...document.querySelectorAll("#res-opencv-palette .opencv-swatch")];
    expect(swatches).toHaveLength(5);
    expect(swatches[0].textContent).toContain("#141824");
    expect(swatches[0].textContent).toContain("42.5%");

    // 5. CV Measurements Grid (Lighting, Composition, Video Optical Flow, and AWS S3)
    const metricTerms = [...document.querySelectorAll("#res-opencv-metrics dt")].map((n) => n.textContent);
    expect(metricTerms).toEqual([
      "Lighting & Exposure (cv2.calcHist / LAB)",
      "Composition & Focus (cv2.Laplacian / Canny / HoughLinesP)",
      "CLAHE Recovery (cv2.Canny / Laplacian)",
      "Optical Flow & Continuity (cv2.calcOpticalFlowFarneback / compareHist)",
      "AWS Cloud Persistence (Amazon S3)",
    ]);
    const metricDetails = [...document.querySelectorAll("#res-opencv-metrics dd")].map((n) => n.textContent);
    expect(metricDetails[1]).toContain("horizontal-dominant (216 lines)");
    expect(metricDetails[2]).toContain("Edge density 12.37% (+66.1%)");
    expect(metricDetails[2]).toContain("Laplacian variance 368.4 (+100.0%)");
    expect(metricDetails[3]).toContain("pan-right");
    expect(metricDetails[3]).toContain("continuous-single-take");
    expect(metricDetails[4]).toContain("s3://orb-opencv-2026-artifacts");
  });

  it.each([undefined, null, 0, -12.5, Infinity, "66.1"])("does not advertise positive recovery for gain %s", (gain) => {
    renderOpenCVTelemetry({ clahe_applied: true, edge_density_gain_pct: gain,
      post_clahe_edge_density: 0, sharpness_and_geometry: { sharpness_score: 0,
        sharpness_label: "soft/motion-blurred", edge_density_pct: 0, saliency_region: "center-weighted",
        dominant_lines: "organic/curved", structural_lines: { line_count: 0 } } });
    expect(document.getElementById("res-opencv-badges").textContent).not.toContain("edge gain");
    expect(document.getElementById("res-opencv-metrics").textContent).toContain("organic/curved (0 lines)");
    expect(document.getElementById("res-opencv-card").textContent).not.toMatch(/NaN|Infinity|undefined%/);
    if (gain === -12.5) expect(document.getElementById("res-opencv-metrics").textContent).toContain("(-12.5%)");
  });

  it("accepts nested recovery metrics, a single Hough line, and older results without recovery data", () => {
    const geometry = { sharpness_score: 20, dominant_lines: "vertical-dominant", structural_lines: { line_count: 1 } };
    renderOpenCVTelemetry({ clahe_triggered: true, sharpness_and_geometry: geometry,
      clahe_recovery: { post_clahe_edge_density: 2, edge_density_gain_pct: 25 } });
    expect(document.getElementById("res-opencv-badges").textContent).toContain("+25.0% edge gain");
    expect(document.getElementById("res-opencv-metrics").textContent).toContain("vertical-dominant (1 line)");
    renderOpenCVTelemetry({ sharpness_and_geometry: { sharpness_score: 20, dominant_lines: "vertical-dominant" } });
    expect(document.getElementById("res-opencv-metrics").textContent).toContain("lines: vertical-dominant");
    expect(document.getElementById("res-opencv-metrics").textContent).not.toContain("CLAHE Recovery");
    expect(document.getElementById("res-opencv-badges").textContent).not.toContain("edge gain");
    renderOpenCVTelemetry({ clahe_applied: false, edge_density_gain_pct: 66.1 });
    expect(document.getElementById("res-opencv-badges").textContent).not.toContain("edge gain");
  });

  it("hides #res-opencv-card cleanly on text-only Enhance results", () => {
    renderResult({
      operation: "enhance",
      original_prompt: "a castle on a cliff",
      prompt: "An ancient basalt fortress perched on a storm-lashed sea cliff at dusk.",
      refinements: ["Specify lens focal length"],
    });

    const card = document.getElementById("res-opencv-card");
    expect(card.classList.contains("hidden")).toBe(true);
  });
});
