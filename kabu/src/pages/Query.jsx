import React, { useState, useRef, useCallback, useEffect } from "react";
import { motion, AnimatePresence } from "framer-motion";
import {
  ArrowLeft, ArrowUp, ArrowDown, Loader2, Search, TrendingUp, FileText, Users,
  Globe, Wrench, ChevronDown, CheckCircle2, Plus, X, Square,
  Activity, BarChart3, Layers, Shield, AlertTriangle, Zap, Clock,
  Mic, MicOff, Copy, Check, Target,
} from "lucide-react";
import { Link, useLocation } from "react-router-dom";
import { streamChat } from "@/api/backend";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import LivePriceTicker from "@/components/chat/LivePriceTicker";
import Sidebar from "@/components/chat/Sidebar";
import FlowFieldBackground from "@/components/FlowFieldBackground";
import VoiceOverlay from "@/components/chat/VoiceOverlay";

const REMARK_PLUGINS = [remarkGfm];

/* ── Conversation persistence ─────────────────────────────── */
const STORAGE_KEY = "kabu-conversations";
function loadConversations() { try { const r = localStorage.getItem(STORAGE_KEY); return r ? JSON.parse(r) : []; } catch { return []; } }
const MAX_SAVED_CONVOS = 50;
function saveConversations(c) {
  try {
    /* Trim tool result data to prevent localStorage overflow (~5MB limit) */
    const trimmed = c.slice(-MAX_SAVED_CONVOS).map(conv => ({
      ...conv,
      messages: (conv.messages || []).map(m => {
        if (!m.toolCalls) return m;
        return { ...m, toolCalls: m.toolCalls.map(tc => ({
          ...tc,
          price_history: undefined,
          source_details: undefined,
          result: typeof tc.result === "string" && tc.result.length > 200 ? tc.result.slice(0, 200) + "…" : tc.result,
        }))};
      }),
    }));
    localStorage.setItem(STORAGE_KEY, JSON.stringify(trimmed));
  } catch {}
}
function newConvoId() { return Date.now().toString(36) + Math.random().toString(36).slice(2, 7); }

/* ── Tool metadata ──────────────────────────────────────── */
const TOOL_META = {
  lookup_company:        { icon: Search,     label: "Company lookup",      color: "text-blue-400",    bg: "bg-blue-500/10",    hex: "#60a5fa" },
  get_stock_prices:      { icon: TrendingUp, label: "Stock prices",        color: "text-emerald-400", bg: "bg-emerald-500/10", hex: "#34d399" },
  get_financials:        { icon: FileText,   label: "Financials",          color: "text-amber-400",   bg: "bg-amber-500/10",   hex: "#fbbf24" },
  search_edinet_filings: { icon: FileText,   label: "EDINET filings",      color: "text-violet-400",  bg: "bg-violet-500/10",  hex: "#a78bfa" },
  web_search:            { icon: Globe,      label: "Web search",          color: "text-cyan-400",    bg: "bg-cyan-500/10",    hex: "#22d3ee" },
  get_directors:         { icon: Users,      label: "Board data",          color: "text-pink-400",    bg: "bg-pink-500/10",    hex: "#f472b6" },
  get_voting_results:    { icon: FileText,   label: "AGM voting",          color: "text-orange-400",  bg: "bg-orange-500/10",  hex: "#fb923c" },
  get_large_shareholders:{ icon: Users,      label: "Large shareholders",  color: "text-red-400",     bg: "bg-red-500/10",     hex: "#f87171" },
  analyze_technicals:    { icon: Activity,   label: "Technical analysis",  color: "text-teal-400",    bg: "bg-teal-500/10",    hex: "#2dd4bf" },
  score_company:         { icon: BarChart3,  label: "Quant scoring",       color: "text-yellow-400",  bg: "bg-yellow-500/10",  hex: "#facc15" },
  get_company_peers:     { icon: Layers,     label: "Sector peers",        color: "text-lime-400",    bg: "bg-lime-500/10",    hex: "#a3e635" },
  get_market_context:    { icon: Globe,      label: "Market context",      color: "text-indigo-400",  bg: "bg-indigo-500/10",  hex: "#818cf8" },
  screen_sector:         { icon: BarChart3,  label: "Sector screener",     color: "text-fuchsia-400", bg: "bg-fuchsia-500/10", hex: "#e879f9" },
  analyze_risk:          { icon: Shield,       label: "Risk analytics",      color: "text-orange-400",  bg: "bg-orange-500/10",  hex: "#fb923c" },
  detect_red_flags:      { icon: AlertTriangle, label: "Red flag detection", color: "text-red-400",     bg: "bg-red-500/10",     hex: "#f87171" },
  get_shareholder_structure: { icon: Users,    label: "Shareholder structure", color: "text-sky-400",  bg: "bg-sky-500/10",     hex: "#38bdf8" },
};

/* ── Tool helpers ─────────────────────────────────────────── */
function describeToolAction(tool, input) {
  const code = input?.stock_code || "";
  const q = input?.query || "";
  switch (tool) {
    case "lookup_company": return `Resolving company ${code}`;
    case "get_stock_prices": return `Live price + ${input?.days || 30}-day history for ${code}`;
    case "get_financials": return `Quarterly earnings & balance sheet for ${code}`;
    case "search_edinet_filings": return `Scanning EDINET filings for ${code}`;
    case "web_search": return `Searching "${q.length > 40 ? q.slice(0, 37) + "..." : q}"`;
    case "get_directors": return `Board composition for ${input?.company_name || code}`;
    case "get_voting_results": return `AGM voting results for ${code}`;
    case "get_large_shareholders": return `Scanning 大量保有報告書 for ${code}`;
    case "analyze_technicals": return `Technical analysis for ${code}`;
    case "score_company": return `Quantitative scoring for ${code}`;
    case "get_company_peers": return `Finding sector peers for ${code}`;
    case "get_market_context": return `Loading market context`;
    case "screen_sector": return `Screening ${input?.sector || "sector"} — ${input?.max_results || 8} companies`;
    case "analyze_risk": return `Risk analytics for ${code}`;
    case "detect_red_flags": return `Forensic accounting scan for ${code}`;
    case "get_shareholder_structure": return `Shareholder structure from annual report for ${code}`;
    default: return tool;
  }
}

function formatToolDetail(tool, input) {
  const code = input?.stock_code || "";
  switch (tool) {
    case "lookup_company": return { params: [["Code", code]], endpoint: "J-Quants" };
    case "get_stock_prices": return { params: [["Code", code], ["Period", `${input?.days || 30}d`]], endpoint: "J-Quants + Yahoo" };
    case "get_financials": return { params: [["Code", code]], endpoint: "J-Quants Financials" };
    case "search_edinet_filings": return { params: [["Code", code]], endpoint: "EDINET API v2" };
    case "web_search": return { params: [["Query", input?.query || ""]], endpoint: "SERP API" };
    case "get_directors": return { params: [["Code", code]], endpoint: "EDINET + AI" };
    case "get_voting_results": return { params: [["Code", code]], endpoint: "EDINET" };
    case "get_large_shareholders": return { params: [["Code", code]], endpoint: "EDINET" };
    case "analyze_technicals": return { params: [["Code", code]], endpoint: "RSI + MACD + Bollinger" };
    case "score_company": return { params: [["Code", code]], endpoint: "Piotroski + Value + Growth" };
    case "get_company_peers": return { params: [["Code", code]], endpoint: "TSE Peer Universe" };
    case "get_market_context": return { params: [], endpoint: "Nikkei + USD/JPY + S&P" };
    case "screen_sector": return { params: [["Sector", input?.sector || "auto"], ["Sort", input?.sort_by || "composite"], ["Top", `${input?.max_results || 8}`]], endpoint: "J-Quants + TSE" };
    case "analyze_risk": return { params: [["Code", code]], endpoint: "Vol + Beta + Sharpe + VaR" };
    case "detect_red_flags": return { params: [["Code", code]], endpoint: "Z-Score + Accruals + Beneish" };
    case "get_shareholder_structure": return { params: [["Code", code]], endpoint: "EDINET 有価証券報告書" };
    default: return { params: Object.entries(input || {}), endpoint: tool };
  }
}

/* ── Smart Quick Actions (context-aware drill-down) ───────── */
function getQuickActions(tools) {
  if (!tools?.length) return [];
  const codes = new Set();
  const used = new Set();
  for (const t of tools) {
    if (t.input?.stock_code) codes.add(t.input.stock_code);
    used.add(t.tool);
  }
  const code = [...codes][0];
  if (!code) return [];
  const pool = [
    { icon: Activity,       label: "Technicals",    query: `Run technical analysis on ${code}`,                                 key: "analyze_technicals" },
    { icon: Target,         label: "Score",          query: `Give me the quantitative Piotroski + Value/Growth/Quality score for ${code}`, key: "score_company" },
    { icon: Shield,         label: "Risk Profile",   query: `Analyze the full risk profile of ${code} — volatility, beta, Sharpe, VaR`, key: "analyze_risk" },
    { icon: AlertTriangle,  label: "Red Flags",      query: `Run a forensic accounting scan on ${code} for red flags`,           key: "detect_red_flags" },
    { icon: Layers,         label: "Screen Sector",  query: `Screen the sector that ${code} belongs to and rank competitors`,    key: "screen_sector" },
    { icon: Users,          label: "Shareholders",   query: `Who are the major 5%+ shareholders of ${code}? Any activists?`,    key: "get_large_shareholders" },
    { icon: Users,          label: "Board",          query: `Show me the board of directors for ${code}`,                        key: "get_directors" },
    { icon: Users,          label: "All Shareholders", query: `Show me the full shareholder structure for ${code} — top shareholders, ownership breakdown, and any activist investors`, key: "get_shareholder_structure" },
  ];
  return pool.filter(a => !used.has(a.key)).slice(0, 4);
}

/* ── Tool Pill — Ultra-premium Apple HIG ──────────────────── */

/* Tool-specific expected durations (seconds) for fallback progress */
const TOOL_SPEED = {
  lookup_company: 1.5, get_stock_prices: 3, get_financials: 4, web_search: 3,
  get_directors: 8, get_voting_results: 8, get_large_shareholders: 10,
  get_shareholder_structure: 12, search_edinet_filings: 6, analyze_technicals: 4,
  score_company: 5, get_company_peers: 3, get_market_context: 3, screen_sector: 8,
  analyze_risk: 5, detect_red_flags: 5, search_fund_holdings: 10,
};

function useToolProgress(active, tool) {
  const [pct, setPct] = useState(0);
  const startRef = useRef(null);
  const rafRef = useRef(null);
  useEffect(() => {
    if (active) {
      startRef.current = Date.now();
      const k = TOOL_SPEED[tool] || 5;
      const tick = () => {
        const t = (Date.now() - startRef.current) / 1000 / k;
        const v = t < 0.3 ? (t / 0.3) * 60 : t < 0.7 ? 60 + ((t - 0.3) / 0.4) * 25 : 85 + 10 * (1 - Math.exp(-(t - 0.7) * 1.5));
        setPct(Math.min(Math.round(v), 95));
        rafRef.current = requestAnimationFrame(tick);
      };
      rafRef.current = requestAnimationFrame(tick);
    } else if (startRef.current !== null) {
      if (rafRef.current) cancelAnimationFrame(rafRef.current);
      setPct(100);
      startRef.current = null;
    }
    return () => { if (rafRef.current) cancelAnimationFrame(rafRef.current); };
  }, [active, tool]);
  return pct;
}

/* Smooth spring-like number interpolation */
function useSmoothNumber(target) {
  const [display, setDisplay] = useState(target);
  const rafRef = useRef(null);
  const currentRef = useRef(target);
  const velocityRef = useRef(0);
  useEffect(() => {
    const animate = () => {
      const diff = target - currentRef.current;
      if (Math.abs(diff) < 0.5 && Math.abs(velocityRef.current) < 0.1) {
        currentRef.current = target; velocityRef.current = 0; setDisplay(target); return;
      }
      // Spring physics: stiffness=0.08, damping=0.82
      velocityRef.current = velocityRef.current * 0.82 + diff * 0.08;
      currentRef.current += velocityRef.current;
      setDisplay(Math.round(currentRef.current));
      rafRef.current = requestAnimationFrame(animate);
    };
    rafRef.current = requestAnimationFrame(animate);
    return () => { if (rafRef.current) cancelAnimationFrame(rafRef.current); };
  }, [target]);
  return display;
}

/* Orbiting particle canvas for loading state */
function OrbitalRing({ hex, pct, size = 36 }) {
  const canvasRef = useRef(null);
  const rafRef = useRef(null);
  const startRef = useRef(Date.now());

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext("2d");
    const dpr = window.devicePixelRatio || 1;
    canvas.width = size * dpr;
    canvas.height = size * dpr;
    ctx.scale(dpr, dpr);

    const cx = size / 2, cy = size / 2, r = size / 2 - 3;
    const NUM_PARTICLES = 8;
    const TAIL_LEN = 0.35; // radians of tail per particle

    // Parse hex to rgb
    const hexToRgb = (h) => {
      const n = parseInt(h.slice(1), 16);
      return [(n >> 16) & 255, (n >> 8) & 255, n & 255];
    };
    const [pr, pg, pb] = hexToRgb(hex);

    const draw = () => {
      const t = (Date.now() - startRef.current) / 1000;
      ctx.clearRect(0, 0, size, size);

      // Track circle
      ctx.beginPath();
      ctx.arc(cx, cy, r, 0, Math.PI * 2);
      ctx.strokeStyle = `rgba(${pr}, ${pg}, ${pb}, 0.12)`;
      ctx.lineWidth = 2;
      ctx.stroke();

      // Progress arc (bold, glowing)
      const progressAngle = (pct / 100) * Math.PI * 2;
      if (progressAngle > 0.01) {
        // Outer glow for progress arc
        ctx.beginPath();
        ctx.arc(cx, cy, r, -Math.PI / 2, -Math.PI / 2 + progressAngle);
        ctx.strokeStyle = `rgba(${pr}, ${pg}, ${pb}, 0.15)`;
        ctx.lineWidth = 5;
        ctx.lineCap = "round";
        ctx.stroke();
        // Main arc
        ctx.beginPath();
        ctx.arc(cx, cy, r, -Math.PI / 2, -Math.PI / 2 + progressAngle);
        ctx.strokeStyle = `rgba(${pr}, ${pg}, ${pb}, 0.6)`;
        ctx.lineWidth = 2.5;
        ctx.lineCap = "round";
        ctx.stroke();
      }

      // Orbiting particles — always visible, brighter
      for (let i = 0; i < NUM_PARTICLES; i++) {
        const baseAngle = (i / NUM_PARTICLES) * Math.PI * 2;
        const speed = 1.2 + (i % 3) * 0.4;
        const angle = baseAngle + t * speed;
        const wobble = Math.sin(t * 2.5 + i * 1.7) * 2;
        const pr2 = r + wobble;
        const x = cx + Math.cos(angle) * pr2;
        const y = cy + Math.sin(angle) * pr2;

        const particleSize = 1.4 + Math.sin(t * 3 + i) * 0.5;
        const alpha = 0.55 + Math.sin(t * 2 + i * 0.9) * 0.3;

        // Glow halo
        const grad = ctx.createRadialGradient(x, y, 0, x, y, particleSize * 4);
        grad.addColorStop(0, `rgba(${pr}, ${pg}, ${pb}, ${alpha * 0.5})`);
        grad.addColorStop(1, `rgba(${pr}, ${pg}, ${pb}, 0)`);
        ctx.fillStyle = grad;
        ctx.fillRect(x - particleSize * 4, y - particleSize * 4, particleSize * 8, particleSize * 8);

        // Core dot
        ctx.beginPath();
        ctx.arc(x, y, particleSize, 0, Math.PI * 2);
        ctx.fillStyle = `rgba(${pr}, ${pg}, ${pb}, ${alpha * 0.85})`;
        ctx.fill();
      }

      // Leading dot at progress tip — bright beacon
      const leadAngle = -Math.PI / 2 + progressAngle;
      const lx = cx + Math.cos(leadAngle) * r;
      const ly = cy + Math.sin(leadAngle) * r;
      const pulse = 0.7 + Math.sin(t * 5) * 0.3;
      const leadGlow = ctx.createRadialGradient(lx, ly, 0, lx, ly, 6);
      leadGlow.addColorStop(0, `rgba(${pr}, ${pg}, ${pb}, ${pulse})`);
      leadGlow.addColorStop(0.4, `rgba(${pr}, ${pg}, ${pb}, 0.25)`);
      leadGlow.addColorStop(1, `rgba(${pr}, ${pg}, ${pb}, 0)`);
      ctx.fillStyle = leadGlow;
      ctx.fillRect(lx - 6, ly - 6, 12, 12);
      ctx.beginPath();
      ctx.arc(lx, ly, 2, 0, Math.PI * 2);
      ctx.fillStyle = `rgba(${pr}, ${pg}, ${pb}, 0.95)`;
      ctx.fill();

      rafRef.current = requestAnimationFrame(draw);
    };

    rafRef.current = requestAnimationFrame(draw);
    return () => { if (rafRef.current) cancelAnimationFrame(rafRef.current); };
  }, [hex, pct, size]);

  return (
    <canvas
      ref={canvasRef}
      style={{ width: size, height: size, position: "absolute", inset: 0 }}
    />
  );
}

/* Completion burst particles */
function CompletionBurst({ hex, size = 36 }) {
  const canvasRef = useRef(null);
  const rafRef = useRef(null);
  const startRef = useRef(Date.now());

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext("2d");
    const dpr = window.devicePixelRatio || 1;
    const s = size * 2; // double size for burst overflow
    canvas.width = s * dpr;
    canvas.height = s * dpr;
    ctx.scale(dpr, dpr);

    const cx = s / 2, cy = s / 2;
    const hexToRgb = (h) => {
      const n = parseInt(h.slice(1), 16);
      return [(n >> 16) & 255, (n >> 8) & 255, n & 255];
    };
    const [pr, pg, pb] = hexToRgb(hex);

    // Generate burst particles
    const particles = Array.from({ length: 12 }, (_, i) => ({
      angle: (i / 12) * Math.PI * 2 + (Math.random() - 0.5) * 0.3,
      speed: 18 + Math.random() * 25,
      size: 0.8 + Math.random() * 1.2,
      decay: 0.85 + Math.random() * 0.1,
    }));

    const draw = () => {
      const elapsed = (Date.now() - startRef.current) / 1000;
      if (elapsed > 0.8) return; // stop after animation

      ctx.clearRect(0, 0, s, s);

      const progress = elapsed / 0.8; // 0 → 1
      const ease = 1 - Math.pow(1 - progress, 3); // ease-out cubic

      for (const p of particles) {
        const dist = p.speed * ease;
        const x = cx + Math.cos(p.angle) * dist;
        const y = cy + Math.sin(p.angle) * dist;
        const alpha = Math.max(0, 1 - progress * 1.5) * 0.7;
        const currentSize = p.size * (1 - progress * 0.5);

        // Glow
        const grad = ctx.createRadialGradient(x, y, 0, x, y, currentSize * 4);
        grad.addColorStop(0, `rgba(52, 199, 89, ${alpha * 0.4})`);
        grad.addColorStop(1, `rgba(52, 199, 89, 0)`);
        ctx.fillStyle = grad;
        ctx.fillRect(x - currentSize * 4, y - currentSize * 4, currentSize * 8, currentSize * 8);

        // Core
        ctx.beginPath();
        ctx.arc(x, y, currentSize, 0, Math.PI * 2);
        ctx.fillStyle = `rgba(52, 199, 89, ${alpha})`;
        ctx.fill();
      }

      // Center flash
      if (progress < 0.3) {
        const flashAlpha = (1 - progress / 0.3) * 0.3;
        const flashGrad = ctx.createRadialGradient(cx, cy, 0, cx, cy, 16);
        flashGrad.addColorStop(0, `rgba(52, 199, 89, ${flashAlpha})`);
        flashGrad.addColorStop(1, `rgba(52, 199, 89, 0)`);
        ctx.fillStyle = flashGrad;
        ctx.fillRect(cx - 16, cy - 16, 32, 32);
      }

      rafRef.current = requestAnimationFrame(draw);
    };

    rafRef.current = requestAnimationFrame(draw);
    return () => { if (rafRef.current) cancelAnimationFrame(rafRef.current); };
  }, [hex, size]);

  return (
    <canvas
      ref={canvasRef}
      style={{
        width: size * 2, height: size * 2,
        position: "absolute",
        top: -(size / 2), left: -(size / 2),
        pointerEvents: "none",
      }}
    />
  );
}

function ToolPill({ tool, input, result, isLoading, sources, serverPct, serverStage }) {
  const [open, setOpen] = useState(false);
  const [phase, setPhase] = useState("idle"); // idle | loading | completing | done
  const meta = TOOL_META[tool] || { icon: Wrench, label: tool, color: "text-gray-500", bg: "bg-gray-100", border: "border-gray-200", hex: "#9ca3af" };
  const Icon = meta.icon;
  const action = describeToolAction(tool, input);
  const detail = formatToolDetail(tool, input);
  const canExpand = !isLoading && phase !== "completing";
  const estimatedPct = useToolProgress(isLoading, tool);
  // Always use the higher of server-reported or estimated — estimated provides smooth animation floor
  const rawPct = Math.max(estimatedPct, serverPct || 0);
  const pct = useSmoothNumber(rawPct);
  const stage = serverStage || "";
  const [prevStage, setPrevStage] = useState("");

  // Track stage transitions for animation
  useEffect(() => {
    if (stage && stage !== prevStage && stage !== "starting" && stage !== "cached") {
      setPrevStage(stage);
    }
  }, [stage, prevStage]);

  useEffect(() => {
    if (isLoading) { setPhase("loading"); return; }
    if (phase === "loading") {
      setPhase("completing");
      const t = setTimeout(() => setPhase("done"), 1000);
      return () => clearTimeout(t);
    }
  }, [isLoading, phase]);

  // Parse hex to rgba helper
  const hexAlpha = (alpha) => {
    const n = parseInt(meta.hex.slice(1), 16);
    return `rgba(${(n >> 16) & 255}, ${(n >> 8) & 255}, ${n & 255}, ${alpha})`;
  };

  return (
    <motion.div
      initial={{ opacity: 0, y: 12, scale: 0.88 }}
      animate={{ opacity: 1, y: 0, scale: 1 }}
      transition={{ type: "spring", stiffness: 400, damping: 28, mass: 0.8 }}
      layout
    >
      <div
        className="relative rounded-[16px] overflow-hidden"
        style={{
          transition: "all 0.7s cubic-bezier(0.16, 1, 0.3, 1)",
          background: phase === "completing"
            ? "rgba(240, 253, 244, 0.7)"
            : isLoading
            ? "rgba(255, 255, 255, 0.75)"
            : open
            ? "rgba(255, 255, 255, 0.55)"
            : "rgba(255, 255, 255, 0.35)",
          backdropFilter: "blur(24px) saturate(1.8)",
          WebkitBackdropFilter: "blur(24px) saturate(1.8)",
          boxShadow: phase === "completing"
            ? `0 0 0 1px rgba(52, 199, 89, 0.25), 0 4px 24px -4px rgba(52, 199, 89, 0.12), 0 0 40px -8px rgba(52, 199, 89, 0.08)`
            : isLoading
            ? `0 0 0 1px ${hexAlpha(0.12)}, 0 4px 20px -4px ${hexAlpha(0.08)}, 0 0 32px -8px ${hexAlpha(0.05)}`
            : open
            ? "0 0 0 1px rgba(0,0,0,0.06), 0 2px 8px -2px rgba(0,0,0,0.04)"
            : "0 0 0 1px rgba(0,0,0,0.04)",
        }}
      >
        {/* Ambient glow pulse during loading */}
        {isLoading && (
          <div
            className="absolute inset-0 pointer-events-none tool-glow-pulse"
            style={{
              background: `radial-gradient(ellipse 80% 60% at 20% 50%, ${hexAlpha(0.06)}, transparent 70%)`,
            }}
          />
        )}

        {/* Shimmer sweep during loading — refined glass effect */}
        {isLoading && (
          <div className="absolute inset-0 pointer-events-none overflow-hidden rounded-[16px]">
            <div className="tool-shimmer absolute inset-y-0 -left-full w-full"
              style={{ background: `linear-gradient(90deg, transparent 0%, ${hexAlpha(0.07)} 35%, rgba(255,255,255,0.35) 50%, ${hexAlpha(0.07)} 65%, transparent 100%)` }}
            />
          </div>
        )}

        {/* Progress track — refined bottom bar with glow */}
        {(isLoading || phase === "completing") && (
          <div className="absolute bottom-0 left-0 right-0 h-[2px]" style={{ background: "rgba(0,0,0,0.02)" }}>
            <motion.div
              className="h-full rounded-full"
              style={{
                background: phase === "completing"
                  ? "linear-gradient(90deg, rgba(52, 199, 89, 0.5), rgba(52, 199, 89, 0.8))"
                  : `linear-gradient(90deg, ${hexAlpha(0.2)}, ${hexAlpha(0.5)})`,
                boxShadow: phase === "completing"
                  ? "0 0 8px rgba(52, 199, 89, 0.4)"
                  : `0 0 6px ${hexAlpha(0.2)}`,
              }}
              initial={false}
              animate={{ width: `${pct}%` }}
              transition={{ duration: 0.6, ease: [0.16, 1, 0.3, 1] }}
            />
          </div>
        )}

        <motion.button
          layout="position"
          onClick={() => canExpand && setOpen(!open)}
          className={`relative w-full flex items-center gap-3 px-3.5 py-2.5 text-left ${
            canExpand ? "cursor-pointer" : "cursor-default"
          }`}
          style={{ transition: "padding 0.3s ease" }}
        >
          {/* Icon container — orbital particles during loading */}
          <div className="relative shrink-0 flex items-center justify-center" style={{ width: 36, height: 36 }}>
            {isLoading ? (
              <>
                <OrbitalRing hex={meta.hex} pct={pct} size={36} />
                <motion.div
                  animate={{ scale: [1, 1.08, 1] }}
                  transition={{ duration: 2, repeat: Infinity, ease: "easeInOut" }}
                >
                  <Icon className="relative z-10" style={{ width: 14, height: 14, color: meta.hex, opacity: 0.7 }} />
                </motion.div>
              </>
            ) : phase === "completing" ? (
              <>
                <CompletionBurst hex={meta.hex} size={36} />
                <motion.div
                  initial={{ scale: 0, rotate: -180 }}
                  animate={{ scale: 1, rotate: 0 }}
                  transition={{ type: "spring", stiffness: 400, damping: 20, mass: 0.6 }}
                  className="relative z-10 flex items-center justify-center"
                  style={{
                    width: 36, height: 36, borderRadius: "50%",
                    background: "rgba(52, 199, 89, 0.1)",
                    boxShadow: "0 0 16px rgba(52, 199, 89, 0.15)",
                  }}
                >
                  <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="#34c759" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
                    <motion.path
                      d="M4 12 L9 17 L20 6"
                      initial={{ pathLength: 0, opacity: 0 }}
                      animate={{ pathLength: 1, opacity: 1 }}
                      transition={{ duration: 0.4, delay: 0.15, ease: [0.16, 1, 0.3, 1] }}
                    />
                  </svg>
                </motion.div>
              </>
            ) : (
              <motion.div
                className="flex items-center justify-center"
                style={{
                  width: 36, height: 36, borderRadius: "50%",
                  background: `${meta.hex}10`,
                  transition: "all 0.4s ease",
                }}
                whileHover={{ scale: 1.05, background: `${meta.hex}18` }}
              >
                <Icon style={{ width: 14, height: 14, color: meta.hex, opacity: 0.65 }} />
              </motion.div>
            )}
          </div>

          {/* Text content */}
          <div className="min-w-0 flex-1">
            <div className="flex items-center gap-2">
              <AnimatePresence mode="wait">
                <motion.span
                  key={isLoading ? (stage || "loading") : phase === "completing" ? "complete" : "done"}
                  initial={{ opacity: 0, y: 6, filter: "blur(4px)" }}
                  animate={{ opacity: 1, y: 0, filter: "blur(0px)" }}
                  exit={{ opacity: 0, y: -6, filter: "blur(4px)" }}
                  transition={{ duration: 0.25, ease: [0.16, 1, 0.3, 1] }}
                  className="text-[12.5px] font-medium tracking-[-0.01em] truncate flex-1 min-w-0"
                  style={{
                    color: phase === "completing" ? "rgba(52, 199, 89, 0.8)"
                      : isLoading ? "rgba(0,0,0,0.65)"
                      : "rgba(0,0,0,0.42)",
                  }}
                >
                  {isLoading
                    ? (stage && stage !== "starting" && stage !== "cached" ? stage : meta.label)
                    : phase === "completing"
                    ? "Complete"
                    : (typeof result === "string" ? result : meta.label)}
                </motion.span>
              </AnimatePresence>
              {isLoading && (
                <motion.span
                  initial={{ opacity: 0, scale: 0.8 }}
                  animate={{ opacity: 1, scale: 1 }}
                  className="text-[10px] font-mono tabular-nums shrink-0 tool-pct-counter"
                  style={{ color: hexAlpha(0.5) }}
                >
                  {pct}<span style={{ opacity: 0.5, fontSize: 8 }}>%</span>
                </motion.span>
              )}
            </div>
            {/* Micro action description visible during loading */}
            {isLoading && (
              <motion.div
                initial={{ opacity: 0, height: 0 }}
                animate={{ opacity: 1, height: "auto" }}
                transition={{ duration: 0.3, delay: 0.1 }}
              >
                <span className="text-[10px] tracking-wide" style={{ color: "rgba(0,0,0,0.22)" }}>
                  {action}
                </span>
              </motion.div>
            )}
          </div>

          {canExpand && phase === "done" && (
            <motion.div
              animate={{ rotate: open ? 180 : 0 }}
              transition={{ type: "spring", stiffness: 300, damping: 25 }}
            >
              <ChevronDown style={{ width: 14, height: 14, color: "rgba(0,0,0,0.15)" }} />
            </motion.div>
          )}
        </motion.button>

        {/* Expanded details panel */}
        <AnimatePresence initial={false}>
          {open && (
            <motion.div
              initial={{ height: 0, opacity: 0 }}
              animate={{ height: "auto", opacity: 1 }}
              exit={{ height: 0, opacity: 0 }}
              transition={{ duration: 0.3, ease: [0.25, 1, 0.5, 1] }}
              className="overflow-hidden"
            >
              <div className="px-3.5 pb-3 pt-0.5">
                <div className="ml-12 border-l pl-3 space-y-1.5" style={{ borderColor: "rgba(0,0,0,0.05)" }}>
                  <div className="flex items-center gap-1.5">
                    <span style={{ width: 5, height: 5, borderRadius: "50%", background: hexAlpha(0.4) }} />
                    <span className="text-[10px] font-mono tracking-wide" style={{ color: "rgba(0,0,0,0.25)" }}>{detail.endpoint}</span>
                  </div>
                  {detail.params.map(([k, v], i) => (
                    <motion.div
                      key={i}
                      initial={{ opacity: 0, x: -8 }}
                      animate={{ opacity: 1, x: 0 }}
                      transition={{ delay: i * 0.05, duration: 0.2 }}
                      className="flex items-baseline gap-2 text-[10px]"
                    >
                      <span className="uppercase tracking-wider text-[9px] min-w-[36px]" style={{ color: "rgba(0,0,0,0.18)" }}>{k}</span>
                      <span className="font-mono truncate" style={{ color: "rgba(0,0,0,0.38)" }}>{v}</span>
                    </motion.div>
                  ))}
                  {sources && sources.length > 0 && (
                    <div className="flex items-center gap-1.5 pt-1">
                      {sources.map((s, si) => (
                        <motion.span
                          key={s}
                          initial={{ opacity: 0, scale: 0.8 }}
                          animate={{ opacity: 1, scale: 1 }}
                          transition={{ delay: si * 0.05 }}
                          className="text-[9px] px-2 py-0.5 rounded-full font-medium"
                          style={{
                            background: "rgba(0,0,0,0.03)",
                            color: "rgba(0,0,0,0.28)",
                            boxShadow: "0 0 0 1px rgba(0,0,0,0.04)",
                          }}
                        >{s}</motion.span>
                      ))}
                    </div>
                  )}
                </div>
              </div>
            </motion.div>
          )}
        </AnimatePresence>
      </div>
    </motion.div>
  );
}

/* ── Markdown (Apple typography) ──────────────────────────── */
const mdComponents = {
  table: ({ children }) => (
    <div className="my-6 overflow-x-auto rounded-2xl ring-1 ring-black/[0.06] overflow-hidden">
      <table className="w-full text-[13px]">{children}</table>
    </div>
  ),
  thead: ({ children }) => <thead className="bg-black/[0.02]">{children}</thead>,
  th: ({ children }) => (
    <th className="px-4 py-3 text-left text-[11px] font-medium text-black/40 uppercase tracking-wider first:pl-5 last:pr-5 border-b border-black/[0.06]">{children}</th>
  ),
  tbody: ({ children }) => <tbody className="divide-y divide-black/[0.04]">{children}</tbody>,
  tr: ({ children }) => <tr className="hover:bg-black/[0.02] transition-colors duration-150">{children}</tr>,
  td: ({ children }) => (
    <td className="px-4 py-3.5 text-black/55 text-[13px] tabular-nums first:pl-5 last:pr-5 first:text-black/70">{children}</td>
  ),
  code: ({ children, className, node }) => {
    const isBlock = node?.parent?.type === "element" && node?.parent?.tagName === "pre";
    if (!isBlock) {
      return <code className="px-1.5 py-0.5 rounded-lg bg-black/[0.04] text-[12.5px] font-mono text-black/60">{children}</code>;
    }
    return <code className="block px-5 py-4 text-[12.5px] text-black/55 font-mono leading-relaxed">{children}</code>;
  },
  pre: ({ children }) => (
    <pre className="my-5 rounded-2xl bg-black/[0.03] ring-1 ring-black/[0.06] overflow-x-auto">{children}</pre>
  ),
  p: ({ children }) => <p className="mb-4 leading-[1.85] text-[14.5px] text-black/65 tracking-[-0.01em]">{children}</p>,
  h1: ({ children }) => (
    <h1 className="text-[22px] font-semibold text-black/90 mt-8 mb-4 tracking-tight">{children}</h1>
  ),
  h2: ({ children }) => (
    <h2 className="text-[17px] font-semibold text-black/85 mt-7 mb-3 tracking-tight">{children}</h2>
  ),
  h3: ({ children }) => <h3 className="text-[15px] font-semibold text-black/75 mt-6 mb-2.5 tracking-tight">{children}</h3>,
  h4: ({ children }) => <h4 className="text-[14px] font-medium text-black/65 mt-5 mb-2">{children}</h4>,
  ul: ({ children }) => <ul className="mb-4 space-y-1 ml-0.5">{children}</ul>,
  ol: ({ children }) => <ol className="list-decimal mb-4 space-y-1 ml-5 text-black/60 text-[14px] leading-[1.8] marker:text-black/20">{children}</ol>,
  li: ({ children, node }) => {
    const isOrdered = node?.parent?.tagName === "ol";
    if (isOrdered) return <li className="text-black/60 text-[14px] leading-[1.8] pl-1">{children}</li>;
    return (
      <li className="text-black/60 text-[14px] leading-[1.8] flex gap-2.5">
        <span className="mt-[11px] shrink-0 w-1 h-1 rounded-full bg-black/20" />
        <span className="flex-1">{children}</span>
      </li>
    );
  },
  strong: ({ children }) => <strong className="text-black/90 font-semibold">{children}</strong>,
  em: ({ children }) => <em className="text-black/45 italic">{children}</em>,
  a: ({ href, children }) => (
    <a href={href} target="_blank" rel="noopener noreferrer"
      className="text-blue-600/80 hover:text-blue-700 underline underline-offset-2 decoration-blue-500/30 hover:decoration-blue-500/50 transition-colors">{children}</a>
  ),
  hr: () => <div className="my-8 h-px bg-gradient-to-r from-transparent via-black/[0.06] to-transparent" />,
  blockquote: ({ children }) => (
    <blockquote className="border-l-2 border-black/[0.1] pl-4 my-5 text-black/40">{children}</blockquote>
  ),
};

/* ── Helpers ──────────────────────────────────────────────── */
function parseFollowUps(text) {
  const pat = /\n*\*{0,2}-{2,}\s*follow[\s-]*ups?\s*-{2,}\*{0,2}\s*\n/i;
  const m = text.match(pat);
  if (!m) return { body: text, suggestions: [] };
  const body = text.slice(0, m.index).trimEnd();
  const raw = text.slice(m.index + m[0].length).trim();
  return { body, suggestions: raw.split("\n").map(l => l.replace(/^[-*•\d.)\]]+\s*/, "").trim()).filter(l => l.length > 5).slice(0, 3) };
}

function getSourceBadges(tools) {
  if (!tools?.length) return [];
  const seen = new Set();
  return tools.flatMap(t => t.sources || []).filter(Boolean).filter(s => { if (seen.has(s)) return false; seen.add(s); return true; });
}

function mergeSourceDetails(tools) {
  if (!tools?.length) return {};
  const merged = {};
  for (const t of tools) {
    if (t.source_details) for (const [k, v] of Object.entries(t.source_details)) {
      if (!merged[k]) {
        merged[k] = { ...v, items: v.items ? [...v.items] : [] };
        if (!merged[k].desc) merged[k].desc = "";
      } else {
        const existing = merged[k];
        if (v.desc && !existing.desc.includes(v.desc)) {
          existing.desc = existing.desc ? `${existing.desc} · ${v.desc}` : v.desc;
        }
        if (v.items?.length) {
          const seenIds = new Set(existing.items.map(i => i.doc_id || i.url).filter(Boolean));
          for (const item of v.items) {
            const id = item.doc_id || item.url;
            if (id && !seenIds.has(id)) { existing.items.push(item); seenIds.add(id); }
          }
        }
        if (v.url && !existing.url) existing.url = v.url;
        if (v.type === "filings" && existing.type === "api") existing.type = "filings";
      }
    }
  }
  return merged;
}

/* ── Known base URLs for sources ─────────────────────────── */
const SOURCE_URLS = {
  "EDINET": "https://disclosure2.edinet-fsa.go.jp/WEEK0010.aspx",
  "J-Quants": "https://jpx-jquants.com/",
  "JPX": "https://www.jpx.co.jp/english/listing/stocks/",
  "Stooq": "https://stooq.com/",
  "Yahoo Finance": "https://finance.yahoo.com/",
  "Web": "https://www.google.com/",
};

/* ── Source badge (glass pill) ────────────────────────────── */
function SourceBadge({ name, detail }) {
  const [open, setOpen] = useState(false);
  const ref = useRef(null);
  useEffect(() => {
    if (!open) return;
    const h = (e) => { if (ref.current && !ref.current.contains(e.target)) setOpen(false); };
    const k = (e) => { if (e.key === "Escape") setOpen(false); };
    document.addEventListener("mousedown", h);
    document.addEventListener("keydown", k);
    return () => { document.removeEventListener("mousedown", h); document.removeEventListener("keydown", k); };
  }, [open]);
  const hasDetail = detail && (detail.items?.length > 0 || detail.url || detail.desc);
  const baseUrl = detail?.url || SOURCE_URLS[name];
  const items = detail?.items || [];

  return (
    <div className="relative" ref={ref}>
      <button onClick={() => hasDetail && setOpen(!open)}
        className={`text-[11px] font-medium px-3.5 py-1.5 rounded-full transition-all duration-200 ${
          open ? "bg-black/[0.08] text-black/70 ring-1 ring-black/[0.1]"
            : hasDetail ? "bg-black/[0.04] text-black/50 hover:bg-black/[0.08] hover:text-black/70 ring-1 ring-black/[0.06] hover:ring-black/[0.12] cursor-pointer shadow-sm hover:shadow"
            : "bg-black/[0.03] text-black/30 ring-1 ring-black/[0.04]"
        }`}>{name}</button>
      <AnimatePresence>
        {open && hasDetail && (
          <motion.div initial={{ opacity: 0, y: 4, scale: 0.97 }} animate={{ opacity: 1, y: 0, scale: 1 }} exit={{ opacity: 0, y: 4, scale: 0.97 }}
            transition={{ duration: 0.15, ease: [0.25, 1, 0.5, 1] }}
            className="absolute bottom-full left-0 mb-2 w-[300px] max-h-[260px] overflow-y-auto rounded-2xl bg-white backdrop-blur-2xl ring-1 ring-black/[0.08] shadow-2xl shadow-black/10 z-50">
            <div className="px-3.5 pt-2.5 pb-2 border-b border-black/[0.06] flex items-center justify-between">
              <span className="text-[11px] font-medium text-black/50">{name}</span>
              <button onClick={() => setOpen(false)} className="text-black/20 hover:text-black/40 transition-colors"><X className="w-3 h-3" /></button>
            </div>
            {detail.desc && <div className="px-3.5 py-2 text-[10px] text-black/30 font-mono">{detail.desc}</div>}
            {baseUrl && (
              <a href={baseUrl} target="_blank" rel="noopener noreferrer"
                className="flex items-center gap-2 mx-3 my-1.5 px-2.5 py-2 rounded-xl bg-blue-50 hover:bg-blue-100 text-[10px] text-blue-600/70 hover:text-blue-700 font-mono transition-all truncate">
                <Globe className="w-3 h-3 shrink-0" />
                <span className="truncate">{baseUrl.replace(/^https?:\/\//, "").split("?")[0]}</span>
              </a>
            )}
            {(() => {
              const linked = items.filter(i => i.url);
              if (!linked.length) return null;
              return (
                <div className="px-3.5 pb-2.5 pt-1">
                  <div className="text-[9px] text-black/25 uppercase tracking-wider mb-1.5">
                    {linked[0]?.doc_id ? "Filings" : "Results"} ({linked.length})
                  </div>
                  <div className="space-y-0.5">
                    {linked.map((item, i) => (
                      <a key={item.doc_id || item.url || i} href={item.url} target="_blank" rel="noopener noreferrer"
                        className="flex items-start gap-2 px-2 py-1.5 rounded-xl hover:bg-black/[0.03] transition-colors group">
                        <FileText className="w-3 h-3 shrink-0 text-black/15 group-hover:text-black/35 mt-0.5" />
                        <div className="min-w-0 flex-1">
                          <p className="text-[10px] text-black/40 group-hover:text-black/65 truncate">
                            {item.title || item.description || item.filer || item.doc_id}
                          </p>
                          {item.date && <p className="text-[9px] text-black/25 mt-0.5">{item.date}</p>}
                        </div>
                      </a>
                    ))}
                  </div>
                </div>
              );
            })()}
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}

/* ── Thinking indicator (Apple-style pulsing orb) ──────────── */
function ThinkingIndicator() {
  return (
    <motion.div className="flex items-center gap-3 py-6" initial={{ opacity: 0 }} animate={{ opacity: 1 }}>
      <div className="relative w-5 h-5">
        <motion.div
          className="absolute inset-0 rounded-full bg-gradient-to-br from-blue-400/30 to-purple-400/20"
          animate={{ scale: [1, 1.3, 1], opacity: [0.5, 0.2, 0.5] }}
          transition={{ duration: 2, repeat: Infinity, ease: "easeInOut" }}
        />
        <motion.div
          className="absolute inset-1 rounded-full bg-gradient-to-br from-blue-400/40 to-purple-400/30"
          animate={{ scale: [1, 1.15, 1] }}
          transition={{ duration: 2, repeat: Infinity, ease: "easeInOut", delay: 0.1 }}
        />
      </div>
      <span className="text-[13px] text-black/25 font-light tracking-wide">Thinking</span>
    </motion.div>
  );
}

/* ── Animation presets ───────────────────────────────────── */
const msgSpring = { type: "spring", stiffness: 400, damping: 30 };

/* ══════════════════════════════════════════════════════════ */
/*   MAIN QUERY PAGE                                         */
/* ══════════════════════════════════════════════════════════ */
let _msgId = (() => {
  try {
    const saved = JSON.parse(localStorage.getItem("kabu-conversations") || "[]");
    let max = 0;
    for (const c of saved) for (const m of c.messages || []) if (m.id > max) max = m.id;
    return max;
  } catch { return 0; }
})();
const nextId = () => ++_msgId;

/* Check for Speech Recognition support once */
const HAS_SPEECH = typeof window !== "undefined" && !!(window.SpeechRecognition || window.webkitSpeechRecognition);

export default function Query() {
  const location = useLocation();
  const pendingPromptRef = useRef(null);
  const [conversations, setConversations] = useState(() => loadConversations());
  const [activeConvoId, setActiveConvoId] = useState(null);
  const [sidebarOpen, setSidebarOpen] = useState(() => { try { return localStorage.getItem("kabu-sidebar") !== "closed"; } catch { return true; } });
  const [messages, setMessages] = useState([]);
  const [input, setInput] = useState("");
  const [companyContext, setCompanyContext] = useState(null);
  const [isStreaming, setIsStreaming] = useState(false);
  const [streamText, setStreamText] = useState("");
  const [streamTools, setStreamTools] = useState([]);
  const [speedMode, setSpeedMode] = useState(() => { try { return localStorage.getItem("kabu-speed") || "instant"; } catch { return "instant"; } });
  const [chatOpen, setChatOpen] = useState(false);
  const textBufferRef = useRef("");
  const rafRef = useRef(null);
  const textareaRef = useRef(null);
  const scrollRef = useRef(null);
  const abortRef = useRef(null);
  const streamingRef = useRef(false);

  /* ── Voice input state ── */
  const [isListening, setIsListening] = useState(false);
  const recognitionRef = useRef(null);

  /* ── Copy feedback state ── */
  const [copiedId, setCopiedId] = useState(null);
  const copyTimerRef = useRef(null);

  const toggleSidebar = useCallback(() => {
    setSidebarOpen(prev => { const n = !prev; try { localStorage.setItem("kabu-sidebar", n ? "open" : "closed"); } catch {} return n; });
  }, []);

  useEffect(() => {
    if (messages.length === 0 || isStreaming) return;
    setConversations(prev => {
      let updated;
      if (activeConvoId) { updated = prev.map(c => c.id === activeConvoId ? { ...c, messages, updatedAt: Date.now() } : c); }
      else { const id = newConvoId(); setActiveConvoId(id); updated = [{ id, messages, createdAt: Date.now(), updatedAt: Date.now() }, ...prev]; }
      saveConversations(updated); return updated;
    });
  }, [messages, isStreaming, activeConvoId]);

  const handleSelectConvo = useCallback((id) => {
    if (isStreaming) return;
    const c = conversations.find(c => c.id === id);
    if (c) { setMessages(c.messages || []); setActiveConvoId(id); setStreamText(""); setStreamTools([]); setCompanyContext(null); userScrolledUpRef.current = false; }
  }, [conversations, isStreaming]);

  const handleDeleteConvo = useCallback((id) => {
    if (activeConvoId === id && isStreaming) {
      if (abortRef.current) abortRef.current.abort();
      streamingRef.current = false;
      setIsStreaming(false); setStreamText(""); setStreamTools([]); textBufferRef.current = "";
    }
    setConversations(prev => { const u = prev.filter(c => c.id !== id); saveConversations(u); return u; });
    if (activeConvoId === id) { setMessages([]); setActiveConvoId(null); setCompanyContext(null); }
  }, [activeConvoId, isStreaming]);

  const hasMessages = messages.length > 0 || isStreaming;

  // Auto-scroll
  const [showScrollBtn, setShowScrollBtn] = useState(false);
  const userScrolledUpRef = useRef(false);
  const showScrollBtnRef = useRef(false);
  useEffect(() => {
    const el = scrollRef.current; if (!el) return;
    const h = () => {
      const d = el.scrollHeight - el.scrollTop - el.clientHeight;
      userScrolledUpRef.current = d > 150;
      const shouldShow = d > 300;
      if (shouldShow !== showScrollBtnRef.current) { showScrollBtnRef.current = shouldShow; setShowScrollBtn(shouldShow); }
    };
    el.addEventListener("scroll", h, { passive: true }); return () => el.removeEventListener("scroll", h);
  }, [hasMessages]);
  useEffect(() => {
    if (!scrollRef.current || userScrolledUpRef.current) return;
    requestAnimationFrame(() => scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight, behavior: isStreaming ? "auto" : "smooth" }));
  }, [messages, streamText, streamTools, isStreaming]);
  const scrollToBottom = useCallback(() => { scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight, behavior: "smooth" }); userScrolledUpRef.current = false; setShowScrollBtn(false); }, []);

  useEffect(() => {
    return () => {
      if (abortRef.current) abortRef.current.abort();
      if (recognitionRef.current) { try { recognitionRef.current.stop(); } catch {} recognitionRef.current = null; }
      if (copyTimerRef.current) clearTimeout(copyTimerRef.current);
    };
  }, []);
  useEffect(() => { const t = setTimeout(() => textareaRef.current?.focus(), 100); return () => clearTimeout(t); }, []);
  useEffect(() => { if (!isStreaming) { const t = setTimeout(() => textareaRef.current?.focus(), 50); return () => clearTimeout(t); } }, [isStreaming]);

  /* ── Pre-filled prompt from navigation state ── */
  useEffect(() => {
    if (location.state?.prompt || location.state?.company) {
      const company = location.state.company;
      const prompt = location.state.prompt;
      if (company) setCompanyContext(company);
      if (prompt) {
        // Prepend company context so the AI knows which stock to analyze
        pendingPromptRef.current = company
          ? `[Analyze: ${company}]\n\n${prompt}`
          : prompt;
      }
      window.history.replaceState({}, '');
    }
  }, [location.state]);

  /* ── Voice input handlers ── */
  const startListening = useCallback(() => {
    if (!HAS_SPEECH) return;
    const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
    const recognition = new SpeechRecognition();
    recognition.continuous = false;
    recognition.interimResults = true;
    recognition.lang = "en-US";
    recognition.onresult = (event) => {
      if (!event.results?.length) return;
      const transcript = Array.from(event.results).map(r => r?.[0]?.transcript || "").join("");
      setInput(transcript);
      if (textareaRef.current) { textareaRef.current.style.height = "auto"; const limit = Math.min(160, window.innerHeight * 0.3); textareaRef.current.style.height = Math.min(textareaRef.current.scrollHeight, limit) + "px"; }
    };
    recognition.onend = () => setIsListening(false);
    recognition.onerror = () => setIsListening(false);
    recognitionRef.current = recognition;
    try {
      recognition.start();
      setIsListening(true);
    } catch {
      setIsListening(false);
    }
  }, []);

  const stopListening = useCallback(() => {
    try { if (recognitionRef.current) { recognitionRef.current.stop(); recognitionRef.current = null; } } catch {}
    setIsListening(false);
  }, []);

  /* ── Copy handler ── */
  const handleCopy = useCallback((id, text) => {
    navigator.clipboard.writeText(text).then(() => {
      setCopiedId(id);
      if (copyTimerRef.current) clearTimeout(copyTimerRef.current);
      copyTimerRef.current = setTimeout(() => setCopiedId(null), 2000);
    }).catch(() => {});
  }, []);

  const handleSend = useCallback(async (text) => {
    const q = (text || input).trim(); if (!q || streamingRef.current) return;
    if (isListening) stopListening();
    const userMsg = { id: nextId(), role: "user", content: q };
    const updated = [...messages, userMsg];
    streamingRef.current = true;
    setMessages(updated); setInput(""); setIsStreaming(true); setStreamText(""); setStreamTools([]);
    if (abortRef.current) abortRef.current.abort();
    const controller = new AbortController(); abortRef.current = controller;
    if (textareaRef.current) textareaRef.current.style.height = "auto";
    const apiMessages = updated.map(m => ({ role: m.role, content: m.content }));
    let fullText = ""; const tools = [];
    textBufferRef.current = "";
    const isInstant = speedMode === "instant";
    try {
      await streamChat(apiMessages, {
        signal: controller.signal,
        mode: speedMode,
        onText: (chunk) => {
          fullText += chunk;
          textBufferRef.current = fullText;
          if (!isInstant && !rafRef.current) {
            rafRef.current = requestAnimationFrame(() => {
              rafRef.current = null;
              setStreamText(textBufferRef.current);
            });
          }
        },
        onToolCall: ({ id, tool, input: ti }) => { tools.push({ id, tool, input: ti, result: null, isLoading: true, serverPct: 5, serverStage: "starting" }); setStreamTools([...tools]); },
        onToolProgress: (data) => {
          const tc = tools.find(t => (data.id ? t.id === data.id : t.tool === data.tool) && t.isLoading);
          if (tc) {
            tc.serverPct = data.pct;
            tc.serverStage = data.stage || "";
            setStreamTools([...tools]);
          }
        },
        onToolResult: (data) => {
          const tc = tools.find(t => (data.id ? t.id === data.id : t.tool === data.tool) && t.isLoading);
          if (tc) {
            tc.result = data.summary; tc.isLoading = false; tc.serverPct = 100; tc.sources = data.sources || []; tc.source_details = data.source_details || {};
            if (data.tool === "get_stock_prices" && data.stock_code) {
              tc.stock_code = data.stock_code; tc.live_price = data.live_price; tc.live_change_pct = data.live_change_pct;
              tc.market_state = data.market_state; tc.previous_close = data.previous_close; tc.price_history = data.price_history;
            }
          }
          setStreamTools([...tools]);
        },
        onError: (msg) => { if (!controller.signal.aborted) { fullText += `\n\n*Error: ${msg}*`; textBufferRef.current = fullText; if (!isInstant) setStreamText(fullText); } },
        onDone: () => { if (isInstant) setStreamText(textBufferRef.current); },
      });
    } catch {
      // Network error or abort — ignore
    }
    if (rafRef.current) { cancelAnimationFrame(rafRef.current); rafRef.current = null; }
    if (!streamingRef.current) return; // handleStop already cleaned up
    setMessages(prev => [...prev, { id: nextId(), role: "assistant", content: fullText || textBufferRef.current, tools: [...tools] }]);
    streamingRef.current = false;
    setStreamText(""); setStreamTools([]); setIsStreaming(false); textBufferRef.current = "";
  }, [input, messages, speedMode, isListening, stopListening]);

  const handleStop = useCallback(() => {
    if (!streamingRef.current) return;
    if (abortRef.current) abortRef.current.abort();
    const savedText = textBufferRef.current || streamText;
    if (savedText?.trim() || streamTools.length > 0) setMessages(prev => [...prev, { id: nextId(), role: "assistant", content: savedText || "", tools: [...streamTools] }]);
    streamingRef.current = false;
    setStreamText(""); setStreamTools([]); setIsStreaming(false); textBufferRef.current = "";
    textareaRef.current?.focus();
  }, [streamText, streamTools]);

  const handleNewChat = useCallback(() => {
    if (abortRef.current) abortRef.current.abort();
    if (isListening) stopListening();
    streamingRef.current = false;
    setMessages([]); setActiveConvoId(null); setInput(""); setStreamText(""); setStreamTools([]); setIsStreaming(false); setCompanyContext(null); textBufferRef.current = "";
    textareaRef.current?.focus();
  }, [isListening, stopListening]);

  /* ── Cleanup pending RAF on unmount ── */
  useEffect(() => {
    return () => { if (rafRef.current) { cancelAnimationFrame(rafRef.current); rafRef.current = null; } };
  }, []);

  /* ── Fire pre-filled prompt from ReportViewer tools ── */
  useEffect(() => {
    if (pendingPromptRef.current && !streamingRef.current) {
      const prompt = pendingPromptRef.current;
      pendingPromptRef.current = null;
      const t = setTimeout(() => handleSend(prompt), 200);
      return () => clearTimeout(t);
    }
  }, [handleSend]);

  /* ── Keyboard shortcuts ── */
  useEffect(() => {
    const handleKeyDown = (e) => {
      if ((e.metaKey || e.ctrlKey) && e.key === "n") { e.preventDefault(); handleNewChat(); }
    };
    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [handleNewChat]);

  /* ── Render helpers (plain functions, NOT React components) ── */

  const renderSpeedToggle = () => (
    <div className="relative group/speed">
      <button
        onClick={() => {
          const next = speedMode === "stream" ? "instant" : "stream";
          setSpeedMode(next);
          try { localStorage.setItem("kabu-speed", next); } catch {}
        }}
        className="flex items-center gap-1.5 px-3 py-1.5 rounded-full bg-black/[0.03] hover:bg-black/[0.06] text-[11px] text-black/30 hover:text-black/50 transition-all duration-200"
      >
        {speedMode === "stream" ? <Clock className="w-3 h-3" /> : <Zap className="w-3 h-3" />}
        {speedMode === "stream" ? "Max" : "Min"}
      </button>
      <div className="absolute bottom-full left-1/2 -translate-x-1/2 mb-2.5 px-3 py-1.5 rounded-lg bg-black text-white text-[11px] font-semibold whitespace-nowrap opacity-0 group-hover/speed:opacity-100 pointer-events-none transition-opacity duration-200 shadow-xl z-50">
        {speedMode === "stream" ? "Mischa 1.0 Max" : "Mischa 1.2 Min"}
        <div className="absolute top-full left-1/2 -translate-x-1/2 w-2 h-2 bg-black rotate-45 -mt-1" />
      </div>
    </div>
  );

  const handleMicClick = useCallback(() => {
    if (isListening) stopListening(); else startListening();
  }, [isListening, startListening, stopListening]);

  const handleVoiceClick = useCallback(() => {
    setChatOpen(true);
  }, []);

  const renderInputBar = (placeholder = "How can I help you today?", large = false) => (
    <div className="relative group/bar">
      {/* Ambient glow on focus */}
      <div className="absolute -inset-1 rounded-[20px] bg-gradient-to-b from-black/[0.03] to-transparent opacity-0 group-focus-within/bar:opacity-100 blur-xl transition-opacity duration-700 pointer-events-none" />

      <div className={`relative flex flex-col rounded-2xl border border-black/[0.08] group-focus-within/bar:border-black/[0.15] transition-all duration-500 ${
        large
          ? "bg-white shadow-[0_8px_60px_-12px_rgba(0,0,0,0.08)]"
          : "bg-white/95 backdrop-blur-xl shadow-[0_4px_30px_-8px_rgba(0,0,0,0.06)]"
      }`}>
        {/* Textarea area */}
        <textarea
          ref={textareaRef}
          rows={1}
          value={input}
          onChange={(e) => { setInput(e.target.value); e.target.style.height = "auto"; const limit = Math.min(160, window.innerHeight * 0.3); e.target.style.height = Math.min(e.target.scrollHeight, limit) + "px"; }}
          onKeyDown={(e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); if (!isStreaming) handleSend(); } }}
          placeholder={isListening ? "Listening..." : placeholder}
          className={`w-full bg-transparent text-black/85 placeholder-black/25 text-[15px] outline-none resize-none leading-relaxed tracking-[-0.01em] px-5 pt-4 pb-2 ${isListening ? "placeholder-red-400/50" : ""}`}
          style={{ minHeight: large ? "48px" : "32px", maxHeight: "min(160px, 30vh)" }}
        />

        {/* Action row */}
        <div className="flex items-center justify-between px-3 pb-3 pt-1">
          {/* Left spacer */}
          <div className="flex items-center" />

          {/* Right side */}
          <div className="flex items-center gap-2.5">
            {renderSpeedToggle()}

            {isListening && (
              <motion.span
                className="text-[10px] text-red-400/70 font-medium"
                initial={{ opacity: 0 }}
                animate={{ opacity: [0.5, 1, 0.5] }}
                transition={{ duration: 1.5, repeat: Infinity }}
              >
                Recording...
              </motion.span>
            )}

            {/* Mic button */}
            {HAS_SPEECH && !isStreaming && (
              <div className="relative group/mic">
                <button
                  type="button"
                  onClick={handleMicClick}
                  className={`flex items-center justify-center w-10 h-10 rounded-xl transition-all duration-200 ${
                    isListening
                      ? "bg-red-500/15 text-red-400 ring-1 ring-red-500/25 hover:bg-red-500/25"
                      : "text-black/25 hover:text-black/50 hover:bg-black/[0.04]"
                  }`}
                >
                  {isListening ? <MicOff className="w-[18px] h-[18px]" /> : <Mic className="w-[18px] h-[18px]" />}
                </button>
                {!isListening && (
                  <div className="absolute bottom-full left-1/2 -translate-x-1/2 mb-2.5 px-3 py-1.5 rounded-lg bg-black text-white text-[11px] font-semibold whitespace-nowrap opacity-0 group-hover/mic:opacity-100 pointer-events-none transition-opacity duration-200 shadow-xl z-50">
                    Dictate
                    <div className="absolute top-full left-1/2 -translate-x-1/2 w-2 h-2 bg-black rotate-45 -mt-1" />
                  </div>
                )}
              </div>
            )}

            {/* Send / Stop / Voice */}
            {isStreaming ? (
              <button
                type="button"
                onClick={handleStop}
                className="flex items-center gap-1.5 px-4 py-2.5 rounded-xl text-[12px] font-medium bg-black/[0.05] text-black/40 hover:bg-black/[0.1] hover:text-black/60 transition-all duration-200"
              >
                <Square className="w-2.5 h-2.5 fill-current" /> Stop
              </button>
            ) : input.trim() ? (
              <button
                type="button"
                onClick={() => handleSend()}
                className="flex items-center justify-center w-10 h-10 rounded-full bg-black text-white hover:bg-gray-800 transition-all duration-200 shadow-lg shadow-black/15"
              >
                <ArrowUp className="w-4 h-4" strokeWidth={2.5} />
              </button>
            ) : (
              <div className="relative group/voice">
                <button
                  type="button"
                  onClick={handleVoiceClick}
                  className="flex items-center justify-center w-10 h-10 rounded-xl text-black/25 hover:text-black/50 hover:bg-black/[0.04] transition-all duration-200"
                >
                  <svg className="w-5 h-5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round">
                    <line x1="4" y1="12" x2="4" y2="12" />
                    <line x1="8" y1="8" x2="8" y2="16" />
                    <line x1="12" y1="4" x2="12" y2="20" />
                    <line x1="16" y1="8" x2="16" y2="16" />
                    <line x1="20" y1="12" x2="20" y2="12" />
                  </svg>
                </button>
                <div className="absolute bottom-full left-1/2 -translate-x-1/2 mb-2.5 px-3 py-1.5 rounded-lg bg-black text-white text-[11px] font-semibold whitespace-nowrap opacity-0 group-hover/voice:opacity-100 pointer-events-none transition-opacity duration-200 shadow-xl z-50">
                  Voice mode
                  <div className="absolute top-full left-1/2 -translate-x-1/2 w-2 h-2 bg-black rotate-45 -mt-1" />
                </div>
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  );

  /* ─── Render helper: assistant message block ─── */
  const renderAssistant = (msg, streaming = false) => {
    const text = streaming ? streamText : msg?.content || "";
    const msgTools = streaming ? streamTools : msg?.tools || [];
    const { body, suggestions } = parseFollowUps(text);
    const sources = getSourceBadges(msgTools);
    const sourceDetails = mergeSourceDetails(msgTools);
    const pt = msgTools.find(tc => tc.tool === "get_stock_prices" && tc.stock_code && tc.live_price && !tc.isLoading);
    const quickActions = !streaming && !isStreaming ? getQuickActions(msgTools) : [];

    return (
      <>
        {/* Tool pills */}
        {msgTools.length > 0 && (
          <div className="flex flex-wrap gap-2 mb-5">
            {msgTools.map((tc, i) => (
              <ToolPill key={tc.id || `${tc.tool}-${i}`} tool={tc.tool} input={tc.input} result={tc.result}
                isLoading={streaming ? tc.isLoading : false} sources={tc.sources}
                serverPct={streaming ? tc.serverPct : null} serverStage={streaming ? tc.serverStage : null} />
            ))}
          </div>
        )}

        {/* Price ticker */}
        {pt && (
          <div className="mb-5">
            <LivePriceTicker stockCode={pt.stock_code} initialPrice={pt.live_price} initialChangePct={pt.live_change_pct}
              marketState={pt.market_state} previousClose={pt.previous_close} priceHistory={pt.price_history} />
          </div>
        )}

        {/* Text body */}
        {text ? (
          <div className="max-w-none mt-1 overflow-hidden">
            <ReactMarkdown remarkPlugins={REMARK_PLUGINS} components={mdComponents}>{body}</ReactMarkdown>
            {streaming && (
              <span className="inline-block w-[2px] h-[16px] bg-black/30 ml-0.5 -mb-0.5 align-text-bottom streaming-cursor" />
            )}
          </div>
        ) : streaming ? (
          <ThinkingIndicator />
        ) : null}

        {/* Copy button */}
        {msg && !streaming && text && (
          <div className="flex items-center gap-1.5 mt-3">
            <button
              onClick={() => handleCopy(msg.id, text)}
              className="flex items-center gap-1.5 px-2.5 py-1 rounded-lg text-[10px] text-black/20 hover:text-black/50 hover:bg-black/[0.03] transition-all duration-200"
            >
              {copiedId === msg.id ? <Check className="w-3 h-3 text-emerald-400/60" /> : <Copy className="w-3 h-3" />}
              {copiedId === msg.id ? <span className="text-emerald-400/60">Copied</span> : "Copy"}
            </button>
          </div>
        )}

        {/* Sources */}
        {sources.length > 0 && (
          <div className="flex items-center flex-wrap gap-2.5 mt-6 pt-4 border-t border-black/[0.05]">
            <span className="text-[10px] text-black/30 uppercase tracking-widest font-semibold">Sources</span>
            {sources.map(s => <SourceBadge key={s} name={s} detail={sourceDetails[s]} />)}
          </div>
        )}

        {/* Smart quick actions — context-aware drill-down */}
        {quickActions.length > 0 && (
          <div className="mt-5">
            <span className="text-[10px] text-black/30 uppercase tracking-widest font-semibold mb-2 block">Dive deeper</span>
            <div className="flex flex-wrap gap-1.5">
              {quickActions.map((a, i) => {
                const ActionIcon = a.icon;
                return (
                  <motion.button
                    key={i}
                    onClick={() => handleSend(a.query)}
                    className="flex items-center gap-1.5 px-3 py-2 rounded-xl bg-black/[0.03] hover:bg-black/[0.06] ring-1 ring-black/[0.05] hover:ring-black/[0.12] transition-all duration-200 group"
                    initial={{ opacity: 0, y: 4 }}
                    animate={{ opacity: 1, y: 0 }}
                    transition={{ delay: 0.05 + i * 0.04 }}
                    whileHover={{ scale: 1.02 }}
                    whileTap={{ scale: 0.98 }}
                  >
                    <ActionIcon className="w-3 h-3 text-black/25 group-hover:text-black/50" />
                    <span className="text-[11px] text-black/30 group-hover:text-black/60 font-medium">{a.label}</span>
                  </motion.button>
                );
              })}
            </div>
          </div>
        )}

        {/* Follow-up suggestions */}
        {suggestions.length > 0 && !isStreaming && !streaming && (
          <div className="flex flex-wrap gap-2 mt-5">
            {suggestions.map((s, i) => (
              <motion.button key={i} onClick={() => handleSend(s)}
                className="px-3.5 py-2.5 rounded-2xl bg-black/[0.03] hover:bg-black/[0.06] ring-1 ring-black/[0.05] hover:ring-black/[0.12] transition-all duration-200 group"
                initial={{ opacity: 0, y: 4 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: 0.05 + i * 0.05 }}>
                <span className="text-black/35 group-hover:text-black/65 text-[12.5px] text-left leading-snug">{s}</span>
              </motion.button>
            ))}
          </div>
        )}
      </>
    );
  };

  return (
    <div className="h-dvh flex bg-[#f8f9fb] text-black overflow-hidden relative">
      {/* Interactive flow field background */}
      <div className="absolute inset-0 z-0">
        <FlowFieldBackground colorMode={speedMode} />
      </div>

      <div className="flex-1 flex flex-col overflow-hidden relative z-10">

        {/* Header — minimal Apple style */}
        <header className={`relative z-20 shrink-0 flex items-center justify-between px-6 pt-4 pb-2 ${sidebarOpen ? "" : "pr-14"}`}>
          <Link to="/" state={{ openContent: true }} className="flex items-center gap-2 h-9 px-3 rounded-xl bg-black/[0.04] ring-1 ring-black/[0.06] hover:bg-black/[0.08] hover:ring-black/[0.12] text-black/50 hover:text-black/80 transition-all duration-200 group">
            <ArrowLeft className="w-4 h-4 group-hover:-translate-x-0.5 transition-transform" />
            <span className="text-[13px] font-medium tracking-wide">Back</span>
          </Link>
          <div className="flex items-center gap-2">
            {hasMessages && (
              <motion.button
                onClick={handleNewChat}
                className="flex items-center gap-1.5 h-9 px-3.5 rounded-xl text-[13px] text-black/50 hover:text-black/80 bg-black/[0.04] ring-1 ring-black/[0.06] hover:bg-black/[0.08] hover:ring-black/[0.12] font-medium transition-all duration-200"
                whileHover={{ scale: 1.02 }}
                whileTap={{ scale: 0.98 }}
              >
                <Plus className="w-3.5 h-3.5" /> New
              </motion.button>
            )}
          </div>
        </header>

        {/* ─── Empty state ─── */}
        {!hasMessages && (
          <div className="flex-1 flex flex-col items-center justify-center px-6 -mt-24">
            <div className="w-full max-w-[720px]">
              {/* Heading */}
              <motion.div
                className="text-center mb-10"
                initial={{ opacity: 0, y: 12 }}
                animate={{ opacity: 1, y: 0 }}
                transition={{ duration: 0.7, delay: 0.1, ease: [0.16, 1, 0.3, 1] }}
              >
                <h2 className="text-2xl sm:text-3xl md:text-[32px] font-semibold text-black/85 tracking-tight leading-tight">
                  What would you like to know?
                </h2>
                {companyContext && (
                  <div className="mt-3 flex items-center justify-center gap-2">
                    <span className="inline-flex items-center gap-1.5 px-3 py-1 rounded-full bg-blue-50 ring-1 ring-blue-200/50 text-[12px] font-medium text-blue-600">
                      <Target className="w-3 h-3" />
                      {companyContext}
                    </span>
                  </div>
                )}
              </motion.div>

              {/* Input bar */}
              <motion.div
                initial={{ opacity: 0, y: 8 }}
                animate={{ opacity: 1, y: 0 }}
                transition={{ duration: 0.6, delay: 0.15, ease: [0.16, 1, 0.3, 1] }}
              >
                {renderInputBar(companyContext ? `Ask about ${companyContext}...` : "How can I help you today?", true)}
              </motion.div>
            </div>

            {/* Disclaimer */}
            <motion.p
              className="absolute bottom-5 text-[11px] text-black/20"
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              transition={{ delay: 0.5, duration: 0.5 }}
            >
              AI can make mistakes. Check important information.
            </motion.p>
          </div>
        )}

        {/* ─── Chat view ─── */}
        {hasMessages && (
          <>
            <div className="relative z-10 flex-1 overflow-hidden">
              {/* Top fade — transparent so background shows through */}

              <div ref={scrollRef} className="h-full overflow-y-auto query-scroll">
                <div className="max-w-[720px] mx-auto px-6 pt-8 pb-8">
                  {messages.map((msg) =>
                    msg.role === "user" ? (
                      <motion.div key={msg.id} className="flex justify-end mb-6" initial={{ opacity: 0, y: 6 }} animate={{ opacity: 1, y: 0 }} transition={msgSpring}>
                        <div className="max-w-[75%] rounded-[20px] rounded-br-md bg-black/[0.04] backdrop-blur-sm" style={{ padding: "12px 18px" }}>
                          <p className="text-[14.5px] text-black/75 leading-relaxed whitespace-pre-wrap break-words">{msg.content}</p>
                        </div>
                      </motion.div>
                    ) : (
                      <motion.div key={msg.id} className="mb-8" initial={{ opacity: 0, y: 6 }} animate={{ opacity: 1, y: 0 }} transition={msgSpring}>
                        {renderAssistant(msg)}
                      </motion.div>
                    )
                  )}

                  {/* Streaming response */}
                  {isStreaming && (
                    <motion.div className="mb-8" initial={{ opacity: 0 }} animate={{ opacity: 1 }}>
                      {renderAssistant(null, true)}
                    </motion.div>
                  )}
                  <div className="h-32" />
                </div>
              </div>

              {/* Bottom fade — removed to prevent whitish overlay */}

              {/* Scroll to bottom */}
              <AnimatePresence>
                {showScrollBtn && (
                  <motion.button initial={{ opacity: 0, y: 8, scale: 0.9 }} animate={{ opacity: 1, y: 0, scale: 1 }} exit={{ opacity: 0, y: 8, scale: 0.9 }}
                    onClick={scrollToBottom}
                    className="absolute bottom-8 left-1/2 -translate-x-1/2 z-20 w-8 h-8 rounded-full bg-white backdrop-blur-xl ring-1 ring-black/[0.08] flex items-center justify-center hover:bg-gray-50 transition-all duration-200 shadow-lg shadow-black/10">
                    <ArrowDown className="w-3.5 h-3.5 text-black/40" />
                  </motion.button>
                )}
              </AnimatePresence>
            </div>

            {/* Bottom input bar */}
            <div className="relative z-20 shrink-0 px-6 pb-2 pt-2">
              <div className="max-w-[720px] mx-auto">
                {renderInputBar("Ask a follow-up...")}
              </div>
              <p className="text-center text-[11px] text-black/20 mt-2 pb-1">
                AI can make mistakes. Check important information.
              </p>
            </div>
          </>
        )}
      </div>

      <Sidebar conversations={conversations} activeId={activeConvoId} onSelect={handleSelectConvo}
        onNew={handleNewChat} onDelete={handleDeleteConvo} isOpen={sidebarOpen} onToggle={toggleSidebar} />

      <VoiceOverlay isOpen={chatOpen} onClose={() => setChatOpen(false)} />

      <style>{`
        .query-scroll::-webkit-scrollbar { width: 4px; }
        .query-scroll::-webkit-scrollbar-track { background: transparent; }
        .query-scroll::-webkit-scrollbar-thumb { background: rgba(0,0,0,0.06); border-radius: 4px; }
        .query-scroll::-webkit-scrollbar-thumb:hover { background: rgba(0,0,0,0.12); }
        @keyframes blink { 0%, 100% { opacity: 1; } 50% { opacity: 0; } }
        .streaming-cursor { animation: blink 0.8s ease-in-out infinite; }
        @keyframes shimmer { 0% { transform: translateX(0); } 100% { transform: translateX(200%); } }
        .tool-shimmer { animation: shimmer 2.5s cubic-bezier(0.4, 0, 0.2, 1) infinite; }
        @keyframes glowPulse { 0%, 100% { opacity: 0.5; } 50% { opacity: 1; } }
        .tool-glow-pulse { animation: glowPulse 3s ease-in-out infinite; }
        .tool-pct-counter { font-feature-settings: "tnum" 1; }
      `}</style>
    </div>
  );
}
