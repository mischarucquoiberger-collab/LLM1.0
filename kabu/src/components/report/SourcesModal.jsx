import React from "react";
import { motion, AnimatePresence } from "framer-motion";
import { X, ExternalLink, Globe, FileText, BookOpen } from "lucide-react";

function SourceCard({ source, color }) {
  const badgeStyles = {
    blue: "bg-blue-500/10 text-blue-400 border-blue-500/15",
    amber: "bg-amber-500/10 text-amber-400 border-amber-500/15",
  };

  let hostname = "";
  try { hostname = new URL(source.url).hostname; } catch {}

  return (
    <a
      href={source.url || "#"}
      target={source.url ? "_blank" : undefined}
      rel="noreferrer"
      onClick={source.url ? undefined : (e) => e.preventDefault()}
      className="group flex items-start gap-3 p-3.5 rounded-xl bg-white/[0.02] border border-white/[0.06] hover:bg-white/[0.05] hover:border-white/[0.12] transition-all"
    >
      <span className={`inline-flex items-center shrink-0 px-2 py-0.5 rounded-md text-[10px] font-semibold tracking-wide border mt-0.5 ${badgeStyles[color] || badgeStyles.blue}`}>
        {source.type === "edinet" ? "EDINET" : "WEB"}
      </span>
      <div className="min-w-0 flex-1">
        <p className="text-sm font-medium text-gray-200 group-hover:text-white truncate leading-snug">
          {source.title || hostname}
        </p>
        {hostname && (
          <p className="text-[11px] text-gray-500 font-mono truncate mt-0.5">{hostname}</p>
        )}
        {source.snippet && (
          <p className="text-xs text-gray-400/80 mt-1.5 line-clamp-2 leading-relaxed">{source.snippet}</p>
        )}
        {source.date && (
          <p className="text-[10px] text-gray-600 mt-1.5">{source.date}</p>
        )}
      </div>
      <ExternalLink className="w-3.5 h-3.5 text-gray-600 opacity-0 group-hover:opacity-100 transition-opacity shrink-0 mt-0.5" />
    </a>
  );
}

function SourceSection({ title, icon: Icon, sources, color }) {
  return (
    <div>
      <div className="flex items-center gap-2 mb-3 px-1">
        <Icon className={`w-4 h-4 ${color === "amber" ? "text-amber-400" : "text-blue-400"}`} />
        <h3 className="text-xs font-semibold uppercase tracking-wider text-gray-400">{title}</h3>
        <span className="ml-auto text-[11px] text-gray-600 bg-white/[0.04] px-2 py-0.5 rounded-full">{sources.length}</span>
      </div>
      <div className="space-y-2">
        {sources.map((source, i) => (
          <SourceCard key={source.id || `${source.url}-${i}`} source={source} color={color} />
        ))}
      </div>
    </div>
  );
}

export default function SourcesModal({ isOpen, onClose, sources = [], companyName }) {
  const webSources = sources.filter((s) => s.type !== "edinet");
  const edinetSources = sources.filter((s) => s.type === "edinet");

  return (
    <AnimatePresence>
      {isOpen && (
        <>
          {/* Overlay */}
          <motion.div
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            transition={{ duration: 0.2 }}
            className="fixed inset-0 bg-black/60 backdrop-blur-sm z-50"
            onClick={onClose}
          />
          {/* Modal — use flexbox centering for reliable positioning */}
          <motion.div
            initial={{ opacity: 0, scale: 0.96, y: 12 }}
            animate={{ opacity: 1, scale: 1, y: 0 }}
            exit={{ opacity: 0, scale: 0.96, y: 12 }}
            transition={{ duration: 0.25, ease: [0.16, 1, 0.3, 1] }}
            className="fixed inset-0 z-50 flex items-center justify-center p-4 pointer-events-none"
          >
            <div className="pointer-events-auto w-full max-w-2xl max-h-[82vh] flex flex-col bg-[#0f1322] rounded-2xl border border-white/[0.08] shadow-[0_32px_64px_-12px_rgba(0,0,0,0.6)] overflow-hidden">
              {/* Accent bar */}
              <div className="h-px bg-gradient-to-r from-transparent via-purple-500/40 to-transparent" />

              {/* Header */}
              <div className="px-6 py-5 border-b border-white/[0.06] flex items-center justify-between gap-4">
                <div className="flex items-center gap-3 min-w-0">
                  <div className="w-9 h-9 rounded-xl bg-purple-500/10 border border-purple-500/20 flex items-center justify-center shrink-0">
                    <BookOpen className="w-4 h-4 text-purple-400" />
                  </div>
                  <div className="min-w-0">
                    <h2 className="text-base font-semibold text-white leading-tight">Sources</h2>
                    <p className="text-xs text-gray-500 mt-0.5 truncate">
                      {sources.length} source{sources.length !== 1 ? "s" : ""}{companyName ? ` · ${companyName}` : ""}
                    </p>
                  </div>
                </div>
                <button
                  onClick={onClose}
                  className="w-8 h-8 rounded-lg bg-white/[0.04] border border-white/[0.06] flex items-center justify-center text-gray-500 hover:text-gray-300 hover:bg-white/[0.08] transition-colors shrink-0"
                >
                  <X className="w-4 h-4" />
                </button>
              </div>

              {/* Scrollable body */}
              <div className="overflow-y-auto flex-1 p-6 space-y-6 overscroll-contain">
                {webSources.length > 0 && (
                  <SourceSection title="Web Sources" icon={Globe} sources={webSources} color="blue" />
                )}
                {edinetSources.length > 0 && (
                  <SourceSection title="EDINET Filings" icon={FileText} sources={edinetSources} color="amber" />
                )}
                {sources.length === 0 && (
                  <div className="text-center py-12">
                    <Globe className="w-8 h-8 text-gray-600 mx-auto mb-3" />
                    <p className="text-gray-500 text-sm">No sources available for this report.</p>
                  </div>
                )}
              </div>
            </div>
          </motion.div>
        </>
      )}
    </AnimatePresence>
  );
}
