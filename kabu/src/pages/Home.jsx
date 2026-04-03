import React, { useEffect, useState, useCallback, useRef } from "react";
import { gsap } from "gsap";
import { Download, Trash2, BookOpen, ArrowUpRight, Search } from "lucide-react";
import SearchBar from "@/components/home/SearchBar";
import { useCircleTransition } from "@/components/CircleTransition";
import { deleteJob, getStatus, buildDownloadUrl } from "@/api/backend";
import SourcesModal from "@/components/report/SourcesModal";
import KineticType from "@/components/KineticType";

export default function Home() {
  const [history, setHistory] = useState([]);
  const [sourcesOpen, setSourcesOpen] = useState(false);
  const [activeSources, setActiveSources] = useState([]);
  const [activeCompany, setActiveCompany] = useState("");
  const [hoveredItem, setHoveredItem] = useState(null);
  const [generating, setGenerating] = useState(null); // active generating job
  const { navigateWithReveal } = useCircleTransition();

  // refs for GSAP entry animation
  const titleRef = useRef(null);
  const subRef = useRef(null);
  const searchRef = useRef(null);
  const recentRef = useRef(null);
  const navRef = useRef(null);

  useEffect(() => {
    try {
      const raw = localStorage.getItem("reports_history");
      if (raw) {
        const parsed = JSON.parse(raw);
        if (Array.isArray(parsed)) {
          const valid = parsed.filter((h) => h && h.jobId && (h.companyName || h.ticker));
          const seen = new Set();
          const deduped = valid.filter((h) => {
            if (seen.has(h.jobId)) return false;
            seen.add(h.jobId);
            return true;
          });
          if (deduped.length < valid.length) {
            localStorage.setItem("reports_history", JSON.stringify(deduped));
          }
          setHistory(deduped);
        }
      }
    } catch { setHistory([]); }
  }, []);

  // Poll active generating job
  useEffect(() => {
    let dead = false, timer;
    const check = () => {
      try {
        const raw = localStorage.getItem("active_generating");
        if (!raw) { setGenerating(null); timer = setTimeout(check, 2000); return; }
        const data = JSON.parse(raw);
        if (!data?.jobId) { setGenerating(null); timer = setTimeout(check, 2000); return; }
        getStatus(data.jobId).then((st) => {
          if (dead) return;
          if (st.status === "complete" || st.status === "warning" || st.status === "error") {
            localStorage.removeItem("active_generating");
            setGenerating(null);
            // Save completed report to history (GenerateReport may be unmounted)
            try {
              const h = JSON.parse(localStorage.getItem("reports_history") || "[]");
              if (!h.some((entry) => entry.jobId === data.jobId)) {
                h.unshift({
                  jobId: data.jobId,
                  ticker: data.ticker || st.stock_code || "",
                  companyName: st.company_name || data.companyName || data.ticker || "",
                  html: st.html_file ? buildDownloadUrl(st.html_file) : null,
                  pdf: st.pdf_file ? buildDownloadUrl(st.pdf_file) : null,
                  finishedAt: st.finished_at || new Date().toISOString(),
                  sources: st.sources || [],
                });
                localStorage.setItem("reports_history", JSON.stringify(h.slice(0, 50)));
              }
              setHistory(h.filter((x) => x && x.jobId));
            } catch {}
          } else {
            setGenerating({
              jobId: data.jobId,
              ticker: data.ticker || st.stock_code || "",
              companyName: st.company_name || data.companyName || "",
              progress: st.interpolated_progress ?? st.progress ?? 0,
              step: st.step || "Starting",
              eta: st.eta_seconds,
              mode: data.mode,
            });
          }
          timer = setTimeout(check, 1500);
        }).catch(() => {
          if (dead) return;
          setGenerating(null);
          localStorage.removeItem("active_generating");
          timer = setTimeout(check, 3000);
        });
      } catch {
        timer = setTimeout(check, 2000);
      }
    };
    check();
    return () => { dead = true; if (timer) clearTimeout(timer); };
  }, []);

  // entry animation
  useEffect(() => {
    const items = [titleRef, subRef, searchRef, navRef, recentRef].map((r) => r.current).filter(Boolean);
    gsap.set(items, { opacity: 0, y: "40%" });
    const tween = gsap.to(items, {
      duration: 1.2,
      ease: "expo",
      opacity: 1,
      y: "0%",
      stagger: 0.07,
      delay: 0.15,
    });
    return () => tween.kill();
  }, []);

  const formatDate = (iso) => {
    if (!iso) return "";
    const d = new Date(iso);
    const now = new Date();
    const diff = now - d;
    if (diff < 0) return "just now";
    if (diff < 60000) return "just now";
    if (diff < 3600000) return `${Math.floor(diff / 60000)}m ago`;
    if (diff < 86400000) return `${Math.floor(diff / 3600000)}h ago`;
    if (diff < 604800000) return `${Math.floor(diff / 86400000)}d ago`;
    return d.toLocaleString([], { month: "short", day: "numeric" });
  };

  const handleDelete = useCallback(async (jobId) => {
    setHistory((prev) => {
      const updated = prev.filter((h) => h.jobId !== jobId);
      localStorage.setItem("reports_history", JSON.stringify(updated));
      return updated;
    });
    try { await deleteJob(jobId); } catch {}
  }, []);

  const handleView = useCallback((item, e) => {
    const makeInline = (u) => {
      if (!u) return null;
      if (u.includes("inline=1")) return u;
      return u.includes("?") ? `${u}&inline=1` : `${u}?inline=1`;
    };
    const direct = makeInline(item.html) || makeInline(item.pdf) || item.html || item.pdf;
    if (!direct) return;
    const title = item.companyName || item.ticker;
    const params = new URLSearchParams({ url: direct, title, jobId: item.jobId });
    navigateWithReveal(`/Viewer?${params.toString()}`, e);
  }, [navigateWithReveal]);

  return (
    <main style={{ position: "relative", overflowX: "hidden", width: "100%", minHeight: "100vh", background: "#fff" }}>
      <KineticType settled />

      {/* Back button */}
      <button
        type="button"
        onClick={(e) => navigateWithReveal("/", e)}
        style={{
          background: "none",
          border: 0,
          padding: 0,
          position: "absolute",
          top: "clamp(1.2rem, 3vw, 2.5rem)",
          left: "clamp(1.2rem, 3vw, 2.5rem)",
          zIndex: 1000,
          cursor: "pointer",
          width: "clamp(36px, 6vw, 50px)",
          stroke: "#0a0a0a",
          transition: "filter 0.3s ease",
        }}
        onMouseEnter={(e) => { e.currentTarget.style.filter = "opacity(0.35)"; }}
        onMouseLeave={(e) => { e.currentTarget.style.filter = "none"; }}
      >
        <svg viewBox="0 0 50 9" width="100%" strokeLinecap="round">
          <path d="M0 4.5l5-3M0 4.5l5 3M50 4.5h-77" fill="none" />
        </svg>
      </button>

      {/* Content */}
      <section
        style={{
          position: "relative",
          zIndex: 10,
          display: "flex",
          flexDirection: "column",
          minHeight: "100vh",
          padding: "clamp(4rem, 8vh, 6rem) clamp(1rem, 3vw, 2rem)",
        }}
      >
        <div style={{ width: "100%", maxWidth: 540, margin: "auto" }}>
          <h2
            ref={titleRef}
            style={{
              fontFamily: "'Space Grotesk', sans-serif",
              fontSize: "clamp(1.8rem, 3.5vw, 2.5rem)",
              fontWeight: 700,
              letterSpacing: "-0.03em",
              margin: "0 0 0.5rem",
              color: "#0a0a0a",
              textAlign: "center",
            }}
          >
            Research
          </h2>
          <p
            ref={subRef}
            style={{
              textAlign: "center",
              fontFamily: "'Space Grotesk', sans-serif",
              fontSize: "0.85rem",
              color: "rgba(0,0,0,0.4)",
              fontWeight: 300,
              margin: "0 0 2rem",
            }}
          >
            Creation of a real-time custom research report - delivered in minutes.
          </p>

          <div ref={searchRef}>
            <SearchBar />
          </div>

          {/* Query link */}
          <div ref={navRef} style={{ display: "flex", justifyContent: "center", marginTop: "1.2rem" }}>
            <button
              type="button"
              onClick={(e) => navigateWithReveal("/Query", e)}
              style={{
                fontFamily: "'Space Grotesk', sans-serif",
                fontSize: "0.6rem",
                fontWeight: 500,
                letterSpacing: "0.18em",
                textTransform: "uppercase",
                color: "rgba(0,0,0,0.22)",
                background: "none",
                border: "none",
                cursor: "pointer",
                padding: "5px 10px",
                borderRadius: 6,
                transition: "all 0.2s ease",
              }}
              onMouseEnter={(e) => {
                e.currentTarget.style.color = "rgba(0,0,0,0.55)";
                e.currentTarget.style.background = "rgba(0,0,0,0.03)";
              }}
              onMouseLeave={(e) => {
                e.currentTarget.style.color = "rgba(0,0,0,0.22)";
                e.currentTarget.style.background = "none";
              }}
            >
              Query
            </button>
          </div>

          {/* Active generating indicator */}
          {generating && (
            <button
              type="button"
              onClick={(e) => {
                const p = new URLSearchParams({
                  jobId: generating.jobId,
                  ticker: generating.ticker,
                  name: generating.companyName,
                  mode: generating.mode || "full",
                });
                navigateWithReveal(`/GenerateReport?${p.toString()}`, e);
              }}
              style={{
                marginTop: "2.5rem",
                width: "100%",
                background: "none",
                border: "1px solid rgba(0,0,0,0.06)",
                borderRadius: 14,
                padding: "16px 20px",
                cursor: "pointer",
                position: "relative",
                overflow: "hidden",
                textAlign: "left",
                transition: "border-color 0.3s ease, box-shadow 0.3s ease",
              }}
              onMouseEnter={(e) => {
                e.currentTarget.style.borderColor = "rgba(222,95,64,0.2)";
                e.currentTarget.style.boxShadow = "0 4px 20px rgba(222,95,64,0.06)";
              }}
              onMouseLeave={(e) => {
                e.currentTarget.style.borderColor = "rgba(0,0,0,0.06)";
                e.currentTarget.style.boxShadow = "none";
              }}
            >
              {/* Progress bar background */}
              <div
                style={{
                  position: "absolute",
                  top: 0,
                  left: 0,
                  height: "100%",
                  width: `${generating.progress}%`,
                  background: "linear-gradient(90deg, rgba(222,95,64,0.03) 0%, rgba(222,95,64,0.06) 100%)",
                  transition: "width 1.2s cubic-bezier(0.16,1,0.3,1)",
                  borderRadius: 14,
                }}
              />
              {/* Shimmer overlay */}
              <div
                style={{
                  position: "absolute",
                  top: 0,
                  left: 0,
                  width: "100%",
                  height: "100%",
                  background: "linear-gradient(90deg, transparent 0%, rgba(222,95,64,0.04) 50%, transparent 100%)",
                  backgroundSize: "200% 100%",
                  animation: "shimmer 2s ease-in-out infinite",
                  borderRadius: 14,
                }}
              />
              <style>{`@keyframes shimmer { 0% { background-position: 200% 0; } 100% { background-position: -200% 0; } }`}</style>
              {/* Content */}
              <div style={{ position: "relative", zIndex: 1, display: "flex", alignItems: "center", gap: 14 }}>
                {/* Pulsing dot */}
                <div style={{ position: "relative", width: 10, height: 10, flexShrink: 0 }}>
                  <div
                    style={{
                      width: 10,
                      height: 10,
                      borderRadius: "50%",
                      background: "#de5f40",
                      animation: "pulse-dot 2s ease-in-out infinite",
                    }}
                  />
                  <div
                    style={{
                      position: "absolute",
                      top: -3,
                      left: -3,
                      width: 16,
                      height: 16,
                      borderRadius: "50%",
                      border: "1.5px solid rgba(222,95,64,0.3)",
                      animation: "pulse-ring 2s ease-in-out infinite",
                    }}
                  />
                  <style>{`
                    @keyframes pulse-dot { 0%, 100% { opacity: 1; transform: scale(1); } 50% { opacity: 0.6; transform: scale(0.85); } }
                    @keyframes pulse-ring { 0%, 100% { opacity: 0.4; transform: scale(1); } 50% { opacity: 0; transform: scale(1.8); } }
                  `}</style>
                </div>
                {/* Text */}
                <div style={{ flex: 1, minWidth: 0 }}>
                  <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                    <span
                      style={{
                        fontFamily: "'Space Grotesk', sans-serif",
                        fontSize: "0.8rem",
                        fontWeight: 500,
                        color: "#0a0a0a",
                        overflow: "hidden",
                        textOverflow: "ellipsis",
                        whiteSpace: "nowrap",
                      }}
                    >
                      {generating.companyName || generating.ticker}
                    </span>
                    <span
                      style={{
                        fontFamily: "'Space Grotesk', sans-serif",
                        fontSize: "0.65rem",
                        fontWeight: 500,
                        color: "var(--color-accent, #de5f40)",
                        letterSpacing: "0.05em",
                        flexShrink: 0,
                      }}
                    >
                      {generating.ticker}
                    </span>
                  </div>
                  <div style={{ display: "flex", alignItems: "center", gap: 8, marginTop: 3 }}>
                    <span
                      style={{
                        fontFamily: "'Space Grotesk', sans-serif",
                        fontSize: "0.65rem",
                        fontWeight: 500,
                        color: "rgba(222,95,64,0.7)",
                        letterSpacing: "0.08em",
                        textTransform: "uppercase",
                      }}
                    >
                      Generating
                    </span>
                    <span
                      style={{
                        fontFamily: "'Space Grotesk', sans-serif",
                        fontSize: "0.65rem",
                        fontWeight: 400,
                        color: "rgba(0,0,0,0.3)",
                      }}
                    >
                      {generating.step} — {Math.round(generating.progress)}%
                    </span>
                    {generating.eta != null && generating.eta > 0 && (
                      <span
                        style={{
                          fontFamily: "'Space Grotesk', sans-serif",
                          fontSize: "0.65rem",
                          fontWeight: 400,
                          color: "rgba(0,0,0,0.25)",
                          fontVariantNumeric: "tabular-nums",
                        }}
                      >
                        ~{Math.floor(generating.eta / 60)}:{String(Math.floor(generating.eta % 60)).padStart(2, "0")}
                      </span>
                    )}
                  </div>
                </div>
                {/* Arrow */}
                <svg width="14" height="14" viewBox="0 0 14 14" fill="none" style={{ flexShrink: 0, opacity: 0.2 }}>
                  <path d="M5 3l4 4-4 4" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
                </svg>
              </div>
              {/* Bottom progress line */}
              <div
                style={{
                  position: "absolute",
                  bottom: 0,
                  left: 0,
                  height: 2,
                  width: `${generating.progress}%`,
                  background: "linear-gradient(90deg, #de5f40, #e8825e)",
                  borderRadius: "0 0 14px 14px",
                  transition: "width 1.2s cubic-bezier(0.16,1,0.3,1)",
                }}
              />
            </button>
          )}

          {/* Recent reports */}
          {history.length > 0 && (
            <div ref={recentRef} style={{ marginTop: generating ? "1.5rem" : "3rem" }}>
              <span
                style={{
                  display: "block",
                  fontFamily: "'Space Grotesk', sans-serif",
                  fontSize: "0.6rem",
                  textTransform: "uppercase",
                  letterSpacing: "0.25em",
                  color: "rgba(0,0,0,0.4)",
                  fontWeight: 500,
                  marginBottom: "1rem",
                }}
              >
                Recent
              </span>
              <ul style={{ listStyle: "none", margin: 0, padding: 0 }}>
                {history.slice(0, 12).map((item) => {
                  const isHov = hoveredItem === item.jobId;
                  return (
                    <li
                      key={item.jobId}
                      style={{
                        display: "flex",
                        alignItems: "center",
                        padding: "0.85rem 0",
                        borderTop: "1px solid rgba(0,0,0,0.08)",
                        transition: "transform 0.4s cubic-bezier(0.16,1,0.3,1)",
                        transform: isHov ? "translateX(6px)" : "translateX(0)",
                        cursor: "default",
                      }}
                      onMouseEnter={() => setHoveredItem(item.jobId)}
                      onMouseLeave={() => setHoveredItem(null)}
                    >
                      {/* Company name */}
                      <span
                        style={{
                          fontFamily: "'Space Grotesk', sans-serif",
                          fontSize: "0.85rem",
                          fontWeight: 500,
                          color: "#0a0a0a",
                          flex: 1,
                          overflow: "hidden",
                          textOverflow: "ellipsis",
                          whiteSpace: "nowrap",
                        }}
                      >
                        {item.companyName}
                      </span>

                      {/* Ticker */}
                      <span
                        style={{
                          fontFamily: "'Space Grotesk', sans-serif",
                          fontSize: "0.7rem",
                          fontWeight: 500,
                          color: "var(--color-accent, #de5f40)",
                          letterSpacing: "0.05em",
                          marginRight: "1rem",
                          flexShrink: 0,
                        }}
                      >
                        {item.ticker}
                      </span>

                      {/* Time */}
                      <span
                        style={{
                          fontFamily: "'Space Grotesk', sans-serif",
                          fontSize: "0.7rem",
                          color: "rgba(0,0,0,0.4)",
                          fontWeight: 300,
                          marginRight: "1rem",
                          flexShrink: 0,
                        }}
                      >
                        {formatDate(item.finishedAt)}
                      </span>

                      {/* Actions — visible on hover */}
                      <div
                        style={{
                          display: "flex",
                          alignItems: "center",
                          gap: 4,
                          opacity: isHov ? 1 : 0,
                          transition: "opacity 0.2s ease",
                          flexShrink: 0,
                        }}
                      >
                        {item.sources && item.sources.length > 0 && (
                          <button
                            type="button"
                            onClick={() => {
                              setActiveSources(item.sources);
                              setActiveCompany(item.companyName || item.ticker);
                              setSourcesOpen(true);
                            }}
                            style={{
                              background: "none",
                              border: "none",
                              cursor: "pointer",
                              padding: "4px 6px",
                              borderRadius: 4,
                              color: "rgba(0,0,0,0.3)",
                              display: "inline-flex",
                              alignItems: "center",
                              gap: 3,
                              fontSize: "0.65rem",
                              fontFamily: "'Space Grotesk', sans-serif",
                              transition: "color 0.15s ease",
                            }}
                            onMouseEnter={(e) => { e.currentTarget.style.color = "rgba(0,0,0,0.7)"; }}
                            onMouseLeave={(e) => { e.currentTarget.style.color = "rgba(0,0,0,0.3)"; }}
                          >
                            <BookOpen size={12} />
                            {item.sources.length}
                          </button>
                        )}

                        {(item.html || item.pdf) && (
                          <button
                            type="button"
                            onClick={(e) => handleView(item, e)}
                            style={{
                              background: "none",
                              border: "none",
                              cursor: "pointer",
                              padding: "4px 8px",
                              borderRadius: 4,
                              color: "rgba(0,0,0,0.3)",
                              display: "inline-flex",
                              alignItems: "center",
                              gap: 3,
                              fontSize: "0.65rem",
                              fontFamily: "'Space Grotesk', sans-serif",
                              fontWeight: 500,
                              transition: "all 0.15s ease",
                            }}
                            onMouseEnter={(e) => {
                              e.currentTarget.style.background = "#0a0a0a";
                              e.currentTarget.style.color = "#fff";
                            }}
                            onMouseLeave={(e) => {
                              e.currentTarget.style.background = "none";
                              e.currentTarget.style.color = "rgba(0,0,0,0.3)";
                            }}
                          >
                            View <ArrowUpRight size={10} />
                          </button>
                        )}

                        {item.pdf && (
                          <a
                            href={item.pdf}
                            target="_blank"
                            rel="noreferrer"
                            style={{
                              color: "rgba(0,0,0,0.2)",
                              padding: "4px 6px",
                              borderRadius: 4,
                              display: "inline-flex",
                              textDecoration: "none",
                              transition: "color 0.15s ease",
                            }}
                            onMouseEnter={(e) => { e.currentTarget.style.color = "rgba(0,0,0,0.6)"; }}
                            onMouseLeave={(e) => { e.currentTarget.style.color = "rgba(0,0,0,0.2)"; }}
                          >
                            <Download size={12} />
                          </a>
                        )}

                        <button
                          type="button"
                          onClick={() => handleDelete(item.jobId)}
                          title="Delete"
                          style={{
                            background: "none",
                            border: "none",
                            cursor: "pointer",
                            padding: "4px 6px",
                            borderRadius: 4,
                            color: "rgba(0,0,0,0.15)",
                            display: "inline-flex",
                            transition: "all 0.15s ease",
                          }}
                          onMouseEnter={(e) => {
                            e.currentTarget.style.color = "#cc3333";
                            e.currentTarget.style.background = "rgba(204,51,51,0.05)";
                          }}
                          onMouseLeave={(e) => {
                            e.currentTarget.style.color = "rgba(0,0,0,0.15)";
                            e.currentTarget.style.background = "none";
                          }}
                        >
                          <Trash2 size={12} />
                        </button>
                      </div>
                    </li>
                  );
                })}
              </ul>
            </div>
          )}

          {/* Empty state */}
          {history.length === 0 && (
            <div style={{ marginTop: "4rem", textAlign: "center" }}>
              <Search size={22} style={{ color: "rgba(0,0,0,0.15)", margin: "0 auto 14px", display: "block" }} />
              <p style={{ fontFamily: "'Space Grotesk', sans-serif", fontSize: "0.85rem", color: "rgba(0,0,0,0.3)", fontWeight: 300 }}>
                Search to generate your first report
              </p>
            </div>
          )}
        </div>
      </section>

      <SourcesModal
        isOpen={sourcesOpen}
        onClose={() => setSourcesOpen(false)}
        sources={activeSources}
        companyName={activeCompany}
      />
    </main>
  );
}
