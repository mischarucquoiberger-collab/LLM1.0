import React, { useState, useEffect, useRef, useCallback, useMemo } from "react";
import { motion, AnimatePresence } from "framer-motion";
import { ArrowUp } from "lucide-react";
import NumberFlow, { useCanAnimate } from "@number-flow/react";
import { fetchQuote, fetchPriceHistory } from "@/api/backend";

const POLL_INTERVAL = 5000;

const RANGES = [
  { key: "1D", days: 1, interval: "5m", label: "1D" },
  { key: "5D", days: 5, interval: "15m", label: "5D" },
  { key: "1M", days: 30, interval: "30m", label: "1M" },
  { key: "6M", days: 180, interval: "60m", label: "6M" },
  { key: "YTD", days: 0, interval: "1d", label: "YTD" },
  { key: "1Y", days: 365, interval: "1d", label: "1Y" },
  { key: "5Y", days: 1825, interval: "1d", label: "5Y" },
];

function getYTDDays() {
  const now = new Date();
  const start = new Date(now.getFullYear(), 0, 1);
  return Math.ceil((now - start) / 86400000);
}

function isTSEOpen() {
  const now = new Date();
  const day = now.getUTCDay();
  if (day === 0 || day === 6) return false;
  const jstHour = (now.getUTCHours() + 9) % 24;
  const jstMin = now.getUTCMinutes();
  const t = jstHour * 60 + jstMin;
  return (t >= 540 && t <= 690) || (t >= 750 && t < 900);
}

/* ── SVG Chart with gradient fill, hover crosshair ─── */
const CHART_H = 180;
const PAD = { top: 12, right: 12, bottom: 28, left: 12 };
const VW = 500;

function PriceChart({ data, color, referencePrice }) {
  const [hover, setHover] = useState(null);
  const svgRef = useRef(null);

  const closes = useMemo(() => data.map(d => Number(d.close)), [data]);

  const { yMin, yMax } = useMemo(() => {
    const mn = Math.min(...closes);
    const mx = Math.max(...closes);
    const pad = (mx - mn) * 0.1 || mx * 0.02;
    return { yMin: mn - pad, yMax: mx + pad };
  }, [closes]);

  const plotW = VW - PAD.left - PAD.right;
  const plotH = CHART_H - PAD.top - PAD.bottom;

  const points = useMemo(() =>
    closes.map((v, i) => ({
      x: PAD.left + (i / Math.max(closes.length - 1, 1)) * plotW,
      y: PAD.top + plotH - ((v - yMin) / (yMax - yMin || 1)) * plotH,
    })),
    [closes, plotW, plotH, yMin, yMax]
  );

  const linePath = useMemo(() => {
    if (points.length < 2) return "";
    const n = points.length;
    let d = `M ${points[0].x},${points[0].y}`;
    for (let i = 0; i < n - 1; i++) {
      const p0 = points[Math.max(i - 1, 0)];
      const p1 = points[i];
      const p2 = points[i + 1];
      const p3 = points[Math.min(i + 2, n - 1)];
      const t = 0.35;
      d += ` C ${p1.x + (p2.x - p0.x) * t / 3},${p1.y + (p2.y - p0.y) * t / 3} ${p2.x - (p3.x - p1.x) * t / 3},${p2.y - (p3.y - p1.y) * t / 3} ${p2.x},${p2.y}`;
    }
    return d;
  }, [points]);

  const areaPath = useMemo(() => {
    if (!linePath || points.length === 0) return "";
    const bottom = PAD.top + plotH;
    return `${linePath} L ${points[points.length - 1].x},${bottom} L ${points[0].x},${bottom} Z`;
  }, [linePath, points, plotH]);

  const refY = useMemo(() => {
    if (referencePrice == null) return null;
    const pc = Number(referencePrice);
    if (pc < yMin || pc > yMax) return null;
    return PAD.top + plotH - ((pc - yMin) / (yMax - yMin || 1)) * plotH;
  }, [referencePrice, yMin, yMax, plotH]);

  const labels = useMemo(() => {
    if (data.length < 2) return [];
    // Detect intraday data (dates contain HH:MM)
    const isIntraday = (data[0].date || "").includes(":");
    const count = Math.min(5, data.length);
    const step = Math.max(Math.floor((data.length - 1) / (count - 1)), 1);
    const result = [];
    for (let i = 0; i < data.length; i += step) {
      const raw = data[i].date || "";
      let short;
      if (isIntraday) {
        // Show "HH:MM" for intraday, or "MM-DD HH:MM" for multi-day intraday
        const parts = raw.split(" ");
        const time = parts[1] || "";
        const date = (parts[0] || "").replace(/^\d{4}-/, "");
        // For multi-day (5D), show date on first point of each day
        const prevDate = i > 0 ? (data[i - step]?.date || "").split(" ")[0] : "";
        const curDate = parts[0] || "";
        short = prevDate !== curDate && i > 0 ? date : time;
      } else {
        short = raw.replace(/^\d{4}-/, "");
      }
      result.push({ x: points[i].x, text: short });
    }
    return result;
  }, [data, points]);

  const handlePointerMove = useCallback((e) => {
    const svg = svgRef.current;
    if (!svg || points.length === 0) return;
    const rect = svg.getBoundingClientRect();
    const mx = ((e.clientX - rect.left) / rect.width) * VW;
    let closest = 0;
    let minDist = Infinity;
    for (let i = 0; i < points.length; i++) {
      const dist = Math.abs(points[i].x - mx);
      if (dist < minDist) { minDist = dist; closest = i; }
    }
    setHover({ idx: closest, px: points[closest].x, py: points[closest].y });
  }, [points]);

  const gradId = `chart-grad-${color.replace("#", "")}`;

  return (
    <svg
      ref={svgRef}
      width="100%"
      height={CHART_H}
      viewBox={`0 0 ${VW} ${CHART_H}`}
      preserveAspectRatio="none"
      className="block cursor-crosshair"
      style={{ display: "block", overflow: "visible", touchAction: "none" }}
      onPointerMove={handlePointerMove}
      onPointerLeave={() => setHover(null)}
    >
      <defs>
        <linearGradient id={gradId} x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stopColor={color} stopOpacity="0.18" />
          <stop offset="100%" stopColor={color} stopOpacity="0.01" />
        </linearGradient>
      </defs>

      {refY != null && (
        <line x1={PAD.left} y1={refY} x2={VW - PAD.right} y2={refY}
          stroke="rgba(0,0,0,0.06)" strokeDasharray="4 3" strokeWidth="1" />
      )}

      {areaPath && <path d={areaPath} fill={`url(#${gradId})`} />}
      {linePath && (
        <path d={linePath} fill="none" stroke={color} strokeWidth="2"
          strokeLinecap="round" strokeLinejoin="round"
          vectorEffect="non-scaling-stroke" />
      )}

      {labels.map((l, i) => (
        <text key={i} x={l.x} y={CHART_H - 6} textAnchor="middle"
          fill="rgba(0,0,0,0.25)" fontSize="10" fontFamily="system-ui, sans-serif">
          {l.text}
        </text>
      ))}

      {hover && (
        <>
          <line x1={hover.px} y1={PAD.top} x2={hover.px} y2={PAD.top + plotH}
            stroke="rgba(0,0,0,0.12)" strokeWidth="1" />
          <circle cx={hover.px} cy={hover.py} r="4" fill={color} stroke="white" strokeWidth="2" />
          <rect
            x={Math.max(2, Math.min(hover.px - 48, VW - 98))}
            y={Math.max(2, hover.py - 48)}
            width="96" height="38" rx="8"
            fill="white" stroke="rgba(0,0,0,0.08)" strokeWidth="0.5"
            filter="drop-shadow(0 2px 4px rgba(0,0,0,0.06))" />
          <text
            x={Math.max(50, Math.min(hover.px, VW - 50))}
            y={Math.max(18, hover.py - 32)}
            textAnchor="middle" fill="rgba(0,0,0,0.4)" fontSize="10" fontFamily="system-ui, sans-serif">
            {(() => {
              const raw = data[hover.idx]?.date || "";
              if (raw.includes(":")) {
                // Intraday: show "MM-DD HH:MM"
                const parts = raw.split(" ");
                return (parts[0] || "").replace(/^\d{4}-/, "") + " " + (parts[1] || "");
              }
              return raw;
            })()}
          </text>
          <text
            x={Math.max(50, Math.min(hover.px, VW - 50))}
            y={Math.max(33, hover.py - 17)}
            textAnchor="middle" fill="rgba(0,0,0,0.85)" fontSize="13" fontWeight="600" fontFamily="system-ui, sans-serif">
            ¥{Number(closes[hover.idx]).toLocaleString("en-US", { maximumFractionDigits: 1 })}
          </text>
        </>
      )}
    </svg>
  );
}

/* ── Time Range Tabs ──────────────────────────────────── */
function RangeTabs({ active, onChange, loading }) {
  return (
    <div className="flex gap-0.5 px-1 py-1 bg-black/[0.02] rounded-lg">
      {RANGES.map(r => {
        const isActive = active === r.key;
        return (
          <button
            key={r.key}
            onClick={() => onChange(r.key)}
            disabled={loading}
            className={`relative px-2.5 py-1 text-[11px] font-medium rounded-md transition-colors duration-200
              ${isActive
                ? "text-black/90"
                : "text-black/35 hover:text-black/55"
              }
              ${loading ? "opacity-50" : ""}
            `}
          >
            {isActive && (
              <motion.div
                layoutId="range-indicator"
                className="absolute inset-0 bg-white rounded-md shadow-sm"
                style={{ zIndex: 0 }}
                transition={{ type: "spring", bounce: 0.15, duration: 0.4 }}
              />
            )}
            <span className="relative z-10">{r.label}</span>
          </button>
        );
      })}
    </div>
  );
}

/* ── Main Component ───────────────────────────────────── */
export default function LivePriceTicker({
  stockCode,
  initialPrice,
  initialChangePct,
  marketState: initialMarketState,
  previousClose,
  priceHistory,
}) {
  const [price, setPrice] = useState(initialPrice);
  const [changePct, setChangePct] = useState(initialChangePct);
  const [prevClose, setPrevClose] = useState(previousClose);
  const [isLive, setIsLive] = useState(
    initialMarketState === "REGULAR" || isTSEOpen()
  );
  const [activeRange, setActiveRange] = useState("1M");
  const [rangeData, setRangeData] = useState({});
  const [loadingRange, setLoadingRange] = useState(false);
  const [revealed, setRevealed] = useState(false);

  const mountedRef = useRef(true);
  const intervalRef = useRef(null);
  const fetchedRangesRef = useRef(new Set());
  const canAnimate = useCanAnimate();

  // Reveal animation after mount
  useEffect(() => {
    const t = setTimeout(() => setRevealed(true), 100);
    return () => clearTimeout(t);
  }, []);

  // Compute change values relative to selected range
  const rangeChange = useMemo(() => {
    const currentData = rangeData[activeRange];
    if (!currentData || currentData.length < 2 || price == null) {
      return { value: price ? Number(price) * (changePct || 0) / 100 : 0, pct: changePct || 0 };
    }
    const firstClose = Number(currentData[0].close);
    const currentPrice = Number(price);
    if (!firstClose) return { value: 0, pct: 0 };
    const diff = currentPrice - firstClose;
    const pct = (diff / firstClose) * 100;
    return { value: diff, pct };
  }, [activeRange, rangeData, price, changePct]);

  const isPositive = rangeChange.pct >= 0;
  const chartColor = isPositive ? "#059669" : "#ef4444";
  const accentBg = isPositive ? "bg-emerald-500" : "bg-red-500";

  // Poll live price
  const poll = useCallback(async () => {
    if (!mountedRef.current) return;
    try {
      const quote = await fetchQuote(stockCode);
      if (!quote || !mountedRef.current) return;
      if (quote.price != null) setPrice(quote.price);
      if (quote.change_pct != null) setChangePct(quote.change_pct);
      if (quote.previous_close) setPrevClose(quote.previous_close);
      if (quote.market_state && quote.market_state !== "REGULAR" && !isTSEOpen()) setIsLive(false);
    } catch {}
  }, [stockCode]);

  useEffect(() => {
    mountedRef.current = true;
    if (!isLive || !stockCode || !isTSEOpen()) return;
    intervalRef.current = setInterval(() => {
      if (!isTSEOpen()) { clearInterval(intervalRef.current); setIsLive(false); return; }
      poll();
    }, POLL_INTERVAL);
    return () => clearInterval(intervalRef.current);
  }, [isLive, stockCode, poll]);

  useEffect(() => () => { mountedRef.current = false; }, []);

  // priceHistory from report is not used for pre-seeding — each range
  // fetches its own data from the API with the correct interval and date window.

  // Fetch data when range changes
  useEffect(() => {
    if (!stockCode) return;
    if (fetchedRangesRef.current.has(activeRange)) return;
    fetchedRangesRef.current.add(activeRange);

    let cancelled = false;
    setLoadingRange(true);

    const r = RANGES.find(r => r.key === activeRange);
    const days = r.key === "YTD" ? getYTDDays() : r.days;
    const interval = r.interval || "1d";

    fetchPriceHistory(stockCode, days, interval).then(data => {
      if (cancelled || !mountedRef.current) return;
      if (Array.isArray(data) && data.length >= 2) {
        setRangeData(prev => ({ ...prev, [activeRange]: data }));
      }
      setLoadingRange(false);
    }).catch(() => { if (!cancelled) setLoadingRange(false); });

    return () => { cancelled = true; };
  }, [activeRange, stockCode]);

  const currentChartData = rangeData[activeRange] || [];
  const hasChart = currentChartData.length >= 2;

  // Reference price for dotted line: first close in current range
  const refPrice = hasChart ? Number(currentChartData[0].close) : prevClose;

  return (
    <motion.div
      initial={{ opacity: 0, y: 12, scale: 0.98 }}
      animate={{ opacity: 1, y: 0, scale: 1 }}
      transition={{ duration: 0.5, ease: [0.16, 1, 0.3, 1] }}
      className="rounded-2xl border border-black/[0.06] bg-white shadow-sm overflow-hidden"
      style={{ maxWidth: 480 }}
    >
      {/* ── Price Header ── */}
      <div className="px-5 pt-4 pb-3">
        {/* Price */}
        <div className="flex items-baseline gap-3">
          <NumberFlow
            value={revealed ? Number(price) : 0}
            format={{ style: "currency", currency: "JPY", maximumFractionDigits: 1 }}
            className="text-[28px] font-semibold tracking-tight text-black/90 tabular-nums"
            transformTiming={{ duration: 1200, easing: "cubic-bezier(0.16, 1, 0.3, 1)" }}
            spinTiming={{ duration: 1200, easing: "cubic-bezier(0.16, 1, 0.3, 1)" }}
          />
        </div>

        {/* Change badge */}
        <div className="flex items-center gap-2 mt-1.5">
          <motion.span
            className={`inline-flex items-center gap-0.5 px-2 py-0.5 rounded-full text-white text-[12px] font-medium ${accentBg}`}
            layout={canAnimate}
            transition={{ layout: { duration: 0.5, bounce: 0, type: "spring" } }}
          >
            <motion.span
              animate={{ rotate: isPositive ? 0 : 180 }}
              transition={{ duration: 0.3 }}
              className="flex items-center"
            >
              <ArrowUp className="w-3 h-3" strokeWidth={2.5} />
            </motion.span>
            <NumberFlow
              value={revealed ? Math.abs(rangeChange.value) : 0}
              format={{ maximumFractionDigits: 1 }}
              className="tabular-nums"
              transformTiming={{ duration: 800, easing: "cubic-bezier(0.16, 1, 0.3, 1)" }}
              spinTiming={{ duration: 800, easing: "cubic-bezier(0.16, 1, 0.3, 1)" }}
            />
          </motion.span>
          <span className={`text-[12px] font-medium tabular-nums ${isPositive ? "text-emerald-600" : "text-red-500"}`}>
            <NumberFlow
              value={revealed ? rangeChange.pct / 100 : 0}
              format={{ style: "percent", minimumFractionDigits: 2, maximumFractionDigits: 2, signDisplay: "always" }}
              transformTiming={{ duration: 800, easing: "cubic-bezier(0.16, 1, 0.3, 1)" }}
              spinTiming={{ duration: 800, easing: "cubic-bezier(0.16, 1, 0.3, 1)" }}
            />
          </span>
          {isLive ? (
            <span className="inline-flex items-center gap-1 text-[10px] text-black/30 ml-1">
              <motion.span className="w-1.5 h-1.5 rounded-full bg-emerald-500"
                animate={{ opacity: [0.3, 1, 0.3] }}
                transition={{ duration: 2, repeat: Infinity, ease: "easeInOut" }} />
              Live
            </span>
          ) : (
            <span className="text-[10px] text-black/20 ml-1">Closed</span>
          )}
        </div>
      </div>

      {/* ── Chart ── */}
      <div className="px-2 relative" style={{ minHeight: CHART_H }}>
        <AnimatePresence mode="wait">
          {hasChart ? (
            <motion.div
              key={activeRange}
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              exit={{ opacity: 0 }}
              transition={{ duration: 0.25 }}
            >
              <PriceChart data={currentChartData} color={chartColor} referencePrice={refPrice} />
            </motion.div>
          ) : (
            <motion.div
              key="loading"
              className="flex items-center justify-center"
              style={{ height: CHART_H }}
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
            >
              <div className="w-5 h-5 border-2 border-black/10 border-t-black/40 rounded-full animate-spin" />
            </motion.div>
          )}
        </AnimatePresence>
      </div>

      {/* ── Range Tabs ── */}
      <div className="px-3 pb-3 pt-1">
        <RangeTabs active={activeRange} onChange={setActiveRange} loading={loadingRange} />
      </div>
    </motion.div>
  );
}
