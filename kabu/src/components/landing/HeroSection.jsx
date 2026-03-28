import React, { useRef, useEffect, useState } from "react";
import { motion } from "framer-motion";
import { ArrowRight } from "lucide-react";
import { Link } from "react-router-dom";
import DashFieldCanvas from "@/components/DashFieldCanvas";

const ease = [0.16, 1, 0.3, 1];

/* ── Animated counter component ──────────────────────────── */
function AnimCounter({ target, delay = 0, duration = 1200, prefix = "", suffix = "" }) {
  const [val, setVal] = useState(0);
  useEffect(() => {
    let raf;
    const t0 = performance.now();
    const step = () => {
      const p = Math.min((performance.now() - t0) / duration, 1);
      setVal(Math.round((1 - Math.pow(1 - p, 3)) * target));
      if (p < 1) raf = requestAnimationFrame(step);
    };
    const tid = setTimeout(() => { raf = requestAnimationFrame(step); }, delay);
    return () => { clearTimeout(tid); if (raf) cancelAnimationFrame(raf); };
  }, [target, delay, duration]);
  return <>{prefix}{val.toLocaleString()}{suffix}</>;
}

/* ── Character stagger line ──────────────────────────────── */
function RevealLine({ text, baseDelay = 0, stagger = 0.025, parallax = { x: 0, y: 0 }, speed = 0.5, style = {} }) {
  return (
    <div style={{
      overflow: "hidden",
      transform: `translate(${parallax.x}px, ${parallax.y}px)`,
      transition: `transform ${speed}s cubic-bezier(0.16, 1, 0.3, 1)`,
      ...style,
    }}>
      {text.split("").map((ch, i) => (
        <motion.span
          key={i}
          style={{ display: "inline-block", willChange: "transform" }}
          initial={{ y: "110%" }}
          animate={{ y: "0%" }}
          transition={{ delay: baseDelay + i * stagger, duration: 0.6, ease }}
        >
          {ch === " " ? "\u00A0" : ch}
        </motion.span>
      ))}
    </div>
  );
}

export default function HeroSection() {
  const btnRef = useRef(null);
  const [mouse, setMouse] = useState({ x: 0, y: 0 });
  const [btnMag, setBtnMag] = useState({ x: 0, y: 0 });
  const [btnGlow, setBtnGlow] = useState({ x: 50, y: 50, on: false });
  const [hovNav, setHovNav] = useState(null);
  const [tokyoTime, setTokyoTime] = useState("");

  /* ── Tokyo time ── */
  useEffect(() => {
    const fmt = () => {
      try {
        return new Date().toLocaleTimeString("en-US", {
          timeZone: "Asia/Tokyo", hour: "2-digit", minute: "2-digit", hour12: false,
        });
      } catch { return ""; }
    };
    setTokyoTime(fmt());
    const id = setInterval(() => setTokyoTime(fmt()), 30000);
    return () => clearInterval(id);
  }, []);

  /* ── Mouse tracking (RAF-throttled) ── */
  useEffect(() => {
    let rafId = 0;
    let lx = 0, ly = 0;
    const onMove = (e) => {
      lx = e.clientX; ly = e.clientY;
      if (!rafId) {
        rafId = requestAnimationFrame(() => {
          setMouse({
            x: (lx / window.innerWidth - 0.5) * 2,
            y: (ly / window.innerHeight - 0.5) * 2,
          });
          const btn = btnRef.current;
          if (btn) {
            const r = btn.getBoundingClientRect();
            const cx = r.left + r.width / 2, cy = r.top + r.height / 2;
            const dx = lx - cx, dy = ly - cy;
            const dist = Math.sqrt(dx * dx + dy * dy);
            setBtnMag(dist < 130
              ? { x: dx * (1 - dist / 130) * 0.25, y: dy * (1 - dist / 130) * 0.25 }
              : { x: 0, y: 0 }
            );
          }
          rafId = 0;
        });
      }
    };
    window.addEventListener("mousemove", onMove, { passive: true });
    return () => { window.removeEventListener("mousemove", onMove); if (rafId) cancelAnimationFrame(rafId); };
  }, []);

  const nav = [
    { to: "/", label: "Research" },
    { to: "/Query", label: "Query" },
  ];

  return (
    <section className="relative min-h-screen flex flex-col overflow-hidden" style={{ background: "#f8f9fb" }}>
      <DashFieldCanvas style={{ zIndex: 0 }} />

      {/* ── Hero content ── */}
      <div className="relative z-10 flex-1 flex items-center px-8 sm:px-12 lg:px-20 xl:px-28">
        <div className="relative max-w-6xl w-full">

          {/* Breathing accent line */}
          <motion.div
            style={{
              position: "absolute", left: 0, top: "0%", bottom: "5%",
              width: 2, background: "#0033CC", borderRadius: 2,
            }}
            initial={{ scaleY: 0, opacity: 0, originY: "top" }}
            animate={{ scaleY: 1, opacity: [0.15, 0.4, 0.15] }}
            transition={{
              scaleY: { duration: 1.6, delay: 0.1, ease },
              opacity: { duration: 5, repeat: Infinity, ease: "easeInOut", delay: 1.8 },
            }}
          />

          <div style={{ paddingLeft: "clamp(32px, 5vw, 72px)" }}>

            {/* ── Heading — character stagger + parallax per line ── */}
            <h1 style={{
              fontFamily: "'Cormorant Garamond', 'Playfair Display', 'Georgia', serif",
              fontWeight: 600, color: "#0033CC",
              fontSize: "clamp(58px, 9.5vw, 130px)",
              lineHeight: 0.95, letterSpacing: "-0.04em", margin: 0,
              textShadow: "0 1px 3px rgba(0, 51, 204, 0.06)",
            }}>
              <RevealLine
                text="Built for"
                baseDelay={0.12}
                stagger={0.03}
                parallax={{ x: mouse.x * -3, y: mouse.y * -1.5 }}
                speed={0.5}
              />
              <RevealLine
                text="Japanese market"
                baseDelay={0.38}
                stagger={0.022}
                parallax={{ x: mouse.x * -5, y: mouse.y * -2.5 }}
                speed={0.6}
                style={{ fontWeight: 300, fontStyle: "italic" }}
              />
              <RevealLine
                text="research."
                baseDelay={0.58}
                stagger={0.03}
                parallax={{ x: mouse.x * -7, y: mouse.y * -3.5 }}
                speed={0.7}
              />
            </h1>

            {/* ── Expanding horizontal rule ── */}
            <motion.div
              style={{
                height: 1, background: "#0033CC", opacity: 0.1,
                transformOrigin: "left", marginTop: "clamp(24px, 3vw, 44px)",
                maxWidth: 460,
              }}
              initial={{ scaleX: 0 }}
              animate={{ scaleX: 1 }}
              transition={{ duration: 2.2, delay: 1.1, ease }}
            />

            {/* ── Trust signals — 3 animated counters ── */}
            <motion.div
              className="flex items-center gap-5 sm:gap-7 mt-5"
              style={{ fontFamily: "'Inter', system-ui, sans-serif" }}
              initial={{ opacity: 0, y: 12 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ duration: 0.8, delay: 0.85, ease }}
            >
              {[
                { target: 3900, suffix: "+", label: "Listed Companies", desc: "Full TSE coverage", delay: 700 },
                { target: 40, suffix: "+", label: "Data Sources", desc: "EDINET, J-Quants & more", delay: 850 },
                { target: 4, suffix: " min", label: "Report Generation", desc: "AI-powered analysis", prefix: "< ", delay: 1000 },
              ].map(({ target, suffix, label, desc, delay, prefix }, i) => (
                <React.Fragment key={label}>
                  {i > 0 && <span style={{ width: 1, height: 24, background: "#0033CC", opacity: 0.1, flexShrink: 0 }} />}
                  <div>
                    <div style={{
                      fontSize: "clamp(17px, 2vw, 24px)", fontWeight: 600,
                      color: "#0033CC", fontVariantNumeric: "tabular-nums",
                    }}>
                      <AnimCounter target={target} delay={delay} prefix={prefix || ""} suffix={suffix} />
                    </div>
                    <div style={{
                      fontSize: 9, letterSpacing: "0.1em", textTransform: "uppercase",
                      color: "#0033CC", opacity: 0.55, marginTop: 2, fontWeight: 500,
                    }}>
                      {label}
                    </div>
                    <div style={{
                      fontSize: 10, color: "#0055AA", opacity: 0.35, marginTop: 1,
                      fontWeight: 400,
                    }}>
                      {desc}
                    </div>
                  </div>
                </React.Fragment>
              ))}
            </motion.div>

            {/* ── Subtitle with parallax ── */}
            <div style={{
              transform: `translate(${mouse.x * -2}px, ${mouse.y * -1}px)`,
              transition: "transform 0.5s cubic-bezier(0.16, 1, 0.3, 1)",
            }}>
              <motion.p
                style={{
                  fontFamily: "'Inter', system-ui, sans-serif",
                  fontSize: "clamp(14px, 1.4vw, 18px)", color: "#0055AA",
                  marginTop: "clamp(20px, 2.5vw, 32px)", maxWidth: 540,
                  lineHeight: 1.7, fontWeight: 400,
                }}
                initial={{ opacity: 0, y: 16 }}
                animate={{ opacity: 1, y: 0 }}
                transition={{ duration: 0.8, delay: 0.7, ease }}
              >
                Institutional-grade research on every publicly listed company in Japan. AI-powered reports with financial analysis, valuation, and real-time data — delivered in minutes.
              </motion.p>
            </div>

            {/* ── CTA — magnetic button with cursor glow ── */}
            <motion.div
              className="mt-8"
              initial={{ opacity: 0, y: 20 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ duration: 0.8, delay: 1.0, ease }}
            >
              <Link to="/" style={{ textDecoration: "none" }}>
                <motion.button
                  ref={btnRef}
                  className="group"
                  style={{
                    background: btnGlow.on
                      ? `radial-gradient(120px circle at ${btnGlow.x}% ${btnGlow.y}%, rgba(255,255,255,0.14), transparent 60%), #0033CC`
                      : "#0033CC",
                    color: "#fff",
                    fontFamily: "'Inter', system-ui, sans-serif",
                    fontSize: 13, fontWeight: 500, letterSpacing: "0.06em",
                    padding: "16px 42px", border: "none", cursor: "pointer",
                    borderRadius: 12,
                    textTransform: "uppercase",
                    display: "inline-flex", alignItems: "center", gap: 10,
                    transform: `translate(${btnMag.x}px, ${btnMag.y}px)`,
                    transition: "transform 0.2s ease-out, box-shadow 0.3s ease, background 0.1s ease",
                  }}
                  onMouseMove={(e) => {
                    const r = e.currentTarget.getBoundingClientRect();
                    setBtnGlow({
                      x: ((e.clientX - r.left) / r.width) * 100,
                      y: ((e.clientY - r.top) / r.height) * 100,
                      on: true,
                    });
                  }}
                  onMouseLeave={() => setBtnGlow(p => ({ ...p, on: false }))}
                  whileHover={{ boxShadow: "0 14px 45px rgba(0,51,204,0.3)" }}
                  whileTap={{ scale: 0.97 }}
                >
                  Get Started
                  <ArrowRight
                    size={14}
                    strokeWidth={2.5}
                    className="transition-transform duration-300 group-hover:translate-x-1"
                  />
                </motion.button>
              </Link>
            </motion.div>
          </div>
        </div>
      </div>

      {/* ── Scroll hint ── */}
      <motion.div
        className="absolute bottom-20 left-1/2 z-10 hidden sm:flex flex-col items-center gap-2"
        style={{ transform: "translateX(-50%)" }}
        initial={{ opacity: 0 }}
        animate={{ opacity: 1 }}
        transition={{ delay: 2.2, duration: 0.8 }}
      >
        <motion.div
          animate={{ y: [0, 6, 0] }}
          transition={{ duration: 2, repeat: Infinity, ease: "easeInOut" }}
        >
          <div style={{
            width: 20, height: 32, borderRadius: 10,
            border: "1.5px solid rgba(0,51,204,0.12)",
            display: "flex", justifyContent: "center", paddingTop: 6,
          }}>
            <motion.div
              style={{
                width: 2.5, height: 6, borderRadius: 2,
                background: "#0033CC", opacity: 0.2,
              }}
              animate={{ y: [0, 8, 0], opacity: [0.2, 0.4, 0.2] }}
              transition={{ duration: 2, repeat: Infinity, ease: "easeInOut" }}
            />
          </div>
        </motion.div>
      </motion.div>

      {/* ── Bottom bar: logo + time + nav ── */}
      <motion.div
        className="relative z-10 flex items-center justify-between px-8 sm:px-12 lg:px-20 xl:px-28 py-6"
        initial={{ opacity: 0 }}
        animate={{ opacity: 1 }}
        transition={{ duration: 1, delay: 1.4 }}
      >
        <Link to="/" style={{ textDecoration: "none" }}>
          <span style={{
            fontFamily: "'Cormorant Garamond', serif",
            fontSize: 20, fontWeight: 700, color: "#0033CC",
            letterSpacing: "-0.02em", opacity: 0.4,
          }}>
            mischa
          </span>
        </Link>

        <div
          className="hidden sm:flex items-center gap-7"
          style={{
            fontFamily: "'Inter', system-ui, sans-serif",
            fontSize: 11, fontWeight: 500, letterSpacing: "0.1em",
            textTransform: "uppercase",
          }}
        >
          {/* Live Tokyo time */}
          {tokyoTime && (
            <span style={{
              fontSize: 9, color: "#0033CC", opacity: 0.2,
              letterSpacing: "0.08em", fontVariantNumeric: "tabular-nums",
              fontWeight: 400,
            }}>
              TSE {tokyoTime}
            </span>
          )}

          {nav.map(({ to, label }) => (
            <Link
              key={to}
              to={to}
              onMouseEnter={() => setHovNav(to)}
              onMouseLeave={() => setHovNav(null)}
              style={{
                color: "#0033CC", textDecoration: "none",
                opacity: hovNav === to ? 1 : 0.3,
                transition: "opacity 0.3s ease",
                position: "relative", paddingBottom: 4,
              }}
            >
              {label}
              <span style={{
                position: "absolute", bottom: 0, left: 0,
                height: 1, background: "#0033CC",
                width: hovNav === to ? "100%" : "0%",
                transition: "width 0.3s ease",
              }} />
            </Link>
          ))}

          <span style={{
            fontSize: 9, color: "#0033CC", opacity: 0.15,
            letterSpacing: "0.15em",
          }}>
            v1
          </span>
        </div>
      </motion.div>
    </section>
  );
}
