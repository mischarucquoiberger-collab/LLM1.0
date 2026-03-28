import { createContext, useContext, useEffect, useRef, useCallback } from "react";
import { gsap } from "gsap";

/* ── Context: lets Landing know when splash is done ── */
export const SplashContext = createContext({ splashDone: false });
export const useSplash = () => useContext(SplashContext);

/* ── Preload assets during splash ── */
function preloadAssets() {
  // 1. Force-load Space Grotesk variable font at all key weights
  //    This is the main bottleneck (~2s) — trigger it immediately
  const fontFamilies = ["Space Grotesk", "Cormorant Garamond"];
  const weights = [300, 400, 500, 600, 700];
  fontFamilies.forEach((family) => {
    weights.forEach((w) => {
      document.fonts.load(`${w} 1em "${family}"`).catch(() => {});
    });
  });

  // 2. Warm GSAP internal pools with a throwaway tween
  const warmup = document.createElement("div");
  warmup.style.cssText = "position:fixed;left:-9999px;opacity:0;pointer-events:none";
  document.body.appendChild(warmup);
  gsap.to(warmup, { x: 1, duration: 0.01, onComplete: () => warmup.remove() });

  // 3. Prefetch backend TCP/TLS handshake
  fetch("/api/health", { method: "HEAD", mode: "no-cors" }).catch(() => {});

  // 4. Pre-render: force a layout calculation so metrics are cached
  document.body.offsetHeight;
}

export default function SplashScreen({ onDone }) {
  const rootRef = useRef(null);
  const hasFired = useRef(false);
  const effectRan = useRef(false);

  const signalDone = useCallback(() => {
    if (hasFired.current) return;
    hasFired.current = true;
    onDone();
  }, [onDone]);

  useEffect(() => {
    const root = rootRef.current;
    if (!root || effectRan.current) return;
    effectRan.current = true;

    // ── Kick off preloading immediately ──
    preloadAssets();

    // ── Reduced-motion: skip animation, just preload + signal done ──
    if (window.matchMedia("(prefers-reduced-motion: reduce)").matches) {
      document.fonts.ready.then(signalDone);
      return;
    }

    // Track font readiness
    let fontsReady = false;
    document.fonts.ready.then(() => { fontsReady = true; });

    // ── Generate counter-3 digits (0-9 × 2 + final 0 = 21 nums) ──
    const c3 = root.querySelector(".splash-counter-3");
    for (let i = 0; i < 2; i++) {
      for (let j = 0; j < 10; j++) {
        const d = document.createElement("div");
        d.className = "splash-num";
        d.textContent = j;
        c3.appendChild(d);
      }
    }
    const last = document.createElement("div");
    last.className = "splash-num";
    last.textContent = "0";
    c3.appendChild(last);

    // ── Counter animation helper ──
    const animateDigit = (counter, duration, delay = 0) => {
      const numEl = counter.querySelector(".splash-num");
      if (!numEl) return;
      const h = numEl.clientHeight;
      const total = (counter.querySelectorAll(".splash-num").length - 1) * h;
      gsap.to(counter, { y: -total, duration, delay, ease: "power2.inOut" });
    };

    // ═══════════════════════════════════════════
    // PHASE 1 — Counter + Loader fill  (0 → 3s)
    // ═══════════════════════════════════════════
    animateDigit(c3, 2.5);
    animateDigit(root.querySelector(".splash-counter-2"), 3);
    animateDigit(root.querySelector(".splash-counter-1"), 1, 2);

    gsap.from(root.querySelector(".splash-loader-1"), {
      width: 0, duration: 3, ease: "power2.inOut",
    });
    gsap.from(root.querySelector(".splash-loader-2"), {
      width: 0, duration: 3, delay: 0.95, ease: "power2.inOut",
    });

    // ═══════════════════════════════════════════
    // PHASE 2 — Bars split + reveal  (3s → 4s)
    //   Only starts after fonts are loaded
    // ═══════════════════════════════════════════
    const playPhase2 = () => {
      const loader  = root.querySelector(".splash-loader");
      const bar1    = root.querySelector(".splash-loader-1");
      const bar2    = root.querySelector(".splash-loader-2");
      const digits  = root.querySelectorAll(".splash-digit");

      // ★ mix-blend-mode: multiply — white bar pixels become transparent
      //   windows showing the website, black bg stays opaque.
      //   As bars split/rotate/scale/fly, the window shapes follow them.
      root.style.mixBlendMode = "multiply";

      // Digits slide up out of clip-path
      gsap.to(digits, {
        top: "-150px", stagger: { amount: 0.12 },
        duration: 0.5, ease: "power4.inOut",
      });

      // Loader bars split apart
      gsap.to(loader, { background: "none", duration: 0.05 });
      gsap.to(bar1, { rotate: 90, y: -50, duration: 0.3 });
      gsap.to(bar2, { x: -75, y: 75, duration: 0.3 });

      // Loader scales up and flies off
      gsap.to(loader, {
        scale: 40, duration: 0.5, delay: 0.5, ease: "power2.inOut",
      });
      gsap.to(loader, {
        rotate: 45, y: 500, x: 2000, duration: 0.5, delay: 0.5, ease: "power2.inOut",
      });

      // Fade out entire splash screen → signal done when fully faded
      gsap.to(root, {
        opacity: 0, duration: 0.3, delay: 0.8, ease: "power1.inOut",
        onComplete: signalDone,
      });
    };

    // Gate phase 2 on both animation time AND font loading
    let cleanupPoll;
    const gate = gsap.delayedCall(3, () => {
      if (fontsReady) {
        playPhase2();
      } else {
        // Rare edge case: fonts still loading — wait
        let pollActive = true;
        const poll = () => {
          if (!pollActive) return;
          if (fontsReady) playPhase2();
          else requestAnimationFrame(poll);
        };
        requestAnimationFrame(poll);
        cleanupPoll = () => { pollActive = false; };
      }
    });
    // Cleanup: kill splash tweens + delayed call (scoped, not app-wide)
    return () => {
      gate.kill();
      if (cleanupPoll) cleanupPoll();
      if (root) {
        gsap.killTweensOf(root);
        root.querySelectorAll("*").forEach((el) => gsap.killTweensOf(el));
      }
    };
  }, [signalDone]);

  return (
    <div ref={rootRef} className="splash-screen" style={{ zIndex: 99999 }}>
      {/* Centered loader bar */}
      <div className="splash-loader">
        <div className="splash-loader-1 splash-bar" />
        <div className="splash-loader-2 splash-bar" />
      </div>

      {/* Bottom-left counter: 000 → 100 */}
      <div className="splash-counter">
        <div className="splash-counter-1 splash-digit">
          <div className="splash-num">0</div>
          <div className="splash-num splash-num1offset1">1</div>
        </div>
        <div className="splash-counter-2 splash-digit">
          <div className="splash-num">0</div>
          <div className="splash-num splash-num1offset2">1</div>
          {[2, 3, 4, 5, 6, 7, 8, 9, 0].map((n, i) => (
            <div key={i} className="splash-num">{n}</div>
          ))}
        </div>
        <div className="splash-counter-3 splash-digit" />
      </div>
    </div>
  );
}
