"use client";

import { useEffect, useRef } from "react";

const STAR_COUNT = 260;
const SEED = 7;
const RESIZE_DEBOUNCE_MS = 150;
const FALLBACK_STAR = "rgba(220, 225, 255, 0.55)";

/**
 * Static starfield (mockup `stars()`): drawn once, and again after a resize.
 * The PRNG restarts from the same seed on every draw, so stars keep their
 * relative places instead of jumping. The body paints the haze behind it.
 */
function drawStars(canvas: HTMLCanvasElement) {
  const ctx = canvas.getContext("2d");
  if (!ctx) return;

  const dpr = Math.min(2, window.devicePixelRatio || 1);
  const w = window.innerWidth;
  const h = window.innerHeight;
  canvas.width = w * dpr;
  canvas.height = h * dpr;
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  ctx.clearRect(0, 0, w, h);

  const star =
    getComputedStyle(document.documentElement).getPropertyValue("--bg-star").trim() ||
    FALLBACK_STAR;
  let s = SEED;
  const rand = () => (s = (s * 16807) % 2147483647) / 2147483647;

  ctx.fillStyle = star;
  for (let i = 0; i < STAR_COUNT; i++) {
    ctx.globalAlpha = 0.15 + rand() * 0.6;
    const r = rand() < 0.08 ? 1.4 : 0.8;
    ctx.beginPath();
    ctx.arc(rand() * w, rand() * h, r, 0, Math.PI * 2);
    ctx.fill();
  }
  ctx.globalAlpha = 1;
}

export default function Sky() {
  const canvasRef = useRef<HTMLCanvasElement>(null);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    drawStars(canvas);

    let timer: ReturnType<typeof setTimeout> | undefined;
    const onResize = () => {
      clearTimeout(timer);
      timer = setTimeout(() => drawStars(canvas), RESIZE_DEBOUNCE_MS);
    };
    window.addEventListener("resize", onResize);
    return () => {
      window.removeEventListener("resize", onResize);
      clearTimeout(timer);
    };
  }, []);

  return <canvas ref={canvasRef} className="sky" aria-hidden="true" />;
}
