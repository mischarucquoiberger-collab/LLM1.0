import React, { useState, useRef, useEffect, useCallback } from "react";
import { motion, AnimatePresence } from "framer-motion";
import {
  X, AlertCircle, ArrowUp, Square,
  Copy, Check, TrendingUp, Shield, BarChart3, Users, DollarSign, Lightbulb,
  FileText, Zap,
} from "lucide-react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { streamReportChat } from "@/api/backend";
import { useNavigate } from "react-router-dom";

/* ── Markdown components (matches Query.jsx design) ─────── */
const mdComponents = {
  table: ({ children }) => (
    <div className="my-4 overflow-x-auto rounded-xl ring-1 ring-white/[0.06] overflow-hidden">
      <table className="w-full text-[12px]">{children}</table>
    </div>
  ),
  thead: ({ children }) => <thead className="bg-white/[0.04]">{children}</thead>,
  th: ({ children }) => (
    <th className="px-3 py-2 text-left text-[10px] font-medium text-white/40 uppercase tracking-wider border-b border-white/[0.06]">{children}</th>
  ),
  tbody: ({ children }) => <tbody className="divide-y divide-white/[0.03]">{children}</tbody>,
  tr: ({ children }) => <tr className="hover:bg-white/[0.02] transition-colors">{children}</tr>,
  td: ({ children }) => (
    <td className="px-3 py-2.5 text-white/55 text-[12px] tabular-nums">{children}</td>
  ),
  code: ({ children }) => (
    <code className="px-1 py-0.5 rounded-md bg-white/[0.06] text-[11px] font-mono text-white/60">{children}</code>
  ),
  pre: ({ children }) => (
    <pre className="my-3 rounded-xl bg-black/40 ring-1 ring-white/[0.05] overflow-x-auto [&_code]:block [&_code]:px-4 [&_code]:py-3 [&_code]:text-white/50 [&_code]:leading-relaxed [&_code]:bg-transparent [&_code]:rounded-none [&_code]:p-0">{children}</pre>
  ),
  p: ({ children }) => <p className="mb-3 leading-[1.8] text-[13px] text-white/65 tracking-[-0.01em]">{children}</p>,
  h1: ({ children }) => <h1 className="text-[16px] font-semibold text-white/90 mt-5 mb-2 tracking-tight">{children}</h1>,
  h2: ({ children }) => <h2 className="text-[14px] font-semibold text-white/85 mt-4 mb-2 tracking-tight">{children}</h2>,
  h3: ({ children }) => <h3 className="text-[13px] font-semibold text-white/75 mt-3 mb-1.5 tracking-tight">{children}</h3>,
  strong: ({ children }) => <strong className="text-white/90 font-semibold">{children}</strong>,
  em: ({ children }) => <em className="text-white/45 italic">{children}</em>,
  ul: ({ children }) => <ul className="list-disc mb-3 space-y-0.5 ml-4 text-white/60 text-[13px] leading-[1.7] marker:text-white/20">{children}</ul>,
  ol: ({ children }) => <ol className="list-decimal mb-3 space-y-0.5 ml-4 text-white/60 text-[13px] leading-[1.7] marker:text-white/20">{children}</ol>,
  li: ({ children }) => <li className="text-white/60 text-[13px] leading-[1.7] pl-1">{children}</li>,
  a: ({ href, children }) => {
    const isInternal = href && (href.startsWith("/") && !href.startsWith("//"));
    return isInternal ? (
      <button
        onClick={() => window.__reportAssistantNavigate?.(href)}
        className="text-blue-400/80 hover:text-blue-300 underline underline-offset-2 decoration-blue-500/20 hover:decoration-blue-400/40 transition-colors cursor-pointer bg-transparent border-none p-0 font-inherit text-inherit"
      >{children}</button>
    ) : (
      <a href={href} target="_blank" rel="noopener noreferrer"
        className="text-blue-400/80 hover:text-blue-300 underline underline-offset-2 decoration-blue-500/20 hover:decoration-blue-400/40 transition-colors">{children}</a>
    );
  },
  hr: () => <div className="my-5 h-px bg-gradient-to-r from-transparent via-white/[0.06] to-transparent" />,
  blockquote: ({ children }) => (
    <blockquote className="border-l-2 border-white/[0.08] pl-3 my-3 text-white/40">{children}</blockquote>
  ),
};

/* ── Thinking indicator ────────────────────────────────── */
function ThinkingIndicator() {
  return (
    <motion.div className="flex items-center gap-2.5 py-2" initial={{ opacity: 0 }} animate={{ opacity: 1 }}>
      <div className="relative w-4 h-4">
        <motion.div
          className="absolute inset-0 rounded-full bg-gradient-to-br from-blue-400/30 to-purple-400/20"
          animate={{ scale: [1, 1.4, 1], opacity: [0.5, 0.15, 0.5] }}
          transition={{ duration: 2, repeat: Infinity, ease: "easeInOut" }}
        />
        <motion.div
          className="absolute inset-0.5 rounded-full bg-gradient-to-br from-blue-400/40 to-purple-400/30"
          animate={{ scale: [1, 1.2, 1] }}
          transition={{ duration: 2, repeat: Infinity, ease: "easeInOut", delay: 0.1 }}
        />
      </div>
      <span className="text-[12px] text-white/20 font-light tracking-wide">Thinking</span>
    </motion.div>
  );
}

/* ── Suggestion cards ──────────────────────────────────── */
const SUGGESTIONS = [
  { text: "Executive summary in 3 bullets",  icon: FileText,   color: "text-emerald-400", bg: "bg-emerald-500/8" },
  { text: "Bull vs bear case",               icon: TrendingUp, color: "text-blue-400",    bg: "bg-blue-500/8" },
  { text: "Key financial risks",             icon: Shield,     color: "text-amber-400",   bg: "bg-amber-500/8" },
  { text: "Intrinsic value estimate",        icon: DollarSign, color: "text-cyan-400",    bg: "bg-cyan-500/8" },
  { text: "Revenue & margin breakdown",      icon: BarChart3,  color: "text-purple-400",  bg: "bg-purple-500/8" },
  { text: "SWOT analysis",                   icon: Lightbulb,  color: "text-rose-400",    bg: "bg-rose-500/8" },
  { text: "Peer comparison",                 icon: Users,      color: "text-indigo-400",  bg: "bg-indigo-500/8" },
  { text: "Upcoming catalysts",              icon: Zap,        color: "text-yellow-400",  bg: "bg-yellow-500/8" },
];

const msgSpring = { type: "spring", stiffness: 400, damping: 30 };

/* ── Main component ────────────────────────────────────── */
export default function ReportAssistant({ jobId, companyName, isOpen, onClose, file, sources }) {
  const navigate = useNavigate();

  // Expose navigate for mdComponents internal links
  useEffect(() => {
    window.__reportAssistantNavigate = (path) => navigate(path);
    return () => { delete window.__reportAssistantNavigate; };
  }, [navigate]);

  const [messages, setMessages] = useState([]);
  const [input, setInput] = useState("");
  const [isStreaming, setIsStreaming] = useState(false);
  const [error, setError] = useState(null);
  const [copiedId, setCopiedId] = useState(null);
  const copyTimerRef = useRef(null);
  const abortRef = useRef(null);
  const scrollRef = useRef(null);
  const inputRef = useRef(null);

  useEffect(() => {
    if (scrollRef.current) scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
  }, [messages, isStreaming]);

  useEffect(() => {
    if (isOpen && inputRef.current) {
      const t = setTimeout(() => inputRef.current?.focus(), 300);
      return () => clearTimeout(t);
    }
  }, [isOpen]);

  // Abort streaming + clear timers on unmount
  useEffect(() => {
    return () => { abortRef.current?.abort(); if (copyTimerRef.current) clearTimeout(copyTimerRef.current); };
  }, []);

  const handleCopy = (id, text) => {
    navigator.clipboard.writeText(text).then(() => {
      setCopiedId(id);
      if (copyTimerRef.current) clearTimeout(copyTimerRef.current);
      copyTimerRef.current = setTimeout(() => setCopiedId(null), 2000);
    }).catch(() => {});
  };

  const sendMessage = useCallback(
    (text) => {
      if (!text.trim() || isStreaming || (!jobId && !file)) return;
      const userMsg = { id: Date.now(), role: "user", content: text.trim() };
      const assistantMsg = { id: Date.now() + 1, role: "assistant", content: "", streaming: true };

      setMessages((prev) => [...prev, userMsg, assistantMsg]);
      setInput("");
      setIsStreaming(true);
      setError(null);

      const controller = new AbortController();
      abortRef.current = controller;

      const history = [...messages, userMsg].map((m) => ({ role: m.role, content: m.content }));

      streamReportChat(jobId, history, {
        signal: controller.signal,
        file,
        sources,
        company: companyName,
        onText: (chunk) => {
          setMessages((prev) => {
            const last = prev[prev.length - 1];
            if (last?.streaming) return [...prev.slice(0, -1), { ...last, content: last.content + chunk }];
            return prev;
          });
        },
        onError: (msg) => {
          setError(msg);
          setIsStreaming(false);
          setMessages((prev) => {
            const last = prev[prev.length - 1];
            if (last?.streaming) return [...prev.slice(0, -1), { ...last, streaming: false }];
            return prev;
          });
        },
        onDone: () => {
          setIsStreaming(false);
          setMessages((prev) => {
            const last = prev[prev.length - 1];
            if (last?.streaming) return [...prev.slice(0, -1), { ...last, streaming: false }];
            return prev;
          });
        },
      });
    },
    [jobId, messages, isStreaming, file, sources, companyName]
  );

  const handleSubmit = (e) => {
    e.preventDefault();
    sendMessage(input);
  };

  const handleStop = () => {
    abortRef.current?.abort();
    setIsStreaming(false);
    setMessages((prev) => {
      const last = prev[prev.length - 1];
      if (last?.streaming) return [...prev.slice(0, -1), { ...last, streaming: false }];
      return prev;
    });
  };

  return (
    <AnimatePresence>
      {isOpen && (
        <motion.div
          initial={{ width: 0, opacity: 0 }}
          animate={{ width: 420, opacity: 1 }}
          exit={{ width: 0, opacity: 0 }}
          transition={{ duration: 0.35, ease: [0.16, 1, 0.3, 1] }}
          className="shrink-0 border-l border-white/[0.04] bg-[#060910] flex flex-col overflow-hidden h-full"
          style={{ maxWidth: "85vw" }}
        >
          <div style={{ width: "min(420px, 85vw)" }} className="flex flex-col h-full">

            {/* ── Header ──────────────────────────────── */}
            <div className="shrink-0 px-5 py-4 flex items-center gap-3">
              <div className="flex-1 min-w-0">
                <p className="text-[13px] font-medium text-white/80 truncate tracking-tight">
                  Report Assistant
                </p>
                <p className="text-[11px] text-white/25 truncate mt-0.5">
                  {companyName}
                </p>
              </div>
              <button
                onClick={onClose}
                className="w-7 h-7 rounded-lg flex items-center justify-center text-white/20 hover:text-white/50 hover:bg-white/[0.06] transition-all duration-200"
              >
                <X className="w-4 h-4" />
              </button>
            </div>

            {/* ── Divider ──────────────────────────────── */}
            <div className="h-px bg-gradient-to-r from-transparent via-white/[0.06] to-transparent mx-4" />

            {/* ── Messages area ────────────────────────── */}
            <div className="flex-1 relative overflow-hidden">
              {/* Top fade */}
              <div className="absolute top-0 left-0 right-0 h-6 bg-gradient-to-b from-[#060910] to-transparent z-10 pointer-events-none" />
              {/* Bottom fade */}
              <div className="absolute bottom-0 left-0 right-0 h-10 bg-gradient-to-t from-[#060910] to-transparent z-10 pointer-events-none" />

              <div
                ref={scrollRef}
                className="h-full overflow-y-auto px-5 py-5 assistant-scroll"
              >
                {/* ── Empty state ──────────────────────── */}
                {messages.length === 0 && (
                  <motion.div
                    initial={{ opacity: 0, y: 8 }}
                    animate={{ opacity: 1, y: 0 }}
                    transition={{ duration: 0.5, ease: [0.16, 1, 0.3, 1] }}
                    className="space-y-6 pt-2"
                  >
                    <div className="text-center">
                      <p className="text-[15px] font-medium text-white/80 tracking-tight">
                        Ask about this report
                      </p>
                      <p className="text-[11px] text-white/20 mt-1.5 leading-relaxed">
                        Get instant answers from the research analysis
                      </p>
                    </div>

                    {/* Suggestion grid */}
                    <div className="grid grid-cols-2 gap-2">
                      {SUGGESTIONS.map((s, i) => {
                        const Icon = s.icon;
                        return (
                          <motion.button
                            key={s.text}
                            onClick={() => sendMessage(s.text)}
                            initial={{ opacity: 0, y: 6 }}
                            animate={{ opacity: 1, y: 0 }}
                            transition={{ delay: 0.1 + i * 0.04, duration: 0.4 }}
                            whileHover={{ scale: 1.02, y: -1 }}
                            whileTap={{ scale: 0.98 }}
                            className="flex flex-col items-start gap-2 p-3 rounded-xl bg-white/[0.02] ring-1 ring-white/[0.04] hover:ring-white/[0.1] hover:bg-white/[0.04] transition-all duration-200 text-left group"
                          >
                            <div className={`w-6 h-6 rounded-lg ${s.bg} flex items-center justify-center`}>
                              <Icon className={`w-3 h-3 ${s.color} opacity-70 group-hover:opacity-100 transition-opacity`} />
                            </div>
                            <span className="text-[11px] text-white/40 group-hover:text-white/60 transition-colors leading-snug">
                              {s.text}
                            </span>
                          </motion.button>
                        );
                      })}
                    </div>
                  </motion.div>
                )}

                {/* ── Message list ─────────────────────── */}
                <div className="space-y-5">
                  {messages.map((msg) => (
                    <div key={msg.id}>
                      {msg.role === "user" ? (
                        <motion.div
                          className="flex justify-end mb-1"
                          initial={{ opacity: 0, y: 4 }}
                          animate={{ opacity: 1, y: 0 }}
                          transition={msgSpring}
                        >
                          <div className="max-w-[85%] rounded-[16px] rounded-br-md bg-white/[0.06]"
                            style={{ padding: "10px 14px" }}>
                            <p className="text-[13px] text-white/70 leading-relaxed whitespace-pre-wrap break-words">
                              {msg.content}
                            </p>
                          </div>
                        </motion.div>
                      ) : (
                        <motion.div
                          className="mb-1"
                          initial={{ opacity: 0, y: 4 }}
                          animate={{ opacity: 1, y: 0 }}
                          transition={msgSpring}
                        >
                          {msg.content ? (
                            <div className="max-w-none overflow-hidden">
                              <ReactMarkdown remarkPlugins={[remarkGfm]} components={mdComponents}>
                                {msg.content}
                              </ReactMarkdown>
                              {msg.streaming && (
                                <span className="inline-block w-[2px] h-[14px] bg-white/30 ml-0.5 -mb-0.5 align-text-bottom animate-[blink_0.8s_ease-in-out_infinite]" />
                              )}
                            </div>
                          ) : msg.streaming ? (
                            <ThinkingIndicator />
                          ) : null}

                          {/* Copy button */}
                          {msg.content && !msg.streaming && (
                            <div className="flex items-center gap-1 mt-1.5">
                              <button
                                onClick={() => handleCopy(msg.id, msg.content)}
                                className="flex items-center gap-1 px-2 py-0.5 rounded-md text-[10px] text-white/15 hover:text-white/40 hover:bg-white/[0.04] transition-all duration-200"
                              >
                                {copiedId === msg.id
                                  ? <><Check className="w-2.5 h-2.5 text-emerald-400/60" /><span className="text-emerald-400/60">Copied</span></>
                                  : <><Copy className="w-2.5 h-2.5" />Copy</>
                                }
                              </button>
                            </div>
                          )}
                        </motion.div>
                      )}
                    </div>
                  ))}
                </div>
              </div>
            </div>

            {/* ── Error ────────────────────────────────── */}
            <AnimatePresence>
              {error && (
                <motion.div
                  initial={{ opacity: 0, height: 0 }}
                  animate={{ opacity: 1, height: "auto" }}
                  exit={{ opacity: 0, height: 0 }}
                  className="shrink-0 px-5 pb-2"
                >
                  <div className="flex items-center gap-2 px-3 py-2 rounded-xl bg-red-500/8 ring-1 ring-red-500/15 text-[11px] text-red-400/80">
                    <AlertCircle className="w-3 h-3 shrink-0" />
                    <span className="truncate">{error}</span>
                  </div>
                </motion.div>
              )}
            </AnimatePresence>

            {/* ── Input area ───────────────────────────── */}
            <div className="shrink-0 px-4 pb-4 pt-2">
              <div className="relative group/bar">
                {/* Focus glow */}
                <div className="absolute -inset-0.5 rounded-2xl bg-gradient-to-b from-white/[0.04] to-transparent opacity-0 group-focus-within/bar:opacity-100 blur-xl transition-opacity duration-700 pointer-events-none" />

                <div className="relative flex items-center rounded-2xl border border-white/[0.06] group-focus-within/bar:border-white/[0.14] bg-[#0c1018] transition-all duration-500 overflow-hidden">
                  <form onSubmit={handleSubmit} className="flex items-center w-full">
                    <input
                      ref={inputRef}
                      value={input}
                      onChange={(e) => setInput(e.target.value)}
                      onKeyDown={(e) => {
                        if (e.key === "Enter" && !e.shiftKey) {
                          e.preventDefault();
                          if (!isStreaming) handleSubmit(e);
                        }
                      }}
                      placeholder="Ask about the report..."
                      className="flex-1 bg-transparent text-white/85 placeholder-white/20 text-[13px] outline-none px-4 py-3 tracking-[-0.01em]"
                      disabled={isStreaming}
                    />

                    <div className="pr-2">
                      {isStreaming ? (
                        <button
                          type="button"
                          onClick={handleStop}
                          className="flex items-center gap-1 px-3 py-1.5 rounded-xl text-[11px] font-medium bg-white/[0.06] text-white/35 hover:bg-white/[0.12] hover:text-white/55 transition-all duration-200"
                        >
                          <Square className="w-2 h-2 fill-current" />
                          Stop
                        </button>
                      ) : input.trim() ? (
                        <motion.button
                          type="submit"
                          initial={{ scale: 0.8, opacity: 0 }}
                          animate={{ scale: 1, opacity: 1 }}
                          className="flex items-center justify-center w-7 h-7 rounded-full bg-white text-black hover:bg-gray-200 transition-all duration-200 shadow-lg shadow-white/10"
                        >
                          <ArrowUp className="w-3.5 h-3.5" strokeWidth={2.5} />
                        </motion.button>
                      ) : null}
                    </div>
                  </form>
                </div>
              </div>

              {/* Disclaimer */}
              <p className="text-center text-[9px] text-white/10 mt-2.5 tracking-wide">
                Answers based on report sources only
              </p>
            </div>
          </div>

          {/* Custom scrollbar + cursor blink CSS */}
          <style>{`
            .assistant-scroll::-webkit-scrollbar { width: 3px; }
            .assistant-scroll::-webkit-scrollbar-track { background: transparent; }
            .assistant-scroll::-webkit-scrollbar-thumb { background: rgba(255,255,255,0.03); border-radius: 3px; }
            .assistant-scroll::-webkit-scrollbar-thumb:hover { background: rgba(255,255,255,0.06); }
            @keyframes blink { 0%, 100% { opacity: 1; } 50% { opacity: 0; } }
          `}</style>
        </motion.div>
      )}
    </AnimatePresence>
  );
}
