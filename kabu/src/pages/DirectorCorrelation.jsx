import React, { useEffect, useMemo, useRef, useState, useCallback } from "react";
import { motion, AnimatePresence } from "framer-motion";
import ForceGraph2D from "react-force-graph-2d";
import { polygonHull } from "d3-polygon";
import {
  ArrowLeft, Filter, Search, X, Download, ChevronLeft, ChevronRight,
  AlertTriangle, Shield, Users, Link2, Activity, Eye, Info,
  Maximize2, ZoomIn, ZoomOut, RotateCcw, Loader2, ExternalLink, Linkedin,
  BarChart3, Globe, GraduationCap, BookOpen,
} from "lucide-react";
import { Link, useSearchParams } from "react-router-dom";
import { fetchDirectors } from "@/api/backend";
import {
  CONNECTION_TYPES, COMPANY_COLORS as FALLBACK_COLORS,
  CLUSTERS as FALLBACK_CLUSTERS,
  computeIndependenceScore as fallbackIndependenceScore,
  getDataForYear as fallbackGetDataForYear,
} from "@/data/takeda-directors";

/* ── Constants ────────────────────────────────────────────── */
const OVERBOARD_THRESHOLD = 3;
const OVERBOARD_COLOR = "#f97316";
const FLAG_RED = "#ef4444";
const DIM_OPACITY = 0.12;

/* ── Helpers for dynamic data ─────────────────────────────── */
function dynamicGetDataForYear(directors, connections, year) {
  const nodes = directors.filter(d => d.joinYear <= year && (!d.leaveYear || d.leaveYear > year));
  const nodeIds = new Set(nodes.map(n => n.id));
  const links = connections.filter(c => {
    const inRange = (c.startYear || 0) <= year && (!c.endYear || c.endYear > year);
    return inRange && nodeIds.has(c.source) && nodeIds.has(c.target);
  });
  return { nodes, links };
}

function dynamicIndependenceScore(directorId, connections, directors, year) {
  const internalIds = new Set(directors.filter(d => d.type === "internal").map(d => d.id));
  const activeConns = connections.filter(c => {
    const matchDir = c.source === directorId || c.target === directorId;
    const inRange = (c.startYear || 0) <= year && (!c.endYear || c.endYear >= year);
    return matchDir && inRange;
  });
  const insiderConns = activeConns.filter(c => {
    const other = c.source === directorId ? c.target : c.source;
    return internalIds.has(other);
  });
  const totalWeight = insiderConns.reduce((s, c) => s + (c.weight || 1), 0);
  return {
    totalConnections: activeConns.length,
    insiderConnections: insiderConns.length,
    insiderWeight: totalWeight,
    isFlagged: insiderConns.length >= 3,
    severity: insiderConns.length >= 4 ? "critical" : insiderConns.length >= 3 ? "warning" : "ok",
    details: insiderConns.map(c => ({
      insider: c.source === directorId ? c.target : c.source,
      type: c.type,
      detail: c.detail,
    })),
  };
}

/* ── Loading Screen ───────────────────────────────────────── */
function LoadingScreen({ companyName, ticker }) {
  return (
    <div className="h-dvh flex flex-col items-center justify-center bg-[#0A0E1A] relative overflow-hidden">
      {/* Animated background network */}
      <div className="absolute inset-0 opacity-[0.06]">
        <svg className="w-full h-full" viewBox="0 0 800 600">
          {[
            [200, 150], [400, 100], [600, 200], [150, 350], [350, 300],
            [550, 350], [250, 500], [450, 480], [650, 450], [100, 200],
          ].map(([cx, cy], i) => (
            <g key={i}>
              <circle cx={cx} cy={cy} r="4" fill="#3b82f6">
                <animate attributeName="r" values="3;6;3" dur={`${2 + i * 0.3}s`} repeatCount="indefinite" />
                <animate attributeName="opacity" values="0.4;1;0.4" dur={`${2 + i * 0.3}s`} repeatCount="indefinite" />
              </circle>
              {i < 9 && (
                <line
                  x1={cx} y1={cy}
                  x2={[200, 400, 600, 150, 350, 550, 250, 450, 650, 100][(i + 1) % 10]}
                  y2={[150, 100, 200, 350, 300, 350, 500, 480, 450, 200][(i + 1) % 10]}
                  stroke="#3b82f6" strokeWidth="0.5" opacity="0.3"
                >
                  <animate attributeName="opacity" values="0.1;0.4;0.1" dur={`${3 + i * 0.2}s`} repeatCount="indefinite" />
                </line>
              )}
            </g>
          ))}
        </svg>
      </div>

      <motion.div
        initial={{ opacity: 0, y: 20 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.6, ease: [0.16, 1, 0.3, 1] }}
        className="relative z-10 flex flex-col items-center text-center px-6"
      >
        <div className="w-16 h-16 rounded-2xl bg-gradient-to-br from-rose-500/20 to-purple-500/20 border border-white/[0.08] flex items-center justify-center mb-6">
          <Users className="w-8 h-8 text-rose-400" />
        </div>

        <h1 className="text-2xl font-bold text-white mb-2">
          {companyName || "Director Network"}
        </h1>
        {ticker && (
          <p className="text-blue-400 font-mono text-sm mb-6">{ticker}</p>
        )}

        <div className="flex items-center gap-3 mb-4">
          <Loader2 className="w-4 h-4 text-blue-400 animate-spin" />
          <p className="text-sm text-gray-400">
            Researching board of directors...
          </p>
        </div>

        <div className="w-56 h-1 bg-white/[0.06] rounded-full overflow-hidden">
          <motion.div
            className="h-full bg-gradient-to-r from-blue-500 to-purple-500 rounded-full"
            initial={{ width: "0%" }}
            animate={{ width: "95%" }}
            transition={{ duration: 15, ease: "easeOut" }}
          />
        </div>

        <div className="mt-5 space-y-2 text-[11px] text-gray-600 max-w-xs text-center">
          <motion.p initial={{ opacity: 0 }} animate={{ opacity: 1 }} transition={{ delay: 0 }}>
            Searching public records and filings...
          </motion.p>
          <motion.p initial={{ opacity: 0 }} animate={{ opacity: 1 }} transition={{ delay: 4 }}>
            Scraping official company pages...
          </motion.p>
          <motion.p initial={{ opacity: 0 }} animate={{ opacity: 1 }} transition={{ delay: 8 }}>
            Verifying individual director profiles...
          </motion.p>
          <motion.p initial={{ opacity: 0 }} animate={{ opacity: 1 }} transition={{ delay: 12 }}>
            Finding LinkedIn and Wikipedia profiles...
          </motion.p>
          <motion.p initial={{ opacity: 0 }} animate={{ opacity: 1 }} transition={{ delay: 16 }}>
            Checking Wikipedia and public records...
          </motion.p>
          <motion.p initial={{ opacity: 0 }} animate={{ opacity: 1 }} transition={{ delay: 20 }}>
            Building relationship network...
          </motion.p>
        </div>
      </motion.div>
    </div>
  );
}

/* ── Main Component ───────────────────────────────────────── */
export default function DirectorCorrelation() {
  const fgRef = useRef();
  const containerRef = useRef();
  const [params] = useSearchParams();

  const ticker = params.get("ticker") || "";
  const companyName = params.get("name") || ticker || "Takeda";

  // Loading state
  const [loading, setLoading] = useState(!!ticker);
  const [loadError, setLoadError] = useState(null);

  // Dynamic data from API or fallback
  const [rawDirectors, setRawDirectors] = useState(null);
  const [rawConnections, setRawConnections] = useState(null);
  const [clusters, setClusters] = useState(FALLBACK_CLUSTERS);
  const [companyColors, setCompanyColors] = useState(FALLBACK_COLORS);
  const [boardSummary, setBoardSummary] = useState(null);

  // Container dimensions
  const [dimensions, setDimensions] = useState({ width: 800, height: 600 });

  useEffect(() => {
    const measure = () => {
      if (containerRef.current) {
        const { clientWidth, clientHeight } = containerRef.current;
        if (clientWidth > 0 && clientHeight > 0) {
          setDimensions({ width: clientWidth, height: clientHeight });
        }
      }
    };
    measure();
    const ro = new ResizeObserver(measure);
    if (containerRef.current) ro.observe(containerRef.current);
    return () => ro.disconnect();
  }, [loading]);

  // Fetch director data from API
  useEffect(() => {
    if (!ticker) {
      // No ticker = use Takeda mock data (fallback)
      setLoading(false);
      return;
    }

    let cancelled = false;
    setLoading(true);
    setLoadError(null);

    fetchDirectors(ticker, companyName)
      .then(data => {
        if (cancelled) return;
        if (data.directors) setRawDirectors(data.directors);
        if (data.connections) setRawConnections(data.connections);
        if (data.clusters) setClusters(data.clusters);
        if (data.companyColors) setCompanyColors(data.companyColors);
        if (data.boardSummary) setBoardSummary(data.boardSummary);
        setLoading(false);
      })
      .catch(err => {
        if (cancelled) return;
        setLoadError(err.message);
        setLoading(false);
      });

    return () => { cancelled = true; };
  }, [ticker, companyName]);

  // Data state
  const [year, setYear] = useState(2025);
  const [graphData, setGraphData] = useState({ nodes: [], links: [] });

  // Interaction state
  const [selectedNode, setSelectedNode] = useState(null);
  const [hoveredNode, setHoveredNode] = useState(null);
  const [hoveredLink, setHoveredLink] = useState(null);
  const [tooltipPos, setTooltipPos] = useState({ x: 0, y: 0 });
  const [linkTooltipPos, setLinkTooltipPos] = useState({ x: 0, y: 0 });
  const [contextMenu, setContextMenu] = useState(null);

  // Insights panel
  const [insightsOpen, setInsightsOpen] = useState(true);

  // Filter state
  const [filterOpen, setFilterOpen] = useState(false);
  const [searchQuery, setSearchQuery] = useState("");
  const [connToggles, setConnToggles] = useState(() =>
    Object.fromEntries(Object.entries(CONNECTION_TYPES).map(([k, v]) => [k, v.defaultOn]))
  );
  const [showIndependentOnly, setShowIndependentOnly] = useState(false);
  const [showOverboardedOnly, setShowOverboardedOnly] = useState(false);
  const [showInternalOnly, setShowInternalOnly] = useState(false);
  const [showClusters, setShowClusters] = useState(true);

  // Detail panel
  const [detailOpen, setDetailOpen] = useState(false);

  // Highlight sets
  const [highlightNodes, setHighlightNodes] = useState(new Set());
  const [highlightLinks, setHighlightLinks] = useState(new Set());

  // ── Compute graph data for current year + filters ──
  useEffect(() => {
    if (loading) return;

    let rawNodes, rawLinks;
    if (rawDirectors) {
      ({ nodes: rawNodes, links: rawLinks } = dynamicGetDataForYear(rawDirectors, rawConnections || [], year));
    } else {
      ({ nodes: rawNodes, links: rawLinks } = fallbackGetDataForYear(year));
    }

    let filteredNodes = rawNodes;
    if (showIndependentOnly) filteredNodes = filteredNodes.filter(n => n.isIndependent);
    if (showOverboardedOnly) filteredNodes = filteredNodes.filter(n => n.boardSeats >= OVERBOARD_THRESHOLD);
    if (showInternalOnly) filteredNodes = filteredNodes.filter(n => n.type === "internal");
    if (searchQuery) {
      const q = searchQuery.toLowerCase();
      filteredNodes = filteredNodes.filter(n =>
        n.nameEn.toLowerCase().includes(q) ||
        (n.nameJp && n.nameJp.includes(q)) ||
        n.company.toLowerCase().includes(q)
      );
    }

    const nodeIds = new Set(filteredNodes.map(n => n.id));
    const filteredLinks = rawLinks.filter(l =>
      connToggles[l.type] !== false && nodeIds.has(l.source) && nodeIds.has(l.target)
    );

    const allDirectors = rawDirectors || rawNodes;
    const allConnections = rawConnections || rawLinks;
    const enriched = filteredNodes.map(n => ({
      ...n,
      independenceScore: n.isIndependent
        ? (rawDirectors
          ? dynamicIndependenceScore(n.id, allConnections, allDirectors, year)
          : fallbackIndependenceScore(n.id, rawLinks, year))
        : null,
      _size: Math.max(5, n.boardSeats * 3.5),
      _color: companyColors[n.company] || FALLBACK_COLORS[n.company] || "#6b7280",
    }));

    setGraphData({
      nodes: enriched,
      links: filteredLinks.map(l => ({ ...l })),
    });
  }, [year, connToggles, showIndependentOnly, showOverboardedOnly, showInternalOnly, searchQuery, loading, rawDirectors, rawConnections, companyColors]);

  // ── Pre-compute neighbor maps ──
  const { neighborMap, linksByNode } = useMemo(() => {
    const nm = {};
    const lbn = {};
    graphData.links.forEach(link => {
      const sid = typeof link.source === "object" ? link.source.id : link.source;
      const tid = typeof link.target === "object" ? link.target.id : link.target;
      nm[sid] = [...(nm[sid] || []), tid];
      nm[tid] = [...(nm[tid] || []), sid];
      lbn[sid] = [...(lbn[sid] || []), link];
      lbn[tid] = [...(lbn[tid] || []), link];
    });
    return { neighborMap: nm, linksByNode: lbn };
  }, [graphData]);

  // ── Stats ──
  const stats = useMemo(() => {
    const nodes = graphData.nodes;
    const totalDirectors = nodes.length;
    const avgSeats = nodes.length ? (nodes.reduce((s, n) => s + n.boardSeats, 0) / nodes.length).toFixed(1) : 0;
    const overboarded = nodes.filter(n => n.boardSeats >= OVERBOARD_THRESHOLD).length;
    const flagged = nodes.filter(n => n.independenceScore?.isFlagged).length;
    const mostConnected = nodes.reduce((best, n) => {
      const conns = (neighborMap[n.id] || []).length;
      return conns > (best.conns || 0) ? { name: n.nameEn, conns } : best;
    }, { name: "-", conns: 0 });
    const maxLinks = (totalDirectors * (totalDirectors - 1)) / 2;
    const density = maxLinks > 0 ? ((graphData.links.length / maxLinks) * 100).toFixed(1) : 0;
    return { totalDirectors, avgSeats, overboarded, flagged, mostConnected, density };
  }, [graphData, neighborMap]);

  // ── Callbacks ──
  const handleNodeClick = useCallback((node) => {
    if (selectedNode?.id === node.id) {
      setSelectedNode(null);
      setDetailOpen(false);
      setHighlightNodes(new Set());
      setHighlightLinks(new Set());
      return;
    }
    const hn = new Set([node.id, ...(neighborMap[node.id] || [])]);
    const hl = new Set(linksByNode[node.id] || []);
    setHighlightNodes(hn);
    setHighlightLinks(hl);
    setSelectedNode(node);
    setDetailOpen(true);
  }, [neighborMap, linksByNode, selectedNode]);

  const handleBackgroundClick = useCallback(() => {
    setSelectedNode(null);
    setDetailOpen(false);
    setHighlightNodes(new Set());
    setHighlightLinks(new Set());
    setContextMenu(null);
  }, []);

  const handleNodeHover = useCallback((node) => {
    setHoveredNode(node || null);
    const canvas = containerRef.current?.querySelector("canvas");
    if (canvas) canvas.style.cursor = node ? "pointer" : "default";
    if (node && fgRef.current) {
      const coords = fgRef.current.graph2ScreenCoords(node.x, node.y);
      setTooltipPos({ x: coords.x, y: coords.y });
    }
  }, []);

  const handleLinkHover = useCallback((link) => {
    setHoveredLink(link || null);
    if (link && fgRef.current) {
      const sx = typeof link.source === "object" ? link.source.x : 0;
      const sy = typeof link.source === "object" ? link.source.y : 0;
      const tx = typeof link.target === "object" ? link.target.x : 0;
      const ty = typeof link.target === "object" ? link.target.y : 0;
      const mid = fgRef.current.graph2ScreenCoords((sx + tx) / 2, (sy + ty) / 2);
      setLinkTooltipPos({ x: mid.x, y: mid.y });
    }
  }, []);

  const handleNodeRightClick = useCallback((node, event) => {
    event.preventDefault();
    const rect = containerRef.current?.getBoundingClientRect();
    const x = rect ? event.clientX - rect.left : event.clientX;
    const y = rect ? event.clientY - rect.top : event.clientY;
    setContextMenu({ x, y, node });
  }, []);

  useEffect(() => {
    const close = () => setContextMenu(null);
    window.addEventListener("click", close);
    return () => window.removeEventListener("click", close);
  }, []);

  // ── Node canvas rendering ──
  const paintNode = useCallback((node, ctx, globalScale) => {
    const r = node._size || 6;
    const isHighlighted = highlightNodes.size === 0 || highlightNodes.has(node.id);
    const isSelected = selectedNode?.id === node.id;
    const isHovered = hoveredNode?.id === node.id;
    const isFlagged = node.independenceScore?.isFlagged;
    const isOverboarded = node.boardSeats >= OVERBOARD_THRESHOLD;
    const isInternal = node.type === "internal";

    ctx.save();
    if (!isHighlighted) ctx.globalAlpha = DIM_OPACITY;

    // Internal director glow
    if (isInternal && isHighlighted) {
      const grad = ctx.createRadialGradient(node.x, node.y, r, node.x, node.y, r * 3);
      grad.addColorStop(0, "rgba(225, 29, 72, 0.25)");
      grad.addColorStop(1, "rgba(225, 29, 72, 0)");
      ctx.beginPath();
      ctx.arc(node.x, node.y, r * 3, 0, 2 * Math.PI);
      ctx.fillStyle = grad;
      ctx.fill();
    }

    // Overboarded pulsing orange ring
    if (isOverboarded && isHighlighted) {
      const pulse = Math.sin(Date.now() / 400) * 0.35 + 0.65;
      ctx.beginPath();
      ctx.arc(node.x, node.y, r + 3, 0, 2 * Math.PI);
      ctx.strokeStyle = OVERBOARD_COLOR;
      ctx.lineWidth = 2 / globalScale;
      ctx.globalAlpha = isHighlighted ? pulse : DIM_OPACITY * 0.5;
      ctx.stroke();
      ctx.globalAlpha = isHighlighted ? 1 : DIM_OPACITY;
    }

    // Independence fraud red ring
    if (isFlagged && isHighlighted) {
      ctx.beginPath();
      ctx.arc(node.x, node.y, r + 5.5, 0, 2 * Math.PI);
      ctx.strokeStyle = FLAG_RED;
      ctx.lineWidth = 1.5 / globalScale;
      ctx.setLineDash([3 / globalScale, 2 / globalScale]);
      ctx.stroke();
      ctx.setLineDash([]);
    }

    // Main circle
    ctx.beginPath();
    ctx.arc(node.x, node.y, r, 0, 2 * Math.PI);
    ctx.fillStyle = node._color;
    ctx.fill();

    // Selection ring
    if (isSelected) {
      ctx.strokeStyle = "#fff";
      ctx.lineWidth = 2.5 / globalScale;
      ctx.stroke();
    } else if (isHovered) {
      ctx.strokeStyle = "rgba(255,255,255,0.6)";
      ctx.lineWidth = 1.5 / globalScale;
      ctx.stroke();
    }

    // Independence badge
    if (node.isIndependent && isHighlighted) {
      const bx = node.x + r * 0.7;
      const by = node.y - r * 0.7;
      ctx.beginPath();
      ctx.arc(bx, by, 3, 0, 2 * Math.PI);
      ctx.fillStyle = isFlagged ? FLAG_RED : "#22c55e";
      ctx.fill();
      ctx.strokeStyle = "#0A0E1A";
      ctx.lineWidth = 0.8 / globalScale;
      ctx.stroke();
    }

    // Label
    const fontSize = Math.max(10, 12 / globalScale);
    ctx.font = `${fontSize}px Inter, system-ui, sans-serif`;
    ctx.textAlign = "center";
    ctx.textBaseline = "top";
    ctx.fillStyle = isHighlighted ? "rgba(255,255,255,0.9)" : "rgba(255,255,255,0.1)";
    const label = node.nameEn.split(" ").pop() || node.nameEn;
    ctx.fillText(label, node.x, node.y + r + 3);

    ctx.restore();
  }, [highlightNodes, selectedNode, hoveredNode]);

  const paintNodeArea = useCallback((node, color, ctx) => {
    const r = (node._size || 6) + 4;
    ctx.beginPath();
    ctx.arc(node.x, node.y, r, 0, 2 * Math.PI);
    ctx.fillStyle = color;
    ctx.fill();
  }, []);

  // ── Link rendering ──
  const getLinkColor = useCallback((link) => {
    if (highlightLinks.size > 0 && !highlightLinks.has(link)) return `rgba(100,100,100,${DIM_OPACITY})`;
    return CONNECTION_TYPES[link.type]?.color || "#6b7280";
  }, [highlightLinks]);

  const getLinkWidth = useCallback((link) => {
    const base = (link.weight || 1) * 0.8;
    if (highlightLinks.size > 0 && highlightLinks.has(link)) return base * 1.5;
    return base;
  }, [highlightLinks]);

  const getLinkDash = useCallback((link) => {
    return CONNECTION_TYPES[link.type]?.dash || null;
  }, []);

  // ── Convex hulls ──
  const paintClusters = useCallback((ctx, globalScale) => {
    if (!showClusters) return;
    const nodeMap = {};
    graphData.nodes.forEach(n => { nodeMap[n.id] = n; });

    clusters.forEach(cluster => {
      const points = cluster.members
        .map(id => nodeMap[id])
        .filter(n => n && n.x != null && n.y != null)
        .map(n => [n.x, n.y]);
      if (points.length < 2) return;

      ctx.save();

      if (points.length === 2) {
        const [[x1, y1], [x2, y2]] = points;
        const pad = 25;
        const dx = x2 - x1, dy = y2 - y1;
        const len = Math.sqrt(dx * dx + dy * dy) || 1;
        const nx = -dy / len * pad, ny = dx / len * pad;
        ctx.beginPath();
        ctx.arc(x1, y1, pad, Math.atan2(-nx, ny), Math.atan2(nx, -ny));
        ctx.arc(x2, y2, pad, Math.atan2(nx, -ny), Math.atan2(-nx, ny));
        ctx.closePath();
        ctx.fillStyle = cluster.color;
        ctx.fill();
        ctx.lineWidth = 1.5 / globalScale;
        ctx.strokeStyle = cluster.borderColor;
        ctx.setLineDash([4 / globalScale, 3 / globalScale]);
        ctx.stroke();
        ctx.setLineDash([]);
        const cx = (x1 + x2) / 2, cy = (y1 + y2) / 2 - pad - 5;
        const fs = Math.max(8, 9 / globalScale);
        ctx.font = `${fs}px Inter, system-ui, sans-serif`;
        ctx.textAlign = "center";
        ctx.fillStyle = cluster.borderColor.replace(/[\d.]+\)$/, "0.5)");
        ctx.fillText(cluster.label, cx, cy);
      } else {
        const hull = polygonHull(points);
        if (!hull) { ctx.restore(); return; }
        ctx.beginPath();
        hull.forEach(([x, y], i) => { i === 0 ? ctx.moveTo(x, y) : ctx.lineTo(x, y); });
        ctx.closePath();
        ctx.lineWidth = 30;
        ctx.lineJoin = "round";
        ctx.strokeStyle = cluster.color;
        ctx.stroke();
        ctx.fillStyle = cluster.color;
        ctx.fill();
        ctx.beginPath();
        hull.forEach(([x, y], i) => { i === 0 ? ctx.moveTo(x, y) : ctx.lineTo(x, y); });
        ctx.closePath();
        ctx.lineWidth = 1.5 / globalScale;
        ctx.lineJoin = "round";
        ctx.strokeStyle = cluster.borderColor;
        ctx.setLineDash([4 / globalScale, 3 / globalScale]);
        ctx.stroke();
        const cx = points.reduce((s, p) => s + p[0], 0) / points.length;
        const cy = points.reduce((s, p) => s + p[1], 0) / points.length - 25;
        const fs = Math.max(8, 9 / globalScale);
        ctx.font = `${fs}px Inter, system-ui, sans-serif`;
        ctx.textAlign = "center";
        ctx.fillStyle = cluster.borderColor.replace(/[\d.]+\)$/, "0.5)");
        ctx.setLineDash([]);
        ctx.fillText(cluster.label, cx, cy);
      }
      ctx.restore();
    });
  }, [graphData, showClusters, clusters]);

  // ── Export ──
  const exportPNG = useCallback(() => {
    const canvas = containerRef.current?.querySelector("canvas");
    if (!canvas) return;
    const a = document.createElement("a");
    a.download = `director-network-${ticker || "takeda"}-${year}.png`;
    a.href = canvas.toDataURL("image/png");
    a.click();
  }, [year, ticker]);

  const exportCSV = useCallback(() => {
    const header = "Name,Name_JP,Role,Company,Independent,Board_Seats,University,Committees,Independence_Flagged\n";
    const rows = graphData.nodes.map(n =>
      [n.nameEn, n.nameJp || "", n.role, n.company, n.isIndependent, n.boardSeats, n.university, (n.committees || []).join(";"), n.independenceScore?.isFlagged || false].map(v => `"${v}"`).join(",")
    ).join("\n");
    const blob = new Blob([header + rows], { type: "text/csv" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.download = `director-data-${ticker || "takeda"}-${year}.csv`;
    a.href = url;
    a.click();
    URL.revokeObjectURL(url);
  }, [graphData, year, ticker]);

  // ── Fit graph ──
  useEffect(() => {
    if (fgRef.current && graphData.nodes.length) {
      const t = setTimeout(() => fgRef.current?.zoomToFit(600, 60), 400);
      return () => clearTimeout(t);
    }
  }, [graphData]);

  useEffect(() => {
    if (fgRef.current) {
      fgRef.current.d3Force("charge")?.strength(-250);
      fgRef.current.d3Force("link")?.distance(link => 80 + (6 - (link.weight || 1)) * 15);
    }
  }, [graphData]);

  // ── Loading screen ──
  if (loading) {
    return <LoadingScreen companyName={companyName} ticker={ticker} />;
  }

  if (loadError && (!rawDirectors || rawDirectors.length === 0)) {
    return (
      <div className="h-dvh flex flex-col items-center justify-center bg-[#0A0E1A] px-6 text-center">
        <AlertTriangle className="w-10 h-10 text-amber-400 mb-4" />
        <h2 className="text-lg font-semibold text-white mb-2">Could not load director data</h2>
        <p className="text-sm text-gray-500 max-w-md mb-6">{loadError}</p>
        <div className="flex gap-3">
          <Link to="/" state={{ openContent: true }} className="px-4 py-2 rounded-lg bg-white/[0.06] border border-white/[0.08] text-sm text-gray-300 hover:bg-white/[0.1] transition-colors">
            Go back
          </Link>
          <button onClick={() => window.location.reload()} className="px-4 py-2 rounded-lg bg-blue-600 text-sm text-white hover:bg-blue-500 transition-colors">
            Retry
          </button>
        </div>
      </div>
    );
  }

  // ── Render ──
  return (
    <div className="h-dvh flex flex-col overflow-hidden bg-[#0A0E1A]" onContextMenu={e => e.preventDefault()}>

      {/* ━━ Stats Bar ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ */}
      <div className="h-12 shrink-0 border-b border-white/[0.06] bg-[#080C16] flex items-center px-4 gap-6 z-40">
        <Link to="/" state={{ openContent: true }} className="flex items-center gap-1.5 text-gray-500 hover:text-gray-300 transition-colors text-xs shrink-0">
          <ArrowLeft className="w-3.5 h-3.5" />
          <span className="hidden sm:inline">Back</span>
        </Link>
        <div className="h-4 w-px bg-white/10" />
        <h1 className="text-sm font-semibold text-white whitespace-nowrap">
          {companyName} <span className="text-gray-500 font-normal ml-1.5">Board Network</span>
          {ticker && <span className="text-blue-400 font-mono text-xs ml-2">{ticker}</span>}
        </h1>
        <div className="flex-1" />

        <div className="hidden lg:flex items-center gap-5 text-[11px]">
          <StatPill icon={Users} label="Board Members" value={stats.totalDirectors} />
          <StatPill icon={Link2} label="Avg Board Seats" value={stats.avgSeats} />
          <StatPill icon={Activity} label="Connectedness" value={`${stats.density}%`} />
          <StatPill icon={AlertTriangle} label="Multi-Board (3+)" value={stats.overboarded} warn={stats.overboarded > 0} />
          <StatPill icon={Shield} label="Independence Risk" value={stats.flagged} warn={stats.flagged > 0} />
          <div className="text-gray-500">
            Most Connected: <span className="text-gray-300 font-mono">{stats.mostConnected.name}</span>
            <span className="text-gray-600 ml-1">({stats.mostConnected.conns})</span>
          </div>
        </div>

        <div className="flex items-center gap-1.5 ml-3">
          <button onClick={exportPNG} className="flex items-center gap-1 px-2 py-1 rounded-md hover:bg-white/[0.06] text-gray-500 hover:text-gray-300 transition-colors text-[10px]" title="Export PNG">
            <Download className="w-3 h-3" /><span>PNG</span>
          </button>
          <button onClick={exportCSV} className="flex items-center gap-1 px-2 py-1 rounded-md hover:bg-white/[0.06] text-gray-500 hover:text-gray-300 transition-colors text-[10px]" title="Export CSV">
            <Download className="w-3 h-3" /><span>CSV</span>
          </button>
        </div>
      </div>

      {/* ━━ Main area ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ */}
      <div className="flex-1 flex overflow-hidden relative">

        {/* ── Filter sidebar ── */}
        <AnimatePresence initial={false}>
          {filterOpen && (
            <motion.aside
              initial={{ width: 0, opacity: 0 }}
              animate={{ width: 260, opacity: 1 }}
              exit={{ width: 0, opacity: 0 }}
              transition={{ duration: 0.2 }}
              className="shrink-0 border-r border-white/[0.06] bg-[#080C16] overflow-hidden z-30"
              style={{ maxWidth: "75vw" }}
            >
              <div style={{ width: "min(260px, 75vw)" }} className="h-full overflow-y-auto p-4 space-y-5">
                <div className="flex items-center justify-between">
                  <h3 className="text-xs font-semibold text-gray-400 uppercase tracking-widest">Filters</h3>
                  <button onClick={() => setFilterOpen(false)} className="text-gray-500 hover:text-gray-300">
                    <X className="w-4 h-4" />
                  </button>
                </div>

                <div className="relative">
                  <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 w-3.5 h-3.5 text-gray-500" />
                  <input
                    type="text" value={searchQuery} onChange={e => setSearchQuery(e.target.value)}
                    placeholder="Search director..."
                    className="w-full pl-8 pr-3 py-2 rounded-lg bg-white/[0.04] border border-white/[0.08] text-sm text-gray-300 placeholder:text-gray-600 outline-none focus:border-blue-500/40"
                  />
                </div>

                <div>
                  <h4 className="text-[10px] font-semibold text-gray-500 uppercase mb-2">Connection Types</h4>
                  {Object.entries(CONNECTION_TYPES).map(([key, cfg]) => (
                    <label key={key} className="flex items-center gap-2.5 py-1.5 cursor-pointer group"
                      onClick={() => setConnToggles(prev => ({ ...prev, [key]: !prev[key] }))}>
                      <div className={`w-3.5 h-3.5 rounded border transition-colors ${connToggles[key] ? "bg-blue-500 border-blue-500" : "border-gray-600 group-hover:border-gray-500"}`}>
                        {connToggles[key] && <svg viewBox="0 0 14 14" className="w-3.5 h-3.5 text-white"><path d="M3 7l3 3 5-5" stroke="currentColor" strokeWidth="2" fill="none" /></svg>}
                      </div>
                      <div className="w-4 h-0.5 rounded-full" style={{ backgroundColor: cfg.color }} />
                      <span className="text-xs text-gray-400 group-hover:text-gray-300">{cfg.label}</span>
                    </label>
                  ))}
                </div>

                <div>
                  <h4 className="text-[10px] font-semibold text-gray-500 uppercase mb-2">Quick Filters</h4>
                  <ToggleFilter label="Independent directors only" active={showIndependentOnly} onToggle={() => setShowIndependentOnly(!showIndependentOnly)} />
                  <ToggleFilter label="Multi-board directors (3+ seats)" active={showOverboardedOnly} onToggle={() => setShowOverboardedOnly(!showOverboardedOnly)} />
                  <ToggleFilter label={`${companyName} executives only`} active={showInternalOnly} onToggle={() => setShowInternalOnly(!showInternalOnly)} />
                  <ToggleFilter label="Show relationship groups" active={showClusters} onToggle={() => setShowClusters(!showClusters)} />
                </div>

                <div>
                  <h4 className="text-[10px] font-semibold text-gray-500 uppercase mb-2">What You're Seeing</h4>
                  <div className="space-y-2 text-[10px] text-gray-500">
                    <div className="flex items-center gap-2">
                      <div className="w-3 h-3 rounded-full bg-rose-500/40 border border-rose-500" />
                      <span>Company executive (red glow)</span>
                    </div>
                    <div className="flex items-center gap-2">
                      <div className="w-3 h-3 rounded-full border-2 border-orange-500" />
                      <span>Sits on 3+ boards (orange pulse) — may be too busy</span>
                    </div>
                    <div className="flex items-center gap-2">
                      <div className="w-3 h-3 rounded-full border border-dashed border-red-500" />
                      <span>Independence concern — too many insider ties</span>
                    </div>
                    <div className="flex items-center gap-2">
                      <div className="w-2 h-2 rounded-full bg-green-500" />
                      <span>Truly independent director</span>
                    </div>
                    <div className="flex items-center gap-2">
                      <div className="w-2 h-2 rounded-full bg-red-500" />
                      <span>Independence flagged — investigate further</span>
                    </div>
                    <p className="text-gray-600 mt-2 leading-relaxed">
                      Lines show relationships between directors. Click any person to see their full profile, career history, and LinkedIn.
                    </p>
                    <p className="text-gray-600 leading-relaxed">
                      Right-click a person for quick links to LinkedIn, Google, and EDINET filings.
                    </p>
                  </div>
                </div>

                {loadError && (
                  <div className="rounded-lg p-3 bg-amber-500/5 border border-amber-500/20">
                    <p className="text-[10px] text-amber-400 font-semibold">Using demo data</p>
                    <p className="text-[10px] text-amber-400/70 mt-1">Could not fetch live data. Showing Takeda example.</p>
                  </div>
                )}
              </div>
            </motion.aside>
          )}
        </AnimatePresence>

        {!filterOpen && (
          <button onClick={() => setFilterOpen(true)}
            className="absolute left-3 top-3 z-30 p-2 rounded-lg bg-white/[0.06] border border-white/[0.08] text-gray-500 hover:text-gray-300 hover:bg-white/[0.1] transition-colors"
            title="Filters">
            <Filter className="w-4 h-4" />
          </button>
        )}

        {/* ── Graph canvas ── */}
        <div ref={containerRef} className="flex-1 relative overflow-hidden" style={{ minHeight: 0 }}>
          <ForceGraph2D
            ref={fgRef}
            graphData={graphData}
            width={dimensions.width}
            height={dimensions.height}
            nodeId="id"
            nodeCanvasObject={paintNode}
            nodeCanvasObjectMode={() => "replace"}
            nodePointerAreaPaint={paintNodeArea}
            linkColor={getLinkColor}
            linkWidth={getLinkWidth}
            linkLineDash={getLinkDash}
            linkHoverPrecision={6}
            onNodeClick={handleNodeClick}
            onNodeHover={handleNodeHover}
            onNodeRightClick={handleNodeRightClick}
            onLinkHover={handleLinkHover}
            onBackgroundClick={handleBackgroundClick}
            onRenderFramePre={paintClusters}
            cooldownTime={3000}
            autoPauseRedraw={false}
            enableNodeDrag={true}
            backgroundColor="#0A0E1A"
          />

          <div className="absolute right-3 top-3 flex flex-col gap-1.5 z-20">
            <button onClick={() => fgRef.current?.zoomToFit(400, 40)} className="p-2 rounded-lg bg-black/40 backdrop-blur-sm border border-white/[0.08] text-gray-400 hover:text-white transition-colors" title="Fit to view">
              <Maximize2 className="w-3.5 h-3.5" />
            </button>
            <button onClick={() => fgRef.current?.zoom(fgRef.current.zoom() * 1.3, 200)} className="p-2 rounded-lg bg-black/40 backdrop-blur-sm border border-white/[0.08] text-gray-400 hover:text-white transition-colors" title="Zoom in">
              <ZoomIn className="w-3.5 h-3.5" />
            </button>
            <button onClick={() => fgRef.current?.zoom(fgRef.current.zoom() * 0.7, 200)} className="p-2 rounded-lg bg-black/40 backdrop-blur-sm border border-white/[0.08] text-gray-400 hover:text-white transition-colors" title="Zoom out">
              <ZoomOut className="w-3.5 h-3.5" />
            </button>
            <button onClick={() => fgRef.current?.d3ReheatSimulation()} className="p-2 rounded-lg bg-black/40 backdrop-blur-sm border border-white/[0.08] text-gray-400 hover:text-white transition-colors" title="Reset layout">
              <RotateCcw className="w-3.5 h-3.5" />
            </button>
          </div>

          {/* ── Board Insights overlay (bottom-left) ── */}
          {boardSummary && (
            <div className="absolute left-3 bottom-3 z-20">
              <AnimatePresence>
                {insightsOpen ? (
                  <motion.div
                    key="insights-panel"
                    initial={{ opacity: 0, y: 20 }}
                    animate={{ opacity: 1, y: 0 }}
                    exit={{ opacity: 0, y: 20 }}
                    transition={{ duration: 0.2 }}
                    className="w-[320px] max-w-[90vw] bg-[#0D1117]/95 backdrop-blur-md border border-white/[0.08] rounded-xl shadow-2xl overflow-hidden"
                  >
                    <div className="flex items-center justify-between px-4 py-2.5 border-b border-white/[0.06]">
                      <div className="flex items-center gap-2">
                        <BarChart3 className="w-3.5 h-3.5 text-blue-400" />
                        <span className="text-xs font-semibold text-white">Board Insights</span>
                      </div>
                      <button onClick={() => setInsightsOpen(false)} className="text-gray-500 hover:text-gray-300 p-0.5">
                        <X className="w-3.5 h-3.5" />
                      </button>
                    </div>
                    <div className="p-4 space-y-3">
                      {/* Governance metrics grid */}
                      <div className="grid grid-cols-3 gap-2">
                        <div className="bg-white/[0.03] rounded-lg p-2 text-center border border-white/[0.04]">
                          <p className="text-[9px] text-gray-500 uppercase">Board Size</p>
                          <p className="text-base font-bold text-white font-mono">{boardSummary.totalMembers || stats.totalDirectors}</p>
                        </div>
                        <div className="bg-white/[0.03] rounded-lg p-2 text-center border border-white/[0.04]">
                          <p className="text-[9px] text-gray-500 uppercase">Independent</p>
                          <p className={`text-base font-bold font-mono ${
                            boardSummary.totalMembers && boardSummary.independent / boardSummary.totalMembers >= 0.5
                              ? "text-green-400" : "text-orange-400"
                          }`}>
                            {boardSummary.independent ?? "—"}
                            <span className="text-[10px] text-gray-500 font-normal">/{boardSummary.totalMembers || "?"}</span>
                          </p>
                        </div>
                        <div className="bg-white/[0.03] rounded-lg p-2 text-center border border-white/[0.04]">
                          <p className="text-[9px] text-gray-500 uppercase">Internal</p>
                          <p className="text-base font-bold text-rose-400 font-mono">{boardSummary.internal ?? "—"}</p>
                        </div>
                      </div>

                      {/* Diversity & Tenure row */}
                      <div className="grid grid-cols-3 gap-2">
                        <div className="bg-white/[0.03] rounded-lg p-2 text-center border border-white/[0.04]">
                          <p className="text-[9px] text-gray-500 uppercase">Women</p>
                          <p className={`text-base font-bold font-mono ${
                            boardSummary.women > 0 ? "text-purple-400" : "text-gray-600"
                          }`}>{boardSummary.women ?? "—"}</p>
                        </div>
                        <div className="bg-white/[0.03] rounded-lg p-2 text-center border border-white/[0.04]">
                          <p className="text-[9px] text-gray-500 uppercase">Foreign</p>
                          <p className={`text-base font-bold font-mono ${
                            boardSummary.foreignNationals > 0 ? "text-blue-400" : "text-gray-600"
                          }`}>{boardSummary.foreignNationals ?? "—"}</p>
                        </div>
                        <div className="bg-white/[0.03] rounded-lg p-2 text-center border border-white/[0.04]">
                          <p className="text-[9px] text-gray-500 uppercase">Avg Tenure</p>
                          <p className="text-base font-bold text-gray-300 font-mono">
                            {boardSummary.avgTenure ? `${boardSummary.avgTenure}y` : "—"}
                          </p>
                        </div>
                      </div>

                      {/* Independence ratio bar */}
                      {boardSummary.totalMembers > 0 && (
                        <div>
                          <div className="flex justify-between text-[10px] text-gray-500 mb-1">
                            <span>Independence Ratio</span>
                            <span className="font-mono">
                              {boardSummary.totalMembers ? Math.round((boardSummary.independent / boardSummary.totalMembers) * 100) : 0}%
                            </span>
                          </div>
                          <div className="w-full h-2 bg-white/[0.04] rounded-full overflow-hidden">
                            <div
                              className={`h-full rounded-full transition-all ${
                                boardSummary.totalMembers && boardSummary.independent / boardSummary.totalMembers >= 0.5
                                  ? "bg-green-500" : "bg-orange-500"
                              }`}
                              style={{ width: `${boardSummary.totalMembers ? (boardSummary.independent / boardSummary.totalMembers) * 100 : 0}%` }}
                            />
                          </div>
                          <p className="text-[9px] text-gray-600 mt-1">
                            {boardSummary.totalMembers && boardSummary.independent / boardSummary.totalMembers >= 0.5
                              ? "Meets majority-independent standard"
                              : "Below majority-independent threshold — governance risk"}
                          </p>
                        </div>
                      )}

                      {/* Social presence summary */}
                      {(() => {
                        const nodes = graphData.nodes;
                        const withLinkedin = nodes.filter(n => n.linkedinUrl).length;
                        const withWikipedia = nodes.filter(n => n.socialProfiles?.wikipedia).length;
                        const total = withLinkedin + withWikipedia;
                        if (total === 0) return null;
                        return (
                          <div>
                            <p className="text-[9px] text-gray-500 uppercase mb-1.5">Online Presence</p>
                            <div className="flex flex-wrap gap-2 text-[10px]">
                              {withLinkedin > 0 && (
                                <span className="flex items-center gap-1 text-[#0A66C2]">
                                  <Linkedin className="w-3 h-3" />{withLinkedin}/{nodes.length}
                                </span>
                              )}
                              {withWikipedia > 0 && (
                                <span className="flex items-center gap-1 text-gray-400">
                                  <BookOpen className="w-3 h-3" />{withWikipedia}/{nodes.length}
                                </span>
                              )}
                            </div>
                          </div>
                        );
                      })()}

                      {/* Committees */}
                      {boardSummary.committees?.length > 0 && (
                        <div>
                          <p className="text-[9px] text-gray-500 uppercase mb-1.5">Key Committees</p>
                          <div className="flex flex-wrap gap-1.5">
                            {boardSummary.committees.map((c, i) => (
                              <span key={i} className="text-[10px] px-2 py-0.5 rounded-full bg-amber-500/10 border border-amber-500/20 text-amber-400">{c}</span>
                            ))}
                          </div>
                        </div>
                      )}

                      {/* AI insight */}
                      {boardSummary.insight && (
                        <div className="bg-blue-500/5 border border-blue-500/15 rounded-lg p-2.5">
                          <div className="flex items-start gap-2">
                            <Info className="w-3.5 h-3.5 text-blue-400 shrink-0 mt-0.5" />
                            <p className="text-[11px] text-blue-300/80 leading-relaxed">{boardSummary.insight}</p>
                          </div>
                        </div>
                      )}
                    </div>
                  </motion.div>
                ) : (
                  <motion.button
                    key="insights-btn"
                    initial={{ opacity: 0 }}
                    animate={{ opacity: 1 }}
                    exit={{ opacity: 0 }}
                    onClick={() => setInsightsOpen(true)}
                    className="flex items-center gap-2 px-3 py-2 rounded-lg bg-black/40 backdrop-blur-sm border border-white/[0.08] text-gray-400 hover:text-white transition-colors text-xs"
                  >
                    <BarChart3 className="w-3.5 h-3.5" />
                    Board Insights
                  </motion.button>
                )}
              </AnimatePresence>
            </div>
          )}

          {hoveredNode && !selectedNode && (
            <div className="absolute z-50 pointer-events-none" style={{ left: tooltipPos.x + 16, top: tooltipPos.y - 10 }}>
              <NodeTooltip node={hoveredNode} />
            </div>
          )}

          {hoveredLink && (
            <div className="absolute z-50 pointer-events-none" style={{ left: linkTooltipPos.x + 12, top: linkTooltipPos.y - 8 }}>
              <div className="bg-[#151923] border border-white/[0.1] rounded-lg px-3 py-2 shadow-xl max-w-xs">
                <div className="flex items-center gap-2 mb-1">
                  <div className="w-3 h-0.5 rounded" style={{ backgroundColor: CONNECTION_TYPES[hoveredLink.type]?.color }} />
                  <span className="text-[10px] font-semibold text-gray-400 uppercase">{CONNECTION_TYPES[hoveredLink.type]?.label}</span>
                </div>
                <p className="text-xs text-gray-300">{hoveredLink.detail}</p>
                <p className="text-[10px] text-gray-600 mt-1">Weight: {hoveredLink.weight}/5</p>
              </div>
            </div>
          )}

          {contextMenu && (
            <div className="absolute z-50 bg-[#151923]/95 backdrop-blur-md border border-white/[0.1] rounded-xl shadow-2xl py-1.5 min-w-[200px]"
              style={{ left: contextMenu.x, top: contextMenu.y }}>
              <div className="px-3 py-1.5 border-b border-white/[0.06]">
                <p className="text-xs font-semibold text-white truncate">{contextMenu.node.nameEn}</p>
                <p className="text-[10px] text-gray-500 truncate">{contextMenu.node.role}</p>
              </div>
              {contextMenu.node.linkedinUrl ? (
                <button className="w-full text-left px-3 py-2 text-xs text-gray-300 hover:bg-white/[0.06] flex items-center gap-2" onClick={() => { window.open(contextMenu.node.linkedinUrl, "_blank"); setContextMenu(null); }}>
                  <Linkedin className="w-3.5 h-3.5 text-[#0A66C2]" /> Open LinkedIn Profile
                  <ExternalLink className="w-3 h-3 text-gray-600 ml-auto" />
                </button>
              ) : (
                <button className="w-full text-left px-3 py-2 text-xs text-gray-300 hover:bg-white/[0.06] flex items-center gap-2" onClick={() => { window.open(`https://www.linkedin.com/search/results/people/?keywords=${encodeURIComponent(contextMenu.node.nameEn)}`, "_blank"); setContextMenu(null); }}>
                  <Linkedin className="w-3.5 h-3.5 text-gray-500" /> Search LinkedIn
                  <ExternalLink className="w-3 h-3 text-gray-600 ml-auto" />
                </button>
              )}
              <button className="w-full text-left px-3 py-2 text-xs text-gray-300 hover:bg-white/[0.06] flex items-center gap-2" onClick={() => { window.open(`https://www.google.com/search?q=${encodeURIComponent(contextMenu.node.nameEn + " " + companyName + " director")}`, "_blank"); setContextMenu(null); }}>
                <Search className="w-3.5 h-3.5 text-gray-500" /> Search Google
                <ExternalLink className="w-3 h-3 text-gray-600 ml-auto" />
              </button>
              <button className="w-full text-left px-3 py-2 text-xs text-gray-300 hover:bg-white/[0.06] flex items-center gap-2" onClick={() => { window.open(`https://disclosure2dl.edinet-fsa.go.jp/searchdocument/pdf?q=${ticker || "4502"}+${contextMenu.node.nameEn}`, "_blank"); setContextMenu(null); }}>
                <Eye className="w-3.5 h-3.5 text-blue-400" /> EDINET Filings
                <ExternalLink className="w-3 h-3 text-gray-600 ml-auto" />
              </button>
              {contextMenu.node.socialProfiles?.wikipedia && (
                <button className="w-full text-left px-3 py-2 text-xs text-gray-300 hover:bg-white/[0.06] flex items-center gap-2" onClick={() => { window.open(contextMenu.node.socialProfiles.wikipedia, "_blank"); setContextMenu(null); }}>
                  <BookOpen className="w-3.5 h-3.5 text-gray-400" /> Wikipedia
                  <ExternalLink className="w-3 h-3 text-gray-600 ml-auto" />
                </button>
              )}
              <div className="border-t border-white/[0.06] my-1" />
              <button className="w-full text-left px-3 py-2 text-xs text-gray-300 hover:bg-white/[0.06] flex items-center gap-2" onClick={() => { handleNodeClick(contextMenu.node); setContextMenu(null); }}>
                <Activity className="w-3.5 h-3.5 text-purple-400" /> Show Full Network
              </button>
            </div>
          )}
        </div>

        {/* ── Detail panel ── */}
        <AnimatePresence>
          {detailOpen && selectedNode && (
            <motion.aside
              initial={{ width: 0, opacity: 0 }}
              animate={{ width: 340, opacity: 1 }}
              exit={{ width: 0, opacity: 0 }}
              transition={{ duration: 0.25, ease: "easeInOut" }}
              className="shrink-0 border-l border-white/[0.06] bg-[#080C16] overflow-hidden z-30"
              style={{ maxWidth: "85vw" }}
            >
              <div style={{ width: "min(340px, 85vw)" }} className="h-full overflow-y-auto">
                <DetailPanel
                  node={selectedNode}
                  connections={linksByNode[selectedNode.id] || []}
                  graphNodes={graphData.nodes}
                  companyName={companyName}
                  onClose={() => { setDetailOpen(false); setSelectedNode(null); setHighlightNodes(new Set()); setHighlightLinks(new Set()); }}
                />
              </div>
            </motion.aside>
          )}
        </AnimatePresence>
      </div>

      {/* ━━ Timeline slider ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ */}
      <div className="h-[60px] shrink-0 border-t border-white/[0.06] bg-[#080C16] flex items-center px-6 gap-4 z-40">
        <span className="text-[10px] font-semibold text-gray-500 uppercase tracking-widest whitespace-nowrap">Timeline</span>
        <div className="flex items-center gap-3 flex-1">
          <button onClick={() => setYear(Math.max(2020, year - 1))} className="p-1 text-gray-500 hover:text-gray-300">
            <ChevronLeft className="w-4 h-4" />
          </button>
          <div className="flex-1 relative">
            <input type="range" min={2020} max={2025} step={1} value={year} onChange={e => setYear(Number(e.target.value))}
              className="w-full h-1.5 appearance-none bg-white/[0.06] rounded-full cursor-pointer [&::-webkit-slider-thumb]:appearance-none [&::-webkit-slider-thumb]:w-4 [&::-webkit-slider-thumb]:h-4 [&::-webkit-slider-thumb]:rounded-full [&::-webkit-slider-thumb]:bg-blue-500 [&::-webkit-slider-thumb]:border-2 [&::-webkit-slider-thumb]:border-blue-300 [&::-webkit-slider-thumb]:shadow-[0_0_8px_rgba(59,130,246,0.4)] [&::-webkit-slider-thumb]:cursor-pointer"
            />
            <div className="flex justify-between mt-1 px-0.5">
              {[2020, 2021, 2022, 2023, 2024, 2025].map(y => (
                <button key={y} onClick={() => setYear(y)} className={`text-[10px] font-mono transition-colors ${y === year ? "text-blue-400 font-bold" : "text-gray-600 hover:text-gray-400"}`}>
                  {y}
                </button>
              ))}
            </div>
          </div>
          <button onClick={() => setYear(Math.min(2025, year + 1))} className="p-1 text-gray-500 hover:text-gray-300">
            <ChevronRight className="w-4 h-4" />
          </button>
        </div>
        <div className="text-sm font-mono text-blue-400 font-bold tabular-nums w-12 text-right">{year}</div>
      </div>
    </div>
  );
}

/* ── Sub-components ──────────────────────────────────────── */

function StatPill({ icon: Icon, label, value, warn }) {
  return (
    <div className="flex items-center gap-1.5">
      <Icon className={`w-3 h-3 ${warn ? "text-orange-400" : "text-gray-600"}`} />
      <span className="text-gray-500">{label}:</span>
      <span className={`font-mono ${warn ? "text-orange-400 font-bold" : "text-gray-300"}`}>{value}</span>
    </div>
  );
}

function ToggleFilter({ label, active, onToggle }) {
  return (
    <label className="flex items-center gap-2.5 py-1.5 cursor-pointer group">
      <button onClick={onToggle} className={`w-8 h-4 rounded-full transition-colors relative ${active ? "bg-blue-500" : "bg-white/[0.08]"}`}>
        <div className={`absolute top-0.5 w-3 h-3 rounded-full bg-white shadow transition-transform ${active ? "translate-x-4" : "translate-x-0.5"}`} />
      </button>
      <span className="text-xs text-gray-400 group-hover:text-gray-300">{label}</span>
    </label>
  );
}

function NodeTooltip({ node }) {
  const flagged = node.independenceScore?.isFlagged;
  return (
    <div className="bg-[#151923]/95 backdrop-blur-md border border-white/[0.1] rounded-xl px-4 py-3 shadow-2xl min-w-[240px] max-w-[320px]">
      <div className="flex items-start justify-between gap-3">
        <div>
          <p className="text-sm font-semibold text-white">{node.nameEn}</p>
          <p className="text-[11px] text-gray-500 mt-0.5">{node.role}</p>
        </div>
        <div className="flex gap-1 shrink-0">
          {node.isIndependent && (
            <span className={`text-[9px] font-bold px-1.5 py-0.5 rounded ${flagged ? "bg-red-500/20 text-red-400" : "bg-green-500/20 text-green-400"}`}>
              {flagged ? "FLAGGED" : "Independent"}
            </span>
          )}
          {node.type === "internal" && (
            <span className="text-[9px] font-bold px-1.5 py-0.5 rounded bg-rose-500/20 text-rose-400">
              Executive
            </span>
          )}
        </div>
      </div>
      <div className="flex gap-3 mt-2 text-[10px]">
        <span className="text-gray-500">Company: <span className="text-gray-300">{node.company}</span></span>
        <span className="text-gray-500">Seats: <span className={`font-mono ${node.boardSeats >= OVERBOARD_THRESHOLD ? "text-orange-400 font-bold" : "text-gray-300"}`}>{node.boardSeats}</span></span>
      </div>
      <div className="flex flex-wrap gap-x-3 gap-y-0.5 mt-1.5 text-[10px]">
        {node.gender && <span className="text-gray-500">Gender: <span className="text-gray-400">{node.gender}</span></span>}
        {node.nationality && <span className="text-gray-500">Nationality: <span className="text-gray-400">{node.nationality}</span></span>}
      </div>
      {node.expertise?.length > 0 && (
        <div className="flex flex-wrap gap-1 mt-1.5">
          {node.expertise.slice(0, 3).map((e, i) => (
            <span key={i} className="text-[9px] px-1.5 py-0.5 rounded bg-white/[0.06] text-gray-400">{e}</span>
          ))}
        </div>
      )}
      {node.university && (
        <p className="text-[10px] text-gray-500 mt-1"><GraduationCap className="w-3 h-3 inline mr-1" /><span className="text-gray-400">{node.university}</span></p>
      )}
      {/* Social presence indicators */}
      {(node.linkedinUrl || node.socialProfiles?.wikipedia) && (
        <div className="mt-2 flex items-center gap-3 text-[10px]">
          {node.linkedinUrl && (
            <span className="flex items-center gap-1 text-[#0A66C2]"><Linkedin className="w-3 h-3" />LinkedIn</span>
          )}
          {node.socialProfiles?.wikipedia && (
            <span className="flex items-center gap-1 text-gray-400"><BookOpen className="w-3 h-3" />Wikipedia</span>
          )}
        </div>
      )}
      {flagged && (
        <div className="mt-2 px-2 py-1.5 rounded-md bg-red-500/10 border border-red-500/20">
          <p className="text-[10px] text-red-400 font-semibold">Independence Questionable</p>
          <p className="text-[10px] text-red-400/70">{node.independenceScore?.insiderConnections} insider connections</p>
        </div>
      )}
      <p className="text-[9px] text-gray-600 mt-2">Click for details / Right-click for actions</p>
    </div>
  );
}

function DetailPanel({ node, connections, graphNodes, companyName, onClose }) {
  const flagged = node.independenceScore?.isFlagged;
  const nodeMap = {};
  graphNodes.forEach(n => { nodeMap[n.id] = n; });

  return (
    <div className="p-5 space-y-4">
      {/* Header */}
      <div className="flex items-start justify-between">
        <div className="flex-1 min-w-0">
          <h2 className="text-lg font-bold text-white truncate">{node.nameEn}</h2>
          <p className="text-xs text-gray-400 mt-0.5">{node.role}</p>
        </div>
        <button onClick={onClose} className="text-gray-500 hover:text-gray-300 p-1 shrink-0"><X className="w-4 h-4" /></button>
      </div>

      {/* Tags */}
      <div className="flex items-center gap-1.5 flex-wrap">
        <span className="text-[10px] px-2 py-0.5 rounded-full font-semibold" style={{ backgroundColor: node._color + "20", color: node._color }}>
          {node.company}
        </span>
        {node.type === "internal" ? (
          <span className="text-[10px] px-2 py-0.5 rounded-full font-semibold bg-rose-500/15 text-rose-400">Executive</span>
        ) : (
          <span className="text-[10px] px-2 py-0.5 rounded-full font-semibold bg-blue-500/15 text-blue-400">Outside Director</span>
        )}
        {node.isIndependent && (
          <span className={`text-[10px] px-2 py-0.5 rounded-full font-semibold ${flagged ? "bg-red-500/20 text-red-400" : "bg-green-500/20 text-green-400"}`}>
            {flagged ? "Independence Questionable" : "Independent"}
          </span>
        )}
        {node.boardSeats >= OVERBOARD_THRESHOLD && (
          <span className="text-[10px] px-2 py-0.5 rounded-full bg-orange-500/20 text-orange-400 font-semibold">
            Overboarded ({node.boardSeats} seats)
          </span>
        )}
      </div>

      {/* Action buttons — LinkedIn + Google */}
      <div className="flex gap-2">
        {node.linkedinUrl ? (
          <a href={node.linkedinUrl} target="_blank" rel="noopener noreferrer"
            className="flex-1 flex items-center justify-center gap-2 px-3 py-2 rounded-lg bg-[#0A66C2]/15 border border-[#0A66C2]/30 text-[#0A66C2] hover:bg-[#0A66C2]/25 transition-colors text-xs font-medium">
            <Linkedin className="w-3.5 h-3.5" />
            LinkedIn
            <ExternalLink className="w-3 h-3 opacity-50" />
          </a>
        ) : (
          <a href={`https://www.linkedin.com/search/results/people/?keywords=${encodeURIComponent(node.nameEn)}`}
            target="_blank" rel="noopener noreferrer"
            className="flex-1 flex items-center justify-center gap-2 px-3 py-2 rounded-lg bg-white/[0.03] border border-white/[0.08] text-gray-400 hover:text-gray-300 hover:bg-white/[0.06] transition-colors text-xs">
            <Linkedin className="w-3.5 h-3.5" />
            Search
            <ExternalLink className="w-3 h-3 opacity-40" />
          </a>
        )}
        <a href={`https://www.google.com/search?q=${encodeURIComponent(node.nameEn + " " + companyName + " director")}`}
          target="_blank" rel="noopener noreferrer"
          className="flex items-center justify-center gap-1.5 px-3 py-2 rounded-lg bg-white/[0.03] border border-white/[0.08] text-gray-400 hover:text-gray-300 hover:bg-white/[0.06] transition-colors text-xs"
          title="Search on Google">
          <Search className="w-3.5 h-3.5" />
        </a>
      </div>

      {/* Social profiles */}
      {node.socialProfiles?.wikipedia && (
        <div>
          <h4 className="text-[10px] font-semibold uppercase text-gray-500 mb-1.5">Online Presence</h4>
          <div className="flex gap-2 flex-wrap">
            {node.socialProfiles?.wikipedia && (
              <a href={node.socialProfiles.wikipedia} target="_blank" rel="noopener noreferrer"
                className="flex items-center gap-1.5 px-2.5 py-1.5 rounded-lg bg-white/[0.04] border border-white/[0.08] text-gray-300 hover:bg-white/[0.08] transition-colors text-[11px]">
                <BookOpen className="w-3.5 h-3.5" />
                <span>Wikipedia</span>
                <ExternalLink className="w-2.5 h-2.5 opacity-40" />
              </a>
            )}
          </div>
        </div>
      )}

      {node.bio && <p className="text-xs text-gray-400 leading-relaxed italic">{node.bio}</p>}

      {/* Expertise tags */}
      {node.expertise?.length > 0 && (
        <div className="flex flex-wrap gap-1.5">
          {node.expertise.map((e, i) => (
            <span key={i} className="text-[10px] px-2 py-0.5 rounded-full bg-blue-500/10 border border-blue-500/20 text-blue-400">{e}</span>
          ))}
        </div>
      )}

      {/* Demographics */}
      {(node.gender || node.nationality) && (
        <div className="flex gap-3 text-xs">
          {node.gender && (
            <span className="text-gray-500">Gender: <span className="text-gray-300">{node.gender}</span></span>
          )}
          {node.nationality && (
            <span className="text-gray-500 flex items-center gap-1">
              <Globe className="w-3 h-3" /> <span className="text-gray-300">{node.nationality}</span>
            </span>
          )}
        </div>
      )}

      {/* Stats grid */}
      <div className="grid grid-cols-3 gap-2">
        <div className="bg-white/[0.02] rounded-lg p-2.5 border border-white/[0.06] text-center">
          <p className="text-[9px] text-gray-500 uppercase">Seats</p>
          <p className="text-lg font-bold text-white font-mono">{node.boardSeats}</p>
        </div>
        <div className="bg-white/[0.02] rounded-lg p-2.5 border border-white/[0.06] text-center">
          <p className="text-[9px] text-gray-500 uppercase">Connections</p>
          <p className="text-lg font-bold text-white font-mono">{connections.length}</p>
        </div>
        <div className="bg-white/[0.02] rounded-lg p-2.5 border border-white/[0.06] text-center">
          <p className="text-[9px] text-gray-500 uppercase">Joined</p>
          <p className="text-lg font-bold text-white font-mono">{node.joinYear || "—"}</p>
        </div>
      </div>

      {/* Independence score */}
      {node.independenceScore && (
        <div className={`rounded-lg p-3 border ${flagged ? "bg-red-500/5 border-red-500/20" : "bg-white/[0.02] border-white/[0.06]"}`}>
          <h4 className="text-[10px] font-semibold uppercase text-gray-500 mb-2">Independence Analysis</h4>
          <div className="grid grid-cols-2 gap-2 text-xs">
            <div><span className="text-gray-500">Total ties:</span><span className="ml-1 text-gray-300 font-mono">{node.independenceScore?.totalConnections}</span></div>
            <div><span className="text-gray-500">Insider ties:</span><span className={`ml-1 font-mono ${flagged ? "text-red-400 font-bold" : "text-gray-300"}`}>{node.independenceScore?.insiderConnections}</span></div>
          </div>
          {node.independenceScore.details?.length > 0 && (
            <div className="mt-2 space-y-1">
              {node.independenceScore?.details?.map((d, i) => (
                <div key={i} className="text-[10px] text-gray-500">
                  <span className="text-red-400/80 font-mono">{nodeMap[d.insider]?.nameEn || d.insider}</span>
                  <span className="mx-1">&mdash;</span><span>{d.detail}</span>
                </div>
              ))}
            </div>
          )}
        </div>
      )}

      {/* Education */}
      {node.university && (
        <div>
          <h4 className="text-[10px] font-semibold uppercase text-gray-500 mb-1.5">Education</h4>
          <p className="text-xs text-gray-300">{node.university}</p>
        </div>
      )}

      {/* Career timeline */}
      {node.career?.length > 0 && (
        <div>
          <h4 className="text-[10px] font-semibold uppercase text-gray-500 mb-2">Career History</h4>
          <div className="relative pl-4 border-l border-white/[0.06] space-y-2.5">
            {node.career.map((c, i) => (
              <div key={i} className="relative">
                <div className="absolute -left-[18.5px] top-1 w-2 h-2 rounded-full bg-blue-500 border-2 border-[#080C16]" />
                <p className="text-xs text-gray-300 font-medium">{c.company}</p>
                <p className="text-[10px] text-gray-500">{c.role}</p>
                {c.years && <p className="text-[10px] text-gray-600 font-mono">{c.years}</p>}
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Other boards */}
      {node.otherBoards?.length > 0 && (
        <div>
          <h4 className="text-[10px] font-semibold uppercase text-gray-500 mb-1.5">Other Board Seats</h4>
          <div className="flex flex-wrap gap-1.5">
            {node.otherBoards.map((b, i) => (
              <span key={i} className="text-[10px] px-2 py-0.5 rounded-full bg-white/[0.04] border border-white/[0.08] text-gray-400">{b}</span>
            ))}
          </div>
        </div>
      )}

      {/* Committees */}
      {node.committees?.length > 0 && (
        <div>
          <h4 className="text-[10px] font-semibold uppercase text-gray-500 mb-1.5">{companyName} Committees</h4>
          <div className="flex flex-wrap gap-1.5">
            {node.committees.map((c, i) => (
              <span key={i} className="text-[10px] px-2 py-0.5 rounded-full bg-amber-500/10 border border-amber-500/20 text-amber-400">{c}</span>
            ))}
          </div>
        </div>
      )}

      {/* Connections list */}
      <div>
        <h4 className="text-[10px] font-semibold uppercase text-gray-500 mb-2">Connections ({connections.length})</h4>
        <div className="space-y-1.5">
          {connections.map((link, i) => {
            const otherId = (typeof link.source === "object" ? link.source.id : link.source) === node.id
              ? (typeof link.target === "object" ? link.target.id : link.target)
              : (typeof link.source === "object" ? link.source.id : link.source);
            const other = nodeMap[otherId];
            if (!other) return null;
            return (
              <div key={i} className="flex items-start gap-2 text-xs">
                <div className="w-2 h-2 rounded-full mt-1 shrink-0" style={{ backgroundColor: CONNECTION_TYPES[link.type]?.color }} />
                <div>
                  <span className="text-gray-300 font-medium">{other.nameEn}</span>
                  <span className="text-gray-600 ml-1.5">{CONNECTION_TYPES[link.type]?.label}</span>
                  <p className="text-[10px] text-gray-500">{link.detail}</p>
                </div>
              </div>
            );
          })}
        </div>
      </div>

      {/* Keiretsu warning */}
      {node.keiretsuFlag && (
        <div className="rounded-lg p-3 bg-amber-500/5 border border-amber-500/20">
          <div className="flex items-center gap-2">
            <AlertTriangle className="w-3.5 h-3.5 text-amber-400" />
            <h4 className="text-[10px] font-semibold uppercase text-amber-400">Keiretsu Linkage</h4>
          </div>
          <p className="text-xs text-amber-400/80 mt-1">
            Connected to {node.keiretsuFlag}. Historical cross-shareholding and business ties may compromise governance independence.
          </p>
        </div>
      )}
    </div>
  );
}
