import React, { useEffect, useMemo, useRef, useState } from "react";
import { motion, AnimatePresence } from "framer-motion";
import {
  ArrowLeft, Building2,
  Check, Loader2, Download, ExternalLink,
  Share2, RotateCcw, Database, BarChart3, Brain, Sparkles,
  PanelLeftClose, PanelLeftOpen, BookOpen, FileText,
} from "lucide-react";
import { Link, useLocation, useNavigate } from "react-router-dom";
import { startReport, getStatus, buildDownloadUrl, buildViewUrl } from "@/api/backend";
import SourcesModal from "@/components/report/SourcesModal";

/* ── Pipeline ─────────────────────────────────────────────── */
const PIPELINE = [
  { key: "Starting", icon: Sparkles,  label: "Initializing" },
  { key: "Company Info",  icon: Building2, label: "Company Info" },
  { key: "Data Fetch",    icon: Database,  label: "Data Fetch" },
  { key: "Extraction",    icon: FileText,  label: "Extraction" },
  { key: "Analysis",      icon: BarChart3, label: "Analysis" },
  { key: "Valuation",     icon: BarChart3, label: "Valuation" },
  { key: "Peers",         icon: BarChart3, label: "Compare Peers" },
  { key: "Drafting",      icon: Brain,     label: "Drafting" },
  { key: "Rendering",     icon: FileText,  label: "Rendering" },
  { key: "Complete",      icon: Check,     label: "Complete" },
];

const fmtTime = (s) => {
  if (s == null || Number.isNaN(s)) return "--:--";
  return `${Math.floor(s / 60)}:${String(Math.floor(s % 60)).padStart(2, "0")}`;
};

/* ── Status messages per stage ────────────────────────────── */
const STAGE_MESSAGES = {
  Starting:       ["Warming up the engine...", "Preparing analysis pipeline..."],
  "Company Info": ["Looking up company details...", "Fetching corporate profile..."],
  "Data Fetch":   ["Scanning EDINET filings...", "Pulling financial statements...", "Fetching stock price history..."],
  Extraction:     ["Extracting key financial data...", "Parsing segment information...", "Reading annual reports..."],
  Analysis:       ["Analyzing financial trends...", "Computing growth metrics...", "Evaluating business quality..."],
  Valuation:      ["Running DCF model...", "Computing peer multiples...", "Estimating intrinsic value...", "Building valuation range..."],
  Peers:          ["Fetching peer benchmarking data...", "Comparing sector peers...", "Building peer matrix..."],
  Drafting:       ["Writing executive summary...", "Composing investment thesis...", "Drafting financial analysis..."],
  Rendering:      ["Generating charts...", "Formatting final report...", "Preparing PDF export..."],
  Complete:       ["Analysis complete."],
};

/* ── spring curve ── */
const ease = [0.16, 1, 0.3, 1];

/* ── Component ────────────────────────────────────────────── */
export default function GenerateReport() {
  const location = useLocation();
  const navigate = useNavigate();
  const search = useMemo(() => new URLSearchParams(location.search), [location.search]);

  const [ticker, setTicker] = useState(search.get("ticker") || "6501");
  const [companyName, setCompanyName] = useState(search.get("name") || "");
  const [mode, setMode] = useState(search.get("mode") || "full");
  const [jobId, setJobId] = useState(search.get("jobId") || null);
  const [status, setStatus] = useState(null);
  const [isStarting, setIsStarting] = useState(false);
  const [error, setError] = useState(null);
  const [showSources, setShowSources] = useState(false);

  const contentRef = useRef(null);

  // UI state
  const [sidebarOpen, setSidebarOpen] = useState(true);
  const [stageMsg, setStageMsg] = useState("");
  const stageMsgIdx = useRef(0);

  // Countdown timer refs
  const countdownRef = useRef(null);
  const serverEtaRef = useRef(null);
  const [displayEta, setDisplayEta] = useState(null);

  // Use interpolated progress from server for smooth bar, fall back to raw progress
  const pct = status?.interpolated_progress ?? status?.progress ?? 0;
  const step = status?.step || "Starting";
  const maxStepRef = useRef(0);
  const rawIdx = PIPELINE.findIndex((p) => p.key === step);
  if (rawIdx >= 0 && rawIdx > maxStepRef.current) maxStepRef.current = rawIdx;
  const stepIdx = rawIdx >= 0 ? rawIdx : maxStepRef.current;
  const isComplete = status?.status === "complete" || status?.status === "warning" || step === "Complete";
  const isError = status?.status === "error";
  const isRunning = !isComplete && !isError;
  const createdAt = status?.started_at || status?.created_at;
  const finishedAt = status?.finished_at;
  const [elapsed, setElapsed] = useState(null);

  // Auto-collapse sidebar on completion
  useEffect(() => {
    if (isComplete) setSidebarOpen(false);
  }, [isComplete]);

  // Sync active generating state to localStorage (for Home page indicator)
  useEffect(() => {
    if (jobId && isRunning) {
      try {
        localStorage.setItem("active_generating", JSON.stringify({
          jobId, ticker, companyName, startedAt: createdAt, mode,
        }));
      } catch {}
    }
    if (isComplete || isError) {
      try {
        const stored = localStorage.getItem("active_generating");
        if (stored) {
          const data = JSON.parse(stored);
          if (data.jobId === jobId) localStorage.removeItem("active_generating");
        }
      } catch {}
    }
  }, [jobId, isRunning, isComplete, isError, ticker, companyName, createdAt, mode]);

  // 1-second interval to keep elapsed timer ticking during the run
  useEffect(() => {
    if (!createdAt) { setElapsed(null); return; }
    const update = () => {
      const end = finishedAt ? new Date(finishedAt) : new Date();
      setElapsed(Math.max(0, Math.floor((end - new Date(createdAt)) / 1000)));
    };
    update();
    if (finishedAt) return;
    const iv = setInterval(update, 1000);
    return () => clearInterval(iv);
  }, [createdAt, finishedAt]);

  const downloadHtml = buildDownloadUrl(status?.html_file);
  const downloadPdf = buildDownloadUrl(status?.pdf_file);
  const viewHtml = buildViewUrl(status?.html_file);

  /* ── ETA: Smooth countdown driven by backend prediction ── */

  // Sync server ETA into ref (backend is single source of truth)
  useEffect(() => {
    const serverVal = status?.eta_seconds;
    if (serverVal != null) serverEtaRef.current = Math.min(serverVal, 300);
  }, [status?.eta_seconds]);

  // Smooth 1-second countdown that tracks server ETA without jarring resets
  useEffect(() => {
    if (!isRunning) {
      countdownRef.current = null;
      setDisplayEta(null);
      return;
    }
    const iv = setInterval(() => {
      const server = serverEtaRef.current;
      let current = countdownRef.current;

      // First tick — initialize from server
      if (current === null) {
        if (server != null) { countdownRef.current = server; setDisplayEta(Math.round(server)); }
        return;
      }

      // No server data yet — just count down
      if (server === null) {
        current = Math.max(0, current - 1);
        countdownRef.current = current;
        setDisplayEta(Math.round(current));
        return;
      }

      // Adaptive tick rate: steer toward server value smoothly
      const delta = server - current;
      let tickAmount;
      if (delta < -20)     tickAmount = 4.0;   // way ahead — drop fast
      else if (delta < -10) tickAmount = 3.0;
      else if (delta < -4) tickAmount = 2.0;
      else if (delta > 10) tickAmount = 0.2;   // behind — slow almost to a halt
      else if (delta > 4)  tickAmount = 0.5;
      else                 tickAmount = 1.0;   // on track

      current = Math.max(0, current - tickAmount);

      // Asymptotic floor: never hit 0 while server says work remains.
      // Instead of resetting from 0 → server (jarring), hold at a low value
      // and let the natural countdown from server corrections take over.
      if (current < 2 && server > 3) {
        current = Math.max(current, 2);
      }

      countdownRef.current = current;
      setDisplayEta(Math.round(current));
    }, 1000);
    return () => clearInterval(iv);
  }, [isRunning]);

  const eta = displayEta;

  /* ── Rotating stage messages ── */
  useEffect(() => {
    const msgs = STAGE_MESSAGES[step] || ["Processing..."];
    stageMsgIdx.current = 0;
    setStageMsg(msgs[0]);
    if (msgs.length <= 1) return;
    const iv = setInterval(() => {
      stageMsgIdx.current = (stageMsgIdx.current + 1) % msgs.length;
      setStageMsg(msgs[stageMsgIdx.current]);
    }, 3500);
    return () => clearInterval(iv);
  }, [step]);

  /* ── Start job ── */
  const startNewJob = async () => {
    if (!ticker) return;
    setIsStarting(true);
    setError(null);
    setStatus(null);
    countdownRef.current = null;
    serverEtaRef.current = null;
    try {
      const res = await startReport({ stock_code: ticker, company_name: companyName, mode });
      const id = res?.job_id;
      if (!id) throw new Error("Job ID missing");
      setJobId(id);
      const p = new URLSearchParams({ jobId: id, ticker, name: companyName || "", mode });
      navigate(`/GenerateReport?${p.toString()}`, { replace: true });
    } catch (err) {
      setError(err.message || "Failed to start");
    } finally {
      setIsStarting(false);
    }
  };

  // eslint-disable-next-line react-hooks/exhaustive-deps
  useEffect(() => { if (!jobId && ticker && !isStarting) startNewJob(); }, [jobId, ticker, isStarting, companyName, mode]);

  /* ── Poll status ── */
  useEffect(() => {
    if (!jobId) return;
    let dead = false, timer;
    const poll = async () => {
      try {
        const d = await getStatus(jobId);
        if (dead) return;
        setStatus(d);
        setError(null);
        setCompanyName((p) => p || d.company_name || "");
        if (d.status && ["complete", "warning", "error"].includes(d.status)) {
          try {
            const h = JSON.parse(localStorage.getItem("reports_history") || "[]");
            if (!h.some((entry) => entry.jobId === jobId)) {
              h.unshift({ jobId, ticker, companyName: d.company_name || companyName || ticker, html: d.html_file ? buildDownloadUrl(d.html_file) : null, pdf: d.pdf_file ? buildDownloadUrl(d.pdf_file) : null, finishedAt: d.finished_at || new Date().toISOString(), sources: d.sources || [] });
              localStorage.setItem("reports_history", JSON.stringify(h.slice(0, 50)));
            }
          } catch {}
          return;
        }
        timer = setTimeout(poll, 1200);
      } catch (err) {
        if (dead) return;
        if (err.status === 404 && ticker && !isStarting) { setJobId(null); return; }
        setError(err.message || "Status fetch failed");
        timer = setTimeout(poll, 2500);
      }
    };
    poll();
    return () => { dead = true; if (timer) clearTimeout(timer); };
  }, [jobId]);

  /* ── Handlers ── */
  const handleView = () => {
    if (viewHtml) navigate(`/Viewer?${new URLSearchParams({ url: viewHtml, title: companyName || ticker, jobId: jobId || "" })}`);
  };
  const handleDownload = () => {
    const url = downloadPdf || downloadHtml;
    if (url) { const a = document.createElement("a"); a.href = url; a.download = ""; a.target = "_blank"; a.rel = "noopener"; a.click(); }
  };
  const handleShare = () => {
    const link = viewHtml || window.location.href;
    window.location.href = `mailto:?subject=${encodeURIComponent(`Research report: ${companyName || ticker}`)}&body=${encodeURIComponent(`Report link:\n${link}`)}`;
  };
  const handleAskAI = () => {
    if (viewHtml) navigate(`/Viewer?${new URLSearchParams({ url: viewHtml, title: companyName || ticker, jobId: jobId || "" })}`, { state: { openTab: "ai" } });
  };

  /* ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
   *  Render
   * ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ */
  return (
    <div className="h-dvh flex flex-col overflow-hidden bg-white">

      {/* ━━ Top progress bar ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ */}
      <div className="h-[3px] w-full bg-black/[0.04] shrink-0 relative z-50" role="progressbar" aria-valuenow={Math.round(pct)} aria-valuemin={0} aria-valuemax={100}>
        {isComplete && (
          <motion.div
            initial={{ opacity: 0.4 }}
            animate={{ opacity: 0 }}
            transition={{ duration: 1.5, ease: "easeOut" }}
            className="absolute inset-0 z-10 bg-emerald-400/30"
          />
        )}
        <motion.div
          className={`h-full ${isComplete ? "bg-emerald-500" : "bg-[#de5f40]"}`}
          initial={{ width: 0 }}
          animate={{ width: `${pct}%` }}
          transition={{ duration: 0.6, ease: "easeOut" }}
        />
        {isRunning && (
          <motion.div
            className="absolute top-0 h-full w-32 bg-gradient-to-r from-transparent via-white/40 to-transparent"
            animate={{ left: ["-8rem", "100%"] }}
            transition={{ duration: 2, repeat: Infinity, ease: "linear" }}
          />
        )}
      </div>

      {/* ━━ Top bar ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ */}
      <header className="shrink-0 h-12 sm:h-14 border-b border-black/[0.06] bg-white/90 backdrop-blur-md flex items-center px-3 sm:px-4 gap-2 sm:gap-3 z-40">
        <Link to="/" state={{ openContent: true }} className="flex items-center gap-1.5 text-gray-400 hover:text-gray-700 transition-colors text-sm shrink-0">
          <ArrowLeft className="w-4 h-4" />
          <span className="hidden sm:inline">Back</span>
        </Link>

        <div className="h-5 w-px bg-black/[0.08] shrink-0" />

        <div className="flex items-center gap-2.5 min-w-0">
          <div className="w-8 h-8 rounded-lg bg-black/[0.03] border border-black/[0.06] flex items-center justify-center shrink-0">
            <Building2 className="w-4 h-4 text-gray-400" />
          </div>
          <div className="min-w-0">
            <p className="text-[#0a0a0a] font-medium text-sm truncate leading-tight" title={companyName || undefined}>
              {companyName || "Loading..."}
            </p>
            <p className="text-gray-400 text-xs leading-tight">
              <span className="text-[#de5f40] font-mono">{ticker}</span>
              {status?.financials_source && <span className="ml-1.5 text-gray-300">via {status.financials_source}</span>}
            </p>
          </div>
        </div>

        <div className="flex-1" />

        {/* Live stats — hidden on complete (shown in completion card instead) */}
        {isRunning && (
          <div className="hidden md:flex items-center gap-4 text-xs text-gray-400">
            {status?.source_count > 0 && <span>Sources: <span className="text-[#0a0a0a] font-mono">{status.source_count}</span></span>}
            {status?.edinet_count > 0 && <span>EDINET: <span className="text-[#0a0a0a] font-mono">{status.edinet_count}</span></span>}
            {status?.financial_rows > 0 && <span>Fin. rows: <span className="text-[#0a0a0a] font-mono">{status.financial_rows}</span></span>}
          </div>
        )}

        <div className="hidden sm:flex items-center gap-3 text-xs font-mono shrink-0">
          <span className="text-gray-400">{fmtTime(elapsed)}</span>
          {isRunning && eta != null && (
            <span className="text-[#de5f40]/80">ETA {fmtTime(eta)}</span>
          )}
          <span className={`font-semibold ${isComplete ? "text-emerald-600" : isError ? "text-red-500" : "text-[#de5f40]"}`}>
            {Math.round(pct)}%
          </span>
        </div>
      </header>

      {/* ━━ Main layout ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ */}
      <div className="flex-1 flex overflow-hidden">

        {/* ── Sidebar (auto-collapses on complete) ────── */}
        <AnimatePresence initial={false}>
          {sidebarOpen && (
            <motion.aside
              initial={{ width: 0, opacity: 0 }}
              animate={{ width: 260, opacity: 1 }}
              exit={{ width: 0, opacity: 0 }}
              transition={{ duration: 0.3, ease }}
              className="shrink-0 border-r border-black/[0.06] bg-[#fafafa] overflow-hidden flex flex-col"
              style={{ maxWidth: "70vw" }}
            >
              <div className="flex-1 overflow-y-auto p-4 space-y-6" style={{ width: "min(260px, 70vw)" }}>
                {/* Pipeline steps */}
                <div>
                  <h3 className="text-[11px] font-semibold uppercase tracking-widest text-gray-400 mb-3 px-1">Pipeline</h3>
                  <div className="space-y-1">
                    {PIPELINE.map((p, i) => {
                      const Icon = p.icon;
                      const done = i < stepIdx || isComplete;
                      const active = i === stepIdx && !isComplete;
                      return (
                        <motion.div
                          key={p.key}
                          initial={{ opacity: 0, x: -12 }}
                          animate={{ opacity: done || active ? 1 : 0.55, x: 0 }}
                          transition={{ delay: i * 0.03 }}
                          className={`flex items-center gap-2.5 px-3 py-2 rounded-lg transition-all duration-300 ${
                            active ? "bg-[#de5f40]/[0.06] border border-[#de5f40]/20" : "border border-transparent"
                          }`}
                        >
                          {done ? (
                            <motion.div initial={{ scale: 0 }} animate={{ scale: 1 }} className="w-5 h-5 rounded-full bg-emerald-500/15 flex items-center justify-center shrink-0">
                              <Check className="w-3 h-3 text-emerald-600" />
                            </motion.div>
                          ) : active ? (
                            <motion.div animate={{ rotate: 360 }} transition={{ duration: 1.2, repeat: Infinity, ease: "linear" }} className="w-5 h-5 rounded-full bg-[#de5f40]/10 flex items-center justify-center shrink-0">
                              <Loader2 className="w-3 h-3 text-[#de5f40]" />
                            </motion.div>
                          ) : (
                            <div className="w-5 h-5 rounded-full bg-black/[0.04] flex items-center justify-center shrink-0">
                              <Icon className="w-3 h-3 text-gray-400" />
                            </div>
                          )}
                          <span className={`text-xs font-medium ${active ? "text-[#de5f40]" : done ? "text-[#0a0a0a]" : "text-[#0a0a0a]/60"}`}>
                            {p.label}
                          </span>
                          {active && (
                            <motion.span animate={{ opacity: [1, 0.4, 1] }} transition={{ duration: 1.5, repeat: Infinity }} className="ml-auto text-[10px] font-semibold text-[#de5f40]/70">LIVE</motion.span>
                          )}
                          {done && <Check className="ml-auto w-3 h-3 text-emerald-500/40" />}
                        </motion.div>
                      );
                    })}
                  </div>
                </div>

                {/* Data health */}
                <div>
                  <h3 className="text-[11px] font-semibold uppercase tracking-widest text-gray-400 mb-3 px-1">Data</h3>
                  <div className="space-y-2 px-1">
                    {[
                      { l: "Sources", v: status?.source_count },
                      { l: "EDINET filings", v: status?.edinet_count },
                      { l: "Scanned", v: status?.edinet_scanned && status?.edinet_total ? `${status.edinet_scanned}/${status.edinet_total}` : null },
                      { l: "Financial rows", v: status?.financial_rows },
                      { l: "Price rows", v: status?.price_rows },
                    ].filter((x) => x.v != null && x.v !== 0).map((s) => (
                      <div key={s.l} className="flex justify-between items-center">
                        <span className="text-[11px] text-gray-400">{s.l}</span>
                        <span className="text-[11px] font-mono text-[#0a0a0a]">{s.v}</span>
                      </div>
                    ))}
                  </div>
                </div>

                {/* Timing */}
                <div>
                  <h3 className="text-[11px] font-semibold uppercase tracking-widest text-gray-400 mb-3 px-1">Timing</h3>
                  <div className="space-y-2 px-1">
                    <div className="flex justify-between items-center">
                      <span className="text-[11px] text-gray-400">Elapsed</span>
                      <span className="text-[11px] font-mono text-[#0a0a0a]">{fmtTime(elapsed)}</span>
                    </div>
                    {isRunning && eta != null && (
                      <div className="flex justify-between items-center">
                        <span className="text-[11px] text-gray-400">ETA</span>
                        <span className="text-[11px] font-mono text-[#de5f40]">{fmtTime(eta)}</span>
                      </div>
                    )}
                    <div className="flex justify-between items-center">
                      <span className="text-[11px] text-gray-400">Progress</span>
                      <span className="text-[11px] font-mono text-[#de5f40]">{Math.round(pct)}%</span>
                    </div>
                  </div>
                </div>
              </div>

              {/* Sidebar footer */}
              <div className="p-3 border-t border-black/[0.06]">
                <button onClick={() => setSidebarOpen(false)} className="w-full flex items-center justify-center gap-2 py-2 rounded-lg text-gray-400 hover:text-gray-600 hover:bg-black/[0.03] transition-colors text-xs">
                  <PanelLeftClose className="w-3.5 h-3.5" />Collapse
                </button>
              </div>
            </motion.aside>
          )}
        </AnimatePresence>

        {/* Sidebar toggle (when collapsed + running) */}
        {!sidebarOpen && isRunning && (
          <motion.button
            initial={{ opacity: 0, x: -10 }}
            animate={{ opacity: 1, x: 0 }}
            onClick={() => setSidebarOpen(true)}
            className="absolute left-2 top-[76px] z-30 w-8 h-8 rounded-lg bg-black/[0.03] border border-black/[0.06] flex items-center justify-center text-gray-400 hover:text-gray-600 hover:bg-black/[0.06] transition-colors"
          >
            <PanelLeftOpen className="w-4 h-4" />
          </motion.button>
        )}

        {/* ── Main content area ────────────────────────── */}
        <main className="flex-1 flex flex-col overflow-hidden relative">
          {/* Ambient glow */}
          <div className="absolute inset-0 pointer-events-none z-0">
            <motion.div
              animate={{ background: isComplete ? "radial-gradient(circle at 40% 30%, rgba(16,185,129,0.05) 0%, transparent 60%)" : "radial-gradient(circle at 50% 40%, rgba(222,95,64,0.03) 0%, transparent 60%)" }}
              transition={{ duration: 2 }}
              className="absolute inset-0"
            />
            {isComplete && (
              <motion.div
                initial={{ opacity: 0 }}
                animate={{ opacity: 1 }}
                transition={{ delay: 0.5, duration: 2 }}
                className="absolute inset-0"
                style={{ background: "radial-gradient(circle at 60% 70%, rgba(59,130,246,0.03) 0%, transparent 50%)" }}
              />
            )}
          </div>

          {/* Scrollable content */}
          <div ref={contentRef} className="flex-1 overflow-y-auto relative z-10">
            <AnimatePresence mode="wait">

              {/* ━━ RUNNING STATE ━━━━━━━━━━━━━━━━━━━━━━━━━━ */}
              {isRunning && (
                <motion.div
                  key="running"
                  initial={{ opacity: 0, y: 20 }}
                  animate={{ opacity: 1, y: 0 }}
                  exit={{ opacity: 0, scale: 0.95, filter: "blur(8px)" }}
                  transition={{ duration: 0.6 }}
                  className="flex flex-col items-center justify-center min-h-full py-32 px-6"
                >
                  {/* Animated orb */}
                  <div className="relative mb-8">
                    <motion.div
                      animate={{ scale: [1, 1.15, 1], opacity: [0.5, 1, 0.5] }}
                      transition={{ duration: 3, repeat: Infinity, ease: "easeInOut" }}
                      className="w-20 h-20 rounded-full bg-gradient-to-br from-[#de5f40]/15 to-[#de5f40]/5 flex items-center justify-center"
                    >
                      <motion.div
                        animate={{ rotate: 360 }}
                        transition={{ duration: 8, repeat: Infinity, ease: "linear" }}
                        className="w-12 h-12 rounded-full border-2 border-[#de5f40]/20 border-t-[#de5f40]"
                      />
                    </motion.div>
                    <motion.div
                      animate={{ scale: [1, 1.3, 1], opacity: [0.3, 0, 0.3] }}
                      transition={{ duration: 3, repeat: Infinity, ease: "easeInOut" }}
                      className="absolute inset-0 rounded-full border border-[#de5f40]/15"
                    />
                  </div>

                  <AnimatePresence mode="wait">
                    <motion.p
                      key={step + stageMsg}
                      initial={{ opacity: 0, y: 8 }}
                      animate={{ opacity: 1, y: 0 }}
                      exit={{ opacity: 0, y: -8 }}
                      transition={{ duration: 0.3 }}
                      className="text-gray-500 text-base text-center"
                    >
                      {stageMsg}
                    </motion.p>
                  </AnimatePresence>

                  <motion.p
                    initial={{ opacity: 0 }}
                    animate={{ opacity: 1 }}
                    transition={{ delay: 0.5 }}
                    className="text-gray-400 text-sm mt-3"
                  >
                    {step} — {Math.round(pct)}% complete
                  </motion.p>

                  {error && (
                    <p className="text-red-600 text-sm mt-4 bg-red-50 border border-red-200 rounded-lg px-4 py-2">{error}</p>
                  )}
                </motion.div>
              )}

              {/* ━━ COMPLETE STATE ━━━━━━━━━━━━━━━━━━━━━━━━━ */}
              {isComplete && (
                <motion.div
                  key="complete"
                  initial={{ opacity: 0 }}
                  animate={{ opacity: 1 }}
                  transition={{ duration: 0.8 }}
                  className="flex flex-col items-center min-h-full"
                >
                  {/* Spacer */}
                  <div className="flex-1 min-h-[8vh] max-h-[15vh]" />

                  {/* Success icon — clean, minimal */}
                  <motion.div
                    initial={{ scale: 0, opacity: 0 }}
                    animate={{ scale: 1, opacity: 1 }}
                    transition={{ type: "spring", stiffness: 260, damping: 20, delay: 0.15 }}
                    className="relative mb-6"
                  >
                    <div className="w-16 h-16 rounded-[20px] bg-gradient-to-b from-emerald-50 to-emerald-100/80 border border-emerald-200/60 flex items-center justify-center shadow-[0_8px_40px_rgba(16,185,129,0.12)]">
                      <Check className="w-8 h-8 text-emerald-600" strokeWidth={2.5} />
                    </div>
                    {/* Pulse ring */}
                    <motion.div
                      initial={{ scale: 0.8, opacity: 0.5 }}
                      animate={{ scale: 2.5, opacity: 0 }}
                      transition={{ delay: 0.3, duration: 1.2, ease: "easeOut" }}
                      className="absolute inset-0 rounded-[20px] border-2 border-emerald-400/30"
                    />
                  </motion.div>

                  {/* Title */}
                  <motion.h1
                    initial={{ opacity: 0, y: 12 }}
                    animate={{ opacity: 1, y: 0 }}
                    transition={{ delay: 0.35, duration: 0.6, ease }}
                    className="text-2xl sm:text-3xl font-semibold text-[#0a0a0a] tracking-tight mb-2"
                  >
                    Your report is ready
                  </motion.h1>

                  <motion.p
                    initial={{ opacity: 0, y: 8 }}
                    animate={{ opacity: 1, y: 0 }}
                    transition={{ delay: 0.45, duration: 0.5, ease }}
                    className="text-gray-400 text-sm mb-8"
                  >
                    {companyName || ticker} — {fmtTime(elapsed)} — {status?.source_count || 0} sources
                  </motion.p>

                  {/* ── Primary CTA ── */}
                  <motion.div
                    initial={{ opacity: 0, y: 10 }}
                    animate={{ opacity: 1, y: 0 }}
                    transition={{ delay: 0.6, duration: 0.5, ease }}
                    className="flex flex-col items-center gap-4 mb-10"
                  >
                    {viewHtml && (
                      <motion.button
                        whileHover={{ scale: 1.02, y: -1 }}
                        whileTap={{ scale: 0.98 }}
                        onClick={handleView}
                        className="group inline-flex items-center gap-3 px-8 py-3.5 rounded-2xl bg-[#0a0a0a] text-white font-medium text-[15px] shadow-[0_4px_24px_rgba(0,0,0,0.12)] hover:shadow-[0_8px_32px_rgba(0,0,0,0.18)] transition-shadow duration-300"
                      >
                        <ExternalLink className="w-[18px] h-[18px] opacity-60 group-hover:opacity-100 transition-opacity" />
                        View Report
                      </motion.button>
                    )}

                    {/* Secondary actions — minimal icon row */}
                    <motion.div
                      initial={{ opacity: 0 }}
                      animate={{ opacity: 1 }}
                      transition={{ delay: 0.8, duration: 0.4 }}
                      className="flex items-center gap-1"
                    >
                      {(downloadPdf || downloadHtml) && (
                        <button onClick={handleDownload} className="flex items-center gap-1.5 px-3.5 py-2 rounded-xl text-gray-400 hover:text-[#0a0a0a] hover:bg-black/[0.04] transition-all duration-200 text-[13px]">
                          <Download className="w-3.5 h-3.5" />
                          <span>Download</span>
                        </button>
                      )}
                      <button onClick={handleShare} className="flex items-center gap-1.5 px-3.5 py-2 rounded-xl text-gray-400 hover:text-[#0a0a0a] hover:bg-black/[0.04] transition-all duration-200 text-[13px]">
                        <Share2 className="w-3.5 h-3.5" />
                        <span>Share</span>
                      </button>
                      <button onClick={() => setShowSources(true)} className="flex items-center gap-1.5 px-3.5 py-2 rounded-xl text-gray-400 hover:text-[#0a0a0a] hover:bg-black/[0.04] transition-all duration-200 text-[13px]">
                        <BookOpen className="w-3.5 h-3.5" />
                        <span>Sources</span>
                      </button>
                      <button onClick={handleAskAI} className="flex items-center gap-1.5 px-3.5 py-2 rounded-xl text-gray-400 hover:text-[#0a0a0a] hover:bg-black/[0.04] transition-all duration-200 text-[13px]">
                        <Sparkles className="w-3.5 h-3.5" />
                        <span>AI Tools</span>
                      </button>
                    </motion.div>
                  </motion.div>

                  {/* ── Report preview card ── */}
                  {viewHtml && (
                    <motion.div
                      initial={{ opacity: 0, y: 50, scale: 0.97 }}
                      animate={{ opacity: 1, y: 0, scale: 1 }}
                      transition={{ delay: 0.9, duration: 1, ease }}
                      className="w-full max-w-4xl mx-auto px-6 relative"
                    >
                      {/* Light sweep */}
                      <motion.div
                        initial={{ x: "-100%" }}
                        animate={{ x: "300%" }}
                        transition={{ delay: 1.4, duration: 1.5, ease: "easeInOut" }}
                        className="absolute inset-0 z-10 pointer-events-none bg-gradient-to-r from-transparent via-white/40 to-transparent"
                        style={{ borderRadius: "1.25rem" }}
                      />

                      {/* Report frame — click to open viewer */}
                      <button onClick={handleView} className="block w-full text-left group cursor-pointer">
                        <div className="rounded-2xl overflow-hidden bg-white shadow-[0_2px_20px_rgba(0,0,0,0.06),0_12px_48px_rgba(0,0,0,0.06)] border border-black/[0.06] group-hover:shadow-[0_4px_24px_rgba(0,0,0,0.08),0_16px_56px_rgba(0,0,0,0.08)] transition-shadow duration-500 relative">
                          {/* Hover overlay */}
                          <div className="absolute inset-0 z-20 bg-black/0 group-hover:bg-black/[0.02] transition-colors duration-300 flex items-center justify-center rounded-2xl">
                            <motion.div
                              initial={{ opacity: 0, scale: 0.9 }}
                              whileHover={{ opacity: 1, scale: 1 }}
                              className="opacity-0 group-hover:opacity-100 transition-opacity duration-300 bg-white/95 backdrop-blur-sm rounded-xl px-5 py-2.5 shadow-lg border border-black/[0.06] flex items-center gap-2 text-sm font-medium text-[#0a0a0a]"
                            >
                              <ExternalLink className="w-4 h-4" />
                              Open Full Screen
                            </motion.div>
                          </div>
                          <iframe
                            src={viewHtml}
                            title={`${companyName || ticker} Research Report`}
                            className="w-full bg-white pointer-events-none"
                            style={{ height: "clamp(40vh, 60vh, 70vh)", border: "none" }}
                            tabIndex={-1}
                          />
                        </div>
                      </button>
                    </motion.div>
                  )}

                  {/* Bottom actions */}
                  <motion.div
                    initial={{ opacity: 0 }}
                    animate={{ opacity: 1 }}
                    transition={{ delay: 1.3, duration: 0.5 }}
                    className="flex items-center gap-3 py-10"
                  >
                    <button
                      onClick={() => startNewJob()}
                      disabled={isStarting}
                      className="flex items-center gap-1.5 px-3.5 py-2 rounded-xl text-gray-300 hover:text-gray-500 hover:bg-black/[0.03] transition-all text-[13px] disabled:opacity-40"
                    >
                      <RotateCcw className="w-3.5 h-3.5" />
                      New Report
                    </button>
                    <Link
                      to="/"
                      state={{ openContent: true }}
                      className="flex items-center gap-1.5 px-3.5 py-2 rounded-xl text-gray-300 hover:text-gray-500 hover:bg-black/[0.03] transition-all text-[13px]"
                    >
                      <ArrowLeft className="w-3.5 h-3.5" />
                      Home
                    </Link>
                  </motion.div>
                </motion.div>
              )}

              {/* ━━ ERROR STATE ━━━━━━━━━━━━━━━━━━━━━━━━━━━━ */}
              {!isComplete && isError && (
                <motion.div
                  key="error"
                  initial={{ opacity: 0, y: 20 }}
                  animate={{ opacity: 1, y: 0 }}
                  exit={{ opacity: 0, scale: 0.95, filter: "blur(8px)" }}
                  transition={{ duration: 0.6 }}
                  className="flex flex-col items-center justify-center min-h-full py-24 px-6"
                >
                  <div className="w-16 h-16 rounded-[20px] bg-gradient-to-b from-red-50 to-red-100/80 border border-red-200/60 flex items-center justify-center mb-6 shadow-[0_8px_40px_rgba(239,68,68,0.08)]">
                    <span className="text-2xl font-light text-red-500">!</span>
                  </div>
                  <h2 className="text-xl font-semibold text-[#0a0a0a] mb-2 tracking-tight">Generation Failed</h2>
                  <p className="text-gray-500 text-sm mb-1 text-center max-w-md">{status?.error || "An unexpected error occurred."}</p>
                  {error && <p className="text-red-400 text-xs mb-1">{error}</p>}
                  <p className="text-gray-300 text-xs mb-8">Check that the ticker is valid, or try a different company.</p>
                  <div className="flex gap-3">
                    <motion.button
                      whileHover={{ scale: 1.02 }}
                      whileTap={{ scale: 0.98 }}
                      onClick={() => startNewJob()}
                      disabled={isStarting}
                      className="inline-flex items-center gap-2 px-6 py-3 rounded-2xl bg-[#0a0a0a] hover:bg-gray-800 text-white font-medium text-sm disabled:opacity-50 transition-colors"
                    >
                      <RotateCcw className="w-4 h-4" />Retry
                    </motion.button>
                    <Link
                      to="/"
                      state={{ openContent: true }}
                      className="inline-flex items-center gap-2 px-5 py-3 rounded-2xl border border-black/[0.08] text-gray-500 hover:text-[#0a0a0a] hover:border-black/[0.12] transition-colors text-sm"
                    >
                      Try different company
                    </Link>
                  </div>
                </motion.div>
              )}

            </AnimatePresence>
          </div>

          {/* ── Bottom status bar (while running) ── */}
          {isRunning && (
            <motion.div
              initial={{ opacity: 0, y: 10 }}
              animate={{ opacity: 1, y: 0 }}
              className="shrink-0 border-t border-black/[0.06] bg-white/95 backdrop-blur-sm px-6 py-3 flex items-center justify-between z-20"
            >
              <div className="flex items-center gap-3 text-xs text-gray-400">
                <Loader2 className="w-3.5 h-3.5 text-[#de5f40] animate-spin" />
                <span className="text-gray-500">{status?.message || stageMsg}</span>
              </div>
              <div className="flex items-center gap-4 text-xs font-mono">
                <span className="text-gray-400">{fmtTime(elapsed)}</span>
                <span className="text-[#de5f40]">{Math.round(pct)}%</span>
              </div>
            </motion.div>
          )}
        </main>
      </div>

      <SourcesModal
        isOpen={showSources}
        onClose={() => setShowSources(false)}
        sources={status?.sources || []}
        companyName={companyName || ticker}
      />
    </div>
  );
}
