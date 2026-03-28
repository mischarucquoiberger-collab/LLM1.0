import React, { useState, useEffect, useRef, useCallback, useMemo } from "react";
import { motion } from "framer-motion";
import { TrendingUp, TrendingDown, Minus } from "lucide-react";
import { fetchQuote, fetchPriceHistory } from "@/api/backend";

const POLL_INTERVAL = 5000;
const CHART_H = 120;
const PAD = { top: 8, right: 8, bottom: 20, left: 8 };
const VW = 400;

function isTSEOpen() {
  const now = new Date();
  const day = now.getUTCDay();
  if (day === 0 || day === 6) return false;
  const jstHour = (now.getUTCHours() + 9) % 24;
  const jstMin = now.getUTCMinutes();
  const t = jstHour * 60 + jstMin;
  return (t >= 540 && t <= 690) || (t >= 750 && t < 900);
}

function fmtPrice(p) {
  if (p == null) return "\u2014";
  return `\u00A5${Number(p).toLocaleString("en-US", { maximumFractionDigits: 1 })}`;
}

function fmtPct(pct) {
  if (pct == null) return "";
  return `${pct >= 0 ? "+" : ""}${pct.toFixed(2)}%`;
}

/* ── Pure SVG sparkline ─────────────────────────────────── */
function Sparkline({ data, color, prevClose }) {
  const [hover, setHover] = useState(null);
  const svgRef = useRef(null);

  const closes = useMemo(() => data.map(d => Number(d.close)), [data]);

  const { yMin, yMax } = useMemo(() => {
    const mn = Math.min(...closes);
    const mx = Math.max(...closes);
    const pad = (mx - mn) * 0.12 || mx * 0.02;
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
    if (prevClose == null) return null;
    const pc = Number(prevClose);
    if (pc < yMin || pc > yMax) return null;
    return PAD.top + plotH - ((pc - yMin) / (yMax - yMin || 1)) * plotH;
  }, [prevClose, yMin, yMax, plotH]);

  const labels = useMemo(() => {
    if (data.length < 2) return [];
    const count = Math.min(5, data.length);
    const step = Math.max(Math.floor((data.length - 1) / (count - 1)), 1);
    const result = [];
    for (let i = 0; i < data.length; i += step) {
      result.push({ x: points[i].x, text: (data[i].date || "").replace(/^\d{4}-/, "") });
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

  const gradId = `sp-${color.replace("#", "")}`;

  return (
    <svg
      ref={svgRef}
      width="100%"
      height={CHART_H}
      viewBox={`0 0 ${VW} ${CHART_H}`}
      preserveAspectRatio="none"
      className="block"
      style={{ display: "block", overflow: "visible", touchAction: "none" }}
      onPointerMove={handlePointerMove}
      onPointerLeave={() => setHover(null)}
    >
      <defs>
        <linearGradient id={gradId} x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stopColor={color} stopOpacity="0.15" />
          <stop offset="100%" stopColor={color} stopOpacity="0" />
        </linearGradient>
      </defs>

      {refY != null && (
        <line x1={PAD.left} y1={refY} x2={VW - PAD.right} y2={refY}
          stroke="rgba(0,0,0,0.08)" strokeDasharray="3 3" />
      )}

      {areaPath && <path d={areaPath} fill={`url(#${gradId})`} />}
      {linePath && (
        <path d={linePath} fill="none" stroke={color} strokeWidth="1.5"
          strokeLinecap="round" strokeLinejoin="round"
          vectorEffect="non-scaling-stroke" />
      )}

      {labels.map((l, i) => (
        <text key={i} x={l.x} y={CHART_H - 4} textAnchor="middle"
          fill="rgba(0,0,0,0.2)" fontSize="9" fontFamily="system-ui, sans-serif">
          {l.text}
        </text>
      ))}

      {hover && (
        <>
          <line x1={hover.px} y1={PAD.top} x2={hover.px} y2={PAD.top + plotH}
            stroke="rgba(0,0,0,0.08)" strokeWidth="1" />
          <circle cx={hover.px} cy={hover.py} r="3.5" fill={color} stroke="white" strokeWidth="2" />
          <rect
            x={Math.max(2, Math.min(hover.px - 42, VW - 86))}
            y={Math.max(2, hover.py - 42)}
            width="84" height="36" rx="8"
            fill="white" stroke="rgba(0,0,0,0.08)" strokeWidth="0.5" />
          <text
            x={Math.max(44, Math.min(hover.px, VW - 44))}
            y={Math.max(16, hover.py - 26)}
            textAnchor="middle" fill="rgba(0,0,0,0.35)" fontSize="9" fontFamily="system-ui, sans-serif">
            {(data[hover.idx]?.date || "").replace(/^\d{4}-/, "")}
          </text>
          <text
            x={Math.max(44, Math.min(hover.px, VW - 44))}
            y={Math.max(29, hover.py - 13)}
            textAnchor="middle" fill="rgba(0,0,0,0.85)" fontSize="11" fontWeight="600" fontFamily="system-ui, sans-serif">
            {fmtPrice(closes[hover.idx])}
          </text>
        </>
      )}
    </svg>
  );
}

/* ── Main Component ─────────────────────────────────────── */
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
  const [flash, setFlash] = useState(null);
  const [isLive, setIsLive] = useState(
    initialMarketState === "REGULAR" || isTSEOpen()
  );
  const [fetchedHistory, setFetchedHistory] = useState(null);
  const prevPriceRef = useRef(initialPrice);
  const intervalRef = useRef(null);
  const flashTimeoutRef = useRef(null);
  const mountedRef = useRef(true);

  const poll = useCallback(async () => {
    if (!mountedRef.current) return;
    try {
      const quote = await fetchQuote(stockCode);
      if (!quote || !mountedRef.current) return;
      const newPrice = quote.price;
      const prev = prevPriceRef.current;
      if (newPrice != null && prev != null) {
        if (newPrice > prev) setFlash("up");
        else if (newPrice < prev) setFlash("down");
      }
      setPrice(newPrice);
      setChangePct(quote.change_pct);
      if (quote.previous_close) setPrevClose(quote.previous_close);
      prevPriceRef.current = newPrice;
      if (quote.market_state && quote.market_state !== "REGULAR" && !isTSEOpen()) setIsLive(false);
      if (flashTimeoutRef.current) clearTimeout(flashTimeoutRef.current);
      flashTimeoutRef.current = setTimeout(() => { if (mountedRef.current) setFlash(null); }, 800);
    } catch {}
  }, [stockCode]);

  useEffect(() => {
    mountedRef.current = true;
    if (!isLive || !stockCode || !isTSEOpen()) return;
    intervalRef.current = setInterval(() => {
      if (!isTSEOpen()) { clearInterval(intervalRef.current); setIsLive(false); return; }
      poll();
    }, POLL_INTERVAL);
    return () => { clearInterval(intervalRef.current); if (flashTimeoutRef.current) clearTimeout(flashTimeoutRef.current); };
  }, [isLive, stockCode, poll]);

  useEffect(() => () => { mountedRef.current = false; }, []);

  useEffect(() => {
    if (!stockCode) return;
    const sseValid = priceHistory && Array.isArray(priceHistory) &&
      priceHistory.filter(p => p && p.close != null && p.close !== "" && Number(p.close) > 0).length >= 2;
    if (sseValid) return;

    let cancelled = false;
    fetchPriceHistory(stockCode, 90).then(data => {
      if (cancelled || !mountedRef.current) return;
      if (Array.isArray(data) && data.length >= 2) {
        setFetchedHistory(data);
      }
    }).catch(() => {});
    return () => { cancelled = true; };
  }, [stockCode, priceHistory]);

  const chartData = useMemo(() => {
    if (priceHistory && Array.isArray(priceHistory) && priceHistory.length > 0) {
      const valid = priceHistory.filter(p => p && p.close != null && p.close !== "" && Number(p.close) > 0);
      if (valid.length >= 2) return valid;
    }
    if (fetchedHistory && Array.isArray(fetchedHistory) && fetchedHistory.length > 0) {
      const valid = fetchedHistory.filter(p => p && p.close != null && Number(p.close) > 0);
      if (valid.length >= 2) return valid;
    }
    return [];
  }, [priceHistory, fetchedHistory]);

  const isPositive = changePct != null && changePct >= 0;
  const isNegative = changePct != null && changePct < 0;
  const priceColor = isPositive ? "text-emerald-600" : isNegative ? "text-red-500" : "text-black/60";
  const pctColor = isPositive ? "text-emerald-600/70" : isNegative ? "text-red-500/70" : "text-black/30";
  const flashBg = flash === "up" ? "bg-emerald-50" : flash === "down" ? "bg-red-50" : "bg-white";
  const borderClr = flash === "up" ? "border-emerald-200/60" : flash === "down" ? "border-red-200/60" : "border-black/[0.06]";
  const chartColor = isPositive ? "#059669" : isNegative ? "#ef4444" : "#64748b";
  const TrendIcon = isPositive ? TrendingUp : isNegative ? TrendingDown : Minus;
  const hasChart = chartData.length >= 2;

  return (
    <motion.div
      initial={{ opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.5, ease: [0.16, 1, 0.3, 1] }}
      className={`rounded-2xl border transition-all duration-700 shadow-sm ${flashBg} ${borderClr}`}
      style={{ maxWidth: 420 }}
    >
      {/* Price header */}
      <div className="flex items-center gap-3 px-4 pt-3 pb-2">
        <div className={`w-7 h-7 rounded-xl flex items-center justify-center shrink-0 ${
          isPositive ? "bg-emerald-100" : isNegative ? "bg-red-100" : "bg-black/[0.03]"
        }`}>
          <TrendIcon className={`w-3.5 h-3.5 ${priceColor}`} />
        </div>
        <div className="flex flex-col min-w-0 flex-1">
          <div className="flex items-baseline gap-2">
            <motion.span key={price}
              initial={{ opacity: 0.6, y: flash === "up" ? 4 : flash === "down" ? -4 : 0 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ duration: 0.4, ease: [0.16, 1, 0.3, 1] }}
              className={`text-[16px] font-semibold tabular-nums tracking-tight ${priceColor}`}>
              {fmtPrice(price)}
            </motion.span>
            <span className={`text-[12px] font-medium tabular-nums ${pctColor}`}>
              {fmtPct(changePct)}
            </span>
          </div>
          <div className="flex items-center gap-2 mt-0.5">
            {prevClose && (
              <span className="text-[10px] text-black/25 tabular-nums">prev close {fmtPrice(prevClose)}</span>
            )}
            {isLive ? (
              <span className="inline-flex items-center gap-1 text-[10px] text-black/25">
                <motion.span className="w-1 h-1 rounded-full bg-emerald-500"
                  animate={{ opacity: [0.3, 1, 0.3] }}
                  transition={{ duration: 2, repeat: Infinity, ease: "easeInOut" }} />
                live
              </span>
            ) : (
              <span className="text-[10px] text-black/15">market closed</span>
            )}
          </div>
        </div>
        {hasChart && (
          <span className="text-[10px] text-black/20 tabular-nums shrink-0">{chartData.length}d</span>
        )}
      </div>

      {/* Pure SVG Chart */}
      {hasChart && (
        <div className="px-1 pb-2">
          <Sparkline data={chartData} color={chartColor} prevClose={prevClose} />
        </div>
      )}
    </motion.div>
  );
}
