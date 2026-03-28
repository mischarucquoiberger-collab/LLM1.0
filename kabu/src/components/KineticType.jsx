import { useEffect, useRef, forwardRef, useImperativeHandle } from "react";
import { gsap } from "gsap";

const LINES = [
  "STOCKS JAPANESE EDINET",
  "LLM FINANCE STOCKS",
  "JAPANESE EDINET LLM",
  "FINANCE STOCKS JAPANESE",
  "EDINET LLM FINANCE",
  "STOCKS JAPANESE EDINET",
  "LLM FINANCE STOCKS",
  "JAPANESE EDINET LLM",
  "FINANCE STOCKS JAPANESE",
  "EDINET LLM FINANCE",
  "STOCKS JAPANESE EDINET",
];

const KineticType = forwardRef(function KineticType({ settled = false }, ref) {
  const containerRef = useRef(null);
  const linesRef = useRef([]);

  useImperativeHandle(ref, () => ({
    getContainer: () => containerRef.current,
    getLines: () => linesRef.current,
    transitionIn() {
      const el = containerRef.current;
      const lines = linesRef.current;
      return gsap
        .timeline({ paused: true })
        .to(el, { duration: 1.4, ease: "power2.inOut", scale: 2.7, rotate: -90 })
        .to(lines, { keyframes: [{ x: "20%", duration: 1, ease: "power1.inOut" }, { x: "-200%", duration: 1.5, ease: "power1.in" }], stagger: 0.04 }, 0)
        .to(lines, { keyframes: [{ opacity: 1, duration: 1, ease: "power1.in" }, { opacity: 0, duration: 1.5, ease: "power1.in" }] }, 0);
    },
    transitionOut() {
      const el = containerRef.current;
      const lines = linesRef.current;
      const lineOpacity = parseFloat(getComputedStyle(document.documentElement).getPropertyValue('--type-line-opacity')) || 0.035;
      return gsap
        .timeline({ paused: true })
        .to(el, { duration: 1.4, ease: "power2.inOut", scale: 1, rotate: 0 }, 1.2)
        .to(lines, { duration: 2.3, ease: "back", x: "0%", stagger: -0.04 }, 0)
        .to(lines, { keyframes: [{ opacity: 1, duration: 1, ease: "power1.in" }, { opacity: lineOpacity, duration: 1.5, ease: "power1.in" }] }, 0);
    },
  }));

  // mouse parallax
  useEffect(() => {
    const el = containerRef.current;
    if (!el || settled) return;
    const xTo = gsap.quickTo(el, "x", { duration: 1.8, ease: "power2" });
    const yTo = gsap.quickTo(el, "y", { duration: 1.8, ease: "power2" });
    const onMove = (e) => {
      xTo((e.clientX / window.innerWidth - 0.5) * 30);
      yTo((e.clientY / window.innerHeight - 0.5) * 20);
    };
    document.addEventListener("mousemove", onMove);
    return () => { document.removeEventListener("mousemove", onMove); gsap.killTweensOf(el); };
  }, [settled]);

  return (
    <div
      ref={containerRef}
      aria-hidden="true"
      style={{
        position: "fixed",
        inset: 0,
        height: "100dvh",
        width: "100vw",
        overflow: "hidden",
        display: "grid",
        justifyContent: "center",
        alignContent: "center",
        textAlign: "center",
        willChange: "transform",
        textTransform: "uppercase",
        pointerEvents: "none",
      }}
    >
      {LINES.map((text, i) => (
        <div
          key={i}
          ref={(el) => { linesRef.current[i] = el; }}
          style={{
            whiteSpace: "nowrap",
            fontSize: "clamp(5rem, 15vh, 12rem)",
            lineHeight: 0.85,
            fontWeight: 700,
            fontFamily: "'Space Grotesk', sans-serif",
            letterSpacing: "0.04em",
            color: "var(--color-type, #000)",
            opacity: settled ? 0.035 : 0,
            userSelect: "none",
            willChange: "transform, opacity",
          }}
        >
          {text}
        </div>
      ))}
    </div>
  );
});

export default KineticType;
