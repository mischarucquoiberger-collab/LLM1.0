import { useEffect, useRef } from "react";

/* ── Pixel hand cursor SVG (inline, no external file needed) ── */
const HAND_SVG = `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 32 32" width="32" height="32" shape-rendering="crispEdges">
  <g fill="#000">
    <rect x="10" y="0" width="2" height="2"/>
    <rect x="12" y="0" width="2" height="2"/>
    <rect x="8" y="2" width="2" height="2"/>
    <rect x="14" y="2" width="2" height="2"/>
    <rect x="8" y="4" width="2" height="2"/>
    <rect x="14" y="4" width="2" height="2"/>
    <rect x="8" y="6" width="2" height="2"/>
    <rect x="14" y="6" width="2" height="2"/>
    <rect x="8" y="8" width="2" height="2"/>
    <rect x="14" y="8" width="2" height="2"/>
    <rect x="18" y="8" width="2" height="2"/>
    <rect x="22" y="8" width="2" height="2"/>
    <rect x="8" y="10" width="2" height="2"/>
    <rect x="14" y="10" width="2" height="2"/>
    <rect x="16" y="10" width="2" height="2"/>
    <rect x="20" y="10" width="2" height="2"/>
    <rect x="22" y="10" width="2" height="2"/>
    <rect x="24" y="10" width="2" height="2"/>
    <rect x="2" y="12" width="2" height="2"/>
    <rect x="4" y="12" width="2" height="2"/>
    <rect x="8" y="12" width="2" height="2"/>
    <rect x="14" y="12" width="2" height="2"/>
    <rect x="16" y="12" width="2" height="2"/>
    <rect x="20" y="12" width="2" height="2"/>
    <rect x="24" y="12" width="2" height="2"/>
    <rect x="26" y="12" width="2" height="2"/>
    <rect x="2" y="14" width="2" height="2"/>
    <rect x="6" y="14" width="2" height="2"/>
    <rect x="8" y="14" width="2" height="2"/>
    <rect x="14" y="14" width="2" height="2"/>
    <rect x="16" y="14" width="2" height="2"/>
    <rect x="20" y="14" width="2" height="2"/>
    <rect x="24" y="14" width="2" height="2"/>
    <rect x="26" y="14" width="2" height="2"/>
    <rect x="2" y="16" width="2" height="2"/>
    <rect x="6" y="16" width="2" height="2"/>
    <rect x="8" y="16" width="2" height="2"/>
    <rect x="26" y="16" width="2" height="2"/>
    <rect x="2" y="18" width="2" height="2"/>
    <rect x="6" y="18" width="2" height="2"/>
    <rect x="26" y="18" width="2" height="2"/>
    <rect x="4" y="20" width="2" height="2"/>
    <rect x="26" y="20" width="2" height="2"/>
    <rect x="4" y="22" width="2" height="2"/>
    <rect x="24" y="22" width="2" height="2"/>
    <rect x="6" y="24" width="2" height="2"/>
    <rect x="24" y="24" width="2" height="2"/>
    <rect x="6" y="26" width="2" height="2"/>
    <rect x="22" y="26" width="2" height="2"/>
    <rect x="8" y="28" width="2" height="2"/>
    <rect x="22" y="28" width="2" height="2"/>
    <rect x="8" y="30" width="2" height="2"/>
    <rect x="10" y="30" width="2" height="2"/>
    <rect x="12" y="30" width="2" height="2"/>
    <rect x="14" y="30" width="2" height="2"/>
    <rect x="16" y="30" width="2" height="2"/>
    <rect x="18" y="30" width="2" height="2"/>
    <rect x="20" y="30" width="2" height="2"/>
  </g>
  <g fill="#fff">
    <rect x="10" y="2" width="4" height="2"/>
    <rect x="10" y="4" width="4" height="2"/>
    <rect x="10" y="6" width="4" height="2"/>
    <rect x="10" y="8" width="4" height="2"/>
    <rect x="16" y="10" width="4" height="2"/>
    <rect x="10" y="10" width="4" height="2"/>
    <rect x="20" y="12" width="4" height="2"/>
    <rect x="16" y="12" width="4" height="2"/>
    <rect x="10" y="12" width="4" height="2"/>
    <rect x="4" y="14" width="2" height="2"/>
    <rect x="10" y="14" width="4" height="2"/>
    <rect x="16" y="14" width="4" height="6"/>
    <rect x="20" y="14" width="4" height="4"/>
    <rect x="4" y="16" width="2" height="2"/>
    <rect x="10" y="16" width="4" height="2"/>
    <rect x="14" y="16" width="2" height="2"/>
    <rect x="20" y="16" width="6" height="2"/>
    <rect x="4" y="18" width="2" height="2"/>
    <rect x="8" y="16" width="2" height="6"/>
    <rect x="10" y="18" width="16" height="2"/>
    <rect x="6" y="20" width="20" height="2"/>
    <rect x="6" y="22" width="18" height="2"/>
    <rect x="8" y="24" width="16" height="2"/>
    <rect x="8" y="26" width="14" height="2"/>
    <rect x="10" y="28" width="12" height="2"/>
  </g>
</svg>`;

const CURSOR_SIZE = 32;

/* Hotspot = very tip of the index finger in the 32×32 SVG
   Finger tip outline spans x 10-14, y 0-2  →  tip centre = (12, 0) */
const HOTSPOT_X = 12;
const HOTSPOT_Y = 0;

export default function CustomCursor() {
  const cursorRef = useRef(null);

  useEffect(() => {
    const el = cursorRef.current;
    if (!el) return;

    // skip touch devices
    if (window.matchMedia("(hover: none), (pointer: coarse)").matches) return;

    // Generate a 1×1 transparent PNG — using an actual image instead of
    // "cursor: none" prevents the OS from ever flashing the real cursor
    // during repaints, text hover, or GPU compositing.
    const c = document.createElement("canvas");
    c.width = 1;
    c.height = 1;
    const blankCursor = `url(${c.toDataURL()}) 0 0, none`;

    // Apply at every level so nothing can leak through
    document.documentElement.style.setProperty("cursor", blankCursor, "important");
    document.body.style.setProperty("cursor", blankCursor, "important");
    const styleTag = document.createElement("style");
    styleTag.textContent = `*, *::before, *::after { cursor: ${blankCursor} !important; }`;
    document.head.appendChild(styleTag);

    let visible = false;

    /* ── Zero-delay positioning: direct translate3d, no GSAP, no CSS transition ── */
    const onMove = (e) => {
      el.style.transform = `translate3d(${e.clientX - HOTSPOT_X}px,${e.clientY - HOTSPOT_Y}px,0)`;
      if (!visible) { visible = true; el.style.opacity = "1"; }
    };

    const onLeave = () => { visible = false; el.style.opacity = "0"; };
    const onEnter = (e) => {
      el.style.transform = `translate3d(${e.clientX - HOTSPOT_X}px,${e.clientY - HOTSPOT_Y}px,0)`;
      visible = true;
      el.style.opacity = "1";
    };

    document.addEventListener("mousemove", onMove);
    document.addEventListener("mouseleave", onLeave);
    document.addEventListener("mouseenter", onEnter);

    // hover glow on interactive elements
    const hoverIn = () => el.classList.add("cursor--hover");
    const hoverOut = () => el.classList.remove("cursor--hover");
    const registered = new WeakSet();
    const addHover = () => {
      document.querySelectorAll("button, a, input, textarea, select, .hero__stat, .cursor-hover").forEach((item) => {
        if (registered.has(item)) return;
        registered.add(item);
        item.addEventListener("mouseenter", hoverIn);
        item.addEventListener("mouseleave", hoverOut);
      });
    };

    addHover();
    const obs = new MutationObserver(addHover);
    obs.observe(document.body, { childList: true, subtree: true });

    return () => {
      document.removeEventListener("mousemove", onMove);
      document.removeEventListener("mouseleave", onLeave);
      document.removeEventListener("mouseenter", onEnter);
      obs.disconnect();
      document.documentElement.style.removeProperty("cursor");
      document.body.style.removeProperty("cursor");
      styleTag.remove();
    };
  }, []);

  return (
    <div
      ref={cursorRef}
      aria-hidden="true"
      dangerouslySetInnerHTML={{ __html: HAND_SVG }}
      style={{
        position: "fixed",
        top: 0,
        left: 0,
        width: CURSOR_SIZE,
        height: CURSOR_SIZE,
        pointerEvents: "none",
        zIndex: 99998,
        opacity: 0,
        willChange: "transform",
        transition: "opacity 0.15s ease, filter 0.2s ease",
      }}
    />
  );
}
