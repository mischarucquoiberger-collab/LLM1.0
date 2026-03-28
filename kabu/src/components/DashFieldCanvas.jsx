import { useRef, useEffect } from "react";

/*
 * DashFieldCanvas — Ultra-premium interactive animated dash field
 *
 * 12-layer interaction system:
 *  1.  Dual-octave Perlin noise — organic breathing flow field
 *  2.  Per-dash angular inertia — smooth organic rotation with momentum
 *  3.  Cursor magnetic vortex — tangential+radial blend, velocity-adaptive
 *  4.  Cursor ghosts — past positions create interference patterns
 *  5.  Dwell orbital — dashes slowly orbit when cursor rests
 *  6.  Click shockwaves — expanding displacement rings
 *  7.  2D traveling wave — brightness/angle pulse across field
 *  8.  Dynamic sizing — length, width respond to influence
 *  9.  HSL color gradients — spectral transitions by proximity + velocity
 * 10.  Constellation mesh — grid neighbor connections appear near cursor
 * 11.  Cursor glow — soft radial spotlight follows mouse
 * 12.  Shimmer — close dashes sparkle with high-frequency oscillation
 */

/* ── Perlin noise 2D ────────────────────────────────────── */
const PERM = new Uint8Array(512);
const GRAD = [[1,1],[-1,1],[1,-1],[-1,-1],[1,0],[-1,0],[0,1],[0,-1]];
(function() {
  const p = new Uint8Array(256);
  for (let i = 0; i < 256; i++) p[i] = i;
  for (let i = 255; i > 0; i--) {
    const j = (Math.random() * (i + 1)) | 0;
    [p[i], p[j]] = [p[j], p[i]];
  }
  for (let i = 0; i < 512; i++) PERM[i] = p[i & 255];
})();

function fade(t) { return t * t * t * (t * (t * 6 - 15) + 10); }

function noise2D(x, y) {
  const X = Math.floor(x) & 255, Y = Math.floor(y) & 255;
  const xf = x - Math.floor(x), yf = y - Math.floor(y);
  const u = fade(xf), v = fade(yf);
  const dot = (g, a, b) => GRAD[g][0] * a + GRAD[g][1] * b;
  const aa = PERM[PERM[X] + Y] & 7, ab = PERM[PERM[X] + Y + 1] & 7;
  const ba = PERM[PERM[X + 1] + Y] & 7, bb = PERM[PERM[X + 1] + Y + 1] & 7;
  const x1 = dot(aa, xf, yf) + u * (dot(ba, xf - 1, yf) - dot(aa, xf, yf));
  const x2 = dot(ab, xf, yf - 1) + u * (dot(bb, xf - 1, yf - 1) - dot(ab, xf, yf - 1));
  return x1 + v * (x2 - x1);
}

/* ── HSL → RGB (CSS Color Level 4 algorithm) ───────────── */
function hslRgb(h, s, l) {
  const a = s * Math.min(l, 1 - l);
  const f = (n) => {
    const k = (n + h / 30) % 12;
    return l - a * Math.max(-1, Math.min(k - 3, 9 - k, 1));
  };
  return [Math.round(f(0) * 255), Math.round(f(8) * 255), Math.round(f(4) * 255)];
}

/* ── Grid config ───────────────────────────────────────── */
const SP        = 32;
const DASH_MIN  = 5.5;
const DASH_MAX  = 14;
const LW_MIN    = 1.1;
const LW_MAX    = 2.8;
const NOISE_SC  = 0.012;
const TIME_SP   = 0.08;

/* ── Interaction config ────────────────────────────────── */
const RADIUS    = 220;
const VORTEX_S  = 0.85;
const GHOST_N   = 6;
const GHOST_DK  = 0.92;
const CONST_A   = 0.14;
const MAX_RIP   = 6;
const RIP_DUR   = 2.5;
const RIP_MAX_R = 500;
const RIP_STR   = 0.75;
const INERTIA   = 0.07;
const WAVE_SP   = 0.35;
const WAVE_AMP  = 0.09;
const DWELL_T   = 1.2;
const ORBIT_SP  = 0.6;

/* ── Accent hash ───────────────────────────────────────── */
function isAccent(c, r) {
  const h = Math.sin(c * 127.1 + r * 311.7) * 43758.5453;
  return (h - Math.floor(h)) < 0.07;
}

export default function DashFieldCanvas({ className = "", style = {} }) {
  const canvasRef  = useRef(null);
  const animRef    = useRef(null);
  const mouseRef   = useRef({ x: -9999, y: -9999 });
  const smoothRef  = useRef({ x: -9999, y: -9999 });
  const prevRef    = useRef({ x: -9999, y: -9999 });
  const velRef     = useRef(0);
  const ghostsRef  = useRef([]);
  const ripplesRef = useRef([]);
  const scrollRef  = useRef(0);
  const anglesRef  = useRef(null);
  const gridRef    = useRef({ cols: 0, rows: 0 });
  const infRef     = useRef(null);
  const pxRef      = useRef(null);
  const pyRef      = useRef(null);

  useEffect(() => {
    const cvs = canvasRef.current;
    if (!cvs) return;
    const ctx = cvs.getContext("2d");
    let dpr = window.devicePixelRatio || 1;

    const resize = () => {
      dpr = window.devicePixelRatio || 1;
      const rect = cvs.getBoundingClientRect();
      cvs.width = rect.width * dpr;
      cvs.height = rect.height * dpr;
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
      const cols = Math.ceil(rect.width / SP) + 2;
      const rows = Math.ceil(rect.height / SP) + 2;
      gridRef.current = { cols, rows };
      const n = cols * rows;
      const old = anglesRef.current;
      anglesRef.current = new Float32Array(n);
      if (old) anglesRef.current.set(old.subarray(0, Math.min(old.length, n)));
      infRef.current = new Float32Array(n);
      pxRef.current  = new Float32Array(n);
      pyRef.current  = new Float32Array(n);
    };
    resize();
    window.addEventListener("resize", resize);

    const onMouse = (e) => { mouseRef.current.x = e.clientX; mouseRef.current.y = e.clientY; };
    const onLeave = () => { mouseRef.current.x = -9999; mouseRef.current.y = -9999; };
    window.addEventListener("mousemove", onMouse);
    window.addEventListener("mouseout", onLeave);

    const onClick = (e) => {
      const rip = ripplesRef.current;
      if (rip.length >= MAX_RIP) rip.shift();
      rip.push({ x: e.clientX, y: e.clientY, birth: performance.now() });
    };
    window.addEventListener("click", onClick);

    const onScroll = () => { scrollRef.current = window.scrollY; };
    window.addEventListener("scroll", onScroll, { passive: true });

    const t0 = performance.now();
    let lastGhostPush = 0;
    let lastMoveTime = 0;

    const tick = () => {
      const now = performance.now();
      const w = cvs.width / dpr;
      const h = cvs.height / dpr;
      const time = (now - t0) / 1000;

      /* ── Smooth mouse + velocity ── */
      const sm = smoothRef.current, tm = mouseRef.current, pm = prevRef.current;
      sm.x += (tm.x - sm.x) * 0.12;
      sm.y += (tm.y - sm.y) * 0.12;
      const vx = sm.x - pm.x, vy = sm.y - pm.y;
      velRef.current += (Math.min(Math.sqrt(vx * vx + vy * vy), 50) - velRef.current) * 0.1;
      pm.x = sm.x; pm.y = sm.y;
      const vel = velRef.current;
      const mouseOn = sm.x > -1000;

      /* ── Dwell tracking ── */
      if (vel > 2) lastMoveTime = time;
      const dwellTime = mouseOn ? time - lastMoveTime : 0;

      /* ── Cursor ghosts ── */
      const ghosts = ghostsRef.current;
      if (mouseOn && time - lastGhostPush > 0.07) {
        lastGhostPush = time;
        ghosts.push({ x: sm.x, y: sm.y, str: 1 });
        if (ghosts.length > GHOST_N) ghosts.shift();
      }
      for (const g of ghosts) g.str *= GHOST_DK;
      while (ghosts.length && ghosts[0].str < 0.01) ghosts.shift();

      /* ── Expire ripples ── */
      const ripples = ripplesRef.current;
      while (ripples.length && (now - ripples[0].birth) / 1000 > RIP_DUR) ripples.shift();

      const scrollOff = scrollRef.current * 0.04;
      ctx.clearRect(0, 0, w, h);

      const mx = sm.x, my = sm.y;
      const dynR = RADIUS + vel * 4;

      /* ── Cursor glow (soft radial spotlight) ── */
      if (mouseOn) {
        const gr = dynR * 1.4;
        const grd = ctx.createRadialGradient(mx, my, 0, mx, my, gr);
        grd.addColorStop(0, "rgba(0,60,200,0.055)");
        grd.addColorStop(0.4, "rgba(0,60,200,0.025)");
        grd.addColorStop(1, "rgba(0,60,200,0)");
        ctx.fillStyle = grd;
        ctx.beginPath();
        ctx.arc(mx, my, gr, 0, Math.PI * 2);
        ctx.fill();
      }

      const { cols, rows } = gridRef.current;
      const offX = ((w - (cols - 1) * SP) / 2) | 0;
      const offY = ((h - (rows - 1) * SP) / 2) | 0;
      ctx.lineCap = "round";

      const angles = anglesRef.current;
      const infMap = infRef.current;
      const pxA = pxRef.current;
      const pyA = pyRef.current;
      const wPh = time * WAVE_SP;

      /* ══════════════════════════════════════════════════
       *  MAIN DASH LOOP
       * ══════════════════════════════════════════════════ */
      for (let r = 0; r < rows; r++) {
        for (let c = 0; c < cols; c++) {
          const idx = r * cols + c;
          const bx = offX + c * SP;
          const by = offY + r * SP + scrollOff;

          /* ── 1. Perlin noise base ── */
          const n1 = noise2D(c * NOISE_SC + time * TIME_SP, r * NOISE_SC + time * TIME_SP * 0.55);
          const n2 = noise2D(c * NOISE_SC * 2.1 + 50 + time * TIME_SP * 0.35,
                             r * NOISE_SC * 2.1 + 50 + time * TIME_SP * 0.25);
          let tgt = (n1 + n2 * 0.45) * Math.PI;

          let inf = 0;
          let dispX = 0, dispY = 0;

          /* ── 2. Traveling wave ── */
          tgt += Math.sin(wPh + (bx + by) * 0.007) * WAVE_AMP;

          /* ── 3–4. Cursor vortex + dwell orbital ── */
          if (mouseOn) {
            const dx = mx - bx, dy = my - by;
            const dist = Math.sqrt(dx * dx + dy * dy);

            if (dist < dynR && dist > 1) {
              const t = 1 - dist / dynR;
              const si = t * t * (3 - 2 * t);
              inf = Math.max(inf, si);

              const rad = Math.atan2(dy, dx);
              const tan = rad + Math.PI * 0.5;
              const blend = 0.3 + Math.min(vel / 25, 0.35) + t * 0.2;
              const target = tan * blend + rad * (1 - blend);
              let d = target - tgt;
              while (d > Math.PI) d -= Math.PI * 2;
              while (d < -Math.PI) d += Math.PI * 2;
              tgt += d * si * VORTEX_S;

              const push = si * si * 4;
              dispX += (bx - mx) / dist * push;
              dispY += (by - my) / dist * push;
            }

            /* Dwell orbital */
            if (dwellTime > DWELL_T && dist < RADIUS * 0.6 && dist > 1) {
              const dt = 1 - dist / (RADIUS * 0.6);
              const fade = Math.min((dwellTime - DWELL_T) / 2, 1);
              const oAngle = Math.atan2(dy, dx) + time * ORBIT_SP + dist * 0.015;
              let od = oAngle - tgt;
              while (od > Math.PI) od -= Math.PI * 2;
              while (od < -Math.PI) od += Math.PI * 2;
              tgt += od * dt * dt * fade * 0.35;
            }
          }

          /* ── 5. Ghost interference ── */
          for (const g of ghosts) {
            if (g.str < 0.03) continue;
            const gx = g.x - bx, gy = g.y - by;
            const gd = Math.sqrt(gx * gx + gy * gy);
            const gR = RADIUS * 0.65;
            if (gd < gR && gd > 1) {
              const gt = 1 - gd / gR;
              const gi = gt * gt * g.str;
              const ga = Math.atan2(gy, gx) + Math.PI * 0.5;
              let dd = ga - tgt;
              while (dd > Math.PI) dd -= Math.PI * 2;
              while (dd < -Math.PI) dd += Math.PI * 2;
              tgt += dd * gi * 0.4;
              inf = Math.max(inf, gi * 0.35);
            }
          }

          /* ── 6. Click shockwaves ── */
          for (const rip of ripples) {
            const age = (now - rip.birth) / 1000;
            const ripR = (age / RIP_DUR) * RIP_MAX_R;
            const rx = bx - rip.x, ry = by - rip.y;
            const rd = Math.sqrt(rx * rx + ry * ry);
            const rw = 80 + age * 40;
            const ring = Math.abs(rd - ripR);
            if (ring < rw) {
              const rf = 1 - age / RIP_DUR;
              const rt = (1 - ring / rw) * rf * rf;
              const oa = Math.atan2(ry, rx);
              let dd = oa - tgt;
              while (dd > Math.PI) dd -= Math.PI * 2;
              while (dd < -Math.PI) dd += Math.PI * 2;
              tgt += dd * rt * RIP_STR;
              inf = Math.max(inf, rt * 0.7);
              if (rd > 1) {
                dispX += rx / rd * rt * 6;
                dispY += ry / rd * rt * 6;
              }
            }
          }

          /* ── 7. Angular inertia ── */
          let cur = angles[idx] || 0;
          let ad = tgt - cur;
          while (ad > Math.PI) ad -= Math.PI * 2;
          while (ad < -Math.PI) ad += Math.PI * 2;
          cur += ad * (INERTIA + inf * 0.18);
          angles[idx] = cur;

          /* ── 8. Dynamic sizing ── */
          const halfLen = DASH_MIN + inf * (DASH_MAX - DASH_MIN);
          const lw = LW_MIN + inf * (LW_MAX - LW_MIN);

          /* Final position */
          const fx = bx + dispX;
          const fy = by + dispY;
          infMap[idx] = inf;
          pxA[idx] = fx;
          pyA[idx] = fy;

          /* ── 9. HSL color ── */
          const acc = isAccent(c, r);
          let hu, sa, li, al;

          if (mouseOn) {
            const dh = Math.sqrt((mx - bx) * (mx - bx) + (my - by) * (my - by));
            if (dh < dynR * 1.2) {
              const ht = 1 - dh / (dynR * 1.2);
              const b = ht * ht;
              hu = 225 - b * 30 - Math.min(vel / 25, 1) * 25 * b;
              sa = 0.7 + b * 0.3;
              li = 0.28 + b * 0.35;
              al = 0.25 + b * 0.65;
            } else {
              hu = acc ? 225 : 220; sa = acc ? 0.85 : 0.15;
              li = acc ? 0.38 : 0.58; al = acc ? 0.4 : 0.22;
            }
          } else {
            hu = acc ? 225 : 220; sa = acc ? 0.85 : 0.15;
            li = acc ? 0.38 : 0.58; al = acc ? 0.4 : 0.22;
          }

          /* Wave brightness modulation */
          al *= 0.92 + 0.08 * (0.5 + 0.5 * Math.sin(wPh * 2.5 + (bx + by) * 0.005));

          /* Shimmer for close dashes */
          if (inf > 0.55) {
            al *= 0.82 + 0.18 * Math.sin(time * 9 + idx * 1.7);
          }

          /* Ripple color boost */
          for (const rip of ripples) {
            const age = (now - rip.birth) / 1000;
            const ripR = (age / RIP_DUR) * RIP_MAX_R;
            const rd = Math.sqrt((bx - rip.x) * (bx - rip.x) + (by - rip.y) * (by - rip.y));
            const ring = Math.abs(rd - ripR);
            const rw = 60 + age * 30;
            if (ring < rw) {
              const rf = 1 - age / RIP_DUR;
              const rt = (1 - ring / rw) * rf;
              al = Math.min(1, al + rt * 0.5);
              li = Math.min(0.7, li + rt * 0.2);
              sa = Math.min(1, sa + rt * 0.15);
            }
          }

          const [cr, cg, cb] = hslRgb(hu, sa, li);
          const cosA = Math.cos(cur), sinA = Math.sin(cur);
          const ex = cosA * halfLen, ey = sinA * halfLen;

          ctx.lineWidth = lw;
          ctx.strokeStyle = `rgba(${cr},${cg},${cb},${al})`;
          ctx.beginPath();
          ctx.moveTo(fx - ex, fy - ey);
          ctx.lineTo(fx + ex, fy + ey);
          ctx.stroke();
        }
      }

      /* ══════════════════════════════════════════════════
       *  CONSTELLATION MESH
       * ══════════════════════════════════════════════════ */
      const cTh = 0.08;
      for (let r = 0; r < rows; r++) {
        for (let c = 0; c < cols; c++) {
          const idx = r * cols + c;
          const inf = infMap[idx];
          if (inf < cTh) continue;

          /* Right neighbor */
          if (c + 1 < cols) {
            const ri = idx + 1;
            if (infMap[ri] >= cTh) {
              const s = Math.min(inf, infMap[ri]);
              const a = s * CONST_A;
              if (a > 0.003) {
                ctx.lineWidth = 0.4 + s * 0.7;
                ctx.strokeStyle = `rgba(0,70,210,${a})`;
                ctx.beginPath();
                ctx.moveTo(pxA[idx], pyA[idx]);
                ctx.lineTo(pxA[ri], pyA[ri]);
                ctx.stroke();
              }
            }
          }

          /* Bottom neighbor */
          if (r + 1 < rows) {
            const bi = (r + 1) * cols + c;
            if (infMap[bi] >= cTh) {
              const s = Math.min(inf, infMap[bi]);
              const a = s * CONST_A;
              if (a > 0.003) {
                ctx.lineWidth = 0.4 + s * 0.7;
                ctx.strokeStyle = `rgba(0,70,210,${a})`;
                ctx.beginPath();
                ctx.moveTo(pxA[idx], pyA[idx]);
                ctx.lineTo(pxA[bi], pyA[bi]);
                ctx.stroke();
              }
            }
          }

          /* Diagonal (bottom-right) — weaker */
          if (c + 1 < cols && r + 1 < rows) {
            const di = (r + 1) * cols + c + 1;
            if (infMap[di] >= cTh * 1.5) {
              const s = Math.min(inf, infMap[di]) * 0.5;
              const a = s * CONST_A;
              if (a > 0.003) {
                ctx.lineWidth = 0.3 + s * 0.5;
                ctx.strokeStyle = `rgba(0,70,210,${a})`;
                ctx.beginPath();
                ctx.moveTo(pxA[idx], pyA[idx]);
                ctx.lineTo(pxA[di], pyA[di]);
                ctx.stroke();
              }
            }
          }
        }
      }

      animRef.current = requestAnimationFrame(tick);
    };

    animRef.current = requestAnimationFrame(tick);

    return () => {
      if (animRef.current) cancelAnimationFrame(animRef.current);
      window.removeEventListener("resize", resize);
      window.removeEventListener("mousemove", onMouse);
      window.removeEventListener("mouseout", onLeave);
      window.removeEventListener("click", onClick);
      window.removeEventListener("scroll", onScroll);
    };
  }, []);

  return (
    <canvas
      ref={canvasRef}
      className={className}
      style={{
        position: "fixed", inset: 0,
        width: "100%", height: "100%",
        pointerEvents: "none",
        ...style,
      }}
    />
  );
}
