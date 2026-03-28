import React, { useState } from "react";
import { motion } from "framer-motion";
import { ArrowLeft, FileText, Building2, Users, Vote, UserCheck } from "lucide-react";
import { Link, useSearchParams, useNavigate } from "react-router-dom";
import { startReport } from "@/api/backend";
import { toast } from "@/components/ui/use-toast";

const FEATURES = [
  {
    key: "research",
    title: "Research Report",
    description: "Comprehensive AI-powered analysis covering financials, market position, and growth outlook.",
    icon: FileText,
    accent: "blue",
    enabled: true,
  },
  {
    key: "realestate",
    title: "Hidden Real Estate Value",
    description: "Uncover undervalued land and property assets hidden on corporate balance sheets.",
    icon: Building2,
    accent: "amber",
    enabled: false,
  },
  {
    key: "directors",
    title: "Director Correlation",
    description: "Map board-level relationships and cross-company directorship networks.",
    icon: Users,
    accent: "purple",
    enabled: true,
    route: "/DirectorMap",  // params appended in handleClick
  },
  {
    key: "director-proposals",
    title: "Director Proposals",
    description: "Analyse director election proposals and their voting approval percentages.",
    icon: UserCheck,
    accent: "teal",
    enabled: false,
  },
  {
    key: "shareholder-voting",
    title: "Shareholder Voting",
    description: "Review shareholder meeting resolutions and voting outcome percentages.",
    icon: Vote,
    accent: "rose",
    enabled: false,
  },
];

const ACCENT = {
  blue: {
    bg: "from-blue-500/20 to-blue-600/10",
    border: "border-blue-500/20",
    text: "text-blue-400",
    hover: "group-hover:border-blue-500/40",
    shadow: "group-hover:shadow-blue-500/10",
  },
  amber: {
    bg: "from-amber-500/20 to-amber-600/10",
    border: "border-amber-500/20",
    text: "text-amber-400",
    hover: "group-hover:border-amber-500/40",
    shadow: "group-hover:shadow-amber-500/10",
  },
  purple: {
    bg: "from-purple-500/20 to-purple-600/10",
    border: "border-purple-500/20",
    text: "text-purple-400",
    hover: "group-hover:border-purple-500/40",
    shadow: "group-hover:shadow-purple-500/10",
  },
  teal: {
    bg: "from-teal-500/20 to-teal-600/10",
    border: "border-teal-500/20",
    text: "text-teal-400",
    hover: "group-hover:border-teal-500/40",
    shadow: "group-hover:shadow-teal-500/10",
  },
  rose: {
    bg: "from-rose-500/20 to-rose-600/10",
    border: "border-rose-500/20",
    text: "text-rose-400",
    hover: "group-hover:border-rose-500/40",
    shadow: "group-hover:shadow-rose-500/10",
  },
};

export default function CompanyDetail() {
  const [params] = useSearchParams();
  const navigate = useNavigate();
  const [isSubmitting, setIsSubmitting] = useState(false);

  const ticker = params.get("ticker") || "";
  const name = params.get("name") || ticker;
  const sector = params.get("sector") || "";

  const handleClick = async (feature) => {
    if (!feature.enabled) {
      toast({ title: "Coming Soon", description: `${feature.title} is not yet available.` });
      return;
    }

    // Direct route (e.g. Director Correlation)
    if (feature.route) {
      const qs = `?ticker=${encodeURIComponent(ticker)}&name=${encodeURIComponent(name)}`;
      navigate(feature.route + qs);
      return;
    }

    // Research Report — use existing flow
    setIsSubmitting(true);
    try {
      const response = await startReport({ stock_code: ticker, company_name: name, mode: "full" });
      const jobId = response?.job_id;
      if (!jobId) throw new Error("Job ID missing in response");
      navigate(
        `/GenerateReport?jobId=${jobId}&ticker=${encodeURIComponent(ticker)}&name=${encodeURIComponent(name)}&mode=full`
      );
    } catch (err) {
      toast({ title: "Error", description: err.message || "Failed to start report", variant: "destructive" });
    } finally {
      setIsSubmitting(false);
    }
  };

  return (
    <div className="min-h-screen bg-[#090d1a] text-white">
      {/* Header */}
      <div className="max-w-5xl mx-auto px-4 sm:px-6 pt-8 sm:pt-10 pb-6">
        <Link
          to="/"
          state={{ openContent: true }}
          className="inline-flex items-center gap-2 text-sm text-gray-500 hover:text-gray-300 transition-colors mb-8"
        >
          <ArrowLeft className="w-4 h-4" />
          Back
        </Link>

        <motion.div
          initial={{ opacity: 0, y: 12 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.5, ease: [0.16, 1, 0.3, 1] }}
        >
          <h1 className="text-2xl sm:text-3xl font-bold tracking-tight truncate">{name}</h1>
          <div className="flex items-center gap-3 mt-2">
            <span className="text-blue-400 font-mono text-sm">{ticker}</span>
            {sector && (
              <span className="px-2.5 py-0.5 rounded-full bg-white/[0.06] border border-white/[0.08] text-xs text-gray-400">
                {sector}
              </span>
            )}
          </div>
        </motion.div>
      </div>

      {/* Feature Cards */}
      <div className="max-w-5xl mx-auto px-4 sm:px-6 pb-16 sm:pb-20">
        <div className="grid grid-cols-1 md:grid-cols-3 gap-3 sm:gap-5">
          {FEATURES.map((feature, i) => {
            const colors = ACCENT[feature.accent];
            const Icon = feature.icon;
            return (
              <motion.button
                key={feature.key}
                onClick={() => handleClick(feature)}
                disabled={isSubmitting}
                initial={{ opacity: 0, y: 20 }}
                animate={{ opacity: 1, y: 0 }}
                transition={{ delay: 0.15 + i * 0.1, duration: 0.5, ease: [0.16, 1, 0.3, 1] }}
                className={`group relative text-left p-6 rounded-2xl bg-white/[0.03] border border-white/[0.06] ${feature.enabled ? `${colors.hover} ${colors.shadow} hover:bg-white/[0.05] cursor-pointer` : "opacity-50 cursor-not-allowed"} transition-all duration-500 disabled:opacity-60 disabled:cursor-wait`}
              >
                <div
                  className={`w-12 h-12 rounded-xl bg-gradient-to-br ${colors.bg} border ${colors.border} flex items-center justify-center mb-5`}
                >
                  <Icon className={`w-6 h-6 ${colors.text}`} />
                </div>
                <h3 className="text-lg font-semibold text-white mb-2">{feature.title}</h3>
                <p className="text-sm text-gray-500 leading-relaxed">{feature.description}</p>
                {!feature.enabled && (
                  <span className="absolute top-4 right-4 px-2.5 py-1 rounded-full bg-white/[0.06] border border-white/[0.06] text-[10px] uppercase tracking-wider text-gray-500 font-medium">
                    Coming Soon
                  </span>
                )}
              </motion.button>
            );
          })}
        </div>
      </div>
    </div>
  );
}
