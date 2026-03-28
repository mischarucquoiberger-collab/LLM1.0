import React from "react";
import { motion } from "framer-motion";
import { FileText, Clock, Star } from "lucide-react";

const recentReports = [
  { company: "Toyota Motor", ticker: "7203", time: "2 min ago", score: 87 },
  { company: "Sony Group", ticker: "6758", time: "15 min ago", score: 92 },
  { company: "SoftBank Group", ticker: "9984", time: "1 hr ago", score: 74 },
  { company: "Keyence Corp", ticker: "6861", time: "2 hrs ago", score: 95 },
  { company: "Nintendo Co", ticker: "7974", time: "3 hrs ago", score: 88 },
];

function getScoreColor(score) {
  if (score >= 90) return "text-emerald-400 bg-emerald-500/10";
  if (score >= 80) return "text-blue-400 bg-blue-500/10";
  if (score >= 70) return "text-amber-400 bg-amber-500/10";
  return "text-red-400 bg-red-500/10";
}

export default function RecentReports() {
  return (
    <div className="rounded-2xl border border-white/[0.06] bg-white/[0.02] overflow-hidden">
      <div className="px-6 py-5 border-b border-white/[0.06] flex items-center justify-between">
        <h3 className="text-white font-semibold flex items-center gap-2">
          <FileText className="w-4 h-4 text-blue-400" />
          Recent Reports
        </h3>
        <span className="text-xs text-gray-500">Live Feed</span>
      </div>

      <div className="divide-y divide-white/[0.04]">
        {recentReports.map((report, i) => (
          <motion.div
            key={report.ticker}
            className="flex items-center justify-between px-6 py-4 hover:bg-white/[0.02] transition-colors cursor-pointer"
            initial={{ opacity: 0, x: -10 }}
            animate={{ opacity: 1, x: 0 }}
            transition={{ delay: i * 0.08 }}
          >
            <div className="flex items-center gap-4">
              <div className="w-8 h-8 rounded-lg bg-blue-500/10 flex items-center justify-center">
                <span className="text-blue-400 font-mono text-xs font-bold">{report.ticker.slice(0, 2)}</span>
              </div>
              <div>
                <p className="text-white text-sm font-medium">{report.company}</p>
                <p className="text-gray-500 text-xs flex items-center gap-1 mt-0.5">
                  <Clock className="w-3 h-3" />
                  {report.time}
                </p>
              </div>
            </div>
            <div className={`flex items-center gap-1.5 px-2.5 py-1 rounded-lg text-sm font-semibold ${getScoreColor(report.score)}`}>
              <Star className="w-3 h-3" />
              {report.score}
            </div>
          </motion.div>
        ))}
      </div>
    </div>
  );
}