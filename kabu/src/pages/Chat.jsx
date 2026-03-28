import React, { useState, useRef, useEffect, useCallback } from "react";
import { motion, AnimatePresence } from "framer-motion";
import {
  ArrowLeft, Send, Loader2, Bot, User, Wrench,
  Search, TrendingUp, FileText, Users, Globe, ChevronDown, ChevronRight,
  Sparkles, MessageSquare, Square, Activity, BarChart3, Layers, Shield, AlertTriangle, Target,
} from "lucide-react";
import { Link } from "react-router-dom";
import { streamChat } from "@/api/backend";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import LivePriceTicker from "@/components/chat/LivePriceTicker";

const REMARK_PLUGINS = [remarkGfm];

/* ── Tool metadata for display ───────────────────────────── */
const TOOL_META = {
  lookup_company:       { icon: Search,     label: "Looking up company",     color: "text-blue-400" },
  get_stock_prices:     { icon: TrendingUp, label: "Fetching stock prices",  color: "text-green-400" },
  get_financials:       { icon: FileText,   label: "Loading financials",     color: "text-amber-400" },
  search_edinet_filings:{ icon: FileText,   label: "Searching EDINET filings", color: "text-purple-400" },
  web_search:           { icon: Globe,      label: "Searching the web",      color: "text-cyan-400" },
  get_directors:        { icon: Users,      label: "Loading director data",  color: "text-pink-400" },
  get_voting_results:   { icon: FileText,   label: "AGM voting results",    color: "text-orange-400" },
  get_large_shareholders:{ icon: Users,     label: "Large shareholders",    color: "text-red-400" },
  analyze_technicals:    { icon: Activity,  label: "Technical analysis",    color: "text-emerald-400" },
  score_company:         { icon: Target,    label: "Company scoring",       color: "text-yellow-400" },
  get_company_peers:     { icon: Layers,    label: "Peer comparison",       color: "text-indigo-400" },
  get_market_context:    { icon: BarChart3, label: "Market context",        color: "text-teal-400" },
  screen_sector:         { icon: Layers,    label: "Sector screening",      color: "text-violet-400" },
  analyze_risk:          { icon: Shield,    label: "Risk analysis",         color: "text-rose-400" },
  detect_red_flags:      { icon: AlertTriangle, label: "Red flag detection", color: "text-red-400" },
  get_shareholder_structure: { icon: Users, label: "Shareholder structure", color: "text-sky-400" },
};

const SUGGESTED = [
  "What is Toyota's current stock price and financial performance?",
  "Compare Sony and Nintendo's latest revenue and margins",
  "Who sits on SoftBank Corp.'s board of directors?",
  "Search for latest news on Keyence",
  "What EDINET filings has Recruit submitted recently?",
];

/* ── Describe tool action from input ─────────────────────── */
function describeToolAction(tool, input) {
  const code = input?.stock_code || "";
  const q = input?.query || "";
  switch (tool) {
    case "lookup_company":      return `Resolving company ${code}`;
    case "get_stock_prices":    return `Live price + ${input?.days || 30}-day history for ${code}`;
    case "get_financials":      return `Quarterly earnings & margins for ${code}`;
    case "search_edinet_filings": return `Scanning EDINET filings for ${code} (${input?.days_back || 90}d)`;
    case "web_search":          return `Searching "${q.length > 40 ? q.slice(0, 37) + "..." : q}"`;
    case "get_directors":       return `Board composition for ${input?.company_name || code}`;
    case "get_voting_results":  return `AGM voting results for ${code} via EDINET`;
    case "get_large_shareholders": return `Scanning 大量保有報告書 for ${code}`;
    case "analyze_technicals":  return `Technical analysis for ${code}`;
    case "score_company":       return `Scoring ${code}`;
    case "get_company_peers":   return `Finding peers for ${code}`;
    case "get_market_context":  return "Loading market context";
    case "screen_sector":       return `Screening sector ${input?.sector || code}`;
    case "analyze_risk":        return `Risk analysis for ${code}`;
    case "detect_red_flags":    return `Red flag scan for ${code}`;
    case "get_shareholder_structure": return `Shareholder structure for ${code}`;
    default:                    return tool;
  }
}

/* ── Format tool detail for display ──────────────────────── */
function formatToolDetail(tool, input) {
  const code = input?.stock_code || "";
  switch (tool) {
    case "lookup_company":
      return { params: [["Stock code", code]], endpoint: "J-Quants Listed Info API" };
    case "get_stock_prices":
      return { params: [["Stock code", code], ["Period", `${input?.days || 30} days`]], endpoint: "J-Quants Daily Quotes + Yahoo Finance" };
    case "get_financials":
      return { params: [["Stock code", code]], endpoint: "J-Quants Financial Statements API" };
    case "search_edinet_filings":
      return { params: [["Stock code", code], ["Search window", `${input?.days_back || 90} days`]], endpoint: "EDINET API v2 /documents.json" };
    case "web_search":
      return { params: [["Query", input?.query || ""]], endpoint: "SERP API" };
    case "get_directors":
      return { params: [["Stock code", code], ["Company", input?.company_name || ""]], endpoint: "EDINET + GPT Pipeline" };
    case "get_voting_results":
      return { params: [["Stock code", code], ["Search window", `${input?.days_back || 400} days`]], endpoint: "EDINET API v2 (臨時報告書)" };
    case "get_large_shareholders":
      return { params: [["Stock code", code], ["Search window", `${input?.days_back || 730} days`]], endpoint: "EDINET API v2 (大量保有報告書)" };
    case "analyze_technicals":
      return { params: [["Stock code", code]], endpoint: "J-Quants + Technical Indicators" };
    case "score_company":
      return { params: [["Stock code", code]], endpoint: "Multi-factor Scoring Engine" };
    case "get_company_peers":
      return { params: [["Stock code", code]], endpoint: "J-Quants Sector Analysis" };
    case "get_market_context":
      return { params: [], endpoint: "Market Overview" };
    case "screen_sector":
      return { params: [["Stock code", code], ["Sector", input?.sector || ""]], endpoint: "Sector Screener" };
    case "analyze_risk":
      return { params: [["Stock code", code]], endpoint: "Risk Analytics" };
    case "detect_red_flags":
      return { params: [["Stock code", code]], endpoint: "Earnings Quality Scanner" };
    case "get_shareholder_structure":
      return { params: [["Stock code", code]], endpoint: "EDINET 有価証券報告書" };
    default:
      return { params: Object.entries(input || {}), endpoint: tool };
  }
}

/* ── Tool Call Card (expandable) ─────────────────────────── */
function ToolCallCard({ tool, input, result, isLoading, sources }) {
  const [open, setOpen] = useState(false);
  const meta = TOOL_META[tool] || { icon: Wrench, label: tool, color: "text-gray-400" };
  const Icon = meta.icon;
  const action = describeToolAction(tool, input);
  const detail = formatToolDetail(tool, input);
  const canExpand = !isLoading;

  return (
    <motion.div layout className="my-1.5 rounded-lg bg-white/[0.03] border border-white/[0.08] overflow-hidden">
      <button
        onClick={() => canExpand && setOpen(!open)}
        className={`w-full flex items-center gap-2 px-3 py-2 text-left transition-colors ${canExpand ? "hover:bg-white/[0.03] cursor-pointer" : "cursor-default"}`}
      >
        {isLoading ? (
          <Loader2 className={`w-3.5 h-3.5 ${meta.color} animate-spin`} />
        ) : (
          <Icon className={`w-3.5 h-3.5 ${meta.color}`} />
        )}
        <div className="flex-1 min-w-0">
          <span className="text-xs text-gray-400 block truncate">
            {isLoading ? action : (typeof result === "string" ? result : result ? JSON.stringify(result) : action)}
          </span>
          {isLoading && (
            <span className="text-[10px] text-gray-600 block mt-0.5">{meta.label}</span>
          )}
        </div>
        {canExpand && (
          <motion.div animate={{ rotate: open ? 180 : 0 }} transition={{ duration: 0.2 }}>
            <ChevronDown className="w-3 h-3 text-gray-600" />
          </motion.div>
        )}
      </button>
      <AnimatePresence initial={false}>
        {open && (
          <motion.div
            initial={{ height: 0, opacity: 0 }}
            animate={{ height: "auto", opacity: 1 }}
            exit={{ height: 0, opacity: 0 }}
            transition={{ duration: 0.25, ease: [0.16, 1, 0.3, 1] }}
            className="overflow-hidden"
          >
            <div className="px-3 pb-2.5 pt-0.5 border-t border-white/[0.04]">
              <div className="flex items-center gap-1.5 mb-1.5">
                <div className="w-1 h-1 rounded-full bg-emerald-500/60" />
                <span className="text-[10px] text-white/20 font-mono">{detail.endpoint}</span>
              </div>
              <div className="space-y-0.5">
                {detail.params.map(([k, v], i) => (
                  <div key={i} className="flex items-center gap-2 text-[10px]">
                    <span className="text-white/15 min-w-[60px]">{k}</span>
                    <span className="text-white/35 font-mono">{v}</span>
                  </div>
                ))}
              </div>
              {sources && sources.length > 0 && (
                <div className="flex items-center gap-1.5 mt-2 pt-1.5 border-t border-white/[0.03]">
                  <span className="text-[9px] text-white/12 uppercase tracking-wider">Data from</span>
                  {sources.map(s => (
                    <span key={s} className="text-[9px] px-1.5 py-0.5 rounded-md bg-white/[0.04] text-white/25 font-mono">{s}</span>
                  ))}
                </div>
              )}
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </motion.div>
  );
}

/* ── Parse follow-up suggestions from response ──────────── */
function parseFollowUps(text) {
  const pattern = /\n*\*{0,2}-{2,}\s*follow[\s-]*ups?\s*-{2,}\*{0,2}\s*\n/i;
  const match = text.match(pattern);
  if (!match) return { body: text, suggestions: [] };
  const idx = match.index;
  const body = text.slice(0, idx).trimEnd();
  const raw = text.slice(idx + match[0].length).trim();
  const suggestions = raw
    .split("\n")
    .map(l => l.replace(/^[-*•\d.)\]]+\s*/, "").trim())
    .filter(l => l.length > 5)
    .slice(0, 3);
  return { body, suggestions };
}

function getSourceBadges(tools) {
  if (!tools || tools.length === 0) return [];
  const seen = new Set();
  return tools
    .flatMap(t => t.sources || [])
    .filter(Boolean)
    .filter(s => { if (seen.has(s)) return false; seen.add(s); return true; });
}

function mergeSourceDetails(tools) {
  if (!tools || tools.length === 0) return {};
  const merged = {};
  for (const t of tools) {
    if (t.source_details) {
      for (const [k, v] of Object.entries(t.source_details)) {
        if (!merged[k]) merged[k] = v;
        else if (v.items) {
          if (!merged[k].items) merged[k].items = [];
          const ids = new Set(merged[k].items.map(i => i.doc_id || i.url));
          for (const item of v.items) {
            if (!ids.has(item.doc_id || item.url)) merged[k].items.push(item);
          }
        }
      }
    }
  }
  return merged;
}

function SourceBadge({ name, detail }) {
  const [open, setOpen] = useState(false);
  const ref = useRef(null);
  useEffect(() => {
    if (!open) return;
    const handler = (e) => { if (ref.current && !ref.current.contains(e.target)) setOpen(false); };
    document.addEventListener("mousedown", handler);
    return () => document.removeEventListener("mousedown", handler);
  }, [open]);
  const hasDetail = detail && (detail.items?.length > 0 || detail.url || detail.desc);
  return (
    <div className="relative" ref={ref}>
      <button
        onClick={() => hasDetail && setOpen(!open)}
        className={`text-[10px] px-2 py-0.5 rounded-full border transition-all duration-200 ${
          open ? "border-white/20 bg-white/[0.06] text-white/50"
            : hasDetail ? "border-white/[0.08] bg-white/[0.03] text-white/30 hover:border-white/15 hover:text-white/45 cursor-pointer"
              : "border-white/[0.08] bg-white/[0.03] text-white/30"
        }`}
      >{name}</button>
      <AnimatePresence>
        {open && hasDetail && (
          <motion.div
            initial={{ opacity: 0, y: 4, scale: 0.95 }}
            animate={{ opacity: 1, y: 0, scale: 1 }}
            exit={{ opacity: 0, y: 4, scale: 0.95 }}
            transition={{ duration: 0.15, ease: [0.16, 1, 0.3, 1] }}
            className="absolute bottom-full left-0 mb-2 w-[300px] max-h-[260px] overflow-y-auto rounded-xl border border-white/[0.08] bg-[#0d1120]/95 backdrop-blur-xl shadow-2xl shadow-black/40 z-50"
          >
            <div className="px-3 pt-2.5 pb-2 border-b border-white/[0.05] flex items-center gap-2">
              <div className="w-1.5 h-1.5 rounded-full bg-emerald-500/70" />
              <span className="text-[11px] font-medium text-white/50">{name}</span>
            </div>
            {detail.desc && <div className="px-3 py-1.5 text-[10px] text-white/20 font-mono">{detail.desc}</div>}
            {detail.type === "filings" && detail.items?.length > 0 && (
              <div className="px-2 pb-2">
                {detail.items.map((item, i) => (
                  <a key={i} href={item.url || "#"} target="_blank" rel="noopener noreferrer" className="flex items-start gap-2 px-2 py-1.5 rounded-lg hover:bg-white/[0.04] transition-colors group">
                    <FileText className="w-3 h-3 text-violet-400/50 mt-0.5 shrink-0" />
                    <div className="min-w-0 flex-1">
                      <p className="text-[10px] text-white/40 group-hover:text-white/60 truncate">{item.description || item.filer}</p>
                      <div className="flex items-center gap-2 mt-0.5">
                        <span className="text-[9px] text-white/15 font-mono">{item.doc_id}</span>
                        {item.date && <span className="text-[9px] text-white/15">{item.date.split(" ")[0]}</span>}
                      </div>
                    </div>
                    <ChevronRight className="w-2.5 h-2.5 text-white/10 group-hover:text-white/30 mt-0.5 shrink-0" />
                  </a>
                ))}
              </div>
            )}
            {detail.type === "links" && detail.items?.length > 0 && (
              <div className="px-2 pb-2">
                {detail.items.map((item, i) => (
                  <a key={i} href={item.url || "#"} target="_blank" rel="noopener noreferrer" className="flex items-start gap-2 px-2 py-1.5 rounded-lg hover:bg-white/[0.04] transition-colors group">
                    <Globe className="w-3 h-3 text-cyan-400/50 mt-0.5 shrink-0" />
                    <div className="min-w-0 flex-1">
                      <p className="text-[10px] text-white/40 group-hover:text-white/60 truncate">{item.title || item.url}</p>
                      <span className="text-[9px] text-white/15 font-mono truncate block">{(item.url || "").replace(/^https?:\/\//, "").split("/")[0]}</span>
                    </div>
                    <ChevronRight className="w-2.5 h-2.5 text-white/10 group-hover:text-white/30 mt-0.5 shrink-0" />
                  </a>
                ))}
              </div>
            )}
            {detail.type === "link" && detail.url && (
              <div className="px-2 pb-2">
                <a href={detail.url} target="_blank" rel="noopener noreferrer" className="flex items-center gap-2 px-2 py-1.5 rounded-lg hover:bg-white/[0.04] transition-colors group">
                  <Globe className="w-3 h-3 text-emerald-400/50 shrink-0" />
                  <span className="text-[10px] text-white/30 group-hover:text-white/50 font-mono truncate">{detail.url.replace(/^https?:\/\//, "").split("?")[0]}</span>
                  <ChevronRight className="w-2.5 h-2.5 text-white/10 group-hover:text-white/30 shrink-0" />
                </a>
              </div>
            )}
            {detail.type === "api" && !detail.url && !detail.items && (
              <div className="px-3 pb-2.5 text-[10px] text-white/20">Data retrieved via authenticated API call</div>
            )}
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}

/* ── Markdown renderer with dark-theme tables ────────────── */
const mdComponents = {
  table: ({ children }) => (
    <div className="my-3 overflow-x-auto rounded-lg border border-white/[0.08]">
      <table className="w-full text-xs">{children}</table>
    </div>
  ),
  thead: ({ children }) => <thead className="bg-white/[0.04]">{children}</thead>,
  th: ({ children }) => <th className="px-3 py-2 text-left text-gray-400 font-medium border-b border-white/[0.08]">{children}</th>,
  td: ({ children }) => <td className="px-3 py-2 text-gray-300 border-b border-white/[0.04]">{children}</td>,
  code: ({ className, children, node }) => {
    const isBlock = node?.parent?.type === "element" && node?.parent?.tagName === "pre";
    if (!isBlock) {
      return <code className="px-1.5 py-0.5 rounded bg-white/[0.06] text-blue-300 text-[11px]">{children}</code>;
    }
    return <code className="block text-[11px] text-gray-300">{children}</code>;
  },
  pre: ({ children }) => (
    <pre className="my-2 p-3 rounded-lg bg-white/[0.04] border border-white/[0.08] overflow-x-auto">{children}</pre>
  ),
  p: ({ children }) => <p className="mb-2 leading-relaxed">{children}</p>,
  h1: ({ children }) => <h1 className="text-lg font-bold text-white mt-4 mb-2">{children}</h1>,
  h2: ({ children }) => <h2 className="text-base font-semibold text-white mt-3 mb-1.5">{children}</h2>,
  h3: ({ children }) => <h3 className="text-sm font-semibold text-gray-200 mt-2 mb-1">{children}</h3>,
  ul: ({ children }) => <ul className="list-disc list-inside mb-2 space-y-0.5">{children}</ul>,
  ol: ({ children }) => <ol className="list-decimal list-inside mb-2 space-y-0.5">{children}</ol>,
  li: ({ children }) => <li className="text-gray-300">{children}</li>,
  strong: ({ children }) => <strong className="text-white font-semibold">{children}</strong>,
  a: ({ href, children }) => <a href={href} target="_blank" rel="noopener noreferrer" className="text-blue-400 hover:underline">{children}</a>,
};

/* ── Main Chat Page ──────────────────────────────────────── */
let _chatMsgId = 0;
const nextChatId = () => ++_chatMsgId;

export default function Chat() {
  const [messages, setMessages] = useState([]); // {id, role, content, toolCalls?}
  const [input, setInput] = useState("");
  const [isStreaming, setIsStreaming] = useState(false);
  const [streamingText, setStreamingText] = useState("");
  const [activeTools, setActiveTools] = useState([]);
  const scrollRef = useRef(null);
  const inputRef = useRef(null);
  const abortRef = useRef(null);
  const streamingRef = useRef(false);

  // Abort stream on unmount (e.g. navigating away)
  useEffect(() => {
    return () => { if (abortRef.current) abortRef.current.abort(); };
  }, []);

  // Smart auto-scroll: only scroll if user is near the bottom
  const userScrolledUpRef = useRef(false);

  useEffect(() => {
    const el = scrollRef.current;
    if (!el) return;
    const handleScroll = () => {
      const distFromBottom = el.scrollHeight - el.scrollTop - el.clientHeight;
      userScrolledUpRef.current = distFromBottom > 120;
    };
    el.addEventListener("scroll", handleScroll, { passive: true });
    return () => el.removeEventListener("scroll", handleScroll);
  }, []);

  useEffect(() => {
    if (scrollRef.current && !userScrolledUpRef.current) {
      scrollRef.current.scrollTo({
        top: scrollRef.current.scrollHeight,
        behavior: isStreaming ? "auto" : "smooth",
      });
    }
  }, [messages, streamingText, activeTools, isStreaming]);

  const sendMessage = useCallback(async (text) => {
    if (!text.trim() || streamingRef.current) return;

    const userMsg = { id: nextChatId(), role: "user", content: text.trim() };
    setMessages(prev => [...prev, userMsg]);
    setInput("");
    streamingRef.current = true;
    setIsStreaming(true);
    setStreamingText("");
    setActiveTools([]);

    // Abort any previous in-flight request
    if (abortRef.current) abortRef.current.abort();
    const controller = new AbortController();
    abortRef.current = controller;

    // Build conversation history for API
    const history = [...messages, userMsg].map(m => ({
      role: m.role,
      content: m.content,
    }));

    let fullText = "";
    const toolCalls = [];

    await streamChat(history, {
      signal: controller.signal,
      onText: (chunk) => {
        fullText += chunk;
        setStreamingText(fullText);
      },
      onToolCall: ({ id, tool, input: toolInput }) => {
        const tc = { id, tool, input: toolInput, result: null, isLoading: true };
        toolCalls.push(tc);
        setActiveTools([...toolCalls]);
      },
      onToolResult: (data) => {
        const { tool, summary, sources, source_details } = data;
        const tc = toolCalls.find(t => (data.id ? t.id === data.id : t.tool === tool) && t.isLoading);
        if (tc) {
          tc.result = summary;
          tc.isLoading = false;
          tc.sources = sources || [];
          tc.source_details = source_details || {};
          if (tool === "get_stock_prices" && data.stock_code) {
            tc.stock_code = data.stock_code;
            tc.live_price = data.live_price;
            tc.live_change_pct = data.live_change_pct;
            tc.market_state = data.market_state;
            tc.previous_close = data.previous_close;
            tc.price_history = data.price_history;
          }
          setActiveTools([...toolCalls]);
        }
      },
      onError: (msg) => {
        if (controller.signal.aborted) return;
        fullText += `\n\n*Error: ${msg}*`;
        setStreamingText(fullText);
      },
      onDone: () => {
        // Finalize
      },
    });

    // Guard: handleStop already cleaned up, or component unmounted (abort fired)
    if (!streamingRef.current || controller.signal.aborted) return;
    setMessages(prev => [...prev, {
      id: nextChatId(),
      role: "assistant",
      content: fullText,
      toolCalls: toolCalls.length > 0 ? [...toolCalls] : undefined,
    }]);
    streamingRef.current = false;
    setStreamingText("");
    setActiveTools([]);
    setIsStreaming(false);
    inputRef.current?.focus();
  }, [messages]);

  const handleStop = useCallback(() => {
    if (!streamingRef.current) return;
    if (abortRef.current) abortRef.current.abort();
    if (streamingText || activeTools.length > 0) {
      setMessages(prev => [...prev, {
        id: nextChatId(),
        role: "assistant",
        content: streamingText || "(Stopped)",
        toolCalls: activeTools.length > 0 ? [...activeTools] : undefined,
      }]);
    }
    streamingRef.current = false;
    setStreamingText("");
    setActiveTools([]);
    setIsStreaming(false);
    inputRef.current?.focus();
  }, [streamingText, activeTools]);

  const handleSubmit = (e) => {
    e.preventDefault();
    sendMessage(input);
  };

  const handleKeyDown = (e) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      sendMessage(input);
    }
  };

  return (
    <div className="h-dvh flex flex-col bg-[#090d1a] text-white">
      {/* Header */}
      <div className="shrink-0 border-b border-white/[0.06] bg-[#080C16] px-6 py-3 flex items-center gap-4">
        <Link to="/" state={{ openContent: true }} className="text-gray-500 hover:text-gray-300 transition-colors">
          <ArrowLeft className="w-4 h-4" />
        </Link>
        <div className="flex items-center gap-2">
          <div className="w-7 h-7 rounded-lg bg-gradient-to-br from-purple-500/20 to-blue-500/20 border border-purple-500/20 flex items-center justify-center">
            <Sparkles className="w-4 h-4 text-purple-400" />
          </div>
          <h1 className="text-sm font-semibold">Research Assistant</h1>
          <span className="text-[10px] px-1.5 py-0.5 rounded-full bg-purple-500/10 border border-purple-500/20 text-purple-400">Bot</span>
        </div>
      </div>

      {/* Messages area */}
      <div ref={scrollRef} className="flex-1 overflow-y-auto px-4 py-6">
        <div className="max-w-3xl mx-auto space-y-4">
          {/* Empty state */}
          {messages.length === 0 && !isStreaming && (
            <motion.div
              initial={{ opacity: 0, y: 20 }}
              animate={{ opacity: 1, y: 0 }}
              className="text-center py-20"
            >
              <div className="w-16 h-16 mx-auto mb-6 rounded-2xl bg-gradient-to-br from-purple-500/20 to-blue-500/20 border border-purple-500/20 flex items-center justify-center">
                <Sparkles className="w-8 h-8 text-purple-400" />
              </div>
              <h2 className="text-xl font-semibold mb-2">Research Assistant</h2>
              <p className="text-sm text-gray-500 mb-8 max-w-md mx-auto">
                Ask anything about Japanese equities. I can look up stock prices, financial statements,
                EDINET filings, board directors, and search for the latest news.
              </p>
              <div className="flex flex-wrap justify-center gap-2 max-w-xl mx-auto">
                {SUGGESTED.map((s, i) => (
                  <button
                    key={i}
                    onClick={() => sendMessage(s)}
                    className="text-xs px-3 py-2 rounded-lg bg-white/[0.04] border border-white/[0.08] text-gray-400 hover:bg-white/[0.08] hover:text-gray-200 transition-colors text-left"
                  >
                    {s}
                  </button>
                ))}
              </div>
            </motion.div>
          )}

          {/* Message history */}
          {messages.map((msg) => (
            <motion.div
              key={msg.id}
              initial={{ opacity: 0, y: 8 }}
              animate={{ opacity: 1, y: 0 }}
              className={`flex gap-3 ${msg.role === "user" ? "justify-end" : "justify-start"}`}
            >
              {msg.role === "assistant" && (
                <div className="shrink-0 w-7 h-7 rounded-lg bg-gradient-to-br from-purple-500/20 to-blue-500/20 border border-purple-500/20 flex items-center justify-center mt-0.5">
                  <Bot className="w-4 h-4 text-purple-400" />
                </div>
              )}
              <div className={`max-w-[85%] ${
                msg.role === "user"
                  ? "bg-blue-600/20 border border-blue-500/20 rounded-2xl rounded-br-md px-4 py-3"
                  : "bg-white/[0.02] rounded-2xl rounded-bl-md px-4 py-3"
              }`}>
                {/* Tool calls for assistant messages */}
                {msg.toolCalls && (
                  <div className="mb-2">
                    {msg.toolCalls.map((tc, i) => (
                      <ToolCallCard key={i} tool={tc.tool} input={tc.input} result={tc.result} isLoading={false} sources={tc.sources} />
                    ))}
                  </div>
                )}
                {/* Live price ticker */}
                {msg.toolCalls && (() => {
                  const pt = msg.toolCalls.find(tc => tc.tool === "get_stock_prices" && tc.stock_code && tc.live_price);
                  return pt ? (
                    <div className="mb-3">
                      <LivePriceTicker
                        stockCode={pt.stock_code}
                        initialPrice={pt.live_price}
                        initialChangePct={pt.live_change_pct}
                        marketState={pt.market_state}
                        previousClose={pt.previous_close}
                        priceHistory={pt.price_history}
                      />
                    </div>
                  ) : null;
                })()}
                {msg.role === "user" ? (
                  <p className="text-sm text-gray-200 whitespace-pre-wrap break-words">{msg.content}</p>
                ) : (
                  (() => {
                    const { body, suggestions } = parseFollowUps(msg.content);
                    const sources = getSourceBadges(msg.toolCalls);
                    const sourceDetails = mergeSourceDetails(msg.toolCalls);
                    return (
                      <>
                        <div className="text-sm text-gray-300 prose prose-invert prose-sm max-w-none">
                          <ReactMarkdown remarkPlugins={REMARK_PLUGINS} components={mdComponents}>{body}</ReactMarkdown>
                        </div>
                        {sources.length > 0 && (
                          <div className="flex items-center gap-1.5 mt-2 pt-2 border-t border-white/[0.06]">
                            <span className="text-[10px] text-gray-600 uppercase tracking-wider">Sources</span>
                            {sources.map(s => (
                              <SourceBadge key={s} name={s} detail={sourceDetails[s]} />
                            ))}
                          </div>
                        )}
                        {suggestions.length > 0 && !isStreaming && (
                          <div className="grid grid-cols-1 gap-1.5 mt-3">
                            {suggestions.map((s, i) => (
                              <motion.button
                                key={i}
                                onClick={() => sendMessage(s)}
                                className="text-left p-2.5 rounded-xl border border-white/[0.04] bg-white/[0.015] hover:bg-white/[0.035] hover:border-white/[0.08] transition-all duration-300 group"
                                initial={{ opacity: 0, y: 6 }}
                                animate={{ opacity: 1, y: 0 }}
                                transition={{ delay: 0.1 + i * 0.06, duration: 0.35 }}
                                whileHover={{ y: -1 }}
                              >
                                <div className="flex items-center gap-2">
                                  <div className="w-5 h-5 rounded-md bg-purple-500/[0.08] flex items-center justify-center shrink-0">
                                    <MessageSquare className="w-2.5 h-2.5 text-purple-400/60" />
                                  </div>
                                  <p className="text-white/25 group-hover:text-white/50 text-[11px] leading-snug transition-colors duration-200 truncate">
                                    {s}
                                  </p>
                                </div>
                              </motion.button>
                            ))}
                          </div>
                        )}
                      </>
                    );
                  })()
                )}
              </div>
              {msg.role === "user" && (
                <div className="shrink-0 w-7 h-7 rounded-lg bg-blue-500/20 border border-blue-500/20 flex items-center justify-center mt-0.5">
                  <User className="w-4 h-4 text-blue-400" />
                </div>
              )}
            </motion.div>
          ))}

          {/* Streaming response */}
          {isStreaming && (
            <motion.div
              initial={{ opacity: 0, y: 8 }}
              animate={{ opacity: 1, y: 0 }}
              className="flex gap-3 justify-start"
            >
              <div className="shrink-0 w-7 h-7 rounded-lg bg-gradient-to-br from-purple-500/20 to-blue-500/20 border border-purple-500/20 flex items-center justify-center mt-0.5">
                <Bot className="w-4 h-4 text-purple-400" />
              </div>
              <div className="max-w-[85%] bg-white/[0.02] rounded-2xl rounded-bl-md px-4 py-3">
                {/* Active tool calls */}
                {activeTools.map((tc, i) => (
                  <ToolCallCard key={i} tool={tc.tool} input={tc.input} result={tc.result} isLoading={tc.isLoading} sources={tc.sources} />
                ))}
                {/* Live price ticker during streaming */}
                {(() => {
                  const pt = activeTools.find(tc => tc.tool === "get_stock_prices" && tc.stock_code && tc.live_price && !tc.isLoading);
                  return pt ? (
                    <div className="mb-3">
                      <LivePriceTicker
                        stockCode={pt.stock_code}
                        initialPrice={pt.live_price}
                        initialChangePct={pt.live_change_pct}
                        marketState={pt.market_state}
                        previousClose={pt.previous_close}
                        priceHistory={pt.price_history}
                      />
                    </div>
                  ) : null;
                })()}
                {/* Streaming text */}
                {streamingText ? (
                  <div className="text-sm text-gray-300 prose prose-invert prose-sm max-w-none streaming-cursor">
                    <ReactMarkdown remarkPlugins={REMARK_PLUGINS} components={mdComponents}>{parseFollowUps(streamingText).body}</ReactMarkdown>
                  </div>
                ) : activeTools.length === 0 ? (
                  <div className="flex items-center gap-2 text-sm text-gray-500">
                    <Loader2 className="w-4 h-4 animate-spin" />
                    <span>Thinking...</span>
                  </div>
                ) : null}
              </div>
            </motion.div>
          )}
        </div>
      </div>

      {/* Input bar */}
      <div className="shrink-0 border-t border-white/[0.06] bg-[#080C16] px-4 py-3">
        <form onSubmit={handleSubmit} className="max-w-3xl mx-auto flex gap-2">
          <textarea
            ref={inputRef}
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={handleKeyDown}
            placeholder="Ask about any Japanese company..."
            rows={1}
            disabled={isStreaming}
            className="flex-1 bg-white/[0.04] border border-white/[0.08] rounded-xl px-4 py-3 text-sm text-white placeholder-gray-600 resize-none focus:outline-none focus:border-purple-500/40 transition-colors disabled:opacity-50"
            style={{ maxHeight: "min(120px, 30vh)" }}
            onInput={(e) => {
              e.target.style.height = "auto";
              const limit = Math.min(120, window.innerHeight * 0.3);
              e.target.style.height = Math.min(e.target.scrollHeight, limit) + "px";
            }}
          />
          {isStreaming ? (
            <motion.button
              type="button"
              onClick={handleStop}
              className="shrink-0 w-11 h-11 rounded-xl bg-white/[0.06] border border-white/[0.08] flex items-center justify-center text-white/50 hover:bg-white/[0.1] hover:text-white/70 transition-all"
              initial={{ scale: 0.9 }}
              animate={{ scale: 1 }}
              whileTap={{ scale: 0.93 }}
            >
              <Square className="w-4 h-4 fill-current" />
            </motion.button>
          ) : (
            <button
              type="submit"
              disabled={!input.trim()}
              className="shrink-0 w-11 h-11 rounded-xl bg-gradient-to-r from-purple-600 to-blue-600 flex items-center justify-center text-white disabled:opacity-30 hover:opacity-90 transition-opacity"
            >
              <Send className="w-5 h-5" />
            </button>
          )}
        </form>
      </div>
    </div>
  );
}
