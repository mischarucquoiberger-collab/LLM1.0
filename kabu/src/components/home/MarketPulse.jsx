import React from "react";
import { motion } from "framer-motion";
import { Activity, TrendingUp, TrendingDown } from "lucide-react";

const indices = [
  { name: "Nikkei 225", value: "38,487.24", change: "+1.23%", positive: true },
  { name: "TOPIX", value: "2,680.15", change: "+0.87%", positive: true },
  { name: "JPX-Nikkei 400", value: "21,543.30", change: "-0.14%", positive: false },
  { name: "Mothers", value: "678.42", change: "+2.05%", positive: true },
];

export default function MarketPulse() {
  return (
    <div className="rounded-2xl border border-white/[0.06] bg-white/[0.02] p-6">
      <h3 className="text-white font-semibold flex items-center gap-2 mb-5">
        <Activity className="w-4 h-4 text-amber-400" />
        Market Pulse
      </h3>

      <div className="space-y-4">
        {indices.map((index, i) => (
          <motion.div
            key={index.name}
            className="flex items-center justify-between"
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            transition={{ delay: i * 0.1 }}
          >
            <div>
              <p className="text-white text-sm font-medium">{index.name}</p>
              <p className="text-gray-400 text-sm font-mono mt-0.5">{index.value}</p>
            </div>
            <div
              className={`flex items-center gap-1 text-sm font-medium ${
                index.positive ? "text-emerald-400" : "text-red-400"
              }`}
            >
              {index.positive ? (
                <TrendingUp className="w-3.5 h-3.5" />
              ) : (
                <TrendingDown className="w-3.5 h-3.5" />
              )}
              {index.change}
            </div>
          </motion.div>
        ))}
      </div>
    </div>
  );
}