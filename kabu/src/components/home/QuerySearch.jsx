import React, { useState, useRef, useCallback, useEffect } from "react";
import { motion, AnimatePresence } from "framer-motion";
import {
  Sparkles, Loader2, Search, TrendingUp, FileText, Users, Globe, Wrench,
  ChevronDown, Send, X, CheckCircle2,
  Activity, BarChart3, Layers, Shield, AlertTriangle, Target,
} from "lucide-react";
import { streamChat } from "@/api/backend";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

const REMARK_PLUGINS = [remarkGfm];

/* ── Tool metadata ─────────────────────────────────────────── */
const TOOL_META = {
  lookup_company:        { icon: Search,     label: "Looking up company",       color: "text-blue-400",   bg: "bg-blue-500/10",   border: "border-blue-500/20" },
  get_stock_prices:      { icon: TrendingUp, label: "Fetching stock prices",    color: "text-emerald-400", bg: "bg-emerald-500/10", border: "border-emerald-500/20" },
  get_financials:        { icon: FileText,   label: "Loading financials",       color: "text-amber-400",  bg: "bg-amber-500/10",  border: "border-amber-500/20" },
  search_edinet_filings: { icon: FileText,   label: "Searching EDINET filings", color: "text-purple-400", bg: "bg-purple-500/10", border: "border-purple-500/20" },
  web_search:            { icon: Globe,      label: "Searching the web",        color: "text-cyan-400",   bg: "bg-cyan-500/10",   border: "border-cyan-500/20" },
  get_directors:         { icon: Users,      label: "Loading director data",    color: "text-pink-400",   bg: "bg-pink-500/10",   border: "border-pink-500/20" },
  get_voting_results:    { icon: FileText,   label: "AGM voting results",       color: "text-orange-400", bg: "bg-orange-500/10", border: "border-orange-500/20" },
  get_large_shareholders:{ icon: Users,      label: "Large shareholders",       color: "text-red-400",    bg: "bg-red-500/10",    border: "border-red-500/20" },
  analyze_technicals:    { icon: Activity,   label: "Technical analysis",       color: "text-emerald-400", bg: "bg-emerald-500/10", border: "border-emerald-500/20" },
  score_company:         { icon: Target,     label: "Company scoring",          color: "text-yellow-400", bg: "bg-yellow-500/10", border: "border-yellow-500/20" },
  get_company_peers:     { icon: Layers,     label: "Peer comparison",          color: "text-indigo-400", bg: "bg-indigo-500/10", border: "border-indigo-500/20" },
  get_market_context:    { icon: BarChart3,  label: "Market context",           color: "text-teal-400",   bg: "bg-teal-500/10",   border: "border-teal-500/20" },
  screen_sector:         { icon: Layers,     label: "Sector screening",         color: "text-violet-400", bg: "bg-violet-500/10", border: "border-violet-500/20" },
  analyze_risk:          { icon: Shield,     label: "Risk analysis",            color: "text-rose-400",   bg: "bg-rose-500/10",   border: "border-rose-500/20" },
  detect_red_flags:      { icon: AlertTriangle, label: "Red flag detection",    color: "text-red-400",    bg: "bg-red-500/10",    border: "border-red-500/20" },
  get_shareholder_structure: { icon: Users,  label: "Shareholder structure",    color: "text-sky-400",    bg: "bg-sky-500/10",    border: "border-sky-500/20" },
};

const SUGGESTED_QUERIES = [
  { text: "What is Toyota's current stock price?", icon: TrendingUp },
  { text: "Compare Sony and Nintendo revenue", icon: FileText },
  { text: "Who are SoftBank's board directors?", icon: Users },
  { text: "Latest news on Recruit Holdings", icon: Globe },
];

/* ── Tool Call Pill ──────────────────────────────────────── */
function ToolPill({ tool, input, result, isLoading }) {
  const [open, setOpen] = useState(false);
  const meta = TOOL_META[tool] || { icon: Wrench, label: tool, color: "text-gray-400", bg: "bg-white/[0.04]", border: "border-white/[0.08]" };
  const Icon = meta.icon;

  return (
    <motion.div
      initial={{ opacity: 0, scale: 0.95 }}
      animate={{ opacity: 1, scale: 1 }}
      className={`rounded-xl ${meta.bg} border ${meta.border} overflow-hidden`}
    >
      <button
        onClick={() => !isLoading && setOpen(!open)}
        className="w-full flex items-center gap-2.5 px-3.5 py-2 text-left transition-colors hover:bg-white/[0.02]"
      >
        <div className={`w-6 h-6 rounded-lg ${meta.bg} flex items-center justify-center shrink-0`}>
          {isLoading ? (
            <Loader2 className={`w-3.5 h-3.5 ${meta.color} animate-spin`} />
          ) : (
            <CheckCircle2 className={`w-3.5 h-3.5 ${meta.color}`} />
          )}
        </div>
        <span className="text-xs text-gray-300 flex-1 truncate">
          {isLoading ? meta.label + "..." : result || meta.label}
        </span>
        {!isLoading && (
          <motion.div animate={{ rotate: open ? 180 : 0 }} transition={{ duration: 0.2 }}>
            <ChevronDown className="w-3 h-3 text-gray-600" />
          </motion.div>
        )}
      </button>
      <AnimatePresence>
        {open && !isLoading && (
          <motion.div
            initial={{ height: 0, opacity: 0 }}
            animate={{ height: "auto", opacity: 1 }}
            exit={{ height: 0, opacity: 0 }}
            transition={{ duration: 0.2 }}
            className="overflow-hidden"
          >
            <div className="px-3.5 pb-2.5 text-[10px] text-gray-500 font-mono whitespace-pre-wrap break-all border-t border-white/[0.04] pt-2">
              {JSON.stringify(input, null, 2)}
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </motion.div>
  );
}

/* ── Markdown components ─────────────────────────────────── */
const mdComponents = {
  table: ({ children }) => (
    <div className="my-3 overflow-x-auto rounded-xl border border-white/[0.08] bg-white/[0.02]">
      <table className="w-full text-xs">{children}</table>
    </div>
  ),
  thead: ({ children }) => <thead className="bg-white/[0.05]">{children}</thead>,
  th: ({ children }) => <th className="px-3 py-2.5 text-left text-gray-400 font-medium border-b border-white/[0.08] text-xs">{children}</th>,
  td: ({ children }) => <td className="px-3 py-2 text-gray-300 border-b border-white/[0.04] text-xs">{children}</td>,
  code: ({ className, children, node }) => {
    const isBlock = node?.parent?.type === "element" && node?.parent?.tagName === "pre";
    if (!isBlock) {
      return <code className="px-1.5 py-0.5 rounded-md bg-white/[0.06] text-blue-300 text-[11px] font-mono">{children}</code>;
    }
    return <code className="block text-[11px] text-gray-300 font-mono">{children}</code>;
  },
  pre: ({ children }) => (
    <pre className="my-2.5 p-3.5 rounded-xl bg-[#0d1220] border border-white/[0.08] overflow-x-auto">{children}</pre>
  ),
  p: ({ children }) => <p className="mb-2.5 leading-relaxed text-[13px]">{children}</p>,
  h1: ({ children }) => <h1 className="text-lg font-bold text-white mt-5 mb-2">{children}</h1>,
  h2: ({ children }) => <h2 className="text-base font-semibold text-white mt-4 mb-2">{children}</h2>,
  h3: ({ children }) => <h3 className="text-sm font-semibold text-gray-200 mt-3 mb-1.5">{children}</h3>,
  ul: ({ children }) => <ul className="list-disc list-inside mb-2.5 space-y-1 ml-1">{children}</ul>,
  ol: ({ children }) => <ol className="list-decimal list-inside mb-2.5 space-y-1 ml-1">{children}</ol>,
  li: ({ children }) => <li className="text-gray-300 text-[13px]">{children}</li>,
  strong: ({ children }) => <strong className="text-white font-semibold">{children}</strong>,
  a: ({ href, children }) => <a href={href} target="_blank" rel="noopener noreferrer" className="text-blue-400 hover:text-blue-300 underline underline-offset-2 decoration-blue-400/30 hover:decoration-blue-300/50 transition-colors">{children}</a>,
  hr: () => <hr className="border-white/[0.06] my-4" />,
  blockquote: ({ children }) => <blockquote className="border-l-2 border-purple-500/40 pl-3 my-2 text-gray-400 italic">{children}</blockquote>,
};

/* ── Thinking dots animation ──────────────────────────────── */
function ThinkingDots() {
  return (
    <div className="flex items-center gap-3 py-1">
      <div className="flex items-center gap-1">
        {[0, 1, 2].map((i) => (
          <motion.div
            key={i}
            className="w-1.5 h-1.5 rounded-full bg-purple-400"
            animate={{ opacity: [0.3, 1, 0.3], scale: [0.8, 1, 0.8] }}
            transition={{ duration: 1.2, repeat: Infinity, delay: i * 0.2, ease: "easeInOut" }}
          />
        ))}
      </div>
      <span className="text-sm text-gray-500">Thinking...</span>
    </div>
  );
}

/* ── Response container ──────────────────────────────────── */
function ResponseCard({ tools, text, isStreaming, resultRef }) {
  const hasTools = tools.length > 0;
  const hasText = text.length > 0;

  return (
    <motion.div
      ref={resultRef}
      initial={{ opacity: 0, y: 16 }}
      animate={{ opacity: 1, y: 0 }}
      exit={{ opacity: 0, y: 8 }}
      transition={{ duration: 0.4, ease: [0.16, 1, 0.3, 1] }}
      className="mt-6"
    >
      {/* Tool pills */}
      {hasTools && (
        <div className="flex flex-wrap gap-2 mb-4">
          {tools.map((tc, i) => (
            <ToolPill key={i} tool={tc.tool} input={tc.input} result={tc.result} isLoading={tc.isLoading} />
          ))}
        </div>
      )}

      {/* Response body */}
      {hasText ? (
        <motion.div
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          transition={{ duration: 0.3 }}
          className="rounded-2xl border border-white/[0.06] bg-gradient-to-b from-white/[0.03] to-transparent p-5 sm:p-6"
        >
          <div className="text-sm text-gray-300 prose prose-invert prose-sm max-w-none">
            <ReactMarkdown remarkPlugins={REMARK_PLUGINS} components={mdComponents}>{text}</ReactMarkdown>
          </div>
          {!isStreaming && (
            <motion.div
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              transition={{ delay: 0.3 }}
              className="flex items-center gap-2 mt-4 pt-3 border-t border-white/[0.04]"
            >
              <Sparkles className="w-3 h-3 text-purple-400/50" />
              <p className="text-gray-600 text-[11px]">
                Powered by AI &middot; Data from J-Quants, EDINET & web sources
              </p>
            </motion.div>
          )}
        </motion.div>
      ) : isStreaming && !hasTools ? (
        <div className="rounded-2xl border border-white/[0.06] bg-white/[0.02] p-5">
          <ThinkingDots />
        </div>
      ) : null}
    </motion.div>
  );
}

/* ── Main Component ──────────────────────────────────────── */
export default function QuerySearch() {
  const [query, setQuery] = useState("");
  const [isStreaming, setIsStreaming] = useState(false);
  const [streamingText, setStreamingText] = useState("");
  const [activeTools, setActiveTools] = useState([]);
  const [finalText, setFinalText] = useState("");
  const [finalTools, setFinalTools] = useState([]);
  const inputRef = useRef(null);
  const resultRef = useRef(null);
  const abortRef = useRef(null);
  const streamingRef = useRef(false);

  useEffect(() => {
    return () => { if (abortRef.current) abortRef.current.abort(); };
  }, []);

  useEffect(() => {
    if ((isStreaming || finalText) && resultRef.current) {
      resultRef.current.scrollIntoView({ behavior: "smooth", block: "nearest" });
    }
  }, [streamingText, activeTools, isStreaming, finalText]);

  const handleSearch = useCallback(async (text) => {
    const searchQuery = text || query;
    if (!searchQuery.trim() || streamingRef.current) return;

    streamingRef.current = true;
    setIsStreaming(true);
    setStreamingText("");
    setActiveTools([]);
    setFinalText("");
    setFinalTools([]);

    if (abortRef.current) abortRef.current.abort();
    const controller = new AbortController();
    abortRef.current = controller;

    const messages = [{ role: "user", content: searchQuery.trim() }];
    let fullText = "";
    const toolCalls = [];

    try {
      await streamChat(messages, {
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
          const { tool, summary } = data;
          const tc = toolCalls.find(t => (data.id ? t.id === data.id : t.tool === tool) && t.isLoading);
          if (tc) {
            tc.result = summary;
            tc.isLoading = false;
            setActiveTools([...toolCalls]);
          }
        },
        onError: (msg) => {
          if (controller.signal.aborted) return;
          fullText += `\n\n*Error: ${msg}*`;
          setStreamingText(fullText);
        },
        onDone: () => {},
      });
    } catch {
      // Network error or abort — ignore
    }

    if (!streamingRef.current) return; // handleStop already cleaned up
    setFinalText(fullText);
    setFinalTools(toolCalls.length > 0 ? [...toolCalls] : []);
    setStreamingText("");
    setActiveTools([]);
    streamingRef.current = false;
    setIsStreaming(false);
    inputRef.current?.focus();
  }, [query]);

  const handleClear = () => {
    setQuery("");
    setFinalText("");
    setFinalTools([]);
    setStreamingText("");
    setActiveTools([]);
  };

  const showingResult = isStreaming || finalText;

  return (
    <div className="w-full max-w-3xl mx-auto">
      {/* Search bar */}
      <form
        onSubmit={(e) => {
          e.preventDefault();
          handleSearch();
        }}
      >
        <motion.div
          className={`relative flex items-center rounded-2xl border bg-white/[0.02] transition-all duration-500 ease-out ${
            isStreaming
              ? "border-purple-500/30 shadow-lg shadow-purple-500/5"
              : "border-white/[0.06] focus-within:border-white/20 focus-within:bg-white/[0.05] focus-within:shadow-2xl focus-within:shadow-purple-500/10"
          }`}
          layout
        >
          <div className="ml-5 shrink-0">
            {isStreaming ? (
              <Loader2 className="w-5 h-5 text-purple-400 animate-spin" />
            ) : (
              <Search className="w-5 h-5 text-gray-500" />
            )}
          </div>
          <input
            ref={inputRef}
            type="text"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && !e.shiftKey) {
                e.preventDefault();
                handleSearch();
              }
            }}
            placeholder="Ask about any Japanese company..."
            className="w-full bg-transparent text-white placeholder-gray-600 px-4 py-5 text-[15px] outline-none"
            disabled={isStreaming}
          />
          <div className="flex items-center gap-1.5 mr-3">
            {query && !isStreaming && (
              <motion.button
                type="button"
                initial={{ opacity: 0, scale: 0.8 }}
                animate={{ opacity: 1, scale: 1 }}
                exit={{ opacity: 0, scale: 0.8 }}
                onClick={handleClear}
                className="p-1.5 rounded-lg text-gray-600 hover:text-gray-300 hover:bg-white/[0.06] transition-colors"
              >
                <X className="w-4 h-4" />
              </motion.button>
            )}
            <button
              type="submit"
              disabled={isStreaming || !query.trim()}
              className="p-2.5 rounded-xl bg-gradient-to-r from-purple-600 to-blue-600 hover:from-purple-500 hover:to-blue-500 text-white transition disabled:opacity-30 disabled:cursor-not-allowed"
            >
              <Send className="w-4 h-4" />
            </button>
          </div>
        </motion.div>
      </form>

      {/* Suggested queries — hide when showing results */}
      <AnimatePresence>
        {!showingResult && (
          <motion.div
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0, height: 0 }}
            transition={{ duration: 0.2 }}
            className="mt-4 grid grid-cols-2 gap-2 px-0.5"
          >
            {SUGGESTED_QUERIES.map((sq, i) => {
              const SqIcon = sq.icon;
              return (
                <motion.button
                  key={i}
                  initial={{ opacity: 0, y: 8 }}
                  animate={{ opacity: 1, y: 0 }}
                  transition={{ delay: i * 0.05 }}
                  onClick={() => {
                    setQuery(sq.text);
                    handleSearch(sq.text);
                  }}
                  disabled={isStreaming}
                  className="flex items-center gap-2.5 px-3.5 py-3 rounded-xl border border-white/[0.06] bg-white/[0.02] hover:border-white/[0.12] hover:bg-white/[0.05] text-gray-400 hover:text-gray-200 text-xs text-left transition-all disabled:opacity-50 group"
                >
                  <SqIcon className="w-3.5 h-3.5 shrink-0 text-gray-600 group-hover:text-purple-400 transition-colors" />
                  <span className="line-clamp-1">{sq.text}</span>
                </motion.button>
              );
            })}
          </motion.div>
        )}
      </AnimatePresence>

      {/* Streaming response */}
      <AnimatePresence mode="wait">
        {isStreaming && (
          <ResponseCard
            tools={activeTools}
            text={streamingText}
            isStreaming={true}
            resultRef={resultRef}
          />
        )}
      </AnimatePresence>

      {/* Final response */}
      <AnimatePresence mode="wait">
        {finalText && !isStreaming && (
          <ResponseCard
            tools={finalTools}
            text={finalText}
            isStreaming={false}
            resultRef={resultRef}
          />
        )}
      </AnimatePresence>
    </div>
  );
}
