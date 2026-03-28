import React, { useState, useEffect, useRef } from "react";
import { motion } from "framer-motion";
import DashFieldCanvas from "@/components/DashFieldCanvas";

const ease = [0.16, 1, 0.3, 1];

/*
 * Splash — Character stagger reveal + enhanced exit
 *
 * 0.0s  Dash field starts
 * 0.3s  Logo characters stagger in
 * 0.6s  Subtitle fades in
 * 2.2s  Begin exit phase
 * 2.8s  onComplete → dissolve with blur + scale
 */

export default function SplashScreen({ onComplete }) {
  const [phase, setPhase] = useState(0);
  const done = useRef(false);

  useEffect(() => {
    const t = [];
    t.push(setTimeout(() => setPhase(1), 300));
    t.push(setTimeout(() => setPhase(2), 2200));
    t.push(setTimeout(() => {
      if (!done.current) { done.current = true; onComplete(); }
    }, 2800));
    return () => t.forEach(clearTimeout);
  }, [onComplete]);

  const logoChars = "Mischa".split("");
  const subChars = "Japanese Market Research".split("");

  return (
    <motion.div
      className="fixed inset-0 z-50 flex items-center justify-center"
      style={{ background: "#f8f9fb" }}
      exit={{ opacity: 0, scale: 0.96, filter: "blur(10px)" }}
      transition={{ duration: 0.8, ease: [0.76, 0, 0.24, 1] }}
    >
      <DashFieldCanvas style={{ zIndex: 0 }} />

      <div
        style={{
          position: "relative", zIndex: 1,
          display: "flex", flexDirection: "column", alignItems: "center", gap: 14,
        }}
      >
        {/* Logo — character stagger reveal */}
        <div style={{ overflow: "hidden", display: "flex" }}>
          {logoChars.map((ch, i) => (
            <motion.span
              key={i}
              style={{
                display: "inline-block",
                fontFamily: "'Cormorant Garamond', 'Playfair Display', serif",
                fontSize: 48, fontWeight: 600, color: "#0033CC",
                letterSpacing: "-0.01em",
              }}
              initial={{ y: "110%" }}
              animate={phase >= 1 ? { y: "0%" } : { y: "110%" }}
              transition={{
                delay: i * 0.055,
                duration: 0.55,
                ease,
              }}
            >
              {ch}
            </motion.span>
          ))}
        </div>

        {/* Subtitle — character stagger with longer delay */}
        <div style={{ overflow: "hidden", display: "flex" }}>
          {subChars.map((ch, i) => (
            <motion.span
              key={i}
              style={{
                display: "inline-block",
                fontFamily: "'Inter', system-ui, sans-serif",
                fontSize: 11, fontWeight: 400, color: "#0033CC",
                letterSpacing: "0.25em", textTransform: "uppercase",
                opacity: 0.5,
              }}
              initial={{ y: "110%" }}
              animate={phase >= 1 ? { y: "0%" } : { y: "110%" }}
              transition={{
                delay: 0.25 + i * 0.018,
                duration: 0.45,
                ease,
              }}
            >
              {ch === " " ? "\u00A0" : ch}
            </motion.span>
          ))}
        </div>

        {/* Exit fade — covers the text during phase 2 */}
        <motion.div
          style={{
            position: "absolute", inset: -20,
            background: "#f8f9fb",
            pointerEvents: "none",
          }}
          initial={{ opacity: 0 }}
          animate={{ opacity: phase === 2 ? 1 : 0 }}
          transition={{ duration: 0.5, ease: "easeInOut" }}
        />
      </div>
    </motion.div>
  );
}
