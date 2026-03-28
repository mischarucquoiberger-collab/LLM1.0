import { useRef, useEffect } from "react";

/* ── Simplex 2D noise ──────────────────────────────────────────
   Compact implementation based on Stefan Gustavson's algorithm.
   Returns values in roughly [−1, 1].                            */
const F2 = 0.5 * (Math.sqrt(3) - 1);
const G2 = (3 - Math.sqrt(3)) / 6;
const GRAD = [[1,1],[-1,1],[1,-1],[-1,-1],[1,0],[-1,0],[0,1],[0,-1]];

function createNoise(seed = 0) {
  const perm = new Uint8Array(512);
  const p = new Uint8Array(256);
  for (let i = 0; i < 256; i++) p[i] = i;
  let s = (seed * 16807 + 1) | 0;
  for (let i = 255; i > 0; i--) {
    s = (s * 16807) % 2147483647;
    const j = s % (i + 1);
    const tmp = p[i]; p[i] = p[j]; p[j] = tmp;
  }
  for (let i = 0; i < 512; i++) perm[i] = p[i & 255];

  return (x, y) => {
    const sk = (x + y) * F2;
    const i = Math.floor(x + sk), j = Math.floor(y + sk);
    const t = (i + j) * G2;
    const x0 = x - (i - t), y0 = y - (j - t);
    const i1 = x0 > y0 ? 1 : 0, j1 = x0 > y0 ? 0 : 1;
    const x1 = x0 - i1 + G2, y1 = y0 - j1 + G2;
    const x2 = x0 - 1 + 2 * G2, y2 = y0 - 1 + 2 * G2;
    const ii = i & 255, jj = j & 255;
    const gi0 = perm[ii + perm[jj]] & 7;
    const gi1 = perm[ii + i1 + perm[jj + j1]] & 7;
    const gi2 = perm[ii + 1 + perm[jj + 1]] & 7;
    let n0 = 0, n1 = 0, n2 = 0;
    let t0 = 0.5 - x0 * x0 - y0 * y0;
    if (t0 > 0) { t0 *= t0; n0 = t0 * t0 * (GRAD[gi0][0] * x0 + GRAD[gi0][1] * y0); }
    let t1 = 0.5 - x1 * x1 - y1 * y1;
    if (t1 > 0) { t1 *= t1; n1 = t1 * t1 * (GRAD[gi1][0] * x1 + GRAD[gi1][1] * y1); }
    let t2 = 0.5 - x2 * x2 - y2 * y2;
    if (t2 > 0) { t2 *= t2; n2 = t2 * t2 * (GRAD[gi2][0] * x2 + GRAD[gi2][1] * y2); }
    return 70 * (n0 + n1 + n2);
  };
}

/* ── Configuration ─────────────────────────────────────────── */
const SPACING = 28;
const BASE_DASH = 10;
const DASH_WIDTH = 1.2;
const NOISE_SCALE = 0.006;
const TIME_SPEED = 0.00015;

// Cursor
const CURSOR_R = 260;
const CURSOR_R2 = CURSOR_R * CURSOR_R;
const LERP_BASE = 0.065;

// Mouse trail
const TRAIL_MAX = 14;
const TRAIL_R = 140;
const TRAIL_R2 = TRAIL_R * TRAIL_R;
const TRAIL_SAMPLE = 3; // sample every N frames

// Click ripple
const RIPPLE_SPEED = 380;
const RIPPLE_BAND = 90;
const RIPPLE_LIFE = 1400;

// Color transition shockwave
const COLOR_WAVE_DURATION = 2000; // ms for the wave to fully expand
const COLOR_WAVE_BAND = 160;     // width of the glowing wavefront edge

/* ── Color palettes ──────────────────────────────────────────── */
// Blue palette (Min mode) — deeper blue on white bg
const BLUE = { rBase: 40, rRange: 20, rBoost: 50, gBase: 70, gRange: 30, gBoost: 60, bBase: 200, bRange: 30, bBoost: 10 };
// Golden/amber palette (Max mode) — warm gold on white bg
const ORANGE = { rBase: 215, rRange: 15, rBoost: 15, gBase: 170, gRange: 25, gBoost: 30, bBase: 50, bRange: 15, bBoost: 10 };

function lerpColor(a, b, t) {
  return {
    rBase: a.rBase + (b.rBase - a.rBase) * t,
    rRange: a.rRange + (b.rRange - a.rRange) * t,
    rBoost: a.rBoost + (b.rBoost - a.rBoost) * t,
    gBase: a.gBase + (b.gBase - a.gBase) * t,
    gRange: a.gRange + (b.gRange - a.gRange) * t,
    gBoost: a.gBoost + (b.gBoost - a.gBoost) * t,
    bBase: a.bBase + (b.bBase - a.bBase) * t,
    bRange: a.bRange + (b.bRange - a.bRange) * t,
    bBoost: a.bBoost + (b.bBoost - a.bBoost) * t,
  };
}

// Ease-out cubic for smooth deceleration
function easeOutCubic(t) { return 1 - (1 - t) * (1 - t) * (1 - t); }

export default function FlowFieldBackground({ paused = false, colorMode = "blue" }) {
  const canvasRef = useRef(null);
  const pausedRef = useRef(paused);
  const colorModeRef = useRef(colorMode);
  const stateRef = useRef({
    mouse: { x: -9999, y: -9999 },
    trail: [],
    ripples: [],
    frame: 0,
    raf: 0,
    // Color transition state
    colorWave: null,       // { t0, fromColor, toColor, cx, cy, maxRadius }
    settledColor: colorMode === "stream" ? ORANGE : BLUE,
  });

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext("2d", { alpha: true });
    const noise = createNoise(42);
    const noise2 = createNoise(137);
    const st = stateRef.current;

    let dpr, W, H, cols, rows, angles, offX, offY, canvasRect;

    const resize = () => {
      dpr = window.devicePixelRatio || 1;
      const parent = canvas.parentElement;
      if (!parent) return;
      W = parent.clientWidth;
      H = parent.clientHeight;
      canvas.width = W * dpr;
      canvas.height = H * dpr;
      canvas.style.width = W + "px";
      canvas.style.height = H + "px";
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
      canvasRect = canvas.getBoundingClientRect();

      cols = Math.ceil(W / SPACING) + 2;
      rows = Math.ceil(H / SPACING) + 2;
      offX = (W - (cols - 1) * SPACING) / 2;
      offY = (H - (rows - 1) * SPACING) / 2;

      const total = cols * rows;
      const prev = angles;
      angles = new Float32Array(total);
      if (prev) {
        const len = Math.min(prev.length, total);
        for (let i = 0; i < len; i++) angles[i] = prev[i];
      }
    };

    const ro = new ResizeObserver(resize);
    if (canvas.parentElement) ro.observe(canvas.parentElement);
    resize();

    const onMove = (e) => {
      if (!canvasRect) return;
      st.mouse.x = e.clientX - canvasRect.left;
      st.mouse.y = e.clientY - canvasRect.top;
    };
    const onLeave = () => {
      st.mouse.x = -9999;
      st.mouse.y = -9999;
      st.trail.length = 0;
    };
    const onClick = (e) => {
      if (!canvasRect) return;
      st.ripples.push({
        x: e.clientX - canvasRect.left,
        y: e.clientY - canvasRect.top,
        t0: performance.now(),
      });
      if (st.ripples.length > 5) st.ripples.shift();
    };

    window.addEventListener("mousemove", onMove, { passive: true });
    window.addEventListener("mouseleave", onLeave, { passive: true });
    window.addEventListener("click", onClick, { passive: true });

    const TWO_PI = Math.PI * 2;

    const draw = (now) => {
      if (pausedRef.current || !angles) { st.raf = requestAnimationFrame(draw); return; }
      const t = now * TIME_SPEED;
      const mx = st.mouse.x;
      const my = st.mouse.y;

      // Sample mouse trail
      st.frame++;
      if (st.frame % TRAIL_SAMPLE === 0 && mx > -1000) {
        st.trail.push({ x: mx, y: my });
        if (st.trail.length > TRAIL_MAX) st.trail.shift();
      }

      // Expire old ripples
      const ripples = st.ripples;
      for (let i = ripples.length - 1; i >= 0; i--) {
        if (now - ripples[i].t0 >= RIPPLE_LIFE) ripples.splice(i, 1);
      }

      // ── Color wave transition state ──
      const wave = st.colorWave;
      let waveProgress = -1; // -1 means no active wave
      let waveRadius = 0;
      let waveCx = 0, waveCy = 0;
      if (wave) {
        const elapsed = now - wave.t0;
        const rawP = Math.min(elapsed / COLOR_WAVE_DURATION, 1);
        waveProgress = easeOutCubic(rawP);
        waveRadius = waveProgress * wave.maxRadius;
        waveCx = wave.cx;
        waveCy = wave.cy;
        if (rawP >= 1) {
          // Wave complete — settle into new color
          st.settledColor = wave.toColor;
          st.colorWave = null;
        }
      }

      ctx.clearRect(0, 0, W, H);
      ctx.lineCap = "round";

      const trail = st.trail;
      const trailLen = trail.length;
      const settled = st.settledColor;

      for (let row = 0; row < rows; row++) {
        const y = offY + row * SPACING;
        const rN = row * NOISE_SCALE * SPACING;

        for (let col = 0; col < cols; col++) {
          const idx = row * cols + col;
          const x = offX + col * SPACING;
          const cN = col * NOISE_SCALE * SPACING;

          // ── Base angle from dual-layer noise ──
          const n1 = noise(cN + t, rN + t * 0.6);
          const n2 = noise2(cN * 1.7 - t * 0.4, rN * 1.7 + t * 0.3);
          let target = (n1 + n2 * 0.4) * Math.PI * 1.4;

          let maxInfluence = 0;

          // ── Cursor influence ──
          const dx = x - mx;
          const dy = y - my;
          const dist2 = dx * dx + dy * dy;
          let cursorInf = 0;

          if (dist2 < CURSOR_R2) {
            const dist = Math.sqrt(dist2);
            const norm = 1 - dist / CURSOR_R;
            cursorInf = norm * norm;
            const away = Math.atan2(dy, dx);
            let diff = away - target;
            while (diff > Math.PI) diff -= TWO_PI;
            while (diff < -Math.PI) diff += TWO_PI;
            target += diff * cursorInf * 0.9;
            maxInfluence = cursorInf;
          }

          // ── Trail influence ──
          let trailInf = 0;
          let trailAway = 0;
          for (let ti = 0; ti < trailLen; ti++) {
            const tp = trail[ti];
            const tdx = x - tp.x;
            const tdy = y - tp.y;
            const td2 = tdx * tdx + tdy * tdy;
            if (td2 < TRAIL_R2) {
              const td = Math.sqrt(td2);
              const age = (ti + 1) / trailLen;
              const prox = (1 - td / TRAIL_R);
              const inf = prox * prox * age * 0.45;
              if (inf > trailInf) {
                trailInf = inf;
                trailAway = Math.atan2(tdy, tdx);
              }
            }
          }
          if (trailInf > 0) {
            let diff = trailAway - target;
            while (diff > Math.PI) diff -= TWO_PI;
            while (diff < -Math.PI) diff += TWO_PI;
            target += diff * trailInf * 0.6;
          }
          if (trailInf > maxInfluence) maxInfluence = trailInf;

          // ── Ripple influence ──
          let rippleInf = 0;
          let rippleAway = 0;
          for (let ri = 0; ri < ripples.length; ri++) {
            const rip = ripples[ri];
            const rdx = x - rip.x;
            const rdy = y - rip.y;
            const rdist = Math.sqrt(rdx * rdx + rdy * rdy);
            const elapsed = now - rip.t0;
            const ringR = (elapsed / 1000) * RIPPLE_SPEED;
            const fromRing = Math.abs(rdist - ringR);
            if (fromRing < RIPPLE_BAND) {
              const fade = 1 - elapsed / RIPPLE_LIFE;
              const ring = (1 - fromRing / RIPPLE_BAND) * fade * fade;
              if (ring > rippleInf) {
                rippleInf = ring;
                rippleAway = Math.atan2(rdy, rdx);
              }
            }
          }
          if (rippleInf > 0) {
            let diff = rippleAway - target;
            while (diff > Math.PI) diff -= TWO_PI;
            while (diff < -Math.PI) diff += TWO_PI;
            target += diff * rippleInf * 0.75;
          }
          if (rippleInf > maxInfluence) maxInfluence = rippleInf;

          // ── Smooth lerp ──
          const lerp = LERP_BASE + maxInfluence * 0.18;
          let aDiff = target - angles[idx];
          while (aDiff > Math.PI) aDiff -= TWO_PI;
          while (aDiff < -Math.PI) aDiff += TWO_PI;
          angles[idx] += aDiff * lerp;

          const a = angles[idx];
          const cosA = Math.cos(a);
          const sinA = Math.sin(a);

          // ── Dynamic dash length ──
          let dashLen = BASE_DASH + maxInfluence * 8;
          const half = dashLen / 2;

          // ── Opacity ──
          const opN = noise(col * 0.04 + t * 0.3, row * 0.04 - t * 0.15) * 0.5 + 0.5;
          let alpha = 0.25 + opN * 0.13;
          alpha += cursorInf * 0.42;
          alpha += trailInf * 0.3;
          alpha += rippleInf * 0.4;

          // ── Color: blend based on color wave ──
          const hN = noise2(col * 0.02 + t * 0.08, row * 0.02) * 0.5 + 0.5;
          const boost = maxInfluence * 0.6;
          let pal = settled;
          let wavefrontGlow = 0;

          if (wave && waveProgress >= 0) {
            // Distance from this point to wave center
            const wdx = x - waveCx;
            const wdy = y - waveCy;
            const wDist = Math.sqrt(wdx * wdx + wdy * wdy);

            // How far inside the wave radius is this point?
            const inside = waveRadius - wDist;

            if (inside > COLOR_WAVE_BAND) {
              // Fully inside the wave — use target color
              pal = wave.toColor;
            } else if (inside > 0) {
              // In the wavefront band — blend + glow
              const bandT = inside / COLOR_WAVE_BAND;
              // Smooth step for color blend
              const smoothT = bandT * bandT * (3 - 2 * bandT);
              pal = lerpColor(wave.fromColor, wave.toColor, smoothT);

              // Wavefront glow: peaks at the edge, creating a bright ring
              const glowT = 1 - bandT; // 1.0 at outer edge, 0.0 deep inside
              wavefrontGlow = glowT * glowT * (1 - waveProgress * 0.3); // fades as wave completes
            } else if (inside > -COLOR_WAVE_BAND * 0.4) {
              // Just ahead of the wave — subtle anticipation glow
              const aheadT = 1 + inside / (COLOR_WAVE_BAND * 0.4);
              wavefrontGlow = aheadT * aheadT * 0.3 * (1 - waveProgress);
              pal = settled; // keep old color
            }
            // else: fully outside the wave — keep settled color
          }

          // Apply wavefront effects
          alpha += wavefrontGlow * 0.55;
          if (alpha > 0.95) alpha = 0.95;

          const cr = Math.round(pal.rBase + hN * pal.rRange + boost * pal.rBoost);
          const cg = Math.round(pal.gBase + hN * pal.gRange + boost * pal.gBoost);
          const cb = Math.round(pal.bBase + hN * pal.bRange + boost * pal.bBoost);

          // Wavefront makes lines temporarily longer and thicker
          const waveScale = 1 + wavefrontGlow * 1.8;
          const finalHalf = half * waveScale;
          const finalWidth = (DASH_WIDTH + maxInfluence * 0.6) * (1 + wavefrontGlow * 0.8);

          ctx.strokeStyle = `rgba(${Math.min(cr, 255)},${Math.min(cg, 255)},${Math.min(cb, 255)},${alpha})`;
          ctx.lineWidth = finalWidth;
          ctx.beginPath();
          ctx.moveTo(x - cosA * finalHalf, y - sinA * finalHalf);
          ctx.lineTo(x + cosA * finalHalf, y + sinA * finalHalf);
          ctx.stroke();
        }
      }

      st.raf = requestAnimationFrame(draw);
    };

    st.raf = requestAnimationFrame(draw);

    return () => {
      cancelAnimationFrame(st.raf);
      ro.disconnect();
      window.removeEventListener("mousemove", onMove);
      window.removeEventListener("mouseleave", onLeave);
      window.removeEventListener("click", onClick);
    };
  }, []);

  useEffect(() => { pausedRef.current = paused; }, [paused]);

  // Trigger color wave when colorMode changes
  useEffect(() => {
    const prev = colorModeRef.current;
    colorModeRef.current = colorMode;
    if (prev === colorMode) return; // no change

    const st = stateRef.current;
    const canvas = canvasRef.current;

    // If a wave is already in progress, settle it instantly to avoid snap-back
    if (st.colorWave) {
      st.settledColor = st.colorWave.toColor;
      st.colorWave = null;
    }

    const fromColor = st.settledColor;
    const toColor = colorMode === "stream" ? ORANGE : BLUE;

    // Wave emanates from center of canvas
    let cx = 0, cy = 0, maxRadius = 800;
    if (canvas) {
      const rect = canvas.getBoundingClientRect();
      cx = rect.width / 2;
      cy = rect.height / 2;
      // Max radius = distance from center to furthest corner
      maxRadius = Math.sqrt(cx * cx + cy * cy) + COLOR_WAVE_BAND;
    }

    st.colorWave = {
      t0: performance.now(),
      fromColor,
      toColor,
      cx,
      cy,
      maxRadius,
    };
  }, [colorMode]);

  return (
    <canvas
      ref={canvasRef}
      className="absolute inset-0 pointer-events-none"
      aria-hidden="true"
    />
  );
}
