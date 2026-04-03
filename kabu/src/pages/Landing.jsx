import React, { useEffect, useState, useCallback, useRef, useMemo, useContext } from "react";
import { gsap } from "gsap";
import { Download, Trash2, BookOpen, ArrowUpRight, Search } from "lucide-react";
import SearchBar from "@/components/home/SearchBar";
import { useLocation, useNavigate } from "react-router-dom";
import { useCircleTransition } from "@/components/CircleTransition";
import { deleteJob, getStatus, buildDownloadUrl } from "@/api/backend";
import SourcesModal from "@/components/report/SourcesModal";
import KineticType from "@/components/KineticType";
import { SplashContext } from "@/components/SplashScreen";

const RADIUS = 150;
const WEIGHT_FROM = 300;
const WEIGHT_TO = 700;
const TYPE_LINE_OPACITY = 0.006;

export default function Landing() {
  const [ready, setReady] = useState(false);
  const { splashDone } = useContext(SplashContext);
  const isAnimating = useRef(true);
  const proximityChars = useRef([]);
  const proximityCleanupRef = useRef(null);
  const setupDoneRef = useRef(false);
  const location = useLocation();
  const nav = useNavigate();
  const { navigateWithReveal } = useCircleTransition();
  const autoOpenContent = useRef(false);

  // hero refs
  const typeRef = useRef(null);
  const heroRef = useRef(null);
  const wordsRef = useRef([]);
  const thickWordsRef = useRef([]);
  const statNumsRef = useRef([]);
  const descRef = useRef(null);
  // content refs
  const contentRef = useRef(null);
  const backRef = useRef(null);
  const contentItemsRef = useRef([]);
  const researchCharsRef = useRef([]);
  const subtitleWordsRef = useRef([]);

  // content state (from Home)
  const [history, setHistory] = useState([]);
  const [sourcesOpen, setSourcesOpen] = useState(false);
  const [activeSources, setActiveSources] = useState([]);
  const [activeCompany, setActiveCompany] = useState("");
  const [hoveredItem, setHoveredItem] = useState(null);
  const [generating, setGenerating] = useState(null);

  // load history
  useEffect(() => {
    try {
      const raw = localStorage.getItem("reports_history");
      if (raw) {
        const parsed = JSON.parse(raw);
        if (Array.isArray(parsed)) {
          const valid = parsed.filter((h) => h && h.jobId && (h.companyName || h.ticker));
          // Deduplicate by jobId (keep first/newest occurrence)
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

  // wait for fonts
  useEffect(() => {
    document.fonts.ready.then(() => setReady(true));
  }, []);

  // ---- variable proximity helpers ----
  const splitForProximity = useCallback((el) => {
    if (!el) return;
    const text = el.textContent.trim();
    el.innerHTML = "";
    text.split("").forEach((ch) => {
      if (ch === " ") {
        el.appendChild(document.createTextNode(" "));
      } else {
        const span = document.createElement("span");
        span.textContent = ch;
        span.style.display = "inline-block";
        span.style.fontVariationSettings = `'wght' ${WEIGHT_FROM}`;
        el.appendChild(span);
        proximityChars.current.push(span);
      }
    });
  }, []);

  // Word-aware version — keeps words intact so line breaks only happen between words
  const splitForProximityByWord = useCallback((el) => {
    if (!el) return;
    const text = el.textContent.trim();
    el.innerHTML = "";
    text.split(" ").forEach((word, i) => {
      if (i > 0) el.appendChild(document.createTextNode(" "));
      const wordWrap = document.createElement("span");
      wordWrap.style.whiteSpace = "nowrap";
      word.split("").forEach((ch) => {
        const span = document.createElement("span");
        span.textContent = ch;
        span.style.display = "inline-block";
        span.style.fontVariationSettings = `'wght' ${WEIGHT_FROM}`;
        wordWrap.appendChild(span);
        proximityChars.current.push(span);
      });
      el.appendChild(wordWrap);
    });
  }, []);

  const startProximityLoop = useCallback(() => {
    let mouseX = 0, mouseY = 0;
    let lastX = null, lastY = null;
    let active = true;
    const onMove = (e) => { mouseX = e.clientX; mouseY = e.clientY; };
    document.addEventListener("mousemove", onMove);
    const update = () => {
      if (!active) return;
      if (lastX === mouseX && lastY === mouseY) { requestAnimationFrame(update); return; }
      lastX = mouseX; lastY = mouseY;
      const chars = proximityChars.current;
      for (let i = 0; i < chars.length; i++) {
        const span = chars[i];
        const rect = span.getBoundingClientRect();
        if (rect.width === 0) continue;
        const cx = rect.left + rect.width / 2;
        const cy = rect.top + rect.height / 2;
        const dist = Math.hypot(mouseX - cx, mouseY - cy);
        const weight = dist >= RADIUS ? WEIGHT_FROM : WEIGHT_FROM + (WEIGHT_TO - WEIGHT_FROM) * (1 - dist / RADIUS);
        span.style.fontVariationSettings = `'wght' ${Math.round(weight)}`;
      }
      requestAnimationFrame(update);
    };
    requestAnimationFrame(update);
    proximityCleanupRef.current = () => { active = false; document.removeEventListener("mousemove", onMove); };
  }, []);

  // cleanup proximity on unmount
  useEffect(() => {
    return () => { if (proximityCleanupRef.current) proximityCleanupRef.current(); };
  }, []);

  // ---- setup: split words for proximity + show at final state ----
  // Runs during splash so everything is visible when splash dissolves
  useEffect(() => {
    if (!ready || setupDoneRef.current) return;
    setupDoneRef.current = true;

    const words = wordsRef.current.filter(Boolean);
    const thickWords = thickWordsRef.current.filter(Boolean);
    const statNums = statNumsRef.current.filter(Boolean);
    const desc = descRef.current;
    const typeLines = typeRef.current?.getLines() || [];

    // split hero words for proximity
    words.forEach((word) => {
      const text = word.textContent;
      word.innerHTML = "";
      text.split("").forEach((ch) => {
        const span = document.createElement("span");
        span.textContent = ch;
        span.style.display = "inline-block";
        span.style.fontVariationSettings = `'wght' ${WEIGHT_FROM}`;
        word.appendChild(span);
        proximityChars.current.push(span);
      });
    });

    // split description (word-aware to prevent mid-word breaks) + stat labels for proximity
    splitForProximityByWord(desc);
    document.querySelectorAll(".hero__stat-label").forEach((l) => splitForProximity(l));

    // Show everything at final state — no intro animation
    gsap.set(typeLines, { opacity: TYPE_LINE_OPACITY });
    gsap.set(thickWords, { webkitTextStrokeColor: "#de5f40" });

    // Initialize stat numbers for count-up
    statNums.forEach((n) => {
      if (n.dataset.counter === "1") n.textContent = "0+";
      else if (n.dataset.counter === "2") n.textContent = "0+";
      else n.textContent = "<0 min";
    });
  }, [ready, splitForProximity, splitForProximityByWord]);

  // ---- after splash: only count up numbers slowly ----
  useEffect(() => {
    if (!ready || !splashDone) return;

    const statNums = statNumsRef.current.filter(Boolean);

    // Allow interaction immediately
    isAnimating.current = false;
    startProximityLoop();

    // Count up numbers slowly — the only animation on the page
    const c1 = { v: 0 };
    const t1 = gsap.to(c1, {
      v: 3900, duration: 1.5, ease: "power2.out", delay: 0.15,
      onUpdate: () => { statNums[0].textContent = Math.floor(c1.v).toLocaleString() + "+"; },
    });
    const c2 = { v: 0 };
    const t2 = gsap.to(c2, {
      v: 40, duration: 1.25, ease: "power2.out", delay: 0.15,
      onUpdate: () => { statNums[1].textContent = Math.floor(c2.v) + "+"; },
    });
    const c3 = { v: 0 };
    const t3 = gsap.to(c3, {
      v: 4, duration: 1, ease: "power2.out", delay: 0.15,
      onUpdate: () => { statNums[2].textContent = "<" + Math.ceil(c3.v) + " min"; },
    });

    // After count-up, split stat nums for proximity weight effect
    const done = gsap.delayedCall(1.9, () => {
      statNums.forEach((n) => splitForProximity(n));
    });

    return () => { t1.kill(); t2.kill(); t3.kill(); done.kill(); };
  }, [ready, splashDone, splitForProximity, startProximityLoop]);

  // ---- register content section chars for proximity weight effect ----
  const contentCharsRegistered = useRef(false);
  useEffect(() => {
    if (!ready || contentCharsRegistered.current) return;
    contentCharsRegistered.current = true;

    // Research title chars
    researchCharsRef.current.filter(Boolean).forEach((el) => {
      proximityChars.current.push(el);
    });

    // Subtitle chars (character spans inside each word span)
    subtitleWordsRef.current.filter(Boolean).forEach((wordEl) => {
      Array.from(wordEl.children).forEach((span) => {
        proximityChars.current.push(span);
      });
    });
  }, [ready]);

  // ---- detect openContent from navigation state ----
  useEffect(() => {
    if (location.state?.openContent) {
      autoOpenContent.current = true;
      // Clear React Router state so refresh doesn't re-trigger
      nav(".", { replace: true, state: {} });
    }
  }, [location, nav]);

  // ---- auto-open content when returning from Query ----
  useEffect(() => {
    if (!ready || !splashDone || !autoOpenContent.current) return;
    autoOpenContent.current = false;

    const hero = heroRef.current;
    const back = backRef.current;
    const content = contentRef.current;
    const items = contentItemsRef.current.filter(Boolean);

    // Set kinetic type to its "transitioned in" final state (scale 2.7, rotate -90, lines off-screen)
    const typeContainer = typeRef.current?.getContainer();
    const typeLines = typeRef.current?.getLines() || [];
    if (typeContainer) gsap.set(typeContainer, { scale: 2.7, rotate: -90 });
    gsap.set(typeLines, { x: "-200%", opacity: 0 });

    // Immediately show content, hide hero
    gsap.set(hero, { opacity: 0, y: "-5%", pointerEvents: "none", visibility: "hidden" });
    gsap.set(content, { opacity: 1, pointerEvents: "auto" });
    gsap.set(back, { opacity: 1, pointerEvents: "auto" });
    gsap.set(items, { opacity: 1, y: "0%" });
    gsap.set(researchCharsRef.current.filter(Boolean), { y: "0%" });
    gsap.set(subtitleWordsRef.current.filter(Boolean), { y: "0%" });

    isAnimating.current = false;
  }, [ready, splashDone]);

  // ---- openSite: Enter Site → Content (kinetic type transition) ----
  const openSite = useCallback(() => {
    if (isAnimating.current) return;
    isAnimating.current = true;

    const tIn = typeRef.current?.transitionIn();
    if (!tIn) { isAnimating.current = false; return; }
    const hero = heroRef.current;
    const back = backRef.current;
    const content = contentRef.current;
    const items = contentItemsRef.current.filter(Boolean);

    const tl = gsap.timeline({ onComplete: () => { isAnimating.current = false; } });

    tl.addLabel("start", 0)
      .addLabel("typeTransition", 0.3)
      .addLabel("contentOpening", tIn.totalDuration() * 0.75 + 0.3)

      // hero fades out and moves up
      .to(hero, { duration: 0.8, ease: "power2.inOut", opacity: 0, y: "-5%" }, "start")

      // kinetic type scales 2.7x, rotates -90°, lines sweep
      .add(tIn.play(), "typeTransition")

      // show content section
      .add(() => {
        gsap.set(hero, { pointerEvents: "none", visibility: "hidden" });
        gsap.set(content, { opacity: 1, pointerEvents: "auto" });
        gsap.set(back, { pointerEvents: "auto" });
      }, "contentOpening")

      // back button fades in
      .to(back, { duration: 0.7, opacity: 1 }, "contentOpening")

      // content items stagger in from below
      .set(items, { opacity: 0, y: "40%" }, "contentOpening")
      .to(items, { duration: 1.2, ease: "expo", opacity: 1, y: "0%", stagger: 0.07 }, "contentOpening")

      // splash-style character roll-up for "Research"
      .set(researchCharsRef.current.filter(Boolean), { y: "120%" }, "contentOpening")
      .to(researchCharsRef.current.filter(Boolean), {
        duration: 0.9,
        ease: "power4.out",
        y: "0%",
        stagger: 0.04,
      }, "contentOpening+=0.05")

      // splash-style word roll-up for subtitle
      .set(subtitleWordsRef.current.filter(Boolean), { y: "120%" }, "contentOpening")
      .to(subtitleWordsRef.current.filter(Boolean), {
        duration: 0.7,
        ease: "power3.out",
        y: "0%",
        stagger: 0.03,
      }, "contentOpening+=0.35");
  }, []);

  // ---- closeSite: Back → Hero (reverse kinetic type transition) ----
  const closeSite = useCallback(() => {
    if (isAnimating.current) return;
    isAnimating.current = true;

    const tOut = typeRef.current?.transitionOut();
    if (!tOut) { isAnimating.current = false; return; }
    const hero = heroRef.current;
    const back = backRef.current;
    const content = contentRef.current;
    const items = contentItemsRef.current.filter(Boolean);

    const tl = gsap.timeline({ onComplete: () => { isAnimating.current = false; } });

    tl.addLabel("start", 0)
      .addLabel("typeTransition", 0.5)
      .addLabel("showHero", tOut.totalDuration() * 0.7 + 0.5)

      // back button fades out
      .to(back, { duration: 0.7, ease: "power1", opacity: 0 }, "start")

      // subtitle words slide down (reverse)
      .to(subtitleWordsRef.current.filter(Boolean), {
        duration: 0.4,
        ease: "power4.in",
        y: "120%",
        stagger: { each: 0.015, from: "end" },
      }, "start")

      // research chars slide down (reverse)
      .to(researchCharsRef.current.filter(Boolean), {
        duration: 0.5,
        ease: "power4.in",
        y: "120%",
        stagger: { each: 0.02, from: "end" },
      }, "start+=0.05")

      // content items stagger out upward
      .to(items, { duration: 0.8, ease: "power4.in", opacity: 0, y: "40%", stagger: -0.04 }, "start")

      // hide content
      .add(() => {
        gsap.set(back, { pointerEvents: "none" });
        gsap.set(content, { opacity: 0, pointerEvents: "none" });
      })

      // reverse kinetic type transition
      .add(tOut.play(), "typeTransition")

      // show hero
      .add(() => {
        gsap.set(hero, { visibility: "visible", pointerEvents: "auto" });
      }, "showHero")
      .to(hero, { duration: 1, ease: "power3.inOut", opacity: 1, y: "0%" }, "showHero");
  }, []);

  // ---- content helpers ----
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

  /* ── Memoize hero subtree — isolates from content-state re-renders
       so splitForProximity DOM mutations survive reconciliation ── */
  const heroElement = useMemo(() => (
    <section
      ref={heroRef}
      style={{
        position: "relative",
        zIndex: 10,
        minHeight: "100%",
        display: "flex",
        alignItems: "center",
        paddingTop: "clamp(2rem, 4vh, 4rem)",
        paddingBottom: "clamp(1.5rem, 3vh, 3rem)",
      }}
    >
      {/* Top nav */}
      <div style={{
        position: "absolute", top: 0, left: 0, right: 0,
        display: "flex", justifyContent: "flex-end", alignItems: "center",
        padding: "clamp(1.5rem, 3vh, 2.5rem) clamp(2rem, 5vw, 6rem)",
        zIndex: 20, fontFamily: "'Space Grotesk', sans-serif",
      }}>
        <span style={{ fontSize: "0.5rem", color: "#0a0a0a", opacity: 0.1, letterSpacing: "0.25em", textTransform: "uppercase" }}>
          v1.0
        </span>
      </div>

      <div className="hero-layout" style={{ maxWidth: 1400, width: "100%", margin: "0 auto", padding: "0 clamp(2rem, 5vw, 6rem)", display: "grid", gridTemplateColumns: "3fr 2fr", gap: "clamp(3rem, 6vw, 7rem)", alignItems: "center" }}>
        {/* Left — Heading */}
        <div>
        {/* Eyebrow */}
        <div style={{
          fontFamily: "'Space Grotesk', sans-serif",
          fontSize: "0.6rem",
          letterSpacing: "0.3em",
          textTransform: "uppercase",
          color: "rgba(0,0,0,0.25)",
          fontWeight: 500,
          marginBottom: "clamp(1rem, 2vh, 1.8rem)",
          display: "flex",
          alignItems: "center",
          gap: "0.5rem",
        }}>
          <span className="hero__status-dot" style={{ width: 5, height: 5, borderRadius: "50%", background: "var(--color-accent, #de5f40)", flexShrink: 0 }} />
          AI-Powered Research Platform
        </div>

        {/* Title with accent bar */}
        <div style={{ display: "flex", gap: "clamp(1.2rem, 2.5vw, 2rem)" }}>
          <div className="hero__accent-bar" style={{
            width: 2,
            background: "var(--color-accent, #de5f40)",
            borderRadius: 1,
            flexShrink: 0,
            alignSelf: "stretch",
          }} />
          <h1
            style={{
              fontFamily: "'Space Grotesk', sans-serif",
              fontSize: "clamp(2.5rem, 5.5vw, 5.5rem)",
              fontWeight: 300,
              lineHeight: 1.05,
              letterSpacing: "-0.04em",
              margin: 0,
              color: "#0a0a0a",
            }}
          >
            <span className="hero__word" style={{ display: "inline-block", overflow: "hidden", verticalAlign: "bottom", padding: "0.06em 0.04em 0.08em" }}>
              <span ref={(el) => { wordsRef.current[0] = el; }} className="hero__word-inner" style={{ display: "inline-block" }}>Built</span>
            </span>{" "}
            <span className="hero__word" style={{ display: "inline-block", overflow: "hidden", verticalAlign: "bottom", padding: "0.06em 0.04em 0.08em" }}>
              <span ref={(el) => { wordsRef.current[1] = el; }} className="hero__word-inner" style={{ display: "inline-block" }}>for</span>
            </span>{" "}
            <span className="hero__accent" style={{ cursor: "default" }}>
              <span className="hero__word" style={{ display: "inline-block", overflow: "hidden", verticalAlign: "bottom", padding: "0.06em 0.04em 0.08em" }}>
                <span
                  ref={(el) => { wordsRef.current[2] = el; thickWordsRef.current[0] = el; }}
                  className="hero__word-inner hero__word-inner--thick"
                  style={{ display: "inline-block", WebkitTextStroke: "4px transparent", paintOrder: "stroke fill" }}
                >
                  Japanese
                </span>
              </span>{" "}
              <span className="hero__word" style={{ display: "inline-block", overflow: "hidden", verticalAlign: "bottom", padding: "0.06em 0.04em 0.08em" }}>
                <span
                  ref={(el) => { wordsRef.current[3] = el; thickWordsRef.current[1] = el; }}
                  className="hero__word-inner hero__word-inner--thick"
                  style={{ display: "inline-block", WebkitTextStroke: "4px transparent", paintOrder: "stroke fill" }}
                >
                  Market
                </span>
              </span>
            </span>
            <br />
            <span className="hero__word" style={{ display: "inline-block", overflow: "hidden", verticalAlign: "bottom", padding: "0.06em 0.04em 0.08em" }}>
              <span ref={(el) => { wordsRef.current[4] = el; }} className="hero__word-inner" style={{ display: "inline-block" }}>Research.</span>
            </span>
          </h1>
        </div>
        </div>

        {/* Right — Stats, Description, CTA */}
        <div>
        {/* Stats — vertical editorial layout */}
        <div className="hero__stats-wrap" style={{ display: "flex", flexDirection: "column", gap: "clamp(1.4rem, 2.8vh, 2rem)", marginBottom: "clamp(2rem, 4vh, 3rem)" }}>
          {[
            { label: "Listed Companies", counter: "1" },
            { label: "Data Sources", counter: "2" },
            { label: "Report Generation", counter: "3" },
          ].map((s, i) => (
            <div
              key={s.label}
              className="hero__stat"
              style={{ display: "flex", alignItems: "baseline", gap: "1rem" }}
            >
              <span
                ref={(el) => { statNumsRef.current[i] = el; }}
                data-counter={s.counter}
                className="hero__stat-number"
                style={{
                  fontFamily: "'Space Grotesk', sans-serif",
                  fontSize: "clamp(1.6rem, 2.8vw, 2.2rem)",
                  fontWeight: 300,
                  color: "#0a0a0a",
                  letterSpacing: "-0.03em",
                  fontVariantNumeric: "tabular-nums",
                  minWidth: "clamp(5rem, 8vw, 7rem)",
                }}
              >
                0
              </span>
              <div style={{
                width: 24,
                height: 1,
                background: "var(--color-accent, #de5f40)",
                borderRadius: 1,
                opacity: 0.3,
                flexShrink: 0,
              }} />
              <span
                className="hero__stat-label"
                style={{
                  fontFamily: "'Space Grotesk', sans-serif",
                  fontSize: "0.72rem",
                  textTransform: "uppercase",
                  letterSpacing: "0.15em",
                  color: "rgba(0,0,0,0.55)",
                  fontWeight: 500,
                }}
              >
                {s.label}
              </span>
            </div>
          ))}
        </div>

        {/* Description */}
        <p
          ref={descRef}
          style={{
            fontFamily: "'Space Grotesk', sans-serif",
            fontSize: "clamp(0.85rem, 1vw, 1rem)",
            lineHeight: 1.7,
            color: "rgba(0,0,0,0.4)",
            margin: "0 0 clamp(1.5rem, 3vh, 2rem)",
            maxWidth: 480,
            fontWeight: 300,
            cursor: "default",
            transition: "color 0.4s cubic-bezier(0.16, 1, 0.3, 1)",
          }}
          onMouseEnter={(e) => { e.currentTarget.style.color = "rgba(0,0,0,0.7)"; }}
          onMouseLeave={(e) => { e.currentTarget.style.color = "rgba(0,0,0,0.4)"; }}
        >
          Generate institutional-grade equity research reports for any company listed on the Tokyo Stock Exchange. Our AI analyzes financials, valuations, peer comparisons, and market data — then delivers a comprehensive report in under four minutes.
        </p>

        {/* CTA — outlined, accent fill on hover */}
        <button
          type="button"
          className="hero-cta"
          onClick={openSite}
          style={{
            display: "inline-flex",
            alignItems: "center",
            gap: 0,
            background: "transparent",
            border: "1.5px solid var(--color-accent, #de5f40)",
            color: "#0a0a0a",
            fontFamily: "'Space Grotesk', sans-serif",
            fontSize: "0.65rem",
            fontWeight: 500,
            letterSpacing: "0.22em",
            textTransform: "uppercase",
            padding: "clamp(1rem, 1.8vh, 1.2rem) clamp(2.2rem, 4.5vw, 3.2rem)",
            cursor: "pointer",
            borderRadius: 8,
            position: "relative",
            overflow: "hidden",
            marginTop: "clamp(0.5rem, 1vh, 1rem)",
          }}
        >
          <span style={{ position: "relative", zIndex: 1 }}>Get Started</span>
          <span
            className="hero-cta__icon"
            style={{
              position: "relative",
              zIndex: 1,
              display: "inline-block",
              fontSize: "1rem",
              maxWidth: 0,
              opacity: 0,
              overflow: "hidden",
              transition: "max-width 0.5s cubic-bezier(0.16,1,0.3,1), opacity 0.5s cubic-bezier(0.16,1,0.3,1), margin 0.5s cubic-bezier(0.16,1,0.3,1)",
            }}
          >
            &rarr;
          </span>
        </button>
        </div>
      </div>
    </section>
  ), [openSite]);

  // loading state
  if (!ready) {
    return (
      <div style={{ position: "fixed", inset: 0, background: "#fff", display: "flex", alignItems: "center", justifyContent: "center" }}>
        <div style={{ width: 60, height: 60, borderRadius: "50%", opacity: 0.4, background: "var(--color-accent, #de5f40)", animation: "pulse 0.7s linear infinite alternate" }} />
      </div>
    );
  }

  return (
    <main className="landing-main" style={{ position: "relative", overflow: "hidden", width: "100%", background: "radial-gradient(ellipse at 20% 50%, rgba(222,95,64,0.025) 0%, transparent 65%), #fff" }}>
      <KineticType ref={typeRef} />

      {/* Hero — rendered from useMemo to isolate from content-state re-renders */}
      {heroElement}

      {/* ════════════════════════════════════════════════
          CONTENT SECTION — search, recent reports, nav
          Initially hidden; revealed by openSite()
          ════════════════════════════════════════════════ */}
      <section
        ref={contentRef}
        style={{
          position: "fixed",
          top: 0,
          left: 0,
          width: "100%",
          height: "100%",
          opacity: 0,
          pointerEvents: "none",
          zIndex: 10,
          display: "flex",
          justifyContent: "center",
          padding: "clamp(1rem, 2vw, 2rem)",
          paddingTop: "clamp(4rem, 10vh, 8rem)",
          paddingBottom: "clamp(2rem, 4vh, 4rem)",
          overflowY: "auto",
          WebkitOverflowScrolling: "touch",
        }}
      >
        {/* Back button — uses CSS .back-btn for hover/focus */}
        <button
          ref={backRef}
          type="button"
          className="back-btn"
          onClick={closeSite}
        >
          <svg viewBox="0 0 50 9" width="100%">
            <path d="M0 4.5l5-3M0 4.5l5 3M50 4.5h-77" fill="none" />
          </svg>
        </button>

        <div style={{ width: "100%", maxWidth: 640 }}>
          {/* Title */}
          <h2
            ref={(el) => { contentItemsRef.current[0] = el; }}
            style={{
              fontFamily: "'Space Grotesk', sans-serif",
              fontSize: "clamp(3.5rem, 8vw, 6rem)",
              fontWeight: 300,
              letterSpacing: "-0.04em",
              margin: 0,
              color: "#0a0a0a",
              textAlign: "center",
              lineHeight: 1.05,
              cursor: "default",
              transition: "color 0.4s cubic-bezier(0.16, 1, 0.3, 1)",
            }}
            onMouseEnter={(e) => { e.currentTarget.style.color = "var(--color-accent, #de5f40)"; }}
            onMouseLeave={(e) => { e.currentTarget.style.color = "#0a0a0a"; }}
          >
            {"Research".split("").map((ch, i) => (
              <span key={i} style={{ display: "inline-block", overflow: "hidden", verticalAlign: "bottom", padding: "0 0 0.08em" }}>
                <span
                  ref={(el) => { researchCharsRef.current[i] = el; }}
                  style={{ display: "inline-block", fontVariationSettings: `'wght' ${WEIGHT_FROM}` }}
                >
                  {ch}
                </span>
              </span>
            ))}
          </h2>

          {/* Accent line */}
          <div
            ref={(el) => { contentItemsRef.current[1] = el; }}
            style={{
              width: 40,
              height: 2,
              background: "var(--color-accent, #de5f40)",
              margin: "2rem auto",
              borderRadius: 1,
            }}
          />

          {/* Subtitle */}
          <p
            ref={(el) => { contentItemsRef.current[2] = el; }}
            style={{
              textAlign: "center",
              fontFamily: "'Space Grotesk', sans-serif",
              fontSize: "1.05rem",
              color: "rgba(0,0,0,0.35)",
              fontWeight: 300,
              margin: "0 auto clamp(1.5rem, 4vh, 3.5rem)",
              maxWidth: 560,
              lineHeight: 1.8,
              letterSpacing: "0.01em",
            }}
          >
            {"Institutional-grade research on every listed company in Japan — powered by AI".split(" ").map((word, i) => (
              <React.Fragment key={i}>
                <span style={{ display: "inline-block", overflow: "hidden", verticalAlign: "top", padding: "0 0 0.15em" }}>
                  <span
                    ref={(el) => { subtitleWordsRef.current[i] = el; }}
                    style={{ display: "inline-block", whiteSpace: "nowrap" }}
                  >
                    {word.split("").map((ch, j) => (
                      <span
                        key={j}
                        style={{ display: "inline-block", fontVariationSettings: `'wght' ${WEIGHT_FROM}` }}
                      >
                        {ch}
                      </span>
                    ))}
                  </span>
                </span>{" "}
              </React.Fragment>
            ))}
          </p>

          {/* Search Bar */}
          <div ref={(el) => { contentItemsRef.current[3] = el; }} style={{ position: "relative", zIndex: 20 }}>
            <SearchBar />
          </div>

          {/* Query nav */}
          <div
            ref={(el) => { contentItemsRef.current[4] = el; }}
            style={{ display: "flex", justifyContent: "center", marginTop: "1.5rem", position: "relative", zIndex: 1 }}
          >
            <button
              type="button"
              onClick={(e) => navigateWithReveal("/Query", e)}
              style={{
                background: "none",
                border: "none",
                fontFamily: "'Space Grotesk', sans-serif",
                fontSize: "0.6rem",
                fontWeight: 500,
                letterSpacing: "0.18em",
                textTransform: "uppercase",
                color: "rgba(0,0,0,0.22)",
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
              Query Mode
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
                fontFamily: "'Space Grotesk', sans-serif",
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
              <div style={{ position: "absolute", top: 0, left: 0, height: "100%", width: `${generating.progress}%`, background: "linear-gradient(90deg, rgba(222,95,64,0.03) 0%, rgba(222,95,64,0.06) 100%)", transition: "width 1.2s cubic-bezier(0.16,1,0.3,1)", borderRadius: 14 }} />
              {/* Shimmer overlay */}
              <div style={{ position: "absolute", top: 0, left: 0, width: "100%", height: "100%", background: "linear-gradient(90deg, transparent 0%, rgba(222,95,64,0.04) 50%, transparent 100%)", backgroundSize: "200% 100%", animation: "shimmer 2s ease-in-out infinite", borderRadius: 14 }} />
              <style>{`@keyframes shimmer { 0% { background-position: 200% 0; } 100% { background-position: -200% 0; } }`}</style>
              {/* Content */}
              <div style={{ position: "relative", zIndex: 1, display: "flex", alignItems: "center", gap: 14 }}>
                {/* Pulsing dot */}
                <div style={{ position: "relative", width: 10, height: 10, flexShrink: 0 }}>
                  <div style={{ width: 10, height: 10, borderRadius: "50%", background: "#de5f40", animation: "pulse-dot 2s ease-in-out infinite" }} />
                  <div style={{ position: "absolute", top: -3, left: -3, width: 16, height: 16, borderRadius: "50%", border: "1.5px solid rgba(222,95,64,0.3)", animation: "pulse-ring 2s ease-in-out infinite" }} />
                  <style>{`
                    @keyframes pulse-dot { 0%, 100% { opacity: 1; transform: scale(1); } 50% { opacity: 0.6; transform: scale(0.85); } }
                    @keyframes pulse-ring { 0%, 100% { opacity: 0.4; transform: scale(1); } 50% { opacity: 0; transform: scale(1.8); } }
                  `}</style>
                </div>
                {/* Text */}
                <div style={{ flex: 1, minWidth: 0 }}>
                  <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                    <span style={{ fontSize: "0.8rem", fontWeight: 500, color: "#0a0a0a", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                      {generating.companyName || generating.ticker}
                    </span>
                    <span style={{ fontSize: "0.65rem", fontWeight: 500, color: "var(--color-accent, #de5f40)", letterSpacing: "0.05em", flexShrink: 0 }}>
                      {generating.ticker}
                    </span>
                  </div>
                  <div style={{ display: "flex", alignItems: "center", gap: 8, marginTop: 3 }}>
                    <span style={{ fontSize: "0.65rem", fontWeight: 500, color: "rgba(222,95,64,0.7)", letterSpacing: "0.08em", textTransform: "uppercase" }}>
                      Generating
                    </span>
                    <span style={{ fontSize: "0.65rem", fontWeight: 400, color: "rgba(0,0,0,0.3)" }}>
                      {generating.step} — {Math.round(generating.progress)}%
                    </span>
                    {generating.eta != null && generating.eta > 0 && (
                      <span style={{ fontSize: "0.65rem", fontWeight: 400, color: "rgba(0,0,0,0.25)", fontVariantNumeric: "tabular-nums" }}>
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
              <div style={{ position: "absolute", bottom: 0, left: 0, height: 2, width: `${generating.progress}%`, background: "linear-gradient(90deg, #de5f40, #e8825e)", borderRadius: "0 0 14px 14px", transition: "width 1.2s cubic-bezier(0.16,1,0.3,1)" }} />
            </button>
          )}

          {/* Recent reports */}
          {history.length > 0 && (
            <div ref={(el) => { contentItemsRef.current[5] = el; }} style={{ marginTop: generating ? "1.5rem" : "4rem" }}>
              <span
                style={{
                  display: "block",
                  fontFamily: "'Space Grotesk', sans-serif",
                  fontSize: "0.55rem",
                  textTransform: "uppercase",
                  letterSpacing: "0.3em",
                  color: "rgba(0,0,0,0.3)",
                  fontWeight: 500,
                  marginBottom: "1.2rem",
                }}
              >
                Recent</span>
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
          {history.length === 0 && !generating && (
            <div ref={(el) => { contentItemsRef.current[5] = el; }} style={{ marginTop: "5rem", textAlign: "center" }}>
              <div style={{
                width: 48,
                height: 48,
                borderRadius: 14,
                background: "rgba(0,0,0,0.02)",
                border: "1px solid rgba(0,0,0,0.04)",
                display: "flex",
                alignItems: "center",
                justifyContent: "center",
                margin: "0 auto 1.2rem",
              }}>
                <Search size={18} style={{ color: "rgba(0,0,0,0.12)" }} />
              </div>
              <p style={{ fontFamily: "'Space Grotesk', sans-serif", fontSize: "0.85rem", color: "rgba(0,0,0,0.2)", fontWeight: 300 }}>
                Enter a company name or ticker to generate your first report
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
