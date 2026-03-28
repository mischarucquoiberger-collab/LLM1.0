import React from "react";
import { motion } from "framer-motion";
import { TrendingUp, TrendingDown, ArrowRight } from "lucide-react";
import { useCircleTransition } from "@/components/CircleTransition";

export default function TrendingCard({ company, index }) {
  const { navigateWithReveal } = useCircleTransition();
  const isPositive = company.change >= 0;

  const handleClick = (e) => {
    navigateWithReveal(
      `/CompanyDetail?ticker=${encodeURIComponent(company.ticker)}&name=${encodeURIComponent(company.name)}&sector=${encodeURIComponent(company.sector)}`,
      e
    );
  };

  return (
    <div onClick={handleClick} className="cursor-pointer">
      <motion.div
        className="group relative p-5 rounded-xl border border-white/[0.04] bg-white/[0.02] hover:bg-white/[0.04] hover:border-white/[0.08] transition-all duration-500 cursor-pointer overflow-hidden"
        initial={{ opacity: 0, y: 20 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ delay: index * 0.05, duration: 0.6, ease: [0.16, 1, 0.3, 1] }}
        whileHover={{ y: -4, scale: 1.01 }}
      >
        <div className="flex items-start justify-between mb-3">
          <div>
            <p className="text-blue-400/80 font-mono text-xs font-medium tracking-wider">{company.ticker}</p>
            <h3 className="text-white font-medium mt-1.5 text-base leading-tight">{company.name}</h3>
          </div>
          <motion.div
            className={`flex items-center gap-1 px-2 py-1 rounded-md text-xs font-medium ${
              isPositive
                ? "bg-emerald-500/10 text-emerald-400"
                : "bg-red-500/10 text-red-400"
            }`}
            whileHover={{ scale: 1.05 }}
          >
            {isPositive ? (
              <TrendingUp className="w-3 h-3" />
            ) : (
              <TrendingDown className="w-3 h-3" />
            )}
            {isPositive ? "+" : ""}{company.change}%
          </motion.div>
        </div>

        <p className="text-gray-600 text-xs mb-3">{company.sector}</p>

        <div className="flex items-center justify-between">
          <span className="text-gray-500 text-sm font-medium">¥{company.price?.toLocaleString()}</span>
          <motion.div 
            className="flex items-center gap-1 text-gray-600 group-hover:text-blue-400 transition-colors text-xs opacity-0 group-hover:opacity-100"
            initial={{ x: -5 }}
            whileHover={{ x: 0 }}
          >
            View
            <ArrowRight className="w-3 h-3" />
          </motion.div>
        </div>
      </motion.div>
    </div>
  );
}