import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { beforeAll, describe, expect, it, vi } from "vitest";

const html = readFileSync(resolve(process.cwd(), "web/index.html"), "utf8");

describe("OpenCV 5.0 Agentic Vision Telemetry UI (Sprint 3)", () => {
  let renderResult;

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
        clahe_preview_url: "/api/jobs/job123/frames/opencv_clahe_enhanced.jpg",
        hud_preview_url: "/api/jobs/job123/frames/opencv_hud_overlay.jpg",
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
            trigger: "mean_luminance=38.4 (<78) or contrast_std=24.1 (<34)",
            decision: "Autonomous CLAHE Shadow & Contrast Recovery",
            action: "Applied LAB L-channel CLAHE (clipLimit=2.8, tileGridSize=8x8).",
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

    // 5. CV Measurements Grid (Lighting, Composition, and Video Optical Flow)
    const metricTerms = [...document.querySelectorAll("#res-opencv-metrics dt")].map((n) => n.textContent);
    expect(metricTerms).toEqual([
      "Lighting & Exposure (cv2.calcHist / LAB)",
      "Composition & Focus (cv2.Laplacian / Canny / HoughLinesP)",
      "Optical Flow & Continuity (cv2.calcOpticalFlowFarneback / compareHist)",
    ]);
    const metricDetails = [...document.querySelectorAll("#res-opencv-metrics dd")].map((n) => n.textContent);
    expect(metricDetails[2]).toContain("pan-right");
    expect(metricDetails[2]).toContain("continuous-single-take");
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
