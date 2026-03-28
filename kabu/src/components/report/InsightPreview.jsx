import React from "react";
import { motion, AnimatePresence } from "framer-motion";
import { Lightbulb, Eye } from "lucide-react";

const previewInsights = [
  "Identifying undervalued asset segments...",
  "Cross-referencing executive compensation data...",
  "Analyzing subsidiary ownership structure...",
  "Scanning regulatory filings for disclosures...",
  "Comparing peer margins across APAC region...",
  "Detecting unusual institutional flow patterns...",
  "Evaluating supply chain concentration risk...",
  "Mapping patent filing trends and R&D pipeline...",
];

export default function InsightPreview({ currentStep }) {
  const visibleInsights = previewInsights.slice(0, Math.min(currentStep + 2, previewInsights.length));

  return (
    <div className="rounded-2xl border border-white/[0.06] bg-white/[0.02] p-6">
      <h3 className="text-white font-semibold flex items-center gap-2 mb-5 text-sm">
        <Eye className="w-4 h-4 text-amber-400" />
        Live Analysis Feed
      </h3>

      <div className="space-y-3">
        <AnimatePresence>
          {visibleInsights.map((insight, i) => (
            <motion.div
              key={insight}
              className="flex items-start gap-3 text-sm"
              initial={{ opacity: 0, y: 10, height: 0 }}
              animate={{ opacity: 1, y: 0, height: "auto" }}
              transition={{ duration: 0.4 }}
            >
              <Lightbulb className={`w-4 h-4 shrink-0 mt-0.5 ${
                i === visibleInsights.length - 1 ? "text-amber-400" : "text-gray-600"
              }`} />
              <span className={i === visibleInsights.length - 1 ? "text-gray-300" : "text-gray-500"}>
                {insight}
              </span>
            </motion.div>
          ))}
        </AnimatePresence>
      </div>
    </div>
  );
}