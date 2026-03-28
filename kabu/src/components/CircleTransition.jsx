import { createContext, useContext, useState, useRef, useCallback, useEffect } from "react";
import { useNavigate } from "react-router-dom";
import FlowFieldBackground from "@/components/FlowFieldBackground";

const Ctx = createContext(null);

export function useCircleTransition() {
  return useContext(Ctx);
}

const EXPAND_MS = 900;
const FADE_MS = 500;

export function CircleTransitionProvider({ children }) {
  const navigate = useNavigate();

  const [ov, setOv] = useState(null);
  // ov = { cx, cy, phase }
  // phases: mount → expand → fade → null

  const targetRef = useRef(null);
  const busyRef = useRef(false);

  /* ── Public API ── */
  const navigateWithReveal = useCallback(
    (urlOrPromise, event, opts) => {
      const animate = opts?.animate === true;

      // No animation — navigate immediately (default)
      if (!animate) {
        if (typeof urlOrPromise === "string") {
          navigate(urlOrPromise);
        } else if (urlOrPromise && typeof urlOrPromise.then === "function") {
          urlOrPromise.then((url) => navigate(url)).catch(() => {});
        }
        return;
      }

      // Animated stripes transition
      if (busyRef.current) {
        if (typeof urlOrPromise === "string") navigate(urlOrPromise);
        return;
      }

      busyRef.current = true;

      if (typeof urlOrPromise === "string") {
        targetRef.current = urlOrPromise;
      } else if (urlOrPromise && typeof urlOrPromise.then === "function") {
        urlOrPromise
          .then((url) => {
            if (!url) { busyRef.current = false; setOv(null); return; }
            targetRef.current = url;
          })
          .catch(() => {
            busyRef.current = false;
            setOv(null);
          });
      }

      let cx = window.innerWidth / 2;
      let cy = window.innerHeight / 2;
      if (event?.clientX && event.clientX > 0) {
        cx = event.clientX;
        cy = event.clientY;
      }

      setOv({ cx, cy, phase: "mount" });
    },
    [navigate]
  );

  /* ── Phase progression ── */
  useEffect(() => {
    if (!ov) return;

    if (ov.phase === "mount") {
      // Double-rAF ensures the DOM has painted at clip-path: circle(0%)
      // before we transition to the expanded state
      const raf = requestAnimationFrame(() => {
        requestAnimationFrame(() => {
          setOv((p) => (p ? { ...p, phase: "expand" } : null));
        });
      });
      return () => cancelAnimationFrame(raf);
    }

    if (ov.phase === "expand") {
      let innerId;
      const id = setTimeout(() => {
        // Navigate to target
        if (targetRef.current) {
          const url = targetRef.current;
          targetRef.current = null;
          navigate(url);
        }
        // Brief delay so new page mounts behind the overlay, then fade
        innerId = setTimeout(() => {
          setOv((p) => (p ? { ...p, phase: "fade" } : null));
        }, 60);
      }, EXPAND_MS + 30);
      return () => { clearTimeout(id); clearTimeout(innerId); };
    }

    if (ov.phase === "fade") {
      const id = setTimeout(() => {
        setOv(null);
        busyRef.current = false;
      }, FADE_MS + 30);
      return () => clearTimeout(id);
    }
  }, [ov?.phase, navigate]); // eslint-disable-line react-hooks/exhaustive-deps

  /* ── Safety: 5s hard ceiling ── */
  useEffect(() => {
    if (!ov) return;
    const t = setTimeout(() => {
      if (targetRef.current) {
        navigate(targetRef.current);
        targetRef.current = null;
      }
      setOv(null);
      busyRef.current = false;
    }, 5000);
    return () => clearTimeout(t);
  }, [!!ov, navigate]); // eslint-disable-line react-hooks/exhaustive-deps

  /* ── Render ── */
  const expanded = ov && (ov.phase === "expand" || ov.phase === "fade");
  const fading = ov?.phase === "fade";

  return (
    <Ctx.Provider value={{ navigateWithReveal }}>
      {children}
      {ov && (
        <div
          style={{
            position: "fixed",
            inset: 0,
            zIndex: 9999,
            background: "#000",
            clipPath: expanded
              ? `circle(150% at ${ov.cx}px ${ov.cy}px)`
              : `circle(0% at ${ov.cx}px ${ov.cy}px)`,
            opacity: fading ? 0 : 1,
            transition: [
              `clip-path ${EXPAND_MS}ms cubic-bezier(0.76, 0, 0.24, 1)`,
              `opacity ${FADE_MS}ms cubic-bezier(0.4, 0, 0.2, 1)`,
            ].join(", "),
            pointerEvents: fading ? "none" : "auto",
            willChange: "clip-path, opacity",
          }}
          aria-hidden="true"
        >
          <FlowFieldBackground />
        </div>
      )}
    </Ctx.Provider>
  );
}
